from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class Categoria(Base):
    __tablename__ = "categoria"

    categoria_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_cat = Column(String(100), nullable=False)
    descripcion_cat = Column(String(200))

    productos = relationship("Producto", back_populates="categoria")


class Producto(Base):
    __tablename__ = "producto"

    producto_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(250))
    unidad_medida = Column(String(30))
    stock_minimo = Column(Integer, nullable=False, default=0)
    categoria_id = Column(Integer, ForeignKey("categoria.categoria_id"), nullable=False)

    categoria = relationship("Categoria", back_populates="productos")
    inventarios = relationship("Inventario", back_populates="producto")
    detalles = relationship("DetalleTicket", back_populates="producto")
