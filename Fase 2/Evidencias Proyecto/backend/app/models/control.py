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
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)

from app.db.database import Base


class MapaUsuarioEsquema(Base):
    """Mapa global `correo -> esquema` del esquema de control (stack §4)."""

    __tablename__ = "mapa_usuario_esquema"

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
