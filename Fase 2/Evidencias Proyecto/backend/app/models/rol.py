from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class Rol(Base):
    __tablename__ = "rol"

    rol_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_rol = Column(String(50), nullable=False)
    descripcion = Column(String(150))

    usuarios = relationship("Usuario", back_populates="rol")
