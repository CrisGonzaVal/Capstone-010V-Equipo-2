"""T6 (Feature 010): contrato del aprovisionamiento de instituciones.

Seam bajo prueba: la **operacion HTTP real** `POST /api/v1/control/instituciones/`
(`TestClient` sobre `app.main.app`) y su **efecto observable** en el esquema de
control (registro de institucion, mapa `correo -> esquema`, usuario Administrador
inicial y `version_esquema`). Esta tarea fija el contrato **antes** de que T7
implemente el servicio y el router:

  * Clerk **existente** (AC-7): un correo de Administrador verificado en Clerk
    permite el alta y deja el tenant operativo (registro, mapa, Administrador,
    version objetivo); la respuesta es `201` con `nombre_esquema` derivado en
    servidor y `estado=operativa`.
  * Clerk **inexistente** (AC-8): un correo sin identidad en Clerk falla de forma
    explicita (`422`) y **no deja tenant operativo**.
  * **fallo de la frontera Clerk** (verificador que levanta): el alta responde
    `503` y no deja estado parcial.
  * **Superadmin** puede solicitar el alta; un **rol limitado** recibe `403` y
    **no crea** institucion, mapa ni esquema (AC-7/AC-9).
  * **duplicados/colision** (AC-8): `institucion_id` repetido, correo de
    Administrador ya mapeado, usuario local con ese correo y colision de
    `nombre_esquema` responden conflicto (`409`) sin mutar el estado previo.
  * **fallos por etapa** y su **compensacion**: ningun fallo deja institucion,
    mapa, usuario ni version parciales (AC-8).

Costura Clerk: la verificacion de existencia del correo en Clerk se inyecta con
una dependencia (`app.api.dependencies.obtener_verificador_correo_clerk`), de modo
que **ninguna prueba unitaria invoca Clerk real** (plan §3). El contrato del
verificador es `Callable[[str], bool]`: `True` si el correo existe, `False` si no,
y `app.core.security.ErrorAutenticacion` si la consulta a Clerk no se puede
completar.

Fase ROJA de TDD: el router y el servicio aun no existen (la ruta responde `404`)
y la costura de verificacion no esta cableada; cada prueba falla por **capacidad
ausente** (estado esperado distinto o `pytest.fail` explicito) —nunca por
importacion ni sintaxis. Las pruebas Angular del portal `/control` (estados de
carga/error/exito y guard) se **difieren a T12**, donde se implementa el portal
(ver nota en `tasks.md`): no se crean esqueletos de guard ni de componente aqui.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import config, security
from app.main import app
from app.models import (
    Departamento,
    Institucion,
    MapaUsuarioEsquema,
    Rol,
    Usuario,
    VersionEsquema,
)
from app.services import tenant_service
from app.services.auth_service import IdentidadAutenticada

#: Ruta contractual del alta de institucion (plan §1).
RUTA_ALTA = "/api/v1/control/instituciones/"

#: Correo del Administrador cuyo tenant se aprovisiona en las pruebas de exito.
CORREO_ADMINISTRADOR = "admin.nuevo@compustock.cl"

#: Campos obligatorios del cuerpo de alta (plan §1); el cliente nunca envia
#: esquema, version, rol ni estado (T2 fija ese DTO).
_CAMPOS_CUERPO_BASE = {
    "nombre": "Institucion Nueva",
    "correo_administrador": CORREO_ADMINISTRADOR,
    "nombre_administrador": "Ada",
    "apellido_administrador": "Administradora",
    "departamento_nombre_administrativo": "Administracion",
}


# ---------------------------------------------------------------------------
# Helpers: identidad simulada, costura Clerk, cliente del app real y estado
# ---------------------------------------------------------------------------


def _identidad(rol: str) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Aprovisionamiento010",
        correo="sonda.aprovisionamiento010@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-aprovisionamiento-010")


def _costura_verificador():
    """Dependencia de verificacion Clerk, o `None` si T7 aun no la creo."""
    return getattr(dependencies, "obtener_verificador_correo_clerk", None)


def _fabrica(motor) -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=motor)


@contextmanager
def _cliente(motor, rol: str, verificar: Callable[[str], bool]):
    """`TestClient` del app real con `get_db`, la identidad y la costura Clerk.

    `verificar` sustituye la verificacion de existencia del correo en Clerk: las
    pruebas unitarias nunca invocan Clerk real. Si T7 aun no expone la costura, no
    se overridea (la ruta tampoco existe todavia; el fallo es por capacidad
    ausente). Las excepciones no manejadas se vuelven `500` para poder observar
    que el contrato esperado (p. ej. `503`) no se cumple.
    """
    Fabrica = _fabrica(motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(rol)
    costura = _costura_verificador()
    if costura is not None:
        app.dependency_overrides[costura] = lambda: verificar
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _cuerpo(institucion_id: str = "INST01", **cambios) -> dict:
    return {"institucion_id": institucion_id, **_CAMPOS_CUERPO_BASE, **cambios}


def _estado_relevante(motor) -> dict:
    """Foto del estado que un alta **no** debe dejar a medias (control + tenant).

    En el contexto logico unico de SQLite, control y tenant comparten tablas, por
    lo que la foto es el conjunto de instituciones, mapeos, usuarios y versiones
    observables. Un alta fallida debe dejar estos conjuntos **identicos**.
    """
    sesion = sessionmaker(bind=motor)()
    try:
        return {
            "instituciones": sorted(
                i.institucion_id for i in sesion.execute(select(Institucion)).scalars()
            ),
            "mapas": sorted(
                (m.correo, m.institucion_id, m.nombre_esquema)
                for m in sesion.execute(select(MapaUsuarioEsquema)).scalars()
            ),
            "usuarios": sorted(u.correo for u in sesion.execute(select(Usuario)).scalars()),
            "versiones": sorted(
                v.version for v in sesion.execute(select(VersionEsquema)).scalars()
            ),
        }
    finally:
        sesion.close()


def _sembrar(motor, *objetos) -> None:
    """Siembra objetos en orden, con `flush` por objeto.

    El ORM no declara `relationship()` entre el mapa y `institucion` (ni entre
    `usuario` y sus catalogos por id), por lo que el orden de `INSERT` no se
    infiere del FK del DDL: se fuerza el orden de siembra con un `flush` por
    objeto para no disparar una FK antes de tiempo (el fallo debe ser del alta,
    no del andamiaje de la prueba).

    La sesion usa `expire_on_commit=False`: el andamiaje lee identificadores
    generados (`departamento_id`, `rol_id`) despues del `commit`, y con la
    expiracion por defecto la instancia queda desligada y no puede refrescarse.
    """
    sesion = sessionmaker(bind=motor, expire_on_commit=False)()
    try:
        for objeto in objetos:
            sesion.add(objeto)
            sesion.flush()
        sesion.commit()
    finally:
        sesion.close()


def _verificador_clerk_caido(correo: str):
    """Verificador que simula la frontera Clerk inaccesible (fallo de red)."""
    raise security.ErrorAutenticacion("Clerk no disponible para verificar el correo")


# ---------------------------------------------------------------------------
# La costura de verificacion Clerk existe y es inyectable (contrato de T7)
# ---------------------------------------------------------------------------


def test_costura_de_verificacion_clerk_es_inyectable():
    """El alta verifica la existencia del correo en Clerk tras una costura.

    Plan §3: las pruebas unitarias no invocan Clerk real. El contrato exige una
    dependencia inyectable `obtener_verificador_correo_clerk` que devuelva un
    `Callable[[str], bool]`.
    """
    if _costura_verificador() is None:
        pytest.fail(
            "capacidad ausente (T7): app.api.dependencies.obtener_verificador_correo_clerk "
            "debe exponer la costura inyectable que verifica si el correo del "
            "Administrador existe en Clerk."
        )


# ---------------------------------------------------------------------------
# AC-7: Clerk existente y Superadmin -> tenant operativo completo
# ---------------------------------------------------------------------------


def test_alta_con_correo_clerk_existente_crea_tenant_operativo(motor):
    """AC-7: con correo verificado en Clerk y Superadmin, el alta deja el tenant.

    El esquema es el nombre determinista del `institucion_id` (derivado en
    servidor, no aportado por el cliente), la version es la objetivo y el estado
    es `operativa`. En control quedan institucion, mapa correo-esquema y usuario
    Administrador; el tenant queda versionado.
    """
    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 201, respuesta.text

    cuerpo = respuesta.json()
    esquema_esperado = tenant_service.nombre_esquema_para_institucion("INST01")
    assert cuerpo["institucion_id"] == "INST01"
    assert cuerpo["nombre"] == "Institucion Nueva"
    assert cuerpo["correo_administrador"] == CORREO_ADMINISTRADOR
    assert cuerpo["nombre_esquema"] == esquema_esperado
    assert cuerpo["version_esquema"] == config.VERSION_ESQUEMA_OBJETIVO
    assert cuerpo["estado"] == "operativa"
    assert cuerpo.get("mensaje")

    sesion = sessionmaker(bind=motor)()
    try:
        assert sesion.get(Institucion, "INST01") is not None, "falta el registro de institucion"

        mapa = sesion.execute(
            select(MapaUsuarioEsquema).where(MapaUsuarioEsquema.correo == CORREO_ADMINISTRADOR)
        ).scalar_one_or_none()
        assert mapa is not None, "falta el mapa correo-esquema"
        assert mapa.institucion_id == "INST01"
        assert mapa.nombre_esquema == esquema_esperado
        assert mapa.activo is True

        administrador = sesion.execute(
            select(Usuario).where(Usuario.correo == CORREO_ADMINISTRADOR)
        ).scalar_one_or_none()
        assert administrador is not None, "falta el usuario Administrador inicial"
        assert administrador.rol is not None
        assert administrador.rol.nombre_rol == "Administrador"

        versiones = sesion.execute(select(VersionEsquema)).scalars().all()
        assert [v.version for v in versiones] == [config.VERSION_ESQUEMA_OBJETIVO], (
            "el tenant debe quedar exactamente en la version objetivo"
        )
    finally:
        sesion.close()


def test_alta_deja_un_tenant_resoluble_por_su_administrador(motor):
    """AC-7/AC-13: el Administrador dado de alta resuelve su esquema en control.

    Comprobacion de integracion con `tenant_service`: el correo recien mapeado y
    el tenant versionado deben ser enrutables (mismo camino que usa la sesion de
    negocio en T5).
    """
    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 201, respuesta.text

    sesion = sessionmaker(bind=motor)()
    try:
        resolucion = tenant_service.resolver_tenant_por_correo(sesion, CORREO_ADMINISTRADOR)
        assert resolucion.institucion_id == "INST01"
        assert resolucion.nombre_esquema == respuesta.json()["nombre_esquema"]
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# AC-8: Clerk inexistente / no disponible -> fallo explicito sin tenant
# ---------------------------------------------------------------------------


def test_alta_con_correo_clerk_inexistente_falla_sin_tenant(motor):
    """AC-8: un correo sin identidad Clerk falla (`422`) y no deja tenant.

    La comprobacion ocurre antes de crear cualquier recurso: el estado previo se
    conserva intacto.
    """
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", lambda _correo: False) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 422, respuesta.text

    assert _estado_relevante(motor) == antes, "un correo Clerk inexistente no deja tenant"


def test_alta_con_frontera_clerk_caida_responde_503_sin_tenant(motor):
    """AC-8: si Clerk no puede verificar el correo, el alta responde `503`.

    Un fallo de la frontera externa es indisponibilidad (no autenticacion del
    solicitante) y no deja estado parcial.
    """
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", _verificador_clerk_caido) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 503, respuesta.text

    assert _estado_relevante(motor) == antes, "una caida de Clerk no deja tenant"


# ---------------------------------------------------------------------------
# AC-7/AC-9: Superadmin autoriza; un rol limitado no crea nada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_alta_por_rol_limitado_deniega_y_no_crea_nada(motor, rol):
    """AC-9/AC-17: un rol distinto de Superadmin recibe `403` sin mutacion.

    Aunque el correo de Administrador exista en Clerk, la autorizacion de la
    matriz central deniega antes de crear institucion, mapa o esquema.
    """
    antes = _estado_relevante(motor)

    with _cliente(motor, rol, lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 403, (rol, respuesta.text)

    assert _estado_relevante(motor) == antes, (
        "un rol no Superadmin no debe crear institucion, mapa ni esquema"
    )


# ---------------------------------------------------------------------------
# AC-8: duplicados y colision de esquema -> conflicto sin mutar
# ---------------------------------------------------------------------------


def test_alta_duplicada_por_institucion_id_responde_409_sin_mutar(motor):
    """AC-8: un `institucion_id` ya registrado da `409` sin alterar el estado."""
    _sembrar(motor, Institucion(institucion_id="INST01", nombre="Institucion Existente"))
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 409, respuesta.text

    assert _estado_relevante(motor) == antes


def test_alta_con_correo_administrador_ya_mapeado_responde_409(motor):
    """AC-8: un correo ya asignado a otro esquema da `409` sin mutar.

    La unicidad del mapa (`correo -> esquema`) se reserva antes de crear
    recursos; el estado previo queda intacto.
    """
    _sembrar(
        motor,
        Institucion(institucion_id="OTRA", nombre="Institucion Ajena"),
        MapaUsuarioEsquema(
            correo=CORREO_ADMINISTRADOR,
            institucion_id="OTRA",
            nombre_esquema="tenant_otra_cafe0000",
            activo=True,
        ),
    )
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 409, respuesta.text

    assert _estado_relevante(motor) == antes
    assert "INST01" not in _estado_relevante(motor)["instituciones"]


def test_alta_con_usuario_local_ya_existente_compensa_sin_tenant(motor):
    """AC-8: fallo en la etapa del usuario inicial compensa sin dejar institución.

    El correo ya existe como usuario local (unicidad `usuario.correo`), de modo
    que la etapa de creacion del Administrador falla despues de reservar la
    institucion en control: el alta debe compensar (rollback) y **no** dejar la
    institucion, el mapa ni la version parciales.
    """
    rol = Rol(nombre_rol="Administrador", descripcion="Rol de la institucion ajena")
    institucion = Institucion(institucion_id="OTRA", nombre="Institucion Ajena")
    departamento = Departamento(
        nombre_dep="Administracion",
        descripcion="Departamento ajeno",
        institucion_id="OTRA",
    )
    _sembrar(motor, rol, institucion, departamento)
    _sembrar(
        motor,
        Usuario(
            nombre="Ada",
            apellido="Ya existe",
            correo=CORREO_ADMINISTRADOR,
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        ),
    )
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 409, respuesta.text

    assert _estado_relevante(motor) == antes, (
        "el fallo por etapa no debe dejar institucion, mapa ni version parciales"
    )
    assert "INST01" not in _estado_relevante(motor)["instituciones"]


def test_colision_de_nombre_esquema_responde_409_sin_tenant_parcial(motor):
    """AC-8: una colision de `nombre_esquema` da `409` sin sobrescribir esquemas.

    El nombre del esquema es determinista a partir del `institucion_id`; si otro
    registro ya ocupa ese nombre, el alta falla y no queda ningun tenant parcial
    (ni institucion `INST01`, ni mapa del Administrador, ni version).
    """
    nombre_en_colision = tenant_service.nombre_esquema_para_institucion("INST01")
    _sembrar(
        motor,
        Institucion(institucion_id="OTRA", nombre="Institucion Ajena"),
        MapaUsuarioEsquema(
            correo="otro.correo@compustock.cl",
            institucion_id="OTRA",
            nombre_esquema=nombre_en_colision,
            activo=True,
        ),
    )
    antes = _estado_relevante(motor)

    with _cliente(motor, "Superadmin", lambda _correo: True) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json=_cuerpo())
    assert respuesta.status_code == 409, respuesta.text

    estado = _estado_relevante(motor)
    assert estado == antes, "la colision no debe mutar el estado previo"
    assert "INST01" not in estado["instituciones"]
    assert (
        CORREO_ADMINISTRADOR,
        "INST01",
        nombre_en_colision,
    ) not in estado["mapas"], "no debe quedar un mapa parcial del Administrador"
