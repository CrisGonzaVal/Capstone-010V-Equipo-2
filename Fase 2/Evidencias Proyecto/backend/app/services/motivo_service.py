"""Registro auxiliar de motivos y constancias (Feature 017, D-5/D-6).

La tabla `control.registro_motivo_constancia` no es una entidad de dominio: es
evidencia recuperable de una mutacion administrativa o de un fallo de
coordinacion entre las dos confirmaciones locales (tenant y control). Este
servicio concentra las escrituras para que los demas servicios no dupliquen la
regla de idempotencia ni el catalogo de tipos (AGENTS.md §6).

Tipos:

* `justificacion`: motivo completo de una edicion/baja/reactivacion efectiva.
* `constancia_motivo`: el cambio de negocio se aplico pero el motivo no pudo
  persistirse; el reintento con la misma clave lo completa.
* `constancia_compensacion`: una invitacion creada no pudo compensarse; se
  conserva `invitacion_id` (nunca la URL) para reconciliarla manualmente.

Ningun metodo persiste ni devuelve la URL de invitacion.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.control import RegistroMotivoConstancia

#: Tipos de fila (coinciden con el CHECK del modelo).
JUSTIFICACION = "justificacion"
CONSTANCIA_MOTIVO = "constancia_motivo"
CONSTANCIA_COMPENSACION = "constancia_compensacion"

#: Accion de compensacion de una invitacion huerfana (D-2).
ACCION_COMPENSACION_INVITACION = "compensacion_invitacion_fallida"

#: Accion de la evidencia de un alta de usuario cuyo mapa no pudo confirmarse
#: (D-2): el reintento la completa junto con el mapa sin inventar una clave.
ACCION_ALTA_INVITACION = "alta_usuario_invitacion"

#: Longitud maxima de `clave_idempotente` (columna String(100)).
_LONGITUD_CLAVE = 100


def clave_para_invitacion(prefijo: str, invitacion_id: str) -> str:
    """Clave idempotente estable y acotada para una invitacion externa."""
    return f"{prefijo}:{invitacion_id}"[:_LONGITUD_CLAVE]


def clave_para_alta(usuario_id: int) -> str:
    """Clave idempotente persistida que identifica el alta parcial de un usuario.

    Es la unica clave que el reintento puede reutilizar (D-2): se deriva del
    usuario local ya confirmado, de modo que dos reintentos del mismo alta no
    generan evidencia duplicada ni fabrican una clave nueva.
    """
    return f"alta-usuario:{usuario_id}"[:_LONGITUD_CLAVE]


def _buscar(db: Session, clave: str) -> RegistroMotivoConstancia | None:
    return db.execute(
        select(RegistroMotivoConstancia).where(
            RegistroMotivoConstancia.clave_idempotente == clave
        )
    ).scalar_one_or_none()


def registrar_justificacion(
    db: Session,
    *,
    actor_correo: str,
    accion: str,
    institucion_id: str,
    clave_idempotente: str,
    codigo_motivo: str,
    texto_motivo: str | None = None,
    usuario_objetivo_id: int | None = None,
    correo_objetivo: str | None = None,
) -> RegistroMotivoConstancia:
    """Persiste (o completa) la justificacion de una mutacion efectiva (D-5).

    La clave idempotente es la unidad de repeticion: si ya existe una
    justificacion con la misma clave no se duplica; si existe una constancia de
    motivo pendiente (el cambio se aplico pero el motivo fallo), se completa
    convirtiendola en justificacion. Un reintento nunca repite el cambio de
    negocio, solo la evidencia.
    """
    existente = _buscar(db, clave_idempotente)
    if existente is not None:
        if existente.tipo_registro == CONSTANCIA_MOTIVO:
            existente.tipo_registro = JUSTIFICACION
            existente.actor_correo = actor_correo
            existente.accion = accion
            existente.institucion_id = institucion_id
            existente.usuario_objetivo_id = usuario_objetivo_id
            existente.correo_objetivo = correo_objetivo
            existente.codigo_motivo = codigo_motivo
            existente.texto_motivo = texto_motivo
            existente.fecha_registro = datetime.utcnow()
            db.commit()
            db.refresh(existente)
        return existente

    fila = RegistroMotivoConstancia(
        tipo_registro=JUSTIFICACION,
        actor_correo=actor_correo,
        usuario_objetivo_id=usuario_objetivo_id,
        correo_objetivo=correo_objetivo,
        institucion_id=institucion_id,
        accion=accion,
        codigo_motivo=codigo_motivo,
        texto_motivo=texto_motivo,
        fecha_registro=datetime.utcnow(),
        clave_idempotente=clave_idempotente,
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        # Carrera sobre la clave unica: la otra peticion ya dejo la evidencia.
        db.rollback()
        return _buscar(db, clave_idempotente)  # type: ignore[return-value]
    db.refresh(fila)
    return fila


def completar_motivo_pendiente(
    db: Session,
    *,
    clave_idempotente: str,
    actor_correo: str,
    accion: str,
    institucion_id: str,
    codigo_motivo: str,
    texto_motivo: str | None = None,
    usuario_objetivo_id: int | None = None,
    correo_objetivo: str | None = None,
) -> bool:
    """Completa una `constancia_motivo` existente sin crear evidencia nueva.

    Se usa en el reintento idempotente de una mutacion que ya se aplico y cuyo
    motivo fallo: si no existe constancia pendiente devuelve `False` y no
    escribe nada (una mutacion sin cambio no genera motivo).
    """
    existente = _buscar(db, clave_idempotente)
    if existente is None or existente.tipo_registro != CONSTANCIA_MOTIVO:
        return False
    return (
        registrar_justificacion(
            db,
            actor_correo=actor_correo,
            accion=accion,
            institucion_id=institucion_id,
            clave_idempotente=clave_idempotente,
            codigo_motivo=codigo_motivo,
            texto_motivo=texto_motivo,
            usuario_objetivo_id=usuario_objetivo_id,
            correo_objetivo=correo_objetivo,
        )
        is not None
    )


def registrar_constancia_motivo(
    db: Session,
    *,
    actor_correo: str,
    accion: str,
    institucion_id: str,
    clave_idempotente: str,
    usuario_objetivo_id: int | None = None,
    correo_objetivo: str | None = None,
) -> RegistroMotivoConstancia:
    """Deja constancia de que el cambio se aplico pero el motivo fallo (D-5).

    Se ejecuta en una transaccion propia despues del fallo de la segunda
    confirmacion. No contiene motivo completo: el reintento con la misma clave lo
    completara. Si ya existe evidencia con la clave no se duplica.
    """
    existente = _buscar(db, clave_idempotente)
    if existente is not None:
        return existente
    fila = RegistroMotivoConstancia(
        tipo_registro=CONSTANCIA_MOTIVO,
        actor_correo=actor_correo,
        usuario_objetivo_id=usuario_objetivo_id,
        correo_objetivo=correo_objetivo,
        institucion_id=institucion_id,
        accion=accion,
        fecha_registro=datetime.utcnow(),
        clave_idempotente=clave_idempotente,
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _buscar(db, clave_idempotente)  # type: ignore[return-value]
    db.refresh(fila)
    return fila


def registrar_compensacion_invitacion(
    db: Session,
    *,
    actor_correo: str,
    institucion_id: str,
    correo_objetivo: str,
    invitacion_id: str,
    resultado_revocacion: str,
) -> RegistroMotivoConstancia:
    """Constancia de una invitacion huerfana que no pudo revocarse (D-2/AC-3).

    Guarda `invitacion_id` para que el Superadmin la localice manualmente en
    Clerk; la URL jamas se persiste.
    """
    clave = clave_para_invitacion("compensacion-invitacion", invitacion_id)
    existente = _buscar(db, clave)
    if existente is not None:
        return existente
    fila = RegistroMotivoConstancia(
        tipo_registro=CONSTANCIA_COMPENSACION,
        actor_correo=actor_correo,
        usuario_objetivo_id=None,
        correo_objetivo=correo_objetivo,
        institucion_id=institucion_id,
        accion=ACCION_COMPENSACION_INVITACION,
        fecha_registro=datetime.utcnow(),
        clave_idempotente=clave,
        invitacion_id=invitacion_id,
        resultado_revocacion=resultado_revocacion[:500],
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _buscar(db, clave)  # type: ignore[return-value]
    db.refresh(fila)
    return fila


def registrar_constancia_alta(
    db: Session,
    *,
    actor_correo: str,
    institucion_id: str,
    usuario_objetivo_id: int,
    correo_objetivo: str,
    invitacion_id: str | None = None,
) -> RegistroMotivoConstancia:
    """Evidencia recuperable de un alta cuyo mapa no se confirmo (D-2).

    Se persiste con una clave idempotente derivada del usuario local ya
    confirmado (la unica clave que el reintento puede reutilizar) y conserva
    `invitacion_id` cuando existe, para reconciliar la invitacion huerfana. La
    URL nunca se guarda. Si ya existe evidencia con la clave no se duplica.
    """
    clave = clave_para_alta(usuario_objetivo_id)
    existente = _buscar(db, clave)
    if existente is not None:
        return existente
    fila = RegistroMotivoConstancia(
        tipo_registro=CONSTANCIA_MOTIVO,
        actor_correo=actor_correo,
        usuario_objetivo_id=usuario_objetivo_id,
        correo_objetivo=correo_objetivo,
        institucion_id=institucion_id,
        accion=ACCION_ALTA_INVITACION,
        fecha_registro=datetime.utcnow(),
        clave_idempotente=clave,
        invitacion_id=invitacion_id,
    )
    db.add(fila)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _buscar(db, clave)  # type: ignore[return-value]
    db.refresh(fila)
    return fila


def buscar_constancia_alta(
    db: Session, usuario_objetivo_id: int
) -> RegistroMotivoConstancia | None:
    """Evidencia persistida del alta parcial de un usuario, o `None` (D-2)."""
    return _buscar(db, clave_para_alta(usuario_objetivo_id))


def completar_constancia_alta(
    db: Session,
    *,
    usuario_objetivo_id: int,
    actor_correo: str,
    institucion_id: str,
    correo_objetivo: str,
) -> bool:
    """Completa la evidencia del alta parcial reutilizando su clave (D-2).

    Solo actua si la evidencia persistida existe (nunca fabrica una clave): la
    convierte en registro completado y refresca actor/fecha. Devuelve `False`
    cuando no hay evidencia recuperable, de modo que el llamador pueda responder
    503 sin inventar idempotencia.
    """
    existente = buscar_constancia_alta(db, usuario_objetivo_id)
    if existente is None:
        return False
    if existente.tipo_registro == CONSTANCIA_MOTIVO:
        existente.tipo_registro = JUSTIFICACION
        existente.actor_correo = actor_correo
        existente.institucion_id = institucion_id
        existente.correo_objetivo = correo_objetivo
        existente.fecha_registro = datetime.utcnow()
        db.commit()
        db.refresh(existente)
    return True
