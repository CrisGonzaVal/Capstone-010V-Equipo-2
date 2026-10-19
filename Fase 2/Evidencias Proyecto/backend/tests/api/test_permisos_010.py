"""T2 (Feature 010): la matriz de permisos declara el alta de institución.

Seam bajo prueba: la **matriz central** (`app.core.permisos`) y la dependencia
HTTP (`app.api.dependencies.requiere_operacion`). La matriz de referencia se
transcribe **a mano** desde la spec 010 (no se lee de `MATRIZ_PERMISOS`), que es
la fuente de verdad independiente que evita una prueba tautológica. Las 22
operaciones son las 21 vigentes (007/008/009) más el alta de institución:

    POST /api/v1/control/instituciones/  ->  solo Superadmin

Es la **única** incorporación de la 010 a la matriz y no relaja ninguna operación
existente (D-7, AC-7…AC-9, AC-17). El alta se autoriza con la matriz central, no
con un flag de confianza del cliente.

Fase ROJA de TDD: la operación todavía no está declarada en `MATRIZ_PERMISOS`
(la cablea T7), por eso las pruebas fallan por esa capacidad ausente —con
`AssertionError` o un `pytest.fail` explícito— nunca por importación ni sintaxis.
Las otras tres suites de transcripción (`test_permisos.py`, `test_permisos_008.py`,
`test_permisos_endpoints.py`) se mantienen intactas en esta tarea: su
reconciliación a 22 operaciones corresponde a T7, cuando el `app` publique la
ruta y la suite previa deba seguir verde sin regresiones.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos
from app.models import Rol, Usuario
from app.services.auth_service import IdentidadAutenticada

# ---------------------------------------------------------------------------
# Fuente de verdad independiente: la matriz 010 transcrita a mano
# ---------------------------------------------------------------------------

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}
_INVENTARIO_Y_TICKETS = {"Superadmin", "Administrador", "Bodeguero"}
_ESCRITURA_CATALOGO = {"Administrador"}
_ESCRITURA_STOCK = {"Administrador", "Bodeguero"}
_ESCRITURA_TICKETS = {"Administrador", "Bodeguero", "Solicitante"}
#: Alta de institución (Feature 010, D-7): solo Superadmin.
_ALTA_INSTITUCION = {"Superadmin"}
#: Gestion organizacional (Feature 011, D-4/D-5): solo Administrador institucional.
_ORGANIZACION = {"Administrador"}
#: Ciclo de vida del ticket (Feature 013, AC-17): anulacion y edicion las opera
#: el dueño del ticket (Solicitante) junto con el Administrador institucional.
_ANULACION_Y_EDICION = {"Administrador", "Solicitante"}
#: Ciclo de vida del ticket (Feature 013, AC-17): rechazo, operativo de bodega.
_RECHAZO = {"Administrador", "Bodeguero"}

#: Operación contractual del alta de institución (plan §1).
OPERACION_ALTA: tuple[str, str] = ("POST", "/api/v1/control/instituciones/")

#: Operaciones que la Feature 011 agrega despues de la 010 a la matriz central.
OPERACIONES_011: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/organizacion/sedes"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}/sede"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/usuarios/{usuario_id}/sede"): _ORGANIZACION,
    (
        "GET",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): _ORGANIZACION,
    (
        "POST",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): _ORGANIZACION,
    (
        "DELETE",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}",
    ): _ORGANIZACION,
}

#: Operaciones nuevas de control SaaS de la Feature 012 (T6), solo Superadmin.
OPERACIONES_012_CONTROL: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/control/instituciones/"): _ALTA_INSTITUCION,
    ("GET", "/api/v1/control/instituciones/{institucion_id}"): _ALTA_INSTITUCION,
    ("PUT", "/api/v1/control/instituciones/{institucion_id}"): _ALTA_INSTITUCION,
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/estado",
    ): _ALTA_INSTITUCION,
    ("GET", "/api/v1/control/dashboard"): _ALTA_INSTITUCION,
    (
        "GET",
        "/api/v1/control/instituciones/{institucion_id}/capacidades",
    ): _ALTA_INSTITUCION,
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}",
    ): _ALTA_INSTITUCION,
}

#: Operaciones nuevas de CRUD organizacional de la Feature 012 (T7). El
#: Administrador institucional administra `/organizacion/*`; las operaciones de
#: `/usuarios/` las comparte con Superadmin.
OPERACIONES_012_ORGANIZACION: dict[tuple[str, str], set[str]] = {
    ("POST", "/api/v1/organizacion/sedes"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/sedes/{sede_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/organizacion/sedes/{sede_id}/estado"): _ORGANIZACION,
    ("GET", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("POST", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}"): _ORGANIZACION,
    (
        "PATCH",
        "/api/v1/organizacion/departamentos/{departamento_id}/estado",
    ): _ORGANIZACION,
    ("PUT", "/api/v1/usuarios/{usuario_id}"): _ADMINISTRATIVOS,
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): _ADMINISTRATIVOS,
}

#: Matriz vigente tras las Features 008/009, SIN el alta de la 010 (21 operaciones).
MATRIZ_009: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/auth/me"): _TODOS,
    ("GET", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("POST", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/roles"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/departamentos"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/instituciones"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/inventario/categorias"): _TODOS,
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): _TODOS,
    ("GET", "/api/v1/inventario/productos"): _TODOS,
    ("GET", "/api/v1/inventario/productos/{producto_id}"): _TODOS,
    ("POST", "/api/v1/inventario/productos"): _ESCRITURA_CATALOGO,
    ("GET", "/api/v1/inventario/existencias"): _TODOS,
    ("GET", "/api/v1/inventario/stock"): _TODOS,
    ("GET", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    ("POST", "/api/v1/inventario/movimientos"): _ESCRITURA_STOCK,
    ("GET", "/api/v1/tickets/catalogos"): _TODOS,
    ("GET", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/"): _ESCRITURA_TICKETS,
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _ESCRITURA_STOCK,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _ESCRITURA_STOCK,
    ("GET", "/api/v1/dashboard/"): _TODOS,
}

#: Operaciones nuevas del ciclo de vida de la Feature 013 (T6, AC-17): la
#: anulacion y la edicion las opera el dueño del ticket (Solicitante) mas el
#: Administrador; el rechazo, el Bodeguero mas el Administrador; detalle e
#: historial son lectura de los cuatro roles. Superadmin queda sin escritura.
OPERACIONES_013: dict[tuple[str, str], set[str]] = {
    ("POST", "/api/v1/tickets/{ticket_id}/anulacion"): _ANULACION_Y_EDICION,
    ("POST", "/api/v1/tickets/{ticket_id}/rechazo"): _RECHAZO,
    ("PUT", "/api/v1/tickets/{ticket_id}"): _ANULACION_Y_EDICION,
    ("GET", "/api/v1/tickets/{ticket_id}"): _TODOS,
    ("GET", "/api/v1/tickets/{ticket_id}/historial"): _TODOS,
}

#: Matriz vigente tras añadir el alta de institución, las seis asignaciones
#: organizacionales de la 011 y las cinco operaciones de ciclo de vida de la 013
#: (49 operaciones).
MATRIZ_010: dict[tuple[str, str], set[str]] = {
    **MATRIZ_009,
    OPERACION_ALTA: _ALTA_INSTITUCION,
    **OPERACIONES_011,
    **OPERACIONES_012_CONTROL,
    **OPERACIONES_012_ORGANIZACION,
    **OPERACIONES_013,
}

_ROLES = ("Superadmin", "Administrador", "Bodeguero", "Solicitante")


# ---------------------------------------------------------------------------
# Helpers: identidad simulada, app sonda y override de base de datos
# ---------------------------------------------------------------------------


def _identidad(rol: str | None) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Matriz010",
        correo="sonda.matriz010@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-matriz-010")


def _override_db(motor):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    return obtener_db


def _exigir_matriz() -> None:
    """Falla con mensaje explícito si la operación aún no está declarada.

    Evita que construir la dependencia lance un `KeyError` crudo: T2 exige que las
    pruebas rojas fallen por la capacidad ausente con un motivo legible.
    """
    if OPERACION_ALTA not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            "capacidad ausente (T7): MATRIZ_PERMISOS debe declarar "
            f"{OPERACION_ALTA} {sorted(_ALTA_INSTITUCION)}; aun no figura."
        )


def _app_sonda() -> FastAPI:
    app_sonda = FastAPI()
    dependencia = dependencies.requiere_operacion(*OPERACION_ALTA)

    @app_sonda.api_route(
        OPERACION_ALTA[1], methods=[OPERACION_ALTA[0]], dependencies=[Depends(dependencia)]
    )
    def sonda():
        return {"ok": True}

    return app_sonda


def _cliente(app_sonda: FastAPI, motor, rol: str | None = None, *, autenticar=False):
    app_sonda.dependency_overrides[dependencies.get_db] = _override_db(motor)
    if autenticar:
        app_sonda.dependency_overrides[dependencies.get_current_user] = (
            lambda: _identidad(rol)
        )
    return TestClient(app_sonda)


# ---------------------------------------------------------------------------
# La matriz central es exactamente la de la 010 (22 operaciones)
# ---------------------------------------------------------------------------


def test_matriz_010_transcrita_tiene_28_operaciones():
    assert len(MATRIZ_010) == (
        28
        + len(OPERACIONES_012_CONTROL)
        + len(OPERACIONES_012_ORGANIZACION)
        + len(OPERACIONES_013)
    )
    assert len(MATRIZ_009) == 21


def test_matriz_central_es_la_esperada_para_010():
    assert {
        clave: set(roles) for clave, roles in permisos.MATRIZ_PERMISOS.items()
    } == MATRIZ_010


def test_alta_institucion_es_la_unica_operacion_agregada_por_010():
    assert (
        set(MATRIZ_010)
        - set(MATRIZ_009)
        - set(OPERACIONES_011)
        - set(OPERACIONES_012_CONTROL)
        - set(OPERACIONES_012_ORGANIZACION)
        - set(OPERACIONES_013)
        == {OPERACION_ALTA}
    )
    assert MATRIZ_010[OPERACION_ALTA] == _ALTA_INSTITUCION


def test_010_no_relaja_el_resto_de_la_matriz():
    """La incorporación del alta no altera ninguna operación previa."""
    for clave, roles in MATRIZ_009.items():
        assert MATRIZ_010[clave] == roles, clave


def test_alta_de_institucion_es_solo_para_superadmin():
    """AC-7/AC-9/AC-17: la operación se declara y solo la concede Superadmin."""
    permitidos = permisos.MATRIZ_PERMISOS.get(OPERACION_ALTA)
    assert permitidos is not None, (
        "la operación de alta debe declararse en MATRIZ_PERMISOS"
    )
    assert set(permitidos) == _ALTA_INSTITUCION
    for rol in ("Administrador", "Bodeguero", "Solicitante"):
        assert rol not in permitidos


# ---------------------------------------------------------------------------
# HTTP: allow/deny de la dependencia para el alta (D-5/D-7)
# ---------------------------------------------------------------------------


def test_alta_permite_a_superadmin(motor):
    _exigir_matriz()
    cliente = _cliente(_app_sonda(), motor, "Superadmin", autenticar=True)
    respuesta = cliente.request(*OPERACION_ALTA)
    assert respuesta.status_code == 200, respuesta.text


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_alta_deniega_a_rol_no_superadmin(motor, rol):
    _exigir_matriz()
    cliente = _cliente(_app_sonda(), motor, rol, autenticar=True)
    respuesta = cliente.request(*OPERACION_ALTA)
    assert respuesta.status_code == 403, (rol, respuesta.text)


def test_alta_sin_sesion_responde_401(motor):
    _exigir_matriz()
    cliente = _cliente(_app_sonda(), motor)
    respuesta = cliente.request(*OPERACION_ALTA)
    assert respuesta.status_code == 401, respuesta.text
