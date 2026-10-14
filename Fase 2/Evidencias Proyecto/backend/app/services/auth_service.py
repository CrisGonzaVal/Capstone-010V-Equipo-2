"""Servicio de autenticacion federada (Feature 006).

Clerk es la unica autoridad de autenticacion: este servicio no valida
contrasenas ni emite tokens. Orquesta la frontera externa (`core/security.py`)
y el vinculo con el usuario local por `usuario.correo` (SQLAlchemy ORM),
devolviendo una identidad reutilizable por las dependencias FastAPI.

No se persiste el `sub` ni se crean/modifican usuarios.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core import security
from app.core.security import ErrorAutenticacion, FuenteJWKS
from app.models.usuario import Usuario
from app.schemas.auth_schema import IdentidadAutenticadaRespuesta


@dataclass(frozen=True)
class IdentidadAutenticada:
    """Identidad resuelta: usuario local vinculado y `sub` validado de Clerk."""

    usuario: Usuario
    sub: str


def vincular_usuario_por_correo(db: Session, correo: str) -> Usuario | None:
    """Resuelve el usuario local por `correo` (UNIQUE) con SQLAlchemy ORM."""
    return db.execute(
        select(Usuario).where(Usuario.correo == correo)
    ).scalar_one_or_none()


def resolver_identidad(
    *,
    token: str,
    issuer: str,
    fuente_jwks: FuenteJWKS,
    secret_key: str,
    transport: httpx.BaseTransport,
    db: Session,
) -> IdentidadAutenticada:
    """Valida el token, obtiene el correo primario verificado y lo vincula.

    Cualquier fallo (token, red, Clerk o vinculo local) se levanta como
    `ErrorAutenticacion`, que la capa HTTP normaliza a 401.
    """
    claims = security.validar_token(token, issuer, fuente_jwks)
    sub = claims["sub"]
    correo = security.obtener_correo_primario_verificado(sub, secret_key, transport)
    usuario = vincular_usuario_por_correo(db, correo)
    if usuario is None:
        raise ErrorAutenticacion("sin coincidencia local para el correo verificado")
    return IdentidadAutenticada(usuario=usuario, sub=sub)


def construir_identidad_autenticada(
    db: Session,
    identidad: IdentidadAutenticada,
) -> IdentidadAutenticadaRespuesta:
    """Proyecta la identidad local completa para `GET /auth/me` (AC-8, AC-9).

    Lee el usuario vinculado y su `rol` con SQLAlchemy ORM (relación cargada con
    `joinedload`, sin SQL raw ni consultas N+1) y arma el DTO con `rol` como el
    nombre legible `rol.nombre_rol`; nunca expone `rol_id`.

    Si el usuario o su relación de rol no son resolubles, responde 401 sin datos
    parciales y sin crear ni modificar filas.
    """
    usuario = db.execute(
        select(Usuario)
        .options(joinedload(Usuario.rol))
        .where(Usuario.usuario_id == identidad.usuario.usuario_id)
    ).scalar_one_or_none()
    if usuario is None or usuario.rol is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return IdentidadAutenticadaRespuesta(
        usuario_id=usuario.usuario_id,
        sub=identidad.sub,
        nombre=usuario.nombre,
        apellido=usuario.apellido,
        correo=usuario.correo,
        rol=usuario.rol.nombre_rol,
    )

