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

from typing import Callable, List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core import permisos, security
from app.models import (
    Departamento,
    Institucion,
    MapaUsuarioEsquema,
    Rol,
    Usuario,
)
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
    estados = _estados_locales(
        db_control if db_control is not None else db, [u.correo for u in usuarios]
    )
    for usuario in usuarios:
        # Atributo transitorio (no mapeado): lo consume `UsuarioRespuesta`.
        usuario.activo = estados.get(usuario.correo, True)
    return usuarios


def _estados_locales(db_control: Session, correos: List[str]) -> dict[str, bool]:
    """Estado local (`activo`) por correo desde el mapa de control, en un viaje."""
    if not correos:
        return {}
    filas = (
        db_control.query(MapaUsuarioEsquema)
        .filter(MapaUsuarioEsquema.correo.in_(correos))
        .all()
    )
    return {fila.correo: fila.activo for fila in filas}


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
) -> Usuario:
    """Crea un usuario aplicando el rol asignable y el ambito del creador.

    Feature 012 (D-3/AC-8): Clerk es la unica autoridad de identidad, de modo que
    el alta **valida que el correo ya exista en Clerk** antes de crear la fila
    local; no crea ni modifica ninguna identidad de Clerk. Si la frontera externa
    no puede consultarse responde **503** y si el correo no existe **422**, sin
    crear un usuario local no autenticable.

    La autorizacion por rol de la operacion ya la impone la dependencia HTTP;
    aqui se aplica la regla de dominio del rol asignable (D-6/AC-10) y el limite
    institucional del alta (D-4/AC-8): un departamento destino de otra institucion
    responde 403 sin crear fila. Todas las validaciones preceden a cualquier
    mutacion.

    Feature 012 (correccion T13): `db` es la sesion de **negocio** (tenant), donde
    vive el usuario; `db_control` es la sesion de **control** donde vive el mapa
    `correo -> esquema` (`None` reutiliza `db`, valido en el contexto logico unico
    de SQLite). El alta registra la **vinculacion local** en
    `mapa_usuario_esquema` (activa) para que el correo resuelva a su tenant; sin
    ella el usuario existiria en el tenant pero no seria autenticable (D-3). Un
    correo ya vinculado a otra institucion (o a una identidad local activa)
    responde **409** sin crear ni sobrescribir.
    """
    _validar_rol_asignable(db, datos.rol_id, identidad)
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    ambito_service.validar_departamento_en_alcance(
        db, datos.departamento_id, institucion_id
    )
    _verificar_correo_en_clerk(datos.correo, verificar_correo)

    existente = db.query(Usuario).filter(Usuario.correo == datos.correo).first()
    if existente:
        raise HTTPException(status_code=400, detail="El correo ya esta registrado")

    sesion_control = db_control if db_control is not None else db
    mapa = sesion_control.get(MapaUsuarioEsquema, str(datos.correo))
    if mapa is not None and mapa.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El correo ya esta vinculado a una identidad local activa",
        )

    nuevo_usuario = Usuario(**datos.model_dump())
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    _registrar_vinculacion(db, sesion_control, nuevo_usuario, mapa)
    return nuevo_usuario


def _registrar_vinculacion(
    db: Session,
    sesion_control: Session,
    usuario: Usuario,
    mapa: MapaUsuarioEsquema | None,
) -> None:
    """Registra/reactiva el `mapa_usuario_esquema` del usuario recien creado (D-3).

    La institucion de la vinculacion se deriva del **propio usuario**
    (`departamento -> institucion`), no del actor: asi tambien es correcta cuando
    un Superadmin (ambito global) da de alta en un tenant. Una institucion no
    resoluble no crea vinculacion (defensivo). Un mapa existente inactivo de la
    **misma** institucion se reactiva; uno de otra institucion responde **409**.
    """
    institucion_usuario = ambito_service.institucion_de_usuario(db, usuario)
    if institucion_usuario is None:
        return
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
        sesion_control.add(
            MapaUsuarioEsquema(
                correo=usuario.correo,
                institucion_id=institucion_usuario,
                nombre_esquema=nombre_esquema,
                activo=True,
            )
        )
    else:
        mapa.institucion_id = institucion_usuario
        mapa.nombre_esquema = nombre_esquema
        mapa.activo = True
    sesion_control.commit()


def _verificar_correo_en_clerk(
    correo: str, verificar_correo: Callable[[str], bool] | None
) -> None:
    """Valida la identidad preexistente en Clerk sin crear ni modificar nada (D-3).

    Sin costura inyectada no se consulta Clerk (la dependencia HTTP la aporta el
    endpoint). Un fallo de la frontera externa responde **503**; un correo sin
    identidad verificada responde **422**; en ambos casos no se crea la fila local.
    """
    if verificar_correo is None:
        return
    try:
        existe = verificar_correo(str(correo))
    except security.ErrorAutenticacion as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No fue posible verificar el correo contra Clerk",
        ) from exc
    if not existe:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El correo no existe como identidad verificada en Clerk",
        )


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
