"""Resolucion del ambito institucional por identidad (Feature 007, D-4/AC-8).

La institucion de Administrador, Bodeguero y Solicitante se deriva de
`usuario.departamento_id -> departamento.institucion_id`. Solo Superadmin tiene
alcance global; el catalogo maestro de categoria/producto permanece compartido en
007. Si la institucion no se resuelve para un rol limitado, la operacion se
deniega con 403: nunca se concede alcance global ni se omite el filtro (D-4,
AC-8). La regla vive en los servicios, no en los routers
(`AGENTS.md` §6).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import permisos
from app.models import Departamento
from app.services.auth_service import IdentidadAutenticada

_SUPERADMIN = permisos.RolConocido.SUPERADMIN.value


def es_alcance_global(identidad: IdentidadAutenticada | None) -> bool:
    """`True` solo para Superadmin: es el unico rol con alcance global."""
    return permisos.nombre_rol_de(identidad) == _SUPERADMIN


def institucion_de_identidad(
    db: Session, identidad: IdentidadAutenticada | None
) -> str | None:
    """Deriva la institucion via `usuario.departamento_id -> departamento`.

    Devuelve `None` cuando el usuario, su departamento o la institucion no son
    resolubles; no lanza, para poder distinguir "global" de "no resoluble" en el
    llamador.
    """
    if identidad is None:
        return None
    departamento_id = getattr(identidad.usuario, "departamento_id", None)
    if departamento_id is None:
        return None
    departamento = db.get(Departamento, departamento_id)
    if departamento is None:
        return None
    return departamento.institucion_id


def alcance_institucional(
    db: Session, identidad: IdentidadAutenticada | None
) -> str | None:
    """Institucion efectiva del usuario: `None` = alcance global (Superadmin).

    Para cualquier otro rol, si la institucion no se resuelve, responde **403**
    en vez de conceder alcance global (D-4, AC-8).
    """
    if es_alcance_global(identidad):
        return None
    institucion_id = institucion_de_identidad(db, identidad)
    if institucion_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se pudo resolver la institucion del usuario",
        )
    return institucion_id


def validar_departamento_en_alcance(
    db: Session, departamento_id: int, institucion_id: str | None
) -> None:
    """Rechaza con 403 un `departamento_id` explicito de otra institucion.

    Con alcance global (`institucion_id is None`) no hay restriccion. Un
    departamento inexistente no es "ajeno": no se denuncia su inexistencia, el
    filtro natural devuelve una lista vacia.
    """
    if institucion_id is None:
        return
    departamento = db.get(Departamento, departamento_id)
    if departamento is None:
        return
    if departamento.institucion_id != institucion_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El departamento indicado esta fuera de la institucion del usuario",
        )
