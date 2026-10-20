"""T7 (Feature 017): dashboard tecnico SaaS sobre PostgreSQL 16 - gated.

Acredita contra namespaces reales lo que SQLite no puede simular:

  * taxonomia `operativo` / `no enrutable` / `no disponible` con conteos
    conocidos frente a no disponibles (D-8, AC-13/AC-14), sin presentar cero
    cuando el tenant no responde o su version es incompatible;
  * la clasificacion **no consulta datos de negocio** (se eliminan las tablas de
    tickets/catalogo/stock del tenant operativo y el dashboard sigue operativo);
  * unicidad concurrente del mapa `correo -> esquema` (dos altas del mismo correo
    dejan una sola fila);
  * reintento tenant/mapa: un usuario local sin asociacion completa el mapa sin
    duplicar la fila de usuario (D-2).

La estructura de las columnas/tabla auxiliares solo en `control` ya la verifica
`test_instalacion_limpia_postgres.py::test_estructura_de_invitacion_y_motivos_vive_solo_en_control`
(T3); no se duplica aqui. El doble login concurrente lo cubre
`test_aceptacion_invitacion_postgres_017.py` (T5).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_dashboard_tecnico_postgres_017.py

Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
mantenimiento donde se crean y DESTRUYEN bases temporales propias; nunca se toca
`apt_erp`.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema

from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL, crear_sesion_control, crear_sesion_esquema
from app.models import (
    BaseControl,
    Departamento,
    InstitucionControl,
    MapaUsuarioEsquema,
    Rol,
    Sede,
    Usuario,
    VersionEsquema,
)
from app.schemas.control_schema import (
    CLASE_NO_DISPONIBLE,
    CLASE_NO_ENRUTABLE,
    CLASE_OPERATIVO,
    InstitucionAltaControlCrear,
)
from app.schemas.usuario_schema import UsuarioCrear
from app.services import control_service, tenant_service, usuario_service
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

_OPERATIVO = "INST-017OP"
_INACTIVA = "INST-017INA"
_SIN_RAIZ = "INST-017SIN"
_NODISP = "INST-017VER"
_NORESPONDE = "INST-017DOWN"


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


@contextmanager
def _base_temporal():
    dsn = (_POSTGRES_TEST_URL or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_017dash_{uuid4().hex[:12]}"
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


def _datos(institucion_id: str, correo: str) -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id=institucion_id,
        nombre=f"Institucion {institucion_id}",
        correo_administrador=correo,
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo="Administracion",
    )


def _superadmin() -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Super",
        apellido="Admin",
        correo="superadmin@017.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Superadmin")
    return IdentidadAutenticada(usuario=usuario, sub="sub-017-dash")


def _mapa_en_control(
    engine,
    institucion_id: str,
    correo: str,
    *,
    activo: bool = True,
) -> None:
    sesion = crear_sesion_control(engine)
    try:
        sesion.add(
            MapaUsuarioEsquema(
                correo=security.normalizar_correo(correo),
                institucion_id=institucion_id,
                nombre_esquema=tenant_service.nombre_esquema_para_institucion(
                    institucion_id
                ),
                activo=activo,
                estado_invitacion="aceptada",
            )
        )
        sesion.commit()
    finally:
        sesion.close()


def _usuario_en_tenant(
    engine,
    institucion_id: str,
    correo: str,
    rol_nombre: str,
    departamento_nombre: str = "Administracion",
) -> int:
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        rol = sesion.execute(
            select(Rol).where(Rol.nombre_rol == rol_nombre)
        ).scalar_one()
        departamento = sesion.execute(
            select(Departamento).where(
                Departamento.nombre_dep == departamento_nombre
            )
        ).scalars().first()
        if departamento is None:
            departamento = Departamento(
                nombre_dep=departamento_nombre,
                descripcion="Departamento de prueba",
                institucion_id=institucion_id,
            )
            sesion.add(departamento)
            sesion.flush()
        usuario = Usuario(
            nombre=rol_nombre,
            apellido="Prueba",
            correo=correo,
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
        sesion.add(usuario)
        sesion.commit()
        return usuario.usuario_id
    finally:
        sesion.close()


def _sede_en_tenant(engine, institucion_id: str, nombre: str) -> None:
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        sesion.add(Sede(nombre=nombre, institucion_id=institucion_id))
        sesion.commit()
    finally:
        sesion.close()


def _estado_institucion(engine, institucion_id: str, activo: bool) -> None:
    sesion = crear_sesion_control(engine)
    try:
        control_service.cambiar_estado_institucion(sesion, institucion_id, activo)
    finally:
        sesion.close()


@contextmanager
def _motor_con_control():
    with _base_temporal() as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def mundo_dashboard():
    with _motor_con_control() as engine:
        sesion = crear_sesion_control(engine)
        try:
            sesion.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
            sesion.flush()
            for institucion_id, correo in (
                (_OPERATIVO, "admin.op@017.cl"),
                (_INACTIVA, "admin.inactiva@017.cl"),
                (_NODISP, "admin.ver@017.cl"),
                (_NORESPONDE, "admin.down@017.cl"),
            ):
                control_service.aprovisionar_institucion(
                    sesion, _datos(institucion_id, correo), lambda _correo: True
                )
            # Activa sin mapa: resolucion de metadatos/routing falla.
            sesion.add(
                InstitucionControl(
                    institucion_id=_SIN_RAIZ,
                    nombre="Institucion sin raiz",
                    direccion="Sin tenant",
                )
            )
            sesion.commit()
        finally:
            sesion.close()

        # Conteos del tenant operativo: una sede adicional y asociaciones activas
        # e inactivas que la taxonomia debe distinguir.
        _sede_en_tenant(engine, _OPERATIVO, "Sede Norte")
        _usuario_en_tenant(engine, _OPERATIVO, "bodega.op@017.cl", "Bodeguero")
        _mapa_en_control(engine, _OPERATIVO, "bodega.op@017.cl", activo=True)
        _usuario_en_tenant(engine, _OPERATIVO, "bodega.inactivo@017.cl", "Bodeguero")
        _mapa_en_control(engine, _OPERATIVO, "bodega.inactivo@017.cl", activo=False)
        _usuario_en_tenant(engine, _OPERATIVO, "solicita.op@017.cl", "Solicitante")
        _mapa_en_control(engine, _OPERATIVO, "solicita.op@017.cl", activo=True)
        _usuario_en_tenant(engine, _OPERATIVO, "admin.inactivo@017.cl", "Administrador")
        _mapa_en_control(engine, _OPERATIVO, "admin.inactivo@017.cl", activo=False)

        _estado_institucion(engine, _INACTIVA, False)

        # Version incompatible en un tenant activo y resoluble.
        esquema_ver = tenant_service.nombre_esquema_para_institucion(_NODISP)
        sesion_ver = crear_sesion_esquema(esquema_ver, motor=engine)
        try:
            sesion_ver.execute(
                VersionEsquema.__table__.update().values(version="000.0-incompatible")
            )
            sesion_ver.commit()
        finally:
            sesion_ver.close()

        # Tenant activo y resoluble que deja de responder: se elimina su esquema.
        esquema_down = tenant_service.nombre_esquema_para_institucion(_NORESPONDE)
        with engine.begin() as conexion:
            conexion.exec_driver_sql(f'DROP SCHEMA "{esquema_down}" CASCADE')

        yield engine


def _resumen(engine):
    sesion = crear_sesion_control(engine)
    try:
        return control_service.dashboard_saas(sesion)
    finally:
        sesion.close()


def test_taxonomia_y_agregados_conocidos_no_disponibles(mundo_dashboard):
    resumen = _resumen(mundo_dashboard)
    por_id = {fila.institucion_id: fila for fila in resumen.instituciones}

    assert resumen.total_instituciones == 5
    assert resumen.total_instituciones_activas == 4
    assert resumen.conteos_conocidos == 1
    assert resumen.conteos_no_disponibles == 4

    operativo = por_id[_OPERATIVO]
    assert operativo.estado_tecnico == CLASE_OPERATIVO
    assert operativo.version_persistida == VERSION_ESQUEMA_OBJETIVO
    assert operativo.version_objetivo == VERSION_ESQUEMA_OBJETIVO
    assert operativo.sedes == 2
    assert operativo.departamentos == 1
    assert operativo.administradores_activos == 1
    assert operativo.administradores_inactivos == 1
    assert operativo.usuarios_por_rol == {"Bodeguero": 1, "Solicitante": 1}

    inactiva = por_id[_INACTIVA]
    assert inactiva.activo is False
    assert inactiva.estado_tecnico == CLASE_NO_ENRUTABLE
    assert inactiva.sedes is None
    assert inactiva.departamentos is None

    sin_raiz = por_id[_SIN_RAIZ]
    assert sin_raiz.estado_tecnico == CLASE_NO_ENRUTABLE
    assert sin_raiz.sedes is None

    assert por_id[_NODISP].estado_tecnico == CLASE_NO_DISPONIBLE
    assert por_id[_NODISP].version_persistida == "000.0-incompatible"
    assert por_id[_NODISP].sedes is None

    assert por_id[_NORESPONDE].estado_tecnico == CLASE_NO_DISPONIBLE
    assert por_id[_NORESPONDE].sedes is None
    assert por_id[_NORESPONDE].usuarios_por_rol is None

    assert resumen.total_administradores_activos == 1
    assert resumen.total_administradores_inactivos == 1
    assert resumen.usuarios_por_rol == {"Bodeguero": 1, "Solicitante": 1}


def test_clasificacion_no_consulta_datos_de_negocio(mundo_dashboard):
    """AC-14: el dashboard no lee tickets, catalogo, stock ni movimientos."""
    esquema = tenant_service.nombre_esquema_para_institucion(_OPERATIVO)
    tablas_negocio = (
        "historial_transicion_ticket",
        "detalle_ticket",
        "ticket",
        "movimiento_inventario",
        "stock_sede",
        "inventario",
        "producto",
        "categoria",
        "estado_ticket",
        "prioridad",
        "departamento_encargado",
    )
    with mundo_dashboard.begin() as conexion:
        for tabla in tablas_negocio:
            conexion.exec_driver_sql(f'DROP TABLE "{esquema}"."{tabla}" CASCADE')

    resumen = _resumen(mundo_dashboard)
    operativo = next(
        fila for fila in resumen.instituciones if fila.institucion_id == _OPERATIVO
    )
    assert operativo.estado_tecnico == CLASE_OPERATIVO
    assert operativo.sedes == 2
    assert operativo.usuarios_por_rol == {"Bodeguero": 1, "Solicitante": 1}


def test_unicidad_concurrente_del_mapa(mundo_dashboard):
    """Dos altas concurrentes del mismo correo dejan una sola fila (AC-7)."""
    engine = mundo_dashboard
    correo = "carrera.map@017.cl"
    esquema = tenant_service.nombre_esquema_para_institucion(_OPERATIVO)
    barrera = threading.Barrier(2)
    resultados: list[str] = []
    bloqueo = threading.Lock()

    def _insertar() -> None:
        sesion = crear_sesion_control(engine)
        try:
            sesion.add(
                MapaUsuarioEsquema(
                    correo=correo,
                    institucion_id=_OPERATIVO,
                    nombre_esquema=esquema,
                    activo=True,
                    estado_invitacion="pendiente",
                )
            )
            barrera.wait(timeout=10)
            sesion.commit()
            with bloqueo:
                resultados.append("creada")
        except IntegrityError:
            sesion.rollback()
            with bloqueo:
                resultados.append("duplicada")
        except Exception as exc:  # pragma: no cover - diagnostico legible
            sesion.rollback()
            with bloqueo:
                resultados.append(f"error:{type(exc).__name__}")
        finally:
            sesion.close()

    hilos = [threading.Thread(target=_insertar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=20)

    assert sorted(resultados) == ["creada", "duplicada"], resultados
    sesion = crear_sesion_control(engine)
    try:
        filas = sesion.execute(
            select(MapaUsuarioEsquema).where(MapaUsuarioEsquema.correo == correo)
        ).scalars().all()
    finally:
        sesion.close()
    assert len(filas) == 1


def test_reintento_completa_mapa_sin_duplicar_usuario(mundo_dashboard):
    """D-2: usuario tenant sin mapa completa la asociacion en el reintento."""
    engine = mundo_dashboard
    correo = "reintento.op@017.cl"
    usuario_id = _usuario_en_tenant(engine, _OPERATIVO, correo, "Bodeguero")

    datos = UsuarioCrear(
        nombre="Bodeguero",
        apellido="Prueba",
        correo=correo,
        departamento_id=1,
        rol_id=1,
    )
    # El departamento y rol reales del tenant se leen para armar la entrada.
    esquema = tenant_service.nombre_esquema_para_institucion(_OPERATIVO)
    sesion_tenant = crear_sesion_esquema(esquema, motor=engine)
    sesion_control = crear_sesion_control(engine)
    try:
        rol = sesion_tenant.execute(
            select(Rol).where(Rol.nombre_rol == "Bodeguero")
        ).scalar_one()
        departamento = sesion_tenant.execute(
            select(Departamento).where(Departamento.institucion_id == _OPERATIVO)
        ).scalars().first()
        datos = datos.model_copy(
            update={"rol_id": rol.rol_id, "departamento_id": departamento.departamento_id}
        )
        resultado = usuario_service.crear_usuario(
            sesion_tenant,
            datos,
            _superadmin(),
            db_control=sesion_control,
            consultar_identidad=lambda _correo: security.EstadoIdentidadClerk(
                identidad_existente=True,
                invitacion_pendiente=False,
                invitacion_id=None,
            ),
            institucion_id=_OPERATIVO,
        )
        assert resultado.usuario_id == usuario_id
        mapa = sesion_control.execute(
            select(MapaUsuarioEsquema).where(MapaUsuarioEsquema.correo == correo)
        ).scalar_one()
        assert mapa.activo is True
        assert mapa.estado_invitacion == "aceptada"
    finally:
        sesion_control.close()
        sesion_tenant.close()

    # Una sola fila de usuario: el reintento no duplico.
    sesion_tenant = crear_sesion_esquema(esquema, motor=engine)
    try:
        usuarios = sesion_tenant.execute(
            select(Usuario).where(Usuario.correo == correo)
        ).scalars().all()
    finally:
        sesion_tenant.close()
    assert len(usuarios) == 1
