from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    HistorialTransicionTicket,
    MovimientoInventario,
    Prioridad,
    Producto,
    StockSede,
    Ticket,
    Usuario,
)
from app.core import permisos
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    EstadoTicketRespuesta,
    HistorialTransicionRespuesta,
    PrioridadRespuesta,
    ProductoCatalogoRespuesta,
    SolicitanteRespuesta,
    TicketCrear,
    TicketDetalleRespuesta,
    TicketDespacho,
    TicketEditar,
)
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada
from app.services.inventario_service import TIPO_SALIDA, es_stock_critico

#: Nombres canonicos de los estados que gobiernan el despacho y el ciclo de
#: vida. Se buscan por nombre (case-insensitive) y nunca por id fijo (D-1,
#: plan §3.2). `Cerrado` y `Anulado` son los dos terminales de la 013,
#: resueltos por nombre canonico y nunca por su posicion en el catalogo
#: (spec D-4, enmienda AC-26); `Pendiente` es el unico estado editable.
NOMBRE_ESTADO_EN_CURSO = "encurso"
NOMBRE_ESTADO_CERRADO = "cerrado"
NOMBRE_ESTADO_ANULADO = "anulado"
NOMBRE_ESTADO_PENDIENTE = "pendiente"

#: Longitud maxima del motivo de anulacion/rechazo (D-6): la escala del
#: `VARCHAR(500)` del historial y de `ticket.descripcion`. Se valida en el
#: servicio, nunca en Pydantic (plan decision 3), para no adelantar el 422 al
#: 404/409 del orden AC-7.
LONGITUD_MAXIMA_MOTIVO = 500

#: Observacion literal de auditoria de cada salida de despacho (D-6). El formato
#: solo lleva ids enteros y etiquetas fijas, por lo que cabe en el `VARCHAR(250)`
#: de `movimiento_inventario.observacion`.
PLANTILLA_OBSERVACION_DESPACHO = (
    "Despacho ticket_id={ticket_id}; "
    "detalle_id={detalle_ticket_id}; "
    "producto_id={producto_id}"
)

#: Rol cuya propiedad se resuelve por `ticket.usuario_id` y no por institucion.
_SOLICITANTE = permisos.RolConocido.SOLICITANTE.value


def _es_solicitante(identidad: IdentidadAutenticada | None) -> bool:
    """`True` solo para el rol `Solicitante` (un rol ausente/desconocido no)."""
    return permisos.nombre_rol_de(identidad) == _SOLICITANTE


#: Detalle unico del 404 de ticket (spec D-8): oculta por igual el inexistente
#: y el ajeno al alcance del rol. Es el mismo literal que esperan las pruebas
#: de la 013 y que `global_service.leer_global_unico` devuelve al no resolver
#: el recurso en ningun tenant.
DETALLE_TICKET_NO_ENCONTRADO = "Ticket no encontrado"


