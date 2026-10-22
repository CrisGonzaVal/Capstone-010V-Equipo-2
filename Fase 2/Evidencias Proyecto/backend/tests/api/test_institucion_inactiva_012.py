"""T2 (Feature 012): institucion inactiva deniega (401) antes de tenant/version.

Seam bajo prueba: `app.services.tenant_service` y la dependencia
`app.api.dependencies.get_contexto_solicitud`. Una institucion inactiva
(`InstitucionControl.activo = False`) no resuelve identidad: la operacion tenant
deniega como identidad local no resoluble, **401**, incluso con la version del
tenant en el objetivo (D-2, diseno-tecnico.md §4).

Fase ROJA de TDD: `InstitucionControl.activo` y la consulta previa a la version
aun no existen (T3/T5); cada prueba falla por esa capacidad ausente o por la
ausencia del comportamiento esperado, nunca por importacion ni sintaxis.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.models.control import MapaUsuarioEsquema, VersionEsquema
from app.models.usuario import Usuario
from app.services import tenant_service
from app.services.auth_service import IdentidadAutenticada

_VACIO = "capacidad ausente (T3/T5): {}".format


def _control_canonico():
    try:
        return importlib.import_module("app.models.control_canonico")
    except ImportError:
        pytest.fail(
            "capacidad ausente (T3): falta app.models.control_canonico "
            "(InstitucionControl.activo)."
        )


def _preparar(motor, *, activo: bool, con_version: bool = True) -> None:
    modulo = _control_canonico()
    base_control = getattr(modulo, "BaseControl", None)
    institucion_control = getattr(modulo, "InstitucionControl", None)
    if base_control is None or institucion_control is None:
        pytest.fail(_VACIO("BaseControl/InstitucionControl"))
    base_control.metadata.create_all(motor, checkfirst=True)

    db = sessionmaker(bind=motor)()
    try:
        db.add(
            institucion_control(
                institucion_id="INST01", nombre="Instituto Uno", activo=activo
            )
        )
        # El canonico de control y el mapa viven en `MetaData` distintos, asi que
        # el orden de INSERT no se infiere de la FK en el contexto logico unico de
        # SQLite: se fuerza con un `flush` para no disparar la FK del mapa.
        db.flush()
        db.add(
            MapaUsuarioEsquema(
                correo="u.inst01@compustock.cl",
                institucion_id="INST01",
                nombre_esquema="tenant_inst01",
                activo=True,
            )
        )
        if con_version:
            db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        db.commit()
    finally:
        db.close()


def _identidad(correo: str, rol: str = "Administrador") -> IdentidadAutenticada:
    from app.models.rol import Rol

    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Inactiva",
        correo=correo,
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-012")


# ---------------------------------------------------------------------------
# Servicio: institucion inactiva no resuelve tenant
# ---------------------------------------------------------------------------


def test_institucion_inactiva_no_resuelve_tenant(motor):
    """AC-2: con version objetivo pero institucion inactiva, no hay resolucion."""
    _preparar(motor, activo=False)
    db = sessionmaker(bind=motor)()
    try:
        with pytest.raises(tenant_service.ErrorTenant):
            tenant_service.resolver_tenant_por_correo(db, "u.inst01@compustock.cl")
    finally:
        db.close()


def test_contexto_solicitud_deniega_institucion_inactiva(motor):
    _preparar(motor, activo=False)
    db = sessionmaker(bind=motor)()
    try:
        with pytest.raises(tenant_service.ErrorTenant):
            tenant_service.resolver_contexto_solicitud(db, "u.inst01@compustock.cl")
    finally:
        db.close()


def test_institucion_activa_resuelve_tenant(motor):
    """Control: una institucion activa y versionada si resuelve."""
    _preparar(motor, activo=True)
    db = sessionmaker(bind=motor)()
    try:
        resolucion = tenant_service.resolver_tenant_por_correo(
            db, "u.inst01@compustock.cl"
        )
        assert resolucion.nombre_esquema == "tenant_inst01"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# HTTP: 401 (identidad local no resoluble), no 403
# ---------------------------------------------------------------------------


def _cliente_probe(motor, correo: str, rol: str = "Administrador") -> TestClient:
    app_probe = FastAPI()

    @app_probe.get("/sonda")
    def sonda(_contexto: object = Depends(dependencies.get_contexto_solicitud)):
        return {"ok": True}

    def _db():
        sesion = sessionmaker(bind=motor)()
        try:
            yield sesion
        finally:
            sesion.close()

    app_probe.dependency_overrides[dependencies.get_db] = _db
    app_probe.dependency_overrides[dependencies.get_current_user] = (
        lambda: _identidad(correo, rol)
    )
    return TestClient(app_probe, raise_server_exceptions=False)


def test_http_institucion_inactiva_responde_401(motor):
    """AC-2/D-7: institucion inactiva -> 401 (no 403 ni 200)."""
    _preparar(motor, activo=False)
    cliente = _cliente_probe(motor, "u.inst01@compustock.cl")
    respuesta = cliente.get("/sonda")
    assert respuesta.status_code == 401, respuesta.text


def test_http_institucion_activa_responde_200(motor):
    _preparar(motor, activo=True)
    cliente = _cliente_probe(motor, "u.inst01@compustock.cl")
    respuesta = cliente.get("/sonda")
    assert respuesta.status_code == 200, respuesta.text
