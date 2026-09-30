from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.producto_schema import ProductoRespuesta


class DetalleTicketCrear(BaseModel):
    producto_id: int
    cantidad_solicitada: int


class DetalleTicketRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    detalle_ticket_id: int
    producto_id: int
    cantidad_solicitada: int
    cantidad_entregada: int
    producto: Optional[ProductoRespuesta] = None


class TicketCrear(BaseModel):
    usuario_id: int
    prioridad_id: int
    estado_id: int
    asunto: str
    descripcion: Optional[str] = None
    detalles: List[DetalleTicketCrear]


class TicketActualizarEstado(BaseModel):
    estado_id: int


class TicketRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    usuario_id: int
    prioridad_id: int
    estado_id: int
    asunto: str
    descripcion: Optional[str] = None
    fecha_creacion: datetime
    fecha_cierre: Optional[datetime] = None
    detalles: List[DetalleTicketRespuesta] = []
