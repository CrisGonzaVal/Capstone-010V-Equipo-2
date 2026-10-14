"""T2 (Feature 007): autorizacion de las **18 operaciones reales** y contrato HTTP/OpenAPI.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), no una app
sonda. T1 verifico la dependencia y la matriz aisladas; aqui se comprueba que
esas 18 operaciones estan efectivamente cableadas en los endpoints de negocio.

Estrategia anti-tautologica: la matriz de referencia se escribe a mano (no se lee
de `permisos.MATRIZ_PERMISOS`) y se contrasta contra las rutas que publica el
propio `app`. Con una peticion **valida** (el mismo payload), cambiar solo el rol
de la identidad debe mover el estatus entre 2xx y 403; asi la prueba distingue
"autorizacion" de "error de forma" y no depende de la base mas que para sembrar
el catalogo.

La matriz D-3 mantiene dos matices que esta suite fija:
  * `GET /tickets/` da permiso al Solicitante (el filtrado a sus propios tickets
    es T4, no ahora).
  * `GET /tickets/catalogos` da permiso a los cuatro roles.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos
from app.main import app
from app.models import DetalleTicket, EstadoTicket, Rol, Ticket, Usuario
from app.services.auth_service import IdentidadAutenticada

# ---------------------------------------------------------------------------
# Fuente de verdad independiente: la matriz D-3 transcrita a mano (18 filas)
# ---------------------------------------------------------------------------

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}
_INVENTARIO_Y_TICKETS = {"Superadmin", "Administrador", "Bodeguero"}

MATRIZ_D3: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/auth/me"): _TODOS,
    ("GET", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("POST", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/roles"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/departamentos"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/instituciones"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/inventario/categorias"): _TODOS,
    ("GET", "/api/v1/inventario/productos"): _TODOS,
    ("POST", "/api/v1/inventario/productos"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/inventario/existencias"): _TODOS,
    ("GET", "/api/v1/inventario/stock"): _TODOS,
    ("GET", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    ("POST", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    ("GET", "/api/v1/tickets/catalogos"): _TODOS,
    ("GET", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _INVENTARIO_Y_TICKETS,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _INVENTARIO_Y_TICKETS,
}

_ROLES = ("Superadmin", "Administrador", "Bodeguero", "Solicitante")

_METODOS_HTTP = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
)

#: Operaciones cuyo exito contractual es `201 Created` (el resto son `200`).
_CODIGOS_201 = {
    ("POST", "/api/v1/usuarios/"),
    ("POST", "/api/v1/inventario/productos"),
    ("POST", "/api/v1/inventario/movimientos"),
    ("POST", "/api/v1/tickets/"),
}

#: Rol representativo permitido por operacion (el primero de la matriz D-3 en el
#: orden de `_ROLES`), para la prueba de aceptacion de al menos un rol valido.
CASOS_DENEGADOS = [
    (metodo, ruta, rol)
    for (metodo, ruta), permitidos in MATRIZ_D3.items()
    for rol in _ROLES
    if rol not in permitidos
]

CASOS_PERMITIDOS = [
    (metodo, ruta, rol)
    for (metodo, ruta), permitidos in MATRIZ_D3.items()
    for rol in _ROLES
    if rol in permitidos
]


# ---------------------------------------------------------------------------
# Helpers: identidad por rol, cliente real, payload valido por operacion
# ---------------------------------------------------------------------------


def _identidad_con_rol(rol: str | None, usuario_id: int = 1) -> IdentidadAutenticada:
    """Identidad autenticada con el rol dado; `None` simula rol ausente.

    El usuario no se persiste: la autorizacion solo lee `usuario.rol.nombre_rol`.
    Para `GET /auth/me` el endpoint relee el usuario por `usuario_id` en la base,
    de modo que la identidad se construye con el id de un usuario persistido.
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Autorizacion",
        correo="sonda@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-sonda")


@contextmanager
def _cliente(motor, rol: str | None = None, *, usuario_id: int = 1):
    """`TestClient` del `app` real con `get_db` en SQLite y la identidad por rol.

    Con `rol=None` y `autenticar=False` no se overridea `get_current_user`, de
    modo que la sesion ausente/invalida ejerce el 401 real.
    """
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if rol is not _SIN_AUTENTICAR:
        app.dependency_overrides[dependencies.get_current_user] = (
            lambda: _identidad_con_rol(rol, usuario_id)
        )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


#: Centinela para distinguir "sin autenticar" de "rol ausente" (`None`).
_SIN_AUTENTICAR = object()


