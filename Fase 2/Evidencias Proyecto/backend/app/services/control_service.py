"""Servicio del esquema de control (Feature 010).

Agrupa la logica que opera sobre el esquema global de control antes de abrir la
sesion de negocio. En esta tarea (T5) expone la **comparacion de version
objetivo** que gobierna el enrutamiento:

* `es_version_objetivo(version)`: igualdad exacta contra la constante de
  despliegue `VERSION_ESQUEMA_OBJETIVO` (stack §5). Ausente, vacia, futura,
  incompleta, con espacios o de otro tipo deniega en cerrado.
* `tenant_en_version_objetivo(db)`: lee la unica fila vigente de
  `version_esquema` del esquema al que esta ligada `db` (el tenant) y confirma
  que coincide con la version objetivo.

El bootstrap de control (`ejecutar_bootstrap_control`, T8) y el aprovisionamiento
del alta (T7) llegan en sus propias tareas; esta tarea no los implementa.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL
from app.models.control import (
    MapaUsuarioEsquema,
    RegistroMotivoConstancia,
    VersionEsquema,
)
from app.models.control_canonico import (
    CAPACIDADES,
    FuncionInstitucion,
    InstitucionControl,
)
from app.models.institucion import Departamento, Institucion
from app.models.rol import Rol
from app.models.sede import Sede
from app.models.usuario import Usuario
from app.schemas.control_schema import (
    CLASE_NO_DISPONIBLE,
    CLASE_NO_ENRUTABLE,
    CLASE_OPERATIVO,
    DETALLE_INSTITUCION_INACTIVA,
    DETALLE_TENANT_NO_DISPONIBLE,
    DETALLE_TENANT_NO_RESOLUBLE,
    DETALLE_VERSION_AUSENTE,
    DETALLE_VERSION_INCOMPATIBLE,
    ESTADO_OPERATIVA,
    AdministradorListadoControlRespuesta,
    CapacidadRespuesta,
    DashboardSaaSRespuesta,
    InstitucionAltaControlCrear,
    InstitucionAltaControlRespuesta,
    InstitucionControlRespuesta,
    InstitucionEdicion,
    InstitucionEstadoRespuesta,
    InstitucionMetricasRespuesta,
)

#: Estructuras auxiliares que viven **solo** en el esquema de control. El
#: aprovisionamiento tenant las excluye de `Base.metadata`; la Feature 017 suma
#: `registro_motivo_constancia` al mapa de la Feature 010.
_TABLAS_SOLO_CONTROL: frozenset[str] = frozenset(
    {
        MapaUsuarioEsquema.__tablename__,
        RegistroMotivoConstancia.__tablename__,
    }
)


def tablas_metadata_tenant() -> list:
    """Tablas de `Base.metadata` que se replican en cada esquema tenant.

    Excluye las auxiliares de control (mapa de usuarios y registro de
    motivos/constancias). Es la unica fuente del filtro de aprovisionamiento: un
    modelo nuevo de control debe sumarse a `_TABLAS_SOLO_CONTROL` y no al tenant.
    """
    return [
        tabla
        for tabla in Base.metadata.sorted_tables
        if tabla.name not in _TABLAS_SOLO_CONTROL
    ]


#: Catalogos de rol replicados en cada tenant (D-4). El rol Superadmin vive solo
#: en control y nunca se replica en un tenant.
_ROLES_TENANT: tuple[tuple[str, str], ...] = (
    ("Administrador", "Gestiona usuarios, departamentos y catalogo maestro"),
    ("Bodeguero", "Gestiona stock fisico y despacha pedidos aprobados"),
    ("Solicitante", "Funcionario que consulta stock y emite tickets"),
)

#: Catalogo de prioridades replicado en cada tenant (D-4).
_PRIORIDADES_TENANT: tuple[tuple[str, str], ...] = (
    ("Alta", "Necesario para operar en el corto plazo"),
    ("Media", "Requiere reposicion pero no bloquea la operacion"),
    ("Baja", "Puede esperar a la siguiente compra periodica"),
)

#: Catalogo de estados de ticket replicado en cada tenant (D-4), en orden de flujo.
_ESTADOS_TICKET_TENANT: tuple[tuple[str, str], ...] = (
    ("Pendiente", "Ticket creado, aun sin revision"),
    ("EnRevision", "Revisando justificacion y disponibilidad"),
    ("EnCurso", "Aprobado y en preparacion de despacho"),
    ("Cerrado", "Despachado y con fecha de cierre registrada"),
)

#: Nombre de la sede inicial que recibe todo tenant recien aprovisionado (spec
#: 011 D-5). Sin CRUD de sedes (Feature 012) un tenant sin sedes no podria
#: operar, de modo que el alta crea "Sede Central" como semilla de arranque y
#: deja el tenant operativo.
NOMBRE_SEDE_CENTRAL = "Sede Central"

# ---------------------------------------------------------------------------
# Bootstrap administrativo de control (T8, AC-6)
# ---------------------------------------------------------------------------

#: ID canonico de la institucion administrativa de control (D-2, stack §7). Es un
#: valor reservado: no es el tenant de ninguna institucion concreta y nunca se
#: enruta. Se usa como clave estable de idempotencia del bootstrap.
INSTITUCION_ADMINISTRATIVA_ID = "CTRL-SAAS"

#: Nombre legible de la institucion administrativa de control.
INSTITUCION_ADMINISTRATIVA_NOMBRE = "CompuStock SaaS"

#: Nombre del departamento administrativo que satisface
#: `usuario.departamento_id NOT NULL` sin excepciones de nulabilidad (stack §7).
DEPARTAMENTO_ADMINISTRATIVO_NOMBRE = "Administracion SaaS"

#: Nombre del rol global del Superadmin. Vive en control y nunca se replica como
#: rol de tenant (stack §3/§7).
ROL_SUPERADMIN = "Superadmin"

#: Correo de la identidad Superadmin de control cuando la base aun no tiene una.
#: El bootstrap nunca reescribe una identidad Superadmin preexistente (p. ej. la
#: de una base migrada): solo la crea si no hay ninguna.
CORREO_SUPERADMIN = "superadmin@compustock.cl"


class ErrorAprovisionamiento(Exception):
    """Fallo del alta de institucion; la capa HTTP lo normaliza a su respuesta."""


class ErrorCorreoInexistente(ErrorAprovisionamiento):
    """El correo del Administrador no existe en Clerk -> HTTP 422."""


class ErrorClerkNoDisponible(ErrorAprovisionamiento):
    """La frontera Clerk no pudo verificar el correo -> HTTP 503."""


class ErrorAltaParcialIncompatible(ErrorAprovisionamiento):
    """El esquema existente no es el resto compatible del alta -> HTTP 503."""


class ErrorTenantNoDisponible(Exception):
    """La sesion/lectura/escritura del tenant no esta disponible -> HTTP 503."""


class ErrorConflictoAprovisionamiento(ErrorAprovisionamiento):
    """Institucion/correo/esquema ya tomado o fallo de etapa -> HTTP 409."""


class ErrorInstitucionNoEncontrada(Exception):
    """La institucion canonica no existe en control -> HTTP 404."""


class ErrorAdministradorNoEncontrado(Exception):
    """El usuario no existe o no es Administrador de la institucion -> HTTP 404."""


class ErrorRolAdministradorInvalido(Exception):
    """La ruta de control solo gestiona Administradores -> HTTP 403."""


class ErrorFuncionInvalida(Exception):
    """La funcion no pertenece al conjunto cerrado de capacidades -> HTTP 422."""


def es_version_objetivo(version: str | None) -> bool:
    """True solo si `version` es **exactamente** la constante de despliegue.

    La comparacion es de igualdad exacta (stack §5): no hay normalizacion,
    recorte ni comparacion semantica; cualquier discrepancia deniega cerrado.
    """
    return version == VERSION_ESQUEMA_OBJETIVO


def tenant_en_version_objetivo(db: Session) -> bool:
    """True solo si el tenant de `db` tiene una unica fila de version objetivo.

    Une exactamente una fila vigente en `version_esquema` (stack §5) y su token
    es la version objetivo. Cero filas (tenant no preparado), varias filas o un
    token distinto **deniegan en cerrado**: no existe fallback.
    """
    versiones = db.execute(select(VersionEsquema.version)).scalars().all()
    return len(versiones) == 1 and es_version_objetivo(versiones[0])


# ---------------------------------------------------------------------------
# Bootstrap administrativo de control (T8)
# ---------------------------------------------------------------------------


def _institucion_administrativa(db: Session) -> InstitucionControl:
    """Institucion administrativa de control, reutilizandola si ya existe.

    Pertenece al **canonico de control** (Feature 012): usa `InstitucionControl`,
    que porta `rut`, `direccion` y el estado `activo` sin contaminar el espejo
    tenant de dos columnas.
    """
    institucion = db.get(InstitucionControl, INSTITUCION_ADMINISTRATIVA_ID)
    if institucion is None:
        institucion = InstitucionControl(
            institucion_id=INSTITUCION_ADMINISTRATIVA_ID,
            nombre=INSTITUCION_ADMINISTRATIVA_NOMBRE,
            direccion="Esquema de control",
        )
        db.add(institucion)
        db.flush()
    return institucion


def _rol_superadmin(db: Session) -> Rol:
    """Rol Superadmin de control, reutilizandolo si ya existe."""
    rol = (
        db.execute(select(Rol).where(Rol.nombre_rol == ROL_SUPERADMIN))
        .scalars()
        .first()
    )
    if rol is None:
        rol = Rol(
            nombre_rol=ROL_SUPERADMIN,
            descripcion="Administrador global de la plataforma SaaS",
        )
        db.add(rol)
        db.flush()
    return rol


def _departamento_administrativo(db: Session, institucion_id: str) -> Departamento:
    """Departamento administrativo de control, reutilizandolo si ya existe.

    `departamento.institucion_id` sigue siendo `NOT NULL`: el departamento se
    ancla a la institucion administrativa, sin excepciones de nulabilidad.
    """
    departamento = (
        db.execute(
            select(Departamento)
            .where(Departamento.institucion_id == institucion_id)
            .order_by(Departamento.departamento_id)
        )
        .scalars()
        .first()
    )
    if departamento is None:
        departamento = Departamento(
            nombre_dep=DEPARTAMENTO_ADMINISTRATIVO_NOMBRE,
            descripcion="Departamento administrativo del esquema de control",
            institucion_id=institucion_id,
        )
        db.add(departamento)
        db.flush()
    return departamento


def _usuario_superadmin(db: Session, rol: Rol, departamento: Departamento) -> Usuario:
    """Usuario Superadmin de control, reutilizandolo si ya existe.

    La identidad se reconoce por su rol Superadmin (no por el correo), de modo
    que una base migrada con su propio correo Superadmin no recibe una copia; si
    no existe ninguna, se crea una con el correo por defecto de control.
    """
    usuario = (
        db.execute(
            select(Usuario)
            .join(Rol, Usuario.rol_id == Rol.rol_id)
            .where(Rol.nombre_rol == ROL_SUPERADMIN)
            .order_by(Usuario.usuario_id)
        )
        .scalars()
        .first()
    )
    if usuario is None:
        usuario = Usuario(
            nombre=ROL_SUPERADMIN,
            apellido="CompuStock",
            correo=CORREO_SUPERADMIN,
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
        db.add(usuario)
        db.flush()
    return usuario


def ejecutar_bootstrap_control(db: Session) -> None:
    """Inicializa la estructura administrativa del esquema de control (AC-6).

    Crea —o reutiliza si ya existen— la institucion administrativa, el
    departamento administrativo, el rol Superadmin y su usuario, satisfaciendo
    `usuario.departamento_id NOT NULL` y `departamento.institucion_id NOT NULL`
    **sin** alterar las nulabilidades del modelo 3NF ni tocar datos de negocio.

    Es **idempotente**: sobre una base existente una segunda ejecucion reutiliza
    los registros administrativos (misma institucion, mismo rol, mismo usuario) y
    no duplica ni trunca nada. Solo inserta la fila administrativa que falte; las
    instituciones, usuarios y roles de negocio no se leen ni se modifican.
    """
    institucion = _institucion_administrativa(db)
    rol = _rol_superadmin(db)
    departamento = _departamento_administrativo(db, institucion.institucion_id)
    _usuario_superadmin(db, rol, departamento)
    db.commit()


# ---------------------------------------------------------------------------
# Aprovisionamiento minimo de institucion (T7)
# ---------------------------------------------------------------------------


def _mapa_por_correo(db: Session, correo: str) -> MapaUsuarioEsquema | None:
    return db.execute(
        select(MapaUsuarioEsquema).where(MapaUsuarioEsquema.correo == correo)
    ).scalar_one_or_none()


def _mapa_por_nombre_esquema(
    db: Session, nombre_esquema: str
) -> MapaUsuarioEsquema | None:
    return db.execute(
        select(MapaUsuarioEsquema).where(
            MapaUsuarioEsquema.nombre_esquema == nombre_esquema
        )
    ).scalar_one_or_none()


def _es_correo_usuario_local(db: Session, correo: str) -> bool:
    return (
        db.execute(
            select(Usuario.usuario_id).where(
                func.lower(func.trim(Usuario.correo))
                == security.normalizar_correo(correo)
            )
        ).scalar_one_or_none()
        is not None
    )


def _reservar_control(
    db: Session,
    datos: InstitucionAltaControlCrear,
    nombre_esquema: str,
) -> None:
    """Reserva el registro canonico de institucion y el mapa `correo -> esquema`.

    Comprueba duplicidades (institucion, correo mapeado, colision de
    `nombre_esquema`) y la inexistencia del correo como usuario local **antes**
    de crear recursos (AC-8). Cualquier conflicto levanta
    `ErrorConflictoAprovisionamiento` sin haber mutado el estado.
    """
    if db.get(InstitucionControl, datos.institucion_id) is not None:
        raise ErrorConflictoAprovisionamiento("la institucion ya esta registrada")
    if _mapa_por_correo(db, datos.correo_administrador) is not None:
        raise ErrorConflictoAprovisionamiento("el correo ya esta asociado a un esquema")
    if _mapa_por_nombre_esquema(db, nombre_esquema) is not None:
        raise ErrorConflictoAprovisionamiento("el nombre de esquema ya esta en uso")
    if _es_correo_usuario_local(db, datos.correo_administrador):
        raise ErrorConflictoAprovisionamiento("el correo ya es un usuario local")
    from app.services.usuario_service import _es_identidad_de_control

    if _es_identidad_de_control(db, datos.correo_administrador):
        raise ErrorConflictoAprovisionamiento(
            "el correo pertenece a una identidad global de control"
        )


def _rol_administrador(sesion: Session) -> Rol:
    """Devuelve el rol `Administrador` **unico** del contexto de la sesion.

    El catalogo replicado del tenant (`_ROLES_TENANT`, D-4) ya publica el rol
    `Administrador`, asi que el usuario inicial debe **reutilizarlo** en lugar de
    crear un segundo registro. Antes de esta correccion el alta creaba uno nuevo
    despues de replicar el catalogo, dejando el rol duplicado en el tenant.

    Solo en ausencia de ese rol (p. ej. el contexto logico de la suite SQLite, que
    no replica catalogos) se crea uno minimo.
    """
    rol = (
        sesion.execute(select(Rol).where(Rol.nombre_rol == "Administrador"))
        .scalars()
        .first()
    )
    if rol is None:
        rol = Rol(
            nombre_rol="Administrador",
            descripcion="Administrador inicial de la institucion",
        )
        sesion.add(rol)
        sesion.flush()
    return rol


def _crear_administrador(
    sesion: Session,
    datos: InstitucionAltaControlCrear,
    *,
    institucion_id: str,
) -> None:
    """Departamento administrativo, rol Administrador y usuario inicial del tenant."""
    rol = _rol_administrador(sesion)

    departamento = Departamento(
        nombre_dep=datos.departamento_nombre_administrativo,
        descripcion="Departamento administrativo inicial",
        institucion_id=institucion_id,
    )
    sesion.add(departamento)
    sesion.flush()

    sesion.add(
        Usuario(
            nombre=datos.nombre_administrador,
            apellido=datos.apellido_administrador,
            correo=datos.correo_administrador,
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
    )


def _crear_sede_inicial(sesion: Session, institucion_id: str) -> Sede:
    """Crea la sede inicial "Sede Central" del tenant recien aprovisionado.

    Es bootstrap de datos organizacionales (spec 011 D-5), **no** CRUD de sedes:
    sin la Feature 012 un tenant sin sedes no podria operar, asi que el alta
    siembra "Sede Central" para dejarlo operativo antes de declarar su version.
    La sede pertenece a la institucion del tenant (`institucion_id` no nulo).
    """
    sede = Sede(nombre=NOMBRE_SEDE_CENTRAL, institucion_id=institucion_id)
    sesion.add(sede)
    sesion.flush()
    return sede


def _inicializar_capacidades(db: Session, institucion_id: str) -> None:
    """Crea las seis capacidades habilitadas de una institucion (AC-5).

    El catalogo de capacidades es de control (Feature 012): cada institucion
    nace con sus seis filas `funcion_institucion(habilitada=True)`. Los tenants
    nunca reciben esta estructura.
    """
    for funcion in sorted(CAPACIDADES):
        db.add(
            FuncionInstitucion(
                institucion_id=institucion_id,
                funcion=funcion,
                habilitada=True,
            )
        )


def _provisionar_tenant_logico(
    db: Session,
    datos: InstitucionAltaControlCrear,
    *,
    estado_invitacion: str,
    invitacion_id: str | None,
    expira_en,
) -> None:
    """Aprovisiona en el **contexto logico unico** (suite SQLite, AC-16).

    Control y tenant comparten tablas, asi que el mismo `db` recibe la
    institucion canonica (con `rut`, `direccion` y `activo`), el
    departamento/rol/usuario Administrador, las seis capacidades, el mapa y la
    version. No se crean namespaces: SQLite no los simula (D-10).
    """
    db.add(
        InstitucionControl(
            institucion_id=datos.institucion_id,
            nombre=datos.nombre,
            rut=datos.rut,
            direccion=datos.direccion,
        )
    )
    db.flush()
    _inicializar_capacidades(db, datos.institucion_id)
    db.add(
        MapaUsuarioEsquema(
            correo=security.normalizar_correo(datos.correo_administrador),
            institucion_id=datos.institucion_id,
            nombre_esquema=_nombre_esquema(datos.institucion_id),
            activo=True,
            estado_invitacion=estado_invitacion,
            invitacion_id=invitacion_id,
            invitacion_expira_en=expira_en,
        )
    )
    db.flush()
    _crear_administrador(db, datos, institucion_id=datos.institucion_id)
    _crear_sede_inicial(db, datos.institucion_id)
    db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))


def _provisionar_tenant_postgres(
    db: Session,
    datos: InstitucionAltaControlCrear,
    nombre_esquema: str,
    *,
    estado_invitacion: str,
    invitacion_id: str | None,
    expira_en,
) -> None:
    """Aprovisiona el esquema tenant real (PostgreSQL) y el registro de control.

    Crea el esquema, su DDL canonical (las 17 tablas del tenant, incluida
    `version_esquema`; el mapa y el registro de motivos/constancias son solo de
    control), la institucion espejo, los catalogos replicados y el usuario
    Administrador inicial, y deja el tenant en la version objetivo al final. El
    registro canonico de institucion y el mapa quedan en el esquema de control
    (`db`).
    """
    # Import local: `tenant_service` importa este modulo.
    from app.db import database
    from sqlalchemy.schema import CreateSchema

    motor = db.get_bind()
    with motor.begin() as conexion:
        conexion.execute(CreateSchema(nombre_esquema))

    tablas_tenant = tablas_metadata_tenant()
    motor_tenant = motor.execution_options(
        schema_translate_map={None: nombre_esquema}
    )
    Base.metadata.create_all(bind=motor_tenant, tables=tablas_tenant)

    sesion_tenant = database.crear_sesion_esquema(nombre_esquema, motor=motor)
    try:
        # Espejo tenant: exactamente dos columnas (`institucion_id`, `nombre`).
        # El canonico (con `rut`/`direccion`/`activo`) vive solo en control.
        sesion_tenant.add(
            Institucion(
                institucion_id=datos.institucion_id,
                nombre=datos.nombre,
            )
        )
        sesion_tenant.flush()
        for nombre, descripcion in _ROLES_TENANT:
            sesion_tenant.add(Rol(nombre_rol=nombre, descripcion=descripcion))
        from app.models.ticket import EstadoTicket, Prioridad

        for nombre, descripcion in _PRIORIDADES_TENANT:
            sesion_tenant.add(Prioridad(nombre=nombre, descripcion=descripcion))
        for nombre, descripcion in _ESTADOS_TICKET_TENANT:
            sesion_tenant.add(EstadoTicket(nombre=nombre, descripcion=descripcion))
        sesion_tenant.flush()
        _crear_administrador(
            sesion_tenant, datos, institucion_id=datos.institucion_id
        )
        sesion_tenant.flush()
        _crear_sede_inicial(sesion_tenant, datos.institucion_id)
        sesion_tenant.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        sesion_tenant.commit()
    except Exception:
        sesion_tenant.rollback()
        raise
    finally:
        sesion_tenant.close()

    db.add(
        InstitucionControl(
            institucion_id=datos.institucion_id,
            nombre=datos.nombre,
            rut=datos.rut,
            direccion=datos.direccion,
        )
    )
    db.flush()
    _inicializar_capacidades(db, datos.institucion_id)
    db.add(
        MapaUsuarioEsquema(
            correo=security.normalizar_correo(datos.correo_administrador),
            institucion_id=datos.institucion_id,
            nombre_esquema=nombre_esquema,
            activo=True,
            estado_invitacion=estado_invitacion,
            invitacion_id=invitacion_id,
            invitacion_expira_en=expira_en,
        )
    )


def _nombre_esquema(institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _estado_identidad_aprovisionamiento(
    correo: str,
    verificar_correo: Callable[[str], bool],
    consultar_identidad: Callable | None,
) -> security.EstadoIdentidadClerk:
    if consultar_identidad is not None:
        try:
            return consultar_identidad(correo)
        except security.ErrorInvitacionConflicto as exc:
            raise ErrorConflictoAprovisionamiento(str(exc)) from exc
        except security.ErrorClerkNoDisponible as exc:
            raise ErrorClerkNoDisponible(str(exc)) from exc
        except security.ErrorAutenticacion as exc:
            raise ErrorClerkNoDisponible(
                "no fue posible verificar el correo contra Clerk"
            ) from exc
    try:
        existe = verificar_correo(correo)
    except security.ErrorAutenticacion as exc:
        raise ErrorClerkNoDisponible(
            "no fue posible verificar el correo contra Clerk"
        ) from exc
    return security.EstadoIdentidadClerk(
        identidad_existente=bool(existe),
        invitacion_pendiente=False,
        invitacion_id=None,
    )


def _compensar_invitacion_aprovisionamiento(
    db: Session,
    *,
    invitacion: security.InvitacionCreada | None,
    correo: str,
    institucion_id: str,
    revocar_invitacion_fn: Callable[[str], None] | None,
) -> None:
    """Revoca la invitacion del primer Administrador o deja constancia (D-2)."""
    if invitacion is None:
        return
    try:
        if revocar_invitacion_fn is None:
            raise RuntimeError("revocador no disponible")
        revocar_invitacion_fn(invitacion.invitacion_id)
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
            from app.services import motivo_service

            motivo_service.registrar_compensacion_invitacion(
                db,
                actor_correo="sistema",
                institucion_id=institucion_id,
                correo_objetivo=correo,
                invitacion_id=invitacion.invitacion_id,
                resultado_revocacion=f"revocacion_fallida: {type(exc).__name__}",
            )
        except Exception:  # noqa: BLE001
            db.rollback()


def _esquema_tenant_existente(db: Session, nombre_esquema: str) -> bool:
    """True si el esquema determinista del tenant ya existe (PostgreSQL)."""
    from sqlalchemy import inspect

    try:
        return inspect(db.get_bind()).has_schema(nombre_esquema)
    except Exception:  # noqa: BLE001 - sin metadatos el alta no puede continuar
        return False


def _validar_tenant_parcial(
    db: Session, datos: InstitucionAltaControlCrear, nombre_esquema: str
) -> None:
    """Valida que el esquema existente sea el resto del alta de esta institucion.

    El alta institucional tiene dos confirmaciones (D-2): si el commit de
    tenant se aplico y el de control no, el reintento debe completar solo la
    etapa de control. Antes de reutilizar el esquema se exige que contenga el
    espejo institucional, exactamente la version objetivo y el usuario
    Administrador inicial normalizado; cualquier otro contenido responde 503
    recuperable y nunca se declara operativo.
    """
    from app.db import database

    sesion = database.crear_sesion_esquema(nombre_esquema, motor=db.get_bind())
    try:
        try:
            espejo = sesion.get(Institucion, datos.institucion_id)
            if espejo is None or espejo.nombre != datos.nombre:
                raise ErrorAltaParcialIncompatible(
                    "el esquema existente no corresponde a esta institucion; "
                    "requiere reconciliacion"
                )
            versiones = sesion.execute(select(VersionEsquema.version)).scalars().all()
            if versiones != [VERSION_ESQUEMA_OBJETIVO]:
                raise ErrorAltaParcialIncompatible(
                    "el esquema existente no esta en la version objetivo; "
                    "requiere reconciliacion"
                )
            usuarios = (
                sesion.execute(
                    select(Usuario).where(
                        func.lower(func.trim(Usuario.correo))
                        == security.normalizar_correo(datos.correo_administrador)
                    )
                )
                .scalars()
                .all()
            )
            if len(usuarios) != 1:
                raise ErrorAltaParcialIncompatible(
                    "el esquema existente no tiene un unico Administrador inicial "
                    "compatible; requiere reconciliacion"
                )
            rol = sesion.get(Rol, usuarios[0].rol_id)
            if rol is None or rol.nombre_rol != "Administrador":
                raise ErrorAltaParcialIncompatible(
                    "el usuario inicial del esquema existente no es Administrador; "
                    "requiere reconciliacion"
                )
        except ErrorAltaParcialIncompatible:
            raise
        except Exception as exc:  # noqa: BLE001 - resto ilegible = incompatible
            raise ErrorAltaParcialIncompatible(
                "el esquema existente esta incompleto o es ilegible; requiere "
                "reconciliacion"
            ) from exc
    finally:
        sesion.close()


def _completar_alta_institucional_control(
    db: Session,
    datos: InstitucionAltaControlCrear,
    nombre_esquema: str,
    *,
    verificar_correo: Callable[[str], bool],
    consultar_identidad: Callable | None,
) -> InstitucionAltaControlRespuesta:
    """Completa la etapa de control de un alta cuyo tenant ya se confirmo (D-2).

    No crea esquema, usuario ni invitacion: **solo** recupera el estado Clerk
    (lectura) para conservar `invitacion_id` cuando exista y confirma en control
    la institucion, las capacidades y el mapa. Nunca reemite la URL.
    """
    correo = security.normalizar_correo(str(datos.correo_administrador))
    estado = _estado_identidad_aprovisionamiento(
        correo, verificar_correo, consultar_identidad
    )
    if estado.identidad_existente:
        estado_invitacion, invitacion_id = "aceptada", None
    elif estado.invitacion_pendiente:
        estado_invitacion, invitacion_id = "pendiente", estado.invitacion_id
    else:
        estado_invitacion, invitacion_id = "pendiente", None

    try:
        db.add(
            InstitucionControl(
                institucion_id=datos.institucion_id,
                nombre=datos.nombre,
                rut=datos.rut,
                direccion=datos.direccion,
            )
        )
        db.flush()
        _inicializar_capacidades(db, datos.institucion_id)
        db.add(
            MapaUsuarioEsquema(
                correo=correo,
                institucion_id=datos.institucion_id,
                nombre_esquema=nombre_esquema,
                activo=True,
                estado_invitacion=estado_invitacion,
                invitacion_id=invitacion_id,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorConflictoAprovisionamiento(
            "otra solicitud completo el alta de la institucion mientras se "
            "reintentaba"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - se responde 503 recuperable
        db.rollback()
        raise ErrorClerkNoDisponible(
            "el alta no se completo; requiere reconciliacion"
        ) from exc

    return InstitucionAltaControlRespuesta(
        institucion_id=datos.institucion_id,
        nombre=datos.nombre,
        correo_administrador=correo,
        nombre_esquema=nombre_esquema,
        version_esquema=VERSION_ESQUEMA_OBJETIVO,
        estado=ESTADO_OPERATIVA,
        mensaje=(
            "Institucion aprovisionada: reintento completo el registro de control "
            "sin duplicar tenant, usuario ni invitacion"
        ),
        url_invitacion=None,
    )


def aprovisionar_institucion(
    db: Session,
    datos: InstitucionAltaControlCrear,
    verificar_correo: Callable[[str], bool],
    *,
    consultar_identidad: Callable | None = None,
    crear_invitacion_fn: Callable | None = None,
    revocar_invitacion_fn: Callable[[str], None] | None = None,
) -> InstitucionAltaControlRespuesta:
    """Da de alta una institucion y su primer Administrador (D-7/AC-3).

    Flujo (Feature 017): normalizar el correo, validar duplicados antes de
    invitar, clasificar la identidad en Clerk (identidad existente ->
    `aceptada`; invitacion pendiente -> reutilizarla; ninguna -> crear
    invitacion), crear el tenant con su mapa y confirmar. Si falla la creacion
    local se intenta revocar la invitacion; si la revocacion falla se deja una
    constancia con `invitacion_id` (nunca URL). La institucion solo se informa
    operativa cuando el flujo completo se confirmo.
    """
    correo = security.normalizar_correo(str(datos.correo_administrador))
    datos = datos.model_copy(update={"correo_administrador": correo})

    # D-2/C-B: alta institucional parcialmente confirmada. Si el tenant ya existe
    # y control no tiene institucion/mapa, el reintento completa solo control sin
    # recrear esquema, usuario ni invitacion (ni responder 503 permanente).
    nombre_esquema = _nombre_esquema(datos.institucion_id)
    es_postgres = db.get_bind().dialect.name == "postgresql"
    if es_postgres and _esquema_tenant_existente(db, nombre_esquema):
        if (
            db.get(InstitucionControl, datos.institucion_id) is not None
            or _mapa_por_correo(db, correo) is not None
        ):
            raise ErrorConflictoAprovisionamiento(
                "la institucion o el correo ya estan registrados"
            )
        _validar_tenant_parcial(db, datos, nombre_esquema)
        return _completar_alta_institucional_control(
            db,
            datos,
            nombre_esquema,
            verificar_correo=verificar_correo,
            consultar_identidad=consultar_identidad,
        )

    # D-2: todas las validaciones locales (duplicados, colisiones, identidad de
    # control) preceden a cualquier llamada externa que cree una invitacion.
    _reservar_control(db, datos, nombre_esquema)

    estado = _estado_identidad_aprovisionamiento(
        correo, verificar_correo, consultar_identidad
    )
    estado_invitacion, invitacion_id, expira_en = "aceptada", None, None
    invitacion = None
    if not estado.identidad_existente:
        if estado.invitacion_pendiente:
            estado_invitacion = "pendiente"
            invitacion_id = estado.invitacion_id
        else:
            if crear_invitacion_fn is None:
                raise ErrorClerkNoDisponible(
                    "la frontera de invitaciones no esta configurada"
                )
            try:
                invitacion = crear_invitacion_fn(correo, ignore_existing=False)
            except security.ErrorInvitacionConflicto as exc:
                raise ErrorConflictoAprovisionamiento(str(exc)) from exc
            except security.ErrorClerkNoDisponible as exc:
                raise ErrorClerkNoDisponible(str(exc)) from exc
            estado_invitacion = "pendiente"
            invitacion_id = invitacion.invitacion_id
            expira_en = invitacion.expira_en

    es_postgres = db.get_bind().dialect.name == "postgresql"
    try:
        if es_postgres:
            _provisionar_tenant_postgres(
                db,
                datos,
                nombre_esquema,
                estado_invitacion=estado_invitacion,
                invitacion_id=invitacion_id,
                expira_en=expira_en,
            )
        else:
            _provisionar_tenant_logico(
                db,
                datos,
                estado_invitacion=estado_invitacion,
                invitacion_id=invitacion_id,
                expira_en=expira_en,
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _compensar_invitacion_aprovisionamiento(
            db,
            invitacion=invitacion,
            correo=correo,
            institucion_id=datos.institucion_id,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
        raise ErrorConflictoAprovisionamiento(
            "conflicto al crear el tenant: el alta no aplico ningun cambio"
        ) from exc
    except Exception as exc:
        db.rollback()
        _compensar_invitacion_aprovisionamiento(
            db,
            invitacion=invitacion,
            correo=correo,
            institucion_id=datos.institucion_id,
            revocar_invitacion_fn=revocar_invitacion_fn,
        )
        raise ErrorClerkNoDisponible(
            "el alta no se completo; requiere reconciliacion"
        ) from exc

    return InstitucionAltaControlRespuesta(
        institucion_id=datos.institucion_id,
        nombre=datos.nombre,
        correo_administrador=correo,
        nombre_esquema=nombre_esquema,
        version_esquema=VERSION_ESQUEMA_OBJETIVO,
        estado=ESTADO_OPERATIVA,
        mensaje="Institucion aprovisionada y tenant operativo",
        url_invitacion=None if invitacion is None else invitacion.url,
    )


# ---------------------------------------------------------------------------
# Gestion administrativa del registro institucional (T6, AC-1…AC-5)
# ---------------------------------------------------------------------------


def _mapa_de_institucion(
    db: Session, institucion_id: str
) -> MapaUsuarioEsquema | None:
    """Primera fila del mapa `correo -> esquema` de la institucion, o `None`.

    Da el `nombre_esquema` derivado de la institucion (informativo) y permite
    localizar el tenant para sincronizar el espejo (D-1).
    """
    return (
        db.execute(
            select(MapaUsuarioEsquema)
            .where(MapaUsuarioEsquema.institucion_id == institucion_id)
            .order_by(MapaUsuarioEsquema.correo)
        )
        .scalars()
        .first()
    )


def _respuesta_institucion(
    db: Session, institucion: InstitucionControl
) -> InstitucionControlRespuesta:
    """Read model del registro canonico con su `nombre_esquema` derivado."""
    mapa = _mapa_de_institucion(db, institucion.institucion_id)
    return InstitucionControlRespuesta(
        institucion_id=institucion.institucion_id,
        nombre=institucion.nombre,
        rut=institucion.rut,
        direccion=institucion.direccion,
        activo=institucion.activo,
        nombre_esquema=mapa.nombre_esquema if mapa is not None else None,
    )


def listar_instituciones(db: Session) -> list[InstitucionControlRespuesta]:
    """Lista todo el registro institucional canonico de control (orden estable)."""
    instituciones = (
        db.execute(
            select(InstitucionControl).order_by(InstitucionControl.institucion_id)
        )
        .scalars()
        .all()
    )
    return [_respuesta_institucion(db, institucion) for institucion in instituciones]


def obtener_institucion(db: Session, institucion_id: str) -> InstitucionControlRespuesta:
    """Devuelve una institucion canonica por id, o 404 si no existe."""
    institucion = db.get(InstitucionControl, institucion_id)
    if institucion is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")
    return _respuesta_institucion(db, institucion)


def _sincronizar_espejo(db: Session, institucion_id: str, nombre: str) -> None:
    """Refleja `institucion_id` + `nombre` en el espejo tenant si el tenant existe.

    En PostgreSQL el espejo vive en el esquema del tenant, asi que se abre una
    sesion ligada a ese esquema (D-1: solo la pareja `institucion_id` + `nombre`
    se sincroniza; `rut`/`direccion`/`activo` permanecen solo en control). En el
    contexto logico unico (SQLite) el espejo y el canonico comparten tabla: la
    actualizacion del canonico ya refleja el nombre, de modo que solo se ajusta
    la fila del espejo si existe.
    """
    if db.get_bind().dialect.name != "postgresql":
        espejo = db.get(Institucion, institucion_id)
        if espejo is not None:
            espejo.nombre = nombre
        return

    mapa = _mapa_de_institucion(db, institucion_id)
    if mapa is None:
        return
    from app.db import database

    sesion = database.crear_sesion_esquema(mapa.nombre_esquema, motor=db.get_bind())
    try:
        espejo = sesion.get(Institucion, institucion_id)
        if espejo is not None:
            espejo.nombre = nombre
            sesion.commit()
    finally:
        sesion.close()


def editar_institucion(
    db: Session, institucion_id: str, datos: InstitucionEdicion
) -> InstitucionControlRespuesta:
    """Modifica los atributos canonicos y sincroniza el espejo (D-1, AC-1).

    `nombre`, `rut` y `direccion` son canonicos: se persisten en control. Solo
    `nombre` (junto con `institucion_id`) se refleja en el espejo tenant; un
    atributo que no forme parte de esa pareja no se copia ni causa rechazo.
    """
    institucion = db.get(InstitucionControl, institucion_id)
    if institucion is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")

    institucion.nombre = datos.nombre
    institucion.rut = datos.rut
    institucion.direccion = datos.direccion
    db.flush()
    _sincronizar_espejo(db, institucion_id, datos.nombre)
    db.commit()
    return _respuesta_institucion(db, institucion)


def cambiar_estado_institucion(
    db: Session, institucion_id: str, activo: bool
) -> InstitucionEstadoRespuesta:
    """Activa o desactiva logicamente una institucion (idempotente, D-2/AC-2).

    No borra la fila, el tenant, los mapas, los datos ni el historial; solo
    persiste el estado de ciclo de vida en `control.institucion.activo`.
    """
    institucion = db.get(InstitucionControl, institucion_id)
    if institucion is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")
    institucion.activo = activo
    db.commit()
    return InstitucionEstadoRespuesta(institucion_id=institucion_id, activo=activo)


def listar_capacidades(db: Session, institucion_id: str) -> list[CapacidadRespuesta]:
    """Devuelve las seis capacidades de la institucion con su estado persistido.

    Una capacidad sin fila explicita se publica **habilitada** (diseno-tecnico
    §2: la ausencia no es una desactivacion). Institucion inexistente -> 404.
    """
    if db.get(InstitucionControl, institucion_id) is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")
    filas = {
        fila.funcion: fila.habilitada
        for fila in db.execute(
            select(FuncionInstitucion).where(
                FuncionInstitucion.institucion_id == institucion_id
            )
        )
        .scalars()
        .all()
    }
    return [
        CapacidadRespuesta(funcion=funcion, habilitada=filas.get(funcion, True))
        for funcion in sorted(CAPACIDADES)
    ]


def actualizar_capacidad(
    db: Session, institucion_id: str, funcion: str, habilitada: bool
) -> CapacidadRespuesta:
    """Habilita/deshabilita una capacidad funcional de la institucion (AC-5).

    Una funcion fuera del conjunto cerrado responde 422 sin mutacion; una
    institucion inexistente, 404. La operacion es idempotente y no elimina datos.
    """
    if funcion not in CAPACIDADES:
        raise ErrorFuncionInvalida("la funcion no es una capacidad funcional valida")
    if db.get(InstitucionControl, institucion_id) is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")

    fila = db.execute(
        select(FuncionInstitucion).where(
            FuncionInstitucion.institucion_id == institucion_id,
            FuncionInstitucion.funcion == funcion,
        )
    ).scalar_one_or_none()
    if fila is None:
        db.add(
            FuncionInstitucion(
                institucion_id=institucion_id, funcion=funcion, habilitada=habilitada
            )
        )
    else:
        fila.habilitada = habilitada
    db.commit()
    return CapacidadRespuesta(funcion=funcion, habilitada=habilitada)


# ---------------------------------------------------------------------------
# Dashboard tecnico SaaS y taxonomia unica de tenant (Feature 017, D-8/AC-13/AC-14)
# ---------------------------------------------------------------------------

#: Rol privilegiado con metrica separada; nunca se agrega a `usuarios_por_rol`.
_ROL_ADMINISTRADOR = "Administrador"


@contextmanager
def _abrir_sesion_dashboard(db: Session, nombre_esquema: str):
    """Sesion de lectura del tenant para el dashboard (derivada en servidor).

    En PostgreSQL abre una sesion con `schema_translate_map` por ejecucion, de
    modo que una institucion no ve el esquema de otra. En el contexto logico
    unico de SQLite la sesion de control ya cubre la base completa. Es una
    costura inyectable para probar las clases de D-8 en la suite SQLite.
    """
    if db.get_bind().dialect.name != "postgresql":
        yield db
        return

    from app.db import database

    sesion = database.crear_sesion_esquema(nombre_esquema, motor=db.get_bind())
    try:
        yield sesion
    finally:
        sesion.close()


def _version_persistida_tenant(
    sesion: Session, institucion_id: str
) -> str | None:
    """Version del tenant: exactamente una fila; ausente/duplicada es ilegible.

    `institucion_id` no se usa en PostgreSQL (cada sesion ya esta ligada a su
    esquema), pero forma parte de la costura para poder representar versiones
    distintas por institucion en el contexto logico de SQLite.
    """
    versiones = sesion.execute(select(VersionEsquema.version)).scalars().all()
    return versiones[0] if len(versiones) == 1 else None


def _instituciones_canonicas(db: Session) -> list[InstitucionControl]:
    """Instituciones del registro, excluyendo la administrativa de control.

    La institucion administrativa (`CTRL-SAAS`) no es un tenant de negocio y no
    participa del panorama SaaS.
    """
    return list(
        db.execute(
            select(InstitucionControl)
            .where(InstitucionControl.institucion_id != INSTITUCION_ADMINISTRATIVA_ID)
            .order_by(InstitucionControl.institucion_id)
        )
        .scalars()
        .all()
    )


def _metrica_base(
    institucion: InstitucionControl,
    *,
    estado_tecnico: str,
    detalle_tecnico: str | None,
    version_persistida: str | None,
) -> dict:
    """Campos comunes del read model: nunca incluye datos de negocio."""
    return {
        "institucion_id": institucion.institucion_id,
        "nombre": institucion.nombre,
        "activo": institucion.activo,
        "estado_tecnico": estado_tecnico,
        "detalle_tecnico": detalle_tecnico,
        "version_objetivo": VERSION_ESQUEMA_OBJETIVO,
        "version_persistida": version_persistida,
    }


def _contar_metricas_tenant(
    db_control: Session, sesion: Session, institucion_id: str
) -> dict[str, object]:
    """Conteos tecnicos de un tenant operativo (D-8).

    Solo asociaciones locales **activas** cuentan por rol. Los Administradores
    se separan en activos/inactivos; el rol privilegiado no se duplica en
    `usuarios_por_rol`. Los conteos no tocan tickets, catalogo, stock ni
    movimientos.
    """
    sedes = sesion.execute(
        select(func.count())
        .select_from(Sede)
        .where(Sede.institucion_id == institucion_id)
    ).scalar_one()
    departamentos = sesion.execute(
        select(func.count())
        .select_from(Departamento)
        .where(Departamento.institucion_id == institucion_id)
    ).scalar_one()

    filas = sesion.execute(
        select(Usuario.correo, Rol.nombre_rol)
        .select_from(Usuario)
        .join(Departamento, Usuario.departamento_id == Departamento.departamento_id)
        .join(Rol, Usuario.rol_id == Rol.rol_id)
        .where(Departamento.institucion_id == institucion_id)
    ).all()

    from app.services import usuario_service

    mapas = usuario_service._mapas_locales(
        db_control, [correo for correo, _rol in filas]
    )
    administradores_activos = 0
    administradores_inactivos = 0
    usuarios_por_rol: dict[str, int] = {}
    for correo, rol_nombre in filas:
        mapa = mapas.get(security.normalizar_correo(correo))
        asociacion_valida = (
            mapa is not None and mapa.institucion_id == institucion_id
        )
        if rol_nombre == _ROL_ADMINISTRADOR:
            if asociacion_valida and mapa.activo:
                administradores_activos += 1
            elif asociacion_valida:
                administradores_inactivos += 1
        elif asociacion_valida and mapa.activo:
            usuarios_por_rol[rol_nombre] = usuarios_por_rol.get(rol_nombre, 0) + 1

    return {
        "sedes": sedes,
        "departamentos": departamentos,
        "administradores_activos": administradores_activos,
        "administradores_inactivos": administradores_inactivos,
        "usuarios_por_rol": usuarios_por_rol,
    }


def _clasificar_institucion(
    db: Session, institucion: InstitucionControl
) -> InstitucionMetricasRespuesta:
    """Clasifica una institucion antes de abrir su tenant (D-8).

    Orden: estado institucional -> resolucion de metadatos/routing -> lectura
    del tenant. Una institucion inactiva o sin tenant resoluble es
    `no enrutable` y **no se consulta**; un fallo de lectura o de version es
    `no disponible` con conteos `None` (nunca cero).
    """
    if not institucion.activo:
        return InstitucionMetricasRespuesta(
            **_metrica_base(
                institucion,
                estado_tecnico=CLASE_NO_ENRUTABLE,
                detalle_tecnico=DETALLE_INSTITUCION_INACTIVA,
                version_persistida=None,
            )
        )

    mapa = _mapa_de_institucion(db, institucion.institucion_id)
    if (
        mapa is None
        or not mapa.nombre_esquema
        or mapa.nombre_esquema == ESQUEMA_CONTROL
    ):
        return InstitucionMetricasRespuesta(
            **_metrica_base(
                institucion,
                estado_tecnico=CLASE_NO_ENRUTABLE,
                detalle_tecnico=DETALLE_TENANT_NO_RESOLUBLE,
                version_persistida=None,
            )
        )

    try:
        with _abrir_sesion_dashboard(db, mapa.nombre_esquema) as sesion:
            version = _version_persistida_tenant(sesion, institucion.institucion_id)
            if version is None:
                return InstitucionMetricasRespuesta(
                    **_metrica_base(
                        institucion,
                        estado_tecnico=CLASE_NO_DISPONIBLE,
                        detalle_tecnico=DETALLE_VERSION_AUSENTE,
                        version_persistida=None,
                    )
                )
            if not es_version_objetivo(version):
                return InstitucionMetricasRespuesta(
                    **_metrica_base(
                        institucion,
                        estado_tecnico=CLASE_NO_DISPONIBLE,
                        detalle_tecnico=DETALLE_VERSION_INCOMPATIBLE,
                        version_persistida=version,
                    )
                )
            metricas = _contar_metricas_tenant(
                db, sesion, institucion.institucion_id
            )
            return InstitucionMetricasRespuesta(
                **_metrica_base(
                    institucion,
                    estado_tecnico=CLASE_OPERATIVO,
                    detalle_tecnico=None,
                    version_persistida=version,
                ),
                **metricas,
            )
    except Exception:  # noqa: BLE001 - un tenant caido es una clase, no un fallo global
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 - nunca se enmascara la clasificacion
            pass
        return InstitucionMetricasRespuesta(
            **_metrica_base(
                institucion,
                estado_tecnico=CLASE_NO_DISPONIBLE,
                detalle_tecnico=DETALLE_TENANT_NO_DISPONIBLE,
                version_persistida=None,
            )
        )


def dashboard_saas(db: Session) -> DashboardSaaSRespuesta:
    """Panorama tecnico del Superadmin con taxonomia unica de tenant (D-8).

    Enumera las instituciones del registro sin la administrativa de control y
    clasifica cada una: `operativo` (activa, enrutable y version exacta; muestra
    conteos), `no enrutable` (inactiva o sin metadatos/routing; no se abre el
    tenant) y `no disponible` (tenant caido o version ausente/ilegible/
    incompatible). La inactiva se lista y cuenta en el total. Los agregados
    separan instituciones con conteos conocidos de las no disponibles y suman
    solo los tenants operativos. Nunca se consultan datos de negocio.
    """
    try:
        instituciones = _instituciones_canonicas(db)
    except Exception as exc:  # noqa: BLE001 - control no disponible -> 503
        raise _error_tenant(exc) from exc
    metricas = [
        _clasificar_institucion(db, institucion) for institucion in instituciones
    ]

    activas = sum(1 for institucion in instituciones if institucion.activo)
    conocidos = sum(
        1 for fila in metricas if fila.estado_tecnico == CLASE_OPERATIVO
    )
    total_administradores_activos = sum(
        fila.administradores_activos or 0
        for fila in metricas
        if fila.estado_tecnico == CLASE_OPERATIVO
    )
    total_administradores_inactivos = sum(
        fila.administradores_inactivos or 0
        for fila in metricas
        if fila.estado_tecnico == CLASE_OPERATIVO
    )
    usuarios_por_rol: dict[str, int] = {}
    for fila in metricas:
        if fila.estado_tecnico != CLASE_OPERATIVO:
            continue
        for rol_nombre, cantidad in (fila.usuarios_por_rol or {}).items():
            usuarios_por_rol[rol_nombre] = (
                usuarios_por_rol.get(rol_nombre, 0) + cantidad
            )

    return DashboardSaaSRespuesta(
        total_instituciones=len(instituciones),
        total_instituciones_activas=activas,
        total_administradores_activos=total_administradores_activos,
        total_administradores_inactivos=total_administradores_inactivos,
        usuarios_por_rol=usuarios_por_rol,
        conteos_conocidos=conocidos,
        conteos_no_disponibles=len(metricas) - conocidos,
        instituciones=metricas,
    )


# ---------------------------------------------------------------------------
# Gobierno de Administradores por institucion (Feature 017, D-10/AC-8)
# ---------------------------------------------------------------------------


def _institucion_existente(db: Session, institucion_id: str) -> InstitucionControl:
    institucion = db.get(InstitucionControl, institucion_id)
    if institucion is None:
        raise ErrorInstitucionNoEncontrada("la institucion no existe")
    return institucion


def _nombre_esquema_de_institucion(db: Session, institucion_id: str) -> str:
    mapa = _mapa_de_institucion(db, institucion_id)
    if mapa is not None:
        return mapa.nombre_esquema
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _error_tenant(exc: Exception) -> Exception:
    """Traduce un fallo de sesion/tenant a 503 sin ocultar errores de dominio.

    La taxonomia D-10 conserva 404/403/409/422; solo los fallos de apertura,
    lectura o escritura del tenant (SQLAlchemy/conexion) se normalizan a
    `ErrorTenantNoDisponible` -> **503** documentado (C-E).
    """
    from fastapi import HTTPException

    if isinstance(
        exc,
        (
            ErrorInstitucionNoEncontrada,
            ErrorAdministradorNoEncontrado,
            ErrorRolAdministradorInvalido,
            ErrorTenantNoDisponible,
            HTTPException,
        ),
    ):
        return exc
    return ErrorTenantNoDisponible(
        "La sesion del tenant no esta disponible; reintente la operacion"
    )



@contextmanager
def _sesion_tenant_derivada(db: Session, institucion_id: str):
    """Abre la sesion tenant desde el registro de control, nunca desde el cliente.

    En PostgreSQL se usa `schema_translate_map` por ejecucion; en el contexto
    logico unico de SQLite la sesion de control ya es la base completa.
    """
    nombre_esquema = _nombre_esquema_de_institucion(db, institucion_id)
    if db.get_bind().dialect.name != "postgresql":
        yield db
        return

    from app.db import database

    sesion = database.crear_sesion_esquema(nombre_esquema, motor=db.get_bind())
    try:
        yield sesion
    finally:
        sesion.close()


def _administrador_de_institucion(
    db: Session, sesion_tenant: Session, institucion_id: str, usuario_id: int
):
    from app.services import ambito_service

    usuario = sesion_tenant.get(Usuario, usuario_id)
    if usuario is None:
        raise ErrorAdministradorNoEncontrado("el Administrador no existe")
    if ambito_service.institucion_de_usuario(sesion_tenant, usuario) != institucion_id:
        raise ErrorAdministradorNoEncontrado("el Administrador no existe")
    rol = sesion_tenant.get(Rol, usuario.rol_id)
    if rol is None or rol.nombre_rol != "Administrador":
        raise ErrorAdministradorNoEncontrado(
            "el usuario no es Administrador de la institucion"
        )
    return usuario


def listar_administradores_control(
    db: Session, institucion_id: str
) -> list[AdministradorListadoControlRespuesta]:
    """Listado minimo de Administradores de una institucion (AC-5/AC-8).

    Solo asociaciones locales cuyo rol es `Administrador`; publica los cinco
    campos acordados (ids/nombre/correo/estado local/estado de invitacion) y
    **nunca** consulta Clerk ni expone URL.
    """
    from app.services import usuario_service

    _institucion_existente(db, institucion_id)
    try:
        with _sesion_tenant_derivada(db, institucion_id) as sesion_tenant:
            usuarios = (
                sesion_tenant.execute(
                    select(Usuario)
                    .join(Rol, Rol.rol_id == Usuario.rol_id)
                    .join(
                        Departamento,
                        Usuario.departamento_id == Departamento.departamento_id,
                    )
                    .where(
                        Rol.nombre_rol == "Administrador",
                        Departamento.institucion_id == institucion_id,
                    )
                    .order_by(Usuario.usuario_id)
                )
                .scalars()
                .all()
            )
            mapas = usuario_service._mapas_locales(
                db, [usuario.correo for usuario in usuarios]
            )
            resultado = []
            for usuario in usuarios:
                clave = security.normalizar_correo(usuario.correo)
                mapa = mapas.get(clave)
                resultado.append(
                    AdministradorListadoControlRespuesta(
                        usuario_id=usuario.usuario_id,
                        nombre=usuario.nombre,
                        apellido=usuario.apellido,
                        correo=usuario.correo,
                        activo=True if mapa is None else mapa.activo,
                        estado_invitacion=usuario_service.estado_invitacion_efectivo(
                            mapa
                        ),
                    )
                )
            return resultado
    except Exception as exc:  # noqa: BLE001 - se normaliza a 503 documentado
        raise _error_tenant(exc) from exc


def crear_administrador_control(
    db: Session,
    institucion_id: str,
    datos,
    identidad,
    *,
    consultar_identidad=None,
    crear_invitacion_fn=None,
    revocar_invitacion_fn=None,
):
    """Alta de un Administrador institucional desde control (D-10).

    Valida la institucion en control, deriva el esquema en servidor y exige que
    el rol destino sea `Administrador`. La orquestacion de invitacion y
    compensacion es la misma del alta tenant (`usuario_service.crear_usuario`).
    """
    from app.services import usuario_service

    _institucion_existente(db, institucion_id)
    try:
        with _sesion_tenant_derivada(db, institucion_id) as sesion_tenant:
            rol = sesion_tenant.get(Rol, datos.rol_id)
            if rol is None or rol.nombre_rol != "Administrador":
                raise ErrorRolAdministradorInvalido(
                    "la gestion de control solo permite el rol Administrador"
                )
            usuario = usuario_service.crear_usuario(
                sesion_tenant,
                datos,
                identidad,
                db_control=db,
                consultar_identidad=consultar_identidad,
                crear_invitacion_fn=crear_invitacion_fn,
                revocar_invitacion_fn=revocar_invitacion_fn,
                institucion_id=institucion_id,
            )
            sesion_tenant.refresh(usuario)
            sesion_tenant.expunge(usuario)
            return usuario
    except Exception as exc:  # noqa: BLE001 - se normaliza a 503 documentado
        raise _error_tenant(exc) from exc


def editar_administrador_control(
    db: Session,
    institucion_id: str,
    usuario_id: int,
    datos,
    identidad,
):
    """Edicion motivada de un Administrador de la institucion (D-7/D-10)."""
    from app.services import organizacion_service

    _institucion_existente(db, institucion_id)
    try:
        with _sesion_tenant_derivada(db, institucion_id) as sesion_tenant:
            usuario = _administrador_de_institucion(
                db, sesion_tenant, institucion_id, usuario_id
            )
            resultado = organizacion_service.editar_usuario(
                sesion_tenant,
                usuario_id,
                datos,
                identidad,
                db_control=db,
                institucion_id=institucion_id,
            )
            _proyectar_mapa(resultado, db)
            sesion_tenant.refresh(resultado)
            sesion_tenant.expunge(resultado)
            return resultado
    except Exception as exc:  # noqa: BLE001 - se normaliza a 503 documentado
        raise _error_tenant(exc) from exc


def cambiar_estado_administrador_control(
    db: Session,
    institucion_id: str,
    usuario_id: int,
    datos,
    identidad,
):
    """Baja/reactivacion motivada de un Administrador (D-7/D-10/AC-12)."""
    from app.services import organizacion_service

    _institucion_existente(db, institucion_id)
    try:
        with _sesion_tenant_derivada(db, institucion_id) as sesion_tenant:
            usuario = _administrador_de_institucion(
                db, sesion_tenant, institucion_id, usuario_id
            )
            mapa = organizacion_service.cambiar_estado_usuario(
                sesion_tenant,
                db,
                usuario_id,
                datos.activo,
                identidad,
                motivo=getattr(datos, "motivo", None),
                idempotencia=getattr(datos, "idempotencia", None),
                institucion_id=institucion_id,
            )
            _proyectar_mapa(usuario, db)
            sesion_tenant.refresh(usuario)
            sesion_tenant.expunge(usuario)
            return usuario, mapa
    except Exception as exc:  # noqa: BLE001 - se normaliza a 503 documentado
        raise _error_tenant(exc) from exc


def reenviar_invitacion_administrador_control(
    db: Session,
    institucion_id: str,
    usuario_id: int,
    *,
    consultar_identidad=None,
    crear_invitacion_fn,
    revocar_invitacion_fn=None,
    actor_correo: str = "sistema",
):
    """Reenvia la invitacion de un Administrador creando una nueva (D-4)."""
    from app.services import usuario_service

    _institucion_existente(db, institucion_id)
    try:
        with _sesion_tenant_derivada(db, institucion_id) as sesion_tenant:
            usuario = _administrador_de_institucion(
                db, sesion_tenant, institucion_id, usuario_id
            )
            resultado = usuario_service.reenviar_invitacion(
                sesion_tenant,
                db,
                usuario,
                consultar_identidad=consultar_identidad,
                crear_invitacion_fn=crear_invitacion_fn,
                revocar_invitacion_fn=revocar_invitacion_fn,
                actor_correo=actor_correo,
            )
            sesion_tenant.refresh(resultado)
            sesion_tenant.expunge(resultado)
            return resultado
    except Exception as exc:  # noqa: BLE001 - se normaliza a 503 documentado
        raise _error_tenant(exc) from exc


def _proyectar_mapa(usuario, db: Session) -> None:
    """Carga la proyeccion del mapa en el usuario de respuesta (sin URL)."""
    from app.services import usuario_service

    mapa = usuario_service._mapa_por_correo(db, usuario.correo)
    usuario.activo = True if mapa is None else mapa.activo
    usuario.estado_invitacion = usuario_service.estado_invitacion_efectivo(mapa)
