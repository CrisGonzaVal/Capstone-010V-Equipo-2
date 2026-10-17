"""Entidades del modelo organizacional: sede y su stock por sede (Feature 011).

`Sede` y `StockSede` son las dos entidades de dominio que la Feature 011 agrega al
modelo (de doce a catorce, ver la seccion aprobada de `docs/spec/stack.md`
"Evolucion del modelo organizacional e inventario por sede"). Sustituyen la
granularidad departamental del saldo operativo: el saldo vigente vive por
`(sede, producto)` y el total institucional se **deriva** de las sedes (spec D-2).

Pertenencia y defensa en profundidad (mismo patron que la Feature 008): cada
sede pertenece a una institucion y `StockSede` lleva `institucion_id` con FKs
compuestas `(institucion_id, sede_id)` y `(institucion_id, producto_id)`, de modo
que el esquema rechaza asociar una sede con un producto de otra institucion. Las
relaciones ORM se fijan a los ids simples (`primaryjoin`) para no depender del
orden de las claves compuestas, igual que en `inventario.py`.

Las filas legadas de `inventario` y sus movimientos **no** se tocan: siguen siendo
los registros historicos inmutables de la auditoria (spec D-2, decision 10).
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Sede(Base):
    """Sede de una institucion; unidad de la bodega fisica (spec D-6).

    Cada sede pertenece a exactamente una institucion (`institucion_id` no nulo) y
    expone la clave compuesta `(institucion_id, sede_id)` que sirve de destino a la
    FK compuesta de `stock_sede`.
    """

    __tablename__ = "sede"
    __table_args__ = (
        # Destino de la FK compuesta `stock_sede -> sede`. Ancla la sede a su
        # institucion sin depender solo de los filtros del servicio.
        UniqueConstraint("institucion_id", "sede_id", name="sede_institucion_uk"),
    )

    sede_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Direccion fisica de la sede; opcional (el dato organizacional es propio de
    #: la sede y no se infiere de `inventario.ubicacion`, que queda legado).
    direccion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    institucion_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("institucion.institucion_id"), nullable=False
    )

    institucion = relationship(
        "Institucion",
        primaryjoin="Sede.institucion_id == Institucion.institucion_id",
        foreign_keys="Sede.institucion_id",
    )
    stocks = relationship(
        "StockSede",
        back_populates="sede",
        primaryjoin="Sede.sede_id == StockSede.sede_id",
        foreign_keys="StockSede.sede_id",
    )
    departamentos = relationship(
        "Departamento",
        primaryjoin="Sede.sede_id == Departamento.sede_id",
        foreign_keys="Departamento.sede_id",
        viewonly=True,
    )


class StockSede(Base):
    """Saldo vigente de un producto en una sede (spec D-2).

    Unica fuente operativa de stock: `UNIQUE (sede_id, producto_id)` y
    `CHECK (stock_actual >= 0)`. Las FKs compuestas obligan a que la sede y el
    producto pertenezcan a la institucion de la fila.
    """

    __tablename__ = "stock_sede"
    __table_args__ = (
        # Sustituyen a las FK simples: con `institucion_id` unica por fila,
        # obligan a que sede y producto sean de la misma institucion (spec AC-2).
        ForeignKeyConstraint(
            ["institucion_id", "sede_id"],
            ["sede.institucion_id", "sede.sede_id"],
            name="stock_sede_sede_institucion_fk",
        ),
        ForeignKeyConstraint(
            ["institucion_id", "producto_id"],
            ["producto.institucion_id", "producto.producto_id"],
            name="stock_sede_producto_institucion_fk",
        ),
        # Una sola fila de saldo por sede y producto.
        UniqueConstraint(
            "sede_id", "producto_id", name="stock_sede_sede_producto_uk"
        ),
        CheckConstraint("stock_actual >= 0", name="stock_sede_stock_ck"),
    )

    stock_sede_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    stock_actual: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sede_id: Mapped[int] = mapped_column(Integer, nullable=False)
    producto_id: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Institucion de la sede; la puebla el servicio y sostiene las FK compuestas.
    institucion_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("institucion.institucion_id"), nullable=False
    )

    sede = relationship(
        "Sede",
        back_populates="stocks",
        primaryjoin="StockSede.sede_id == Sede.sede_id",
        foreign_keys="StockSede.sede_id",
    )
    producto = relationship(
        "Producto",
        primaryjoin="StockSede.producto_id == Producto.producto_id",
        foreign_keys="StockSede.producto_id",
    )
    movimientos = relationship(
        "MovimientoInventario",
        back_populates="stock_sede",
        primaryjoin="StockSede.stock_sede_id == MovimientoInventario.stock_sede_id",
        foreign_keys="MovimientoInventario.stock_sede_id",
    )