def _ruta_concreta(metodo: str, ruta: str, datos: dict) -> str:
    """Resuelve `{ticket_id}` al ticket sembrado que corresponde a la operacion."""
    if ruta == "/api/v1/tickets/{ticket_id}/despacho":
        return ruta.replace("{ticket_id}", str(datos["ticket_despacho_id"]))
    if ruta == "/api/v1/tickets/{ticket_id}/estado":
        return ruta.replace("{ticket_id}", str(datos["ticket_estado_id"]))
    return ruta


def _cuerpo(metodo: str, ruta: str, datos: dict):
    """Payload valido para la operacion (o `None` en las lecturas GET)."""
    if metodo == "GET":
        return None
    if (metodo, ruta) == ("POST", "/api/v1/usuarios/"):
        return {
            "nombre": "Nuevo",
            "apellido": "Usuario",
            "correo": "nuevo.autorizacion@compustock.cl",
            "departamento_id": datos["departamento_id"],
            # Rol asignable por el rol autorizado mas restrictivo (Administrador,
            # D-6/AC-10); Superadmin tambien lo admite. La prueba aislada de la
            # restriccion de rol vive en test_rol_asignable_usuarios.py (T5).
            "rol_id": datos["rol_bodeguero_id"],
        }
    if (metodo, ruta) == ("POST", "/api/v1/inventario/productos"):
        return {
            "nombre": "Producto autorizado",
            "descripcion": None,
            "unidad_medida": "UNIDAD",
            "stock_minimo": 1,
            "categoria_id": datos["categoria_id"],
        }
    if (metodo, ruta) == ("POST", "/api/v1/inventario/movimientos"):
        return {
            "tipo_movimiento": "ENTRADA",
            "cantidad": 5,
            "observacion": "Movimiento autorizado",
            "inventario_id": datos["inventario_id"],
        }
    if (metodo, ruta) == ("POST", "/api/v1/tickets/"):
        return {
            "usuario_id": datos["usuario_id"],
            "prioridad_id": datos["prioridad_id"],
            "estado_id": datos["estado_pendiente_id"],
            "asunto": "Ticket autorizado",
            "descripcion": "Alta valida para probar la autorizacion.",
            "detalles": [
                {"producto_id": datos["producto_id"], "cantidad_solicitada": 1}
            ],
        }
    if (metodo, ruta) == ("POST", "/api/v1/tickets/{ticket_id}/despacho"):
        return {"usuario_id": datos["usuario_id"]}
    if (metodo, ruta) == ("PATCH", "/api/v1/tickets/{ticket_id}/estado"):
        return {"estado_id": datos["estado_en_curso_id"]}
    raise AssertionError(f"sin payload definido para {metodo} {ruta}")


# ---------------------------------------------------------------------------
# Sembrado: catalogo canonico de estados y dos tickets para despacho/estado
# ---------------------------------------------------------------------------


