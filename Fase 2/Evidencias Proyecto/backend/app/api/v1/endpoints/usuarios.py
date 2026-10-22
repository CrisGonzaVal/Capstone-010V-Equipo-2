from collections.abc import Callable
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.usuario_schema import (
    UsuarioCrear,
    UsuarioEdicionConMotivo,
    UsuarioEstadoConMotivo,
    UsuarioEstadoRespuesta,
    UsuarioInvitacionRespuesta,
    UsuarioRespuesta,
)
from app.services import organizacion_service, usuario_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/usuarios", tags=["Administracion y Roles"])

#: Rutas de edicion/estado del usuario local (Feature 012, T7, diseno §1.2).
RUTA_USUARIO = "/api/v1/usuarios/{usuario_id}"
RUTA_USUARIO_ESTADO = "/api/v1/usuarios/{usuario_id}/estado"
RUTA_USUARIO_REENVIO = "/api/v1/usuarios/{usuario_id}/invitacion/reenvio"


@router.get(
    "/",
    response_model=List[UsuarioRespuesta],
    summary="Listar usuarios",
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/usuarios/"))
    ],
)
def listar_usuarios(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/usuarios/")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    return usuario_service.listar_usuarios(db, identidad, db_control=db_control)


@router.post(
    "/",
    response_model=UsuarioInvitacionRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
    description=(
        "Da de alta un usuario local con invitacion Clerk (Feature 017, D-1/D-2). "
        "Si el correo ya es una identidad en Clerk, solo se crea la asociacion "
        "local `aceptada` sin invitar; si tiene invitacion pendiente se reutiliza "
        "como asociacion `pendiente`; si no existe, se crea una invitacion y la "
        "URL se devuelve **solo** en esta respuesta. Un fallo de la frontera Clerk "
        "responde **503** y un conflicto/duplicado **409**, sin usuario local. "
        "No se crean ni modifican identidades de Clerk."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        status.HTTP_409_CONFLICT: {
            "description": (
                "Correo duplicado, ya vinculado o identidad global de control; no "
                "se crea ni se sobrescribe ningun usuario."
            )
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Cuerpo invalido; no se crea una fila local."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "Frontera Clerk no disponible o asociacion local no confirmada; el "
                "reintento completa un alta parcial sin invitar de nuevo."
            )
        },
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", "/api/v1/usuarios/"))
    ],
)
def crear_usuario(
    datos: UsuarioCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/usuarios/")
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
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    # `get_db_negocio` (no `get_db`): el usuario local vive en el esquema de **su**
    # institucion (Feature 010), no en `control`. La validacion de rol/departamento
    # y la creacion de la fila deben ocurrir en el mismo tenant que resolvio el
    # correo verificado; en control no habria roles/departamentos del tenant y el
    # alta responderia 403. La vinculacion `mapa_usuario_esquema` si vive en control
    # y se gestiona con `db_control`.
    return usuario_service.crear_usuario(
        db,
        datos,
        identidad,
        verificar_correo=verificar_correo,
        db_control=db_control,
        consultar_identidad=consultar_identidad,
        crear_invitacion_fn=crear_invitacion_fn,
        revocar_invitacion_fn=revocar_invitacion_fn,
    )


@router.put(
    "/{usuario_id}",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar un usuario local",
    description=(
        "Modifica nombre, apellido, departamento y rol de un usuario del tenant "
        "(AC-8). No cambia el correo (clave de identidad local) ni toca Clerk. Un "
        "usuario o departamento inexistente/**ajeno** responde **404** sin "
        "mutacion (AC-12); un rol no asignable por el creador, **403** (D-6/"
        "AC-10); un cuerpo invalido, **422**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Cuerpo invalido o con campos no permitidos (p. ej. `correo`); no "
                "se aplica ningun cambio."
            )
        },
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", RUTA_USUARIO))
    ],
)
def editar_usuario(
    usuario_id: int,
    datos: UsuarioEdicionConMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_USUARIO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    return organizacion_service.editar_usuario(
        db, usuario_id, datos, identidad, db_control=db_control
    )


@router.patch(
    "/{usuario_id}/estado",
    response_model=UsuarioEstadoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar la vinculacion local de un usuario",
    description=(
        "Persiste el estado local en `mapa_usuario_esquema.activo` (idempotente, "
        "D-3/AC-8/AC-11): desactivar impide que el correo resuelva al tenant sin "
        "borrar la identidad de Clerk; reactivar es el mismo endpoint con `true`. "
        "Si el usuario es encargado de algun departamento responde **409** con el "
        "motivo concreto; un usuario inexistente o ajeno, **404**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("PATCH", RUTA_USUARIO_ESTADO))
    ],
)
def cambiar_estado_usuario(
    usuario_id: int,
    datos: UsuarioEstadoConMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_USUARIO_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    mapa = organizacion_service.cambiar_estado_usuario(
        db,
        db_control,
        usuario_id,
        datos.activo,
        identidad,
        motivo=datos.motivo,
        idempotencia=datos.idempotencia,
    )
    return UsuarioEstadoRespuesta(usuario_id=usuario_id, activo=mapa.activo)


@router.post(
    "/{usuario_id}/invitacion/reenvio",
    response_model=UsuarioInvitacionRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Reenviar la invitacion de un Bodeguero o Solicitante",
    description=(
        "Crea una invitacion nueva para un Bodeguero/Solicitante activo del tenant "
        "del Administrador (Feature 017, D-4/D-10/AC-6/AC-9): intenta revocar la "
        "pendiente anterior y entrega la URL **solo** en esta respuesta. Una "
        "invitacion aceptada, una asociacion inactiva o un conflicto de Clerk "
        "responde **409** sin cambiar el identificador persistido; la reactivacion "
        "de una asociacion inactiva es una operacion separada (`PATCH .../estado` "
        "con motivo) y se realiza antes del reenvio. Superadmin recibe **403** en "
        "toda ruta ordinaria de `/usuarios/`."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        status.HTTP_409_CONFLICT: {
            "description": (
                "Invitacion ya aceptada, asociacion inactiva, usuario sin "
                "asociacion o conflicto de Clerk; no se entrega enlace ni se "
                "cambia el ID persistido."
            )
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Cuerpo invalido; no se aplica ningun cambio."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "Frontera Clerk no disponible; no se afirma que la invitacion "
                "anterior siga activa."
            )
        },
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", RUTA_USUARIO_REENVIO))
    ],
)
def reenviar_invitacion_usuario(
    usuario_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_USUARIO_REENVIO)
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
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    from app.core import security

    actor = (
        security.normalizar_correo(str(identidad.usuario.correo))
        if identidad.usuario is not None
        else "sistema"
    )
    return usuario_service.reenviar_invitacion_usuario(
        db,
        db_control,
        usuario_id,
        identidad,
        consultar_identidad=consultar_identidad,
        crear_invitacion_fn=crear_invitacion_fn,
        revocar_invitacion_fn=revocar_invitacion_fn,
        actor_correo=actor,
    )


@router.get(
    "/roles",
    summary="Listar roles disponibles",
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/usuarios/roles")),
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/usuarios/roles")),
    ],
)
def listar_roles(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_roles(db)


@router.get(
    "/departamentos",
    summary="Listar departamentos",
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(
            dependencies.requiere_capacidad("GET", "/api/v1/usuarios/departamentos")
        )
    ],
)
def listar_departamentos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/usuarios/departamentos")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return usuario_service.listar_departamentos(db, identidad)


@router.get(
    "/instituciones",
    summary="Listar instituciones",
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(
            dependencies.requiere_capacidad("GET", "/api/v1/usuarios/instituciones")
        )
    ],
)
def listar_instituciones(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/usuarios/instituciones")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return usuario_service.listar_instituciones(db, identidad)
