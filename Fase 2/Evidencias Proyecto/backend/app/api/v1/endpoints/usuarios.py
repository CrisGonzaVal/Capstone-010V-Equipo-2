from collections.abc import Callable
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.usuario_schema import (
    UsuarioCrear,
    UsuarioEdicion,
    UsuarioEstado,
    UsuarioEstadoRespuesta,
    UsuarioRespuesta,
)
from app.services import organizacion_service, usuario_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/usuarios", tags=["Administracion y Roles"])

#: Rutas de edicion/estado del usuario local (Feature 012, T7, diseno §1.2).
RUTA_USUARIO = "/api/v1/usuarios/{usuario_id}"
RUTA_USUARIO_ESTADO = "/api/v1/usuarios/{usuario_id}/estado"


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
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
    description=(
        "Da de alta un usuario local (D-3/AC-8). Clerk es la unica autoridad de "
        "identidad: el correo debe existir previamente como identidad verificada "
        "en Clerk; si no existe responde **422** y si la frontera externa no puede "
        "verificarse responde **503**, sin crear un usuario local no autenticable. "
        "No se crean ni modifican identidades de Clerk."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Cuerpo invalido o correo sin identidad verificada en Clerk; no se "
                "crea una fila local no autenticable."
            )
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "No fue posible verificar el correo contra Clerk: la frontera "
                "externa esta indisponible y no se crea ningun usuario."
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
    datos: UsuarioEdicion,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_USUARIO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return organizacion_service.editar_usuario(db, usuario_id, datos, identidad)


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
    datos: UsuarioEstado,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_USUARIO_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
    db_control: Session = Depends(dependencies.get_db),
):
    mapa = organizacion_service.cambiar_estado_usuario(
        db, db_control, usuario_id, datos.activo, identidad
    )
    return UsuarioEstadoRespuesta(usuario_id=usuario_id, activo=mapa.activo)


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
