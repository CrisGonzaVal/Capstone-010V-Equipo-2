"""T8 (Feature 010): bootstrap de control idempotente en PostgreSQL 16 (AC-6).

Complemento gated de `test_control_modelo_010.py`. La suite SQLite ya demuestra el
contrato logico (estructura administrativa e idempotencia sobre el contexto logico
unico); aqui se verifica contra PostgreSQL 16 real, con namespace, que el bootstrap:

  * crea la institucion/departamento administrativos, el rol Superadmin y su
    usuario sin alterar las nulabilidades `usuario.departamento_id NOT NULL` ni
    `departamento.institucion_id NOT NULL`;
  * sobre una base **con datos de negocio**, la primera y la segunda ejecucion
    dejan exactamente los mismos registros administrativos (conteos e IDs
    iguales) y **no** tocan las filas de negocio preexistentes.

COMO ACTIVARLA
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_bootstrap_control_postgres_010.py

    Sin `POSTGRES_TEST_URL` el modulo se **salta**. No se anade ninguna
    dependencia: `psycopg2` ya esta en `requirements.txt`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import create_engine, select
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.database import Base, crear_sesion_esquema
from app.models import Departamento, Institucion, Rol, Usuario
from app.services.control_service import (
    INSTITUCION_ADMINISTRATIVA_ID,
    ROL_SUPERADMIN,
    ejecutar_bootstrap_control,
)

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)


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
    nombre = f"control_test_{uuid4().hex[:12]}"
    with motor.begin() as conexion:
        conexion.execute(CreateSchema(nombre))
    try:
        yield nombre
    finally:
        with motor.begin() as conexion:
            conexion.execute(DropSchema(nombre, cascade=True))


def _foto(sesion) -> dict:
    """Conteo e identificadores de las filas administrativas y de negocio."""
    return {
        "instituciones": sorted(
            i.institucion_id for i in sesion.execute(select(Institucion)).scalars()
        ),
        "departamentos": sorted(
            d.departamento_id for d in sesion.execute(select(Departamento)).scalars()
        ),
        "usuarios": sorted(
            u.correo for u in sesion.execute(select(Usuario)).scalars()
        ),
        "roles": sorted(
            r.nombre_rol for r in sesion.execute(select(Rol)).scalars()
        ),
    }


def _superadmins(sesion) -> list[Usuario]:
    return (
        sesion.execute(select(Usuario).join(Rol).where(Rol.nombre_rol == ROL_SUPERADMIN))
        .scalars()
        .all()
    )


def _sembrar_negocio(sesion) -> None:
    """Sembrar datos de negocio que el bootstrap **no** debe alterar."""
    sesion.add(Institucion(institucion_id="NEG01", nombre="Institucion de Negocio"))
    sesion.flush()
    sesion.add(Rol(nombre_rol="Solicitante", descripcion="Rol de negocio"))
    sesion.flush()
    rol_solicitante = (
        sesion.execute(select(Rol).where(Rol.nombre_rol == "Solicitante"))
        .scalars()
        .one()
    )
    departamento = Departamento(nombre_dep="Operaciones", institucion_id="NEG01")
    sesion.add(departamento)
    sesion.flush()
    sesion.add(
        Usuario(
            nombre="Nina",
            apellido="Negocio",
            correo="nina.negocio@compustock.cl",
            departamento_id=departamento.departamento_id,
            rol_id=rol_solicitante.rol_id,
        )
    )
    sesion.commit()


def test_bootstrap_control_es_idempotente_y_no_toca_negocio(engine):
    """AC-6: dos ejecuciones dejan los mismos registros y datos de negocio intactos."""
    with _esquema_temporal(engine) as esquema:
        motor_control = engine.execution_options(schema_translate_map={None: esquema})
        Base.metadata.create_all(bind=motor_control)

        sesion = crear_sesion_esquema(esquema, motor=engine)
        try:
            _sembrar_negocio(sesion)
            foto_negocio = _foto(sesion)

            ejecutar_bootstrap_control(sesion)
            superadmins_1 = _superadmins(sesion)
            assert len(superadmins_1) == 1, "debe existir un unico usuario Superadmin"
            foto_1 = _foto(sesion)

            # El bootstrap agrega solo la estructura administrativa.
            assert INSTITUCION_ADMINISTRATIVA_ID in foto_1["instituciones"]
            assert foto_1["roles"] == sorted(foto_negocio["roles"] + [ROL_SUPERADMIN])
            assert "nina.negocio@compustock.cl" in foto_1["usuarios"]

            # Segunda ejecucion: no duplica ni altera nada.
            ejecutar_bootstrap_control(sesion)
            foto_2 = _foto(sesion)
            assert foto_2 == foto_1, (foto_1, foto_2)
            assert [u.usuario_id for u in _superadmins(sesion)] == [
                u.usuario_id for u in superadmins_1
            ]

            # Los datos de negocio siguen presentes e intactos.
            assert set(foto_negocio["instituciones"]) <= set(foto_2["instituciones"])
            assert set(foto_negocio["roles"]) <= set(foto_2["roles"])
            assert set(foto_negocio["usuarios"]) <= set(foto_2["usuarios"])
        finally:
            sesion.close()


def test_bootstrap_control_conserva_nulabilidades_del_modelo(engine):
    """AC-6: el usuario/departamento administrativos satisfacen los NOT NULL 3NF."""
    with _esquema_temporal(engine) as esquema:
        motor_control = engine.execution_options(schema_translate_map={None: esquema})
        Base.metadata.create_all(bind=motor_control)

        sesion = crear_sesion_esquema(esquema, motor=engine)
        try:
            ejecutar_bootstrap_control(sesion)

            administrador = _superadmins(sesion)[0]
            departamento = sesion.get(Departamento, administrador.departamento_id)
            assert departamento is not None
            assert departamento.institucion_id == INSTITUCION_ADMINISTRATIVA_ID
            assert sesion.get(Institucion, INSTITUCION_ADMINISTRATIVA_ID) is not None

            # Columnas siguen siendo NOT NULL en el DDL del esquema de control.
            from sqlalchemy import inspect

            columnas_usuario = {
                c["name"]: c
                for c in inspect(engine).get_columns("usuario", schema=esquema)
            }
            columnas_departamento = {
                c["name"]: c
                for c in inspect(engine).get_columns("departamento", schema=esquema)
            }
            assert columnas_usuario["departamento_id"]["nullable"] is False
            assert columnas_departamento["institucion_id"]["nullable"] is False
        finally:
            sesion.close()
