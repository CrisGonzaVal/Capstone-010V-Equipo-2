"""T2 (Feature 013): migracion 012.1 -> 013.1, constructor y token de version - gated.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs ni el
DDL por esquema, asi que lo que la Feature 013 exige del catalogo replicado y
del historial solo se acredita contra PostgreSQL 16 real:

  * **Migracion `012.1 -> 013.1`** (`004_migracion_ciclo_vida_ticket_013.sql`)
    sobre una instalacion existente: `Anulado` presente en control y en cada
    tenant, `historial_transicion_ticket` creada en control y en cada tenant,
    datos y mapas intactos, sin filas de historial fabricadas (AC-12),
    reejecucion sin cambios (idempotencia) y preflight que aborta ante
    estructura 013 parcial sin marcar version.
  * **Constructor/initdb** (`01 -> 02 -> 03` recien levantado): los tenants
    nacen en `013.1` con `Anulado` replicado y la tabla creada.
  * **Token de version**: un tenant en `012.1` deniega en cerrado con el
    objetivo `013.1`; solo se enrutan tenants exactamente en la version
    objetivo (AC-21).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_ciclo_vida_ticket_postgres_013.py

Fase ROJA de TDD: la migracion 004, la fila `Anulado` de la semilla, la tabla
del historial en DDL/constructor y el token `013.1` aun no existen (T4/T5), de
modo que cada prueba falla por esa ausencia (`_existe_archivo` o asercion),
nunca por un error de sintaxis del test.
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
MIGRACION_013 = (
    RAIZ / "database" / "migraciones" / "004_migracion_ciclo_vida_ticket_013.sql"
)

#: Version anterior de una instalacion existente (la que fija la 012).
VERSION_ANTERIOR = "012.1"
#: Estado nuevo del catalogo y tabla nueva del historial (spec D-1/D-10).
ESTADO_ANULADO = "Anulado"
TABLA_HISTORIAL = "historial_transicion_ticket"

#: Tablas de negocio cuyo dato debe sobrevivir a la migracion (sin DELETE).
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


def _existe_archivo(ruta: Path) -> None:
    if not ruta.exists():
        pytest.fail(
            f"capacidad ausente (T5): falta el script {ruta.name}; la Feature 013 "
            "lo crea en T5 y hasta entonces esta prueba esta en rojo."
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


def _conteos_de_negocio(conexion, esquema: str) -> dict[str, int]:
    return {
        tabla: _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}".{tabla}')
        for tabla in TABLAS_DE_NEGOCIO
    }


def _degradar_a_012_1(conexion) -> None:
    """Deja la base con la **forma** de una instalacion 012.1 existente.

    Retira el estado `Anulado` y la tabla del historial de control y de cada
    tenant, y vuelve la version a `012.1`. Es el estado del que parte la
    migracion 004 en una base real.
    """
    for institucion_id in _instituciones(conexion):
        esquema = _esquema_de_institucion(institucion_id)
        _ejecutar(conexion, f'DROP TABLE IF EXISTS "{esquema}".{TABLA_HISTORIAL}')
        _ejecutar(
            conexion,
            f"DELETE FROM \"{esquema}\".estado_ticket WHERE nombre = %s",
            (ESTADO_ANULADO,),
        )
        _ejecutar(
            conexion,
            f'UPDATE "{esquema}".version_esquema SET version = %s',
            (VERSION_ANTERIOR,),
        )
    _ejecutar(conexion, f"DROP TABLE IF EXISTS control.{TABLA_HISTORIAL}")
    _ejecutar(
        conexion,
        "DELETE FROM control.estado_ticket WHERE nombre = %s",
        (ESTADO_ANULADO,),
    )
    _ejecutar(
        conexion, "UPDATE control.version_esquema SET version = %s", (VERSION_ANTERIOR,)
    )


def _instalacion_012_1(conexion) -> list[str]:
    """01 -> 02 -> 03 y degradacion a 012.1; devuelve las instituciones."""
    _ejecutar_script(conexion, ESQUEMA_SQL)
    _ejecutar_script(conexion, SEMILLA_SQL)
    _ejecutar_script(conexion, CONSTRUCTOR_SQL)
    _degradar_a_012_1(conexion)
    return _instituciones(conexion)


def _version_de(conexion, esquema: str) -> str:
    return _un_escalar(conexion, f'SELECT version FROM "{esquema}".version_esquema')


def _version_de_control(conexion) -> str:
    return _un_escalar(conexion, "SELECT version FROM control.version_esquema")


def _assert_013_en_todos_los_esquemas(conexion) -> None:
    objetivo = VERSION_ESQUEMA_OBJETIVO
    assert _version_de_control(conexion) == objetivo, "control debe quedar versionada"
    for institucion_id in _instituciones(conexion):
        esquema = _esquema_de_institucion(institucion_id)
        assert _version_de(conexion, esquema) == objetivo, institucion_id
        assert ESTADO_ANULADO in {
            fila[0]
            for fila in _ejecutar(
                conexion, f'SELECT nombre FROM "{esquema}".estado_ticket'
            )
        }, f"{esquema} sin el estado {ESTADO_ANULADO}"
        assert TABLA_HISTORIAL in _tablas_del_esquema(conexion, esquema), esquema
    assert ESTADO_ANULADO in {
        fila[0]
        for fila in _ejecutar(conexion, "SELECT nombre FROM control.estado_ticket")
    }, "control sin el estado Anulado"
    assert TABLA_HISTORIAL in _tablas_del_esquema(conexion, "control")


# ---------------------------------------------------------------------------
# AC-20/AC-21: token de version del codigo
# ---------------------------------------------------------------------------


def test_el_codigo_apunta_a_la_version_013_1():
    """AC-20/AC-21: `VERSION_ESQUEMA_OBJETIVO` sube de `012.1` a `013.1` (T5)."""
    assert VERSION_ESQUEMA_OBJETIVO == "013.1", VERSION_ESQUEMA_OBJETIVO


# ---------------------------------------------------------------------------
# AC-20: instalacion nueva (constructor/initdb)
# ---------------------------------------------------------------------------


def test_instalacion_nueva_replica_anulado_e_historial_en_control_y_tenants():
    """AC-20: `01 -> 02 -> 03` crea la tabla y siembra `Anulado` en cada esquema."""
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

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
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

        assert _un_escalar(
            conexion, f"SELECT count(*) FROM control.{TABLA_HISTORIAL}"
        ) == 0
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _un_escalar(
                conexion, f'SELECT count(*) FROM "{esquema}".{TABLA_HISTORIAL}'
            ) == 0, esquema


# ---------------------------------------------------------------------------
# AC-20: migracion operacional 012.1 -> 013.1
# ---------------------------------------------------------------------------


def test_migracion_013_es_idempotente():
    """AC-20: la migracion es re-ejecutable sin cambios ni duplicados."""
    _existe_archivo(MIGRACION_013)
    with _base_temporal() as conexion:
        instituciones = _instalacion_012_1(conexion)

        _ejecutar_script(conexion, MIGRACION_013)
        estados_despues = {
            institucion_id: _un_escalar(
                conexion,
                "SELECT count(*) FROM "
                f'"{_esquema_de_institucion(institucion_id)}".estado_ticket',
            )
            for institucion_id in instituciones
        }
        _ejecutar_script(conexion, MIGRACION_013)

        assert _version_de_control(conexion) == VERSION_ESQUEMA_OBJETIVO
        for institucion_id in instituciones:
            esquema = _esquema_de_institucion(institucion_id)
            assert _un_escalar(
                conexion, f'SELECT count(*) FROM "{esquema}".estado_ticket'
            ) == estados_despues[institucion_id], (
                "la segunda ejecucion no debe duplicar filas del catalogo"
            )
        assert _un_escalar(
            conexion,
            "SELECT count(*) FROM control.estado_ticket WHERE nombre = %s",
            (ESTADO_ANULADO,),
        ) == 1, "la segunda ejecucion no debe duplicar el estado Anulado"
        _assert_013_en_todos_los_esquemas(conexion)


def test_migracion_013_transiciona_012_1_preservando_datos_sin_fabricar_historial():
    """AC-20/AC-12: 012.1 -> 013.1 con datos intactos y sin trazabilidad inventada."""
    _existe_archivo(MIGRACION_013)
    with _base_temporal() as conexion:
        instituciones = _instalacion_012_1(conexion)
        antes = {
            institucion_id: _conteos_de_negocio(
                conexion, _esquema_de_institucion(institucion_id)
            )
            for institucion_id in instituciones
        }
        mapa_antes = _un_escalar(conexion, "SELECT count(*) FROM control.mapa_usuario_esquema")
        assert _version_de_control(conexion) == VERSION_ANTERIOR

        _ejecutar_script(conexion, MIGRACION_013)

        _assert_013_en_todos_los_esquemas(conexion)
        for institucion_id in instituciones:
            esquema = _esquema_de_institucion(institucion_id)
            assert _conteos_de_negocio(conexion, esquema) == antes[institucion_id], (
                "los datos de negocio no pueden perderse ni duplicarse"
            )
            assert _un_escalar(
                conexion, f'SELECT count(*) FROM "{esquema}".{TABLA_HISTORIAL}'
            ) == 0, "sin filas de historial fabricadas (AC-12)"
        assert _un_escalar(
            conexion, "SELECT count(*) FROM control.mapa_usuario_esquema"
        ) == mapa_antes, "el mapa de usuarios no cambia"


def test_migracion_013_aborta_ante_estructura_parcial_sin_marcar_version():
    """AC-20/AC-21: preflight fail-closed; sin version parcial ante 013 parcial."""
    _existe_archivo(MIGRACION_013)
    with _base_temporal() as conexion:
        instituciones = _instalacion_012_1(conexion)
        esquema_parcial = _esquema_de_institucion(instituciones[0])
        # Estructura 013 parcial en un solo tenant, sin versionar.
        _ejecutar(
            conexion,
            f'CREATE TABLE "{esquema_parcial}".{TABLA_HISTORIAL} '
            "(solo_estructura_parcial INTEGER)",
        )

        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION_013)
        conexion.rollback()
        assert "parcial" in str(excinfo.value).lower(), excinfo.value

        # Ninguna version queda marcada: todo sigue en 012.1.
        assert _version_de_control(conexion) == VERSION_ANTERIOR
        for institucion_id in instituciones:
            esquema = _esquema_de_institucion(institucion_id)
            assert _version_de(conexion, esquema) == VERSION_ANTERIOR, esquema


# ---------------------------------------------------------------------------
# AC-21: token de version en el routing
# ---------------------------------------------------------------------------


def _motor_sqlalchemy(conexion):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # psycopg2 2.9+ no expone `password` en `get_dsn_parameters()`; se reutiliza
    # la URL original del harness solo cambiando el nombre de la base.
    nombre_base = conexion.get_dsn_parameters()["dbname"]
    url = _url_con_base(_POSTGRES_TEST_URL or "", nombre_base)
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
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)
        _ejecutar_script(conexion, CONSTRUCTOR_SQL)

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
