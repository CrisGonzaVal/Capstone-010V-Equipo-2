from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Departamento, Institucion, Rol, Usuario
from app.schemas.usuario_schema import UsuarioCrear


def listar_usuarios(db: Session) -> List[Usuario]:
    return db.query(Usuario).all()


def crear_usuario(db: Session, datos: UsuarioCrear) -> Usuario:
    existente = db.query(Usuario).filter(Usuario.correo == datos.correo).first()
    if existente:
        raise HTTPException(status_code=400, detail="El correo ya esta registrado")

    nuevo_usuario = Usuario(**datos.model_dump())
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario


def listar_roles(db: Session) -> List[Rol]:
    return db.query(Rol).all()


def listar_departamentos(db: Session) -> List[Departamento]:
    return db.query(Departamento).all()


def listar_instituciones(db: Session) -> List[Institucion]:
    return db.query(Institucion).all()
