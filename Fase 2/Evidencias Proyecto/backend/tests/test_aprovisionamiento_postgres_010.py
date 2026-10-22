"""Feature 010 (O-1): el tenant aprovisionado tiene el rol `Administrador` unico.

Complemento gated PostgreSQL 16 de `test_aprovisionamiento_010.py` (SQLite). La
duplicacion del rol solo se manifiesta en el aprovisionamiento real por esquemas
(`_provisionar_tenant_postgres`): alli la replica del catalogo publica
`Administrador` y, antes de la correccion, el usuario inicial creaba un **segundo**
registro, dejando el rol duplicado en `tenant_*.rol` y apuntando al duplicado.

SQLite no reproduce el namespace por tenant, asi que el invariante
("exactamente los roles esperados, sin duplicados, y el usuario inicial apuntando
al rol del catalogo") se acredita aqui contra el motor objetivo.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_aprovisionamiento_postgres_010.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
    mantenimiento donde el test crea y DESTRUYE una base temporal propia; nunca
    toca `apt_erp`. NO se anade ninguna dependencia: `psycopg2` ya esta en
    `requirements.txt`.
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

from sqlalchemy import create_engine, select
from sqlalchemy.schema import CreateSchema

from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL, crear_sesion_control, crear_sesion_esquema
from app.models import BaseControl, Rol, Sede, Usuario, VersionEsquema
from app.schemas.control_schema import InstitucionAltaControlCrear
from app.services import control_service, tenant_service

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

#: Roles que todo tenant aprovisionado replica (D-4), en el orden del catalogo.
_ROLES_ESPERADOS = ("Administrador", "Bodeguero", "Solicitante")


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


@contextmanager
def _base_temporal(url_entrada: str):
    """Crea una base PostgreSQL efimera y la destruye al salir (nunca `apt_erp`)."""
    dsn = (url_entrada or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_o1_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    componentes = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        yield componentes
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _datos() -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id="INST-T010",
        nombre="Institucion de prueba O-1",
        rut="99-9",
        direccion="Av. Prueba 100",
        correo_administrador="admin.t010@ejemplo.cl",
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo="Administracion",
    )


def test_tenant_aprovisionado_tiene_rol_administrador_unico():
    """O-1: el tenant no duplica `Administrador` y el usuario inicial apunta a el.

    Antes de la correccion `_crear_administrador` creaba un segundo
    `Administrador` tras replicar el catalogo: el tenant quedaba con 4 filas de rol
    (Administrador x2, Bodeguero, Solicitante) y el usuario apuntaba al duplicado.
    """
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            # Feature 012: el canonico de control vive en `BaseControl`; se crea
            # primero para que `institucion` sea el superset (mirror + `activo`).
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)

            sesion_control = crear_sesion_control(engine)
            try:
                respuesta = control_service.aprovisionar_institucion(
                    sesion_control, _datos(), lambda _correo: True
                )
            finally:
                sesion_control.close()

            nombre_esquema = tenant_service.nombre_esquema_para_institucion("INST-T010")
            assert respuesta.nombre_esquema == nombre_esquema

            sesion_tenant = crear_sesion_esquema(nombre_esquema, motor=engine)
            try:
                roles = sesion_tenant.execute(select(Rol)).scalars().all()
                nombres = [rol.nombre_rol for rol in roles]
                assert sorted(nombres) == sorted(_ROLES_ESPERADOS), (
                    f"roles del tenant inesperados: {nombres}"
                )
                administradores = [r for r in roles if r.nombre_rol == "Administrador"]
                assert len(administradores) == 1, (
                    f"el tenant debe tener un solo Administrador: {nombres}"
                )

                usuario = sesion_tenant.execute(
                    select(Usuario).where(
                        Usuario.correo == "admin.t010@ejemplo.cl"
                    )
                ).scalar_one()
                assert usuario.rol_id == administradores[0].rol_id, (
                    "el usuario inicial debe apuntar al Administrador del catalogo, "
                    "no a un duplicado"
                )
                assert usuario.rol.nombre_rol == "Administrador"
            finally:
                sesion_tenant.close()
        finally:
            engine.dispose()


def test_tenant_aprovisionado_recibe_sede_central_y_version_objetivo():
    """AC-12 (T6, Feature 011): el tenant nuevo nace operativo.

    El aprovisionamiento debe crear "Sede Central" (bootstrap organizacional, no
    CRUD) y dejar una **unica** fila con la version objetivo vigente
    (`VERSION_ESQUEMA_OBJETIVO`; la Feature 012 la subio a `012.1`) para que el
    tenant sea enrutable. SQLite no reproduce el namespace por tenant, asi que el
    invariante se acredita contra PostgreSQL 16 real.
    """
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            # Feature 012: el canonico de control vive en `BaseControl`; se crea
            # primero para que `institucion` sea el superset (mirror + `activo`).
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)

            sesion_control = crear_sesion_control(engine)
            try:
                control_service.aprovisionar_institucion(
                    sesion_control, _datos(), lambda _correo: True
                )
            finally:
                sesion_control.close()

            nombre_esquema = tenant_service.nombre_esquema_para_institucion("INST-T010")
            sesion_tenant = crear_sesion_esquema(nombre_esquema, motor=engine)
            try:
                sedes = sesion_tenant.execute(select(Sede)).scalars().all()
                assert len(sedes) == 1, f"el tenant debe tener una sede inicial: {sedes}"
                assert sedes[0].nombre == "Sede Central"
                assert sedes[0].institucion_id == "INST-T010"

                versiones = (
                    sesion_tenant.execute(select(VersionEsquema.version)).scalars().all()
                )
                assert versiones == [VERSION_ESQUEMA_OBJETIVO], versiones
            finally:
                sesion_tenant.close()
        finally:
            engine.dispose()
