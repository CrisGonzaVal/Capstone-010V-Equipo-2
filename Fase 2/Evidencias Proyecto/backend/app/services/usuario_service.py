"""Servicio de administracion de usuarios y catalogos de apoyo (Feature 001/007).

Feature 007 (D-4/AC-8): el Administrador queda limitado a su institucion en el
listado de usuarios/departamentos y en la consulta de instituciones (solo la
propia); Superadmin es global. La institucion se deriva de
`usuario.departamento_id -> departamento.institucion_id` con `ambito_service`, y
una institucion no resoluble para un rol limitado responde 403.

Feature 007 (D-6/AC-10): al crear un usuario, el Administrador solo puede
asignar los roles `Bodeguero` o `Solicitante`; intentar `Superadmin` o
`Administrador` responde 403 sin crear fila. Superadmin conserva libertad total
de rol. El alta del Administrador tambien queda acotada a su institucion (el
departamento destino debe pertenecer a ella). La regla vive en este servicio
(`AGENTS.md` §6), no en el router.
"""

from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import permisos
from app.models import Departamento, Institucion, Rol, Usuario
from app.schemas.usuario_schema import UsuarioCrear
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

_SUPERADMIN = permisos.RolConocido.SUPERADMIN.value
_ADMINISTRADOR = permisos.RolConocido.ADMINISTRADOR.value

#: Roles que un Administrador puede asignar en el alta (D-6, AC-10).
_ROLES_ASIGNABLES_ADMINISTRADOR: frozenset[str] = frozenset(
    {
        permisos.RolConocido.BODEGUERO.value,
        permisos.RolConocido.SOLICITANTE.value,
    }
)


def listar_usuarios(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Usuario]:
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Usuario)
    if institucion_id is not None:
        consulta = consulta.join(
            Departamento, Usuario.departamento_id == Departamento.departamento_id
        ).filter(Departamento.institucion_id == institucion_id)
    return consulta.all()


def _validar_rol_asignable(
    db: Session, rol_id: int, identidad: IdentidadAutenticada | None
) -> None:
    """Restringe el rol asignable segun la autoridad del creador (D-6, AC-10).

    Superadmin puede asignar cualquiera de los cuatro roles. Administrador solo
    `Bodeguero` o `Solicitante`; cualquier otro (incluido un `rol_id` inexistente
    o un rol desconocido) responde 403. Cualquier otro rol creador no deberia
    alcanzar el alta (la matriz D-3 ya la reserva a los administrativos), pero se
    deniega de forma defensiva: no hay autoridad implicita.
    """
    rol_creador = permisos.nombre_rol_de(identidad)
    if rol_creador == _SUPERADMIN:
        return
    if rol_creador == _ADMINISTRADOR:
        rol = db.get(Rol, rol_id)
        nombre_asignado = rol.nombre_rol if rol is not None else None
        if nombre_asignado not in _ROLES_ASIGNABLES_ADMINISTRADOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El Administrador solo puede asignar roles Bodeguero o Solicitante",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permiso insuficiente para la operacion",
    )


def crear_usuario(
    db: Session,
    datos: UsuarioCrear,
    identidad: IdentidadAutenticada | None = None,
) -> Usuario:
    """Crea un usuario aplicando el rol asignable y el ambito del creador.

    La autorizacion por rol de la operacion ya la impone la dependencia HTTP;
    aqui se aplica la regla de dominio del rol asignable (D-6/AC-10) y el limite
    institucional del alta (D-4/AC-8): un departamento destino de otra institucion
    responde 403 sin crear fila. Ambas validaciones preceden a cualquier
    mutacion.
    """
    _validar_rol_asignable(db, datos.rol_id, identidad)
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    ambito_service.validar_departamento_en_alcance(
        db, datos.departamento_id, institucion_id
    )

    existente = db.query(Usuario).filter(Usuario.correo == datos.correo).first()
    if existente:
        raise HTTPException(status_code=400, detail="El correo ya esta registrado")

    nuevo_usuario = Usuario(**datos.model_dump())
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario


def listar_roles(db: Session) -> List[Rol]:
    # Los roles del catalogo son compartidos (D-3): no se filtran por institucion.
    return db.query(Rol).all()


def listar_departamentos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Departamento]:
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Departamento)
    if institucion_id is not None:
        consulta = consulta.filter(Departamento.institucion_id == institucion_id)
    return consulta.all()


def listar_instituciones(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Institucion]:
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Institucion)
    if institucion_id is not None:
        consulta = consulta.filter(Institucion.institucion_id == institucion_id)
    return consulta.all()
