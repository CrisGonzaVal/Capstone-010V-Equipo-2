"""Servicio de asignaciones organizacionales (Feature 011, T7).

Superficie minima para que el modelo organizacional sea operable sin CRUD de
sedes (eso es la Feature 012): consulta de sedes del tenant, asignacion de sede a
departamento y a un Bodeguero, y asociacion/retiro/listado de encargados de
departamento (tabla puente `departamento_encargado`, spec D-4).

Reglas de dominio (AGENTS §6: la logica vive aqui, no en el router):

  * La institucion del actor se resuelve con `ambito_service.alcance_institucional`
    a partir de la identidad ya autenticada; nunca de la peticion. Un recurso
    inexistente **o ajeno** se oculta con **404** (patron Feature 008, spec §4.12);
    un recurso de otra institucion no se toca.
  * Una precondicion organizacional o una asociacion incompatible/duplicada
    responde **409** sin mutacion: asignar sede a un usuario que no es Bodeguero,
    encargado con rol distinto de Solicitante, encargado de otro departamento o
    asociacion repetida.
  * El listado de encargados solo devuelve asociaciones **vigentes y compatibles**
    (usuario existente, rol Solicitante y pertenencia al departamento); una
    asociacion obsoleta no se borra pero tampoco se muestra ni concede nada.
"""

from __future__ import annotations

from typing import List

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import permisos
from app.models import Departamento, DepartamentoEncargado, Rol, Sede, Usuario
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

_BODEGUERO = permisos.RolConocido.BODEGUERO.value
_SOLICITANTE = permisos.RolConocido.SOLICITANTE.value

_DETALLE_DEPARTAMENTO = "Departamento inexistente o fuera del ambito del usuario"
_DETALLE_USUARIO = "Usuario inexistente o fuera del ambito del usuario"
_DETALLE_SEDE = "Sede inexistente o fuera del ambito del usuario"


# ---------------------------------------------------------------------------
# Helpers de resolucion y pertenencia (404 indistinguible, spec §4.12)
# ---------------------------------------------------------------------------


def _departamento_en_alcance(
    db: Session, departamento_id: int, institucion_id: str | None
) -> Departamento:
    """Departamento visible para el ambito, o 404 si no existe o es ajeno."""
    departamento = db.get(Departamento, departamento_id)
    if departamento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_DETALLE_DEPARTAMENTO
        )
    ambito_service.exigir_pertenencia(
        departamento.institucion_id, institucion_id, detalle=_DETALLE_DEPARTAMENTO
    )
    return departamento


def _sede_en_alcance(
    db: Session, sede_id: int, institucion_id: str | None
) -> Sede:
    """Sede visible para el ambito, o 404 si no existe o es ajena (AC-3)."""
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_DETALLE_SEDE
        )
    ambito_service.exigir_pertenencia(
        sede.institucion_id, institucion_id, detalle=_DETALLE_SEDE
    )
    return sede


def _usuario_en_alcance(
    db: Session, usuario_id: int, institucion_id: str | None
) -> Usuario:
    """Usuario visible para el ambito, o 404 si no existe o es ajeno."""
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_DETALLE_USUARIO
        )
    institucion_usuario = ambito_service.institucion_de_usuario(db, usuario)
    ambito_service.exigir_pertenencia(
        institucion_usuario, institucion_id, detalle=_DETALLE_USUARIO
    )
    return usuario


def _nombre_rol(db: Session, usuario: Usuario) -> str | None:
    """Nombre del rol del usuario, o `None` si su rol no es resoluble."""
    rol = db.get(Rol, usuario.rol_id)
    return None if rol is None else rol.nombre_rol


def _conflicto(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)


# ---------------------------------------------------------------------------
# Sedes
# ---------------------------------------------------------------------------


def listar_sedes(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Sede]:
    """Sedes de la institucion del actor, sin nombrar ninguna de otro tenant."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Sede)
    if institucion_id is not None:
        consulta = consulta.filter(Sede.institucion_id == institucion_id)
    return consulta.order_by(Sede.sede_id).all()


def asignar_sede_a_departamento(
    db: Session,
    departamento_id: int,
    sede_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> Departamento:
    """Fija la sede de un departamento del tenant (spec D-5, AC-5/AC-6)."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    departamento = _departamento_en_alcance(db, departamento_id, institucion_id)
    _sede_en_alcance(db, sede_id, institucion_id)
    departamento.sede_id = sede_id
    db.commit()
    db.refresh(departamento)
    return departamento


