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


class TicketDespacho(BaseModel):
    """Payload minimo de `POST /tickets/{ticket_id}/despacho`.

    La sesion Clerk y el permiso de rol se resuelven en la ruta. El actor del
    despacho viaja explicito en el cuerpo y solo se valida su existencia: no se
    persiste en `movimiento_inventario` ni se le atribuye el historial.
    """

    usuario_id: int = Field(description="Actor que despacha. Debe existir en `usuario`.")


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
    #: Instantanea de la sede del departamento al crearse el ticket (Feature 011,
    #: spec D-5/AC-9). La expone el alta y el despacho; los tickets legados sin
    #: migrar la conservan en `None`.
    sede_id: Optional[int] = None
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
    de la entidad: los arma `ticket_service.obtener_catalogos()`.

    Feature 008 (AC-8): `institucion_id` atribuye cada producto a su institucion,
    de modo que la lectura global de Superadmin no mezcle registros homonimos de
    instituciones distintas. Para un rol limitado coincide con su institucion.

    Feature 011 (D-2/D-6): `stock_total` es la suma de los saldos por sede del
    tenant (nunca del inventario departamental legado) y `es_critico` se evalua
    **por sede**: alguna sede en o bajo el minimo marca el producto.
    """

    producto_id: int
    nombre: str
    unidad_medida: Optional[str] = None
    categoria_nombre: str
    stock_total: int
    es_critico: bool
    institucion_id: Optional[str] = None


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
