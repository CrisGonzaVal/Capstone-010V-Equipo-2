from sqlalchemy import (
    TIMESTAMP,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# Feature 008 (D-2): `inventario.institucion_id` se **deriva del departamento** y
# lo puebla el servicio (T5-T7); no es un ambito independiente. Es el ancla de las
# claves compuestas que obligan a que el departamento y el producto del inventario
# compartan institucion (AC-2, AC-4). T9 endurecio la columna a `nullable=False`
# para igualar el DDL de instalacion nueva (`database/01_esquema.sql`) y la
# migracion `98_`; las fixtures de prueba pueblan la institucion de forma coherente
# (via el servicio o sembrando el arbol institucional completo). Las relaciones se
# fijan a los ids simples para no depender del orden de las claves compuestas.


class Inventario(Base):
    __tablename__ = "inventario"
    __table_args__ = (
        # Ambas FK comparten `institucion_id`: como es unica por fila, obligan a
        # que el departamento y el producto del inventario pertenezcan a la misma
        # institucion; no hay via para un inventario con producto ajeno
        # (AC-2, AC-4). Sustituyen a las FK simples previas.
        ForeignKeyConstraint(
            ["institucion_id", "departamento_id"],
            ["departamento.institucion_id", "departamento.departamento_id"],
            name="inventario_departamento_institucion_fk",
        ),
        ForeignKeyConstraint(
            ["institucion_id", "producto_id"],
            ["producto.institucion_id", "producto.producto_id"],
            name="inventario_producto_institucion_fk",
        ),
        UniqueConstraint(
            "departamento_id",
            "producto_id",
            name="inventario_producto_departamento_uk",
        ),
    )

    inventario_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    stock_actual = Column(Integer, nullable=False, default=0)
    ubicacion = Column(String(100))
    departamento_id = Column(Integer, nullable=False)
    producto_id = Column(Integer, nullable=False)
    institucion_id = Column(
        String(20), ForeignKey("institucion.institucion_id"), nullable=False
    )

    departamento = relationship(
        "Departamento",
        back_populates="inventarios",
        primaryjoin="Inventario.departamento_id == Departamento.departamento_id",
        foreign_keys="Inventario.departamento_id",
    )
    producto = relationship(
        "Producto",
        back_populates="inventarios",
        primaryjoin="Inventario.producto_id == Producto.producto_id",
        foreign_keys="Inventario.producto_id",
    )
    movimientos = relationship("MovimientoInventario", back_populates="inventario")


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"

    movimiento_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tipo_movimiento = Column(String(20), nullable=False)
    cantidad = Column(Integer, nullable=False)
    fecha_movimiento = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    observacion = Column(String(250))
    #: Referencia **historica** al inventario departamental legado. Se conserva con
    #: su FK y sus valores intactos en las filas existentes; deja de ser obligatoria
    #: porque los movimientos **nuevos** de la Feature 011 se enlazan por
    #: `stock_sede_id` y dejan esta columna nula (spec D-2 y §7; seccion aprobada
    #: de `stack.md` "Evolucion del modelo organizacional e inventario por sede").
    inventario_id = Column(Integer, ForeignKey("inventario.inventario_id"), nullable=True)
    #: Referencia de auditoria de los movimientos **nuevos** (Feature 011, spec
    #: D-2): los movimientos de negocio y de consolidacion apuntan al stock por
    #: sede. La exclusividad entre ambas referencias (exactamente un destino segun
    #: la clase de movimiento) la expresa el contrato del servicio, no un `CHECK`,
    #: para no bloquear la migracion ni los registros legados.
    stock_sede_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stock_sede.stock_sede_id"), nullable=True
    )

    inventario = relationship("Inventario", back_populates="movimientos")
    stock_sede = relationship(
        "StockSede",
        back_populates="movimientos",
        primaryjoin="MovimientoInventario.stock_sede_id == StockSede.stock_sede_id",
        foreign_keys="MovimientoInventario.stock_sede_id",
    )