def asignar_sede_a_usuario(
    db: Session,
    usuario_id: int,
    sede_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> Usuario:
    """Fija la sede de un Bodeguero del tenant (spec D-5/D-7, AC-5/AC-7).

    Un usuario que no es Bodeguero es una precondicion organizacional invalida y
    responde **409** sin mutar nada: la sede solo tiene sentido para quien opera
    existencias.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    usuario = _usuario_en_alcance(db, usuario_id, institucion_id)
    _sede_en_alcance(db, sede_id, institucion_id)
    if _nombre_rol(db, usuario) != _BODEGUERO:
        raise _conflicto(
            "Solo un usuario Bodeguero puede tener una sede asignada"
        )
    usuario.sede_id = sede_id
    db.commit()
    db.refresh(usuario)
    return usuario


# ---------------------------------------------------------------------------
# Encargados de departamento (N:N, spec D-4)
# ---------------------------------------------------------------------------


def _consulta_encargados(db: Session, departamento_id: int):
    """Asociaciones compatibles vigentes: usuario Solicitante del departamento."""
    return (
        db.query(Usuario)
        .join(DepartamentoEncargado, DepartamentoEncargado.usuario_id == Usuario.usuario_id)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .filter(
            DepartamentoEncargado.departamento_id == departamento_id,
            Usuario.departamento_id == departamento_id,
            Rol.nombre_rol == _SOLICITANTE,
        )
        .order_by(Usuario.usuario_id)
    )


def listar_encargados(
    db: Session,
    departamento_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> List[Usuario]:
    """Encargados vigentes y compatibles de un departamento del tenant."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    _departamento_en_alcance(db, departamento_id, institucion_id)
    return _consulta_encargados(db, departamento_id).all()


def asociar_encargado(
    db: Session,
    departamento_id: int,
    usuario_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> Usuario:
    """Asocia un Solicitante del mismo departamento como encargado (AC-4).

    El usuario debe existir en el tenant (404 si no o si es ajeno) y ser
    compatible (409 si su rol no es Solicitante, si pertenece a otro departamento
    o si la asociacion ya existe). No concede ningun privilegio adicional.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    _departamento_en_alcance(db, departamento_id, institucion_id)
    usuario = _usuario_en_alcance(db, usuario_id, institucion_id)
    if _nombre_rol(db, usuario) != _SOLICITANTE:
        raise _conflicto(
            "El encargado de departamento debe ser un usuario Solicitante"
        )
    if usuario.departamento_id != departamento_id:
        raise _conflicto(
            "El encargado debe pertenecer al mismo departamento que asocia"
        )
    existente = (
        db.query(DepartamentoEncargado)
        .filter(
            DepartamentoEncargado.departamento_id == departamento_id,
            DepartamentoEncargado.usuario_id == usuario_id,
        )
        .first()
    )
    if existente is not None:
        raise _conflicto("El usuario ya es encargado de este departamento")
    asociacion = DepartamentoEncargado(
        departamento_id=departamento_id, usuario_id=usuario_id
    )
    db.add(asociacion)
    try:
        db.commit()
    except IntegrityError as exc:  # carrera contra la unicidad de la tabla puente
        db.rollback()
        raise _conflicto("El usuario ya es encargado de este departamento") from exc
    db.refresh(usuario)
    return usuario


def retirar_encargado(
    db: Session,
    departamento_id: int,
    usuario_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> None:
    """Retira la asociacion departamento/encargado (AC-5).

    Afecta solo a la pareja indicada; otras asociaciones del usuario con otros
    departamentos no se tocan. Una asociacion inexistente responde **404**.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    _departamento_en_alcance(db, departamento_id, institucion_id)
    asociacion = (
        db.query(DepartamentoEncargado)
        .filter(
            DepartamentoEncargado.departamento_id == departamento_id,
            DepartamentoEncargado.usuario_id == usuario_id,
        )
        .first()
    )
    if asociacion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asociacion de encargado inexistente",
        )
    db.delete(asociacion)
    db.commit()
