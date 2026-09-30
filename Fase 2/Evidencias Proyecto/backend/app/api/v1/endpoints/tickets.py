from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.ticket_schema import (
    TicketActualizarEstado,
    TicketCrear,
    TicketRespuesta,
)
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["Tickets y Solicitudes"])


@router.get("/", response_model=List[TicketRespuesta], summary="Listar tickets")
def listar_tickets(estado_id: int = None, db: Session = Depends(dependencies.get_db)):
    return ticket_service.listar_tickets(db, estado_id)


@router.post(
    "/",
    response_model=TicketRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear ticket con sus detalles",
)
def crear_ticket(datos: TicketCrear, db: Session = Depends(dependencies.get_db)):
    return ticket_service.crear_ticket(db, datos)


@router.patch(
    "/{ticket_id}/estado",
    response_model=TicketRespuesta,
    summary="Actualizar el estado de un ticket",
)
def actualizar_estado_ticket(
    ticket_id: int,
    datos: TicketActualizarEstado,
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.actualizar_estado_ticket(db, ticket_id, datos.estado_id)
