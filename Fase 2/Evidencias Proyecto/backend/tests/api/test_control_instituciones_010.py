"""T2 (Feature 010): contrato HTTP del alta de institución (control).

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`) y su
`/openapi.json`. Fija el contrato antes de que exista router, servicio o schema:

  * el alta `POST /api/v1/control/instituciones/` solo la autoriza Superadmin
    (AC-7…AC-9, AC-17): sesión ausente/inválida -> 401; rol no Superadmin -> 403;
  * el contrato de éxito es `201` con `InstitucionAltaControlRespuesta` (plan §1);
  * los errores 401/403/409/422/503 quedan documentados en `/openapi.json`;
  * el DTO de entrada `InstitucionAltaControlCrear` **no** recibe nombre de esquema,
    versión, rol ni estado: el servidor los deriva (D-7, plan §1); y
  * la resolución de tenant depende de la versión objetivo
    (`VERSION_ESQUEMA_OBJETIVO`, plan §1): correo no mapeado, tenant no preparado
    o versión incompatible se deniegan cerrado (AC-2, AC-12).

Fase ROJA de TDD: la ruta aún no existe (un `404`), no figura en `/openapi.json`
y `MATRIZ_PERMISOS` no declara la operación (se cablean en T7). Los casos de
resolución de tenant (`AC-2`/`AC-12`) ya son **pruebas de comportamiento** sobre
`app.services.control_service` y `app.services.tenant_service`, creados en T5.
Este módulo no importa el router ni el schema de control a propósito: no existen
todavía (T7).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import config, permisos
from app.main import app
from app.models import (
    Institucion,
    MapaUsuarioEsquema,
    Rol,
    Usuario,
    VersionEsquema,
)
from app.services import control_service, tenant_service
from app.services.auth_service import IdentidadAutenticada

#: Ruta contractual del alta de institución (plan §1).
RUTA_ALTA = "/api/v1/control/instituciones/"

#: Centinela para distinguir "sin autenticar" de "rol ausente" (`None`).
_SIN_AUTENTICAR = object()

#: Campos obligatorios del DTO de entrada (plan §1). `rut` y `direccion` son
#: opcionales; el cliente nunca envía esquema, versión, rol ni estado.
CAMPOS_ENTRADA_OBLIGATORIOS = {
    "institucion_id",
    "nombre",
    "correo_administrador",
    "nombre_administrador",
    "apellido_administrador",
    "departamento_nombre_administrativo",
}
CAMPOS_ENTRADA_PROHIBIDOS = {
    "nombre_esquema",
    "version_esquema",
    "version",
    "rol",
    "estado",
}

#: Campos del DTO de respuesta (plan §1).
CAMPOS_RESPUESTA = {
    "institucion_id",
    "nombre",
    "correo_administrador",
    "nombre_esquema",
    "version_esquema",
    "estado",
    "mensaje",
}

#: Códigos de error que el alta debe documentar (plan §1).
CODIGOS_ERROR_DOCUMENTADOS = ("401", "403", "409", "422", "503")


# ---------------------------------------------------------------------------
# Helpers: identidad simulada y cliente del app real
# ---------------------------------------------------------------------------


def _identidad(rol: str | None) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="Control010",
        correo="sonda.control010@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-control-010")


@contextmanager
def _cliente(motor, rol=_SIN_AUTENTICAR):
    """`TestClient` del `app` real con `get_db` en SQLite y la identidad por rol.

    Con `rol=_SIN_AUTENTICAR` no se overridea `get_current_user`, de modo que la
    sesión ausente/inválida ejerce el 401 real.
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
        app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(rol)
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _operacion_alta_openapi() -> dict:
    """Devuelve la operación del alta en `/openapi.json`, o falla si no existe."""
    contrato = app.openapi()
    if RUTA_ALTA not in contrato["paths"]:
        pytest.fail(
            f"capacidad ausente (T7): la ruta {RUTA_ALTA} debe publicarse en "
            "/openapi.json."
        )
    return contrato["paths"][RUTA_ALTA]["post"]


# ---------------------------------------------------------------------------
# AC-9: 401 sin sesión / 403 con rol no Superadmin (sin mutación)
# ---------------------------------------------------------------------------


