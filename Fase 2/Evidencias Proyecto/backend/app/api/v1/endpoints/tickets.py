from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    HistorialTransicionRespuesta,
    TicketActualizarEstado,
    TicketCrear,
    TicketDetalleRespuesta,
    TicketDespacho,
    TicketEditar,
    TicketMotivo,
    TicketRespuesta,
)
from app.services import ticket_service
from app.services import global_service
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
        "unicamente las existencias de las sedes de esa institucion "
        "(ningun stock de otra institucion influye); cada producto lleva su "
        "`institucion_id`. Un producto sin existencias aparece con `stock_total` "
        "en 0 y su marca `es_critico`, calculada con la misma regla por sede que "
        "`GET /inventario/existencias`: critico si alguna sede esta en o bajo el "
        "minimo (Feature 011, D-2/D-6).\n\n"
        "`solicitantes` se acota por rol (Feature 007): el Solicitante solo se ve a "
        "si mismo; Administrador y Bodeguero, a los de su institucion. Feature 017 "
        "(D-9/AC-15): es una lectura de negocio, por lo que el Superadmin recibe "
        "**403** sin datos; su superficie es `/control/*`.\n\n"
        "El orden es determinista: prioridades y estados por su id (que es el "
        "orden del flujo), productos por nombre, solicitantes por apellido."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/tickets/catalogos"))
    ],
)
def obtener_catalogos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/catalogos")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
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
        "tickets; Administrador y Bodeguero, solo los de su institucion. "
        "Feature 017 (D-9/AC-15): el **Superadmin no tiene esta lectura** y "
        "recibe **403** sin datos."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/tickets/"))
    ],
)
def listar_tickets(
    estado_id: int = None,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: ticket_service.listar_tickets(sesion, estado_id, identidad),
    )


