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


class TicketMotivo(BaseModel):
    """Payload de `POST /tickets/{ticket_id}/anulacion` y `.../rechazo`.

    Feature 013 (spec D-6, plan decision 3): `motivo` se declara **sin**
    restriccion de vacio/longitud en Pydantic. La validacion (no vacio, hasta
    `LONGITUD_MAXIMA_MOTIVO` = 500) es del servicio, que responde 422: si el
    schema rechazara el payload, el 422 se dispararia antes del handler y se
    adelantaria al 404 (ticket inexistente o fuera de alcance) y al 409
    (estado actual inadmisible) del orden 404 -> 409 -> 422 del AC-7.
    """

    motivo: str = Field(
        description=(
            "Motivo obligatorio de la anulacion o el rechazo. No puede estar "
            "vacio ni exceder los 500 caracteres (lo valida el servicio)."
        )
    )


class TicketEditar(BaseModel):
    """Payload de `PUT /tickets/{ticket_id}` (Feature 013, spec D-9).

    Equivalente al del alta, menos la autoría: no lleva `usuario_id` (el
    solicitante no cambia), ni `estado_id` (solo se edita en `Pendiente`), ni
    sede ni institucion (intactas). El **conjunto completo** de detalles
    reemplaza al previo (plan decision 7). La forma se valida aqui (422) y
    las referencias en el servicio (404), que escribe cabecera y detalles en
    una sola transaccion (AC-13…AC-15).
    """

    asunto: str = Field(
        min_length=3,
        max_length=150,
        description="Titulo breve del requerimiento.",
    )
    descripcion: Optional[str] = Field(
        default=None, description="Justificacion del requerimiento."
    )
    prioridad_id: int = Field(description="Prioridad. Debe existir en `prioridad`.")
    detalles: List[DetalleTicketCrear] = Field(
        min_length=1,
        description=(
            "Al menos una linea de detalle. El conjunto reemplaza al previo "
            "por completo; vacio es un 422."
        ),
    )


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


class TicketDetalleRespuesta(TicketRespuesta):
    """Detalle completo de `GET /api/v1/tickets/{ticket_id}` (Feature 013).

    Extiende `TicketRespuesta` (cabecera + fechas + items con su `producto`
    anidado) con los campos resueltos que la vista de detalle necesita para
    presentar el ticket sin cruzar catalogos (spec §6, D-13, AC-23): estado,
    prioridad, solicitante con su departamento, y la sede instantanea. Son
    columnas de tablas relacionadas, no de `ticket`, por lo que los puebla
    `ticket_service.obtener_ticket_detalle` y no `from_attributes`.
    """

    estado_nombre: Optional[str] = Field(
        default=None, description="Nombre canónico del estado actual del ticket."
    )
    prioridad_nombre: Optional[str] = Field(
        default=None, description="Nombre de la prioridad del ticket."
    )
    solicitante_id: Optional[int] = Field(
        default=None, description="Usuario solicitante (espejo de `usuario_id`)."
    )
    solicitante_nombre: Optional[str] = None
    solicitante_apellido: Optional[str] = None
    solicitante_correo: Optional[str] = None
    departamento_nombre: Optional[str] = Field(
        default=None, description="Departamento del solicitante."
    )
    sede_nombre: Optional[str] = Field(
        default=None,
        description=(
            "Nombre de la sede instantanea del ticket (`sede_id`); `None` en un "
            "ticket legado sin instantanea."
        ),
    )


class HistorialTransicionRespuesta(BaseModel):
    """Fila de `GET /api/v1/tickets/{ticket_id}/historial` (Feature 013).

    Read model de `historial_transicion_ticket` (spec §6, AC-9/AC-10): los
    siete campos tabulares mas los resueltos de presentación (`*_nombre`) que
    la vista de detalle usa para mostrar el historial legible —actor y
    de→a— sin cruzar catalogos. `estado_origen_id` es nulo **solo** en la fila
    de creación del ticket. La lectura es de solo escritura en el servidor y
    ordena de forma determinista (spec §6): `fecha_transicion DESC,
    historial_transicion_id DESC`.
    """

    model_config = ConfigDict(from_attributes=True)

    historial_transicion_id: int
    ticket_id: int
    estado_origen_id: Optional[int] = None
    estado_destino_id: int
    usuario_id: int
    fecha_transicion: datetime
    motivo: Optional[str] = Field(
        default=None,
        description=(
            "Motivo literal de la anulación o el rechazo; nulo en creación, "
            "cambio de estado y despacho."
        ),
    )
    estado_origen_nombre: Optional[str] = None
    estado_destino_nombre: Optional[str] = None
    usuario_nombre: Optional[str] = None
    usuario_apellido: Optional[str] = None


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