def test_alta_sin_sesion_responde_401(motor):
    """AC-9: sin Bearer válido la sesión se rechaza con 401.

    En rojo falla con 404 (la ruta aún no existe); cuando T7 la publique, el 401
    de `get_current_user` es el esperado.
    """
    with _cliente(motor, _SIN_AUTENTICAR) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json={})
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_alta_rol_no_superadmin_responde_403(motor, rol):
    """AC-9/AC-17: un rol distinto de Superadmin no autoriza el alta.

    En rojo falla con 404 (ruta ausente); con T7 el 403 de la matriz es el esperado.
    """
    with _cliente(motor, rol) as cliente:
        respuesta = cliente.post(RUTA_ALTA, json={})
    assert respuesta.status_code == 403, (rol, respuesta.text)


def test_alta_esta_declarada_solo_para_superadmin_en_la_matriz():
    """AC-17: la frontera real de autorización es la matriz central, no el cliente."""
    permitidos = permisos.MATRIZ_PERMISOS.get(("POST", RUTA_ALTA))
    assert permitidos is not None, (
        "la operación de alta debe declararse en MATRIZ_PERMISOS"
    )
    assert set(permitidos) == {"Superadmin"}


# ---------------------------------------------------------------------------
# AC-7/AC-8/AC-9: contrato del alta en /openapi.json
# ---------------------------------------------------------------------------


def test_openapi_publica_el_alta_con_201_y_seguridad():
    operacion = _operacion_alta_openapi()
    assert "201" in operacion["responses"], "el alta devuelve 201 Created"
    assert operacion.get("summary"), "la operación debe declarar un resumen"
    assert operacion.get("security"), "el alta debe exigir el esquema Bearer"
    esquema = operacion["responses"]["201"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].endswith("InstitucionAltaControlRespuesta"), esquema


def test_openapi_alta_documenta_los_errores_declarados():
    operacion = _operacion_alta_openapi()
    for codigo in CODIGOS_ERROR_DOCUMENTADOS:
        assert codigo in operacion["responses"], codigo
        assert operacion["responses"][codigo].get("description"), codigo


