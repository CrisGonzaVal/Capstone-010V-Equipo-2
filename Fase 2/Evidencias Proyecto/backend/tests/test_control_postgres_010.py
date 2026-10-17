"""T3 (Feature 010): namespace real, FK locales y mapa en PostgreSQL 16.

Complemento gated de `test_control_modelo_010.py`. SQLite en memoria **no**
reproduce namespaces ni la semantica de FK/DDL de PostgreSQL, asi que lo que la
spec exige y SQLite no puede acreditar se verifica aqui contra PostgreSQL 16 real:

  * `version_esquema` es **por esquema** (namespace): dos esquemas pueden tener
    versiones distintas y la seleccion con `schema_translate_map` aisla cada una;
  * el mapa `correo -> esquema` mantiene la unicidad de `correo` y su **FK local**
    a `institucion` en PostgreSQL, y admite varias filas que comparten
    `nombre_esquema` (usuarios de una misma institucion, AC-10);
  * el DDL canonical del tenant conserva las **seis FK locales** hacia
    `institucion` dentro del mismo esquema, **sin FK cross-schema**, y admite la
    fila espejo de institucion y la replica de `rol`, `prioridad` y
    `estado_ticket` (AC-5, AC-10, AC-16).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_control_postgres_010.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan** con una razon clara y la suite
    local (SQLite) sigue verde. Se acepta tambien la forma con driver de SQLAlchemy
    (`postgresql+psycopg2://...`). Se usan esquemas temporales propios con nombre
    unico; nunca se toca `apt_erp` ni un esquema existente.

Al estilo de los tests gated de la Feature 008 (`test_migracion_postgres.py`):
misma condicion de salto y evidencia reservada al motor objetivo. NO se anade
ninguna dependencia: `psycopg2` ya esta en `requirements.txt`.
"""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

#: Tablas del DDL canonical (12 entidades 3NF) que todo tenant reproduce.
TABLAS_DOMINIO = (
    "institucion",
    "departamento",
    "rol",
    "usuario",
    "categoria",
    "producto",
    "inventario",
    "movimiento_inventario",
    "prioridad",
    "estado_ticket",
    "ticket",
    "detalle_ticket",
)

#: Las seis FK locales hacia `institucion` que el DDL canonical declara (stack §2).
TABLAS_CON_FK_INSTITUCION = (
    "departamento",
    "categoria",
    "producto",
    "inventario",
    "ticket",
    "detalle_ticket",
)


# ---------------------------------------------------------------------------
# Motor, esquemas temporales y helpers
# ---------------------------------------------------------------------------


def _url_sqlalchemy() -> str:
    url = _POSTGRES_TEST_URL or ""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


@pytest.fixture(scope="module")
def engine():
    motor = create_engine(_url_sqlalchemy(), future=True)
    try:
        yield motor
    finally:
        motor.dispose()


@contextmanager
def _esquema_temporal(motor):
    """Crea un esquema PostgreSQL efimero y lo destruye al salir."""
    nombre = f"tenant_test_{uuid4().hex[:12]}"
    with motor.begin() as conexion:
        conexion.execute(CreateSchema(nombre))
    try:
        yield nombre
    finally:
        with motor.begin() as conexion:
            conexion.execute(DropSchema(nombre, cascade=True))


def _modelo(nombre_modulo: str, nombre: str, motivo: str):
    try:
        modulo = importlib.import_module(nombre_modulo)
    except ImportError:
        pytest.fail(f"capacidad ausente (T4): falta el modulo {nombre_modulo} ({motivo}).")
    valor = getattr(modulo, nombre, None)
    if valor is None:
        pytest.fail(f"capacidad ausente (T4): {nombre_modulo}.{nombre} no existe ({motivo}).")
    return valor


def _crear_tabla_en_esquema(motor, objeto, esquema: str):
    """Crea la tabla (y sus dependencias de dominio) en `esquema`; devuelve la copia."""
    meta = MetaData()
    for tabla in objeto.__table__.metadata.tables.values():
        if tabla.name in TABLAS_DOMINIO or tabla.name == objeto.__table__.name:
            tabla.to_metadata(meta, schema=esquema)
    meta.create_all(motor)
    return meta.tables[f"{esquema}.{objeto.__table__.name}"]


# ---------------------------------------------------------------------------
# AC-5/AC-13: version_esquema por esquema (namespace real)
# ---------------------------------------------------------------------------