@router.post(
    "/",
    response_model=TicketRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear ticket con sus detalles",
    description=(
        "Crea el ticket y sus lineas de detalle **en una sola transaccion**: si "
        "alguna falla, no queda ticket sin detalle. La escritura no valida stock "
        "ni descuenta inventario (es la peticion, no la entrega).\n\n"
        "Un `prioridad_id`, `estado_id` o `producto_id` que no exista devuelve "
        "**404** nombrando la referencia, no 500. Los errores de forma del payload "
        "(asunto de menos de 3 caracteres, `detalles` vacio, cantidad no positiva) "
        "devuelven **422**.\n\n"
        "Atribucion (enmienda 22/Oct/2026 de 003/007/008): la autoria es **siempre "
        "la identidad autenticada**, sea cual sea el rol autorizado. `usuario_id` "
        "es opcional e ignorado: enviarlo (propio, ajeno o inexistente) no produce "
        "404 ni 422 ni cambia el autor.\n\n"
        "Feature 008 (AC-11): el ticket y sus detalles se anclan a la institucion "
        "de la identidad de sesion y **todos** los productos del detalle deben ser "
        "de esa misma institucion. Un producto ajeno devuelve **404** (ocultacion, "
        "igual que un id inexistente) y no deja ticket ni detalle parciales. Si el "
        "departamento de la identidad no tiene sede, el alta responde **409** sin "
        "escribir nada."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", "/api/v1/tickets/"))
    ],
)
def crear_ticket(
    datos: TicketCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/tickets/")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
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
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "POST", "/api/v1/tickets/{ticket_id}/despacho"
            )
        )
    ],
)
def despachar_ticket(
    ticket_id: int,
    datos: TicketDespacho,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "POST", "/api/v1/tickets/{ticket_id}/despacho"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
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
        "estados o pedir el estado que el ticket ya tiene se rechazan con "
        "**409** y no modifican el ticket.\n\n"
        "`Cerrado` y `Anulado` son los dos estados terminales, resueltos por "
        "su **nombre canónico** y nunca por su posición en el catálogo "
        "(Feature 013, enmienda D-4/AC-26): una petición cuyo origen sea "
        "`Anulado` responde **409** con un detalle que dirige a la operación "
        "de anulación o rechazo correspondiente, y una cuyo origen sea "
        "`Cerrado` responde **409** con un detalle que declara que el cierre "
        "es definitivo; ninguna petición puede llevar el ticket **a** "
        "`Anulado` ni **a** `Cerrado`, con el mismo detalle dirigido. Todo "
        "ello **en cualquier catálogo**, sin modificar el ticket.\n\n"
        "Un ticket inexistente devuelve **404**; en ese orden, también **404** "
        "si el estado pedido no existe en el catálogo. Un ticket de otra "
        "institucion (rol limitado) tambien devuelve **404** sin modificar nada "
        "(Feature 007).\n\n"
        "El paso de `EnCurso` a `Cerrado` está **reservado al despacho** "
        "(Feature 005): cualquier petición cuyo destino sea el `Cerrado` "
        "canónico —ambos por nombre, con menor `estado_id` ante "
        "duplicados— responde **409** sin modificar estado ni fecha, con el "
        "detalle exacto `El cierre requiere despacho; use POST "
        "/api/v1/tickets/{ticket_id}/despacho`.\n\n"
        "`fecha_cierre` ya no se sella en esta operación: los dos caminos "
        "vigentes de sellado del cierre son el alta directa (004 AC-17) y el "
        "despacho transaccional (005), y ninguno de los dos la sobrescribe."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad("PATCH", "/api/v1/tickets/{ticket_id}/estado")
        )
    ],
)
def actualizar_estado_ticket(
    ticket_id: int,
    datos: TicketActualizarEstado,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "PATCH", "/api/v1/tickets/{ticket_id}/estado"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return ticket_service.actualizar_estado_ticket(
        db, ticket_id, datos.estado_id, identidad
    )


@router.post(
    "/{ticket_id}/anulacion",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Anular un ticket con motivo",
    description=(
        "Anula un ticket que esta en `Pendiente` o `EnRevision` y lo lleva al "
        "estado terminal `Anulado`, **con su fila de historial y el motivo "
        "literal en la misma transaccion** (Feature 013, spec D-1/D-3/D-6). "
        "`fecha_cierre` queda nula y no se escribe stock ni movimiento de "
        "inventario: la anulacion no es un cierre por despacho.\n\n"
        "Actores: el dueño Solicitante y el Administrador de la institucion "
        "(matriz AC-17). El orden de respuesta es estricto (AC-7): primero "
        "**404** si el ticket no existe o esta fuera del alcance del rol "
        "(indistinguibles, ocultamiento D-8); luego **409** si el estado "
        "actual no admite la operacion (`EnCurso`, `Cerrado` o ya `Anulado`) "
        "o si el catalogo del tenant no contiene el estado `Anulado`; por "
        "ultimo **422** si el motivo falta, esta vacio o excede los 500 "
        "caracteres (lo valida el servicio). Ningun rechazo deja escritura "
        "parcial.\n\n"
        "Superadmin no opera tickets: **403** en toda escritura (AC-17)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "POST", "/api/v1/tickets/{ticket_id}/anulacion"
            )
        )
    ],
)
def anular_ticket(
    ticket_id: int,
    datos: TicketMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "POST", "/api/v1/tickets/{ticket_id}/anulacion"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return ticket_service.anular_ticket(db, ticket_id, datos.motivo, identidad)


@router.post(
    "/{ticket_id}/rechazo",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Rechazar un ticket con motivo",
    description=(
        "Rechaza un ticket en `Pendiente` o `EnRevision` llevandolo al mismo "
        "estado terminal `Anulado` que la anulacion (Feature 013, spec "
        "D-1/D-3/D-6): lo que distingue un rechazo de una anulacion es el "
        "actor y el motivo registrados en el historial, no una fila de "
        "catalogo aparte. Mismo contrato, codigos, payload y orden "
        "404 -> 409 -> 422 (AC-7) que `POST .../anulacion`.\n\n"
        "Actores: el Bodeguero y el Administrador de la institucion (matriz "
        "AC-17). Superadmin no opera tickets: **403** en toda escritura."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "POST", "/api/v1/tickets/{ticket_id}/rechazo"
            )
        )
    ],
)
def rechazar_ticket(
    ticket_id: int,
    datos: TicketMotivo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "POST", "/api/v1/tickets/{ticket_id}/rechazo"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return ticket_service.rechazar_ticket(db, ticket_id, datos.motivo, identidad)


@router.put(
    "/{ticket_id}",
    response_model=TicketRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Editar un ticket en estado Pendiente",
    description=(
        "Edita asunto, descripcion, prioridad y el **conjunto completo** de "
        "items detallados de un ticket en `Pendiente` (Feature 013, spec D-9). "
        "El payload es equivalente al del alta, menos la autoria: no lleva "
        "`usuario_id` (el solicitante no cambia) ni `estado_id`. El conjunto "
        "de detalles reemplaza al previo por completo y cabecera + detalles se "
        "escriben en **una sola transaccion** (sin items parciales). Estado, "
        "solicitante, sede e institucion quedan intactos; editar no registra "
        "fila de historial (no es una mutacion de estado).\n\n"
        "Actores: el dueño Solicitante y el Administrador de la institucion "
        "(matriz AC-17). El orden de respuesta (AC-15): **404** de ocultamiento "
        "si el ticket no existe o esta fuera del alcance; **409** si el ticket "
        "no esta en `Pendiente`; **404** nombrando la referencia ante una "
        "prioridad o un producto inexistente o ajeno a la institucion; "
        "**422** ante forma invalida (asunto, cantidad no positiva o detalles "
        "vacios). La validacion total del payload precede a la primera "
        "escritura. Superadmin y Bodeguero no editan: **403**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", "/api/v1/tickets/{ticket_id}"))
    ],
)
def editar_ticket(
    ticket_id: int,
    datos: TicketEditar,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", "/api/v1/tickets/{ticket_id}")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return ticket_service.editar_ticket(db, ticket_id, datos, identidad)


@router.get(
    "/{ticket_id}",
    response_model=TicketDetalleRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar el detalle completo de un ticket",
    description=(
        "Devuelve la cabecera del ticket (asunto, prioridad, solicitante con "
        "su departamento, sede instantanea y fechas de creacion y, si existe, "
        "de cierre), sus items con las cantidades solicitadas y entregadas y "
        "los campos resueltos de presentacion (`estado_nombre`, "
        "`prioridad_nombre`, `solicitante_*`, `departamento_nombre`, "
        "`sede_nombre`) —Feature 013, spec §6/D-13—. La vista de detalle "
        "sustituye el \"fuera de alcance\" de la 004: es la superficie desde "
        "la que se operan todas las acciones del ciclo de vida.\n\n"
        "Legible por el Solicitante (sus tickets) y por Administrador y "
        "Bodeguero (los de su institucion). Feature 017 (D-9/AC-15): el "
        "**Superadmin no tiene esta lectura** y recibe **403** sin datos. Un "
        "ticket inexistente o fuera del alcance responde **404** identico, sin "
        "revelar existencia (AC-18). Solo lectura: no concede ninguna capacidad "
        "de escritura."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad("GET", "/api/v1/tickets/{ticket_id}")
        )
    ],
)
def obtener_ticket_detalle(
    ticket_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/{ticket_id}")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.leer_global_unico(
        db,
        identidad,
        lambda sesion: ticket_service.obtener_ticket_detalle(
            sesion, ticket_id, identidad
        ),
        no_encontrado=ticket_service.DETALLE_TICKET_NO_ENCONTRADO,
    )


