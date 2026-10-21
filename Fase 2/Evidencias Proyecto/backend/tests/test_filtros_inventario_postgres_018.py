"""T5 (Feature 018): aislamiento cross-schema de los filtros de inventario (gated).

Cierra la evidencia que la suite SQLite no puede acreditar. SQLite tiene un unico
contexto logico, de modo que ahi el `departamento_id` de otra institucion es una
fila **visible** y responde **403**; en PostgreSQL cada tenant vive en su propio
esquema y el identificador ajeno **no existe** en el esquema del actor. La spec
(plan §1.4 y §3) exige no confundir ambas semantica:

  * **AC-3**: `GET /api/v1/inventario/existencias?sede_id=<sede de otro tenant>`
    responde **200 con lista vacia**, nunca 403/404: `sede_id` es un filtro de
    lista, no un recurso. El contraste se fija aqui mismo: el endpoint de recurso
    `GET /api/v1/inventario/stock?sede_id=<sede ajena>` conserva el **404** de la
    Feature 011 (AC-3), cuyas pruebas gated siguen intactas.
  * **AC-3/AC-4**: un `departamento_id` de otro tenant tampoco existe en el
    esquema del actor y responde **200 con lista vacia**. No se escribe ninguna
    prueba gated que espere el 403: esa semantica solo es observable en el arnes
    SQLite.
  * **AC-4**: `GET /api/v1/inventario/ambito` devuelve las opciones del propio
    tenant -todas para el Administrador, solo su sede para el Bodeguero- sin
    contaminacion del otro esquema.
  * **AC-9**: cada tenant solo ve su catalogo y su saldo; los mismos numeros de
    `sede_id`/`departamento_id` significan cosas distintas segun el esquema.

COMO ACTIVARLA
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_filtros_inventario_postgres_018.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
    mantenimiento donde el modulo crea y DESTRUYE bases temporales propias; nunca
    toca `apt_erp`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app.api import dependencies
from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import (
    Base,
    ESQUEMA_CONTROL,
    crear_sesion_control,
    crear_sesion_esquema,
)
from app.main import app
from app.models import (
    BaseControl,
    Categoria,
    Departamento,
    MapaUsuarioEsquema,
    Producto,
    Rol,
    Sede,
    StockSede,
    Usuario,
    VersionEsquema,
)
from app.schemas.control_schema import InstitucionAltaControlCrear
from app.services import control_service, tenant_service
from app.services.auth_service import IdentidadAutenticada

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

#: Lectura de lista ampliada con el filtro `sede_id` (Feature 018).
_RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"
#: Lectura minima de opciones para los selectores (Feature 018).
_RUTA_AMBITO = "/api/v1/inventario/ambito"
#: Endpoint de **recurso** de la Feature 011: conserva el 404 para sede ajena.
_RUTA_STOCK = "/api/v1/inventario/stock"

_INSTITUCION_A = "INST-018A"
_INSTITUCION_B = "INST-018B"
_CORREO_ADMIN_A = "admin.a@018.cl"
_CORREO_ADMIN_B = "admin.b@018.cl"
_CORREO_BODEGUERO_A = "bodega.a@018.cl"

_NOMBRE_SEDE_INICIAL = control_service.NOMBRE_SEDE_CENTRAL


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


# ---------------------------------------------------------------------------
# Base temporal (nunca `apt_erp`) y utilidades de siembra
# ---------------------------------------------------------------------------


@contextmanager
def _base_temporal():
    """Crea una base PostgreSQL efimera y la destruye al salir."""
    dsn = (_POSTGRES_TEST_URL or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_018t5_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    url = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        yield url
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _datos(institucion_id: str, nombre: str, correo: str) -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id=institucion_id,
        nombre=nombre,
        correo_administrador=correo,
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo=f"Administracion {institucion_id}",
    )


def _sesion_tenant(engine, institucion_id: str) -> Session:
    return crear_sesion_esquema(
        tenant_service.nombre_esquema_para_institucion(institucion_id),
        motor=engine,
    )


def _crear_sede(sesion: Session, institucion_id: str, nombre: str) -> int:
    """Sede del tenant; el id lo asigna la secuencia **de ese esquema**."""
    sede = Sede(nombre=nombre, institucion_id=institucion_id)
    sesion.add(sede)
    sesion.flush()
    return sede.sede_id


def _crear_departamento(
    sesion: Session, institucion_id: str, nombre: str, sede_id: int | None
) -> int:
    departamento = Departamento(
        nombre_dep=nombre,
        descripcion=f"Departamento de prueba {nombre}",
        institucion_id=institucion_id,
        sede_id=sede_id,
    )
    sesion.add(departamento)
    sesion.flush()
    return departamento.departamento_id


def _crear_producto_con_saldo(
    sesion: Session,
    institucion_id: str,
    *,
    nombre_categoria: str,
    nombre_producto: str,
    saldos: dict[int, int],
) -> int:
    """Categoria + producto del tenant con una fila de `stock_sede` por sede."""
    categoria = Categoria(
        nombre_cat=nombre_categoria,
        descripcion_cat=f"Categoria de prueba {nombre_categoria}",
        institucion_id=institucion_id,
    )
    sesion.add(categoria)
    sesion.flush()
    producto = Producto(
        nombre=nombre_producto,
        descripcion=f"Producto de prueba {nombre_producto}",
        unidad_medida="UNIDAD",
        stock_minimo=2,
        categoria_id=categoria.categoria_id,
        institucion_id=institucion_id,
    )
    sesion.add(producto)
    sesion.flush()
    for sede_id, cantidad in saldos.items():
        sesion.add(
            StockSede(
                stock_actual=cantidad,
                sede_id=sede_id,
                producto_id=producto.producto_id,
                institucion_id=institucion_id,
            )
        )
    sesion.flush()
    return producto.producto_id


def _crear_bodeguero(
    sesion: Session,
    institucion_id: str,
    *,
    correo: str,
    departamento_id: int,
    sede_id: int,
) -> int:
    rol = sesion.execute(
        select(Rol).where(Rol.nombre_rol == "Bodeguero")
    ).scalar_one()
    usuario = Usuario(
        nombre="Bode",
        apellido="Guero",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=rol.rol_id,
        sede_id=sede_id,
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario.usuario_id


def _registrar_mapa(engine, institucion_id: str, correo: str) -> None:
    """Vincula el correo del Bodeguero a su tenant en el mapa de control (D-3)."""
    sesion = crear_sesion_control(engine)
    try:
        sesion.add(
            MapaUsuarioEsquema(
                correo=security.normalizar_correo(correo),
                institucion_id=institucion_id,
                nombre_esquema=tenant_service.nombre_esquema_para_institucion(
                    institucion_id
                ),
                activo=True,
                estado_invitacion="aceptada",
            )
        )
        sesion.commit()
    finally:
        sesion.close()


def _sembrar_tenant_a(engine) -> dict[str, int]:
    """Tenant A: dos sedes (una extra), un departamento con sede y su saldo.

    La sede extra es la id **2** de este esquema y el unico departamento con
    sede es la id **2**. El tenant B crea una tercera sede y un tercer
    departamento, que por tanto **no existen** en A: esos son los identificadores
    ajenos usados por las pruebas.
    """
    sesion = _sesion_tenant(engine, _INSTITUCION_A)
    try:
        sede_inicial = sesion.execute(
            select(Sede.sede_id).where(Sede.nombre == _NOMBRE_SEDE_INICIAL)
        ).scalar_one()
        sede_extra = _crear_sede(sesion, _INSTITUCION_A, "Alfa Norte")
        departamento = _crear_departamento(
            sesion, _INSTITUCION_A, "Alfa Almacen", sede_extra
        )
        producto = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_A,
            nombre_categoria="Papeleria Alfa",
            nombre_producto="Resma Alfa",
            saldos={sede_extra: 7},
        )
        bodeguero = _crear_bodeguero(
            sesion,
            _INSTITUCION_A,
            correo=_CORREO_BODEGUERO_A,
            departamento_id=departamento,
            sede_id=sede_extra,
        )
        sesion.commit()
        ids = {
            "sede_inicial": sede_inicial,
            "sede_extra": sede_extra,
            "departamento": departamento,
            "producto": producto,
            "bodeguero": bodeguero,
        }
    finally:
        sesion.close()
    _registrar_mapa(engine, _INSTITUCION_A, _CORREO_BODEGUERO_A)
    return ids


def _sembrar_tenant_b(engine) -> dict[str, int]:
    """Tenant B: tres sedes (2 y 3 extra), dos departamentos con sede y saldo.

    `sede_id=3` y `departamento_id=3` existen **solo** aqui, de modo que pedirlos
    desde A prueba que un identificador de otro esquema es indistinguible de uno
    inexistente en el esquema del actor.
    """
    sesion = _sesion_tenant(engine, _INSTITUCION_B)
    try:
        sede_inicial = sesion.execute(
            select(Sede.sede_id).where(Sede.nombre == _NOMBRE_SEDE_INICIAL)
        ).scalar_one()
        sede_centro = _crear_sede(sesion, _INSTITUCION_B, "Beta Centro")
        sede_sur = _crear_sede(sesion, _INSTITUCION_B, "Beta Sur")
        departamento_centro = _crear_departamento(
            sesion, _INSTITUCION_B, "Beta Bodega", sede_centro
        )
        departamento_sur = _crear_departamento(
            sesion, _INSTITUCION_B, "Beta Logistica", sede_sur
        )
        producto = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_B,
            nombre_categoria="Papeleria Beta",
            nombre_producto="Resma Beta",
            saldos={sede_centro: 5, sede_sur: 4},
        )
        sesion.commit()
        return {
            "sede_inicial": sede_inicial,
            "sede_centro": sede_centro,
            "sede_sur": sede_sur,
            "departamento_centro": departamento_centro,
            "departamento_sur": departamento_sur,
            "producto": producto,
        }
    finally:
        sesion.close()


def _identidad(
    correo: str,
    rol: str,
    *,
    departamento_id: int,
    sede_id: int | None = None,
) -> IdentidadAutenticada:
    """Identidad sintetica con el rol y la sede que lee el servicio (`getattr`)."""
    usuario = Usuario(
        usuario_id=1,
        nombre="Frontera",
        apellido="Gated",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
        sede_id=sede_id,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub=f"sub-{correo}")


@contextmanager
def _cliente(mundo, identidad: IdentidadAutenticada):
    """`TestClient` del `app` real con `get_db` atado a la base temporal.

    `get_db` cede la sesion de **control**; `get_db_negocio` resuelve el esquema
    del correo contra el mapa real de control y abre el tenant, igual que en
    produccion. Asi la frontera entre esquemas se ejecuta de verdad.
    """
    Fabrica = sessionmaker(bind=mundo["motor_control"])

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: identidad
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _ambito(cliente) -> dict:
    respuesta = cliente.get(_RUTA_AMBITO)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _ids_producto(filas: list[dict]) -> set[int]:
    return {fila["producto_id"] for fila in filas}


@pytest.fixture
def mundo_018():
    """`control` + dos tenants reales en esquemas separados, provisionados de verdad."""
    with _base_temporal() as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            # Guarda explicita: la base desechable nunca es `apt_erp`.
            assert engine.url.database.startswith("compustock_018t5_"), (
                engine.url.database
            )

            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            # El canonico de control (con `activo`/`funcion_institucion`) primero.
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)

            control = crear_sesion_control(engine)
            try:
                # El gating tolerante lee la version desde control: se siembra la
                # version objetivo para que el contexto resuelva (Feature 012).
                control.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
                control.flush()
                control_service.aprovisionar_institucion(
                    control,
                    _datos(_INSTITUCION_A, "Instituto Alfa 018", _CORREO_ADMIN_A),
                    lambda _correo: True,
                )
                control_service.aprovisionar_institucion(
                    control,
                    _datos(_INSTITUCION_B, "Instituto Beta 018", _CORREO_ADMIN_B),
                    lambda _correo: True,
                )
            finally:
                control.close()

            ids_a = _sembrar_tenant_a(engine)
            ids_b = _sembrar_tenant_b(engine)

            yield {
                "engine": engine,
                "motor_control": motor_control,
                "ids_a": ids_a,
                "ids_b": ids_b,
                # Los departamentos administrativos iniciales son la id 1 en
                # ambos esquemas: la institucion se resuelve por esa fila.
                "identidad_admin_a": _identidad(
                    _CORREO_ADMIN_A, "Administrador", departamento_id=1
                ),
                "identidad_admin_b": _identidad(
                    _CORREO_ADMIN_B, "Administrador", departamento_id=1
                ),
                "identidad_bodeguero_a": _identidad(
                    _CORREO_BODEGUERO_A,
                    "Bodeguero",
                    departamento_id=ids_a["departamento"],
                    sede_id=ids_a["sede_extra"],
                ),
            }
        finally:
            engine.dispose()


# ===========================================================================
# AC-3/AC-9: `sede_id` de otro esquema -> 200/[] (filtro, no recurso)
# ===========================================================================


def test_sede_de_otro_tenant_devuelve_200_vacio_y_el_recurso_conserva_404(mundo_018):
    """AC-3/AC-9: el mismo id es valido en B e inexistente en A.

    Desde A, `existencias?sede_id=<sede de B>` responde **200/[]** y no 403/404:
    `sede_id` filtra una lista y no se hace lookup previo. Desde B, esa misma
    sede si devuelve su saldo, asi que el id no es un numero inventado. El
    contraste queda fijado en la misma prueba: el endpoint de **recurso**
    `GET /inventario/stock?sede_id=...` conserva el **404** de la Feature 011,
    cuyas pruebas gated siguen intactas.
    """
    sede_solo_en_b = mundo_018["ids_b"]["sede_sur"]
    with _cliente(mundo_018, mundo_018["identidad_admin_a"]) as cliente_a:
        ajena = cliente_a.get(
            _RUTA_EXISTENCIAS, params={"sede_id": sede_solo_en_b}
        )
        inexistente = cliente_a.get(
            _RUTA_EXISTENCIAS, params={"sede_id": 999_999}
        )
        recurso = cliente_a.get(_RUTA_STOCK, params={"sede_id": sede_solo_en_b})

    with _cliente(mundo_018, mundo_018["identidad_admin_b"]) as cliente_b:
        propia_de_b = cliente_b.get(
            _RUTA_EXISTENCIAS, params={"sede_id": sede_solo_en_b}
        )

    assert ajena.status_code == 200, ajena.text
    assert ajena.json() == [], "un filtro sin filas visibles no es un error"
    assert inexistente.status_code == 200, inexistente.text
    assert inexistente.json() == []
    # La sede existe de verdad, solo que en el otro esquema.
    assert propia_de_b.status_code == 200, propia_de_b.text
    assert _ids_producto(propia_de_b.json()) == {mundo_018["ids_b"]["producto"]}
    # Contraste con el recurso de la 011: no se altera su 404.
    assert recurso.status_code == 404, recurso.text


# ===========================================================================
# AC-3/AC-4: `departamento_id` de otro esquema -> 200/[] (nunca 403 en PG)
# ===========================================================================


def test_departamento_de_otro_tenant_devuelve_200_vacio_sin_403(mundo_018):
    """AC-3/AC-4: entre esquemas la fila ajena no es visible: 200/[].

    El 403 de "departamento de otra institucion" solo es observable en el arnes
    SQLite, donde la fila ajena convive en el mismo esquema (plan §1.4). En
    PostgreSQL el identificador no existe para el actor y el filtro degrada a
    lista vacia, exactamente como uno inexistente.
    """
    departamento_solo_en_b = mundo_018["ids_b"]["departamento_sur"]
    with _cliente(mundo_018, mundo_018["identidad_admin_a"]) as cliente_a:
        ajena = cliente_a.get(
            _RUTA_EXISTENCIAS, params={"departamento_id": departamento_solo_en_b}
        )
    with _cliente(mundo_018, mundo_018["identidad_admin_b"]) as cliente_b:
        propia_de_b = cliente_b.get(
            _RUTA_EXISTENCIAS, params={"departamento_id": departamento_solo_en_b}
        )

    assert ajena.status_code == 200, ajena.text
    assert ajena.json() == []
    assert ajena.status_code != 403, "entre esquemas no hay 403 de departamento"
    # En B el mismo id resuelve a su sede y trae su saldo: era un id real.
    assert propia_de_b.status_code == 200, propia_de_b.text
    filas = propia_de_b.json()
    assert _ids_producto(filas) == {mundo_018["ids_b"]["producto"]}
    assert filas[0]["stock_total"] == 4, "saldo de Beta Sur"


# ===========================================================================
# AC-9: cada tenant solo ve su catalogo y su saldo
# ===========================================================================


def test_cada_tenant_solo_ve_su_catalogo_y_su_saldo(mundo_018):
    """AC-9: sin filtros, la lista no mezcla productos ni sedes del otro esquema."""
    with _cliente(mundo_018, mundo_018["identidad_admin_a"]) as cliente_a:
        filas_a = cliente_a.get(_RUTA_EXISTENCIAS).json()
    with _cliente(mundo_018, mundo_018["identidad_admin_b"]) as cliente_b:
        filas_b = cliente_b.get(_RUTA_EXISTENCIAS).json()

    assert _ids_producto(filas_a) == {mundo_018["ids_a"]["producto"]}
    assert _ids_producto(filas_b) == {mundo_018["ids_b"]["producto"]}

    sedes_a = {sede["sede_id"] for fila in filas_a for sede in fila["sedes"]}
    sedes_b = {sede["sede_id"] for fila in filas_b for sede in fila["sedes"]}
    assert sedes_a == {mundo_018["ids_a"]["sede_extra"]}
    assert sedes_b == {
        mundo_018["ids_b"]["sede_centro"],
        mundo_018["ids_b"]["sede_sur"],
    }
    # Mismo numero de sede (2) en ambos esquemas, contenidos distintos.
    assert filas_a[0]["stock_total"] == 7
    assert filas_b[0]["stock_total"] == 9


# ===========================================================================
# AC-4: lectura de ambito sin contaminacion del otro esquema
# ===========================================================================


def test_ambito_administrador_contiene_solo_su_institucion(mundo_018):
    """AC-4/D-6: el Administrador recibe sus sedes y departamentos con sede."""
    with _cliente(mundo_018, mundo_018["identidad_admin_a"]) as cliente_a:
        ambito_a = _ambito(cliente_a)

    nombres_sedes_a = {fila["sede_nombre"] for fila in ambito_a["sedes"]}
    ids_sedes_a = {fila["sede_id"] for fila in ambito_a["sedes"]}
    ids_departamentos_a = {
        fila["departamento_id"] for fila in ambito_a["departamentos"]
    }

    assert ids_sedes_a == {
        mundo_018["ids_a"]["sede_inicial"],
        mundo_018["ids_a"]["sede_extra"],
    }
    assert nombres_sedes_a == {_NOMBRE_SEDE_INICIAL, "Alfa Norte"}
    assert ids_departamentos_a == {mundo_018["ids_a"]["departamento"]}
    # Nada del tenant B, aunque comparta el numero de sede/departamento 2.
    assert mundo_018["ids_b"]["sede_sur"] not in ids_sedes_a
    assert mundo_018["ids_b"]["departamento_sur"] not in ids_departamentos_a
    assert not {"Beta Centro", "Beta Sur"} & nombres_sedes_a
    assert not {"Beta Bodega", "Beta Logistica"} & {
        fila["departamento_nombre"] for fila in ambito_a["departamentos"]
    }


def test_ambito_bodeguero_solo_su_sede_y_sus_departamentos(mundo_018):
    """AC-4/D-6: el Bodeguero no recibe sedes ajenas ni de otra sede."""
    with _cliente(mundo_018, mundo_018["identidad_bodeguero_a"]) as cliente_a:
        ambito = _ambito(cliente_a)

    assert [fila["sede_id"] for fila in ambito["sedes"]] == [
        mundo_018["ids_a"]["sede_extra"]
    ]
    assert ambito["sedes"][0]["sede_nombre"] == "Alfa Norte"
    assert {fila["departamento_id"] for fila in ambito["departamentos"]} == {
        mundo_018["ids_a"]["departamento"]
    }
    assert all(
        fila["sede_id"] == mundo_018["ids_a"]["sede_extra"]
        for fila in ambito["departamentos"]
    )


# ===========================================================================
# AC-3: el filtro propio acota el saldo; el ajeno no revela nada
# ===========================================================================


def test_filtro_propio_acota_saldo_y_sede_ajena_en_rol_operativo_da_vacio(
    mundo_018,
):
    """AC-3/D-7: la sede propia filtra; la de otro esquema da 200/[] por interseccion."""
    with _cliente(mundo_018, mundo_018["identidad_bodeguero_a"]) as cliente:
        propia = cliente.get(
            _RUTA_EXISTENCIAS, params={"sede_id": mundo_018["ids_a"]["sede_extra"]}
        )
        ajena = cliente.get(
            _RUTA_EXISTENCIAS, params={"sede_id": mundo_018["ids_b"]["sede_sur"]}
        )

    assert propia.status_code == 200, propia.text
    filas = propia.json()
    assert _ids_producto(filas) == {mundo_018["ids_a"]["producto"]}
    assert filas[0]["stock_total"] == 7
    assert [sede["sede_id"] for sede in filas[0]["sedes"]] == [
        mundo_018["ids_a"]["sede_extra"]
    ]

    assert ajena.status_code == 200, ajena.text
    assert ajena.json() == []
