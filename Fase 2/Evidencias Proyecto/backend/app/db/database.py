from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

# `engine`, `SessionLocal` y `Base` conservan el nombre canonico de SQLAlchemy
# (ver excepcion de identificadores en spec.md §4). Renombrarlos romperia la
# convencion con la que los referencia cualquier herramienta del ecosistema.
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

#: Esquema del contexto global de control (stack §1/§7). Es la unica disposicion
#: en la que vive el registro institucional canonico, el mapa `correo -> esquema`,
#: el rol Superadmin y su identidad.
ESQUEMA_CONTROL = "control"


def crear_sesion_control(motor: Engine | None = None) -> Session:
    """Sesion del contexto global de control, ligada **explicitamente** a `control`.

    La sesion de control fija su esquema con `schema_translate_map={None:
    'control'}` (nunca `search_path`), de modo que resuelve a `control` en las dos
    disposiciones reales de la base:

    * **Instalacion limpia** (`01_esquema.sql`): el DDL fija
      `ALTER DATABASE ... SET search_path TO control, public`, asi que las
      referencias sin prefijo ya resolvian a `control`; la traduccion explicita
      produce el mismo resultado (`control.tabla`).
    * **Base migrada** (`database/migraciones/001_migracion_multitenant_esquemas.sql`):
      el `search_path` por defecto **no** apunta a `control` (ese ajuste solo lo
      aplica la instalacion limpia), de modo que una sesion sin traduccion
      resolveria contra `public` y no encontraria el control. La traduccion
      explicita corrige ese caso sin depender del `search_path` de la base.

    En SQLite (suite ordinaria, AC-16) no se simulan esquemas: se devuelve una
    sesion sobre el contexto logico unico, sin traduccion de namespace.
    """
    motor_base = motor or engine
    if motor_base.dialect.name == "postgresql":
        motor_base = motor_base.execution_options(
            schema_translate_map={None: ESQUEMA_CONTROL}
        )
    return SessionLocal(bind=motor_base)


def crear_sesion_esquema(nombre_esquema: str, motor: Engine | None = None) -> Session:
    """Sesion de negocio ligada al esquema tenant, con mapa **por ejecucion**.

    El `schema_translate_map` traduce el esquema logico comun de los modelos
    (`None`) al esquema tenant resuelto en control. Se aplica a una **copia** del
    engine, de modo que el `Engine` compartido y su pool nunca quedan con estado
    de tenant: al cerrar la sesion la conexion vuelve al pool sin `search_path`
    alterado ni tenant residual (stack §6). El esquema **no** se selecciona con
    `search_path`.

    En SQLite (suite ordinaria) no se simulan esquemas: se devuelve una sesion
    sobre el contexto logico unico (AC-16), sin traduccion de namespace.
    """
    motor_base = motor or engine
    if motor_base.dialect.name == "postgresql":
        motor_base = motor_base.execution_options(
            schema_translate_map={None: nombre_esquema}
        )
    return SessionLocal(bind=motor_base)