@router.get(
    "/{ticket_id}/historial",
    response_model=List[HistorialTransicionRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Consultar el historial de transiciones de un ticket",
    description=(
        "Lista las transiciones del ticket —estado de origen y destino, "
        "actor, marca de tiempo y motivo— en orden determinista: "
        "`fecha_transicion` descendente con desempate por "
        "`historial_transicion_id` descendente (Feature 013, spec §6, "
        "AC-9/AC-10). La lista vacia significa \"sin transiciones registradas"
        "\": un ticket anterior a la 013 no lleva filas inventadas (AC-12). "
        "Bajo esta ruta solo existe `GET`: el historial es inmutable por API, "
        "sus filas se escriben junto con cada mutacion del ciclo de vida.\n\n"
        "Mismo alcance por rol y mismo **404** de ocultamiento que el "
        "detalle (AC-18): Solicitante (sus tickets), Administrador y Bodeguero "
        "(su institucion). Feature 017 (D-9/AC-15): el **Superadmin no tiene esta "
        "lectura** y recibe **403** sin datos."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/tickets/{ticket_id}/historial"
            )
        )
    ],
)
def obtener_historial_ticket(
    ticket_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/tickets/{ticket_id}/historial")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.leer_global_unico(
        db,
        identidad,
        lambda sesion: ticket_service.obtener_historial_ticket(
            sesion, ticket_id, identidad
        ),
        no_encontrado=ticket_service.DETALLE_TICKET_NO_ENCONTRADO,
    )
