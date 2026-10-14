from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    TicketActualizarEstado,
    TicketCrear,
    TicketDespacho,
    TicketRespuesta,
)
from app.services import ticket_service
from app.services.auth_service import IdentidadAutenticada

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
        "Feature 008: el catalogo es institucional. `productos` lista solo los "
        "productos de la institucion del usuario y su `stock_total` agrega "
        "unicamente las existencias de los departamentos de esa institucion "
        "(ningun stock de otra institucion influye); cada producto lleva su "
        "`institucion_id`. Un producto sin existencias aparece con `stock_total` "
        "en 0 y su marca `es_critico`, calculada con la misma regla que "
        "`GET /inventario/existencias` (`stock_total <= stock_minimo`).\n\n"
        "`solicitantes` se acota por rol (Feature 007): el Solicitante solo se ve a "
        "si mismo; Administrador y Bodeguero, a los de su institucion; Superadmin, a "
        "todos con lectura global del catalogo (cada producto atribuido).\n\n"
        "El orden es determinista: prioridades y estados por su id (que es el "
        "orden del flujo), productos por nombre, solicitantes por apellido."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
)
def obtener_catalogos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/catalogos")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.obtener_catalogos(db, identidad)


@router.get(
    "/",
    response_model=List[TicketRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar tickets",
    description=(
        "Devuelve los tickets con sus detalles. `estado_id` acota el resultado a "
        "un estado. El orden es determinista: `fecha_creacion` descendente y, en "
        "empate, `ticket_id` descendente.\n\n"
        "El alcance depende del rol (Feature 007): el Solicitante recibe solo sus "
        "tickets; Administrador y Bodeguero, solo los de su institucion; Superadmin, "
        "todos."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
)
def listar_tickets(
    estado_id: int = None,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.listar_tickets(db, estado_id, identidad)


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
        "cantidad no positiva) devuelven **422**.\n\n"
        "Atribucion (Feature 007): si el rol es Solicitante, el ticket se atribuye "
        "a su identidad e ignora cualquier `usuario_id` alternativo. "
        "Administrador/Bodeguero conservan `usuario_id` obligatorio.\n\n"
        "Feature 008 (AC-11): el ticket pertenece a la institucion de su "
        "solicitante y **todos** los productos del detalle deben ser de esa misma "
        "institucion. Un solicitante de otra institucion elegido por un rol "
        "limitado o un producto ajeno devuelven **404** (ocultacion, igual que un "
        "id inexistente) y no dejan ticket ni detalle parciales."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
)
def crear_ticket(
    datos: TicketCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/tickets/")
    ),
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.crear_ticket(db, datos, identidad)


@router.post(
    "/{ticket_id}/despacho",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Despachar un ticket y rebajar su inventario",
    description=(
        "Despacha un ticket que esta en el estado `EnCurso` y lo lleva a "
        "`Cerrado`, **rebajando el stock, fijando las cantidades entregadas y "
        "registrando una salida de auditoria por detalle en una sola "
        "transaccion**. La entrega es completa: cada detalle entrega su "
        "`cantidad_solicitada`.\n\n"
        "El ticket inexistente o un `usuario_id` inexistente devuelven **404**. "
        "Un ticket de otra institucion (rol limitado) devuelve **404** sin mutar "
        "stock ni estado (Feature 007). El estado no elegible (ya despachado), el "
        "catalogo sin los nombres requeridos, un ticket sin detalles, un detalle "
        "sin producto resoluble, el inventario ausente o ambiguo, el stock "
        "insuficiente y una referencia cruzada de institucion (producto o "
        "inventario de otra institucion que la del ticket, Feature 008) devuelven "
        "**409** sin escribir nada. Un payload invalido o "
        "un `usuario_id` ausente/no entero devuelven **422**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
)
def despachar_ticket(
    ticket_id: int,
    datos: TicketDespacho,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "POST", "/api/v1/tickets/{ticket_id}/despacho"
        )
    ),
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.despachar_ticket(db, ticket_id, datos, identidad)


@router.patch(
    "/{ticket_id}/estado",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Actualizar el estado de un ticket",
    description=(
        "Cambia el estado del ticket dentro del flujo lineal del catálogo: "
        "solo se acepta **avanzar o retroceder un paso** entre estados "
        "contiguos (el orden del catálogo es el orden del flujo). Saltar "
        "estados, pedir el estado que el ticket ya tiene o salir del estado "
        "terminal (el último del catálogo) se rechazan con **409** y no "
        "modifican el ticket.\n\n"
        "Un ticket inexistente devuelve **404**; en ese orden, también **404** "
        "si el estado pedido no existe en el catálogo. Un ticket de otra "
        "institucion (rol limitado) tambien devuelve **404** sin modificar nada "
        "(Feature 007).\n\n"
        "El paso de `EnCurso` a `Cerrado` está **reservado al despacho** "
        "(Feature 005): si el ticket está en el `EnCurso` canónico y se pide "
        "el `Cerrado` canónico —ambos por nombre, con menor `estado_id` ante "
        "duplicados—, responde **409** sin modificar estado ni fecha, con el "
        "detalle exacto `El cierre requiere despacho; use POST "
        "/api/v1/tickets/{ticket_id}/despacho`.\n\n"
        "Al entrar en el estado llamado `Cerrado` —sin distinguir mayúsculas, "
        "nunca por un id fijo— se sella `fecha_cierre` en la misma operación; "
        "si ya estaba sellada, se conserva sin sobrescribirse."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
)
def actualizar_estado_ticket(
    ticket_id: int,
    datos: TicketActualizarEstado,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "PATCH", "/api/v1/tickets/{ticket_id}/estado"
        )
    ),
    db: Session = Depends(dependencies.get_db),
):
    return ticket_service.actualizar_estado_ticket(
        db, ticket_id, datos.estado_id, identidad
    )
