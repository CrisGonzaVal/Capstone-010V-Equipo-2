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
from app.models import (
    Departamento,
    DepartamentoEncargado,
    MapaUsuarioEsquema,
    Rol,
    Sede,
    Usuario,
)
from app.schemas.organizacion_schema import (
    DepartamentoCrear,
    DepartamentoEdicion,
    SedeCrear,
    SedeEdicion,
)
from app.schemas.usuario_schema import UsuarioEdicion
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


# ---------------------------------------------------------------------------
# CRUD organizacional de sedes (Feature 012, T7, AC-6/AC-11/AC-13)
# ---------------------------------------------------------------------------


def _institucion_requerida(db: Session, identidad: IdentidadAutenticada | None) -> str:
    """Institucion del actor para crear recursos organizacionales.

    El alcance global (Superadmin) no crea recursos de tenant: la matriz ya
    reserva estas operaciones al Administrador institucional, pero se deniega de
    forma defensiva para no crear filas sin institucion.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    if institucion_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La operacion requiere una institucion concreta",
        )
    return institucion_id


def crear_sede(
    db: Session,
    datos: SedeCrear,
    identidad: IdentidadAutenticada | None = None,
) -> Sede:
    """Crea una sede en la institucion del Administrador (AC-6/AC-13).

    El nombre es unico dentro de la institucion: una sede homonima responde
    **409** sin crear fila, de modo que "Sede Central" no se duplica al abrir la
    UI (AC-6). La institucion la resuelve el servidor desde la sesion.
    """
    institucion_id = _institucion_requerida(db, identidad)
    existente = (
        db.query(Sede)
        .filter(Sede.institucion_id == institucion_id, Sede.nombre == datos.nombre)
        .first()
    )
    if existente is not None:
        raise _conflicto("Ya existe una sede con ese nombre en la institucion")
    sede = Sede(
        nombre=datos.nombre, direccion=datos.direccion, institucion_id=institucion_id
    )
    db.add(sede)
    db.commit()
    db.refresh(sede)
    return sede


def editar_sede(
    db: Session,
    sede_id: int,
    datos: SedeEdicion,
    identidad: IdentidadAutenticada | None = None,
) -> Sede:
    """Modifica el nombre y la direccion de una sede del tenant (AC-6).

    Una sede inexistente o **ajena** responde **404** sin mutacion (patron de
    ocultacion de la 011).
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    sede = _sede_en_alcance(db, sede_id, institucion_id)
    sede.nombre = datos.nombre
    sede.direccion = datos.direccion
    db.commit()
    db.refresh(sede)
    return sede


def cambiar_estado_sede(
    db: Session,
    sede_id: int,
    activo: bool,
    identidad: IdentidadAutenticada | None = None,
) -> Sede:
    """Activa o desactiva logicamente una sede (idempotente, AC-11).

    Sin borrado fisico ni perdida de historial. Reactivar es la misma operacion
    con `activo=True`. Una desactivacion es **idempotente** si la sede ya esta en
    ese estado; si la desactivacion dejaria dependencias activas incompatibles
    (departamentos activos o Bodegueros asignados a la sede) responde **409** con
    el motivo concreto y no cambia el estado.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    sede = _sede_en_alcance(db, sede_id, institucion_id)
    if sede.activo == activo:
        return sede
    if not activo:
        motivo = _dependencias_sede(db, sede_id)
        if motivo is not None:
            raise _conflicto(motivo)
    sede.activo = activo
    db.commit()
    db.refresh(sede)
    return sede


def _dependencias_sede(db: Session, sede_id: int) -> str | None:
    """Motivo por el que desactivar la sede es insegura, o `None` si es seguro."""
    departamento = (
        db.query(Departamento)
        .filter(Departamento.sede_id == sede_id, Departamento.activo.is_(True))
        .first()
    )
    if departamento is not None:
        return (
            "No se puede desactivar la sede: hay departamentos activos asignados a "
            "ella; reasigne su sede antes"
        )
    bodeguero = (
        db.query(Usuario)
        .join(Rol, Rol.rol_id == Usuario.rol_id)
        .filter(Usuario.sede_id == sede_id, Rol.nombre_rol == _BODEGUERO)
        .first()
    )
    if bodeguero is not None:
        return (
            "No se puede desactivar la sede: hay Bodegueros asignados a ella; "
            "reasigne su sede antes"
        )
    return None


# ---------------------------------------------------------------------------
# CRUD organizacional de departamentos (Feature 012, T7, AC-7/AC-11/AC-13)
# ---------------------------------------------------------------------------


def listar_departamentos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Departamento]:
    """Departamentos de la institucion del actor, con su sede y estado (AC-7)."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Departamento)
    if institucion_id is not None:
        consulta = consulta.filter(Departamento.institucion_id == institucion_id)
    return consulta.order_by(Departamento.departamento_id).all()


def crear_departamento(
    db: Session,
    datos: DepartamentoCrear,
    identidad: IdentidadAutenticada | None = None,
) -> Departamento:
    """Crea un departamento en la institucion del Administrador (AC-7/AC-13).

    La sede **no** es obligatoria en el alta (la precondicion de sede es
    operativa, regla 011); se asigna despues con `PUT .../sede`.
    """
    institucion_id = _institucion_requerida(db, identidad)
    departamento = Departamento(
        nombre_dep=datos.nombre_dep,
        descripcion=datos.descripcion,
        institucion_id=institucion_id,
    )
    db.add(departamento)
    db.commit()
    db.refresh(departamento)
    return departamento


