"""T8 (Feature 012): contrato OpenAPI del CRUD organizacional nuevo.

Seam bajo prueba: `/openapi.json` (`app.openapi()`). Cierra AC-13 para las nueve
operaciones nuevas del Administrador institucional (`diseno-tecnico.md` §1.2):
`response_model`, codigo de exito, errores documentados y seguridad presente.

La matriz central (roles por operacion) se verifica en `test_permisos_012.py`
(transcripcion a mano, no-regresion de las 28 entradas vigentes); aqui solo se fija
el extremo del contrato: que cada operacion publique su forma.
"""

from __future__ import annotations

from app.main import app

#: (metodo, ruta, codigo_exito, documenta_409, documenta_422).
OPERACIONES = (
    ("post", "/api/v1/organizacion/sedes", "201", True, True),
    ("put", "/api/v1/organizacion/sedes/{sede_id}", "200", False, True),
    ("patch", "/api/v1/organizacion/sedes/{sede_id}/estado", "200", True, False),
    ("get", "/api/v1/organizacion/departamentos", "200", False, False),
    ("post", "/api/v1/organizacion/departamentos", "201", False, True),
    ("put", "/api/v1/organizacion/departamentos/{departamento_id}", "200", False, True),
    (
        "patch",
        "/api/v1/organizacion/departamentos/{departamento_id}/estado",
        "200",
        True,
        False,
    ),
    ("put", "/api/v1/usuarios/{usuario_id}", "200", False, True),
    ("patch", "/api/v1/usuarios/{usuario_id}/estado", "200", True, False),
)


def _operacion(metodo: str, ruta: str) -> dict:
    operacion = app.openapi().get("paths", {}).get(ruta, {}).get(metodo)
    assert operacion is not None, f"falta {metodo.upper()} {ruta} en /openapi.json"
    return operacion


def test_openapi_publica_las_rutas_organizacionales_nuevas():
    for metodo, ruta, _exito, _c409, _c422 in OPERACIONES:
        _operacion(metodo, ruta)


def test_openapi_declara_el_codigo_de_exito():
    for metodo, ruta, exito, _c409, _c422 in OPERACIONES:
        assert exito in _operacion(metodo, ruta).get("responses", {}), (metodo, ruta)


def test_openapi_documenta_401_y_403():
    """AC-13: toda operacion administrativa documenta 401 (sesion) y 403 (rol)."""
    for metodo, ruta, _exito, _c409, _c422 in OPERACIONES:
        respuestas = _operacion(metodo, ruta).get("responses", {})
        assert "401" in respuestas, (metodo, ruta, "sin 401")
        assert "403" in respuestas, (metodo, ruta, "sin 403")


def test_openapi_documenta_404_en_las_operaciones_con_recurso():
    for metodo, ruta, _exito, _c409, _c422 in OPERACIONES:
        assert "404" in _operacion(metodo, ruta).get("responses", {}), (metodo, ruta)


def test_openapi_documenta_409_cuando_corresponde():
    for metodo, ruta, _exito, documenta_409, _c422 in OPERACIONES:
        if not documenta_409:
            continue
        assert "409" in _operacion(metodo, ruta).get("responses", {}), (metodo, ruta)


def test_openapi_documenta_422_cuando_hay_payload():
    for metodo, ruta, _exito, _c409, documenta_422 in OPERACIONES:
        if not documenta_422:
            continue
        assert "422" in _operacion(metodo, ruta).get("responses", {}), (metodo, ruta)


def test_openapi_declara_response_model_de_exito():
    """AC-13: las operaciones con cuerpo de exito publican `response_model`."""
    for metodo, ruta, exito, _c409, _c422 in OPERACIONES:
        esquema = (
            _operacion(metodo, ruta)
            .get("responses", {})
            .get(exito, {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        assert esquema, (metodo, ruta, "sin response_model")


def test_openapi_exige_bearer_en_las_operaciones_nuevas():
    for metodo, ruta, _exito, _c409, _c422 in OPERACIONES:
        assert _operacion(metodo, ruta).get("security"), (metodo, ruta, "sin security")