def _ticket_no_encontrado() -> HTTPException:
    """404 unico de ticket: oculta por igual el inexistente y el ajeno (D-5)."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DETALLE_TICKET_NO_ENCONTRADO,
    )


def _institucion_de_usuario(db: Session, usuario: Usuario | None) -> str | None:
    """Institucion de un usuario via `departamento_id -> departamento`, o `None`.

    Delegado a `ambito_service` (Feature 008): la resolucion del ambito vive en
    un solo sitio y no se duplica aqui.
    """
    return ambito_service.institucion_de_usuario(db, usuario)


def _institucion_de_ticket(db: Session, ticket: Ticket) -> str | None:
    """Institucion del solicitante de un ticket (su `usuario_id`)."""
    return ambito_service.institucion_de_ticket(db, ticket)


def _institucion_efectiva(
    db: Session, identidad: IdentidadAutenticada | None
) -> str | None:
    """Institucion efectiva del actor para operar tickets; `None` si es global.

    Con `identidad` presente y rol limitado resuelve su institucion (403 si no
    es resoluble, `alcance_institucional`); con Superadmin devuelve `None`. La
    `identidad` ausente (llamada directa al servicio en pruebas) no restringe,
    preservando el contrato previo.
    """
    if identidad is None:
        return None
    return ambito_service.alcance_institucional(db, identidad)


def _acotar_consulta_tickets(
    db: Session, consulta, identidad: IdentidadAutenticada | None
):
    """Aplica el alcance de lectura a la consulta de tickets (D-3, AC-6, AC-8).

    Superadmin no se filtra; el Solicitante ve solo sus propios tickets por
    `usuario_id`; Administrador y Bodeguero, solo los tickets de solicitantes de
    su institucion (via join a `usuario -> departamento`). Una institucion no
    resoluble responde 403 (`ambito_service.alcance_institucional`).
    """
    if identidad is None or ambito_service.es_alcance_global(identidad):
        return consulta
    if _es_solicitante(identidad):
        return consulta.where(Ticket.usuario_id == identidad.usuario.usuario_id)
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    return (
        consulta.join(Usuario, Ticket.usuario_id == Usuario.usuario_id)
        .join(Departamento, Usuario.departamento_id == Departamento.departamento_id)
        .where(Departamento.institucion_id == institucion_id)
    )


def _verificar_alcance_de_ticket(
    db: Session, ticket: Ticket, identidad: IdentidadAutenticada | None
) -> None:
    """Comprueba que el ticket este dentro del alcance del rol antes de mutar.

    Se invoca despues de resolver la existencia del ticket: un ticket de otra
    institucion para Administrador/Bodeguero, o ajeno al Solicitante, responde
    **404** igual que uno inexistente, sin revelar su existencia (D-5, AC-6). Si
    la institucion de un rol limitado no se resuelve, `alcance_institucional`
    responde 403 (D-4). Superadmin no se restringe.
    """
    if identidad is None or ambito_service.es_alcance_global(identidad):
        return
    if _es_solicitante(identidad):
        if ticket.usuario_id != identidad.usuario.usuario_id:
            raise _ticket_no_encontrado()
        return
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    if _institucion_de_ticket(db, ticket) != institucion_id:
        raise _ticket_no_encontrado()


def _acotar_consulta_solicitantes(
    db: Session, consulta, identidad: IdentidadAutenticada | None
):
    """Aplica el alcance al catalogo de solicitantes de `GET /tickets/catalogos`.

    El Solicitante solo se ve a si mismo; Administrador y Bodeguero, a los
    solicitantes de su institucion; Superadmin, a todos (D-3, AC-9).
    """
    if identidad is None or ambito_service.es_alcance_global(identidad):
        return consulta
    if _es_solicitante(identidad):
        return consulta.where(Usuario.usuario_id == identidad.usuario.usuario_id)
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    return consulta.where(Departamento.institucion_id == institucion_id)


def obtener_catalogos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> CatalogosTicketRespuesta:
    """Read model de los cuatro catalogos que necesita el modal de alta.

    Cada lista se arma con la tecnica que le corresponde y no con una sola
    consulta para todo: los cuatro conjuntos no comparten clave y un `UNION`
    obligaria a castear filas de 3 columnas a 5.

    `es_critico` sale de `es_stock_critico()`, la MISMA funcion que aplica
    `GET /inventario/existencias`. Importar una funcion pura de otro service no
    duplica logica de negocio ni cruza features (esta es la capa de servicios):
    si la regla del stock critico cambia, cambia en un solo sitio.

    Feature 008 (D-1/AC-6): el catalogo deja de ser global. Un rol limitado solo
    recibe los productos de su institucion y su `stock_total` suma unicamente las
    existencias de las sedes de esa misma institucion; el stock de otra
    institucion no influye. Superadmin (alcance global) ve el catalogo completo,
    cada producto atribuido con su `institucion_id` (AC-8).

    Feature 011 (spec D-2/D-6, M2): el agregado sale **exclusivamente** de
    `StockSede` (nunca del `inventario` departamental legado). `stock_total` es la
    suma de los saldos de las sedes del tenant y `es_critico` se evalua **por
    sede** -coherente con `/inventario/existencias`-: un producto es critico si
    alguna sede esta en o bajo el minimo.
    """
    institucion_id = _institucion_efectiva(db, identidad)

    prioridades = db.execute(
        select(Prioridad).order_by(Prioridad.prioridad_id)
    ).scalars().all()
    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()

    # Read model de producto + categoria + stock agregado por sede. El `group_by`
    # lista TODAS las columnas del `SELECT` porque PostgreSQL 16 lo exige y SQLite
    # es mas laxo: un `group_by` incompleto passaria la suite en memoria y
    # reventaria en el contenedor.
    #
    # `outerjoin` + `coalesce`: un producto sin filas en `stock_sede` tiene que
    # salir en 0 y no en `None`, porque `stock_total` es `NOT NULL` en el DTO.
    # `sedes_criticas`/`sedes_total` soportan la criticidad por sede (D-6): la
    # marca sale de la sede, no del promedio institucional.
    condicion_stock = StockSede.producto_id == Producto.producto_id
    if institucion_id is not None:
        # El `outerjoin` de stock solo acepta existencias de la institucion del
        # actor; el stock ajeno no entra al agregado.
        condicion_stock = and_(
            condicion_stock, StockSede.institucion_id == institucion_id
        )

    consulta_productos = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.institucion_id,
            Categoria.nombre_cat.label("categoria_nombre"),
            func.coalesce(func.sum(StockSede.stock_actual), 0).label("stock_total"),
            func.count(StockSede.stock_sede_id).label("sedes_total"),
            func.coalesce(
                func.sum(
                    case(
                        (StockSede.stock_actual <= Producto.stock_minimo, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("sedes_criticas"),
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(StockSede, condicion_stock)
        .group_by(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.institucion_id,
            Categoria.nombre_cat,
        )
        .order_by(Producto.nombre, Producto.producto_id)
    )
    if institucion_id is not None:
        # El catalogo es institucional: un rol limitado no ve el producto ajeno.
        consulta_productos = consulta_productos.where(
            Producto.institucion_id == institucion_id
        )

    consulta_solicitantes = (
        select(
            Usuario.usuario_id,
            Usuario.nombre,
            Usuario.apellido,
            Usuario.correo,
            Departamento.nombre_dep.label("departamento_nombre"),
        )
        .join(Departamento, Usuario.departamento_id == Departamento.departamento_id)
        .order_by(Usuario.apellido, Usuario.nombre, Usuario.usuario_id)
    )
    # El catalogo de solicitantes se acota por rol (D-3, AC-9).
    consulta_solicitantes = _acotar_consulta_solicitantes(
        db, consulta_solicitantes, identidad
    )

    return CatalogosTicketRespuesta(
        prioridades=[PrioridadRespuesta.model_validate(p) for p in prioridades],
        estados=[EstadoTicketRespuesta.model_validate(e) for e in estados],
        productos=[
            ProductoCatalogoRespuesta(
                producto_id=fila.producto_id,
                nombre=fila.nombre,
                unidad_medida=fila.unidad_medida,
                categoria_nombre=fila.categoria_nombre,
                stock_total=fila.stock_total,
                # Criticidad por sede (D-6): alguna sede en o bajo el minimo. Un
                # producto sin ninguna sede conserva la semantica de "sin
                # existencia" (`0 <= stock_minimo`) del catalogo.
                es_critico=(
                    fila.sedes_criticas > 0
                    if fila.sedes_total > 0
                    else es_stock_critico(0, fila.stock_minimo)
                ),
                institucion_id=fila.institucion_id,
            )
            for fila in db.execute(consulta_productos).all()
        ],
        solicitantes=[
            SolicitanteRespuesta.model_validate(fila)
            for fila in db.execute(consulta_solicitantes).mappings().all()
        ],
    )


def listar_tickets(
    db: Session,
    estado_id: Optional[int] = None,
    identidad: IdentidadAutenticada | None = None,
) -> List[Ticket]:
    """Lista los tickets con su coleccion cargada eager y un orden estable.

    El orden es explicito y no el que devuelva la base: `fecha_creacion`
    descendente con desempate por `ticket_id` descendente. En SQLite
    `CURRENT_TIMESTAMP` no tiene subsegundo, asi que sin el desempate el orden
    de las altas de un mismo segundo seria el que quisiera el motor (AC-27).

    `selectinload` en cadena resuelve `detalles`, el `producto` anidado y su
    `categoria` -los tres niveles que `DetalleTicketRespuesta` serializa- en un
    numero FIJO de consultas, en vez de una por ticket y otra por detalle.
    `categoria` se carga eager de forma explicita porque la lectura global del
    Superadmin (`global_service._LectorPostgres`) cierra la sesion de cada
    tenant **antes** de que FastAPI serialice la respuesta: sin precargarla, el
    `lazy="select"` de `Producto.categoria` revienta con `DetachedInstanceError`
    sobre el objeto ya desasociado (500 en `GET /tickets/`). Se descarta
    `joinedload` en la coleccion porque multiplicaria las filas del ticket por
    cada detalle.

    El filtro por `estado_id` se comprueba con `is not None`: un `0` o un id
    valido nunca deben confundirse con "sin filtro".

    Feature 007 (D-3/AC-6/AC-8): la lectura se acota por rol; el Solicitante ve
    solo sus tickets y Administrador/Bodeguero, los de su institucion.
    """
    consulta = (
        select(Ticket)
        .options(
            selectinload(Ticket.detalles)
            .selectinload(DetalleTicket.producto)
            .selectinload(Producto.categoria)
        )
        .order_by(Ticket.fecha_creacion.desc(), Ticket.ticket_id.desc())
    )
    consulta = _acotar_consulta_tickets(db, consulta, identidad)
    if estado_id is not None:
        consulta = consulta.where(Ticket.estado_id == estado_id)
    return db.execute(consulta).scalars().all()


def _verificar_referencia(db: Session, modelo, valor: int, etiqueta: str) -> None:
    """Comprueba que una FK exista y, si no, lanza 404 nombrando la referencia.

    Se valida **antes** de escribir, no confiando en la FK de la base: si se
    deja que la violacion llegue al `INSERT`, la respuesta es un 500 opaco que
    no dice que faltó ni cual. El mensaje nombra el tipo de referencia y su
    valor, para que el error sea accionable (`spec.md` AC-6, AC-7).
    """
    if db.get(modelo, valor) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe {etiqueta} indicado: {valor}",
        )


def _verificar_productos(
    db: Session, detalles, institucion_id: str | None
) -> None:
    """Valida todos los `producto_id` del payload antes de escribir nada.

    Los ids se deduplican con un `set` para que cinco lineas del mismo producto
    costen una sola busqueda, y el mensaje reporta **el id mas bajo** que falla
    (`sorted`) para que sea determinista entre ejecuciones.

    Feature 008 (D-4/AC-11): un producto de otra institucion se **oculta con
    404**, con el mismo mensaje que uno inexistente, de modo que un id ajeno no
    revele su existencia. Con alcance global (`institucion_id is None`) no se
    restringe por institucion.
    """
    ids_requeridos = {detalle.producto_id for detalle in detalles}
    for producto_id in sorted(ids_requeridos):
        producto = db.get(Producto, producto_id)
        if producto is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No existe producto indicado: {producto_id}",
            )
        ambito_service.exigir_pertenencia(
            ambito_service.institucion_de_recurso(producto),
            institucion_id,
            detalle=f"No existe producto indicado: {producto_id}",
        )


def _sede_vigente_de_solicitante(db: Session, usuario: Usuario | None) -> int:
    """Sede vigente del departamento del solicitante, o **409** sin fallback.

    Feature 011 (spec D-5/AC-9): al crear un ticket se copia a `ticket.sede_id` la
    sede del departamento del solicitante. Un departamento sin sede asignada
    -o inexistente- impide el alta con **409**, sin usar una sede por defecto
    (regla 3/8 de la spec). La validacion no escribe, de modo que un rechazo no
    deja ticket parcial.
    """
    if usuario is None or usuario.departamento_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El departamento del solicitante no tiene una sede asignada",
        )
    departamento = db.get(Departamento, usuario.departamento_id)
    if departamento is None or departamento.sede_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El departamento del solicitante no tiene una sede asignada",
        )
    return departamento.sede_id


def _registrar_transicion(
    db: Session,
    ticket: Ticket,
    estado_origen_id: int | None,
    estado_destino_id: int,
    identidad: IdentidadAutenticada | None,
    motivo: str | None,
) -> None:
    """Inserta una fila del historial de transiciones (AC-9, AC-11, D-10).

    Debe invocarse **dentro** de la misma transaccion que el cambio de estado
    que documenta, sin commit propio: si la fila no puede escribirse, el
    `rollback` del llamador revierte tambien el cambio de estado y no queda
    ningun efecto parcial (`constitucion.md` §3, AC-11).

    El actor es la identidad autenticada; en invocacion directa al servicio
    sin identidad (no observable por HTTP) se atribuye a `ticket.usuario_id`
    (plan decision 9). `estado_origen_id` es nulo **solo** en la fila de
    creacion del ticket (AC-9); toda transicion posterior declara su origen.
    """
    actor_id = (
        identidad.usuario.usuario_id
        if identidad is not None
        else ticket.usuario_id
    )
    db.add(
        HistorialTransicionTicket(
            ticket_id=ticket.ticket_id,
            estado_origen_id=estado_origen_id,
            estado_destino_id=estado_destino_id,
            usuario_id=actor_id,
            motivo=motivo,
        )
    )


def crear_ticket(
    db: Session, datos: TicketCrear, identidad: IdentidadAutenticada | None = None
) -> Ticket:
    """Persiste el ticket y sus detalles en una sola transaccion ACID.

    Antes este flujo hacia dos `commit()`: el ticket quedaba persistido aunque
    fallara el alta de algun detalle, dejando un ticket huerfano. Ver
    `constitucion.md` §3 (Consistencia Transaccional).

    Las cuatro referencias del payload se comprueban **antes** del primer
    `add()`, con dos motivos:

    1. Devolver 404 con un mensaje util en vez de un 500 de FK.
    2. No dejar nada escrito cuando el payload es invalido: todavia no hay
       nada que revertir, y por eso el `rollback()` va en el `try` de abajo y
       no aqui.

    El `except` es `Exception` y no `HTTPException` a proposito: dentro del
    `try` no se lanzan 404 (ya salieron antes) sino fallos de base, que no
    heredan de `HTTPException`.

    El `rollback()` explicito no es lo que impide el ticket huerfano (eso lo
    hace la prevalidacion, que no escribe nada): es la red exigida por
    `constitucion.md` §3 ante cualquier fallo de base.

    Sobre por que se conserva si con el `get_db` actual resultaria redundante:
    `get_db` hace `db.close()` en su `finally` y `close()` ya revierte, asi que
    borrarlo deja la suite en verde (comprobado por mutacion). Se mantiene
    porque este metodo debe ser correcto por si mismo y no gracias al cleanup
    de quien lo llama, que es lo que dejaria de ser cierto en cuanto dos
    tickets compartieran transaccion.

    Feature 007 (D-3/AC-6): el Solicitante queda **siempre** atribuido a su
    identidad autenticada e ignora cualquier `usuario_id` alternativo del
    payload. Administrador/Bodeguero conservan el contrato vigente con
    `usuario_id` obligatorio, pero solo pueden elegir un solicitante de su
    institucion. Superadmin no crea tickets de una institucion concreta (matriz
    008), pero el servicio mantiene el contrato si se le invocara directamente.

    Feature 008 (D-4/AC-11): el ticket se ancla a la institucion de su
    solicitante y cada producto del detalle debe pertenecer a esa misma
    institucion. Un solicitante de otra institucion para un rol limitado y un
    producto ajeno se **ocultan con 404**, igual que si no existieran; un
    `usuario_id` inexistente conserva el 404 que nombra la referencia. Todo
    rechazo ocurre **antes del primer `add()`**, de modo que no quedan ticket ni
    detalle parciales. Se pueblan `ticket.institucion_id` y
    `detalle_ticket.institucion_id` con esa institucion, satisfaciendo las
    claves compuestas del esquema (AC-4).

    AC-17: si el estado destino es `Cerrado` (case-insensitive), se sella
    `fecha_cierre` en la propia creacion.

    Feature 013 (spec D-11, plan decision 8): un ticket nuevo **no puede nacer
    en `Anulado`**. El estado existe en el catalogo, asi que el rechazo es
    **409** (precondicion, no 404/422) y ocurre antes del primer `add()`, sin
    dejar ticket ni detalle parciales. Ademas la creacion inserta su fila de
    historial (origen nulo, destino = estado inicial, actor = identidad o
    `ticket.usuario_id`; decision 9) en la misma transaccion del ticket (AC-9,
    AC-11).
    """
    if _es_solicitante(identidad):
        # Se ignora el `usuario_id` recibido y se reescribe al del autenticado:
        # no es un 422 (el contrato no cambio) ni un 403, es autoatribucion.
        datos = datos.model_copy(
            update={"usuario_id": identidad.usuario.usuario_id}
        )

    _verificar_referencia(db, Usuario, datos.usuario_id, "usuario")

    # Institucion efectiva del actor (`None` = Superadmin) y del solicitante
    # elegido: el ticket hereda la del solicitante (spec §6).
    institucion_actor = _institucion_efectiva(db, identidad)
    solicitante = db.get(Usuario, datos.usuario_id)
    institucion_ticket = _institucion_de_usuario(db, solicitante)

    if institucion_actor is not None:
        # Rol limitado: el solicitante debe pertenecer a su institucion; uno
        # ajeno se oculta con 404 (D-4/AC-11), indistinguible de un usuario
        # inexistente.
        ambito_service.exigir_pertenencia(
            institucion_ticket,
            institucion_actor,
            detalle=f"No existe usuario indicado: {datos.usuario_id}",
        )

    _verificar_referencia(db, Prioridad, datos.prioridad_id, "prioridad")
    _verificar_referencia(db, EstadoTicket, datos.estado_id, "estado")
    _verificar_productos(db, datos.detalles, institucion_ticket)

    # Feature 011 (spec D-5/AC-9): instantanea de la sede vigente del departamento
    # del solicitante. Se resuelve **antes** de escribir; sin sede el alta es 409.
    sede_ticket = _sede_vigente_de_solicitante(db, solicitante)

    # Resolucion por nombre (case-insensitive) de los dos estados con reglas
    # propias en el alta: `Cerrado` sella fecha (AC-17) y `Anulado` se rechaza
    # (D-11). Ante nombres duplicados gana el de menor `estado_id` (plan §3.2).
    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()
    estado_cierre = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_CERRADO)
    es_estado_cierre = (
        estado_cierre is not None and datos.estado_id == estado_cierre.estado_id
    )

    # D-11 (plan decision 8): `Anulado` no es elegible para alta. El estado
    # existe, asi que el rechazo es 409 y no 404/422; va antes del primer
    # `add()` para no dejar ticket ni detalle parciales.
    estado_anulado = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_ANULADO)
    if estado_anulado is not None and datos.estado_id == estado_anulado.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El estado 'Anulado' no es elegible para alta: un ticket nuevo "
                "no puede nacer anulado"
            ),
        )

    try:
        nuevo_ticket = Ticket(
            **datos.model_dump(exclude={"detalles"}),
            institucion_id=institucion_ticket,
            sede_id=sede_ticket,
        )
        db.add(nuevo_ticket)
        db.flush()  # asigna ticket_id sin cerrar la transaccion

        # AC-17: sellar fecha_cierre si se crea directamente en Cerrado
        if es_estado_cierre:
            nuevo_ticket.fecha_cierre = datetime.utcnow()

        for detalle in datos.detalles:
            db.add(
                DetalleTicket(
                    ticket_id=nuevo_ticket.ticket_id,
                    producto_id=detalle.producto_id,
                    cantidad_solicitada=detalle.cantidad_solicitada,
                    cantidad_entregada=0,
                    institucion_id=institucion_ticket,
                )
            )

        # AC-9/decision 9: la creacion es una mutacion del ciclo de vida y
        # registra su fila de historial (origen nulo, destino = estado
        # inicial) en la MISMA transaccion que el ticket.
        _registrar_transicion(
            db,
            nuevo_ticket,
            estado_origen_id=None,
            estado_destino_id=datos.estado_id,
            identidad=identidad,
            motivo=None,
        )

        db.commit()
        db.refresh(nuevo_ticket)
    except Exception:
        db.rollback()
        raise

    return nuevo_ticket


def actualizar_estado_ticket(
    db: Session,
    ticket_id: int,
    estado_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Aplica una transicion del flujo lineal con terminales por nombre, atomicamente.

    Orden de validacion (D-8): ticket (404) -> estado pedido (404) -> flujo
    (409). El flujo se evalua sobre los indices del catalogo ordenado por
    `estado_id` (D-1): un paso en cualquier direccion entre contiguos; el
    indice actual igual al destino y la distancia != 1 rechazan sin tocar el
    ticket.

    `Cerrado` y `Anulado` son los dos estados terminales, resueltos por
    **nombre canonico** (casefold, menor `estado_id` ante duplicados) y nunca
    por su posicion en el catalogo (013 D-4, enmienda AC-26): ninguno admite
    salida en **ningun** catalogo, y el cambio de estado tampoco puede llevar
    a `Cerrado` ni a `Anulado`. La terminalidad ordinal de la 004 (el ultimo
    estado del catalogo no se sale) quedo **derogada** por la enmienda: la
    ultima posicion no otorga terminalidad a ningun otro estado; la
    contiguidad del flujo lineal entre los estados operativos se conserva.

    El cierre se reconoce por nombre `casefold() == "cerrado"` sobre ese
    mismo catalogo, nunca por un id fijo (D-3); si el nombre esta repetido,
    gana el de menor `estado_id`. `fecha_cierre` ya no se sella en esta
    funcion: con la terminalidad por nombre, toda peticion cuyo destino sea
    `Cerrado` responde 409, de modo que los dos caminos vigentes de sellado
    son el alta directa (004 AC-17) y el despacho transaccional (005), y
    ninguno de los dos la sobrescribe. El unico `commit` del final hace
    estado e historial una sola operacion (`constitucion.md` §3).

    Feature 005 (AC-15, D-1/D-12): el despacho transaccional es el **unico
    camino a `Cerrado`**. Toda peticion cuyo destino sea el `Cerrado`
    canonico responde 409 con el detalle literal que dirige al endpoint de
    despacho, sin mutar el ticket. El estado se resuelve por **nombre**
    (menor `estado_id` ante duplicados), nunca por el ultimo ordinal: en un
    catalogo degenerado el ultimo estado podria no ser `Cerrado`. La guardia
    va despues de validar el flujo (orden D-8) y antes de cualquier
    escritura; los contratos `EnCurso -> Cerrado` de la 004/005 conservan su
    409 y su detalle literal intactos.

    Feature 013 (spec D-4/§6, plan decision 5, enmienda AC-26): `Anulado`
    queda **fuera** del flujo lineal y se resuelve por nombre canonico.
    Cualquier peticion cuyo destino sea `Anulado`, cuyo origen sea `Anulado`
    o cuyo origen sea `Cerrado` responde **409** tras los dos 404 (ticket/
    alcance y estado pedido, orden D-8 intacto) y antes del 409 generico de
    flujo: el de `Anulado` dirige a la operacion de anulacion o rechazo
    correspondiente; el de salida desde `Cerrado` declara que el cierre es
    definitivo y que el despacho es el unico camino a el. Ningun catalogo
    altera estas reglas (AC-26): un ticket ya despachado no puede volver a
    un estado despachable, de modo que no hay camino a una segunda rebaja
    de stock.

    Feature 007 (D-5/AC-6): tras comprobar la existencia se verifica el alcance
    del rol; un ticket de otra institucion (Administrador/Bodeguero) o ajeno al
    Solicitante responde 404, igual que uno inexistente, antes de tocar nada.

    Feature 013 (AC-9/AC-11): toda transicion aceptada inserta su fila de
    historial en la MISMA transaccion que el cambio de estado, via
    `_registrar_transicion`, con la identidad autenticada como actor.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise _ticket_no_encontrado()

    _verificar_alcance_de_ticket(db, ticket, identidad)

    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()

    indice_destino = next(
        (i for i, e in enumerate(estados) if e.estado_id == estado_id), None
    )
    if indice_destino is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe estado indicado: {estado_id}",
        )

    # Guardia 013 (D-4/§6): `Anulado` esta fuera del flujo lineal. Hacia
    # `Anulado` solo se llega por anulacion o rechazo; desde `Anulado` no se
    # sale por ningun camino. El 409 dirige a la operacion correspondiente y
    # va antes del 409 generico de flujo para que toda peticion que toque
    # `Anulado` reciba ese detalle (tras los dos 404 del orden D-8).
    estado_anulado = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_ANULADO)
    if estado_anulado is not None and estado_id == estado_anulado.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El estado 'Anulado' solo se alcanza por anulacion o rechazo; "
                f"use POST /api/v1/tickets/{ticket_id}/anulacion o "
                f"POST /api/v1/tickets/{ticket_id}/rechazo"
            ),
        )
    if estado_anulado is not None and ticket.estado_id == estado_anulado.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El ticket esta en 'Anulado', estado terminal del que ninguna "
                "operacion lo saca; la anulacion y el rechazo solo se aplican "
                "desde 'Pendiente' o 'EnRevision'"
            ),
        )

    # Guardia 013 (enmienda D-4, AC-26): `Cerrado` es terminal por nombre
    # canonico en **cualquier** catalogo y nada sale de el por `PATCH
    # /estado`. El 409 declara que el cierre es definitivo y que el despacho
    # de la 005 es el unico camino a el. Va tras los dos 404 y las guardias
    # de `Anulado` (orden D-8) y antes del 409 generico de flujo.
    estado_cierre = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_CERRADO)
    if estado_cierre is not None and ticket.estado_id == estado_cierre.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El ticket esta en 'Cerrado', estado terminal por nombre: el "
                "cierre es definitivo y no admite ninguna salida; el despacho "
                "transaccional es el unico camino a el, use "
                f"POST /api/v1/tickets/{ticket_id}/despacho"
            ),
        )

    indice_actual = next(
        (i for i, e in enumerate(estados) if e.estado_id == ticket.estado_id), None
    )
    fuera_de_flujo = (
        indice_actual is None  # el ticket esta en un estado ya borrado
        or indice_destino == indice_actual
        or abs(indice_destino - indice_actual) != 1
        # La terminalidad **ordinal** de la 004 (el ultimo estado del catalogo
        # no se sale) quedo derogada por la enmienda D-4 de la 013 (AC-26):
        # la terminalidad se resuelve solo por nombre, via las guardias de
        # `Anulado` y `Cerrado` de arriba; la ultima posicion no la otorga
        # ningun otro estado.
    )
    if fuera_de_flujo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transicion invalida: el ticket esta en el estado "
                f"{ticket.estado_id} y se pidio {estado_id}; el flujo solo "
                f"admite avanzar o retroceder un paso entre estados contiguos"
            ),
        )

    estado_destino = estados[indice_destino]

    # Guardia AC-15 de la 005 (D-1, D-12), ampliada por la enmienda D-4 de la
    # 013 (AC-26): el despacho transaccional es el **unico camino a `Cerrado`**
    # en cualquier catalogo, no solo para el paso `EnCurso -> Cerrado`. Toda
    # peticion cuyo destino sea el `Cerrado` canonico responde con el MISMO
    # detalle literal de la 005 (los contratos `EnCurso -> Cerrado` quedan
    # intactos) y sin mutar el ticket. El destino se resuelve por **nombre
    # canonico** (menor `estado_id` ante duplicados) y no por el ultimo
    # ordinal, que en un catalogo degenerado podria no ser `Cerrado`. Va
    # despues del flujo (orden D-8) y antes de tocar el ticket; con esta
    # guardia, la reentrada en `Cerrado` es imposible y un ticket ya
    # despachado no vuelve a un estado despachable (sin doble rebaja).
    if (
        estado_cierre is not None
        and estado_destino.estado_id == estado_cierre.estado_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El cierre requiere despacho; use "
                f"POST /api/v1/tickets/{ticket_id}/despacho"
            ),
        )

    try:
        # El origen se captura ANTES de mutar: es el que declara la fila del
        # historial (AC-9).
        estado_origen_id = ticket.estado_id
        ticket.estado_id = estado_id
        # `fecha_cierre` ya no se sella aqui (enmienda AC-26): con `Cerrado`
        # terminal por nombre, toda peticion cuyo destino sea `Cerrado` ya
        # respondio 409 arriba. Los dos caminos vigentes de sellado son el
        # alta directa (004 AC-17) y el despacho (005), ambos con su
        # `if fecha_cierre is None` sin sobrescribir nunca la fecha.

        # AC-11 (013): cambio de estado y su fila de historial son una sola
        # operacion; si la fila falla, el rollback revierte el estado.
        _registrar_transicion(
            db,
            ticket,
            estado_origen_id=estado_origen_id,
            estado_destino_id=estado_id,
            identidad=identidad,
            motivo=None,
        )

        db.commit()
        db.refresh(ticket)
    except Exception:
        db.rollback()
        raise
    return ticket


def _resolver_estado_por_nombre(estados, nombre: str):
    """Primera coincidencia por nombre, sin distinguir mayusculas (plan §3.2).

    `estados` ya llega ordenado por `estado_id`, de modo que `next` devuelve el
    de **menor id** ante nombres duplicados, que es la regla de la 004 (D-1).
    """
    objetivo = nombre.casefold()
    return next((e for e in estados if e.nombre.casefold() == objetivo), None)


def despachar_ticket(
    db: Session,
    ticket_id: int,
    datos: TicketDespacho,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Despacha un ticket aprobado: rebaja stock, cierra y audita en una ACID.

    El orden de validacion es contractual (`spec.md` §5, plan §3.1-§3.3) y
    **ninguna** comprobacion de negocio escribe: primero se adquiere el bloqueo
    de la fila del ticket y se comprueba su existencia; despues el actor; luego
    el catalogo de estados y la elegibilidad; a continuacion los detalles, las
    referencias de producto, la unicidad de inventario y la suficiencia del
    stock total; solo entonces se muta y se hace un **unico** `commit()`.

    El bloqueo (`with_for_update()`) serializa dos despachos del mismo ticket
    (D-9): la segunda peticion espera y, tras el commit de la primera, relee el
    estado `Cerrado` y responde 409 sin crear salidas. SQLite ignora
    `FOR UPDATE`; la garantia concurrente se verifica en PostgreSQL real.

    Cada detalle genera su propio `MovimientoInventario` `SALIDA` con la
    cantidad solicitada y la observacion literal D-6 (D-7), aunque varias lineas
    compartan producto: el stock se valida **agregado** por producto antes de
    escribir. La rebaja, las cantidades entregadas, el cierre y las salidas son
    una sola transaccion; cualquier fallo de escritura o commit revierte todo y
    se propaga (`constitucion.md` §3).

    Feature 007 (D-5/AC-6): tras comprobar la existencia se verifica el alcance
    del rol; un ticket de otra institucion (Administrador/Bodeguero) o ajeno al
    Solicitante responde 404 antes de tocar stock, estado o auditoria, de modo
    que la denegacion no muta la transaccion de despacho.

    Feature 008 (D-2/D-4/AC-12): el ticket se ancla a la institucion de su
    solicitante y tanto el producto de cada detalle como el stock que se rebaja
    deben pertenecer a esa misma institucion. Una referencia cruzada es una
    inconsistencia que impide resolver el despacho: responde **409**, se evalua
    antes de cualquier escritura y, como el resto de rechazos, no deja stock,
    entrega, estado ni auditoria parciales en la unica transaccion.

    Feature 011 (spec D-5/AC-9): el despacho usa **exclusivamente** la instantanea
    `ticket.sede_id`, nunca la asignacion vigente del departamento; rebaja solo el
    `StockSede` de esa sede y enlaza el movimiento nuevo por `stock_sede_id`,
    dejando `inventario_id` nulo. Un ticket sin instantanea (legado sin migrar)
    responde 409. La sede se bloquea con `FOR UPDATE` junto al ticket para
    serializar despachos concurrentes; SQLite ignora el bloqueo y la garantia real
    se verifica en PostgreSQL.
    """
    ticket = db.execute(
        select(Ticket).where(Ticket.ticket_id == ticket_id).with_for_update()
    ).scalar_one_or_none()
    if ticket is None:
        raise _ticket_no_encontrado()

    _verificar_alcance_de_ticket(db, ticket, identidad)

    # Institucion del ticket (la de su solicitante): todo detalle y el stock que
    # se rebaje debe pertenecer a ella (D-2, AC-12).
    institucion_ticket = _institucion_de_ticket(db, ticket)

    if db.get(Usuario, datos.usuario_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe usuario indicado: {datos.usuario_id}",
        )

    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()
    estado_en_curso = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_EN_CURSO)
    estado_cerrado = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_CERRADO)
    if estado_en_curso is None or estado_cerrado is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El catalogo de estados no contiene los nombres requeridos para "
                f"despachar ({NOMBRE_ESTADO_EN_CURSO}/{NOMBRE_ESTADO_CERRADO})"
            ),
        )

    if ticket.estado_id != estado_en_curso.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El ticket no esta en '{estado_en_curso.nombre}': el despacho "
                "solo se realiza desde ese estado"
            ),
        )

    detalles = db.execute(
        select(DetalleTicket)
        .where(DetalleTicket.ticket_id == ticket_id)
        .order_by(DetalleTicket.detalle_ticket_id)
    ).scalars().all()
    if not detalles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El ticket no tiene detalles que despachar",
        )

    # Feature 011 (spec D-5/AC-9): el despacho usa **exclusivamente** la sede
    # almacenada en el ticket, nunca la asignacion vigente del departamento. Un
    # ticket legado sin instantanea (migracion no aplicada) no se despacha.
    sede_ticket = ticket.sede_id
    if sede_ticket is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El ticket no tiene una sede asignada (instantanea); la migracion "
                "debe resolverla antes de despacharlo"
            ),
        )

    ids_producto = sorted({detalle.producto_id for detalle in detalles})

    # El saldo vigente se lee de `stock_sede` y se bloquea con `FOR UPDATE` en la
    # misma transaccion (patron de la Feature 005): dos despachos concurrentes del
    # mismo ticket o de la misma sede se serializan. SQLite ignora `FOR UPDATE`;
    # la concurrencia real se verifica en PostgreSQL.
    filas_stock = db.execute(
        select(StockSede)
        .where(
            StockSede.sede_id == sede_ticket,
            StockSede.producto_id.in_(ids_producto),
        )
        .with_for_update()
    ).scalars().all()
    stock_por_producto: dict[int, StockSede] = {
        fila.producto_id: fila for fila in filas_stock
    }

    cantidad_requerida: dict[int, int] = {}
    for detalle in detalles:
        cantidad_requerida[detalle.producto_id] = (
            cantidad_requerida.get(detalle.producto_id, 0)
            + detalle.cantidad_solicitada
        )

    # Validacion total antes de escribir: ninguna comprobacion de negocio muta, de
    # modo que un rechazo no deja stock, entrega, estado ni auditoria parciales.
    for producto_id in ids_producto:
        producto = db.get(Producto, producto_id)
        if producto is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"No se puede resolver el producto {producto_id} de un "
                    "detalle del ticket"
                ),
            )
        # AC-12: el producto del detalle debe ser de la institucion del ticket.
        if not ambito_service.pertenece_al_alcance(
            ambito_service.institucion_de_recurso(producto), institucion_ticket
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El producto {producto_id} no pertenece a la institucion "
                    "del ticket"
                ),
            )
        fila = stock_por_producto.get(producto_id)
        # AC-12: el stock que se rebaja debe ser de la institucion del ticket.
        if fila is not None and not ambito_service.pertenece_al_alcance(
            fila.institucion_id, institucion_ticket
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El stock de la sede {sede_ticket} del producto "
                    f"{producto_id} no pertenece a la institucion del ticket"
                ),
            )
        disponible = 0 if fila is None else fila.stock_actual
        requerido = cantidad_requerida[producto_id]
        if disponible < requerido:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Stock insuficiente para el producto {producto_id}: "
                    f"requerido {requerido}, disponible {disponible}"
                ),
            )

    try:
        for detalle in detalles:
            fila = stock_por_producto[detalle.producto_id]
            fila.stock_actual -= detalle.cantidad_solicitada
            detalle.cantidad_entregada = detalle.cantidad_solicitada
            db.add(
                MovimientoInventario(
                    tipo_movimiento=TIPO_SALIDA,
                    cantidad=detalle.cantidad_solicitada,
                    observacion=PLANTILLA_OBSERVACION_DESPACHO.format(
                        ticket_id=ticket.ticket_id,
                        detalle_ticket_id=detalle.detalle_ticket_id,
                        producto_id=detalle.producto_id,
                    ),
                    # Movimiento nuevo: se enlaza por `stock_sede_id` y deja
                    # `inventario_id` nulo (spec D-2 y §7).
                    stock_sede_id=fila.stock_sede_id,
                )
            )

        ticket.estado_id = estado_cerrado.estado_id
        if ticket.fecha_cierre is None:
            ticket.fecha_cierre = datetime.utcnow()

        # AC-5/AC-9 (013): el despacho es una mutacion del ciclo de vida y
        # suma su fila de historial en la MISMA transaccion ACID que la rebaja
        # de stock; el despacho no exige motivo (motivo nulo).
        _registrar_transicion(
            db,
            ticket,
            estado_origen_id=estado_en_curso.estado_id,
            estado_destino_id=estado_cerrado.estado_id,
            identidad=identidad,
            motivo=None,
        )

        db.commit()
        db.refresh(ticket)
    except Exception:
        db.rollback()
        raise

    return ticket


