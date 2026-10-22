"""Endpoint del alta de institucion en el portal de control (Feature 010, T7).

Router delgado: autoriza por la matriz central (solo Superadmin) e inyecta la
costura de verificacion Clerk, la sesion de control (`Depends(get_db)`) y delega
toda la logica de aprovisionamiento en `app.services.control_service`. No
contiene consultas ni reglas de negocio (AGENTS §6).

El esquema, la version, el rol y el estado los deriva el **servidor**; el cliente
solo envia el DTO de entrada (D-7, AC-7…AC-9).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.control_schema import (
    AdministradorListadoControlRespuesta,
    CapacidadActualizar,
    CapacidadFuncional,
    CapacidadRespuesta,
    DashboardSaaSRespuesta,
    InstitucionAltaControlCrear,
    InstitucionAltaControlRespuesta,
    InstitucionControlRespuesta,
    InstitucionEdicion,
    InstitucionEstado,
    InstitucionEstadoRespuesta,
)
from app.schemas.usuario_schema import (
    UsuarioCrear,
    UsuarioEdicionConMotivo,
    UsuarioEstadoConMotivo,
    UsuarioInvitacionRespuesta,
    UsuarioRespuesta,
)
from app.services import control_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/control", tags=["Control"])

#: Ruta contractual del alta de institucion (plan §1); clave de la matriz.
RUTA_ALTA = "/api/v1/control/instituciones/"

#: Rutas contractuales de la gestion administrativa de control (diseno §1).
RUTA_LISTA = "/api/v1/control/instituciones/"
RUTA_DETALLE = "/api/v1/control/instituciones/{institucion_id}"
RUTA_ESTADO = "/api/v1/control/instituciones/{institucion_id}/estado"
RUTA_DASHBOARD = "/api/v1/control/dashboard"
RUTA_CAPACIDADES = "/api/v1/control/instituciones/{institucion_id}/capacidades"
RUTA_CAPACIDAD = (
    "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}"
)

#: Respuestas de error del alta ademas de las de autorizacion (401/403).
_RESPUESTAS_ALTA = {
    **dependencies.respuestas_de_autorizacion(),
    status.HTTP_409_CONFLICT: {
        "description": (
            "Institucion, correo o nombre de esquema ya registrado, o fallo de "
            "una etapa del alta: no se aplica ningun cambio parcial."
        )
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": (
            "El correo del Administrador no existe en Clerk o el cuerpo es "
            "invalido (el cliente no aporta esquema, version, rol ni estado)."
        )
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": (
            "No fue posible verificar el correo contra Clerk: la frontera externa "
            "esta indisponible y no se crea ningun recurso."
        )
    },
}


@router.post(
    "/instituciones/",
    response_model=InstitucionAltaControlRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Aprovisionar una institucion y su primer Administrador",
    description=(
        "Da de alta una institucion y su primer Administrador (D-7). Solo lo "
        "autoriza **Superadmin** mediante la matriz central (AC-7…AC-9). El "
        "correo del Administrador debe existir previamente en Clerk; si no "
        "existe responde **422** y si Clerk no puede verificar responde **503**, "
        "sin dejar tenant operativo.\n\n"
        "En exito (**201**) el servidor deriva el nombre de esquema "
        "determinista y crea en control la institucion, el mapa "
        "`correo -> esquema`, el usuario Administrador inicial y la version "
        "objetivo. El cliente **no** envia nombre de esquema, version, rol ni "
        "estado. Un duplicado o colision responde **409** sin mutar el estado, y "
        "un fallo de cualquier etapa compensa (rollback): ningun tenant queda "
        "parcial y un reintento no duplica ni sobrescribe datos previos."
    ),
    responses=_RESPUESTAS_ALTA,
)
def alta_institucion(
    datos: InstitucionAltaControlCrear,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_ALTA)
    ),
    verificar_correo: Callable[[str], bool] = Depends(
        dependencies.obtener_verificador_correo_clerk
    ),
    consultar_identidad: Callable = Depends(
        dependencies.obtener_consultor_identidad_clerk
    ),
    crear_invitacion_fn: Callable = Depends(
        dependencies.obtener_creador_invitacion_clerk
    ),
    revocar_invitacion_fn: Callable = Depends(
        dependencies.obtener_revocador_invitacion_clerk
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionAltaControlRespuesta:
    try:
        return control_service.aprovisionar_institucion(
            db,
            datos,
            verificar_correo,
            consultar_identidad=consultar_identidad,
            crear_invitacion_fn=crear_invitacion_fn,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
    except control_service.ErrorCorreoInexistente as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except control_service.ErrorConflictoAprovisionamiento as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (
        control_service.ErrorClerkNoDisponible,
        control_service.ErrorAltaParcialIncompatible,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Gestion administrativa de instituciones (Feature 012, T6)
# ---------------------------------------------------------------------------


def _respuestas_admin(
    *, oculto: bool = False, conflicto: bool = False, payload: bool = False
) -> dict[int, dict[str, str]]:
    """Respuestas documentadas: autorizacion + 404/409/422 segun la operacion."""
    respuestas = dict(dependencies.respuestas_de_autorizacion())
    if oculto:
        respuestas.update(dependencies.respuesta_recurso_oculto())
    if conflicto:
        respuestas.update(dependencies.respuesta_conflicto())
    if payload:
        respuestas[status.HTTP_422_UNPROCESSABLE_CONTENT] = {
            "description": (
                "Cuerpo o funcion invalidos (el cliente no aporta esquema, "
                "version ni estado); no se aplica ningun cambio."
            )
        }
    return respuestas


@router.get(
    "/instituciones/",
    response_model=list[InstitucionControlRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar las instituciones registradas",
    description=(
        "Devuelve el registro institucional canonico de control con su estado "
        "(`activo`) y el `nombre_esquema` derivado. Solo **Superadmin** (AC-1)."
    ),
    responses=_respuestas_admin(),
)
def listar_instituciones(
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_LISTA)
    ),
    db: Session = Depends(dependencies.get_db),
) -> list[InstitucionControlRespuesta]:
    return control_service.listar_instituciones(db)


@router.get(
    "/instituciones/{institucion_id}",
    response_model=InstitucionControlRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar una institucion registrada",
    description=(
        "Devuelve una institucion canonica de control por id. Una institucion "
        "inexistente responde **404**. Solo **Superadmin** (AC-1)."
    ),
    responses=_respuestas_admin(oculto=True),
)
def obtener_institucion(
    institucion_id: str,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_DETALLE)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionControlRespuesta:
    try:
        return control_service.obtener_institucion(db, institucion_id)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put(
    "/instituciones/{institucion_id}",
    response_model=InstitucionControlRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar una institucion registrada",
    description=(
        "Modifica los atributos canonicos (`nombre`, `rut`, `direccion`) en el "
        "registro fuente de verdad de control y sincroniza con el espejo tenant "
        "**solo** `institucion_id` + `nombre` (D-1/AC-1). El cliente no aporta "
        "estado, esquema ni version. Una institucion inexistente responde **404** "
        "y un cuerpo invalido **422**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def editar_institucion(
    institucion_id: str,
    datos: InstitucionEdicion,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_DETALLE)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionControlRespuesta:
    try:
        return control_service.editar_institucion(db, institucion_id, datos)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/instituciones/{institucion_id}/estado",
    response_model=InstitucionEstadoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar una institucion",
    description=(
        "Persiste el estado de ciclo de vida `control.institucion.activo` de "
        "forma logica y reversible: desactivar no borra la fila, el tenant, los "
        "datos ni el historial; reactivar es el mismo endpoint con `true` "
        "(D-2/AC-2). Una institucion inexistente responde **404** y un cuerpo "
        "invalido **422**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def cambiar_estado_institucion(
    institucion_id: str,
    datos: InstitucionEstado,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionEstadoRespuesta:
    try:
        return control_service.cambiar_estado_institucion(
            db, institucion_id, datos.activo
        )
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/dashboard",
    response_model=DashboardSaaSRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar el dashboard SaaS del Superadmin",
    description=(
        "Panorama tecnico del Superadmin con taxonomia unica de tenant "
        "(Feature 017, D-8/AC-13/AC-14): **operativo** (activa, enrutable y "
        "version exacta: muestra conteos), **no enrutable** (inactiva o sin "
        "metadatos/routing: no se abre el tenant) y **no disponible** (tenant "
        "caido o version ausente/ilegible/incompatible: conteos no disponibles, "
        "nunca cero). Las inactivas se listan y cuentan en el total. Los "
        "agregados distinguen instituciones con conteos conocidos de las no "
        "disponibles. No contiene datos personales, de negocio ni motivos. Solo "
        "**Superadmin**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "El esquema de control no pudo enumerarse; la clasificacion por "
                "institucion no disponible se mantiene como 200 con la taxonomia D-8."
            )
        },
    },
)
def consultar_dashboard(
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_DASHBOARD)
    ),
    db: Session = Depends(dependencies.get_db),
) -> DashboardSaaSRespuesta:
    try:
        return control_service.dashboard_saas(db)
    except control_service.ErrorTenantNoDisponible as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get(
    "/instituciones/{institucion_id}/capacidades",
    response_model=list[CapacidadRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Consultar las capacidades funcionales de una institucion",
    description=(
        "Devuelve las seis capacidades del conjunto cerrado con su estado "
        "persistido en control (D-6/AC-5). Una institucion inexistente responde "
        "**404**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True),
)
def listar_capacidades(
    institucion_id: str,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_CAPACIDADES)
    ),
    db: Session = Depends(dependencies.get_db),
) -> list[CapacidadRespuesta]:
    try:
        return control_service.listar_capacidades(db, institucion_id)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put(
    "/instituciones/{institucion_id}/capacidades/{funcion}",
    response_model=CapacidadRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Habilitar o deshabilitar una capacidad funcional",
    description=(
        "Persiste el estado (`habilitada`) de una de las seis capacidades de la "
        "institucion (D-6/AC-5). Una funcion fuera del conjunto cerrado responde "
        "**422** y una institucion inexistente **404**, sin mutacion; solo "
        "**Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def actualizar_capacidad(
    institucion_id: str,
    funcion: CapacidadFuncional,
    datos: CapacidadActualizar,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_CAPACIDAD)
    ),
    db: Session = Depends(dependencies.get_db),
) -> CapacidadRespuesta:
    try:
        return control_service.actualizar_capacidad(
            db, institucion_id, funcion.value, datos.habilitada
        )
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except control_service.ErrorFuncionInvalida as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Gobierno de Administradores por institucion (Feature 017, D-10/AC-8)
# ---------------------------------------------------------------------------

RUTA_ADMIN_LISTA = "/api/v1/control/instituciones/{institucion_id}/usuarios/"
RUTA_ADMIN = "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
RUTA_ADMIN_ESTADO = (
    "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado"
)
RUTA_ADMIN_REENVIO = (
    "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
    "/invitacion/reenvio"
)

_RESPUESTAS_ADMIN_INSTITUCION = {
    **dependencies.respuestas_de_autorizacion(),
    **dependencies.respuesta_recurso_oculto(),
    status.HTTP_409_CONFLICT: {
        "description": (
            "Correo duplicado/vinculado, baja del ultimo Administrador activo, "
            "invitacion ya aceptada o conflicto de Clerk; sin mutacion."
        )
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": (
            "Cuerpo, rol o motivo invalidos; el cliente nunca aporta esquema ni "
            "institucion de la sesion."
        )
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": (
            "Frontera Clerk o segunda confirmacion local no disponible; el alta "
            "parcial es recuperable por reintento."
        )
    },
}


def _traducir_error_administrador(exc: Exception) -> HTTPException:
    if isinstance(exc, control_service.ErrorTenantNoDisponible):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    if isinstance(exc, control_service.ErrorInstitucionNoEncontrada):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, control_service.ErrorAdministradorNoEncontrado):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/instituciones/{institucion_id}/usuarios/",
    response_model=list[AdministradorListadoControlRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar los Administradores de una institucion",
    description=(
        "Listado minimo de Administradores institucionales (Feature 017, D-10/AC-5): "
        "publica solo usuario_id, nombre, apellido, correo, estado local y estado "
        "de invitacion persistido. Nunca consulta Clerk ni expone la URL. El "
        "esquema se deriva en servidor desde el registro de control. Solo "
        "**Superadmin**."
    ),
    responses=_RESPUESTAS_ADMIN_INSTITUCION,
)
def listar_administradores_control(
    institucion_id: str,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_ADMIN_LISTA)
    ),
    db: Session = Depends(dependencies.get_db),
) -> list[AdministradorListadoControlRespuesta]:
    try:
        return control_service.listar_administradores_control(db, institucion_id)
    except (
        control_service.ErrorInstitucionNoEncontrada,
        control_service.ErrorTenantNoDisponible,
    ) as exc:
        raise _traducir_error_administrador(exc) from exc


@router.post(
    "/instituciones/{institucion_id}/usuarios/",
    response_model=UsuarioInvitacionRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un Administrador institucional",
    description=(
        "Alta de un Administrador de la institucion desde control (D-10). El "
        "servidor valida la institucion, deriva el esquema y aplica el flujo de "
        "invitacion/compensacion del alta tenant. La URL se entrega solo en esta "
        "respuesta y nunca se persiste. Solo **Superadmin**."
    ),
    responses=_RESPUESTAS_ADMIN_INSTITUCION,
)
def crear_administrador_control(
    institucion_id: str,
    datos: UsuarioCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_ADMIN_LISTA)
    ),
    consultar_identidad: Callable = Depends(
        dependencies.obtener_consultor_identidad_clerk
    ),
    crear_invitacion_fn: Callable = Depends(
        dependencies.obtener_creador_invitacion_clerk
    ),
    revocar_invitacion_fn: Callable = Depends(
        dependencies.obtener_revocador_invitacion_clerk
    ),
    db: Session = Depends(dependencies.get_db),
) -> UsuarioInvitacionRespuesta:
    try:
        return control_service.crear_administrador_control(
            db,
            institucion_id,
            datos,
            identidad,
            consultar_identidad=consultar_identidad,
            crear_invitacion_fn=crear_invitacion_fn,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
    except (
        control_service.ErrorInstitucionNoEncontrada,
        control_service.ErrorAdministradorNoEncontrado,
        control_service.ErrorRolAdministradorInvalido,
        control_service.ErrorTenantNoDisponible,
    ) as exc:
        raise _traducir_error_administrador(exc) from exc


@router.put(
    "/instituciones/{institucion_id}/usuarios/{usuario_id}",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar un Administrador institucional",
    description=(
        "Edicion motivada de un Administrador (D-7/D-10). Una edicion efectiva "
        "exige motivo del catalogo cerrado; sin cambios es idempotente y no exige "
        "ni registra motivo. Solo **Superadmin**."
    ),
    responses=_RESPUESTAS_ADMIN_INSTITUCION,
)
def editar_administrador_control(
    institucion_id: str,
    usuario_id: int,
    datos: UsuarioEdicionConMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_ADMIN)
    ),
    db: Session = Depends(dependencies.get_db),
) -> UsuarioRespuesta:
    try:
        return control_service.editar_administrador_control(
            db, institucion_id, usuario_id, datos, identidad
        )
    except (
        control_service.ErrorInstitucionNoEncontrada,
        control_service.ErrorAdministradorNoEncontrado,
        control_service.ErrorTenantNoDisponible,
    ) as exc:
        raise _traducir_error_administrador(exc) from exc


@router.patch(
    "/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar un Administrador institucional",
    description=(
        "Baja/reactivacion motivada de un Administrador (D-7/D-10/AC-12). El "
        "estado se persiste en el mapa de control; la baja del ultimo "
        "Administrador activo responde **409** sin mutar. Solo **Superadmin**."
    ),
    responses=_RESPUESTAS_ADMIN_INSTITUCION,
)
def cambiar_estado_administrador_control(
    institucion_id: str,
    usuario_id: int,
    datos: UsuarioEstadoConMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_ADMIN_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db),
) -> UsuarioRespuesta:
    try:
        usuario, mapa = control_service.cambiar_estado_administrador_control(
            db, institucion_id, usuario_id, datos, identidad
        )
    except (
        control_service.ErrorInstitucionNoEncontrada,
        control_service.ErrorAdministradorNoEncontrado,
        control_service.ErrorTenantNoDisponible,
    ) as exc:
        raise _traducir_error_administrador(exc) from exc
    usuario.activo = mapa.activo
    return usuario


@router.post(
    "/instituciones/{institucion_id}/usuarios/{usuario_id}/invitacion/reenvio",
    response_model=UsuarioInvitacionRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Reenviar la invitacion de un Administrador",
    description=(
        "Crea una invitacion nueva para un Administrador (D-4/D-10): intenta "
        "revocar la anterior y entrega la nueva URL solo en esta respuesta. Una "
        "invitacion aceptada o un conflicto de Clerk responde **409** sin cambiar "
        "el identificador persistido. Solo **Superadmin**."
    ),
    responses=_RESPUESTAS_ADMIN_INSTITUCION,
)
def reenviar_invitacion_administrador_control(
    institucion_id: str,
    usuario_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_ADMIN_REENVIO)
    ),
    consultar_identidad: Callable = Depends(
        dependencies.obtener_consultor_identidad_clerk
    ),
    crear_invitacion_fn: Callable = Depends(
        dependencies.obtener_creador_invitacion_clerk
    ),
    revocar_invitacion_fn: Callable = Depends(
        dependencies.obtener_revocador_invitacion_clerk
    ),
    db: Session = Depends(dependencies.get_db),
) -> UsuarioInvitacionRespuesta:
    from app.core import security

    actor = security.normalizar_correo(str(identidad.usuario.correo))
    try:
        return control_service.reenviar_invitacion_administrador_control(
            db,
            institucion_id,
            usuario_id,
            consultar_identidad=consultar_identidad,
            crear_invitacion_fn=crear_invitacion_fn,
            revocar_invitacion_fn=revocar_invitacion_fn,
            actor_correo=actor,
        )
    except (
        control_service.ErrorInstitucionNoEncontrada,
        control_service.ErrorAdministradorNoEncontrado,
        control_service.ErrorTenantNoDisponible,
    ) as exc:
        raise _traducir_error_administrador(exc) from exc
