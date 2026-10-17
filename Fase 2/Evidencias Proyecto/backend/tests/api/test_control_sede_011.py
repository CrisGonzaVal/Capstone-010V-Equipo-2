"""T2 (Feature 011): version objetivo y aprovisionamiento con sede inicial.

Seam bajo prueba: la **operacion HTTP real** `POST /api/v1/control/instituciones/`
sobre el `app` real (contexto logico unico de SQLite) mas las funciones publicas de
`app.services.control_service` para el porton de version.

La Feature 011 anade DDL a cada tenant, de modo que sube el token objetivo a
`011.1` (spec AC-12) y un tenant nuevo debe nacer **operativo**: sin CRUD de sedes
(eso es la Feature 012), el aprovisionamiento crea automaticamente la sede inicial
"Sede Central" (spec D-5).

Trazabilidad AC (spec 011 §5):

  * **AC-12** estructura, version, aprovisionamiento e instalacion.

Fase ROJA de TDD: el token sigue en `010.1` y el aprovisionamiento no crea sedes
(T6); cada prueba falla con un motivo explicito.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import config
from app.main import app
from app.models import Rol, Usuario, VersionEsquema
from app.services import control_service
from app.services.auth_service import IdentidadAutenticada

from ._soporte_sede_011 import (
    NOMBRE_SEDE_CENTRAL,
    VERSION_OBJETIVO_011,
    modelo,
    sesion,
)

RUTA_ALTA = "/api/v1/control/instituciones/"

#: Institucion e identidad del alta de prueba.
INSTITUCION_NUEVA = "INST-011-T"
CORREO_ADMINISTRADOR = "admin.sede011@compustock.cl"

_CUERPO_ALTA = {
    "institucion_id": INSTITUCION_NUEVA,
    "nombre": "Institucion Con Sede Inicial",
    "correo_administrador": CORREO_ADMINISTRADOR,
    "nombre_administrador": "Ada",
    "apellido_administrador": "Administradora",
    "departamento_nombre_administrativo": "Administracion",
}


def _identidad_superadmin() -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="ControlSede011",
        correo="sonda.control.sede011@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Superadmin")
    return IdentidadAutenticada(usuario=usuario, sub="sub-control-sede-011")


@contextmanager
def _cliente_alta(motor):
    """`TestClient` del app real con la costura Clerk resuelta (correo existente)."""
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = _identidad_superadmin
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda correo: True)
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-12: token objetivo y porton de version
# ---------------------------------------------------------------------------


def test_version_objetivo_es_011_1():
    """AC-12: el token de despliegue sube con el DDL de la Feature 011."""
    assert config.VERSION_ESQUEMA_OBJETIVO == VERSION_OBJETIVO_011


def test_tenant_con_la_version_anterior_no_es_objetivo(motor):
    """AC-12: un tenant que quedo en `010.1` no se enruta (cierre fallido).

    Es el efecto observable de subir el token: la version anterior deja de ser
    compatible y el tenant queda fuera hasta migrarlo.
    """
    with sesion(motor) as db:
        db.add(VersionEsquema(version="010.1"))
        db.commit()
        assert control_service.tenant_en_version_objetivo(db) is False


def test_tenant_en_version_011_1_es_objetivo(motor):
    """AC-12: la version nueva exacta si habilita el enrutamiento."""
    with sesion(motor) as db:
        db.add(VersionEsquema(version=VERSION_OBJETIVO_011))
        db.commit()
        assert control_service.tenant_en_version_objetivo(db) is True


# ---------------------------------------------------------------------------
# AC-12: el tenant nuevo nace con "Sede Central"
# ---------------------------------------------------------------------------


def test_aprovisionamiento_crea_la_sede_inicial(motor):
    """AC-12: el alta deja una sede inicial para que el tenant sea operable.

    Sin CRUD de sedes (Feature 012) un tenant sin sedes no podria operar: el
    aprovisionamiento crea "Sede Central" como semilla de arranque (D-5).
    """
    Sede = modelo("Sede")

    with _cliente_alta(motor) as cliente_http:
        respuesta = cliente_http.post(RUTA_ALTA, json=_CUERPO_ALTA)

    assert respuesta.status_code == 201, respuesta.text

    with sesion(motor) as db:
        sedes = (
            db.execute(select(Sede).where(Sede.institucion_id == INSTITUCION_NUEVA))
            .scalars()
            .all()
        )
    assert len(sedes) == 1, "el tenant nuevo recibe exactamente una sede inicial"
    assert sedes[0].nombre == NOMBRE_SEDE_CENTRAL


def test_aprovisionamiento_responde_la_version_011_1(motor):
    """AC-12: la respuesta del alta declara el token objetivo vigente."""
    modelo("Sede")

    with _cliente_alta(motor) as cliente_http:
        respuesta = cliente_http.post(RUTA_ALTA, json=_CUERPO_ALTA)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["version_esquema"] == VERSION_OBJETIVO_011

    with sesion(motor) as db:
        versiones = db.execute(select(VersionEsquema.version)).scalars().all()
    assert VERSION_OBJETIVO_011 in versiones, (
        "el tenant aprovisionado queda en la version objetivo"
    )


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_alta_sigue_siendo_solo_de_superadmin(motor, rol):
    """AC-12 (regresion): la 011 no relaja la autorizacion del alta."""
    usuario = Usuario(
        usuario_id=2,
        nombre="Sonda",
        apellido="NoSuperadmin",
        correo="sonda.no.superadmin@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)

    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = (
        lambda: IdentidadAutenticada(usuario=usuario, sub="sub-no-superadmin")
    )
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda correo: True)
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            respuesta = cliente_http.post(RUTA_ALTA, json=_CUERPO_ALTA)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 403, (rol, respuesta.text)