def _cambiar_a_anulado(
    db: Session,
    ticket_id: int,
    motivo: str | None,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Anula un ticket con motivo, atomicamente. Helper unico de la 013.

    Comparte el camino de la anulacion y el rechazo (plan decision 6): la
    distincion de roles vive en la matriz de permisos, no en el servicio. El
    orden de validacion es estricto (spec §5 invariante 2, AC-7) y **ninguna**
    comprobacion escribe hasta la mutacion final:

    1. El ticket existe y esta en el alcance del rol -> **404** (inexistente y
       ajeno, identicos; D-8).
    2. El catalogo contiene `Anulado` (si no, **409**, spec §6) y el estado
       actual admite la operacion: solo `Pendiente` y `EnRevision`; `EnCurso`,
       `Cerrado` y `Anulado` responden **409** (D-3), como tambien un estado
       ya borrado del catalogo (defensa fail-closed).
    3. El motivo es valido (no vacio y hasta `LONGITUD_MAXIMA_MOTIVO`) ->
       **422** (D-6). Se valida **aqui** y no en Pydantic (decision 3): el
       schema de entrada lo define T8 y la validacion en el servicio es lo que
       respeta el orden 404 -> 409 -> 422 ante problemas simultaneos.

    La mutacion es una sola transaccion: el estado del ticket y su fila de
    historial con el **motivo literal** (AC-9/AC-11); si la fila no puede
    escribirse, el estado no cambia. `fecha_cierre` queda **nula** (D-5: no es
    un cierre por despacho) y no se escribe stock ni movimiento de inventario
    (la anulacion no mueve existencias).
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise _ticket_no_encontrado()

    _verificar_alcance_de_ticket(db, ticket, identidad)

    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()
    estado_anulado = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_ANULADO)
    if estado_anulado is None:
        # Spec §6: sin `Anulado` en el catalogo del tenant la operacion no
        # puede resolver su estado destino; es un 409, no un 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El catalogo de estados no contiene 'Anulado': la operacion "
                "no esta disponible en esta instalacion"
            ),
        )

    if ticket.estado_id == estado_anulado.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El ticket ya esta en 'Anulado'",
        )

    # D-3: desde `EnCurso` el unico cierre valido es el despacho de la 005;
    # `Cerrado` y `Anulado` son terminales. Todo lo que no sea `Pendiente` o
    # `EnRevision` (incluido un estado ya borrado del catalogo) es inadmisible.
    estado_en_curso = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_EN_CURSO)
    estado_cerrado = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_CERRADO)
    estados_inadmisibles = {
        estado.estado_id
        for estado in (estado_en_curso, estado_cerrado, estado_anulado)
        if estado is not None
    }
    estado_actual_conocido = any(
        e.estado_id == ticket.estado_id for e in estados
    )
    if not estado_actual_conocido or ticket.estado_id in estados_inadmisibles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El estado actual no admite anulacion ni rechazo: solo se "
                "admiten 'Pendiente' o 'EnRevision'"
            ),
        )

    if (
        not isinstance(motivo, str)
        or not motivo.strip()
        or len(motivo) > LONGITUD_MAXIMA_MOTIVO
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "El motivo es obligatorio y no puede exceder "
                f"{LONGITUD_MAXIMA_MOTIVO} caracteres"
            ),
        )

    try:
        estado_origen_id = ticket.estado_id
        ticket.estado_id = estado_anulado.estado_id
        # D-5: `fecha_cierre` NO se sella; la anulacion no es un cierre por
        # despacho y no escribe stock ni movimientos.

        # AC-9/AC-11: la fila del historial con el motivo literal viaja en la
        # MISMA transaccion que el cambio de estado.
        _registrar_transicion(
            db,
            ticket,
            estado_origen_id=estado_origen_id,
            estado_destino_id=estado_anulado.estado_id,
            identidad=identidad,
            motivo=motivo,
        )

        db.commit()
        db.refresh(ticket)
    except Exception:
        db.rollback()
        raise

    return ticket


