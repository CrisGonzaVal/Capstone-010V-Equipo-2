"""T2 (Feature 012): contrato OpenAPI de la gestion administrativa.

Seam bajo prueba: `/openapi.json` (`app.openapi()`). Fija el contrato de las rutas
nuevas de `/control` (Superadmin SaaS, diseno-tecnico.md §1) antes de que exista
router, servicio o schema. Fase ROJA de TDD: las rutas aun no se publican (T6), de
modo que cada prueba falla por la **ruta ausente** con un motivo legible, nunca por
importacion ni sintaxis.
"""

from __future__ import annotations

from app.main import app

#: (metodo, ruta, codigo de exito) de las operaciones de control nuevas.
OPERACIONES_CONTROL = (
    ("get", "/api/v1/control/instituciones/", "200"),
    ("get", "/api/v1/control/instituciones/{institucion_id}", "200"),
    ("put", "/api/v1/control/instituciones/{institucion_id}", "200"),
    ("patch", "/api/v1/control/instituciones/{institucion_id}/estado", "200"),
    ("get", "/api/v1/control/dashboard", "200"),
    ("get", "/api/v1/control/instituciones/{institucion_id}/capacidades", "200"),
    (
        "put",
        "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}",
        "200",
    ),
)


def _contrato() -> dict:
    return app.openapi()


def _operacion(metodo: str, ruta: str) -> dict:
    contrato = _contrato()
    ruta_contrato = contrato.get("paths", {}).get(ruta)
    if ruta_contrato is None:
        raise AssertionError(
            f"capacidad ausente (T6): la ruta {ruta} debe publicarse en /openapi.json."
        )
    operacion = ruta_contrato.get(metodo)
    if operacion is None:
        raise AssertionError(
            f"capacidad ausente (T6): {metodo.upper()} {ruta} no figura en "
            "/openapi.json."
        )
    return operacion


def test_openapi_publica_las_rutas_de_control():
    for metodo, ruta, _codigo in OPERACIONES_CONTROL:
        _operacion(metodo, ruta)


def test_openapi_declara_el_codigo_de_exito_de_cada_operacion():
    for metodo, ruta, codigo in OPERACIONES_CONTROL:
        operacion = _operacion(metodo, ruta)
        assert codigo in operacion.get("responses", {}), (metodo, ruta)


def test_openapi_documenta_401_y_403_en_las_operaciones_de_control():
    """AC-13: toda operacion administrativa documenta 401 (sesion) y 403 (rol)."""
    for metodo, ruta, _codigo in OPERACIONES_CONTROL:
        respuestas = _operacion(metodo, ruta).get("responses", {})
        assert "401" in respuestas, (metodo, ruta)
        assert "403" in respuestas, (metodo, ruta)


def test_openapi_declara_el_read_model_de_exito():
    """AC-13: las rutas exitosas publican `response_model` explicito (200)."""
    for metodo, ruta, codigo in OPERACIONES_CONTROL:
        respuestas = _operacion(metodo, ruta).get("responses", {})
        esquema_exito = (
            respuestas.get(codigo, {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        assert esquema_exito, (metodo, ruta, "sin response_model en 200")


def test_openapi_las_operaciones_de_control_exigen_bearer():
    for metodo, ruta, _codigo in OPERACIONES_CONTROL:
        operacion = _operacion(metodo, ruta)
        assert operacion.get("security"), (metodo, ruta, "sin security")
