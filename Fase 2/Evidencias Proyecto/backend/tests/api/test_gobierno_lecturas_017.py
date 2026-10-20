"""T8 (Feature 017): matriz central, denegacion Superadmin y contrato OpenAPI.

Seam bajo prueba: la **matriz central** (`app.core.permisos.MATRIZ_PERMISOS`,
transcrita a mano desde D-9/AC-15, nunca leida como fuente), el contrato
`/openapi.json` y la **interfaz HTTP del `app` real**.

Fase ROJA de TDD: hoy la matriz conserva a Superadmin en las lecturas de
negocio de AC-15 y la API le responde 200 con datos. Los tests fallan por esa
conducta (403 esperado), no por imports ni sintaxis.
"""

from __future__ import annotations

import pytest

from app.core import permisos
from app.main import app

from ._soporte_sede_011 import cliente

#: Roles de negocio que conservan cada lectura retirada al Superadmin (D-9:
#: "Los roles de negocio conservan sus permisos y ambitos").
_ADMIN_BODEGA_SOLICITANTE = frozenset(
    {"Administrador", "Bodeguero", "Solicitante"}
)
_ADMIN_BODEGA = frozenset({"Administrador", "Bodeguero"})

#: Lista CERRADA de D-9/AC-15: operacion retirada -> roles que la conservan.
#: T10 anade `GET /tickets/catalogos`: es una lectura de negocio interna (lista
#: productos, stock y solicitantes del tenant) y la unica superficie de
#: Superadmin es `/control/*` mas la gestion de Administradores.
OPERACIONES_RETIRADAS_017: dict[tuple[str, str], frozenset[str]] = {
    ("GET", "/api/v1/dashboard/"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/tickets/catalogos"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/tickets/"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/tickets/{ticket_id}"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/tickets/{ticket_id}/historial"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/inventario/movimientos"): _ADMIN_BODEGA,
    ("GET", "/api/v1/inventario/categorias"): _ADMIN_BODEGA_SOLICITANTE,
    (
        "GET",
        "/api/v1/inventario/categorias/{categoria_id}",
    ): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/inventario/productos"): _ADMIN_BODEGA_SOLICITANTE,
    (
        "GET",
        "/api/v1/inventario/productos/{producto_id}",
    ): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/inventario/existencias"): _ADMIN_BODEGA_SOLICITANTE,
    ("GET", "/api/v1/inventario/stock"): _ADMIN_BODEGA_SOLICITANTE,
}

#: Las cinco operaciones D-10 (gobierno de Administradores): solo Superadmin.
OPERACIONES_CONTROL_017: dict[tuple[str, str], str] = {
    (
        "GET",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): "AdministradorListadoControlRespuesta",
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): "UsuarioInvitacionRespuesta",
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}",
    ): "UsuarioRespuesta",
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    ): "UsuarioRespuesta",
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
        "/invitacion/reenvio",
    ): "UsuarioInvitacionRespuesta",
}

#: Errores publicados por operacion de control (D-10).
_ERRORES_CONTROL_017: dict[tuple[str, str], frozenset[str]] = {
    ("GET", "/api/v1/control/instituciones/{institucion_id}/usuarios/"): frozenset(
        {"401", "403", "404", "503"}
    ),
    ("POST", "/api/v1/control/instituciones/{institucion_id}/usuarios/"): frozenset(
        {"401", "403", "404", "409", "422", "503"}
    ),
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}",
    ): frozenset({"401", "403", "404", "409", "422", "503"}),
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    ): frozenset({"401", "403", "404", "409", "422", "503"}),
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
        "/invitacion/reenvio",
    ): frozenset({"401", "403", "404", "409", "422", "503"}),
}

#: Codigo de exito contractual de cada operacion D-10.
_EXITO_CONTROL_017: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/control/instituciones/{institucion_id}/usuarios/"): "200",
    ("POST", "/api/v1/control/instituciones/{institucion_id}/usuarios/"): "201",
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}",
    ): "200",
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    ): "200",
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
        "/invitacion/reenvio",
    ): "200",
}

_METODOS_OPENAPI = {"get", "put", "post", "delete", "patch"}
_PREFIJO_CONTRATO = "/api/v1/"


