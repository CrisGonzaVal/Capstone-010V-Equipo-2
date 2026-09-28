from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, CheckConstraint, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

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

class Rol(Base):
    __tablename__ = "rol"

    rol_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_rol = Column(String(50), nullable=False)
    descripcion = Column(String(150))

    usuarios = relationship("Usuario", back_populates="rol")

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
    detalles_ticket = relationship("DetalleTicket", back_populates="producto")

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

class Prioridad(Base):
    __tablename__ = "prioridad"

    prioridad_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(30), nullable=False)
    descripcion = Column(String(100))

    tickets = relationship("Ticket", back_populates="prioridad")

class EstadoTicket(Base):
    __tablename__ = "estado_ticket"

    estado_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(30), nullable=False)
    descripcion = Column(String(100))

    tickets = relationship("Ticket", back_populates="estado")

class Ticket(Base):
    __tablename__ = "ticket"

    ticket_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    usuario_id = Column(Integer, ForeignKey("usuario.usuario_id"), nullable=False)
    prioridad_id = Column(Integer, ForeignKey("prioridad.prioridad_id"), nullable=False)
    estado_id = Column(Integer, ForeignKey("estado_ticket.estado_id"), nullable=False)
    asunto = Column(String(150), nullable=False)
    descripcion = Column(String(500))
    fecha_creacion = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    fecha_cierre = Column(TIMESTAMP)

    usuario = relationship("Usuario", back_populates="tickets")
    prioridad = relationship("Prioridad", back_populates="tickets")
    estado = relationship("EstadoTicket", back_populates="tickets")
    detalles = relationship("DetalleTicket", back_populates="ticket")

class DetalleTicket(Base):
    __tablename__ = "detalle_ticket"

    detalle_ticket_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("producto.producto_id"), nullable=False)
    cantidad_solicitada = Column(Integer, nullable=False)
    cantidad_entregada = Column(Integer, nullable=False, default=0)

    ticket = relationship("Ticket", back_populates="detalles")
    producto = relationship("Producto", back_populates="detalles")