def test_version_esquema_es_por_esquema_y_no_global(engine):
    """Dos esquemas mantienen versiones distintas; la seleccion aisla cada una."""
    version = _modelo("app.models.control", "VersionEsquema", "version por tenant (T4)")

    with _esquema_temporal(engine) as esquema_a, _esquema_temporal(engine) as esquema_b:
        tabla_a = _crear_tabla_en_esquema(engine, version, esquema_a)
        tabla_b = _crear_tabla_en_esquema(engine, version, esquema_b)

        with engine.begin() as conexion:
            conexion.execute(tabla_a.insert().values(version="010.1"))
            conexion.execute(tabla_b.insert().values(version="009.9"))

        clave = version.__table__.schema  # `None` si el modelo no fija esquema logico
        # Conexiones **separadas** por tenant: `Connection.execution_options()`
        # muta y devuelve la misma conexion, por lo que reutilizarla haria que el
        # ultimo mapa ganara y la prueba no aislaria nada.
        with engine.connect() as con_a, engine.connect() as con_b:
            con_a = con_a.execution_options(schema_translate_map={clave: esquema_a})
            con_b = con_b.execution_options(schema_translate_map={clave: esquema_b})
            assert con_a.execute(select(version.version)).scalar_one() == "010.1"
            assert con_b.execute(select(version.version)).scalar_one() == "009.9"


# ---------------------------------------------------------------------------
# AC-6/AC-12: unicidad y FK local del mapa correo->esquema
# ---------------------------------------------------------------------------


