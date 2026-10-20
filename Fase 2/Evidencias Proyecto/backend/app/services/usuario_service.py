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

from datetime import datetime, timezone
from typing import Callable, List

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import permisos, security
from app.models import (
    Departamento,
    Institucion,
    MapaUsuarioEsquema,
    Rol,
    Usuario,
)
from app.schemas.usuario_schema import UsuarioCrear, proyectar_estado_invitacion
from app.services import ambito_service, motivo_service
from app.services.auth_service import IdentidadAutenticada

#: Costuras inyectables de la frontera Clerk de invitaciones (Feature 017).
ConsultorIdentidad = Callable[[str], security.EstadoIdentidadClerk]
CreadorInvitacion = Callable[..., security.InvitacionCreada]
RevocadorInvitacion = Callable[[str], None]

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
    db: Session,
    identidad: IdentidadAutenticada | None = None,
    db_control: Session | None = None,
) -> List[Usuario]:
    """Usuarios del tenant visible para el actor, con su estado local.

    Feature 012 (T12): el listado publica el **estado del vinculo local**
    (`mapa_usuario_esquema.activo`, D-3) y la **sede** del usuario, cerrando la
    brecha que dejaba la vista de usuarios en "Estado no informado".

    `db` es la sesion de **negocio** (tenant) donde vive el usuario y su sede;
    `db_control` es la sesion de **control** donde vive el mapa `correo -> esquema`
    (`None` reutiliza `db`, valido en el contexto logico unico de SQLite). La
    ausencia de fila en el mapa no es una desactivacion explicita (mismo criterio
    que D-6): el usuario se publica como activo.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Usuario)
    if institucion_id is not None:
        consulta = consulta.join(
            Departamento, Usuario.departamento_id == Departamento.departamento_id
        ).filter(Departamento.institucion_id == institucion_id)
    usuarios = consulta.all()
    mapas = _mapas_locales(
        db_control if db_control is not None else db, [u.correo for u in usuarios]
    )
    for usuario in usuarios:
        # Atributos transitorios (no mapeados): los consume `UsuarioRespuesta`.
        mapa = mapas.get(security.normalizar_correo(usuario.correo))
        usuario.activo = True if mapa is None else mapa.activo
        usuario.estado_invitacion = estado_invitacion_efectivo(mapa)
    return usuarios


def estado_invitacion_efectivo(
    mapa: MapaUsuarioEsquema | None, ahora: datetime | None = None
) -> str:
    """Estado persistido proyectado, derivando `expirada` del timestamp (D-3).

    Nunca se consulta Clerk: la expiracion se calcula con
    `invitacion_expira_en`. Un mapa ausente o un estado legado/desconocido se
    publica como `no disponible`, jamas como `aceptada`.
    """
    if mapa is None:
        return proyectar_estado_invitacion(None)
    estado = mapa.estado_invitacion
    if estado == "pendiente" and mapa.invitacion_expira_en is not None:
        instante = ahora or datetime.now(timezone.utc)
        expira = mapa.invitacion_expira_en
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        if expira <= instante:
            return "expirada"
    return proyectar_estado_invitacion(estado)


def _mapas_locales(
    db_control: Session, correos: List[str]
) -> dict[str, MapaUsuarioEsquema]:
    """Mapas de control por correo (comparacion normalizada), en un viaje."""
    if not correos:
        return {}
    normalizados = {security.normalizar_correo(correo) for correo in correos}
    filas = (
        db_control.query(MapaUsuarioEsquema)
        .filter(
            func.lower(func.trim(MapaUsuarioEsquema.correo)).in_(normalizados)
        )
        .all()
    )
    return {security.normalizar_correo(fila.correo): fila for fila in filas}


def _mapa_por_correo(
    sesion_control: Session, correo: str
) -> MapaUsuarioEsquema | None:
    """Mapa de control del correo normalizado, sin depender de la caja."""
    return (
        sesion_control.query(MapaUsuarioEsquema)
        .filter(
            func.lower(func.trim(MapaUsuarioEsquema.correo))
            == security.normalizar_correo(correo)
        )
        .first()
    )


def _es_identidad_de_control(sesion_control: Session, correo: str) -> bool:
    """True si el correo pertenece a la identidad global Superadmin (D-1).

    Un correo de control no puede asociarse a un tenant: se responde **409** sin
    invitar ni crear filas locales.
    """
    nombre_rol = (
        sesion_control.execute(
            select(Rol.nombre_rol)
            .join(Usuario, Usuario.rol_id == Rol.rol_id)
            .where(
                func.lower(func.trim(Usuario.correo))
                == security.normalizar_correo(correo)
            )
        )
        .scalars()
        .first()
    )
    return nombre_rol == _SUPERADMIN


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
    verificar_correo: Callable[[str], bool] | None = None,
    db_control: Session | None = None,
    *,
    consultar_identidad: ConsultorIdentidad | None = None,
    crear_invitacion_fn: CreadorInvitacion | None = None,
    revocar_invitacion_fn: RevocadorInvitacion | None = None,
    institucion_id: str | None = None,
) -> Usuario:
    """Da de alta un usuario local con invitacion y recuperacion (Feature 017).

    Orden de la spec (D-2): **validar todo lo local** (rol asignable, ambito,
    duplicados, identidad de control) antes de tocar Clerk; despues clasificar la
    frontera (identidad existente / invitacion pendiente / ninguna), emitir
    invitacion solo en el ultimo caso, confirmar el usuario tenant y finalmente
    confirmar el mapa de control.

    Casos:

    * Identidad existente -> solo vinculo local con estado `aceptada`.
    * Invitacion pendiente -> asociacion `pendiente` reutilizando la existente.
    * Ninguna -> `crear_invitacion` y asociacion `pendiente` con `invitacion_id`.
    * Usuario tenant ya creado sin mapa -> reintento recuperable: completa la
      asociacion sin volver a invitar ni responder 400/409 por duplicado (D-2).
    * Cualquier mapa existente -> **409** (una asociacion inactiva solo se
      reactiva con la operacion explicita de estado y un motivo nuevo).

    Si falla el commit tenant se intenta revocar la invitacion recien creada; si
    la revocacion falla se persiste una constancia `compensacion_invitacion_fallida`
    con `invitacion_id` (nunca la URL). Si el tenant se confirma y el mapa falla,
    responde **503** con el identificador local para que el reintento complete la
    asociacion.
    """
    _validar_rol_asignable(db, datos.rol_id, identidad)
    alcance = ambito_service.alcance_institucional(db, identidad)
    if institucion_id is None:
        ambito_service.validar_departamento_en_alcance(
            db, datos.departamento_id, alcance
        )
        institucion_destino = None
    else:
        _validar_departamento_en_institucion(db, datos.departamento_id, institucion_id)
        institucion_destino = institucion_id

    correo = security.normalizar_correo(str(datos.correo))
    institucion_para_evidencia = institucion_destino or (
        ambito_service.institucion_de_departamento(db, datos.departamento_id)
    )
    sesion_control = db_control if db_control is not None else db
    mapa = _mapa_por_correo(sesion_control, correo)
    existente = _usuario_por_correo_normalizado(db, correo)

    if existente is not None:
        _exigir_usuario_en_institucion(db, existente, institucion_destino)
        if mapa is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El correo ya esta registrado y vinculado a una institucion",
            )
        # D-2: alta incompleta (usuario tenant sin mapa). Se completa el mapa sin
        # volver a invitar y sin duplicar usuario.
        return _completar_alta_sin_mapa(
            db,
            sesion_control,
            existente,
            correo,
            institucion_destino,
            verificar_correo=verificar_correo,
            consultar_identidad=consultar_identidad,
            crear_invitacion_fn=crear_invitacion_fn,
        )

    if mapa is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El correo ya esta vinculado; una asociacion inactiva se reactiva "
                "con la operacion explicita de estado"
            ),
        )
    if _es_identidad_de_control(sesion_control, correo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El correo pertenece a una identidad global de control",
        )

    estado = _consultar_estado_clerk(
        correo, verificar_correo, consultar_identidad
    )
    invitacion = None
    estado_invitacion = "aceptada"
    invitacion_id = None
    expira_en = None
    if not estado.identidad_existente:
        if estado.invitacion_pendiente:
            estado_invitacion = "pendiente"
            invitacion_id = estado.invitacion_id
        else:
            if crear_invitacion_fn is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="La frontera de invitaciones no esta configurada",
                )
            invitacion = _crear_invitacion(crear_invitacion_fn, correo)
            estado_invitacion = "pendiente"
            invitacion_id = invitacion.invitacion_id
            expira_en = invitacion.expira_en

    nuevo_usuario = Usuario(**{**datos.model_dump(), "correo": correo})
    try:
        _confirmar_usuario_tenant(db, nuevo_usuario)
    except IntegrityError as exc:
        db.rollback()
        _compensar_invitacion(
            sesion_control,
            invitacion=invitacion,
            correo=correo,
            actor_correo=_correo_actor(identidad),
            institucion_id=institucion_para_evidencia,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El correo ya esta registrado",
        ) from exc
    except Exception:
        db.rollback()
        _compensar_invitacion(
            sesion_control,
            invitacion=invitacion,
            correo=correo,
            actor_correo=_correo_actor(identidad),
            institucion_id=institucion_para_evidencia,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
        raise

    try:
        mapa = _registrar_vinculacion(
            db,
            sesion_control,
            nuevo_usuario,
            mapa,
            institucion_id=institucion_destino,
            estado_invitacion=estado_invitacion,
            invitacion_id=invitacion_id,
            expira_en=expira_en,
        )
    except Exception as exc:
        sesion_control.rollback()
        # D-2/C-F: el tenant quedo confirmado y el mapa no. Se deja evidencia
        # recuperable con una clave persistida (derivada del usuario local) para
        # que el reintento complete mapa y registro sin inventar idempotencia.
        _dejar_constancia_alta(
            sesion_control,
            usuario=nuevo_usuario,
            correo=correo,
            institucion_id=institucion_para_evidencia,
            actor_correo=_correo_actor(identidad),
            invitacion_id=invitacion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "El usuario local se creo pero la asociacion no pudo confirmarse; "
                f"reintente el alta (usuario_id={nuevo_usuario.usuario_id})"
            ),
        ) from exc

    _proyectar_invitacion(nuevo_usuario, mapa, invitacion)
    return nuevo_usuario


def _usuario_por_correo_normalizado(db: Session, correo: str) -> Usuario | None:
    return db.execute(
        select(Usuario).where(
            func.lower(func.trim(Usuario.correo))
            == security.normalizar_correo(correo)
        )
    ).scalars().first()


def _validar_departamento_en_institucion(
    db: Session, departamento_id: int, institucion_id: str
) -> None:
    """El departamento destino debe pertenecer a la institucion derivada (D-10)."""
    departamento = db.get(Departamento, departamento_id)
    if departamento is None or departamento.institucion_id != institucion_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El departamento indicado esta fuera de la institucion",
        )


def _exigir_usuario_en_institucion(
    db: Session, usuario: Usuario, institucion_id: str | None
) -> None:
    if institucion_id is None:
        return
    if ambito_service.institucion_de_usuario(db, usuario) != institucion_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario inexistente o fuera de la institucion",
        )


def _correo_actor(identidad: IdentidadAutenticada | None) -> str:
    if identidad is None or identidad.usuario is None:
        return "sistema"
    return security.normalizar_correo(str(identidad.usuario.correo))


def _consultar_estado_clerk(
    correo: str,
    verificar_correo: Callable[[str], bool] | None,
    consultar_identidad: ConsultorIdentidad | None,
) -> security.EstadoIdentidadClerk:
    """Traduce la frontera externa a estado de dominio o a 503/409 (D-1)."""
    if consultar_identidad is not None:
        try:
            return consultar_identidad(correo)
        except security.ErrorInvitacionConflicto as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        except security.ErrorClerkNoDisponible as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        except security.ErrorAutenticacion as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No fue posible verificar el correo contra Clerk",
            ) from exc
    if verificar_correo is not None:
        try:
            existe = verificar_correo(correo)
        except security.ErrorAutenticacion as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No fue posible verificar el correo contra Clerk",
            ) from exc
        return security.EstadoIdentidadClerk(
            identidad_existente=bool(existe),
            invitacion_pendiente=False,
            invitacion_id=None,
        )
    return security.EstadoIdentidadClerk(
        identidad_existente=False, invitacion_pendiente=False, invitacion_id=None
    )


def _crear_invitacion(
    crear_invitacion_fn: CreadorInvitacion, correo: str
) -> security.InvitacionCreada:
    try:
        return crear_invitacion_fn(correo, ignore_existing=False)
    except security.ErrorInvitacionConflicto as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except security.ErrorClerkNoDisponible as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def _confirmar_usuario_tenant(db: Session, usuario: Usuario) -> None:
    """Primera confirmacion local: commit del usuario en el tenant."""
    db.add(usuario)
    db.flush()
    db.commit()
    db.refresh(usuario)


def _compensar_invitacion(
    sesion_control: Session,
    *,
    invitacion: security.InvitacionCreada | None,
    correo: str,
    actor_correo: str,
    institucion_id: str | None,
    revocar_invitacion_fn: RevocadorInvitacion | None,
) -> None:
    """Intenta revocar la invitacion recien creada; si falla deja constancia."""
    if invitacion is None:
        return
    try:
        if revocar_invitacion_fn is None:
            raise RuntimeError("revocador no disponible")
        revocar_invitacion_fn(invitacion.invitacion_id)
    except Exception as exc:  # noqa: BLE001 - la causa se registra como texto
        try:
            sesion_control.rollback()
            motivo_service.registrar_compensacion_invitacion(
                sesion_control,
                actor_correo=actor_correo,
                institucion_id=institucion_id or "CTRL-SAAS",
                correo_objetivo=correo,
                invitacion_id=invitacion.invitacion_id,
                resultado_revocacion=f"revocacion_fallida: {type(exc).__name__}",
            )
        except Exception:  # noqa: BLE001 - nunca se enmascara el error original
            sesion_control.rollback()


def _registrar_vinculacion(
    db: Session,
    sesion_control: Session,
    usuario: Usuario,
    mapa: MapaUsuarioEsquema | None,
    *,
    institucion_id: str | None = None,
    estado_invitacion: str | None = None,
    invitacion_id: str | None = None,
    expira_en: datetime | None = None,
) -> MapaUsuarioEsquema:
    """Segunda confirmacion local: registra el mapa `correo -> esquema` (D-3).

    La institucion se toma del parametro explicito (rutas de control) o del
    propio usuario. Un mapa de otra institucion responde **409**. El estado de
    invitacion se persiste solo cuando el flujo lo conoce; un mapa legado queda
    con `estado_invitacion=None` (se proyecta `no disponible`).
    """
    institucion_usuario = institucion_id or ambito_service.institucion_de_usuario(
        db, usuario
    )
    if institucion_usuario is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo resolver la institucion del usuario",
        )
    if mapa is not None and mapa.institucion_id != institucion_usuario:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El correo esta vinculado a otra institucion",
        )

    # Import local: `tenant_service` importa `control_service`; se evita el ciclo
    # de importacion en cabecera.
    from app.services.tenant_service import nombre_esquema_para_institucion

    nombre_esquema = nombre_esquema_para_institucion(institucion_usuario)
    if mapa is None:
        mapa = MapaUsuarioEsquema(
            correo=security.normalizar_correo(usuario.correo),
            institucion_id=institucion_usuario,
            nombre_esquema=nombre_esquema,
            activo=True,
        )
        sesion_control.add(mapa)
    else:
        mapa.institucion_id = institucion_usuario
        mapa.nombre_esquema = nombre_esquema
        mapa.activo = True
    mapa.estado_invitacion = estado_invitacion
    mapa.invitacion_id = invitacion_id
    mapa.invitacion_expira_en = expira_en
    sesion_control.commit()
    return mapa


def _proyectar_invitacion(
    usuario: Usuario,
    mapa: MapaUsuarioEsquema | None,
    invitacion: security.InvitacionCreada | None,
) -> None:
    """Expone estado y URL solo en la respuesta inmediata (nunca se persiste)."""
    usuario.activo = True if mapa is None else mapa.activo
    usuario.estado_invitacion = estado_invitacion_efectivo(mapa)
    usuario.url_invitacion = None if invitacion is None else invitacion.url


def _completar_alta_sin_mapa(
    db: Session,
    sesion_control: Session,
    usuario: Usuario,
    correo: str,
    institucion_destino: str | None,
    *,
    verificar_correo: Callable[[str], bool] | None,
    consultar_identidad: ConsultorIdentidad | None,
    crear_invitacion_fn: CreadorInvitacion | None,
) -> Usuario:
    """Reintento de un alta parcial: completa mapa y evidencia sin invitar de nuevo.

    D-2/C-F: ademas del mapa se completa el registro/constancia del alta
    original reutilizando **solo** la clave idempotente persistida. Si Clerk
    conoce una invitacion pendiente y no existe evidencia recuperable, no se
    fabrica una clave: se responde 503 para reconciliacion.
    """
    estado = _consultar_estado_clerk(correo, verificar_correo, consultar_identidad)
    if estado.identidad_existente:
        estado_invitacion = "aceptada"
        invitacion_id = None
    elif estado.invitacion_pendiente:
        estado_invitacion = "pendiente"
        invitacion_id = estado.invitacion_id
    else:
        # No se vuelve a invitar (D-2): se conserva una asociacion pendiente sin
        # identificador externo localizable.
        estado_invitacion = "pendiente"
        invitacion_id = None

    evidencia = motivo_service.buscar_constancia_alta(sesion_control, usuario.usuario_id)
    if evidencia is None and estado.invitacion_pendiente:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Existe una invitacion pendiente pero no se pudo recuperar la "
                "evidencia persistida del alta original; requiere reconciliacion "
                "administrativa antes de reintentar"
            ),
        )

    mapa = _registrar_vinculacion(
        db,
        sesion_control,
        usuario,
        None,
        institucion_id=institucion_destino,
        estado_invitacion=estado_invitacion,
        invitacion_id=invitacion_id,
    )
    if evidencia is not None:
        from app.services import ambito_service

        institucion = institucion_destino or ambito_service.institucion_de_usuario(
            db, usuario
        )
        motivo_service.completar_constancia_alta(
            sesion_control,
            usuario_objetivo_id=usuario.usuario_id,
            actor_correo="sistema",
            institucion_id=institucion or "CTRL-SAAS",
            correo_objetivo=correo,
        )
    _proyectar_invitacion(usuario, mapa, None)
    return usuario


def _dejar_constancia_alta(
    sesion_control: Session,
    *,
    usuario: Usuario | None,
    correo: str,
    institucion_id: str | None,
    actor_correo: str,
    invitacion_id: str | None,
) -> None:
    """Persiste la evidencia recuperable de un alta cuyo mapa fallo (D-2)."""
    if usuario is None:
        return
    try:
        motivo_service.registrar_constancia_alta(
            sesion_control,
            actor_correo=actor_correo,
            institucion_id=institucion_id or "CTRL-SAAS",
            usuario_objetivo_id=usuario.usuario_id,
            correo_objetivo=correo,
            invitacion_id=invitacion_id,
        )
    except Exception:  # noqa: BLE001 - el 503 ya informa la recuperacion
        sesion_control.rollback()


def reenviar_invitacion_usuario(
    db: Session,
    sesion_control: Session,
    usuario_id: int,
    identidad: IdentidadAutenticada | None = None,
    *,
    consultar_identidad: ConsultorIdentidad | None = None,
    crear_invitacion_fn: CreadorInvitacion,
    revocar_invitacion_fn: RevocadorInvitacion | None = None,
    actor_correo: str = "sistema",
) -> Usuario:
    """Reenvio ordinario del Administrador a su Bodeguero/Solicitante (D-4/D-10).

    Limita el objetivo a Bodegueros/Solicitantes **activos** de la institucion del
    Administrador. Un objetivo inexistente o ajeno responde **404**; un rol no
    reenviable, **403**; una asociacion ausente o inactiva, **409** (para la
    inactiva, primero se reactiva con `PATCH .../estado` y motivo). La rotacion
    Clerk y la URL solo en la respuesta las implementa `reenviar_invitacion`.
    """
    institucion = ambito_service.alcance_institucional(db, identidad)
    if institucion is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La operacion requiere una institucion concreta",
        )
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or (
        ambito_service.institucion_de_usuario(db, usuario) != institucion
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario inexistente o fuera de la institucion",
        )
    rol = db.get(Rol, usuario.rol_id)
    if rol is None or rol.nombre_rol not in _ROLES_ASIGNABLES_ADMINISTRADOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo se reenvia la invitacion de Bodegueros o Solicitantes",
        )
    return reenviar_invitacion(
        db,
        sesion_control,
        usuario,
        consultar_identidad=consultar_identidad,
        crear_invitacion_fn=crear_invitacion_fn,
        revocar_invitacion_fn=revocar_invitacion_fn,
        actor_correo=actor_correo,
    )



def reenviar_invitacion(
    db: Session,
    sesion_control: Session,
    usuario: Usuario,
    *,
    consultar_identidad: ConsultorIdentidad | None = None,
    crear_invitacion_fn: CreadorInvitacion,
    revocar_invitacion_fn: RevocadorInvitacion | None = None,
    actor_correo: str = "sistema",
) -> Usuario:
    """Crea una invitacion nueva para un usuario y devuelve URL solo ahora (D-4).

    Una invitacion `aceptada` responde **409**. Una invitacion pendiente conocida
    se intenta revocar antes de crear la nueva; si la creacion falla se conserva
    el identificador persistido anterior y se deja constancia. Un "ya invitado"
    de Clerk responde **409** sin cambiar el ID persistido ni entregar enlace.
    """
    correo = security.normalizar_correo(str(usuario.correo))
    mapa = _mapa_por_correo(sesion_control, correo)
    if mapa is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario no tiene asociacion local; complete el alta antes de "
                "reenviar la invitacion"
            ),
        )

    estado = estado_invitacion_efectivo(mapa)
    if estado == "aceptada":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La invitacion ya fue aceptada; no se reenvia",
        )
    if not mapa.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "La asociacion local esta inactiva; reactivela primero con "
                "`PATCH .../estado` y un motivo, y luego reenvie la invitacion"
            ),
        )

    if estado == "pendiente" and mapa.invitacion_id:
        if revocar_invitacion_fn is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La frontera de revocacion no esta configurada",
            )
        try:
            revocar_invitacion_fn(mapa.invitacion_id)
        except security.ErrorClerkNoDisponible as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        mapa.estado_invitacion = "revocada"

    try:
        invitacion = crear_invitacion_fn(correo, ignore_existing=False)
    except security.ErrorInvitacionConflicto as exc:
        sesion_control.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except security.ErrorClerkNoDisponible as exc:
        sesion_control.rollback()
        _constancia_reenvio_fallido(
            sesion_control,
            mapa=mapa,
            correo=correo,
            actor_correo=actor_correo,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    mapa.estado_invitacion = "pendiente"
    mapa.invitacion_id = invitacion.invitacion_id
    mapa.invitacion_expira_en = invitacion.expira_en
    mapa.invitacion_aceptada_en = None
    sesion_control.commit()
    usuario.activo = mapa.activo
    usuario.estado_invitacion = "pendiente"
    usuario.url_invitacion = invitacion.url
    return usuario


def _constancia_reenvio_fallido(
    sesion_control: Session,
    *,
    mapa: MapaUsuarioEsquema,
    correo: str,
    actor_correo: str,
) -> None:
    """Constancia de un reenvio que revoco y no pudo crear la nueva (D-4)."""
    if not mapa.invitacion_id:
        return
    try:
        sesion_control.rollback()
        motivo_service.registrar_compensacion_invitacion(
            sesion_control,
            actor_correo=actor_correo,
            institucion_id=mapa.institucion_id,
            correo_objetivo=correo,
            invitacion_id=mapa.invitacion_id,
            resultado_revocacion="reenvio_fallido: invitacion previa revocada",
        )
    except Exception:  # noqa: BLE001
        sesion_control.rollback()


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
