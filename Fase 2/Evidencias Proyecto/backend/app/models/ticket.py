from sqlalchemy import TIMESTAMP, Column, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.database import Base


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
