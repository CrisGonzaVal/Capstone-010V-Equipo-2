"""Modelos auxiliares del contexto de persistencia de control (Feature 010).

No son una de las doce entidades 3NF: existen para resolver la identidad local
antes de abrir la sesion de negocio y para versionar el DDL por tenant. Su
justificacion aprobada vive en `docs/spec/stack.md`
§"Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)".

* `MapaUsuarioEsquema` (estructura de **control**): traduce el correo primario
  verificado a un esquema tenant. `correo` es la clave de la identidad local
  (un correo no apunta a dos esquemas); `nombre_esquema` **no** lleva unicidad de
  base porque el mapa guarda una fila por usuario y dos usuarios de la misma
  institucion comparten su esquema. La invariante "dos instituciones no comparten
  esquema" se garantiza por derivacion en servidor (nombre determinista a partir
  del ID de institucion, nunca input del cliente), no por una restriccion de
  unicidad. `institucion_id` mantiene una FK **local** al registro de
  `institucion` del mismo esquema logico; nunca hay FK cross-schema.
* `VersionEsquema` (estructura **por tenant**): exactamente una fila vigente con
  la version de DDL aplicada. El enrutamiento exige igualdad exacta contra
  `VERSION_ESQUEMA_OBJETIVO`; ausente/diferente/duplicada deniega en cerrado.

Ambos modelos se declaran **sin esquema fijo** (`schema=None`): el esquema
efectivo lo selecciona `schema_translate_map` por ejecucion (nunca
`search_path`), por lo que el mismo modelo logico sirve al esquema de control,
a cada tenant y al contexto logico unico de la suite SQLite. Esta tarea T4 crea
las estructuras; la resolucion de sesion (T5) y los servicios (T7/T8) las
operan.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)

from app.db.database import Base

#: Estados persistidos del ciclo de invitacion (stack.md, Feature 017). `None`
#: representa un registro legado sin proyeccion: la API lo publica como
#: `no disponible`, nunca como `aceptada`.
ESTADOS_INVITACION: frozenset[str] = frozenset(
    {"pendiente", "aceptada", "revocada", "expirada"}
)

#: Tipos de fila de la estructura auxiliar de control (D-6). Distingue una
#: justificacion administrativa de las constancias recuperables.
TIPOS_REGISTRO_MOTIVO: frozenset[str] = frozenset(
    {"justificacion", "constancia_compensacion", "constancia_motivo"}
)

_LITERALES_ESTADO_INVITACION = ", ".join(
    f"'{estado}'" for estado in sorted(ESTADOS_INVITACION)
)
_LITERALES_TIPO_REGISTRO = ", ".join(
    f"'{tipo}'" for tipo in sorted(TIPOS_REGISTRO_MOTIVO)
)


class MapaUsuarioEsquema(Base):
    """Mapa global `correo -> esquema` del esquema de control (stack §4).

    Desde la Feature 017 conserva ademas la **proyeccion persistida** del ciclo
    de invitacion (`estado_invitacion`, `invitacion_id` y sus timestamps). Es
    estado de control: no se replica a ningun esquema tenant. Una fila legada sin
    `estado_invitacion` se publica como `no disponible`; nunca se interpreta como
    `aceptada`. La asociacion local (`activo`) sigue siendo un indicador separado.
    """

    __tablename__ = "mapa_usuario_esquema"
    __table_args__ = (
        CheckConstraint(
            "estado_invitacion IS NULL "
            f"OR estado_invitacion IN ({_LITERALES_ESTADO_INVITACION})",
            name="mapa_usuario_esquema_estado_invitacion_ck",
        ),
    )

    #: Correo primario verificado de la identidad local. Un correo no puede
    #: apuntar a mas de un esquema: es la clave de la resolucion.
    correo = Column(String(150), primary_key=True)

    #: ID canonico de institucion, con FK **local** al `institucion` del mismo
    #: esquema (control). Sin FK cross-schema.
    institucion_id = Column(
        String(20),
        ForeignKey("institucion.institucion_id"),
        nullable=False,
    )

    #: Nombre PostgreSQL del esquema tenant, generado/validado en servidor.
    #: No lleva unicidad de base: el mapa tiene una fila por usuario, asi que dos
    #: usuarios de la misma institucion comparten `nombre_esquema`. La invariante
    #: "dos instituciones no comparten esquema" se garantiza por derivacion en
    #: servidor (el nombre es determinista a partir del ID de institucion y nunca
    #: es input del cliente), no por una restriccion de unicidad.
    nombre_esquema = Column(String(63), nullable=False)

    #: Solo las asociaciones activas resuelven solicitudes.
    activo = Column(Boolean, nullable=False, default=True)

    #: Proyeccion persistida del ciclo de invitacion (Feature 017). Nula en filas
    #: legadas; nunca se le asigna un valor por defecto que afirme aceptacion.
    estado_invitacion = Column(String(20), nullable=True)

    #: Identificador de la invitacion en Clerk. Sirve para localizar/revocar la
    #: invitacion huerfana; el enlace (URL) nunca se persiste.
    invitacion_id = Column(String(100), nullable=True)

    #: Instante de expiracion entregado por Clerk. `expirada` se deriva de aqui.
    invitacion_expira_en = Column(DateTime, nullable=True)

    #: Instante en que el primer login verificado confirmo la aceptacion.
    invitacion_aceptada_en = Column(DateTime, nullable=True)


class RegistroMotivoConstancia(Base):
    """Evidencia recuperable de mutaciones y compensaciones (Feature 017, D-6).

    Estructura **solo de control**: no es una entidad de dominio ni se replica a
    los esquemas tenant. Una fila es una justificacion administrativa o una
    constancia de fallo (compensacion de invitacion o persistencia del motivo).
    `clave_idempotente` es unica: el reintento reutiliza la misma clave y completa
    la evidencia sin duplicarla. Nunca se persiste la URL de la invitacion; solo
    `invitacion_id`, localizable manualmente en el dashboard de Clerk.
    """

    __tablename__ = "registro_motivo_constancia"
    __table_args__ = (
        CheckConstraint(
            f"tipo_registro IN ({_LITERALES_TIPO_REGISTRO})",
            name="registro_motivo_constancia_tipo_ck",
        ),
    )

    registro_id = Column(Integer, primary_key=True, autoincrement=True)

    #: `justificacion`, `constancia_compensacion` o `constancia_motivo`.
    tipo_registro = Column(String(30), nullable=False)

    #: Identidad del actor que ejecuto la operacion (correo normalizado).
    actor_correo = Column(String(150), nullable=False)

    #: ID local del usuario objetivo cuando exista; sin FK cross-schema.
    usuario_objetivo_id = Column(Integer, nullable=True)

    #: Correo normalizado del objetivo cuando no hay fila local (compensacion).
    correo_objetivo = Column(String(150), nullable=True)

    #: Institucion afectada. FK local al canonico de control.
    institucion_id = Column(
        String(20),
        ForeignKey("institucion.institucion_id"),
        nullable=False,
    )

    #: Operacion auditada (p. ej. `edicion_usuario`, `baja_usuario`,
    #: `compensacion_invitacion_fallida`).
    accion = Column(String(50), nullable=False)

    #: Codigo del catalogo D-5 (solo justificaciones).
    codigo_motivo = Column(String(50), nullable=True)

    #: Texto explicativo de hasta 500 caracteres (obligatorio para `otro`).
    texto_motivo = Column(String(500), nullable=True)

    fecha_registro = Column(DateTime, nullable=False, server_default=func.now())

    #: Identificador idempotente de la operacion; unico para no duplicar evidencia.
    clave_idempotente = Column(String(100), nullable=False, unique=True)

    #: Invitacion Clerk involucrada en una constancia de compensacion.
    invitacion_id = Column(String(100), nullable=True)

    #: Resultado del intento de revocacion. Nunca contiene el enlace.
    resultado_revocacion = Column(String(500), nullable=True)


class VersionEsquema(Base):
    """Version de estructura de un esquema tenant (stack §5).

    Exactamente una fila vigente por esquema; su marca es el checkpoint de
    idempotencia de bootstrap y aprovisionamiento.
    """

    __tablename__ = "version_esquema"

    version_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    #: Token de version objetivo del DDL (`VERSION_ESQUEMA_OBJETIVO`). No nula.
    version = Column(String(20), nullable=False)

    #: Instante del ultimo registro exitoso.
    actualizada_en = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
