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

# Feature 008: `ticket.institucion_id` se deriva del solicitante
# (`usuario -> departamento -> institucion`) y `detalle_ticket.institucion_id`, del
# ticket; los puebla el servicio (T5-T7). Son anclas institucionales para las
# claves compuestas, no identidad nueva: las PK simples se conservan (stack.md
# §"Modelo relacional y particionamiento por institucion"). T9 endurecio ambas
# columnas a `nullable=False` para igualar el DDL de instalacion nueva y la
# migracion `98_`; las fixtures siembran la institucion de forma coherente (el
# servicio la puebla en produccion). Las relaciones se fijan a los ids simples
# para no depender del orden de las claves compuestas.


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
    __table_args__ = (
        # Destino de la FK compuesta `detalle_ticket -> ticket` (AC-4).
        UniqueConstraint("institucion_id", "ticket_id", name="ticket_institucion_uk"),
    )

    ticket_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    usuario_id = Column(Integer, ForeignKey("usuario.usuario_id"), nullable=False)
    prioridad_id = Column(Integer, ForeignKey("prioridad.prioridad_id"), nullable=False)
    estado_id = Column(Integer, ForeignKey("estado_ticket.estado_id"), nullable=False)
    asunto = Column(String(150), nullable=False)
    descripcion = Column(String(500))
    fecha_creacion = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    fecha_cierre = Column(TIMESTAMP)
    institucion_id = Column(
        String(20), ForeignKey("institucion.institucion_id"), nullable=False
    )
    #: Instantanea de la sede del departamento al **crearse** el ticket (Feature
    #: 011, spec D-5/AC-9). El despacho rebaja esa sede aunque el departamento se
    #: reasigne despues; los tickets legados quedan en `NULL` hasta que la
    #: migracion les asigne sede de forma explicita.
    sede_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sede.sede_id"), nullable=True
    )

    usuario = relationship("Usuario", back_populates="tickets")
    prioridad = relationship("Prioridad", back_populates="tickets")
    estado = relationship("EstadoTicket", back_populates="tickets")
    sede = relationship(
        "Sede",
        primaryjoin="Ticket.sede_id == Sede.sede_id",
        foreign_keys="Ticket.sede_id",
    )
    detalles = relationship(
        "DetalleTicket",
        back_populates="ticket",
        primaryjoin="Ticket.ticket_id == DetalleTicket.ticket_id",
        foreign_keys="DetalleTicket.ticket_id",
    )


class DetalleTicket(Base):
    __tablename__ = "detalle_ticket"
    __table_args__ = (
        # El detalle queda anclado a la institucion de su ticket y obligado a un
        # producto de esa misma institucion (AC-4). Sustituyen a las FK simples.
        ForeignKeyConstraint(
            ["institucion_id", "ticket_id"],
            ["ticket.institucion_id", "ticket.ticket_id"],
            name="detalle_ticket_ticket_institucion_fk",
        ),
        ForeignKeyConstraint(
            ["institucion_id", "producto_id"],
            ["producto.institucion_id", "producto.producto_id"],
            name="detalle_ticket_producto_institucion_fk",
        ),
    )

    detalle_ticket_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ticket_id = Column(Integer, nullable=False)
    producto_id = Column(Integer, nullable=False)
    cantidad_solicitada = Column(Integer, nullable=False)
    cantidad_entregada = Column(Integer, nullable=False, default=0)
    institucion_id = Column(
        String(20), ForeignKey("institucion.institucion_id"), nullable=False
    )

    ticket = relationship(
        "Ticket",
        back_populates="detalles",
        primaryjoin="DetalleTicket.ticket_id == Ticket.ticket_id",
        foreign_keys="DetalleTicket.ticket_id",
    )
    producto = relationship(
        "Producto",
        back_populates="detalles",
        primaryjoin="DetalleTicket.producto_id == Producto.producto_id",
        foreign_keys="DetalleTicket.producto_id",
    )


class HistorialTransicionTicket(Base):
    """Historial inmutable de transiciones del ciclo de vida del ticket.

    Feature 013 (spec D-10, AC-9): una fila por transicion — creacion con
    `estado_origen_id` nulo, cambio de estado de la 004, despacho de la 005 y
    anulacion/rechazo de la 013. Cada fila se escribe en la MISMA transaccion
    que el cambio de estado que representa (constitucion.md §3, AC-11) y no se
    migra ni reconstruye para transiciones previas a la feature (AC-12). Es la
    15.ª entidad de dominio (docs/spec/stack.md §2, apartado 013).

    Es una tabla de negocio **por esquema tenant**; aqui se modela una sola
    (contexto logico unico, igual que el resto del dominio) y el DDL de
    instalacion nueva la crea en `control` por paridad estructural. No lleva
    `institucion_id`: su aislamiento es el de su esquema, con la misma defensa
    que `movimiento_inventario` (anclada por su ticket, que ya porta la
    institucion).
    """

    __tablename__ = "historial_transicion_ticket"

    historial_transicion_id = Column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    ticket_id = Column(Integer, ForeignKey("ticket.ticket_id"), nullable=False)
    #: Nulo SOLO en la fila de creacion del ticket (AC-9); toda transicion
    #: posterior declara su estado de partida.
    estado_origen_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("estado_ticket.estado_id"), nullable=True
    )
    estado_destino_id = Column(
        Integer, ForeignKey("estado_ticket.estado_id"), nullable=False
    )
    #: Actor autenticado de la transicion.
    usuario_id = Column(Integer, ForeignKey("usuario.usuario_id"), nullable=False)
    fecha_transicion = Column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    #: Escala de `ticket.descripcion` (VARCHAR(500)). Nullable: la anulacion y
    #: el rechazo lo exigen no vacio, pero esa validacion es del servicio (T7),
    #: no del esquema.
    motivo: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Las relaciones se fijan a los ids simples con `primaryjoin` explicito,
    # igual que en `Ticket`/`DetalleTicket` (Feature 008), para no depender del
    # orden de ninguna clave compuesta. Las dos FK a `estado_ticket` exigen
    # `foreign_keys` declarado en cada una.
    ticket = relationship(
        "Ticket",
        primaryjoin="HistorialTransicionTicket.ticket_id == Ticket.ticket_id",
        foreign_keys="HistorialTransicionTicket.ticket_id",
    )
    estado_origen = relationship(
        "EstadoTicket",
        primaryjoin=(
            "HistorialTransicionTicket.estado_origen_id == EstadoTicket.estado_id"
        ),
        foreign_keys="HistorialTransicionTicket.estado_origen_id",
    )
    estado_destino = relationship(
        "EstadoTicket",
        primaryjoin=(
            "HistorialTransicionTicket.estado_destino_id == EstadoTicket.estado_id"
        ),
        foreign_keys="HistorialTransicionTicket.estado_destino_id",
    )
    usuario = relationship(
        "Usuario",
        primaryjoin="HistorialTransicionTicket.usuario_id == Usuario.usuario_id",
        foreign_keys="HistorialTransicionTicket.usuario_id",
    )
