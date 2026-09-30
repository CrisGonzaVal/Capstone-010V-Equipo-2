from sqlalchemy import TIMESTAMP, Column, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class Inventario(Base):
    __tablename__ = "inventario"
    __table_args__ = (
        UniqueConstraint("departamento_id", "producto_id", name="inventario_producto_departamento_uk"),
    )

    inventario_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    stock_actual = Column(Integer, nullable=False, default=0)
    ubicacion = Column(String(100))
    departamento_id = Column(Integer, ForeignKey("departamento.departamento_id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("producto.producto_id"), nullable=False)

    departamento = relationship("Departamento", back_populates="inventarios")
    producto = relationship("Producto", back_populates="inventarios")
    movimientos = relationship("MovimientoInventario", back_populates="inventario")


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"

    movimiento_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tipo_movimiento = Column(String(20), nullable=False)
    cantidad = Column(Integer, nullable=False)
    fecha_movimiento = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    observacion = Column(String(250))
    inventario_id = Column(Integer, ForeignKey("inventario.inventario_id"), nullable=False)

    inventario = relationship("Inventario", back_populates="movimientos")
