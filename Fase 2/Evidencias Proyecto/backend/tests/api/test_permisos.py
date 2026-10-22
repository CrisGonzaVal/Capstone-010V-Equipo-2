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
#: Lectura de negocio de los roles institucionales (Feature 017, D-9/AC-15):
#: Superadmin deja de leer dashboard, tickets, catalogo, existencias y stock.
_LECTURA_NEGOCIO = {"Administrador", "Bodeguero", "Solicitante"}
#: Historial de movimientos sin Superadmin ni Solicitante (017 / 011).
_MOVIMIENTOS = {"Administrador", "Bodeguero"}
#: Alta de institucion (Feature 010, D-7): solo Superadmin.
_ALTA_INSTITUCION = {"Superadmin"}
#: Gestion organizacional (Feature 011, D-4/D-5): solo Administrador institucional.
_ORGANIZACION = {"Administrador"}
#: Ciclo de vida del ticket (Feature 013, AC-17): anulacion y edicion las opera
#: el dueño del ticket (Solicitante) junto con el Administrador institucional.
_ANULACION_Y_EDICION = {"Administrador", "Solicitante"}
#: Ciclo de vida del ticket (Feature 013, AC-17): rechazo, operativo de bodega.
_RECHAZO = {"Administrador", "Bodeguero"}

#: Las operaciones de negocio -> roles permitidos (matriz vigente de 55 filas:
#: 49 de la 013, las cinco de gobierno de Administradores de la 017 y el reenvio
#: ordinario de invitacion de la 017). La 017 retira Superadmin de 11 lecturas de
#: negocio (D-9/AC-15); el resto no cambia.
MATRIZ_ESPERADA: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/auth/me"): _TODOS,
    ("GET", "/api/v1/usuarios/"): _ORGANIZACION,
    ("POST", "/api/v1/usuarios/"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/roles"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/departamentos"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/instituciones"): _ORGANIZACION,
    ("GET", "/api/v1/inventario/categorias"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/productos"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/productos/{producto_id}"): _LECTURA_NEGOCIO,
    ("POST", "/api/v1/inventario/productos"): _ESCRITURA_CATALOGO,
    ("GET", "/api/v1/inventario/existencias"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/stock"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/movimientos"): _MOVIMIENTOS,
    ("POST", "/api/v1/inventario/movimientos"): _ESCRITURA_STOCK,
    ("GET", "/api/v1/tickets/catalogos"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/tickets/"): _LECTURA_NEGOCIO,
    ("POST", "/api/v1/tickets/"): _ESCRITURA_TICKETS,
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _ESCRITURA_STOCK,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _ESCRITURA_STOCK,
    # Feature 009 (D-3/AC-13/AC-14): lectura consolidada para los cuatro roles.
    ("GET", "/api/v1/dashboard/"): _LECTURA_NEGOCIO,
    # Feature 010 (D-7/AC-7…AC-9): alta de institucion, solo Superadmin.
    ("POST", "/api/v1/control/instituciones/"): _ALTA_INSTITUCION,
    # Feature 011 (D-4/D-5/AC-5): asignaciones organizacionales, solo Administrador.
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
    # Feature 012 (T6, D-1/D-2/D-5/D-6/AC-1…AC-5): gestion administrativa de
    # control SaaS (registro institucional, estado, dashboard y capacidades),
    # exclusiva del Superadmin. Operaciones nuevas y aditivas.
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
    # Feature 012 (T7, D-3/D-4/AC-6…AC-13): CRUD organizacional del Administrador
    # institucional (sedes, departamentos y usuarios locales). Operaciones nuevas
    # y aditivas.
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
    ("PUT", "/api/v1/usuarios/{usuario_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): _ORGANIZACION,
    # Feature 013 (T6, AC-17): ciclo de vida del ticket. Cinco operaciones
    # nuevas y aditivas (44 -> 49): anulacion y edicion (el dueño del ticket y
    # el Administrador), rechazo (Bodeguero y Administrador), y detalle e
    # historial (los cuatro roles); Superadmin queda fuera de toda escritura.
    ("POST", "/api/v1/tickets/{ticket_id}/anulacion"): _ANULACION_Y_EDICION,
    ("POST", "/api/v1/tickets/{ticket_id}/rechazo"): _RECHAZO,
    ("PUT", "/api/v1/tickets/{ticket_id}"): _ANULACION_Y_EDICION,
    ("GET", "/api/v1/tickets/{ticket_id}"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/tickets/{ticket_id}/historial"): _LECTURA_NEGOCIO,
    # Feature 017 (D-10/AC-8/AC-9): cinco operaciones de gobierno de
    # Administradores, solo Superadmin; `/usuarios/` queda solo Administrador.
    (
        "GET",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): _ALTA_INSTITUCION,
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): _ALTA_INSTITUCION,
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}",
    ): _ALTA_INSTITUCION,
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    ): _ALTA_INSTITUCION,
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/invitacion/reenvio",
    ): _ALTA_INSTITUCION,
    # Feature 017 (D-4/D-10/AC-9): reenvio ordinario del Administrador a sus
    # Bodegueros/Solicitantes; Superadmin no accede a rutas ordinarias.
    (
        "POST",
        "/api/v1/usuarios/{usuario_id}/invitacion/reenvio",
    ): _ORGANIZACION,
}