def _nombre_modelo(esquema: dict | None) -> str | None:
    """Nombre del `$ref` de un esquema OpenAPI (directo o dentro de un array)."""
    if not esquema:
        return None
    if "$ref" in esquema:
        return str(esquema["$ref"]).rsplit("/", 1)[-1]
    items = esquema.get("items") or {}
    if "$ref" in items:
        return str(items["$ref"]).rsplit("/", 1)[-1]
    return None


def _operacion_openapi(metodo: str, ruta: str) -> dict:
    operacion = app.openapi().get("paths", {}).get(ruta, {}).get(metodo.lower())
    if operacion is None:
        pytest.fail(f"capacidad ausente: {metodo.upper()} {ruta} no esta en /openapi.json")
    return operacion


# ---------------------------------------------------------------------------
# AC-15/AC-17: matriz central — retirada a Superadmin y roles preservados
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("clave", sorted(OPERACIONES_RETIRADAS_017), ids=str)
def test_superadmin_denegado_en_cada_lectura_de_negocio_ac_15(clave):
    """AC-15/AC-17: la matriz deniega Superadmin en cada operacion de D-9."""
    roles = permisos.MATRIZ_PERMISOS.get(clave)
    assert roles is not None, f"la operacion {clave} desaparecio de la matriz"
    assert "Superadmin" not in roles, f"{clave} conserva Superadmin: {sorted(roles)}"


@pytest.mark.parametrize("clave", sorted(OPERACIONES_RETIRADAS_017), ids=str)
def test_los_roles_de_negocio_conservan_su_lectura_ac_15(clave):
    """AC-15: la retirada es solo del Superadmin; los demas roles no cambian."""
    roles = permisos.MATRIZ_PERMISOS.get(clave)
    assert roles is not None, f"la operacion {clave} desaparecio de la matriz"
    assert set(roles) == set(OPERACIONES_RETIRADAS_017[clave]), (
        clave,
        sorted(roles),
    )


def test_la_matriz_central_es_aditiva_y_sigue_con_55_operaciones_ac_17():
    """AC-17: la matriz vigente suma el reenvio ordinario de la 017 (55 filas)."""
    assert len(permisos.MATRIZ_PERMISOS) == 55


def test_comparacion_automatizada_ac_15_deniega_toda_operacion_retirada_ac_17():
    """AC-17: cada operacion de AC-15 esta denegada a Superadmin en la matriz.

    La comparacion recorre la lista cerrada de D-9 contra `MATRIZ_PERMISOS` sin
    leer los roles esperados de la propia matriz: si una entrada falta o concede
    Superadmin, el test falla.
    """
    denegadas: list[tuple[str, str]] = []
    for clave in OPERACIONES_RETIRADAS_017:
        roles = permisos.MATRIZ_PERMISOS.get(clave)
        if roles is not None and not permisos.rol_autorizado("Superadmin", roles):
            denegadas.append(clave)
    assert set(denegadas) == set(OPERACIONES_RETIRADAS_017), (
        "operaciones de AC-15 que aun conceden Superadmin: "
        f"{sorted(set(OPERACIONES_RETIRADAS_017) - set(denegadas))}"
    )


def test_las_cinco_operaciones_de_control_son_solo_superadmin_ac_8():
    """AC-8: las cinco rutas D-10 se autorizan exclusivamente por Superadmin."""
    for clave in OPERACIONES_CONTROL_017:
        roles = permisos.MATRIZ_PERMISOS.get(clave)
        assert roles is not None, f"capacidad ausente: la matriz no declara {clave}"
        assert set(roles) == {"Superadmin"}, (clave, sorted(roles))


# ---------------------------------------------------------------------------
# AC-15: la API real deniega a Superadmin y no devuelve datos de negocio
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metodo,ruta",
    sorted(OPERACIONES_RETIRADAS_017),
    ids=[f"{metodo} {ruta}" for metodo, ruta in sorted(OPERACIONES_RETIRADAS_017)],
)
def test_api_real_deniega_superadmin_sin_datos_ac_15(
    motor, dos_instituciones, metodo, ruta
):
    """AC-15: Superadmin recibe 403 antes de leer; el cuerpo no trae negocio."""
    concreta = ruta.replace("{ticket_id}", "1").replace(
        "{categoria_id}", str(dos_instituciones["categoria_id"])
    ).replace("{producto_id}", str(dos_instituciones["producto_id"]))

    with cliente(motor, "Superadmin", departamento_id=None) as cliente_http:
        respuesta = cliente_http.request(metodo, concreta)

    assert respuesta.status_code == 403, (metodo, ruta, respuesta.text)
    assert respuesta.json() == {"detail": "Permiso insuficiente para la operacion"}
    assert not isinstance(respuesta.json(), list), "el 403 no puede devolver una lista"
    for campo_negocio in ("tickets", "productos", "movimientos", "kpis", "sedes"):
        assert campo_negocio not in respuesta.json()


