from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Institucion(Base):
    """Espejo tenant del registro institucional (Feature 012, D-1).

    Se limita **exactamente** a `institucion_id` + `nombre`: es la fila que cada
    esquema tenant materializa. El registro canonico (con `rut`, `direccion` y el
    estado de ciclo de vida `activo`) vive solo en control y lo mapea
    `InstitucionControl` (`app/models/control_canonico.py`). Este modelo es
    compartido por la sesion de control y las sesiones tenant; por eso **no**
    puede exponer `activo` (el `create_all` del tenant lo impondria en todos los
    esquemas y violaria el espejo de dos columnas).
    """

    __tablename__ = "institucion"

    institucion_id = Column(String(20), primary_key=True)
    nombre = Column(String(150), nullable=False)

    departamentos = relationship("Departamento", back_populates="institucion")


class Departamento(Base):
    __tablename__ = "departamento"
    __table_args__ = (
        # Destino de la FK compuesta `inventario -> departamento` (Feature 008,
        # AC-2/AC-4): obliga a que el inventario y su departamento compartan
        # institucion. La PK simple se conserva.
        UniqueConstraint(
            "institucion_id", "departamento_id", name="departamento_institucion_uk"
        ),
    )

    departamento_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_dep = Column(String(100), nullable=False)
    descripcion = Column(String(200))
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"), nullable=False)
    #: Sede del departamento (Feature 011, spec D-5). Nullable: la obligatoriedad
    #: es operativa (sin sede se rechazan las operaciones dependientes), no una
    #: restriccion de base; asi se puede desplegar por fases y migrar los datos
    #: legados sin romper las filas existentes.
    sede_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sede.sede_id"), nullable=True
    )
    #: Estado logico del departamento (Feature 012, AC-11). `True` = vigente;
    #: `False` = desactivado sin borrado fisico ni perdida de historial. La
    #: desactivacion se rechaza (409) si deja dependencias activas incompatibles.
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    institucion = relationship("Institucion", back_populates="departamentos")
    usuarios = relationship("Usuario", back_populates="departamento")
    inventarios = relationship("Inventario", back_populates="departamento")
    sede = relationship(
        "Sede",
        primaryjoin="Departamento.sede_id == Sede.sede_id",
        foreign_keys="Departamento.sede_id",
    )
