"""T5 (Feature 008): ajuste puntual de la matriz de permisos (D-3/AC-10).

Seam bajo prueba: la **matriz central** (`app.core.permisos`) y la dependencia
HTTP (`app.api.dependencies.requiere_operacion`). La matriz de referencia se
transcribe **a mano** desde la spec 008 (no se lee de `MATRIZ_PERMISOS`), que es
la fuente de verdad independiente que evita una prueba tautologica.

El ajuste de la 008 es acotado: Superadmin conserva sus lecturas globales pero
deja de escribir catalogo (producto/categoria), stock/movimientos y tickets;
esas escrituras corresponden al Administrador de la institucion (y al Bodeguero
en las operativas). El resto de la matriz 007 no cambia (se contrasta contra la
matriz 007 transcrita aparte).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos
from app.main import app
from app.models import Rol, Usuario
from app.services.auth_service import IdentidadAutenticada

# ---------------------------------------------------------------------------
# Fuente de verdad independiente: matrices 007 y 008 transcritas a mano
# ---------------------------------------------------------------------------

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}
_INVENTARIO_Y_TICKETS = {"Superadmin", "Administrador", "Bodeguero"}
_ESCRITURA_CATALOGO = {"Administrador"}
_ESCRITURA_STOCK = {"Administrador", "Bodeguero"}
_ESCRITURA_TICKETS = {"Administrador", "Bodeguero", "Solicitante"}

#: Matriz completa vigente tras el ajuste de la 008 (20 operaciones: las 18 de
#: 007 mas los dos GET por objeto de catalogo que exige AC-9/AC-16).
MATRIZ_008: dict[tuple[str, str], set[str]] = {
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
}

#: Las 5 operaciones exactamente afectadas por el ajuste 008.
OPERACIONES_AJUSTADAS = {
    ("POST", "/api/v1/inventario/productos"),
    ("POST", "/api/v1/inventario/movimientos"),
    ("POST", "/api/v1/tickets/"),
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"),
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"),
}

#: Matriz 007 (regresion): solo las operaciones NO ajustadas deben coincidir.
MATRIZ_007: dict[tuple[str, str], set[str]] = {
    **MATRIZ_008,
    ("POST", "/api/v1/inventario/productos"): _ADMINISTRATIVOS,
    ("POST", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    ("POST", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _INVENTARIO_Y_TICKETS,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _INVENTARIO_Y_TICKETS,
}

_ROLES = ("Superadmin", "Administrador", "Bodeguero", "Solicitante")


# ---------------------------------------------------------------------------
# Helpers: identidad simulada, app sonda y override de base de datos
# ---------------------------------------------------------------------------


def _identidad(rol: str | None) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Matriz008",
        correo="sonda.matriz008@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-matriz-008")


def _override_db(motor):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    return obtener_db


def _ruta_concreta(ruta: str) -> str:
    return ruta.replace("{ticket_id}", "1")


def _app_sonda(metodo: str, ruta: str) -> FastAPI:
    app_sonda = FastAPI()
    dependencia = dependencies.requiere_operacion(metodo, ruta)

    @app_sonda.api_route(ruta, methods=[metodo], dependencies=[Depends(dependencia)])
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
# La matriz central es exactamente la de la 008
# ---------------------------------------------------------------------------


def test_matriz_central_es_la_esperada_para_008():
    assert {
        clave: set(roles) for clave, roles in permisos.MATRIZ_PERMISOS.items()
    } == MATRIZ_008
    assert len(MATRIZ_008) == 20


def test_ajuste_008_es_minimo_y_acotado():
    """Solo las 5 operaciones de escritura institucional cambian respecto a 007."""
    for clave in OPERACIONES_AJUSTADAS:
        assert MATRIZ_008[clave] != MATRIZ_007[clave], clave
    for clave, roles in MATRIZ_008.items():
        if clave not in OPERACIONES_AJUSTADAS:
            assert roles == MATRIZ_007[clave], (
                f"la operacion {clave} no debia cambiar respecto a 007"
            )


def test_superadmin_deja_de_escribir_catalogo_stock_y_tickets():
    for clave in OPERACIONES_AJUSTADAS:
        assert "Superadmin" not in permisos.roles_de_operacion(*clave), clave


def test_administrador_conserva_las_escrituras_institucionales():
    for clave in OPERACIONES_AJUSTADAS:
        assert "Administrador" in permisos.roles_de_operacion(*clave), clave


# ---------------------------------------------------------------------------
# HTTP: allow/deny por rol en las operaciones ajustadas
# ---------------------------------------------------------------------------

CASOS_AJUSTADOS = [
    (metodo, ruta, rol, 200 if rol in MATRIZ_008[(metodo, ruta)] else 403)
    for (metodo, ruta) in OPERACIONES_AJUSTADAS
    for rol in _ROLES
]


@pytest.mark.parametrize("metodo,ruta,rol,esperado", CASOS_AJUSTADOS)
def test_operacion_ajustada_concede_o_deniega_por_rol(
    motor, metodo, ruta, rol, esperado
):
    cliente = _cliente(_app_sonda(metodo, ruta), motor, rol, autenticar=True)
    respuesta = cliente.request(metodo, _ruta_concreta(ruta))
    assert respuesta.status_code == esperado, (metodo, ruta, rol, respuesta.text)


def test_operacion_ajustada_sin_sesion_responde_401(motor):
    cliente = _cliente(_app_sonda("POST", "/api/v1/inventario/productos"), motor)
    respuesta = cliente.post("/api/v1/inventario/productos")
    assert respuesta.status_code == 401, respuesta.text


# ---------------------------------------------------------------------------
# Denegacion de Superadmin sin mutacion (contra el app real)
# ---------------------------------------------------------------------------


@contextmanager
def _cliente_real(motor, rol: str, departamento_id):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="Real",
        correo="sonda.real.008@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    identidad = IdentidadAutenticada(usuario=usuario, sub="sub-real-008")

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: identidad
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def test_superadmin_no_muta_catalogo_stock_ni_tickets(motor, datos_base):
    """El 403 de Superadmin en escritura institucional no deja filas nuevas."""
    before = {}
    after = {}

    with _cliente_real(motor, "Superadmin", None) as cliente:
        before["productos"] = len(cliente.get("/api/v1/inventario/productos").json())
        before["movimientos"] = len(
            cliente.get("/api/v1/inventario/movimientos").json()
        )
        before["tickets"] = len(cliente.get("/api/v1/tickets/").json())

        producto = cliente.post(
            "/api/v1/inventario/productos",
            json={
                "nombre": "Producto de Superadmin",
                "descripcion": None,
                "unidad_medida": "UNIDAD",
                "stock_minimo": 1,
                "categoria_id": datos_base["categoria_id"],
            },
        )
        movimiento = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "observacion": "Intento de Superadmin",
                "inventario_id": datos_base["inventario_id"],
            },
        )
        ticket = cliente.post(
            "/api/v1/tickets/",
            json={
                "usuario_id": datos_base["usuario_id"],
                "prioridad_id": datos_base["prioridad_id"],
                "estado_id": datos_base["estado_ingresado_id"],
                "asunto": "Ticket de Superadmin",
                "detalles": [
                    {
                        "producto_id": datos_base["producto_id"],
                        "cantidad_solicitada": 1,
                    }
                ],
            },
        )

        after["productos"] = len(cliente.get("/api/v1/inventario/productos").json())
        after["movimientos"] = len(
            cliente.get("/api/v1/inventario/movimientos").json()
        )
        after["tickets"] = len(cliente.get("/api/v1/tickets/").json())

    assert producto.status_code == 403, producto.text
    assert movimiento.status_code == 403, movimiento.text
    assert ticket.status_code == 403, ticket.text
    assert after == before
