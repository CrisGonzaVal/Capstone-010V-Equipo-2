from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.usuario_schema import UsuarioCrear, UsuarioRespuesta
from app.services import usuario_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/usuarios", tags=["Administracion y Roles"])


@router.get(
    "/",
    response_model=List[UsuarioRespuesta],
    summary="Listar usuarios",
    responses=dependencies.respuestas_de_autorizacion(),
)
def listar_usuarios(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/usuarios/")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return usuario_service.listar_usuarios(db, identidad)


@router.post(
    "/",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
    responses=dependencies.respuestas_de_autorizacion(),
)
def crear_usuario(
    datos: UsuarioCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/usuarios/")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return usuario_service.crear_usuario(db, datos, identidad)


@router.get(
    "/roles",
    summary="Listar roles disponibles",
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/usuarios/roles"))
    ],
)
def listar_roles(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_roles(db)


@router.get(
    "/departamentos",
    summary="Listar departamentos",
    responses=dependencies.respuestas_de_autorizacion(),
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
)
def listar_instituciones(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/usuarios/instituciones")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return usuario_service.listar_instituciones(db, identidad)
