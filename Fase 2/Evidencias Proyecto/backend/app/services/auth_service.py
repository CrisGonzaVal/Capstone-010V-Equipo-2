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
from app.models.institucion import Institucion
from app.models.usuario import Usuario
from app.schemas.auth_schema import (
    IdentidadAutenticadaRespuesta,
    InstitucionEfectivaRespuesta,
)


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


def _usuario_con_rol(db: Session, correo: str) -> Usuario | None:
    """Usuario por correo con su `rol` cargado eager y desligado de la sesion.

    Feature 010 (T11): la identidad de negocio vive en el esquema de su
    institucion (no en control), de modo que la sesion temporal que la lee se
    cierra de inmediato. Cargar `rol` con `joinedload` y expulsar el objeto deja
    la identidad utilizable fuera de esa sesion (la autorizacion lee
    `usuario.rol.nombre_rol`).
    """
    usuario = db.execute(
        select(Usuario)
        .options(joinedload(Usuario.rol))
        .where(Usuario.correo == correo)
    ).scalar_one_or_none()
    if usuario is not None:
        db.expunge(usuario)
    return usuario


def resolver_usuario_local(db: Session, correo: str) -> Usuario | None:
    """Resuelve el usuario local del correo: identidad global o usuario de tenant.

    La identidad Superadmin vive en control; las identidades de negocio viven en
    el esquema de su institucion (spec D-2). Se busca primero en control y, si no
    aparece, se traduce el correo a su esquema con el mapa de control
    (`tenant_service`) y se busca alli. Un correo sin fila activa en el mapa no
    concede identidad (la capa HTTP responde 401). En SQLite (contexto logico
    unico, AC-16) la busqueda directa ya resuelve ambos casos.
    """
    usuario = vincular_usuario_por_correo(db, correo)
    if usuario is not None:
        return usuario

    motor = db.get_bind()
    if motor.dialect.name != "postgresql":
        return None

    # Import local: `tenant_service` y `database` no dependen de este modulo,
    # pero se evita cualquier ciclo de importacion a nivel de modulo.
    from app.db.database import ESQUEMA_CONTROL, crear_sesion_esquema
    from app.services import tenant_service

    nombre_esquema = tenant_service.esquema_para_correo(db, correo)
    if nombre_esquema is None or nombre_esquema == ESQUEMA_CONTROL:
        return None
    sesion = crear_sesion_esquema(nombre_esquema, motor=motor)
    try:
        return _usuario_con_rol(sesion, correo)
    finally:
        sesion.close()


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
    usuario = resolver_usuario_local(db, correo)
    if usuario is None:
        raise ErrorAutenticacion("sin coincidencia local para el correo verificado")
    return IdentidadAutenticada(usuario=usuario, sub=sub)


def construir_identidad_autenticada(
    db: Session,
    identidad: IdentidadAutenticada,
) -> IdentidadAutenticadaRespuesta:
    """Proyecta la identidad local completa para `GET /auth/me` (AC-8, AC-9, AC-17).

    Lee el usuario vinculado y su `rol` con SQLAlchemy ORM (relación cargada con
    `joinedload`, sin SQL raw ni consultas N+1) y arma el DTO con `rol` como el
    nombre legible `rol.nombre_rol`; nunca expone `rol_id`.

    Feature 008 (AC-17): agrega `institucion`, la institución efectiva derivada
    en el servidor (`usuario -> departamento -> institucion`) mediante los helpers
    de `app.services.ambito_service`. Para Superadmin es `None` explícito
    (alcance global); para un rol limitado, si el ámbito no se resuelve, responde
    **403** en vez de degradar a global (008 D-4/§8). El campo es informativo: no
    autoriza ni acepta entrada del cliente.

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
    identidad_resuelta = IdentidadAutenticada(usuario=usuario, sub=identidad.sub)
    return IdentidadAutenticadaRespuesta(
        usuario_id=usuario.usuario_id,
        sub=identidad.sub,
        nombre=usuario.nombre,
        apellido=usuario.apellido,
        correo=usuario.correo,
        rol=usuario.rol.nombre_rol,
        institucion=_institucion_efectiva(db, identidad_resuelta),
    )


def _institucion_efectiva(
    db: Session, identidad: IdentidadAutenticada
) -> InstitucionEfectivaRespuesta | None:
    """Institucion informativa del usuario: `None` para Superadmin (AC-17).

    Delega la resolucion y la denegacion en `ambito_service` para no duplicar la
    regla de ambito: alcance global -> `None`; rol limitado -> la institucion
    derivada, o **403** si no se resuelve. La identidad se reconstruye desde el
    usuario releido para que el rol global sea el persistido, no el del token.
    """
    # Import local: `ambito_service` importa `IdentidadAutenticada` de este
    # modulo, de modo que un import a nivel de modulo seria circular.
    from app.services import ambito_service

    if ambito_service.es_alcance_global(identidad):
        return None
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    institucion = db.get(Institucion, institucion_id)
    if institucion is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se pudo resolver la institucion del usuario",
        )
    return InstitucionEfectivaRespuesta(
        institucion_id=institucion.institucion_id,
        nombre=institucion.nombre,
    )

