from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Usuario(Base):
    __tablename__ = "usuario"

    usuario_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    correo = Column(String(150), nullable=False, unique=True, index=True)
    departamento_id = Column(Integer, ForeignKey("departamento.departamento_id"), nullable=False)
    rol_id = Column(Integer, ForeignKey("rol.rol_id"), nullable=False)
    #: Sede asignada al Bodeguero (Feature 011, spec D-5/D-7). Nullable: la
    #: obligatoriedad es operativa, y un usuario que no es Bodeguero no necesita
    #: sede. La gestiona el Administrador institucional por API (Feature 011) y la
    #: administracion completa de usuarios sigue en la Feature 012.
    sede_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sede.sede_id"), nullable=True
    )

    departamento = relationship("Departamento", back_populates="usuarios")
    rol = relationship("Rol", back_populates="usuarios")
    tickets = relationship("Ticket", back_populates="usuario")
    sede = relationship(
        "Sede",
        primaryjoin="Usuario.sede_id == Sede.sede_id",
        foreign_keys="Usuario.sede_id",
    )