def editar_departamento(
    db: Session,
    departamento_id: int,
    datos: DepartamentoEdicion,
    identidad: IdentidadAutenticada | None = None,
) -> Departamento:
    """Modifica nombre y descripcion de un departamento del tenant (AC-7)."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    departamento = _departamento_en_alcance(db, departamento_id, institucion_id)
    departamento.nombre_dep = datos.nombre_dep
    departamento.descripcion = datos.descripcion
    db.commit()
    db.refresh(departamento)
    return departamento


def cambiar_estado_departamento(
    db: Session,
    departamento_id: int,
    activo: bool,
    identidad: IdentidadAutenticada | None = None,
) -> Departamento:
    """Activa o desactiva logicamente un departamento (idempotente, AC-11).

    Sin borrado fisico. Idempotente si el departamento ya esta en ese estado; si
    la desactivacion dejaria usuarios activos vinculados (operaciones dependientes
    inconsistentes) responde **409** con el motivo concreto sin cambiar el estado.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    departamento = _departamento_en_alcance(db, departamento_id, institucion_id)
    if departamento.activo == activo:
        return departamento
    if not activo:
        motivo = _dependencias_departamento(db, departamento_id)
        if motivo is not None:
            raise _conflicto(motivo)
    departamento.activo = activo
    db.commit()
    db.refresh(departamento)
    return departamento


def _dependencias_departamento(db: Session, departamento_id: int) -> str | None:
    """Motivo por el que desactivar el departamento es inseguro, o `None`."""
    usuario = (
        db.query(Usuario).filter(Usuario.departamento_id == departamento_id).first()
    )
    if usuario is not None:
        return (
            "No se puede desactivar el departamento: tiene usuarios vinculados; "
            "reasigne o desactive esos usuarios antes"
        )
    return None


# ---------------------------------------------------------------------------
# Edicion y estado logico de usuarios locales (Feature 012, T7, AC-8/AC-11/AC-13)
# ---------------------------------------------------------------------------


def editar_usuario(
    db: Session,
    usuario_id: int,
    datos: UsuarioEdicion,
    identidad: IdentidadAutenticada | None = None,
) -> Usuario:
    """Modifica los atributos locales de un usuario del tenant (AC-8).

    No cambia el correo (clave de identidad local) ni toca Clerk. Respeta el rol
    asignable del creador (D-6/AC-10: el Administrador solo asignable
    Bodeguero/Solicitante -> **403**), el ambito institucional (**404** para un
    usuario o departamento ajeno) y el contrato (**422** en payload invalido).
    """
    # Import local: `usuario_service` no importa este modulo, pero se evita el
    # acoplamiento de cabecera entre servicios de administracion.
    from app.services.usuario_service import _validar_rol_asignable

    _validar_rol_asignable(db, datos.rol_id, identidad)
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    usuario = _usuario_en_alcance(db, usuario_id, institucion_id)
    _departamento_en_alcance(db, datos.departamento_id, institucion_id)
    usuario.nombre = datos.nombre
    usuario.apellido = datos.apellido
    usuario.departamento_id = datos.departamento_id
    usuario.rol_id = datos.rol_id
    db.commit()
    db.refresh(usuario)
    return usuario


def cambiar_estado_usuario(
    db: Session,
    db_control: Session,
    usuario_id: int,
    activo: bool,
    identidad: IdentidadAutenticada | None = None,
) -> MapaUsuarioEsquema:
    """Activa o desactiva la vinculacion local de un usuario (idempotente, D-3/AC-8/AC-11).

    El estado del usuario local vive en `mapa_usuario_esquema.activo` (D-3), no en
    una columna nueva: desactivar impide que el correo resuelva al tenant sin
    borrar la identidad de Clerk. `db` es la sesion del tenant (resuelve el usuario
    y su ambito institucional); `db_control` es la sesion de control donde vive el
    mapa. Una desactivacion es idempotente si ya esta inactivo; si el usuario es
    encargado de algun departamento (dependencia activa), responde **409** con el
    motivo concreto. Un usuario inexistente o ajeno responde **404**.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    usuario = _usuario_en_alcance(db, usuario_id, institucion_id)

    mapa = db_control.get(MapaUsuarioEsquema, usuario.correo)
    if mapa is not None and mapa.activo == activo:
        # Idempotente: ya esta en el estado pedido.
        return mapa
    if not activo:
        motivo = _dependencias_usuario(db, usuario_id)
        if motivo is not None:
            raise _conflicto(motivo)
    if mapa is None:
        institucion_usuario = ambito_service.institucion_de_usuario(db, usuario)
        if institucion_usuario is None:
            raise _conflicto(
                "No se puede cambiar el estado: el usuario no resuelve a una "
                "institucion"
            )
        # Import local: `tenant_service` importa `control_service`; se evita el
        # ciclo en cabecera.
        from app.services.tenant_service import nombre_esquema_para_institucion

        mapa = MapaUsuarioEsquema(
            correo=usuario.correo,
            institucion_id=institucion_usuario,
            nombre_esquema=nombre_esquema_para_institucion(institucion_usuario),
            activo=activo,
        )
        db_control.add(mapa)
    else:
        mapa.activo = activo
    db_control.commit()
    return mapa


def _dependencias_usuario(db: Session, usuario_id: int) -> str | None:
    """Motivo por el que desactivar el usuario es inseguro, o `None`."""
    asociacion = (
        db.query(DepartamentoEncargado)
        .filter(DepartamentoEncargado.usuario_id == usuario_id)
        .first()
    )
    if asociacion is not None:
        return (
            "No se puede desactivar el usuario: es encargado de uno o mas "
            "departamentos; retire sus asociaciones antes"
        )
    return None
