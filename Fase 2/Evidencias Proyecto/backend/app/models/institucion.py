from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class Institucion(Base):
    __tablename__ = "institucion"

    institucion_id = Column(String(20), primary_key=True)
    nombre = Column(String(150), nullable=False)
    rut = Column(String(20))
    direccion = Column(String(200))

    departamentos = relationship("Departamento", back_populates="institucion")


class Departamento(Base):
    __tablename__ = "departamento"

    departamento_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_dep = Column(String(100), nullable=False)
    descripcion = Column(String(200))
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"), nullable=False)

    institucion = relationship("Institucion", back_populates="departamentos")
    usuarios = relationship("Usuario", back_populates="departamento")
    inventarios = relationship("Inventario", back_populates="departamento")