# ---------------------------------------------------------------------------
# AC-17: contrato OpenAPI de las cinco operaciones nuevas de control (D-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("clave", sorted(OPERACIONES_CONTROL_017), ids=str)
def test_openapi_publica_la_operacion_control_con_metodo_y_ruta_ac_17(clave):
    metodo, ruta = clave
    _operacion_openapi(metodo, ruta)


@pytest.mark.parametrize("clave", sorted(OPERACIONES_CONTROL_017), ids=str)
def test_openapi_declara_el_codigo_de_exito_de_la_operacion_control_ac_17(clave):
    metodo, ruta = clave
    operacion = _operacion_openapi(metodo, ruta)
    codigo = _EXITO_CONTROL_017[clave]
    assert codigo in operacion.get("responses", {}), (clave, codigo)


@pytest.mark.parametrize("clave", sorted(OPERACIONES_CONTROL_017), ids=str)
def test_openapi_declara_el_response_model_de_exito_de_control_ac_17(clave):
    metodo, ruta = clave
    operacion = _operacion_openapi(metodo, ruta)
    codigo = _EXITO_CONTROL_017[clave]
    esquema = (
        operacion.get("responses", {})
        .get(codigo, {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    assert _nombre_modelo(esquema) == OPERACIONES_CONTROL_017[clave], (
        clave,
        esquema,
    )


@pytest.mark.parametrize("clave", sorted(OPERACIONES_CONTROL_017), ids=str)
def test_openapi_documenta_los_errores_declarados_de_control_ac_17(clave):
    metodo, ruta = clave
    operacion = _operacion_openapi(metodo, ruta)
    publicadas = set(operacion.get("responses", {}))
    assert _ERRORES_CONTROL_017[clave] <= publicadas, (
        clave,
        sorted(_ERRORES_CONTROL_017[clave] - publicadas),
    )


@pytest.mark.parametrize("clave", sorted(OPERACIONES_CONTROL_017), ids=str)
def test_openapi_las_operaciones_de_control_exigen_bearer_ac_17(clave):
    metodo, ruta = clave
    operacion = _operacion_openapi(metodo, ruta)
    assert operacion.get("security"), (clave, "sin seguridad declarada")


# ---------------------------------------------------------------------------
# AC-17: contrato OpenAPI de las lecturas retiradas (403 documentado)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("clave", sorted(OPERACIONES_RETIRADAS_017), ids=str)
def test_openapi_documenta_401_403_y_seguridad_en_las_lecturas_retiradas_ac_17(clave):
    metodo, ruta = clave
    operacion = _operacion_openapi(metodo, ruta)
    respuestas = set(operacion.get("responses", {}))
    assert {"401", "403"} <= respuestas, (clave, sorted(respuestas))
    assert operacion.get("security"), (clave, "sin seguridad declarada")
    esquema = (
        operacion.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    assert esquema, (clave, "sin response_model de exito")


def test_openapi_no_publica_lecturas_de_negocio_para_superadmin_ac_15():
    """AC-15/AC-17: el contrato v1 real coincide con las 54 entradas de matriz."""
    contrato = app.openapi()
    operaciones = {
        (metodo.upper(), ruta)
        for ruta, fila in contrato.get("paths", {}).items()
        if ruta.startswith(_PREFIJO_CONTRATO)
        for metodo in fila
        if metodo in _METODOS_OPENAPI
    }
    assert operaciones == set(permisos.MATRIZ_PERMISOS), (
        sorted(operaciones - set(permisos.MATRIZ_PERMISOS)),
        sorted(set(permisos.MATRIZ_PERMISOS) - operaciones),
    )
