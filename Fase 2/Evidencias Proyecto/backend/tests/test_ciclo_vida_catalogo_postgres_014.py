"""T2 (Feature 014): estructura, instalacion limpia y concurrencia - gated PostgreSQL 16.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs ni el
DDL por esquema, asi que lo que la Feature 014 exige del esquema y de la
coordinacion de bloqueos solo se acredita contra PostgreSQL 16 real:

  * **Instalacion limpia** (`01_` + `02_`): 22 tablas en `control` y 19 por
    tenant, columna `activo` en producto/categoria, las dos tablas de historial
    en control y en cada tenant, historiales vacios, semilla de productos y
    categorias activos y version objetivo `014.1` (AC-13/AC-14);
  * **Paridad estructural** control/tenant de las dos tablas de historial;
  * **Escenarios concurrentes** AC-6 (entrada de stock frente a baja de
    producto), AC-16 (baja de categoria frente a alta/reactivacion de
    producto) y rollback de una operacion rechazada (T10). Cada carrera usa
    **dos sesiones reales** sobre conexiones distintas (motor con `NullPool`) y
    una barrera para arrancar a la vez; el resultado admitido es que una
    operacion se serializa y la otra se rechaza. La invariante se verifica
    **despues** de las dos transacciones: nunca un producto inactivo con saldo
    positivo en `stock_sede` ni una categoria inactiva con producto activo.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_ciclo_vida_catalogo_postgres_014.py

Sin `POSTGRES_TEST_URL` los tests se **saltan** con una razon clara y la suite
local (SQLite) sigue verde. La URL apunta a una base de mantenimiento donde el
test crea y destruye una base temporal propia; nunca toca `apt_erp`. NO se anade
ninguna dependencia: `psycopg2` ya esta en `requirements.txt`.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from app.core.config import VERSION_ESQUEMA_OBJETIVO

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA_SQL = RAIZ / "database" / "01_esquema.sql"
SEMILLA_SQL = RAIZ / "database" / "02_datos_semilla.sql"

#: Las 22 tablas de `control` tras la 014: las 20 vigentes (017) mas los dos
#: historiales de transicion del catalogo (16.ª y 17.ª entidades de dominio).
TABLAS_CONTROL_014 = {
    "institucion",
    "sede",
    "departamento",
    "rol",
    "usuario",
    "departamento_encargado",
    "categoria",
    "producto",
    "inventario",
    "stock_sede",
    "movimiento_inventario",
    "prioridad",
    "estado_ticket",
    "ticket",
    "detalle_ticket",
    "historial_transicion_ticket",
    "historial_transicion_producto",
    "historial_transicion_categoria",
    "funcion_institucion",
    "mapa_usuario_esquema",
    "version_esquema",
    "registro_motivo_constancia",
}

#: Las tres estructuras auxiliares que viven solo en `control`; el tenant
#: replica las 19 tablas de negocio.
AUXILIARES_CONTROL = {
    "funcion_institucion",
    "mapa_usuario_esquema",
    "registro_motivo_constancia",
}
TABLAS_TENANT_014 = TABLAS_CONTROL_014 - AUXILIARES_CONTROL

TABLA_HISTORIAL_PRODUCTO = "historial_transicion_producto"
TABLA_HISTORIAL_CATEGORIA = "historial_transicion_categoria"
VERSION_014 = "014.1"


# ---------------------------------------------------------------------------
# Conexion y utilidades
# ---------------------------------------------------------------------------


def _sin_driver(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _url_con_base(url: str, nombre: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))


@contextmanager
def _base_temporal():
    """Crea una base PostgreSQL efimera y la destruye al salir (nunca `apt_erp`)."""
    dsn = _sin_driver(_POSTGRES_TEST_URL or "")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_014_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    try:
        conexion = psycopg2.connect(_url_con_base(dsn, nombre))
        try:
            yield conexion
        finally:
            conexion.close()
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _ejecutar(conexion, sql: str, params=None):
    with conexion.cursor() as cur:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        filas = cur.fetchall() if cur.description else []
    conexion.commit()
    return filas


def _un_escalar(conexion, sql: str, params=None):
    return _ejecutar(conexion, sql, params)[0][0]


def _ejecutar_script(conexion, ruta: Path) -> None:
    _ejecutar(conexion, ruta.read_text(encoding="utf-8"))


def _instalar(conexion) -> None:
    _ejecutar_script(conexion, ESQUEMA_SQL)
    _ejecutar_script(conexion, SEMILLA_SQL)


def _tablas_del_esquema(conexion, esquema: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (esquema,),
    )
    return {fila[0] for fila in filas}


def _columnas_de(conexion, esquema: str, tabla: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (esquema, tabla),
    )
    return {fila[0] for fila in filas}


def _esquema_de_institucion(institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _instituciones(conexion) -> list[str]:
    return [
        fila[0]
        for fila in _ejecutar(
            conexion,
            "SELECT institucion_id FROM control.institucion ORDER BY institucion_id",
        )
    ]


def _version_de(conexion, esquema: str) -> str:
    return _un_escalar(conexion, f'SELECT version FROM "{esquema}".version_esquema')


def _conteo(conexion, esquema: str, tabla: str) -> int:
    return _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}"."{tabla}"')


def _claves_foraneas(conexion, esquema: str, tabla: str) -> set[tuple]:
    """`(columna, tabla_referida)` de las FK reales declaradas en el esquema."""
    filas = _ejecutar(
        conexion,
        """
        SELECT kcu.column_name, ccu.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name
         AND kcu.constraint_schema = tc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.constraint_schema = tc.constraint_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        """,
        (esquema, tabla),
    )
    return {(fila[0], fila[1]) for fila in filas}


# ---------------------------------------------------------------------------
# AC-14: token de version del codigo
# ---------------------------------------------------------------------------


def test_el_codigo_apunta_a_la_version_014_1():
    """AC-14: `VERSION_ESQUEMA_OBJETIVO` es `014.1` (lo cambia T5)."""
    assert VERSION_ESQUEMA_OBJETIVO == VERSION_014, VERSION_ESQUEMA_OBJETIVO


# ---------------------------------------------------------------------------
# AC-13/AC-14: instalacion limpia
# ---------------------------------------------------------------------------


def test_instalacion_limpia_crea_22_tablas_en_control_y_19_por_tenant():
    """AC-14: los conteos suben a 22/19 con exactamente las tablas esperadas."""
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert _tablas_del_esquema(conexion, "control") == TABLAS_CONTROL_014
        assert len(TABLAS_CONTROL_014) == 22

        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _tablas_del_esquema(conexion, esquema) == TABLAS_TENANT_014
            assert len(TABLAS_TENANT_014) == 19


def test_instalacion_limpia_crea_estado_e_historiales_en_control_y_tenants():
    """AC-14: `activo` y las dos tablas de historial existen en todos los esquemas."""
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert {"activo"} <= _columnas_de(conexion, "control", "producto")
        assert {"activo"} <= _columnas_de(conexion, "control", "categoria")
        for tabla in (TABLA_HISTORIAL_PRODUCTO, TABLA_HISTORIAL_CATEGORIA):
            assert tabla in _tablas_del_esquema(conexion, "control")
            assert _conteo(conexion, "control", tabla) == 0

        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert {"activo"} <= _columnas_de(conexion, esquema, "producto"), esquema
            assert {"activo"} <= _columnas_de(conexion, esquema, "categoria"), esquema
            for tabla in (TABLA_HISTORIAL_PRODUCTO, TABLA_HISTORIAL_CATEGORIA):
                assert tabla in _tablas_del_esquema(conexion, esquema), esquema
                assert _conteo(conexion, esquema, tabla) == 0, (esquema, tabla)
            assert _version_de(conexion, esquema) == VERSION_014, esquema
        assert _version_de(conexion, "control") == VERSION_014


def test_semilla_deja_productos_y_categorias_activos_en_cada_tenant():
    """AC-13/AC-14: la semilla inicializa todo el catalogo como activo.

    En **ningun** tenant puede quedar producto o categoria fuera del estado
    activo. La semilla QA solo distribuye catalogo a INST-001 e INST-002 (14
    productos y 10 categorias en total, segun `TOTALES_TENANT`); INST-003 e
    INST-004 nacen legitimamente sin catalogo, de modo que alli la verificacion
    es vacua y no exige filas. T4 conserva esa distribucion aprobada en vez de
    fabricar catalogo para completar el conteo.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)

        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _un_escalar(
                conexion,
                f'SELECT count(*) FROM "{esquema}".producto WHERE activo IS NOT TRUE',
            ) == 0, esquema
            assert _un_escalar(
                conexion,
                f'SELECT count(*) FROM "{esquema}".categoria WHERE activo IS NOT TRUE',
            ) == 0, esquema
            if institucion_id in {"INST-001", "INST-002"}:
                assert _conteo(conexion, esquema, "producto") > 0, esquema
                assert _conteo(conexion, esquema, "categoria") > 0, esquema