def test_openapi_dto_de_entrada_no_recibe_valores_de_servidor():
    """D-7/plan §1: el cliente no aporta esquema, versión, rol ni estado."""
    contrato = app.openapi()
    operacion = _operacion_alta_openapi()
    referencia = operacion["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    nombre = referencia.rsplit("/", 1)[-1]
    assert nombre == "InstitucionAltaControlCrear", referencia

    dto = contrato["components"]["schemas"][nombre]
    propiedades = set(dto["properties"])
    requeridos = set(dto.get("required", []))

    assert CAMPOS_ENTRADA_OBLIGATORIOS <= propiedades
    assert CAMPOS_ENTRADA_OBLIGATORIOS <= requeridos
    assert not (CAMPOS_ENTRADA_PROHIBIDOS & propiedades), (
        "el DTO de entrada no debe exponer nombre de esquema, versión, rol ni estado"
    )


def test_openapi_dto_de_respuesta_declara_el_contrato():
    contrato = app.openapi()
    operacion = _operacion_alta_openapi()
    referencia = operacion["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
    nombre = referencia.rsplit("/", 1)[-1]
    assert nombre == "InstitucionAltaControlRespuesta", referencia

    dto = contrato["components"]["schemas"][nombre]
    assert CAMPOS_RESPUESTA <= set(dto["properties"])
    assert CAMPOS_RESPUESTA <= set(dto.get("required", []))


# ---------------------------------------------------------------------------
# AC-2/AC-12: versión objetivo y resolución de tenant en control (fallo cerrado)
# ---------------------------------------------------------------------------


def test_version_esquema_objetivo_declarada():
    """Plan §1/stack §5: la versión objetivo es la constante de despliegue."""
    version = getattr(config, "VERSION_ESQUEMA_OBJETIVO", None)
    assert isinstance(version, str) and version, (
        "capacidad ausente (T4/T5): app.core.config debe exponer "
        "VERSION_ESQUEMA_OBJETIVO como cadena no vacía."
    )


#: Correo de un rol limitado con asociación activa en el mapa de control.
CORREO_MAPEADO = "limitado.tenant@compustock.cl"

#: Nombre de esquema asignado en el mapa de prueba.
NOMBRE_ESQUEMA_MAPEADO = "tenant_inst01_deadbeef"


@pytest.fixture
def sesion(motor):
    """Sesión de control sobre el motor SQLite en memoria (contexto lógico único)."""
    db = sessionmaker(bind=motor)()
    try:
        yield db
    finally:
        db.close()


def _registrar_mapa(db) -> None:
    """Crea la institución canónica y su asociación activa correo -> esquema."""
    db.add(Institucion(institucion_id="INST01", nombre="Institucion Uno"))
    db.flush()
    db.add(
        MapaUsuarioEsquema(
            correo=CORREO_MAPEADO,
            institucion_id="INST01",
            nombre_esquema=NOMBRE_ESQUEMA_MAPEADO,
            activo=True,
        )
    )
    db.commit()


def test_correo_no_mapeado_no_resuelve_tenant(sesion):
    """AC-2: un correo sin fila activa en el mapa no enruta a ningún esquema.

    Sin fallback a otro esquema ni a global: la resolución deniega en cerrado.
    """
    with pytest.raises(tenant_service.ErrorTenant):
        tenant_service.resolver_tenant_por_correo(sesion, "desconocido@compustock.cl")


def test_tenant_no_preparado_no_enruta(sesion):
    """AC-2/AC-12: un tenant sin fila de versión no atiende negocio.

    La asociación activa existe, pero el esquema no tiene `version_esquema`; la
    resolución deniega en vez de asumir un tenant preparado.
    """
    _registrar_mapa(sesion)

    assert control_service.tenant_en_version_objetivo(sesion) is False
    with pytest.raises(tenant_service.ErrorTenant):
        tenant_service.resolver_tenant_por_correo(sesion, CORREO_MAPEADO)


def test_version_incompatible_deniega_enrutamiento(sesion):
    """AC-12/AC-13: una versión distinta deniega en cerrado (sin fallback).

    La comparación es de igualdad exacta contra `VERSION_ESQUEMA_OBJETIVO`: un
    tenant en `009.9` no se enruta aunque su asociación esté activa.
    """
    _registrar_mapa(sesion)
    sesion.add(VersionEsquema(version="009.9"))
    sesion.commit()

    assert control_service.es_version_objetivo("009.9") is False
    with pytest.raises(tenant_service.ErrorTenant):
        tenant_service.resolver_tenant_por_correo(sesion, CORREO_MAPEADO)


def test_tenant_en_version_objetivo_resuelve_su_esquema(sesion):
    """AC-1/AC-13: con la versión objetivo, el correo resuelve su único esquema.

    Control previo: la resolución devuelve el esquema derivado del correo, no uno
    aportado por el cliente.
    """
    _registrar_mapa(sesion)
    sesion.add(VersionEsquema(version=config.VERSION_ESQUEMA_OBJETIVO))
    sesion.commit()

    resolucion = tenant_service.resolver_tenant_por_correo(sesion, CORREO_MAPEADO)
    assert resolucion.institucion_id == "INST01"
    assert resolucion.nombre_esquema == NOMBRE_ESQUEMA_MAPEADO


def test_contexto_de_solicitud_resuelve_el_tenant_del_correo(sesion):
    """AC-1/AC-3: el contexto de solicitud deriva del correo, no del cliente.

    Un rol limitado con mapa activo y versión objetivo obtiene su esquema; la
    resolución no admite ningún parámetro de tenant.
    """
    _registrar_mapa(sesion)
    sesion.add(VersionEsquema(version=config.VERSION_ESQUEMA_OBJETIVO))
    sesion.commit()

    contexto = tenant_service.resolver_contexto_solicitud(sesion, CORREO_MAPEADO)
    assert contexto.nombre_esquema == NOMBRE_ESQUEMA_MAPEADO
    assert contexto.institucion_id == "INST01"
    assert contexto.version == config.VERSION_ESQUEMA_OBJETIVO