@pytest.fixture
def datos_autorizacion(motor, datos_base):
    """`datos_base` + los cuatro estados canonicos y dos tickets de trabajo.

    `ticket_estado_id` esta en `EnRevision` para que `PATCH /estado` avance un
    paso contiguo a `EnCurso` (200); `ticket_despacho_id` ya esta en `EnCurso`
    con una linea del producto que tiene inventario, para un despacho 200.
    """
    db = sessionmaker(bind=motor)()
    try:
        db.query(EstadoTicket).delete()
        db.flush()
        ids: dict[str, int] = {}
        for nombre in ("Pendiente", "EnRevision", "EnCurso", "Cerrado"):
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            ids[nombre] = estado.estado_id

        # Rol asignable por el Administrador (D-6/AC-10): el payload generico de
        # `POST /usuarios/` debe seguir siendo valido para el rol autorizado mas
        # restrictivo, para que esta suite siga midiendo autorizacion, no la
        # regla de negocio del rol asignable (cubierta por T5).
        rol_bodeguero = Rol(
            nombre_rol="Bodeguero", descripcion="Rol asignable por Administrador"
        )
        db.add(rol_bodeguero)
        db.flush()

        def _ticket(estado_id: int, asunto: str) -> Ticket:
            ticket = Ticket(
                usuario_id=datos_base["usuario_id"],
                prioridad_id=datos_base["prioridad_id"],
                estado_id=estado_id,
                asunto=asunto,
                descripcion="Sembrado para pruebas de autorizacion.",
            )
            db.add(ticket)
            db.flush()
            db.add(
                DetalleTicket(
                    ticket_id=ticket.ticket_id,
                    producto_id=datos_base["producto_id"],
                    cantidad_solicitada=1,
                    cantidad_entregada=0,
                )
            )
            return ticket

        ticket_estado = _ticket(ids["EnRevision"], "Cambio de estado autorizado")
        ticket_despacho = _ticket(ids["EnCurso"], "Despacho autorizado")
        db.commit()

        return {
            **datos_base,
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["EnCurso"],
            "estado_cerrado_id": ids["Cerrado"],
            "ticket_estado_id": ticket_estado.ticket_id,
            "ticket_despacho_id": ticket_despacho.ticket_id,
            "rol_bodeguero_id": rol_bodeguero.rol_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Inventario de rutas contrastado con la matriz D-3
# ---------------------------------------------------------------------------


def test_inventario_de_rutas_igual_a_la_matriz_d3():
    """El `app` publica exactamente las 18 operaciones de negocio de la matriz.

    Falla si una ruta de negocio queda sin autorizacion declarada o si la matriz
    inventa una operacion que el contrato no expone.
    """
    esquema = app.openapi()
    operaciones_reales = {
        (metodo.upper(), ruta)
        for ruta, item in esquema["paths"].items()
        if ruta.startswith("/api/v1")
        for metodo in item
        if metodo in _METODOS_HTTP
    }
    assert operaciones_reales == set(MATRIZ_D3)
    assert set(permisos.MATRIZ_PERMISOS) == set(MATRIZ_D3)


# ---------------------------------------------------------------------------
# Allow / deny por rol y operacion sobre el app real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("metodo,ruta,rol", CASOS_DENEGADOS)
def test_rol_sin_permiso_recibe_403(
    motor, datos_autorizacion, metodo, ruta, rol
):
    """Una identidad autenticada sin permiso recibe 403 exacto, no 401."""
    with _cliente(motor, rol, usuario_id=datos_autorizacion["usuario_id"]) as cliente:
        respuesta = cliente.request(
            metodo,
            _ruta_concreta(metodo, ruta, datos_autorizacion),
            json=_cuerpo(metodo, ruta, datos_autorizacion),
        )
    assert respuesta.status_code == 403, (metodo, ruta, rol, respuesta.text)


@pytest.mark.parametrize("metodo,ruta,rol", CASOS_PERMITIDOS)
def test_rol_con_permiso_recibe_exito(
    motor, datos_autorizacion, metodo, ruta, rol
):
    """Un rol permitido obtiene el 2xx contractual con un payload valido."""
    esperado = 201 if (metodo, ruta) in _CODIGOS_201 else 200
    with _cliente(motor, rol, usuario_id=datos_autorizacion["usuario_id"]) as cliente:
        respuesta = cliente.request(
            metodo,
            _ruta_concreta(metodo, ruta, datos_autorizacion),
            json=_cuerpo(metodo, ruta, datos_autorizacion),
        )
    assert respuesta.status_code == esperado, (metodo, ruta, rol, respuesta.text)


def test_denegacion_no_muta_datos(motor, datos_autorizacion):
    """Una denegacion 403 no crea filas: la lista de tickets queda intacta."""
    with _cliente(motor, "Solicitante") as cliente:
        antes = cliente.get("/api/v1/tickets/").json()
        denegado = cliente.post(
            f"/api/v1/tickets/{datos_autorizacion['ticket_despacho_id']}/despacho",
            json=_cuerpo(
                "POST",
                "/api/v1/tickets/{ticket_id}/despacho",
                datos_autorizacion,
            ),
        )
        despues = cliente.get("/api/v1/tickets/").json()

    assert denegado.status_code == 403, denegado.text
    assert despues == antes


# ---------------------------------------------------------------------------
# Rol ausente/desconocido: nunca concede
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["Admin", "Superusuario", "admin", ""])
def test_rol_desconocido_recibe_403(motor, datos_autorizacion, rol):
    """`Admin` no es alias de `Administrador`: es un rol desconocido."""
    with _cliente(motor, rol, usuario_id=datos_autorizacion["usuario_id"]) as cliente:
        respuesta = cliente.get("/api/v1/tickets/catalogos")
    assert respuesta.status_code == 403, respuesta.text


def test_rol_ausente_recibe_403(motor, datos_autorizacion):
    with _cliente(motor, None, usuario_id=datos_autorizacion["usuario_id"]) as cliente:
        respuesta = cliente.get("/api/v1/tickets/catalogos")
    assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# Sesion ausente/invalida conserva 401; salud y documentacion siguen publicas
