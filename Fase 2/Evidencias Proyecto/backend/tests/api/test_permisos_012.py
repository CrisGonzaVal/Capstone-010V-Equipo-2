"""T2 (Feature 012): la matriz central conserva las 28 operaciones y agrega la
gestion administrativa (control SaaS + CRUD organizacional).

Seam bajo prueba: la **matriz central** (`app.core.permisos.MATRIZ_PERMISOS`).
La matriz de referencia se transcribe **a mano** desde la spec/plan (nunca se lee
de `MATRIZ_PERMISOS`), que es la fuente de verdad independiente que evita una
prueba tautologica.

Estado: la Feature 012 NO modifica ninguna de las 28 operaciones vigentes. Solo
agrega operaciones nuevas: las de control SaaS del Superadmin y el CRUD
organizacional del Administrador institucional (plan §2, diseno-tecnico.md §1).

Fase ROJA de TDD: las operaciones nuevas aun no estan declaradas en
`MATRIZ_PERMISOS` (las cablea T6/T7), por eso las pruebas fallan por esa capacidad
ausente —con `AssertionError` o un `pytest.fail` explicito— nunca por importacion
ni sintaxis.
"""

from __future__ import annotations

import pytest

from app.core import permisos

# ---------------------------------------------------------------------------
# Fuente de verdad independiente: la matriz 012 transcrita a mano
# ---------------------------------------------------------------------------

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}
_INVENTARIO_Y_TICKETS = {"Superadmin", "Administrador", "Bodeguero"}
_ESCRITURA_CATALOGO = {"Administrador"}
_ESCRITURA_STOCK = {"Administrador", "Bodeguero"}
_ESCRITURA_TICKETS = {"Administrador", "Bodeguero", "Solicitante"}
_ALTA_INSTITUCION = {"Superadmin"}
_ORGANIZACION = {"Administrador"}

#: Las 28 operaciones vigentes tras las Features 007..011 (referencia exacta de
#: no-modificacion). La 012 no cambia ninguna.
MATRIZ_010: dict[tuple[str, str], set[str]] = {
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
    ("POST", "/api/v1/control/instituciones/"): _ALTA_INSTITUCION,
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

#: Operaciones nuevas de control SaaS (Superadmin), diseno-tecnico.md §1.
OPERACIONES_CONTROL_012: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/control/instituciones/"): _ALTA_INSTITUCION,
    ("GET", "/api/v1/control/instituciones/{institucion_id}"): _ALTA_INSTITUCION,
    ("PUT", "/api/v1/control/instituciones/{institucion_id}"): _ALTA_INSTITUCION,
    ("PATCH", "/api/v1/control/instituciones/{institucion_id}/estado"): _ALTA_INSTITUCION,
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

#: Operaciones nuevas de CRUD organizacional (Administrador), diseno-tecnico.md §1.2.
OPERACIONES_ORGANIZACION_012: dict[tuple[str, str], set[str]] = {
    ("POST", "/api/v1/organizacion/sedes"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/sedes/{sede_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/organizacion/sedes/{sede_id}/estado"): _ORGANIZACION,
    ("GET", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("POST", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/organizacion/departamentos/{departamento_id}/estado"): _ORGANIZACION,
    ("PUT", "/api/v1/usuarios/{usuario_id}"): _ADMINISTRATIVOS,
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): _ADMINISTRATIVOS,
}

MATRIZ_012: dict[tuple[str, str], set[str]] = {
    **MATRIZ_010,
    **OPERACIONES_CONTROL_012,
    **OPERACIONES_ORGANIZACION_012,
}

_OPERACIONES_NUEVAS = set(OPERACIONES_CONTROL_012) | set(OPERACIONES_ORGANIZACION_012)


def _exigir_nuevas() -> None:
    """Falla con mensaje explicito si las operaciones de la 012 aun no estan."""
    ausentes = _OPERACIONES_NUEVAS - set(permisos.MATRIZ_PERMISOS)
    if ausentes:
        pytest.fail(
            "capacidad ausente (T6/T7): MATRIZ_PERMISOS debe declarar las "
            f"operaciones de la 012; faltan {sorted(ausentes)}."
        )


# ---------------------------------------------------------------------------
# Transcripcion y no-regresion
# ---------------------------------------------------------------------------


def test_baseline_010_tiene_28_operaciones():
    assert len(MATRIZ_010) == 28


def test_matriz_012_transcrita_es_aditiva():
    assert len(MATRIZ_012) == 28 + len(_OPERACIONES_NUEVAS)
    assert set(MATRIZ_012) - set(MATRIZ_010) == _OPERACIONES_NUEVAS
    for clave, roles in MATRIZ_010.items():
        assert MATRIZ_012[clave] == roles, clave


# ---------------------------------------------------------------------------
# La matriz central es exactamente la 012 (28 + nuevas)
# ---------------------------------------------------------------------------


def test_matriz_central_conserva_las_28_operaciones():
    """AC-13: la 012 no retira ni relaja ninguna de las 28 entradas vigentes."""
    for clave, roles in MATRIZ_010.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion {clave} desaparecio de la matriz"
        assert set(actual) == roles, clave


def test_matriz_central_es_la_esperada_para_012():
    _exigir_nuevas()
    assert {
        clave: set(roles) for clave, roles in permisos.MATRIZ_PERMISOS.items()
    } == MATRIZ_012


def test_operaciones_control_012_son_solo_superadmin():
    """AC-1/AC-5/AC-13: el control SaaS es exclusivo del Superadmin."""
    _exigir_nuevas()
    for clave, roles in OPERACIONES_CONTROL_012.items():
        permitidos = permisos.MATRIZ_PERMISOS.get(clave)
        assert permitidos is not None, clave
        assert set(permitidos) == roles, clave
        for otro in ("Administrador", "Bodeguero", "Solicitante"):
            assert otro not in permitidos, (clave, otro)


def test_operaciones_organizacion_012_conservan_sus_roles():
    """AC-6..AC-11/AC-13: el CRUD organizacional es de Administrador (usuario
    mantiene el rol administrativo existente de `/usuarios/`)."""
    _exigir_nuevas()
    for clave, roles in OPERACIONES_ORGANIZACION_012.items():
        permitidos = permisos.MATRIZ_PERMISOS.get(clave)
        assert permitidos is not None, clave
        assert set(permitidos) == roles, clave