def test_paridad_estructural_de_los_historiales_entre_control_y_tenant():
    """AC-14/stack §2: ambas tablas tienen la misma forma y FK en control/tenant."""
    with _base_temporal() as conexion:
        _instalar(conexion)
        instituciones = _instituciones(conexion)
        assert instituciones, "la semilla debe crear al menos un tenant"

        for tabla, recurso in (
            (TABLA_HISTORIAL_PRODUCTO, "producto"),
            (TABLA_HISTORIAL_CATEGORIA, "categoria"),
        ):
            columnas_control = _columnas_de(conexion, "control", tabla)
            fks_control = _claves_foraneas(conexion, "control", tabla)
            assert any(destino == recurso for _, destino in fks_control), tabla
            assert any(destino == "usuario" for _, destino in fks_control), tabla
            for institucion_id in instituciones:
                esquema = _esquema_de_institucion(institucion_id)
                assert _columnas_de(conexion, esquema, tabla) == columnas_control, (
                    esquema,
                    tabla,
                )
                assert _claves_foraneas(conexion, esquema, tabla) == fks_control, (
                    esquema,
                    tabla,
                )


# ---------------------------------------------------------------------------
# AC-6/AC-16: escenarios concurrentes reales (T10)
# ---------------------------------------------------------------------------

