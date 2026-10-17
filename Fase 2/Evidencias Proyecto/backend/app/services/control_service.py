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

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base
from app.models.control import MapaUsuarioEsquema, VersionEsquema
from app.models.institucion import Departamento, Institucion
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.schemas.control_schema import (
    ESTADO_OPERATIVA,
    InstitucionAltaControlCrear,
    InstitucionAltaControlRespuesta,
)

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


class ErrorConflictoAprovisionamiento(ErrorAprovisionamiento):
    """Institucion/correo/esquema ya tomado o fallo de etapa -> HTTP 409."""


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


def _institucion_administrativa(db: Session) -> Institucion:
    """Institucion administrativa de control, reutilizandola si ya existe."""
    institucion = db.get(Institucion, INSTITUCION_ADMINISTRATIVA_ID)
    if institucion is None:
        institucion = Institucion(
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
        db.execute(select(Usuario.usuario_id).where(Usuario.correo == correo))
        .scalar_one_or_none()
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
    if db.get(Institucion, datos.institucion_id) is not None:
        raise ErrorConflictoAprovisionamiento("la institucion ya esta registrada")
    if _mapa_por_correo(db, datos.correo_administrador) is not None:
        raise ErrorConflictoAprovisionamiento("el correo ya esta asociado a un esquema")
    if _mapa_por_nombre_esquema(db, nombre_esquema) is not None:
        raise ErrorConflictoAprovisionamiento("el nombre de esquema ya esta en uso")
    if _es_correo_usuario_local(db, datos.correo_administrador):
        raise ErrorConflictoAprovisionamiento("el correo ya es un usuario local")


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


def _provisionar_tenant_logico(
    db: Session, datos: InstitucionAltaControlCrear
) -> None:
    """Aprovisiona en el **contexto logico unico** (suite SQLite, AC-16).

    Control y tenant comparten tablas, asi que el mismo `db` recibe la
    institucion, el departamento/rol/usuario Administrador, el mapa y la version.
    No se crean namespaces: SQLite no los simula (D-10).
    """
    db.add(
        Institucion(
            institucion_id=datos.institucion_id,
            nombre=datos.nombre,
            rut=datos.rut,
            direccion=datos.direccion,
        )
    )
    db.flush()
    db.add(
        MapaUsuarioEsquema(
            correo=datos.correo_administrador,
            institucion_id=datos.institucion_id,
            nombre_esquema=_nombre_esquema(datos.institucion_id),
            activo=True,
        )
    )
    db.flush()
    _crear_administrador(db, datos, institucion_id=datos.institucion_id)
    db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))


def _provisionar_tenant_postgres(
    db: Session, datos: InstitucionAltaControlCrear, nombre_esquema: str
) -> None:
    """Aprovisiona el esquema tenant real (PostgreSQL) y el registro de control.

    Crea el esquema, su DDL canonical (las 12 entidades 3NF mas
    `version_esquema`; el mapa es solo de control), la institucion espejo, los
    catalogos replicados y el usuario Administrador inicial, y deja el tenant en
    la version objetivo al final. El registro canonico de institucion y el mapa
    quedan en el esquema de control (`db`).
    """
    # Import local: `tenant_service` importa este modulo.
    from app.db import database
    from sqlalchemy.schema import CreateSchema

    motor = db.get_bind()
    with motor.begin() as conexion:
        conexion.execute(CreateSchema(nombre_esquema))

    tabla_mapa = Base.metadata.tables[MapaUsuarioEsquema.__tablename__]
    tablas_tenant = [
        tabla
        for tabla in Base.metadata.sorted_tables
        if tabla is not tabla_mapa
    ]
    motor_tenant = motor.execution_options(
        schema_translate_map={None: nombre_esquema}
    )
    Base.metadata.create_all(bind=motor_tenant, tables=tablas_tenant)

    sesion_tenant = database.crear_sesion_esquema(nombre_esquema, motor=motor)
    try:
        sesion_tenant.add(
            Institucion(
                institucion_id=datos.institucion_id,
                nombre=datos.nombre,
                rut=datos.rut,
                direccion=datos.direccion,
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
        sesion_tenant.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        sesion_tenant.commit()
    except Exception:
        sesion_tenant.rollback()
        raise
    finally:
        sesion_tenant.close()

    db.add(
        Institucion(
            institucion_id=datos.institucion_id,
            nombre=datos.nombre,
            rut=datos.rut,
            direccion=datos.direccion,
        )
    )
    db.flush()
    db.add(
        MapaUsuarioEsquema(
            correo=datos.correo_administrador,
            institucion_id=datos.institucion_id,
            nombre_esquema=nombre_esquema,
            activo=True,
        )
    )


def _nombre_esquema(institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def aprovisionar_institucion(
    db: Session,
    datos: InstitucionAltaControlCrear,
    verificar_correo: Callable[[str], bool],
) -> InstitucionAltaControlRespuesta:
    """Da de alta una institucion y su primer Administrador (D-7, AC-7…AC-9).

    Flujo: (1) verifica que el correo del Administrador exista en Clerk antes de
    crear recursos; (2) calcula el nombre de esquema determinista en servidor;
    (3) rechaza duplicados/colisiones; (4) crea el tenant con su estructura,
    catalogos, usuario inicial, mapa y version objetivo; (5) confirma. Un fallo
    de cualquier etapa compensa (rollback) sin dejar tenant parcial y un reintento
    no duplica ni sobrescribe.
    """
    correo = datos.correo_administrador

    try:
        existe = verificar_correo(correo)
    except security.ErrorAutenticacion as exc:
        raise ErrorClerkNoDisponible(
            "no fue posible verificar el correo contra Clerk"
        ) from exc
    if not existe:
        raise ErrorCorreoInexistente(
            "el correo del Administrador no existe en Clerk"
        )

    nombre_esquema = _nombre_esquema(datos.institucion_id)
    _reservar_control(db, datos, nombre_esquema)

    es_postgres = db.get_bind().dialect.name == "postgresql"
    try:
        if es_postgres:
            _provisionar_tenant_postgres(db, datos, nombre_esquema)
        else:
            _provisionar_tenant_logico(db, datos)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorConflictoAprovisionamiento(
            "conflicto al crear el tenant: el alta no aplico ningun cambio"
        ) from exc
    except Exception:
        db.rollback()
        raise

    return InstitucionAltaControlRespuesta(
        institucion_id=datos.institucion_id,
        nombre=datos.nombre,
        correo_administrador=correo,
        nombre_esquema=nombre_esquema,
        version_esquema=VERSION_ESQUEMA_OBJETIVO,
        estado=ESTADO_OPERATIVA,
        mensaje="Institucion aprovisionada y tenant operativo",
    )
