from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# `engine`, `SessionLocal` y `Base` conservan el nombre canonico de SQLAlchemy
# (ver excepcion de identificadores en spec.md §4). Renombrarlos romperia la
# convencion con la que los referencia cualquier herramienta del ecosistema.
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