#: Tenant de la semilla con catalogo y usuarios completos (ver T5).
INSTITUCION_CONCURRENCIA = "INST-001"
#: Cantidad de anillos por carrera: cubre ambos ordenes de serializacion.
REPETICIONES = 4
#: `application_name` de las conexiones de las carreras, para observar solo sus locks.
_APP_CONCURRENCIA = "compustock_014_race"


def _exigir_estructura_concurrencia(conexion) -> None:
    """El escenario concurrente necesita columnas y tablas de la 014."""
    for esquema in ["control"] + [
        _esquema_de_institucion(institucion_id)
        for institucion_id in _instituciones(conexion)
    ]:
        faltantes = set()
        if "activo" not in _columnas_de(conexion, esquema, "producto"):
            faltantes.add("producto.activo")
        if "activo" not in _columnas_de(conexion, esquema, "categoria"):
            faltantes.add("categoria.activo")
        for tabla in (TABLA_HISTORIAL_PRODUCTO, TABLA_HISTORIAL_CATEGORIA):
            if tabla not in _tablas_del_esquema(conexion, esquema):
                faltantes.add(tabla)
        assert not faltantes, (esquema, sorted(faltantes))


def _motor_de(conexion):
    """Motor SQLAlchemy sobre la base temporal, **sin pool** (dos conexiones)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    nombre_base = conexion.get_dsn_parameters()["dbname"]
    url = _url_con_base(_sin_driver(_POSTGRES_TEST_URL or ""), nombre_base)
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(
        url,
        poolclass=NullPool,
        future=True,
        connect_args={"application_name": _APP_CONCURRENCIA},
    )


@contextmanager
def _sesion_tenant(motor, esquema):
    """Sesion de negocio ligada al esquema del tenant (mismo cableado que `get_db`)."""
    from app.db.database import crear_sesion_esquema

    db = crear_sesion_esquema(esquema, motor=motor)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def _mundo_concurrente(conexion):
    """Esquema, motor, sede y actor Administrador **persistido** del tenant."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.models import Rol, Sede, Usuario
    from app.services.auth_service import IdentidadAutenticada

    esquema = _esquema_de_institucion(INSTITUCION_CONCURRENCIA)
    motor = _motor_de(conexion)
    try:
        with _sesion_tenant(motor, esquema) as db:
            actor = db.execute(
                select(Usuario)
                .options(joinedload(Usuario.rol))
                .join(Usuario.rol)
                .where(Rol.nombre_rol == "Administrador")
                .order_by(Usuario.usuario_id)
                .limit(1)
            ).scalars().first()
            assert actor is not None, "la semilla debe tener un Administrador en INST-001"
            sede_id = db.execute(
                select(Sede.sede_id)
                .where(Sede.institucion_id == INSTITUCION_CONCURRENCIA)
                .order_by(Sede.sede_id)
                .limit(1)
            ).scalar_one_or_none()
            assert sede_id is not None, "la semilla debe tener una sede en INST-001"
            actor_id = actor.usuario_id
            actor_rol_id = actor.rol_id
            actor_departamento_id = actor.departamento_id
            actor_correo = actor.correo

        # Identidad suelta con ids persistidos: la FK de historial exige un
        # usuario real, y el ambito se resuelve por su departamento.
        usuario = Usuario(
            usuario_id=actor_id,
            nombre="QA",
            apellido="Concurrencia014",
            correo=actor_correo,
            departamento_id=actor_departamento_id,
            rol_id=actor_rol_id,
        )
        usuario.rol = Rol(nombre_rol="Administrador")
        yield {
            "esquema": esquema,
            "motor": motor,
            "sede_id": sede_id,
            "institucion_id": INSTITUCION_CONCURRENCIA,
            "usuario_id": actor_id,
            "identidad": IdentidadAutenticada(usuario=usuario, sub="test-014"),
        }
    finally:
        motor.dispose()


