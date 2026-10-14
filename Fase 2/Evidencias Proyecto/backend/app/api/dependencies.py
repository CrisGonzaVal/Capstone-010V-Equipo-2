"""Dependencias de la capa HTTP (Feature 006).

`get_db` inyecta la `Session`. Las costuras `obtener_fuente_jwks` y
`obtener_transporte_clerk` aíslan la red (JWKS y Backend API de Clerk) para
poder overridearlas en los tests. `get_current_user` resuelve la identidad
vinculada delegando en `auth_service` y normaliza todo fallo a HTTP 401.
"""

from collections.abc import Generator

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.security import FuenteJWKS
from app.db.database import SessionLocal
from app.services import auth_service
from app.services.auth_service import IdentidadAutenticada

#: Esquema HTTP Bearer sin error automatico: publica el securityScheme en
#: OpenAPI pero permite un 401 explicito en vez del 403 por defecto cuando
#: faltan credenciales.
esquema_bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def obtener_fuente_jwks() -> FuenteJWKS:
    """Costura inyectable: fuente del documento JWKS (`fuente(issuer) -> dict`)."""
    return security.descargar_jwks


def obtener_transporte_clerk() -> httpx.BaseTransport:
    """Costura inyectable: transporte HTTP hacia el Backend API de Clerk."""
    return httpx.HTTPTransport()


def _no_autorizado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credenciales: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    fuente_jwks: FuenteJWKS = Depends(obtener_fuente_jwks),
    transporte: httpx.BaseTransport = Depends(obtener_transporte_clerk),
    db: Session = Depends(get_db),
) -> IdentidadAutenticada:
    """Devuelve la identidad vinculada (usuario local + `sub` validado de Clerk).

    Ausencia o invalidez de credenciales, fallo de JWKS, de Clerk, correo no
    verificado o falta de coincidencia local se responden como 401 sin filtrar
    la causa interna.
    """
    if credenciales is None:
        raise _no_autorizado()
    try:
        return auth_service.resolver_identidad(
            token=credenciales.credentials,
            issuer=settings.CLERK_ISSUER,
            fuente_jwks=fuente_jwks,
            secret_key=settings.CLERK_SECRET_KEY,
            transport=transporte,
            db=db,
        )
    except security.ErrorAutenticacion as exc:
        raise _no_autorizado() from exc
