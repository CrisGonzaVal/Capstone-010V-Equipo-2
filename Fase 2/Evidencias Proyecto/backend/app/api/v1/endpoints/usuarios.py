from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.usuario_schema import UsuarioCrear, UsuarioRespuesta
from app.services import usuario_service

router = APIRouter(prefix="/usuarios", tags=["Administracion y Roles"])


@router.get("/", response_model=List[UsuarioRespuesta], summary="Listar usuarios")
def listar_usuarios(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_usuarios(db)


@router.post(
    "/",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
)
def crear_usuario(datos: UsuarioCrear, db: Session = Depends(dependencies.get_db)):
    return usuario_service.crear_usuario(db, datos)


@router.get("/roles", summary="Listar roles disponibles")
def listar_roles(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_roles(db)


@router.get("/departamentos", summary="Listar departamentos")
def listar_departamentos(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_departamentos(db)


@router.get("/instituciones", summary="Listar instituciones")
def listar_instituciones(db: Session = Depends(dependencies.get_db)):
    return usuario_service.listar_instituciones(db)