def _crear_categoria(motor, mundo, nombre: str) -> int:
    from app.models import Categoria

    with _sesion_tenant(motor, mundo["esquema"]) as db:
        categoria = Categoria(
            nombre_cat=nombre,
            descripcion_cat="Escenario concurrente 014",
            institucion_id=mundo["institucion_id"],
            activo=True,
        )
        db.add(categoria)
        db.commit()
        db.refresh(categoria)
        return categoria.categoria_id


def _crear_producto(
    motor, mundo, nombre: str, categoria_id: int, *, activo: bool = True
) -> int:
    from app.models import Producto

    with _sesion_tenant(motor, mundo["esquema"]) as db:
        producto = Producto(
            nombre=nombre,
            descripcion="Escenario concurrente 014",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=categoria_id,
            institucion_id=mundo["institucion_id"],
            activo=activo,
        )
        db.add(producto)
        db.commit()
        db.refresh(producto)
        return producto.producto_id


def _crear_stock(motor, mundo, producto_id: int, cantidad: int) -> int:
    from app.models import StockSede

    with _sesion_tenant(motor, mundo["esquema"]) as db:
        fila = StockSede(
            sede_id=mundo["sede_id"],
            producto_id=producto_id,
            institucion_id=mundo["institucion_id"],
            stock_actual=cantidad,
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.stock_sede_id


def _estado_producto(motor, esquema: str, producto_id: int, stock_sede_id: int) -> dict:
    """Estado persistido posterior a la carrera, leido en una sesion fresca."""
    from sqlalchemy import func, select

    from app.models import (
        HistorialTransicionProducto,
        MovimientoInventario,
        Producto,
        StockSede,
    )

    with _sesion_tenant(motor, esquema) as db:
        producto = db.get(Producto, producto_id)
        stock = db.execute(
            select(StockSede.stock_actual).where(
                StockSede.stock_sede_id == stock_sede_id
            )
        ).scalar_one()
        historial = db.execute(
            select(func.count())
            .select_from(HistorialTransicionProducto)
            .where(HistorialTransicionProducto.producto_id == producto_id)
        ).scalar_one()
        movimientos = db.execute(
            select(func.count())
            .select_from(MovimientoInventario)
            .where(MovimientoInventario.stock_sede_id == stock_sede_id)
        ).scalar_one()
        return {
            "activo": producto.activo,
            "stock": stock,
            "historial": historial,
            "movimientos": movimientos,
        }


def _estado_categoria(motor, esquema: str, categoria_id: int) -> dict:
    """Estado persistido de la categoria y de su catalogo tras la carrera."""
    from sqlalchemy import func, select

    from app.models import (
        Categoria,
        HistorialTransicionCategoria,
        Producto,
    )

    with _sesion_tenant(motor, esquema) as db:
        categoria = db.get(Categoria, categoria_id)
        productos = db.execute(
            select(Producto.activo).where(Producto.categoria_id == categoria_id)
        ).scalars().all()
        historial = db.execute(
            select(func.count())
            .select_from(HistorialTransicionCategoria)
            .where(HistorialTransicionCategoria.categoria_id == categoria_id)
        ).scalar_one()
        return {
            "activa": categoria.activo,
            "productos": list(productos),
            "historial": historial,
        }


def _correr_en_paralelo(primera, segunda) -> dict[str, str]:
    """Arranca dos sesiones a la vez con una barrera y devuelve sus resultados."""
    barrera = threading.Barrier(2)
    resultados: dict[str, str] = {}
    candado = threading.Lock()

    def _ejecutar(nombre: str, tarea) -> None:
        try:
            barrera.wait(timeout=15)
            resultado = tarea()
        except Exception as exc:  # pragma: no cover - diagnostico de carrera
            resultado = f"error:{type(exc).__name__}:{exc}"
        with candado:
            resultados[nombre] = resultado

    hilos = [
        threading.Thread(target=_ejecutar, args=("primera", primera)),
        threading.Thread(target=_ejecutar, args=("segunda", segunda)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=30)

    assert not any(hilo.is_alive() for hilo in hilos), (
        "una carrera quedo colgada: posible deadlock o bloqueo sin liberar"
    )
    assert set(resultados) == {"primera", "segunda"}, resultados
    return resultados


class _Turno:
    """Handshake determinista entre la sesion poseedora del lock y la contendiente.

    La sesion poseedora adquiere el lock, **confirma** la posesion con un
    `threading.Event` y solo entonces la contendiente emite su peticion. Asi el
    orden no depende del planificador: un fallo en la espera es un lock ausente
    real, no una carrera de temporizacion.
    """

    def __init__(self, nombre_base: str) -> None:
        self.nombre_base = nombre_base
        self._posesion = threading.Event()

    def poseer(self, db, entidad, columna, valor: int) -> None:
        """Retiene el lock, anuncia la posesion y espera a la contendiente."""
        _retener_lock(db, entidad, columna, valor)
        self._posesion.set()
        # La otra sesion ya puede pedir el mismo lock; se espera a que lo haga
        # para acreditar que la serializacion ocurre de verdad.
        _esperar_bloqueo(self.nombre_base)

    def esperar_posesion(self) -> None:
        """Bloquea la sesion contendiente hasta que la poseedora confirme el lock."""
        if not self._posesion.wait(timeout=15):
            raise TimeoutError(
                "la sesion poseedora del lock no confirmo su adquisicion en 15 s; "
                "el escenario no pudo ordenar el intercalado"
            )


def _tarea_movimiento(
    motor,
    mundo,
    stock_sede_id: int,
    cantidad: int,
    *,
    producto_id: int | None = None,
    turno: _Turno | None = None,
    poseedor: bool = False,
):
    """Entrada de stock nueva sobre `stock_sede` (sesion propia).

    Con `turno` y `poseedor=True`, retiene primero el lock del producto y
    confirma la posesion antes de que la otra sesion compita: fuerza el
    resultado "el movimiento gana".
    """
    from app.db.database import crear_sesion_esquema
    from app.schemas.inventario_schema import MovimientoCrear
    from app.services import inventario_service

    def _tarea() -> str:
        db = crear_sesion_esquema(mundo["esquema"], motor=motor)
        try:
            if turno is not None:
                if poseedor:
                    from app.models import Producto

                    turno.poseer(db, Producto, Producto.producto_id, producto_id)
                else:
                    turno.esperar_posesion()
            inventario_service.registrar_movimiento(
                db,
                MovimientoCrear(
                    tipo_movimiento="ENTRADA",
                    cantidad=cantidad,
                    observacion="Carrera AC-6",
                    stock_sede_id=stock_sede_id,
                ),
                mundo["identidad"],
            )
            return "ok"
        except Exception as exc:
            db.rollback()
            return str(getattr(exc, "status_code", type(exc).__name__))
        finally:
            db.close()

    return _tarea


def _tarea_baja_producto(
    motor,
    mundo,
    producto_id: int,
    *,
    turno: _Turno | None = None,
    poseedor: bool = False,
):
    """Baja de producto (sesion propia).

    Con `turno` y `poseedor=True`, retiene primero el lock del producto y
    confirma la posesion: fuerza el resultado "la baja gana".
    """
    from app.schemas.producto_schema import TransicionCatalogo

    from app.services import inventario_service

    def _tarea() -> str:
        from app.db.database import crear_sesion_esquema

        db = crear_sesion_esquema(mundo["esquema"], motor=motor)
        try:
            if turno is not None:
                if poseedor:
                    from app.models import Producto

                    turno.poseer(db, Producto, Producto.producto_id, producto_id)
                else:
                    turno.esperar_posesion()
            inventario_service.transicionar_producto(
                db,
                producto_id,
                TransicionCatalogo(activo=False, motivo="Carrera AC-6"),
                mundo["identidad"],
            )
            return "ok"
        except Exception as exc:
            db.rollback()
            return str(getattr(exc, "status_code", type(exc).__name__))
        finally:
            db.close()

    return _tarea


def _tarea_baja_categoria(
    motor,
    mundo,
    categoria_id: int,
    *,
    turno: _Turno | None = None,
    poseedor: bool = False,
):
    """Baja de categoria (sesion propia).

    Con `turno` y `poseedor=True`, retiene primero el lock de la categoria y
    confirma la posesion: fuerza el resultado "la baja gana".
    """
    from app.schemas.producto_schema import TransicionCatalogo

    from app.services import inventario_service

    def _tarea() -> str:
        from app.db.database import crear_sesion_esquema

        db = crear_sesion_esquema(mundo["esquema"], motor=motor)
        try:
            if turno is not None:
                if poseedor:
                    from app.models import Categoria

                    turno.poseer(
                        db, Categoria, Categoria.categoria_id, categoria_id
                    )
                else:
                    turno.esperar_posesion()
            inventario_service.transicionar_categoria(
                db,
                categoria_id,
                TransicionCatalogo(activo=False, motivo="Carrera AC-16"),
                mundo["identidad"],
            )
            return "ok"
        except Exception as exc:
            db.rollback()
            return str(getattr(exc, "status_code", type(exc).__name__))
        finally:
            db.close()

    return _tarea


def _tarea_alta_producto(
    motor,
    mundo,
    categoria_id: int,
    nombre: str,
    *,
    turno: _Turno | None = None,
    poseedor: bool = False,
):
    """Alta de producto (sesion propia).

    Con `turno` y `poseedor=True`, retiene primero el lock de la categoria y
    confirma la posesion: fuerza el resultado "el alta gana".
    """
    from app.schemas.producto_schema import ProductoCrear

    from app.services import inventario_service

    def _tarea() -> str:
        from app.db.database import crear_sesion_esquema

        db = crear_sesion_esquema(mundo["esquema"], motor=motor)
        try:
            if turno is not None:
                if poseedor:
                    from app.models import Categoria

                    turno.poseer(
                        db, Categoria, Categoria.categoria_id, categoria_id
                    )
                else:
                    turno.esperar_posesion()
            inventario_service.crear_producto(
                db,
                ProductoCrear(
                    nombre=nombre,
                    descripcion="Carrera AC-16",
                    unidad_medida="UNIDAD",
                    stock_minimo=0,
                    categoria_id=categoria_id,
                ),
                mundo["identidad"],
            )
            return "ok"
        except Exception as exc:
            db.rollback()
            return str(getattr(exc, "status_code", type(exc).__name__))
        finally:
            db.close()

    return _tarea


def _tarea_reactivacion_producto(
    motor,
    mundo,
    producto_id: int,
    *,
    categoria_id: int,
    turno: _Turno | None = None,
    poseedor: bool = False,
):
    """Reactivacion de producto (sesion propia).

    Con `turno` y `poseedor=True`, retiene primero el lock de la categoria (el
    orden del servicio: categoria -> producto) y confirma la posesion: fuerza el
    resultado "la reactivacion gana".
    """
    from app.schemas.producto_schema import TransicionCatalogo

    from app.services import inventario_service

    def _tarea() -> str:
        from app.db.database import crear_sesion_esquema

        db = crear_sesion_esquema(mundo["esquema"], motor=motor)
        try:
            if turno is not None:
                if poseedor:
                    from app.models import Categoria

                    turno.poseer(
                        db, Categoria, Categoria.categoria_id, categoria_id
                    )
                else:
                    turno.esperar_posesion()
            inventario_service.transicionar_producto(
                db,
                producto_id,
                TransicionCatalogo(activo=True, motivo="Carrera AC-16"),
                mundo["identidad"],
            )
            return "ok"
        except Exception as exc:
            db.rollback()
            return str(getattr(exc, "status_code", type(exc).__name__))
        finally:
            db.close()

    return _tarea


def test_escenario_concurrente_baja_de_producto_frente_a_entrada_de_stock_ac_6():
    """AC-6: el movimiento y la baja se serializan o una se rechaza (PG 16).

    Dos sesiones reales arrancan a la vez sobre el mismo producto. La mitad de
    los anillos retiene el lock del producto en el movimiento y la otra mitad en
    la baja, de modo que se ejercitan **ambos** resultados de la serializacion:

    * el movimiento confirma el saldo y la baja responde **409**; o
    * la baja confirma el retiro (saldo cero) y el movimiento responde **409**
      por producto inactivo.

    Nunca ambos confirman, y nunca queda un producto inactivo con saldo
    positivo ni auditoria de un movimiento rechazado.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)
        _exigir_estructura_concurrencia(conexion)

        with _mundo_concurrente(conexion) as mundo:
            nombre_base = conexion.get_dsn_parameters()["dbname"]
            categoria_id = _crear_categoria(
                mundo["motor"], mundo, "Carrera AC-6"
            )
            for anillo in range(REPETICIONES):
                producto_id = _crear_producto(
                    mundo["motor"], mundo, f"AC-6 anillo {anillo}", categoria_id
                )
                stock_sede_id = _crear_stock(
                    mundo["motor"], mundo, producto_id, 0
                )

                # Anillos pares: el movimiento retiene el lock del producto y
                # gana la carrera. Impares: lo retiene la baja. La posesion se
                # confirma antes de lanzar la contendiente, sin depender del
                # planificador.
                movimiento_primero = anillo % 2 == 0
                turno = _Turno(nombre_base)
                resultados = _correr_en_paralelo(
                    _tarea_movimiento(
                        mundo["motor"],
                        mundo,
                        stock_sede_id,
                        25,
                        producto_id=producto_id if movimiento_primero else None,
                        turno=turno,
                        poseedor=movimiento_primero,
                    ),
                    _tarea_baja_producto(
                        mundo["motor"],
                        mundo,
                        producto_id,
                        turno=turno,
                        poseedor=not movimiento_primero,
                    ),
                )
                esperado = (
                    {"primera": "ok", "segunda": "409"}
                    if movimiento_primero
                    else {"primera": "409", "segunda": "ok"}
                )
                assert resultados == esperado, (anillo, resultados)

                estado = _estado_producto(
                    mundo["motor"], mundo["esquema"], producto_id, stock_sede_id
                )
                assert not (estado["activo"] is False and estado["stock"] > 0), (
                    anillo,
                    estado,
                )
                if movimiento_primero:
                    # El movimiento gano: producto activo con su saldo y sin
                    # historial de baja; la baja rechazada no dejo rastro.
                    assert estado == {
                        "activo": True,
                        "stock": 25,
                        "historial": 0,
                        "movimientos": 1,
                    }, (anillo, estado)
                else:
                    # La baja gano: saldo intacto, sin auditoria ni saldo nuevo.
                    assert estado == {
                        "activo": False,
                        "stock": 0,
                        "historial": 1,
                        "movimientos": 0,
                    }, (anillo, estado)


def test_escenario_concurrente_baja_de_categoria_frente_a_alta_de_producto_ac_16():
    """AC-16: baja de categoria y **alta** de producto se serializan (PG 16).

    Ambas rutas bloquean primero la categoria. Si la baja gana, el alta responde
    **409** sin fila; si el alta gana, la baja responde **409**. Nunca persiste
    una categoria inactiva con un producto activo.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)
        _exigir_estructura_concurrencia(conexion)

        with _mundo_concurrente(conexion) as mundo:
            nombre_base = conexion.get_dsn_parameters()["dbname"]
            for anillo in range(REPETICIONES):
                categoria_id = _crear_categoria(
                    mundo["motor"], mundo, f"Carrera AC-16 alta {anillo}"
                )

                # Anillos pares: el alta retiene la categoria y gana; impares:
                # la baja la retiene. La posesion se confirma antes de lanzar la
                # contendiente.
                alta_primero = anillo % 2 == 0
                turno = _Turno(nombre_base)
                resultados = _correr_en_paralelo(
                    _tarea_baja_categoria(
                        mundo["motor"],
                        mundo,
                        categoria_id,
                        turno=turno,
                        poseedor=not alta_primero,
                    ),
                    _tarea_alta_producto(
                        mundo["motor"],
                        mundo,
                        categoria_id,
                        f"Alta concurrente {anillo}",
                        turno=turno,
                        poseedor=alta_primero,
                    ),
                )
                esperado = (
                    {"primera": "409", "segunda": "ok"}
                    if alta_primero
                    else {"primera": "ok", "segunda": "409"}
                )
                assert resultados == esperado, (anillo, resultados)

                estado = _estado_categoria(
                    mundo["motor"], mundo["esquema"], categoria_id
                )
                assert not (
                    estado["activa"] is False
                    and any(estado["productos"])
                ), (anillo, estado)
                if alta_primero:
                    # El alta gano: la categoria sigue activa con su producto y
                    # la baja rechazada no dejo historial.
                    assert estado == {
                        "activa": True,
                        "productos": [True],
                        "historial": 0,
                    }, (anillo, estado)
                else:
                    # La baja gano: el alta no dejo producto ni historial ajeno.
                    assert estado == {
                        "activa": False,
                        "productos": [],
                        "historial": 1,
                    }, (anillo, estado)


def test_escenario_concurrente_baja_de_categoria_frente_a_reactivacion_ac_16():
    """AC-16: baja de categoria y **reactivacion** de producto se serializan.

    La reactivacion bloquea categoria y luego producto (mismo orden que la
    baja). Si la baja gana, la reactivacion responde **409**; si la
    reactivacion gana, la baja responde **409**. La invariante
    categoria inactiva + producto activo no puede persistir.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)
        _exigir_estructura_concurrencia(conexion)

        with _mundo_concurrente(conexion) as mundo:
            nombre_base = conexion.get_dsn_parameters()["dbname"]
            for anillo in range(REPETICIONES):
                categoria_id = _crear_categoria(
                    mundo["motor"], mundo, f"Carrera AC-16 reactivacion {anillo}"
                )
                producto_id = _crear_producto(
                    mundo["motor"],
                    mundo,
                    f"Reactivacion concurrente {anillo}",
                    categoria_id,
                    activo=False,
                )

                # Anillos pares: la reactivacion retiene la categoria y gana;
                # impares: la baja la retiene. La posesion se confirma antes de
                # lanzar la contendiente.
                reactivacion_primero = anillo % 2 == 0
                turno = _Turno(nombre_base)
                resultados = _correr_en_paralelo(
                    _tarea_baja_categoria(
                        mundo["motor"],
                        mundo,
                        categoria_id,
                        turno=turno,
                        poseedor=not reactivacion_primero,
                    ),
                    _tarea_reactivacion_producto(
                        mundo["motor"],
                        mundo,
                        producto_id,
                        categoria_id=categoria_id,
                        turno=turno,
                        poseedor=reactivacion_primero,
                    ),
                )
                esperado = (
                    {"primera": "409", "segunda": "ok"}
                    if reactivacion_primero
                    else {"primera": "ok", "segunda": "409"}
                )
                assert resultados == esperado, (anillo, resultados)

                estado = _estado_categoria(
                    mundo["motor"], mundo["esquema"], categoria_id
                )
                assert not (
                    estado["activa"] is False
                    and any(estado["productos"])
                ), (anillo, estado)
                if reactivacion_primero:
                    # La reactivacion gano: producto activo bajo categoria activa.
                    assert estado == {
                        "activa": True,
                        "productos": [True],
                        "historial": 0,
                    }, (anillo, estado)
                else:
                    # La baja gano: el producto sigue retirado.
                    assert estado == {
                        "activa": False,
                        "productos": [False],
                        "historial": 1,
                    }, (anillo, estado)


def _esperar_bloqueo(nombre_base: str, timeout: float = 10.0) -> None:
    """Espera a que exista una sesion esperando un `Lock` en la base temporal."""
    dsn = _sin_driver(_POSTGRES_TEST_URL or "")
    observador = psycopg2.connect(_url_con_base(dsn, nombre_base))
    observador.autocommit = True
    try:
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            with observador.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = %s AND wait_event_type = 'Lock' "
                    "AND application_name = %s",
                    (nombre_base, _APP_CONCURRENCIA),
                )
                if cur.fetchone()[0] >= 1:
                    return
            time.sleep(0.05)
    finally:
        observador.close()
    raise TimeoutError(
        "ninguna sesion contendiente quedo esperando el lock en "
        f"{timeout:.0f} s (application_name={_APP_CONCURRENCIA}); el escenario "
        "confirma la posesion antes de lanzar la contendiente, asi que esto "
        "significa un lock ausente real en el servicio, no una carrera de "
        "temporizacion"
    )


def _retener_lock(db, entidad, columna, valor: int) -> None:
    """Toma el lock de la fila en esta transaccion (sin esperar a nadie).

    La confirmacion de la posesion y la espera de la contendiente las orquesta
    `_Turno`, de modo que el orden sea determinista.
    """
    from sqlalchemy import select

    db.execute(
        select(entidad).where(columna == valor).with_for_update()
    ).scalar_one()


def test_rollback_de_una_entrada_no_confirmada_deja_la_baja_proceder():
    """Rollback/AC-6: el trabajo no confirmado no es saldo operativo.

    Una sesion bloquea el producto y deja `stock_sede` en 5 **sin confirmar**.
    La baja concurrente espera el lock del producto. Al revertir la primera
    sesion, la baja ve el saldo real (0), procede y deja exactamente una fila de
    historial; no queda rastro del movimiento revertido.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)
        _exigir_estructura_concurrencia(conexion)

        with _mundo_concurrente(conexion) as mundo:
            from sqlalchemy import select

            from app.db.database import crear_sesion_esquema
            from app.models import Producto, StockSede

            nombre_base = conexion.get_dsn_parameters()["dbname"]
            categoria_id = _crear_categoria(
                mundo["motor"], mundo, "Rollback AC-6"
            )
            producto_id = _crear_producto(
                mundo["motor"], mundo, "Rollback anillo", categoria_id
            )
            stock_sede_id = _crear_stock(mundo["motor"], mundo, producto_id, 0)

            sesion_entrada = crear_sesion_esquema(
                mundo["esquema"], motor=mundo["motor"]
            )
            resultado: dict[str, str] = {}
            hilo = None
            try:
                sesion_entrada.execute(
                    select(Producto)
                    .where(Producto.producto_id == producto_id)
                    .with_for_update()
                ).scalar_one()
                fila = sesion_entrada.execute(
                    select(StockSede)
                    .where(StockSede.stock_sede_id == stock_sede_id)
                    .with_for_update()
                ).scalar_one()
                fila.stock_actual = 5
                sesion_entrada.flush()

                tarea = _tarea_baja_producto(
                    mundo["motor"], mundo, producto_id
                )

                def _baja() -> None:
                    resultado["baja"] = tarea()

                hilo = threading.Thread(target=_baja)
                hilo.start()
                _esperar_bloqueo(nombre_base)
                sesion_entrada.rollback()
            finally:
                sesion_entrada.close()

            assert hilo is not None
            hilo.join(timeout=30)
            assert not hilo.is_alive(), "la baja no retomo tras el rollback"

            assert resultado["baja"] == "ok", resultado
            estado = _estado_producto(
                mundo["motor"], mundo["esquema"], producto_id, stock_sede_id
            )
            assert estado == {
                "activo": False,
                "stock": 0,
                "historial": 1,
                "movimientos": 0,
            }, estado
