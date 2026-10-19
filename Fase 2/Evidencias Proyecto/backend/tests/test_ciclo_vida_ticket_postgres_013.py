"""T2 (Feature 013): instalacion limpia, estado `Anulado` e historial - gated.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs ni el
DDL por esquema, asi que lo que la Feature 013 exige del catalogo replicado y del
historial solo se acredita contra PostgreSQL 16 real:

  * **Instalacion limpia** (`01_` + `02_`): `Anulado` presente en control y en
    cada tenant, `historial_transicion_ticket` creada en control y en cada
    tenant, sin filas de historial fabricadas (AC-12) y version objetivo
    `013.1` en todos los esquemas.
  * **Token de version**: un tenant en `012.1` deniega en cerrado con el objetivo
    `013.1`; solo se enrutan tenants exactamente en la version objetivo (AC-21).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_ciclo_vida_ticket_postgres_013.py
"""

from __future__ import annotations

import os
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

#: Version anterior de una instalacion existente (la que fija la 012).
VERSION_ANTERIOR = "012.1"
#: Estado nuevo del catalogo y tabla nueva del historial (spec D-1/D-10).
ESTADO_ANULADO = "Anulado"
TABLA_HISTORIAL = "historial_transicion_ticket"


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
    dsn = _sin_driver(_POSTGRES_TEST_URL or "")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_013_{uuid4().hex[:12]}"
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
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (esquema,),
    )
    return {fila[0] for fila in filas}


def _esquema_de_institucion(institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _instituciones(conexion) -> list[str]:
    return [
        fila[0]
        for fila in _ejecutar(
            conexion, "SELECT institucion_id FROM control.institucion ORDER BY institucion_id"
        )
    ]


def _version_de(conexion, esquema: str) -> str:
    return _un_escalar(conexion, f'SELECT version FROM "{esquema}".version_esquema')


def _version_de_control(conexion) -> str:
    return _un_escalar(conexion, "SELECT version FROM control.version_esquema")


# ---------------------------------------------------------------------------
# AC-20/AC-21: token de version del codigo
# ---------------------------------------------------------------------------


def test_el_codigo_apunta_a_la_version_013_1():
    """AC-20/AC-21: `VERSION_ESQUEMA_OBJETIVO` es `013.1`."""
    assert VERSION_ESQUEMA_OBJETIVO == "013.1", VERSION_ESQUEMA_OBJETIVO


# ---------------------------------------------------------------------------
# AC-20: instalacion nueva
# ---------------------------------------------------------------------------


def test_instalacion_nueva_replica_anulado_e_historial_en_control_y_tenants():
    """AC-20: `01 -> 02` crea la tabla y siembra `Anulado` en cada esquema."""
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert TABLA_HISTORIAL in _tablas_del_esquema(conexion, "control")
        assert ESTADO_ANULADO in {
            fila[0]
            for fila in _ejecutar(conexion, "SELECT nombre FROM control.estado_ticket")
        }
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert TABLA_HISTORIAL in _tablas_del_esquema(conexion, esquema), esquema
            assert ESTADO_ANULADO in {
                fila[0]
                for fila in _ejecutar(
                    conexion, f'SELECT nombre FROM "{esquema}".estado_ticket'
                )
            }, esquema
            assert _version_de(conexion, esquema) == VERSION_ESQUEMA_OBJETIVO, esquema
        assert _version_de_control(conexion) == VERSION_ESQUEMA_OBJETIVO


def test_instalacion_nueva_no_siembra_historial_fabricado():
    """AC-12: la instalacion nueva no inventa filas de historial."""
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert _un_escalar(
            conexion, f"SELECT count(*) FROM control.{TABLA_HISTORIAL}"
        ) == 0
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _un_escalar(
                conexion, f'SELECT count(*) FROM "{esquema}".{TABLA_HISTORIAL}'
            ) == 0, esquema


# ---------------------------------------------------------------------------
# AC-21: token de version en el routing
# ---------------------------------------------------------------------------


def _motor_sqlalchemy(conexion):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # psycopg2 2.9+ no expone `password` en `get_dsn_parameters()`; se reutiliza
    # la URL original del harness solo cambiando el nombre de la base. Se fuerza
    # el driver psycopg2: `psycopg` v3 no es dependencia del proyecto.
    nombre_base = conexion.get_dsn_parameters()["dbname"]
    url = _url_con_base(_sin_driver(_POSTGRES_TEST_URL or ""), nombre_base)
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, poolclass=NullPool, future=True)


@contextmanager
def _sesion_control(conexion):
    """Sesion ligada al esquema `control` de la base temporal (patron T11)."""
    from sqlalchemy.orm import Session

    motor = _motor_sqlalchemy(conexion)
    try:
        con_control = motor.execution_options(
            schema_translate_map={None: "control"}
        )
        sesion = Session(bind=con_control)
        try:
            yield sesion
        finally:
            sesion.close()
    finally:
        motor.dispose()


def test_tenant_en_012_1_deniega_con_el_objetivo_013_1():
    """AC-21: un tenant desactualizado no se enruta con el objetivo `013.1`."""
    from app.db.database import crear_sesion_esquema
    from app.services import tenant_service

    with _base_temporal() as conexion:
        _instalar(conexion)

        filas = _ejecutar(
            conexion,
            "SELECT correo, nombre_esquema FROM control.mapa_usuario_esquema "
            "ORDER BY correo LIMIT 1",
        )
        assert filas, "la semilla debe mapear al menos un correo a su tenant"
        correo, esquema = filas[0]

        # Mismo cableado que `get_db` en produccion (`dependencies.py`): la
        # sesion de control resuelve el mapa y `abrir_sesion_tenant` abre la
        # sesion ligada al esquema del tenant, donde se lee la version.
        motor = _motor_sqlalchemy(conexion)
        abrir_sesion_tenant = lambda esq: crear_sesion_esquema(esq, motor=motor)  # noqa: E731
        try:
            # Tenant bajado a 012.1: el routing lo deniega en cerrado.
            _ejecutar(
                conexion,
                f'UPDATE "{esquema}".version_esquema SET version = %s',
                (VERSION_ANTERIOR,),
            )
            with _sesion_control(conexion) as sesion:
                with pytest.raises(tenant_service.ErrorTenant):
                    tenant_service.resolver_contexto_solicitud(
                        sesion, correo, abrir_sesion_tenant=abrir_sesion_tenant
                    )

            # Solo se enrutan tenants exactamente en la version objetivo.
            _ejecutar(
                conexion,
                f'UPDATE "{esquema}".version_esquema SET version = %s',
                (VERSION_ESQUEMA_OBJETIVO,),
            )
            with _sesion_control(conexion) as sesion:
                contexto = tenant_service.resolver_contexto_solicitud(
                    sesion, correo, abrir_sesion_tenant=abrir_sesion_tenant
                )
        finally:
            motor.dispose()
        assert contexto.nombre_esquema == esquema
        assert contexto.version == VERSION_ESQUEMA_OBJETIVO