def anular_ticket(
    db: Session,
    ticket_id: int,
    motivo: str | None,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Anulacion de un ticket (spec D-1/D-3/D-6; matriz 013: Solicitante y
    Administrador). Delega en `_cambiar_a_anulado`: la distincion entre
    anulacion y rechazo es de matriz y de registro, no de camino.
    """
    return _cambiar_a_anulado(db, ticket_id, motivo, identidad)


def rechazar_ticket(
    db: Session,
    ticket_id: int,
    motivo: str | None,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Rechazo de un ticket (spec D-1/D-3/D-6; matriz 013: Bodeguero y
    Administrador). Comparte `_cambiar_a_anulado` con la anulacion; el estado
    destino es el mismo (`Anulado`) y solo difieren roles y semantica publica.
    """
    return _cambiar_a_anulado(db, ticket_id, motivo, identidad)


def editar_ticket(
    db: Session,
    ticket_id: int,
    datos: TicketEditar,
    identidad: IdentidadAutenticada | None = None,
) -> Ticket:
    """Edita asunto, descripcion, prioridad y detalles de un ticket `Pendiente`.

    Feature 013 (spec D-9, plan decision 7, AC-13…AC-16). El orden de
    validacion es estricto y **ninguna** comprobacion escribe hasta la
    mutacion final:

    1. El ticket existe y esta en el alcance del rol -> **404** (inexistente y
       ajeno, identicos; D-8).
    2. El ticket esta en `Pendiente` (resuelto por nombre canonico; si el
       catalogo no lo contiene, fail-closed) -> si no, **409** sin tocar
       cabecera ni detalles (AC-14).
    3. Validacion total del payload: la prioridad existe (**404** nombrando la
       referencia) y todos los productos existen y pertenecen a la
       institucion del ticket (**404** identico para inexistente y ajeno;
       `_verificar_referencia`/`_verificar_productos`, misma regla que el
       alta). La forma del payload (asunto, cantidad no positiva, detalles
       vacios) la valida `TicketEditar` en Pydantic con 422 antes del
       servicio (AC-15).

    La escritura es atomica (AC-15, plan decision 7): la cabecera se
    actualiza, los detalles previos se **borran** y los nuevos se insertan en
    la MISMA transaccion; cualquier fallo revierte cabecera y detalles sin
    items parciales. No se tocan estado, solicitante, sede ni institucion
    (AC-13), el solicitante no se reatribuye (el payload no lleva
    `usuario_id`) y **no** se registra fila de historial: editar no es una
    mutacion de estado (D-10).
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise _ticket_no_encontrado()

    _verificar_alcance_de_ticket(db, ticket, identidad)

    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()
    estado_pendiente = _resolver_estado_por_nombre(
        estados, NOMBRE_ESTADO_PENDIENTE
    )
    if estado_pendiente is None or ticket.estado_id != estado_pendiente.estado_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La edicion solo se aplica a tickets en estado 'Pendiente'",
        )

    institucion_ticket = _institucion_de_ticket(db, ticket)
    _verificar_referencia(db, Prioridad, datos.prioridad_id, "prioridad")
    _verificar_productos(db, datos.detalles, institucion_ticket)

    try:
        ticket.asunto = datos.asunto
        ticket.descripcion = datos.descripcion
        ticket.prioridad_id = datos.prioridad_id

        # Reemplazo del conjunto completo de detalles (D-9): se borran los
        # previos y se insertan los nuevos en la MISMA transaccion que la
        # cabecera; sin escritura parcial (AC-15). `cantidad_entregada` en 0
        # es la misma regla del alta: en `Pendiente` nada fue entregado.
        db.execute(
            delete(DetalleTicket).where(
                DetalleTicket.ticket_id == ticket.ticket_id
            )
        )
        for detalle in datos.detalles:
            db.add(
                DetalleTicket(
                    ticket_id=ticket.ticket_id,
                    producto_id=detalle.producto_id,
                    cantidad_solicitada=detalle.cantidad_solicitada,
                    cantidad_entregada=0,
                    institucion_id=institucion_ticket,
                )
            )

        db.commit()
        db.refresh(ticket)
    except Exception:
        db.rollback()
        raise

    return ticket


def _cargar_ticket_para_detalle(db: Session, ticket_id: int) -> Ticket:
    """Ticket con TODO lo que `TicketDetalleRespuesta` serializa, eager.

    Los tres niveles de `detalles -> producto -> categoria` y las cuatro
    relaciones de cabecera (`usuario -> departamento`, `prioridad`, `estado` y
    `sede`) se precargan con `selectinload` en cadena: un numero FIJO de
    consultas en vez de una por nivel. La precarga eager tambien protege la
    lectura global del Superadmin (`global_service._LectorPostgres`): el DTO se
    construye dentro de la sesion de cada tenant, pero precargar garantiza que
    ningun `lazy="select"` dependa de una sesion ya cerrada al serializar
    (patron documentado en `listar_tickets`).
    """
    consulta = (
        select(Ticket)
        .options(
            selectinload(Ticket.detalles)
            .selectinload(DetalleTicket.producto)
            .selectinload(Producto.categoria),
            selectinload(Ticket.usuario).selectinload(Usuario.departamento),
            selectinload(Ticket.prioridad),
            selectinload(Ticket.estado),
            selectinload(Ticket.sede),
        )
        .where(Ticket.ticket_id == ticket_id)
    )
    ticket = db.execute(consulta).scalars().first()
    if ticket is None:
        raise _ticket_no_encontrado()
    return ticket


def obtener_ticket_detalle(
    db: Session, ticket_id: int, identidad: IdentidadAutenticada | None = None
) -> TicketDetalleRespuesta:
    """Detalle del ticket con cabecera, items y campos resueltos (spec §6, D-13).

    Feature 013 (AC-18/AC-19): el alcance es el mismo que en el resto de
    operaciones de tickets —el Solicitante lee los suyos, Administrador y
    Bodeguero los de su institucion y Superadmin con alcance global (la capa
    HTTP lo compone con `global_service.leer_global_unico` sobre la sesion de
    cada tenant)— y un ticket inexistente o fuera de alcance responde **404**
    identico, sin revelar existencia (D-8). Solo lectura: no muta nada.

    Los campos de presentacion (`estado_nombre`, `prioridad_nombre`,
    `solicitante_*`, `departamento_nombre`, `sede_nombre`) se resuelven aqui,
    en la capa de servicios, para que el DTO no dependa de la vista ni de la
    capa HTTP (AGENTS §6).
    """
    ticket = _cargar_ticket_para_detalle(db, ticket_id)
    _verificar_alcance_de_ticket(db, ticket, identidad)

    solicitante = ticket.usuario
    departamento = solicitante.departamento if solicitante is not None else None
    respuesta = TicketDetalleRespuesta.model_validate(ticket)
    respuesta.estado_nombre = ticket.estado.nombre if ticket.estado else None
    respuesta.prioridad_nombre = (
        ticket.prioridad.nombre if ticket.prioridad else None
    )
    respuesta.solicitante_id = ticket.usuario_id
    respuesta.solicitante_nombre = solicitante.nombre if solicitante else None
    respuesta.solicitante_apellido = (
        solicitante.apellido if solicitante else None
    )
    respuesta.solicitante_correo = solicitante.correo if solicitante else None
    respuesta.departamento_nombre = (
        departamento.nombre_dep if departamento else None
    )
    respuesta.sede_nombre = ticket.sede.nombre if ticket.sede else None
    return respuesta


def _fila_historial_a_respuesta(
    fila: HistorialTransicionTicket,
) -> HistorialTransicionRespuesta:
    """DTO de una fila del historial con sus estados y actor resueltos (AC-9)."""
    estado_origen = fila.estado_origen
    estado_destino = fila.estado_destino
    usuario = fila.usuario
    return HistorialTransicionRespuesta(
        historial_transicion_id=fila.historial_transicion_id,
        ticket_id=fila.ticket_id,
        estado_origen_id=fila.estado_origen_id,
        estado_destino_id=fila.estado_destino_id,
        usuario_id=fila.usuario_id,
        fecha_transicion=fila.fecha_transicion,
        motivo=fila.motivo,
        estado_origen_nombre=estado_origen.nombre if estado_origen else None,
        estado_destino_nombre=estado_destino.nombre if estado_destino else None,
        usuario_nombre=usuario.nombre if usuario else None,
        usuario_apellido=usuario.apellido if usuario else None,
    )


def obtener_historial_ticket(
    db: Session, ticket_id: int, identidad: IdentidadAutenticada | None = None
) -> List[HistorialTransicionRespuesta]:
    """Transiciones del ticket en orden determinista (spec §6, AC-9/AC-10).

    Mismo alcance por rol que el detalle (AC-18/AC-19): 404 identico para
    inexistente y fuera de alcance; Superadmin global via la capa HTTP. El
    orden es `fecha_transicion DESC, historial_transicion_id DESC` (mas
    reciente primero, desempate estable por id ante timestamps iguales de
    SQLite, que no tiene subsegundos). Un ticket sin transiciones devuelve la
    lista vacia; un ticket legado previo a la 013 no inventa filas (AC-12).

    Es la unica lectura del historial: no hay operacion publica de creacion,
    edicion o borrado de sus filas (AC-10). Las relaciones `estado_origen`,
    `estado_destino` y `usuario` se precargan eager para resolver los nombres
    de presentacion en un numero fijo de consultas y sin depender de sesiones
    ya cerradas (lector global del Superadmin).
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise _ticket_no_encontrado()
    _verificar_alcance_de_ticket(db, ticket, identidad)

    consulta = (
        select(HistorialTransicionTicket)
        .options(
            selectinload(HistorialTransicionTicket.estado_origen),
            selectinload(HistorialTransicionTicket.estado_destino),
            selectinload(HistorialTransicionTicket.usuario),
        )
        .where(HistorialTransicionTicket.ticket_id == ticket_id)
        .order_by(
            HistorialTransicionTicket.fecha_transicion.desc(),
            HistorialTransicionTicket.historial_transicion_id.desc(),
        )
    )
    return [
        _fila_historial_a_respuesta(fila)
        for fila in db.execute(consulta).scalars().all()
    ]
