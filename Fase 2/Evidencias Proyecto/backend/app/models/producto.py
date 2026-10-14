from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base

# Feature 008 (D-1): el catalogo deja de ser global. `institucion_id` ancla cada
# categoria/producto a una institucion y participa de las claves compuestas que
# el esquema usa para rechazar referencias cruzadas (AC-2, AC-4). La PK simple se
# conserva: los identificadores publicos no cambian (stack.md §"Modelo relacional
# y particionamiento por institucion").
#
# Las columnas institucionales son `nullable=True` **en el modelo ORM** a
# proposito durante esta tarea: en T2 los servicios aun no las pueblan (lo hacen
# T5-T7) y la suite SQLite debe seguir verde. El DDL de instalacion nueva
# (`database/01_esquema.sql`) las declara `NOT NULL`, que es la autoridad para
# datos reales. Las relaciones ORM se fijan al id simple (`primaryjoin`) para que
# sigan resolviendo filas antiguas sin institucion.


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = (
        # Destino de la FK compuesta `producto -> categoria` (AC-2).
        UniqueConstraint(
            "institucion_id", "categoria_id", name="categoria_institucion_uk"
        ),
    )

    categoria_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_cat = Column(String(100), nullable=False)
    descripcion_cat = Column(String(200))
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"))

    productos = relationship(
        "Producto",
        back_populates="categoria",
        primaryjoin="Categoria.categoria_id == Producto.categoria_id",
        foreign_keys="Producto.categoria_id",
    )


class Producto(Base):
    __tablename__ = "producto"
    __table_args__ = (
        # Sustituye a la FK simple `producto.categoria_id -> categoria`: ahora el
        # producto solo puede apuntar a una categoria de su misma institucion
        # (AC-2). La relacion ORM se fija a `categoria_id` para seguir resolviendo
        # filas sin institucion.
        ForeignKeyConstraint(
            ["institucion_id", "categoria_id"],
            ["categoria.institucion_id", "categoria.categoria_id"],
            name="producto_categoria_institucion_fk",
        ),
        # Destino de las FK compuestas `inventario -> producto` y
        # `detalle_ticket -> producto` (AC-2, AC-4).
        UniqueConstraint(
            "institucion_id", "producto_id", name="producto_institucion_uk"
        ),
    )

    producto_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(250))
    unidad_medida = Column(String(30))
    stock_minimo = Column(Integer, nullable=False, default=0)
    categoria_id = Column(Integer, nullable=False)
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"))

    categoria = relationship(
        "Categoria",
        back_populates="productos",
        primaryjoin="Producto.categoria_id == Categoria.categoria_id",
        foreign_keys="Producto.categoria_id",
    )
    inventarios = relationship(
        "Inventario",
        back_populates="producto",
        primaryjoin="Producto.producto_id == Inventario.producto_id",
        foreign_keys="Inventario.producto_id",
    )
    detalles = relationship(
        "DetalleTicket",
        back_populates="producto",
        primaryjoin="Producto.producto_id == DetalleTicket.producto_id",
        foreign_keys="DetalleTicket.producto_id",
    )
