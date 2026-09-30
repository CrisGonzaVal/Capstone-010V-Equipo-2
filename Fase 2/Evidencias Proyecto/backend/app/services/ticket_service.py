from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import DetalleTicket, Ticket
from app.schemas.ticket_schema import TicketCrear

# Estado que sella la fecha de cierre del ticket.
# Ver nota en tasks.md: el script de inicializacion no define los ids de
# estado_ticket (solo DDL, sin INSERT), asi que este 4 no tiene referente
# canonico. Sustituir por una busqueda por nombre en Feature 004/005.
ESTADO_CERRADO_ID = 4


def listar_tickets(db: Session, estado_id: Optional[int] = None) -> List[Ticket]:
    consulta = db.query(Ticket)
    if estado_id:
        consulta = consulta.filter(Ticket.estado_id == estado_id)
    return consulta.all()


def crear_ticket(db: Session, datos: TicketCrear) -> Ticket:
    """Persiste el ticket y sus detalles en una sola transaccion ACID.

    Antes este flujo hacia dos `commit()`: el ticket quedaba persistido aunque
    fallara el alta de algun detalle, dejando un ticket huerfano. Ver
    `constitucion.md` §3 (Consistencia Transaccional).
    """
    nuevo_ticket = Ticket(**datos.model_dump(exclude={"detalles"}))
    db.add(nuevo_ticket)
    db.flush()  # asigna ticket_id sin cerrar la transaccion

    for detalle in datos.detalles:
        db.add(
            DetalleTicket(
                ticket_id=nuevo_ticket.ticket_id,
                producto_id=detalle.producto_id,
                cantidad_solicitada=detalle.cantidad_solicitada,
                cantidad_entregada=0,
            )
        )

    db.commit()
    db.refresh(nuevo_ticket)
    return nuevo_ticket


def actualizar_estado_ticket(db: Session, ticket_id: int, estado_id: int) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    ticket.estado_id = estado_id
    if estado_id == ESTADO_CERRADO_ID:
        ticket.fecha_cierre = datetime.utcnow()

    db.commit()
    db.refresh(ticket)
    return ticket