#: Feature 018 (spec D-6/AC-8, plan §1.4): la **unica** operacion que la 018
#: agrega a la matriz central. Se declara como referencia aditiva independiente
#: para no tocar la transcripcion historica de 55 filas ni su `len == 55`
#: (patron de `test_permisos_012.py`): la base 014 queda intacta y la suma se
#: verifica aparte.
_AMBITO_INVENTARIO = {"Administrador", "Bodeguero"}
MATRIZ_018_ADITIVA: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/inventario/ambito"): _AMBITO_INVENTARIO,
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
# AC-9: la matriz central conserva la transcripcion de D-3 (55 operaciones
# vigentes tras las Features 008, 009, 010, 011, 012, 013 y 017: las 18 de 007
# mas los dos GET por objeto de catalogo de la 008, el GET consolidado del
# dashboard de la 009, el alta de institucion de la 010, las seis asignaciones
# organizacionales de la 011, las dieciseis de la 012, las cinco de ciclo de vida
# de la 013 y las once de gobierno de la 017). La 014 agrega cinco operaciones
# mas sin tocar estas filas.
# ---------------------------------------------------------------------------


def test_matriz_conserva_las_operaciones_de_d3_y_solo_agrega():
    """La matriz conserva las 55 filas transcritas y solo admite adiciones.

    La transcripcion es una fase de la cadena: cada una de sus filas debe seguir
    con los mismos roles y la matriz viva no puede retirar ninguna. Las features
    posteriores (014 en adelante) agregan operaciones nuevas sin tocar las
    existentes, por eso el total se compara como cota inferior.
    """
    assert len(MATRIZ_ESPERADA) == 55
    vigente = {
        clave: set(roles) for clave, roles in permisos.MATRIZ_PERMISOS.items()
    }
    for clave, roles in MATRIZ_ESPERADA.items():
        assert vigente.get(clave) == roles, clave
    assert set(vigente) >= set(MATRIZ_ESPERADA)


def test_permisos_018_solo_agrega_la_operacion_de_ambito():
    """AC-8: la 018 suma una fila de ambito y no toca la transcripcion de 55.

    El baseline historico `MATRIZ_ESPERADA` (55 filas) y su `len == 55` quedan
    inmutables; la operacion nueva se comprueba aqui como suma independiente.
    """
    assert len(MATRIZ_ESPERADA) == 55
    for clave, roles in MATRIZ_018_ADITIVA.items():
        vigente = permisos.MATRIZ_PERMISOS.get(clave)
        assert vigente is not None, f"la Feature 018 debe declarar {clave}"
        assert set(vigente) == roles, clave
        for rol in _ROLES:
            assert permisos.rol_autorizado(rol, vigente) is (rol in roles), (
                clave,
                rol,
            )
    assert set(permisos.MATRIZ_PERMISOS) - set(MATRIZ_018_ADITIVA) >= set(
        MATRIZ_ESPERADA
    ), "la 018 no puede retirar ninguna de las 55 operaciones historicas"


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
