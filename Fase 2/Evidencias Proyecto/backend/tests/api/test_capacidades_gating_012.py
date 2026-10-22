"""T2 (Feature 012): mapa central capacidad<->operacion y gating 403 adicional.

Seam bajo prueba: `app.core.capacidades` (mapa central) y la dependencia
`app.api.dependencies.requiere_capacidad` (diseno-tecnico.md §2). La capacidad es
una **condicion adicional** a la matriz: rol sin permiso -> 403 por matriz;
capacidad apagada -> 403 sin mutacion.

Fase ROJA de TDD: el modulo de capacidades y la dependencia aun no existen
(T5/T6); cada prueba falla por esa capacidad ausente con un motivo legible, nunca
por importacion ni sintaxis.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.services.tenant_service import ContextoSolicitud

#: Asociacion operacion -> capacidad (fuente de verdad independiente).
MAPA_ESPERADO: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/inventario/categorias"): "catalogo",
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): "catalogo",
    ("GET", "/api/v1/inventario/productos"): "catalogo",
    ("GET", "/api/v1/inventario/productos/{producto_id}"): "catalogo",
    ("POST", "/api/v1/inventario/productos"): "catalogo",
    ("GET", "/api/v1/inventario/existencias"): "inventario",
    ("GET", "/api/v1/inventario/stock"): "inventario",
    ("GET", "/api/v1/inventario/movimientos"): "inventario",
    ("POST", "/api/v1/inventario/movimientos"): "inventario",
    ("GET", "/api/v1/tickets/catalogos"): "tickets",
    ("GET", "/api/v1/tickets/"): "tickets",
    ("POST", "/api/v1/tickets/"): "tickets",
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): "kanban",
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): "kanban",
    ("GET", "/api/v1/dashboard/"): "dashboard",
    ("GET", "/api/v1/organizacion/sedes"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}/sede"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/usuarios/{usuario_id}/sede"): "gestion_organizacional",
    ("GET", "/api/v1/organizacion/departamentos/{departamento_id}/encargados"): "gestion_organizacional",
    ("POST", "/api/v1/organizacion/departamentos/{departamento_id}/encargados"): "gestion_organizacional",
    ("DELETE", "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}"): "gestion_organizacional",
    ("POST", "/api/v1/organizacion/sedes"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/sedes/{sede_id}"): "gestion_organizacional",
    ("PATCH", "/api/v1/organizacion/sedes/{sede_id}/estado"): "gestion_organizacional",
    ("GET", "/api/v1/organizacion/departamentos"): "gestion_organizacional",
    ("POST", "/api/v1/organizacion/departamentos"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}"): "gestion_organizacional",
    ("PATCH", "/api/v1/organizacion/departamentos/{departamento_id}/estado"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/"): "gestion_organizacional",
    ("POST", "/api/v1/usuarios/"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/roles"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/departamentos"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/instituciones"): "gestion_organizacional",
    ("PUT", "/api/v1/usuarios/{usuario_id}"): "gestion_organizacional",
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): "gestion_organizacional",
}

SIN_CAPACIDAD = (
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/control/instituciones/"),
    ("GET", "/api/v1/control/dashboard"),
    ("POST", "/api/v1/control/instituciones/"),
    ("PUT", "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}"),
)


def _capacidades():
    try:
        return importlib.import_module("app.core.capacidades")
    except ImportError:
        pytest.fail("capacidad ausente (T5): falta el modulo app.core.capacidades.")


def _exigir_requiere_capacidad():
    dependencia = getattr(dependencies, "requiere_capacidad", None)
    if dependencia is None:
        pytest.fail(
            "capacidad ausente (T5): app.api.dependencies.requiere_capacidad no existe."
        )
    return dependencia


# ---------------------------------------------------------------------------
# Mapa central
# ---------------------------------------------------------------------------


def test_mapa_central_cubre_las_operaciones_asociadas():
    capacidades = _capacidades()
    for clave, funcion in MAPA_ESPERADO.items():
        obtenido = capacidades.capacidad_de_operacion(*clave)
        assert obtenido == funcion, (clave, obtenido, funcion)


def test_operaciones_sin_capacidad_no_se_gatean():
    capacidades = _capacidades()
    for clave in SIN_CAPACIDAD:
        assert capacidades.capacidad_de_operacion(*clave) is None, clave


def test_conjunto_cerrado_de_capacidades():
    capacidades = _capacidades()
    assert set(capacidades.CAPACIDADES) == {
        "catalogo",
        "inventario",
        "tickets",
        "kanban",
        "dashboard",
        "gestion_organizacional",
    }


# ---------------------------------------------------------------------------
# Gating 403 adicional (probe HTTP)
# ---------------------------------------------------------------------------


def _contexto() -> ContextoSolicitud:
    return ContextoSolicitud(
        correo="admin@inst01.cl",
        institucion_id="INST01",
        nombre_esquema="tenant_inst01",
        version=VERSION_ESQUEMA_OBJETIVO,
    )


def _cliente_probe(motor, *, habilitada: bool):
    funcion_modelo = None
    institucion_modelo = None
    for candidato in ("app.models.control_canonico",):
        try:
            modulo = importlib.import_module(candidato)
        except ImportError:
            modulo = None
        if modulo is not None:
            funcion_modelo = getattr(modulo, "FuncionInstitucion", None)
            institucion_modelo = getattr(modulo, "InstitucionControl", None)
        if funcion_modelo is not None:
            break
    if funcion_modelo is None or institucion_modelo is None:
        pytest.fail(
            "capacidad ausente (T3): falta FuncionInstitucion/InstitucionControl "
            "para poblar capacidades."
        )

    db = sessionmaker(bind=motor)()
    try:
        # `funcion_institucion` referencia `institucion.institucion_id`; en el
        # contexto logico unico de SQLite hay que crear primero la institucion
        # canonica. Los `MetaData` son distintos, asi que el orden de INSERT no
        # se infiere de la FK: se fuerza con `flush` antes de la capacidad.
        db.add(institucion_modelo(institucion_id="INST01", nombre="Instituto Uno"))
        db.flush()
        db.add(
            funcion_modelo(
                institucion_id="INST01", funcion="catalogo", habilitada=habilitada
            )
        )
        db.commit()
    finally:
        db.close()

    requiere_capacidad = _exigir_requiere_capacidad()
    app_probe = FastAPI()
    dependencia = requiere_capacidad("POST", "/api/v1/inventario/productos")

    @app_probe.post(
        "/api/v1/inventario/productos", dependencies=[Depends(dependencia)]
    )
    def sonda():
        return {"ok": True}

    def _db():
        sesion = sessionmaker(bind=motor)()
        try:
            yield sesion
        finally:
            sesion.close()

    laboratorio = {
        "get_db": _db,
        "get_contexto_capacidad": _contexto,
    }
    for nombre, valor in laboratorio.items():
        original = getattr(dependencies, nombre)
        app_probe.dependency_overrides[original] = valor
    return TestClient(app_probe)


def test_capacidad_apagada_responde_403(motor):
    cliente = _cliente_probe(motor, habilitada=False)
    respuesta = cliente.post("/api/v1/inventario/productos")
    assert respuesta.status_code == 403, respuesta.text


def test_capacidad_encendida_no_bloquea(motor):
    cliente = _cliente_probe(motor, habilitada=True)
    respuesta = cliente.post("/api/v1/inventario/productos")
    assert respuesta.status_code == 200, respuesta.text
