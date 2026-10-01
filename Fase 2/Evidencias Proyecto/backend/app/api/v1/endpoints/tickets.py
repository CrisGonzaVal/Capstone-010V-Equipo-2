from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    TicketActualizarEstado,
    TicketCrear,
    TicketRespuesta,
)
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["Tickets y Solicitudes"])


@router.get(
    "/catalogos",
    response_model=CatalogosTicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar los catalogos del formulario de alta de ticket",
    description=(
        "Devuelve **las cuatro listas en una sola peticion**: prioridades, estados, "
        "productos y solicitantes. Se agrupan aqui, y no en cuatro endpoints, para "
        "que el modal abra con una request en vez de cuatro.\n\n"
        "`productos` trae el stock total agregado de todas las sedes y su marca "
        "`es_critico`, calculada con la misma regla que "
        "`GET /inventario/existencias` (`stock_total <= stock_minimo`). Un producto "
        "sin existencias aparece con `stock_total` en 0.\n\n"
        "El orden es determinista: prioridades y estados por su id (que es el "
        "orden del flujo), productos por nombre, solicitantes por apellido."
    ),
)
def obtener_catalogos(db: Session = Depends(dependencies.get_db)):
    return ticket_service.obtener_catalogos(db)


@router.get(
    "/",
    response_model=List[TicketRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar tickets",
    description="Devuelve los tickets con sus detalles. `estado_id` acota el resultado a un estado.",
)
def listar_tickets(estado_id: int = None, db: Session = Depends(dependencies.get_db)):
    return ticket_service.listar_tickets(db, estado_id)


@router.post(
    "/",
    response_model=TicketRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear ticket con sus detalles",
    description=(
        "Crea el ticket y sus lineas de detalle **en una sola transaccion**: si "
        "alguna falla, no queda ticket sin detalle. La escritura no valida stock "
        "ni descuenta inventario (es la peticion, no la entrega).\n\n"
        "Un `usuario_id`, `prioridad_id`, `estado_id` o `producto_id` que no "
        "exista devuelve **404** nombrando la referencia, no 500. Los errores de "
        "forma del payload (asunto de menos de 3 caracteres, `detalles` vacio, "
        "cantidad no positiva) devuelven **422**."
    ),
)
def crear_ticket(datos: TicketCrear, db: Session = Depends(dependencies.get_db)):
    return ticket_service.crear_ticket(db, datos)


@router.patch(
    "/{ticket_id}/estado",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Actualizar el estado de un ticket",
    description="Cambia el estado del ticket. Al pasar a un estado de cierre sella `fecha_cierre`.",
)
def actualizar_estado_ticket(
    ticket_id: int,
    datos: TicketActualizarEstado,
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.actualizar_estado_ticket(db, ticket_id, datos.estado_id)
