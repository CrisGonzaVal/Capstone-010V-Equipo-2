from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.producto_schema import ProductoRespuesta


class DetalleTicketCrear(BaseModel):
    producto_id: int = Field(description="Producto pedido. Debe existir en el catalogo.")
    cantidad_solicitada: int = Field(
        gt=0,
        description="Unidades pedidas. Es una peticion, no una entrega: puede exceder el stock.",
    )


class DetalleTicketRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    detalle_ticket_id: int
    producto_id: int
    cantidad_solicitada: int
    cantidad_entregada: int
    producto: Optional[ProductoRespuesta] = None


class TicketCrear(BaseModel):
    usuario_id: int = Field(description="Solicitante. Debe existir en `usuario`.")
    prioridad_id: int = Field(description="Prioridad. Debe existir en `prioridad`.")
    estado_id: int = Field(description="Estado inicial. Debe existir en `estado_ticket`.")
    asunto: str = Field(
        min_length=3,
        max_length=150,
        description="Titulo breve del requerimiento.",
    )
    descripcion: Optional[str] = Field(
        default=None, description="Justificacion del requerimiento."
    )
    detalles: List[DetalleTicketCrear] = Field(
        min_length=1,
        description="Al menos una linea de detalle. Vacio es un 422, no un ticket sin items.",
    )


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


class PrioridadRespuesta(BaseModel):
    """Proyeccion de la tabla `prioridad`, que solo tiene tres columnas."""

    model_config = ConfigDict(from_attributes=True)

    prioridad_id: int
    nombre: str
    descripcion: Optional[str] = None


class EstadoTicketRespuesta(BaseModel):
    """Proyeccion de la tabla `estado_ticket`."""

    model_config = ConfigDict(from_attributes=True)

    estado_id: int
    nombre: str
    descripcion: Optional[str] = None


class ProductoCatalogoRespuesta(BaseModel):
    """Read model de `producto` + `categoria` + stock agregado. Sin
    `from_attributes` porque `categoria_nombre` y `stock_total` no son columnas
    de la entidad: los arma `ticket_service.obtener_catalogos()`."""

    producto_id: int
    nombre: str
    unidad_medida: Optional[str] = None
    categoria_nombre: str
    stock_total: int
    es_critico: bool


class SolicitanteRespuesta(BaseModel):
    """Read model de `usuario` + `departamento`. Sin `from_attributes` porque
    `departamento_nombre` no es una columna de `usuario`."""

    usuario_id: int
    nombre: str
    apellido: str
    correo: str
    departamento_nombre: str


class CatalogosTicketRespuesta(BaseModel):
    """Las cuatro listas salen siempre, aunque esten vacias: el formulario
    distingue "no hay catalogo" de "el backend no respondio", y para eso hace
    falta la clave presente con lista vacia."""

    prioridades: List[PrioridadRespuesta]
    estados: List[EstadoTicketRespuesta]
    productos: List[ProductoCatalogoRespuesta]
    solicitantes: List[SolicitanteRespuesta]
