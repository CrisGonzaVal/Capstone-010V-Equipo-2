"""T8 (Feature 008): institucion efectiva en `GET /auth/me` (AC-16, AC-17).

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`). Se siembran
**dos instituciones** con usuarios persistidos por rol y se observa que la
institucion efectiva que `/auth/me` publica se deriva en el servidor
(`usuario -> departamento -> institucion`), nunca de entrada del cliente:

  * Administrador, Bodeguero y Solicitante reciben un objeto `institucion`
    (id + nombre) coherente con lo expuesto por `/usuarios/instituciones`.
  * Superadmin recibe `institucion` **explicitamente `null`**: conserva su
    caracter global y no se degrada a una institucion concreta.

El campo es informativo (contexto de UI): no autoriza ni acepta entrada del
cliente. La suite no comprueba autorizacion por institucion (eso lo cubren T5/T6/T7).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import Departamento, Institucion, Rol, Usuario
from app.services.auth_service import IdentidadAutenticada

RUTA_ME = "/api/v1/auth/me"


# ---------------------------------------------------------------------------
# Sembrado: cuatro roles en INST01 y un rol limitado en INST02
# ---------------------------------------------------------------------------


@pytest.fixture
def identidades(motor, datos_base):
    """`datos_base` (INST01) + usuarios por rol y una institucion ajena INST02.

    `datos_base` ya aporta INST01 ("Instituto de Prueba"), su departamento y el
    usuario roll Administrador (Ana). Aqui se agregan los otros tres roles en
    INST01 y un usuario Administrador en INST02 para probar la derivacion real
    (no un valor fijo).
    """
    db = sessionmaker(bind=motor)()
    try:
        rol_superadmin = Rol(nombre_rol="Superadmin", descripcion="Rol global")
        rol_solicitante = Rol(nombre_rol="Solicitante", descripcion="Rol limitado")
        db.add(rol_superadmin)
        db.add(rol_solicitante)
        db.flush()

        dept_propio_id = datos_base["departamento_id"]
        inst_propia = datos_base["institucion_id"]

        usuario_bodeguero = Usuario(
            nombre="Beto",
            apellido="Bodega",
            correo="beto.bodega@compustock.cl",
            departamento_id=dept_propio_id,
            rol_id=datos_base["rol_bodeguero_id"],
        )
        usuario_solicitante = Usuario(
            nombre="Sofi",
            apellido="Solicita",
            correo="sofi.solicita@compustock.cl",
            departamento_id=dept_propio_id,
            rol_id=rol_solicitante.rol_id,
        )
        usuario_superadmin = Usuario(
            nombre="Sergio",
            apellido="Global",
            correo="sergio.global@compustock.cl",
            departamento_id=dept_propio_id,
            rol_id=rol_superadmin.rol_id,
        )
        db.add_all([usuario_bodeguero, usuario_solicitante, usuario_superadmin])

        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
        )
        db.add(institucion_ajena)
        db.flush()

        departamento_ajeno = Departamento(
            nombre_dep="Bodega Sur",
            descripcion="Deposito de la institucion ajena",
            institucion_id=institucion_ajena.institucion_id,
        )
        db.add(departamento_ajeno)
        db.flush()

        usuario_ajeno = Usuario(
            nombre="Aldo",
            apellido="Ajeno",
            correo="aldo.ajeno@compustock.cl",
            departamento_id=departamento_ajeno.departamento_id,
            rol_id=datos_base["rol_id"],
        )
        db.add(usuario_ajeno)
        db.commit()

        return {
            **datos_base,
            "inst_propia": inst_propia,
            "nombre_propio": "Instituto de Prueba",
            "inst_ajena": "INST02",
            "nombre_ajeno": "Instituto Ajeno",
            "usuario_admin_id": datos_base["usuario_id"],
            "usuario_bodeguero_id": usuario_bodeguero.usuario_id,
            "usuario_solicitante_id": usuario_solicitante.usuario_id,
            "usuario_superadmin_id": usuario_superadmin.usuario_id,
            "usuario_ajeno_id": usuario_ajeno.usuario_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cliente real con identidad por usuario/rol
# ---------------------------------------------------------------------------


def _identidad(rol: str, usuario_id: int) -> IdentidadAutenticada:
    """Identidad con el `usuario_id` persistido y el rol de autorizacion.

    El endpoint `/auth/me` relee el usuario por `usuario_id`; la identidad solo
    aporta el rol para la frontera HTTP de autorizacion.
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Institucion",
        correo=f"sonda.{usuario_id}@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-auth-me")


@contextmanager
def _cliente(motor, rol: str, usuario_id: int):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(
        rol, usuario_id
    )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-17: institucion derivada por rol limitado y null para Superadmin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rol,clave_usuario",
    [
        ("Administrador", "usuario_admin_id"),
        ("Bodeguero", "usuario_bodeguero_id"),
        ("Solicitante", "usuario_solicitante_id"),
    ],
)
def test_auth_me_roles_limitados_exponen_institucion_derivada(
    motor, identidades, rol, clave_usuario
):
    """AC-17: los tres roles limitados reciben su institucion efectiva."""
    with _cliente(motor, rol, identidades[clave_usuario]) as cliente:
        respuesta = cliente.get(RUTA_ME)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["institucion"] == {
        "institucion_id": identidades["inst_propia"],
        "nombre": identidades["nombre_propio"],
    }, cuerpo


