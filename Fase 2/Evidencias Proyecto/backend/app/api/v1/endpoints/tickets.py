from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from app.core.database import get_db
from app.models.models import Ticket, DetalleTicket, Inventario
from app.schemas.schemas import TicketCreate, TicketResponse, TicketUpdateEstado

router = APIRouter(prefix="/tickets", tags=["Tickets y Solicitudes"])

@router.get("/", response_model=List[TicketResponse])
def listar_tickets(estado_id: int = None, db: Session = Depends(get_db)):
    query = db.query(Ticket)
    if estado_id:
        query = query.filter(Ticket.estado_id == estado_id)
    return query.all()

@router.post("/", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def crear_ticket(ticket_data: TicketCreate, db: Session = Depends(get_db)):
    # Extraer detalles
    detalles_data = ticket_data.detalles
    ticket_dict = ticket_data.model_dump(exclude={"detalles"})
    
    nuevo_ticket = Ticket(**ticket_dict)
    db.add(nuevo_ticket)
    db.commit()
    db.refresh(nuevo_ticket)
    
    for detalle in detalles_data:
        db_detalle = DetalleTicket(
            ticket_id=nuevo_ticket.ticket_id,
            producto_id=detalle.producto_id,
            cantidad_solicitada=detalle.cantidad_solicitada,
            cantidad_entregada=0
        )
        db.add(db_detalle)
    
    db.commit()
    db.refresh(nuevo_ticket)
    return nuevo_ticket

@router.patch("/{ticket_id}/estado", response_model=TicketResponse)
def actualizar_estado_ticket(ticket_id: int, estado_update: TicketUpdateEstado, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    
    ticket.estado_id = estado_update.estado_id
    if estado_update.estado_id == 4:  # Asumiendo ID 4 = Cerrado / Entregado
        ticket.fecha_cierre = datetime.utcnow()
        
    db.commit()
    db.refresh(ticket)
    return ticket
