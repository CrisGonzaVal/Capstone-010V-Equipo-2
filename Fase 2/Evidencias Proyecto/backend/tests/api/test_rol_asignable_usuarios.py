"""T5 (Feature 007): restriccion del rol asignable en el alta de usuario (AC-8, AC-10).

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`). Se siembran
los cuatro roles canonicos y **dos instituciones** (propia y ajena) y se observa:

  * El Administrador solo puede asignar `Bodeguero` o `Solicitante`; intentar
    asignar `Superadmin` o `Administrador` responde **403** y **no crea fila**.
  * El Superadmin puede asignar cualquiera de los cuatro roles.
  * El alta del Administrador queda acotada a su institucion: un
    `departamento_id` de otra institucion responde **403** y no crea fila (D-4,
    AC-8); un departamento propio crea el usuario correctamente.

La regla vive en el **servicio** (`usuario_service.crear_usuario`), no en el
router; estas pruebas la ejercen solo a traves de la API, igual que un cliente
real. El contrato de creacion no cambia salvo por la restriccion de rol; el
retiro de `password` del modelo/contrato ya lo aplico T6 (esquema/semilla, T7).
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

RUTA_USUARIOS = "/api/v1/usuarios/"

#: Centinela: identidad con `departamento_id=None` (institucion no resoluble).
_SIN_DEPARTAMENTO = object()


# ---------------------------------------------------------------------------
# Sembrado: los cuatro roles y una institucion ajena
# ---------------------------------------------------------------------------


@pytest.fixture
def contexto(motor, datos_base):
    """`datos_base` (INST01 + rol "Administrador") + los roles y una INST02.

    Devuelve el mapa `nombre_rol -> rol_id` de los cuatro roles canonicos (el
    "Administrador" reutiliza el de `datos_base`) y un departamento de la
    institucion ajena INST02 para probar el limite institucional del alta.
    """
    db = sessionmaker(bind=motor)()
    try:
        roles = {"Administrador": datos_base["rol_id"]}
        for nombre in ("Superadmin", "Bodeguero", "Solicitante"):
            rol = Rol(nombre_rol=nombre, descripcion=f"Rol {nombre}")
            db.add(rol)
            db.flush()
            roles[nombre] = rol.rol_id

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
        db.commit()

        return {
            **datos_base,
            "roles": roles,
            "dep_ajeno_id": departamento_ajeno.departamento_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers: identidad por rol y cliente real
# ---------------------------------------------------------------------------


def _identidad(rol: str, departamento_id) -> IdentidadAutenticada:
    """Identidad autenticada con el rol y el departamento dados (no persistida).

    La autorizacion solo lee `usuario.rol.nombre_rol`; la derivacion
    institucional resuelve el `departamento` por ORM desde `departamento_id`.
    """
    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="RolAsignable",
        correo="sonda.rol@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-rol-asignable")


@contextmanager
def _cliente(motor, rol: str, departamento_id):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    dep = None if departamento_id is _SIN_DEPARTAMENTO else departamento_id
    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(rol, dep)
    # Feature 012 (D-3/AC-8): el alta local verifica el correo contra Clerk. La
    # costura se overridea para no invocar la red (esta suite mide el rol
    # asignable y el limite institucional, no la vinculacion Clerk).
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda _correo: True)
    )
    from tests.soporte_frontera_017 import instalar_frontera_clerk

    instalar_frontera_clerk(identidad_existente=True)
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _payload(contexto, correo: str, rol_id: int, *, departamento_id=None) -> dict:
    return {
        "nombre": "Nuevo",
        "apellido": "Usuario",
        "correo": correo,
        "departamento_id": (
            contexto["departamento_id"] if departamento_id is None else departamento_id
        ),
        "rol_id": rol_id,
    }


def _usuarios_como_administrador(motor) -> list:
    """Listado leido con el rol que conserva `/usuarios/` (Feature 017, D-10).

    Superadmin ya no accede a las rutas ordinarias de usuarios (403); el
    Administrador es el unico rol autorizado en su tenant.
    """
    with _cliente(motor, "Administrador", 1) as cliente:
        respuesta = cliente.get(RUTA_USUARIOS)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# ---------------------------------------------------------------------------
# Administrador: roles permitidos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol_asignado", ["Bodeguero", "Solicitante"])
def test_administrador_crea_usuario_con_rol_permitido(
    motor, contexto, rol_asignado
):
    """Administrador -> Bodeguero/Solicitante responde 201 y crea la fila."""
    correo = f"nuevo.{rol_asignado.lower()}@compustock.cl"
    with _cliente(motor, "Administrador", contexto["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_payload(contexto, correo, contexto["roles"][rol_asignado]),
        )
    assert respuesta.status_code == 201, respuesta.text

    cuerpo = respuesta.json()
    assert cuerpo["correo"] == correo
    assert cuerpo["rol_id"] == contexto["roles"][rol_asignado]

    correos = {u["correo"] for u in _usuarios_como_administrador(motor)}
    assert correo in correos


# ---------------------------------------------------------------------------
# Administrador: roles prohibidos (403 sin mutacion)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol_prohibido", ["Superadmin", "Administrador"])
def test_administrador_no_puede_asignar_rol_prohibido(
    motor, contexto, rol_prohibido
):
    """Administrador -> Superadmin/Administrador responde 403 y NO crea fila."""
    correo = f"intruso.{rol_prohibido.lower()}@compustock.cl"
    antes = _usuarios_como_administrador(motor)

    with _cliente(motor, "Administrador", contexto["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_payload(contexto, correo, contexto["roles"][rol_prohibido]),
        )

    despues = _usuarios_como_administrador(motor)
    assert respuesta.status_code == 403, respuesta.text
    assert len(despues) == len(antes)
    assert all(usuario["correo"] != correo for usuario in despues)


# ---------------------------------------------------------------------------
# Superadmin: sin acceso a las rutas ordinarias de usuarios (Feature 017, D-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rol_asignado", ["Superadmin", "Administrador", "Bodeguero", "Solicitante"]
)
def test_superadmin_no_accede_a_las_rutas_ordinarias_de_usuarios(
    motor, contexto, rol_asignado
):
    """D-10/AC-8: la gestion global usa `/control/*`; `/usuarios/` responde 403.

    La libertad de rol del Superadmin no se ejerce por la API tenant: el
    gobierno de Administradores tiene sus propias cinco rutas de control.
    """
    correo = f"libre.{rol_asignado.lower()}@compustock.cl"
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_payload(contexto, correo, contexto["roles"][rol_asignado]),
        )
        listado = cliente.get(RUTA_USUARIOS)
    assert respuesta.status_code == 403, respuesta.text
    assert listado.status_code == 403, listado.text


# ---------------------------------------------------------------------------
# Administrador: limite institucional del alta (AC-8)
# ---------------------------------------------------------------------------


def test_administrador_no_crea_usuario_en_departamento_ajeno(motor, contexto):
    """Un departamento de otra institucion responde 403 sin crear la fila."""
    correo = "ajeno.institucion@compustock.cl"
    antes = _usuarios_como_administrador(motor)

    with _cliente(motor, "Administrador", contexto["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_payload(
                contexto,
                correo,
                contexto["roles"]["Bodeguero"],
                departamento_id=contexto["dep_ajeno_id"],
            ),
        )

    despues = _usuarios_como_administrador(motor)
    assert respuesta.status_code == 403, respuesta.text
    assert len(despues) == len(antes)
    assert all(usuario["correo"] != correo for usuario in despues)


def test_administrador_crea_usuario_en_departamento_propio(motor, contexto):
    """Un departamento de su institucion crea el usuario correctamente."""
    correo = "propio.institucion@compustock.cl"
    with _cliente(motor, "Administrador", contexto["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_payload(
                contexto,
                correo,
                contexto["roles"]["Solicitante"],
                departamento_id=contexto["departamento_id"],
            ),
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["correo"] == correo