# ---------------------------------------------------------------------------


def test_sin_bearer_responde_401(motor, datos_autorizacion):
    with _cliente(motor, _SIN_AUTENTICAR) as cliente:
        respuesta = cliente.get("/api/v1/tickets/")
    assert respuesta.status_code == 401, respuesta.text


def test_bearer_invalido_responde_401(motor, datos_autorizacion):
    with _cliente(motor, _SIN_AUTENTICAR) as cliente:
        respuesta = cliente.get(
            "/api/v1/tickets/", headers={"Authorization": "Bearer no-es-un-jwt"}
        )
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("ruta", ["/", "/health", "/docs", "/openapi.json"])
def test_rutas_publicas_no_exigen_sesion(motor, ruta):
    with _cliente(motor, _SIN_AUTENTICAR) as cliente:
        respuesta = cliente.get(ruta)
    assert respuesta.status_code == 200, (ruta, respuesta.text)


# ---------------------------------------------------------------------------
# Contrato OpenAPI: seguridad, 401/403 y contratos de exito preservados
# ---------------------------------------------------------------------------


def _ref_de_respuesta(operacion: dict, codigo: str) -> str | None:
    contenido = operacion["responses"][codigo].get("content", {})
    esquema = contenido.get("application/json", {}).get("schema", {})
    if "$ref" in esquema:
        return esquema["$ref"].rsplit("/", 1)[-1]
    items = esquema.get("items", {})
    if "$ref" in items:
        return items["$ref"].rsplit("/", 1)[-1]
    return None


def test_openapi_toda_operacion_exige_bearer():
    esquema = app.openapi()
    for metodo, ruta in MATRIZ_D3:
        operacion = esquema["paths"][ruta][metodo.lower()]
        assert operacion.get("security"), (metodo, ruta)


def test_openapi_declara_401_y_403_en_cada_operacion():
    """Cada operacion de la matriz documenta los dos codigos de autorizacion."""
    esquema = app.openapi()
    for metodo, ruta in MATRIZ_D3:
        operacion = esquema["paths"][ruta][metodo.lower()]
        assert "401" in operacion["responses"], (metodo, ruta)
        assert "403" in operacion["responses"], (metodo, ruta)
        assert operacion["responses"]["401"].get("description"), (metodo, ruta)
        assert operacion["responses"]["403"].get("description"), (metodo, ruta)


def test_openapi_declara_el_codigo_de_exito_de_cada_operacion():
    esquema = app.openapi()
    for metodo, ruta in MATRIZ_D3:
        operacion = esquema["paths"][ruta][metodo.lower()]
        codigo = "201" if (metodo, ruta) in _CODIGOS_201 else "200"
        assert codigo in operacion["responses"], (metodo, ruta)


#: DTO de exito que cada operacion con `response_model` referencia.
REFERENCIAS_ESPERADAS = {
    ("GET", "/api/v1/auth/me"): "IdentidadAutenticadaRespuesta",
    ("GET", "/api/v1/usuarios/"): "UsuarioRespuesta",
    ("POST", "/api/v1/usuarios/"): "UsuarioRespuesta",
    ("GET", "/api/v1/inventario/categorias"): "CategoriaRespuesta",
    ("GET", "/api/v1/inventario/productos"): "ProductoRespuesta",
    ("POST", "/api/v1/inventario/productos"): "ProductoRespuesta",
    ("GET", "/api/v1/inventario/existencias"): "ProductoExistenciaRespuesta",
    ("GET", "/api/v1/inventario/stock"): "InventarioRespuesta",
    ("GET", "/api/v1/inventario/movimientos"): "MovimientoInventarioRespuesta",
    ("GET", "/api/v1/tickets/catalogos"): "CatalogosTicketRespuesta",
    ("GET", "/api/v1/tickets/"): "TicketRespuesta",
    ("POST", "/api/v1/tickets/"): "TicketRespuesta",
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): "TicketRespuesta",
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): "TicketRespuesta",
}


def test_openapi_conserva_los_contratos_de_exito():
    """La autorizacion no altera el `response_model` de exito de ninguna operacion."""
    esquema = app.openapi()
    for (metodo, ruta), nombre in REFERENCIAS_ESPERADAS.items():
        operacion = esquema["paths"][ruta][metodo.lower()]
        codigo = "201" if (metodo, ruta) in _CODIGOS_201 else "200"
        assert _ref_de_respuesta(operacion, codigo) == nombre, (metodo, ruta)
