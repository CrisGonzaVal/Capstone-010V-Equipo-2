"""T1 (Feature 007): pruebas de la politica central y la dependencia de autorizacion.

Seam bajo prueba: la **dependencia FastAPI de autorizacion por rol** y la
**matriz central de permisos** (D-3/AC-9). Como T1 aun no cablea los 18
endpoints de negocio (eso es T2), las pruebas HTTP montan una app FastAPI
minima con rutas sonda protegidas por `requiere_roles`/`requiere_operacion`
sobre `get_current_user` (real, para el 401; overrideado, para 200/403).

Ninguna asercion consulta la base directamente ni importa logica de negocio:
lo observable es la respuesta HTTP (401/403/200) y los literales de la matriz.
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
# Fuente de verdad independiente: la matriz D-3 transcrita a mano
# ---------------------------------------------------------------------------

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}
_INVENTARIO_Y_TICKETS = {"Superadmin", "Administrador", "Bodeguero"}
# Ajuste Feature 008 (D-3/AC-10): Superadmin deja de escribir catalogo,
# stock/movimientos y tickets; esas escrituras son institucionales.
_ESCRITURA_CATALOGO = {"Administrador"}
_ESCRITURA_STOCK = {"Administrador", "Bodeguero"}
_ESCRITURA_TICKETS = {"Administrador", "Bodeguero", "Solicitante"}
#: Alta de institucion (Feature 010, D-7): solo Superadmin.
_ALTA_INSTITUCION = {"Superadmin"}

#: Las 22 operaciones de negocio -> roles permitidos (matriz vigente tras el
#: ajuste puntual de la Feature 008, la operacion `GET /dashboard/` de la 009 y
#: el alta de institucion de la 010; el resto de la matriz D-3 de 007 no cambia,
#: salvo los dos GET por objeto de catalogo que exige AC-9/AC-16 de la 008).
MATRIZ_ESPERADA: dict[tuple[str, str], set[str]] = {
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
    # Feature 009 (D-3/AC-13/AC-14): lectura consolidada para los cuatro roles.
    ("GET", "/api/v1/dashboard/"): _TODOS,
    # Feature 010 (D-7/AC-7…AC-9): alta de institucion, solo Superadmin.
    ("POST", "/api/v1/control/instituciones/"): _ALTA_INSTITUCION,
}

_ROLES = ("Superadmin", "Administrador", "Bodeguero", "Solicitante")


# ---------------------------------------------------------------------------
# Helpers: identidad simulada, app sonda y override de base de datos
# ---------------------------------------------------------------------------


def _identidad(rol: str | None) -> IdentidadAutenticada:
    """Identidad autenticada con el rol dado; `None` simula rol ausente.

    El usuario no se persiste (la autorizacion solo lee `usuario.rol.nombre_rol`),
    asi que no requiere contrasena ni pertenece a la base.
    """
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Autorizacion",
        correo="sonda@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-sonda")


def _override_db(motor):
    FabricaSesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db():
        db = FabricaSesion()
        try:
            yield db
        finally:
            db.close()

    return obtener_db


def _ruta_concreta(ruta: str) -> str:
    return ruta.replace("{ticket_id}", "1")


def _app_sonda(metodo: str, ruta: str) -> FastAPI:
    """App minima con una ruta protegida por la operacion de la matriz."""
    app = FastAPI()
    dependencia = dependencies.requiere_operacion(metodo, ruta)

    @app.api_route(ruta, methods=[metodo], dependencies=[Depends(dependencia)])
    def sonda():
        return {"ok": True}

    return app


def _cliente(app: FastAPI, motor, rol: str | None = None, *, autenticar: bool = False):
    app.dependency_overrides[dependencies.get_db] = _override_db(motor)
    if autenticar:
        app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(rol)
    return TestClient(app)


# ---------------------------------------------------------------------------
# AC-1: los cuatro literales de rol, sin alias `Admin`
# ---------------------------------------------------------------------------


def test_cuatro_roles_exactos_sin_alias_admin():
    assert set(permisos.ROLES_CONOCIDOS) == set(_ROLES)
    assert "Admin" not in permisos.ROLES_CONOCIDOS
    assert len(permisos.ROLES_CONOCIDOS) == 4


# ---------------------------------------------------------------------------
# AC-9: la matriz central es exactamente la de D-3 (22 operaciones vigentes
# tras las Features 008, 009 y 010: las 18 de 007 mas los dos GET por objeto de
# catalogo de la 008, el GET consolidado del dashboard de la 009 y el alta de
# institucion de la 010)
# ---------------------------------------------------------------------------


def test_matriz_cubre_exactamente_las_operaciones_de_d3():
    assert len(MATRIZ_ESPERADA) == 22
    assert {
        clave: set(roles) for clave, roles in permisos.MATRIZ_PERMISOS.items()
    } == MATRIZ_ESPERADA


def test_permiso_por_rol_respeta_la_matriz():
    """Cada rol concede/deniega segun la matriz; desconocido/ausente nunca concede."""
    for metodo, ruta in MATRIZ_ESPERADA:
        permitidos = MATRIZ_ESPERADA[(metodo, ruta)]
        roles_matriz = permisos.roles_de_operacion(metodo, ruta)
        for rol in _ROLES:
            assert permisos.rol_autorizado(rol, roles_matriz) is (rol in permitidos), (
                metodo,
                ruta,
                rol,
            )
        assert permisos.rol_autorizado("Admin", roles_matriz) is False
        assert permisos.rol_autorizado(None, roles_matriz) is False


def test_operacion_fuera_de_la_matriz_no_tiene_permiso():
    """Una operacion no declarada no concede: `roles_de_operacion` no la inventa."""
    with pytest.raises(KeyError):
        permisos.roles_de_operacion("DELETE", "/api/v1/tickets/999")


# ---------------------------------------------------------------------------
# D-5: 401 sin sesion / con sesion invalida; 403 con sesion sin permiso
# ---------------------------------------------------------------------------


def test_sin_sesion_responde_401(motor):
    cliente = _cliente(_app_sonda("GET", "/api/v1/auth/me"), motor)
    respuesta = cliente.get("/api/v1/auth/me")
    assert respuesta.status_code == 401, respuesta.text


def test_bearer_invalido_responde_401(motor):
    cliente = _cliente(_app_sonda("GET", "/api/v1/auth/me"), motor)
    respuesta = cliente.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer no-es-un-jwt"}
    )
    assert respuesta.status_code == 401, respuesta.text


# ---------------------------------------------------------------------------
# Permiso permitido/denegado por rol y operacion (matriz D-3), via HTTP
# ---------------------------------------------------------------------------

CASOS_HTTP = [
    ("GET", "/api/v1/auth/me", "Superadmin", 200),
    ("GET", "/api/v1/auth/me", "Solicitante", 200),
    ("GET", "/api/v1/usuarios/", "Administrador", 200),
    ("GET", "/api/v1/usuarios/", "Bodeguero", 403),
    ("GET", "/api/v1/usuarios/", "Solicitante", 403),
    ("POST", "/api/v1/usuarios/", "Administrador", 200),
    ("POST", "/api/v1/usuarios/", "Bodeguero", 403),
    ("GET", "/api/v1/inventario/productos", "Solicitante", 200),
    ("POST", "/api/v1/inventario/productos", "Administrador", 200),
    ("POST", "/api/v1/inventario/productos", "Bodeguero", 403),
    ("POST", "/api/v1/inventario/productos", "Solicitante", 403),
    ("GET", "/api/v1/inventario/movimientos", "Bodeguero", 200),
    ("GET", "/api/v1/inventario/movimientos", "Administrador", 200),
    ("GET", "/api/v1/inventario/movimientos", "Solicitante", 403),
    ("POST", "/api/v1/tickets/", "Solicitante", 200),
    ("GET", "/api/v1/tickets/", "Bodeguero", 200),
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado", "Bodeguero", 200),
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado", "Solicitante", 403),
    ("POST", "/api/v1/tickets/{ticket_id}/despacho", "Administrador", 200),
    ("POST", "/api/v1/tickets/{ticket_id}/despacho", "Solicitante", 403),
]


@pytest.mark.parametrize("metodo,ruta,rol,esperado", CASOS_HTTP)
def test_dependencia_concede_o_deniega_segun_matriz(motor, metodo, ruta, rol, esperado):
    app = _app_sonda(metodo, ruta)
    cliente = _cliente(app, motor, rol, autenticar=True)
    respuesta = cliente.request(metodo, _ruta_concreta(ruta))
    assert respuesta.status_code == esperado, respuesta.text


def test_denegacion_autenticada_es_403_y_no_401(motor):
    """Con sesion valida pero sin permiso, la respuesta es 403 (no 401)."""
    app = _app_sonda("GET", "/api/v1/usuarios/")
    cliente = _cliente(app, motor, "Bodeguero", autenticar=True)
    respuesta = cliente.get("/api/v1/usuarios/")
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.status_code != 401


# ---------------------------------------------------------------------------
# Rol ausente/desconocido: nunca concede, aunque la operacion sea de todos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["Admin", "Superusuario", "admin", ""])
def test_rol_desconocido_responde_403(motor, rol):
    """`Admin` no es alias de `Administrador`: es un rol desconocido."""
    app = _app_sonda("GET", "/api/v1/auth/me")
    cliente = _cliente(app, motor, rol, autenticar=True)
    respuesta = cliente.get("/api/v1/auth/me")
    assert respuesta.status_code == 403, respuesta.text


def test_rol_ausente_responde_403(motor):
    app = _app_sonda("GET", "/api/v1/auth/me")
    cliente = _cliente(app, motor, None, autenticar=True)
    respuesta = cliente.get("/api/v1/auth/me")
    assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# La identidad Clerk se resuelve una sola vez por solicitud (plan §3.1)
# ---------------------------------------------------------------------------


def test_identidad_se_resuelve_una_sola_vez_por_solicitud(motor):
    llamadas = {"n": 0}

    def identidad_que_cuenta() -> IdentidadAutenticada:
        llamadas["n"] += 1
        return _identidad("Superadmin")

    app = FastAPI()

    @app.get("/doble")
    def doble(
        guardada: IdentidadAutenticada = Depends(
            dependencies.requiere_roles("Superadmin")
        ),
        identidad: IdentidadAutenticada = Depends(dependencies.get_current_user),
    ):
        return {"misma_identidad": guardada is identidad}

    app.dependency_overrides[dependencies.get_db] = _override_db(motor)
    app.dependency_overrides[dependencies.get_current_user] = identidad_que_cuenta

    with TestClient(app) as cliente:
        respuesta = cliente.get("/doble")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["misma_identidad"] is True
    assert llamadas["n"] == 1, "get_current_user debe resolverse una sola vez"


def test_dependencia_de_rol_devuelve_la_identidad(motor):
    """La dependencia entrega la identidad ya resuelta al consumidor."""
    app = FastAPI()

    @app.get("/identidad")
    def identidad_endpoint(
        identidad: IdentidadAutenticada = Depends(
            dependencies.requiere_roles("Administrador", "Superadmin")
        ),
    ):
        return {"usuario_id": identidad.usuario.usuario_id, "sub": identidad.sub}

    app.dependency_overrides[dependencies.get_db] = _override_db(motor)
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(
        "Administrador"
    )

    with TestClient(app) as cliente:
        respuesta = cliente.get("/identidad")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"usuario_id": 1, "sub": "sub-sonda"}
