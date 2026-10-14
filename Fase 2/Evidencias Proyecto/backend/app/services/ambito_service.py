"""Resolucion del ambito institucional por identidad (Features 007 y 008).

La institucion de Administrador, Bodeguero y Solicitante se deriva de
`usuario.departamento_id -> departamento.institucion_id`. Solo Superadmin tiene
alcance global. Si la institucion no se resuelve para un rol limitado, la
operacion se deniega con 403: nunca se concede alcance global ni se omite el
filtro (007 D-4, AC-8).

La Feature 008 (D-1..D-4) generaliza esta capa con helpers reutilizables que T6
y T7 consumen para filtrar consultas y validar pertenencia institucional de
categoria, producto, inventario, usuario y ticket:

  * `institucion_de_*` extraen la institucion de una entidad (departamento,
    usuario, inventario, ticket) o de su columna `institucion_id` (producto,
    categoria).
  * `pertenece_al_alcance` / `exigir_pertenencia` deciden si un recurso es
    visible para el ambito; un recurso ajeno se **oculta con 404**, igual que uno
    inexistente (D-4, AC-9/AC-16).
  * `filtrar_por_institucion` aplica el filtro institucional a una consulta
    (ORM/Core) cuando el ambito es limitado; con alcance global no filtra.
  * `validar_departamento_en_alcance` conserva el **403** de 007 para un
  `departamento_id` explicitamente ajeno.

La regla vive en los servicios, no en los routers (`AGENTS.md` §6).
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import permisos
from app.models import Departamento, Usuario
from app.services.auth_service import IdentidadAutenticada

_SUPERADMIN = permisos.RolConocido.SUPERADMIN.value


def es_alcance_global(identidad: IdentidadAutenticada | None) -> bool:
    """`True` solo para Superadmin: es el unico rol con alcance global."""
    return permisos.nombre_rol_de(identidad) == _SUPERADMIN


# ---------------------------------------------------------------------------
# Extraccion de la institucion de cada entidad
# ---------------------------------------------------------------------------


def institucion_de_departamento(db: Session, departamento_id: int | None) -> str | None:
    """Institucion de un departamento por su id, o `None` sin departamento."""
    if departamento_id is None:
        return None
    departamento = db.get(Departamento, departamento_id)
    return None if departamento is None else departamento.institucion_id


def institucion_de_usuario(db: Session, usuario: Usuario | None) -> str | None:
    """Institucion de un usuario via `departamento_id -> departamento`, o `None`."""
    if usuario is None:
        return None
    return institucion_de_departamento(db, usuario.departamento_id)


def institucion_de_inventario(db: Session, inventario) -> str | None:
    """Institucion de un inventario, heredada de su departamento (D-2)."""
    if inventario is None:
        return None
    return institucion_de_departamento(db, inventario.departamento_id)


def institucion_de_ticket(db: Session, ticket) -> str | None:
    """Institucion de un ticket, heredada del departamento de su solicitante."""
    if ticket is None:
        return None
    return institucion_de_usuario(db, db.get(Usuario, ticket.usuario_id))


def institucion_de_recurso(entidad) -> str | None:
    """Institucion declarada por una entidad con columna `institucion_id`.

    Es el caso de `categoria`, `producto` y `departamento`, que anclan su
    pertenencia en esa columna (D-1). Devuelve `None` si la entidad o su columna
    no existen.
    """
    if entidad is None:
        return None
    return getattr(entidad, "institucion_id", None)


def institucion_de_identidad(
    db: Session, identidad: IdentidadAutenticada | None
) -> str | None:
    """Deriva la institucion de la identidad via su departamento.

    Devuelve `None` cuando el usuario, su departamento o la institucion no son
    resolubles; no lanza, para poder distinguir "global" de "no resoluble" en el
    llamador.
    """
    if identidad is None:
        return None
    return institucion_de_usuario(db, identidad.usuario)


# ---------------------------------------------------------------------------
# Ambito resuelto y validaciones
# ---------------------------------------------------------------------------


def alcance_institucional(
    db: Session, identidad: IdentidadAutenticada | None
) -> str | None:
    """Institucion efectiva del usuario: `None` = alcance global (Superadmin).

    Para cualquier otro rol, si la institucion no se resuelve, responde **403**
    en vez de conceder alcance global (007 D-4, AC-8).
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


def pertenece_al_alcance(
    institucion_recurso: str | None, institucion_id: str | None
) -> bool:
    """`True` si el recurso cae dentro del ambito (`institucion_id`).

    El alcance global (`institucion_id is None`, Superadmin) acepta cualquier
    recurso; un ambito limitado solo acepta recursos de su misma institucion.
    """
    return institucion_id is None or institucion_recurso == institucion_id


def exigir_pertenencia(
    institucion_recurso: str | None,
    institucion_id: str | None,
    *,
    detalle: str,
) -> None:
    """Oculta con **404** un recurso ajeno cuando el ambito es limitado (D-4).

    El 404 es indistinguible del de un recurso inexistente, de modo que un id
    ajeno no revela su existencia. Con alcance global no restringe.
    """
    if not pertenece_al_alcance(institucion_recurso, institucion_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)


def filtrar_por_institucion(consulta, columna, institucion_id: str | None):
    """Acota `consulta` a la institucion cuando el ambito es limitado.

    Con alcance global (`institucion_id is None`) devuelve la consulta intacta,
    de modo que las lecturas globales de Superadmin no se recortan. `columna` es
    la columna institucional sobre la que filtrar (p. ej.
    `Producto.institucion_id` o `Departamento.institucion_id`).
    """
    if institucion_id is None:
        return consulta
    return consulta.where(columna == institucion_id)


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
