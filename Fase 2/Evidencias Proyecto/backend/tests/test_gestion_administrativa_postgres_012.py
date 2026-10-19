"""T2 (Feature 012): DDL/migracion de la gestion administrativa en PostgreSQL 16 - gated.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs ni el
DDL por esquema, asi que lo que la Feature 012 exige del modelo control-only solo
se acredita contra PostgreSQL 16 real:

  * `control.institucion.activo` existe **solo** en control;
  * `funcion_institucion` es auxiliar **solo** de control, con una fila por
    `(institucion_id, funcion)` y el conjunto cerrado de seis capacidades;
  * el espejo tenant `institucion` tiene **exactamente** dos columnas
    (`institucion_id`, `nombre`) y **no** materializa capacidades;
  * la version objetivo de control y de cada tenant es la vigente
    (`VERSION_ESQUEMA_OBJETIVO`; la 012 la subio a `012.1`);
  * la migracion `003_...012.sql` es idempotente.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_gestion_administrativa_postgres_012.py

Fase ROJA de TDD: el DDL de la 012 y el script de migracion aun no existen (T3/T4),
de modo que cada prueba falla por la estructura/archivo ausente, nunca por un error
de sintaxis del test.
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
CONSTRUCTOR_SQL = RAIZ / "database" / "03_construir_tenants_011.sql"
MIGRACION_012 = (
    RAIZ / "database" / "migraciones" / "003_migracion_gestion_administrativa_012.sql"
)

#: Version objetivo vigente: la constante de despliegue, no un literal (el bump
#: de T5 la subira a `013.1` y el constructor seguira automaticamente).
VERSION_OBJETIVO = VERSION_ESQUEMA_OBJETIVO
#: Fase de la cadena de migraciones: el script `003_...012.sql` fija `012.1`
#: para siempre; las pruebas de migracion la ejercitan como destino de ese salto.
VERSION_MIGRACION_012 = "012.1"
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


def _existe_archivo(ruta: Path) -> None:
    if not ruta.exists():
        pytest.fail(
            f"capacidad ausente (T3/T4): falta el script {ruta.name}; la Feature 012 "
            "lo crea en T3/T4 y hasta entonces esta prueba esta en rojo."
        )


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
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)

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
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

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
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_OBJETIVO,)
        ]
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _ejecutar(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            ) == [(VERSION_OBJETIVO,)], institucion_id


# ---------------------------------------------------------------------------
# AC-14: migracion operacional idempotente
# ---------------------------------------------------------------------------


def test_migracion_012_es_idempotente():
    _existe_archivo(MIGRACION_012)
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)
        # El constructor nace en la version objetivo vigente (013.1 desde la
        # Feature 013); la 003 ejercita su propia fase de la cadena.
        _degradar_a_012_1(conexion)

        _ejecutar_script(conexion, MIGRACION_012)
        antes = _un_escalar(conexion, "SELECT count(*) FROM control.funcion_institucion")
        _ejecutar_script(conexion, MIGRACION_012)
        despues = _un_escalar(conexion, "SELECT count(*) FROM control.funcion_institucion")
        assert antes == despues, "la segunda ejecucion no debe duplicar capacidades"
        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_MIGRACION_012,)
        ]

        for institucion_id in _instituciones(conexion):
            filas = _ejecutar(
                conexion,
                "SELECT count(*) FROM control.funcion_institucion WHERE institucion_id = %s",
                (institucion_id,),
            )
            assert filas[0][0] == len(CAPACIDADES), institucion_id


# ---------------------------------------------------------------------------
# AC-1/AC-2/AC-5/AC-13/AC-14: transicion 011.1 -> 012.1 sobre una instalacion
# existente, preservacion de datos y aborto ante estado parcial.
# ---------------------------------------------------------------------------

VERSION_ANTERIOR = "011.1"
CAPACIDADES_POR_INSTITUCION = len(CAPACIDADES)
TABLAS_DE_NEGOCIO = (
    "departamento",
    "usuario",
    "producto",
    "inventario",
    "movimiento_inventario",
    "ticket",
    "detalle_ticket",
    "sede",
    "stock_sede",
)


def _conteos_negocio(conexion, esquema: str) -> dict[str, int]:
    return {
        tabla: _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}".{tabla}')
        for tabla in TABLAS_DE_NEGOCIO
    }


def _degradar_a_011_1(conexion) -> None:
    """Deja la base con la **forma** de una instalacion 011.1.

    El espejo tenant vuelve a tener cuatro columnas (`rut`, `direccion`), no hay
    `activo` ni `funcion_institucion`, y control y cada tenant portan la version
    anterior. Es el estado del que parte la migracion 003 en una instalacion real.
    """
    for institucion_id in _instituciones(conexion):
        esquema = _esquema_de_institucion(institucion_id)
        _ejecutar(conexion, f'ALTER TABLE "{esquema}".sede DROP COLUMN IF EXISTS activo')
        _ejecutar(conexion, f'ALTER TABLE "{esquema}".departamento DROP COLUMN IF EXISTS activo')
        _ejecutar(
            conexion,
            f'ALTER TABLE "{esquema}".institucion '
            "ADD COLUMN IF NOT EXISTS rut VARCHAR(20), "
            "ADD COLUMN IF NOT EXISTS direccion VARCHAR(200)",
        )
        _ejecutar(
            conexion,
            f'UPDATE "{esquema}".version_esquema SET version = %s',
            (VERSION_ANTERIOR,),
        )
    _ejecutar(conexion, "DROP TABLE IF EXISTS control.funcion_institucion")
    _ejecutar(conexion, "ALTER TABLE control.institucion DROP COLUMN IF EXISTS activo")
    _ejecutar(conexion, "ALTER TABLE control.sede DROP COLUMN IF EXISTS activo")
    _ejecutar(conexion, "ALTER TABLE control.departamento DROP COLUMN IF EXISTS activo")
    _ejecutar(
        conexion,
        "UPDATE control.version_esquema SET version = %s",
        (VERSION_ANTERIOR,),
    )


def _degradar_a_012_1(conexion) -> None:
    """Deja la base con la **forma** de una instalacion 012.1 existente.

    El constructor vigente nace en la version objetivo (hoy `013.1`, Feature
    013), pero la migracion 003 de esta suite ejercita su propia fase de la
    cadena (`012.1`, `VERSION_MIGRACION_012`); devuelve control y cada tenant a
    ese token conservando la estructura 012 completa. Las estructuras 013
    (estado `Anulado`, `historial_transicion_ticket`) no molestan: la 003 no las
    conoce ni las toca.
    """
    for institucion_id in _instituciones(conexion):
        esquema = _esquema_de_institucion(institucion_id)
        _ejecutar(
            conexion,
            f'UPDATE "{esquema}".version_esquema SET version = %s',
            (VERSION_MIGRACION_012,),
        )
    _ejecutar(
        conexion,
        "UPDATE control.version_esquema SET version = %s",
        (VERSION_MIGRACION_012,),
    )


def test_migracion_012_transiciona_una_instalacion_011_1_preservando_datos():
    """AC-1/AC-2/AC-5/AC-13: 011.1 -> 012.1 con datos, mapas y espejo intactos."""
    _existe_archivo(MIGRACION_012)
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

        _degradar_a_011_1(conexion)
        instituciones = _instituciones(conexion)
        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_ANTERIOR,)
        ]
        antes = {inst: _conteos_negocio(conexion, _esquema_de_institucion(inst)) for inst in instituciones}
        mapa_antes = _un_escalar(conexion, "SELECT count(*) FROM control.mapa_usuario_esquema")

        _ejecutar_script(conexion, MIGRACION_012)

        # (control) activo, seis capacidades por institucion y la version que
        # fija la migracion 003 (`VERSION_MIGRACION_012`, fase de la cadena).
        assert "activo" in _columnas_de_tabla(conexion, "control", "institucion")
        assert _un_escalar(conexion, "SELECT count(*) FROM control.funcion_institucion") == (
            len(instituciones) * CAPACIDADES_POR_INSTITUCION
        )
        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_MIGRACION_012,)
        ]

        for institucion_id in instituciones:
            esquema = _esquema_de_institucion(institucion_id)
            # espejo reducido a las dos columnas aprobadas y sin capacidades.
            assert _columnas_de_tabla(conexion, esquema, "institucion") == COLUMNAS_ESPEJO
            assert "funcion_institucion" not in _tablas_del_esquema(conexion, esquema)
            # estado logico en sede/departamento.
            assert "activo" in _columnas_de_tabla(conexion, esquema, "sede")
            assert "activo" in _columnas_de_tabla(conexion, esquema, "departamento")
            assert _ejecutar(conexion, f'SELECT version FROM "{esquema}".version_esquema') == [
                (VERSION_MIGRACION_012,)
            ]
            # datos de negocio preservados fila a fila.
            assert _conteos_negocio(conexion, esquema) == antes[institucion_id], institucion_id

        assert _un_escalar(conexion, "SELECT count(*) FROM control.mapa_usuario_esquema") == mapa_antes


def test_migracion_012_aborta_ante_estado_parcial_sin_marcar_version():
    """AC-14: un tenant con estructura 012 sin versionar aborta sin marcar nada."""
    _existe_archivo(MIGRACION_012)
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)
        # El constructor nace en la version objetivo vigente (013.1 desde la
        # Feature 013); la 003 ejercita su propia fase de la cadena.
        _degradar_a_012_1(conexion)

        institucion_id = _instituciones(conexion)[0]
        esquema = _esquema_de_institucion(institucion_id)
        # Estructura 012 (sede.activo) con la version de vuelta en 011.1.
        _ejecutar(
            conexion,
            f'UPDATE "{esquema}".version_esquema SET version = %s',
            (VERSION_ANTERIOR,),
        )

        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION_012)
        conexion.rollback()
        assert "parcial" in str(excinfo.value).lower(), excinfo.value

        # Ninguna version queda parcialmente marcada.
        assert _ejecutar(conexion, "SELECT version FROM control.version_esquema") == [
            (VERSION_MIGRACION_012,)
        ]
        assert _un_escalar(
            conexion, f'SELECT version FROM "{esquema}".version_esquema'
        ) == VERSION_ANTERIOR
