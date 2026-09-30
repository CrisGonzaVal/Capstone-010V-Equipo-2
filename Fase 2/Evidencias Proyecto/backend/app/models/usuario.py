from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class Usuario(Base):
    __tablename__ = "usuario"

    usuario_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    correo = Column(String(150), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)
    departamento_id = Column(Integer, ForeignKey("departamento.departamento_id"), nullable=False)
    rol_id = Column(Integer, ForeignKey("rol.rol_id"), nullable=False)

    departamento = relationship("Departamento", back_populates="usuarios")
    rol = relationship("Rol", back_populates="usuarios")
    tickets = relationship("Ticket", back_populates="usuario")
