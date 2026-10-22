"""T2 (Feature 012): DDL de la gestion administrativa en PostgreSQL 16 - gated.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs ni el
DDL por esquema, asi que lo que la Feature 012 exige del modelo control-only solo
se acredita contra PostgreSQL 16 real:

  * `control.institucion.activo` existe **solo** en control;
  * `funcion_institucion` es auxiliar **solo** de control, con una fila por
    `(institucion_id, funcion)` y el conjunto cerrado de seis capacidades;
  * el espejo tenant `institucion` tiene **exactamente** dos columnas
    (`institucion_id`, `nombre`) y **no** materializa capacidades;
  * la version objetivo de control y de cada tenant es la vigente
    (`VERSION_ESQUEMA_OBJETIVO`).

Las pruebas parten de la instalacion limpia completa (`01_` + `02_`), que ya
crea `control` y los tenants con todos los datos repartidos.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_gestion_administrativa_postgres_012.py
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

#: Version objetivo vigente: la constante de despliegue, no un literal.
VERSION_OBJETIVO = VERSION_ESQUEMA_OBJETIVO
CAPACIDADES = {
    "catalogo",
    "inventario",
    "tickets",
    "kanban",
    "dashboard",
    "gestion_organizacional",
}
COLUMNAS_ESPEJO = {"institucion_id", "nombre"}


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
    nombre = f"compustock_012_{uuid4().hex[:12]}"
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


def _columnas_de_tabla(conexion, esquema: str, tabla: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (esquema, tabla),
    )
    return {fila[0] for fila in filas}


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


# ---------------------------------------------------------------------------
# AC-1/AC-2/AC-5: estructura control-only
# ---------------------------------------------------------------------------


def test_ddl_control_tiene_activo_y_funcion_institucion():
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert "activo" in _columnas_de_tabla(conexion, "control", "institucion")
        tablas = _tablas_del_esquema(conexion, "control")
        assert "funcion_institucion" in tablas, tablas

        for institucion_id in _instituciones(conexion):
            filas = _ejecutar(
                conexion,
                "SELECT funcion, habilitada FROM control.funcion_institucion "
                "WHERE institucion_id = %s",
                (institucion_id,),
            )
            assert {fila[0] for fila in filas} == CAPACIDADES, institucion_id
            assert all(fila[1] is True for fila in filas), institucion_id


# ---------------------------------------------------------------------------
# AC-1/AC-13: espejo tenant exacto y sin capacidades
# ---------------------------------------------------------------------------


def test_espejo_tenant_solo_tiene_dos_columnas_y_no_capacidades():
    with _base_temporal() as conexion:
        _instalar(conexion)

        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _columnas_de_tabla(conexion, esquema, "institucion") == COLUMNAS_ESPEJO, (
                institucion_id
            )
            assert "funcion_institucion" not in _tablas_del_esquema(conexion, esquema), (
                institucion_id
            )


def test_version_objetivo_control_y_tenants():
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_OBJETIVO,)
        ]
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _ejecutar(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            ) == [(VERSION_OBJETIVO,)], institucion_id