def test_mapa_mantiene_unicidad_y_fk_local_en_postgres(engine):
    """El mapa conserva la unicidad de `correo` y su FK a `institucion` en PostgreSQL."""
    mapa = _modelo("app.models.control", "MapaUsuarioEsquema", "mapa correo->esquema (T4)")

    with _esquema_temporal(engine) as esquema:
        tabla_mapa = _crear_tabla_en_esquema(engine, mapa, esquema)
        tabla_institucion = tabla_mapa.metadata.tables.get(f"{esquema}.institucion")

        with engine.begin() as conexion:
            conexion.execute(
                tabla_institucion.insert().values(
                    institucion_id="INST01", nombre="Institucion Uno"
                )
            )
            conexion.execute(
                tabla_mapa.insert().values(
                    correo="ana@compustock.cl",
                    institucion_id="INST01",
                    nombre_esquema="tenant_inst01_deadbeef",
                    activo=True,
                )
            )

        # FK local del mapa hacia la institucion del mismo esquema.
        fks = inspect(engine).get_foreign_keys("mapa_usuario_esquema", schema=esquema)
        assert any(
            fk["referred_table"] == "institucion" and fk.get("referred_schema") == esquema
            for fk in fks
        ), fks

        # Correo repetido en otro esquema -> rechazado.
        with engine.begin() as conexion:
            conexion.execute(
                tabla_institucion.insert().values(
                    institucion_id="INST02", nombre="Institucion Dos"
                )
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conexion:
                conexion.execute(
                    tabla_mapa.insert().values(
                        correo="ana@compustock.cl",
                        institucion_id="INST02",
                        nombre_esquema="tenant_inst02_cafebabe",
                        activo=True,
                    )
                )

        # Un segundo usuario de la MISMA institucion comparte su nombre de
        # esquema: el mapa tiene una fila por usuario (AC-10). Ya no hay
        # restriccion de unicidad de `nombre_esquema`; la invariante "dos
        # instituciones no comparten esquema" se garantiza por derivacion en
        # servidor, no por la base.
        with engine.begin() as conexion:
            conexion.execute(
                tabla_mapa.insert().values(
                    correo="luis@compustock.cl",
                    institucion_id="INST01",
                    nombre_esquema="tenant_inst01_deadbeef",
                    activo=True,
                )
            )
        with engine.connect() as conexion:
            total = conexion.execute(
                select(tabla_mapa.c.correo).where(
                    tabla_mapa.c.nombre_esquema == "tenant_inst01_deadbeef"
                )
            ).all()
        assert len(total) == 2, total


# ---------------------------------------------------------------------------
# AC-1/AC-4: schema_translate_map por ejecucion y pool sin estado de tenant (T5)
# ---------------------------------------------------------------------------


def test_sesion_tenant_por_ejecucion_no_filtra_entre_conexiones_reutilizadas(engine):
    """AC-1/AC-4: el esquema efectivo es por ejecucion; el pool no guarda tenant.

    Crea dos esquemas tenant con una fila `institucion` de **igual ID** y valor
    distinto; abre sesiones con `crear_sesion_esquema` (que aplica
    `schema_translate_map={None: esquema}` sobre una copia del engine) alternando
    tenants sobre las mismas conexiones del pool y comprueba que cada una ve su
    esquema. Al cerrar, ninguna conexion del pool conserva un `search_path`
    alterado: la seleccion **no** usa `search_path`.
    """
    from app.db import database

    institucion = _modelo("app.models", "Institucion", "institucion canonica (dominio)")

    with _esquema_temporal(engine) as esquema_a, _esquema_temporal(engine) as esquema_b:
        tabla_a = _crear_tabla_en_esquema(engine, institucion, esquema_a)
        tabla_b = _crear_tabla_en_esquema(engine, institucion, esquema_b)
        with engine.begin() as conexion:
            conexion.execute(
                tabla_a.insert().values(institucion_id="INST01", nombre="Esquema Uno")
            )
            conexion.execute(
                tabla_b.insert().values(institucion_id="INST01", nombre="Esquema Dos")
            )

        def _nombre_visible(nombre_esquema: str) -> str:
            sesion = database.crear_sesion_esquema(nombre_esquema, motor=engine)
            try:
                return sesion.execute(
                    select(institucion.nombre).where(
                        institucion.institucion_id == "INST01"
                    )
                ).scalar_one()
            finally:
                sesion.close()

        # Alterna tenants repetidamente para forzar la reutilizacion del pool.
        for _ in range(3):
            assert _nombre_visible(esquema_a) == "Esquema Uno"
            assert _nombre_visible(esquema_b) == "Esquema Dos"

        # La conexion devuelta al pool no quedo con `search_path` del tenant.
        with engine.connect() as conexion:
            search_path = conexion.exec_driver_sql("SHOW search_path").scalar()
        assert esquema_a not in search_path, search_path
        assert esquema_b not in search_path, search_path


# ---------------------------------------------------------------------------
# AC-5/AC-10: DDL tenant, FK locales, espejo y catalogos
# ---------------------------------------------------------------------------


def test_ddl_tenant_tiene_seis_fk_locales_sin_cross_schema(engine):
    """Las seis FK hacia `institucion` son locales al esquema del tenant."""
    institucion = _modelo("app.models", "Institucion", "institucion canonica (dominio)")

    with _esquema_temporal(engine) as esquema:
        meta = MetaData()
        for tabla in institucion.__table__.metadata.tables.values():
            if tabla.name in TABLAS_DOMINIO:
                tabla.to_metadata(meta, schema=esquema)
        meta.create_all(engine)

        inspector = inspect(engine)
        for tabla in TABLAS_CON_FK_INSTITUCION:
            fks = inspector.get_foreign_keys(tabla, schema=esquema)
            hacia_institucion = [fk for fk in fks if fk["referred_table"] == "institucion"]
            assert hacia_institucion, (tabla, fks)
            for fk in hacia_institucion:
                assert fk.get("referred_schema") == esquema, (
                    f"FK cross-schema en {tabla}: {fk}"
                )
            # Ninguna FK del tenant apunta a un esquema distinto.
            for fk in fks:
                assert fk.get("referred_schema") in (None, esquema), (tabla, fk)

        # El DDL admite la fila espejo y la replica de catalogos por esquema.
        with engine.begin() as conexion:
            conexion.execute(
                meta.tables[f"{esquema}.institucion"].insert().values(
                    institucion_id="INST99", nombre="Espejo"
                )
            )
            conexion.execute(
                meta.tables[f"{esquema}.rol"].insert().values(nombre_rol="Administrador")
            )
            conexion.execute(
                meta.tables[f"{esquema}.prioridad"].insert().values(nombre="ALTA")
            )
            conexion.execute(
                meta.tables[f"{esquema}.estado_ticket"].insert().values(nombre="INGRESADO")
            )
        with engine.connect() as conexion:
            total = conexion.execute(
                select(meta.tables[f"{esquema}.rol"].c.rol_id)
            ).all()
        assert len(total) == 1