def test_auth_me_deriva_la_institucion_de_cada_usuario_no_de_un_valor_fijo(
    motor, identidades
):
    """AC-17: un usuario de otra institucion recibe la suya, no la de la semilla."""
    with _cliente(motor, "Administrador", identidades["usuario_ajeno_id"]) as cliente:
        respuesta = cliente.get(RUTA_ME)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["institucion"] == {
        "institucion_id": identidades["inst_ajena"],
        "nombre": identidades["nombre_ajeno"],
    }


def test_auth_me_superadmin_expone_institucion_nula_explicita(motor, identidades):
    """AC-17: Superadmin conserva su caracter global con `institucion: null`."""
    with _cliente(motor, "Superadmin", identidades["usuario_superadmin_id"]) as cliente:
        respuesta = cliente.get(RUTA_ME)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert "institucion" in cuerpo, "el campo debe estar presente aunque sea nulo"
    assert cuerpo["institucion"] is None, cuerpo


def test_auth_me_no_acepta_institucion_del_cliente(motor, identidades):
    """AC-17: el ambito no se toma del cliente; un parametro no cambia la respuesta.

    `/auth/me` no declara parametros de entrada. Aun enviando un `institucion_id`
    en la query, la respuesta sigue siendo la institucion derivada del usuario.
    """
    with _cliente(motor, "Administrador", identidades["usuario_admin_id"]) as cliente:
        respuesta = cliente.get(
            RUTA_ME, params={"institucion_id": identidades["inst_ajena"]}
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["institucion"]["institucion_id"] == identidades["inst_propia"]


# ---------------------------------------------------------------------------
# AC-16: contrato OpenAPI de la institucion efectiva
# ---------------------------------------------------------------------------


def test_openapi_auth_me_publica_institucion_opcional(motor):
    """AC-16: el DTO publica `institucion` requerido y nullable (id + nombre)."""
    esquema = app.openapi()
    dto = esquema["components"]["schemas"]["IdentidadAutenticadaRespuesta"]
    assert "institucion" in dto["properties"], dto["properties"]
    assert "institucion" in dto.get("required", []), dto.get("required")

    # El campo es opcional en valor (anyOf objeto|null) pero siempre presente.
    campo = dto["properties"]["institucion"]
    assert any(
        rama.get("type") == "null" for rama in campo.get("anyOf", [])
    ), campo

    referencia = next(
        rama["$ref"] for rama in campo["anyOf"] if "$ref" in rama
    )
    nombre = referencia.rsplit("/", 1)[-1]
    anidado = esquema["components"]["schemas"][nombre]
    assert {"institucion_id", "nombre"} <= set(anidado["properties"]), anidado


def test_openapi_carga_sin_errores(motor):
    """AC-16: `/openapi.json` es deserializable y expone la operacion `/auth/me`."""
    esquema = app.openapi()
    assert RUTA_ME in esquema["paths"]
    assert "200" in esquema["paths"][RUTA_ME]["get"]["responses"]
    assert "401" in esquema["paths"][RUTA_ME]["get"]["responses"]


#: Rutas de la Feature 008 que ocultan un recurso ajeno con 404 (AC-9/AC-16).
_RUTAS_CON_404 = [
    ("get", "/api/v1/inventario/productos/{producto_id}"),
    ("get", "/api/v1/inventario/categorias/{categoria_id}"),
    ("post", "/api/v1/inventario/productos"),
    ("post", "/api/v1/inventario/movimientos"),
    ("post", "/api/v1/tickets/"),
    ("post", "/api/v1/tickets/{ticket_id}/despacho"),
    ("patch", "/api/v1/tickets/{ticket_id}/estado"),
]


@pytest.mark.parametrize("metodo,ruta", _RUTAS_CON_404)
def test_openapi_documenta_404_en_rutas_afectadas(motor, metodo, ruta):
    """AC-16: las rutas afectadas publican el 404 (recurso ajeno oculto)."""
    esquema = app.openapi()
    operacion = esquema["paths"][ruta][metodo]
    assert "404" in operacion["responses"], (metodo, ruta, sorted(operacion["responses"]))
    assert operacion["responses"]["404"].get("description"), (metodo, ruta)


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("post", "/api/v1/tickets/{ticket_id}/despacho"),
        ("patch", "/api/v1/tickets/{ticket_id}/estado"),
    ],
)
def test_openapi_documenta_409_en_operaciones_de_ticket(motor, metodo, ruta):
    """AC-16: despacho y cambio de estado publican tambien el 409 de conflicto."""
    esquema = app.openapi()
    operacion = esquema["paths"][ruta][metodo]
    assert "409" in operacion["responses"], (metodo, ruta, sorted(operacion["responses"]))
    assert operacion["responses"]["409"].get("description"), (metodo, ruta)

