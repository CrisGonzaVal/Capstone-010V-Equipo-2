from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Inventario,
    MovimientoInventario,
    Prioridad,
    Producto,
    Ticket,
    Usuario,
)
from app.core import permisos
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    EstadoTicketRespuesta,
    PrioridadRespuesta,
    ProductoCatalogoRespuesta,
    SolicitanteRespuesta,
    TicketCrear,
    TicketDespacho,
)
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada
from app.services.inventario_service import TIPO_SALIDA, es_stock_critico

#: Nombres canonicos de los estados que gobiernan el despacho. Se buscan por
#: nombre (case-insensitive) y nunca por id fijo (D-1, plan §3.2).
NOMBRE_ESTADO_EN_CURSO = "encurso"
NOMBRE_ESTADO_CERRADO = "cerrado"

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


def _ticket_no_encontrado() -> HTTPException:
    """404 unico de ticket: oculta por igual el inexistente y el ajeno (D-5)."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado"
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
    existencias de los departamentos de esa misma institucion; el stock de otra
    institucion no influye. Superadmin (alcance global) ve el catalogo completo,
    cada producto atribuido con su `institucion_id` (AC-8).
    """
    institucion_id = _institucion_efectiva(db, identidad)

    prioridades = db.execute(
        select(Prioridad).order_by(Prioridad.prioridad_id)
    ).scalars().all()
    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()

    # Read model de producto + categoria + stock agregado. El `group_by` lista
    # TODAS las columnas del `SELECT` porque PostgreSQL 16 lo exige y SQLite es
    # mas laxo: un `group_by` incompleto passaria la suite en memoria y
    # reventaria en el contenedor.
    #
    # `outerjoin` + `coalesce`: un producto sin filas en `inventario` tiene que
    # salir en 0 y no en `None`, porque `stock_total` es `NOT NULL` en el DTO.
    condicion_inventario = Inventario.producto_id == Producto.producto_id
    if institucion_id is not None:
        # El `outerjoin` de inventario solo acepta existencias de departamentos
        # de la institucion del actor; el stock ajeno no entra al agregado.
        departamentos_propios = select(Departamento.departamento_id).where(
            Departamento.institucion_id == institucion_id
        )
        condicion_inventario = and_(
            condicion_inventario,
            Inventario.departamento_id.in_(departamentos_propios),
        )

    consulta_productos = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.institucion_id,
            Categoria.nombre_cat.label("categoria_nombre"),
            func.coalesce(func.sum(Inventario.stock_actual), 0).label("stock_total"),
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(Inventario, condicion_inventario)
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
                es_critico=es_stock_critico(fila.stock_total, fila.stock_minimo),
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

    `selectinload` en cadena resuelve `detalles` y el `producto` anidado que
    `DetalleTicketRespuesta` serializa en un numero FIJO de consultas, en vez de
    una por ticket y otra por detalle. Se descarta `joinedload` en la coleccion
    porque multiplicaria las filas del ticket por cada detalle.

    El filtro por `estado_id` se comprueba con `is not None`: un `0` o un id
    valido nunca deben confundirse con "sin filtro".

    Feature 007 (D-3/AC-6/AC-8): la lectura se acota por rol; el Solicitante ve
    solo sus tickets y Administrador/Bodeguero, los de su institucion.
    """
    consulta = (
        select(Ticket)
        .options(
            selectinload(Ticket.detalles).selectinload(DetalleTicket.producto)
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

    # Determinar si el estado destino es "Cerrado" (case-insensitive)
    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()
    estado_cierre = next(
        (e for e in estados if e.nombre.casefold() == "cerrado"), None
    )
    es_estado_cierre = (
        estado_cierre is not None and datos.estado_id == estado_cierre.estado_id
    )

    try:
        nuevo_ticket = Ticket(
            **datos.model_dump(exclude={"detalles"}),
            institucion_id=institucion_ticket,
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
    """Aplica una transicion del flujo lineal y sella el cierre, atomicamente.

    Orden de validacion (D-8): ticket (404) -> estado pedido (404) -> flujo
    (409). El flujo se evalua sobre los indices del catalogo ordenado por
    `estado_id` (D-1): un paso en cualquier direccion entre contiguos; el
    indice actual igual al destino, la distancia != 1 y cualquier salida
    desde el ultimo estado (terminal) rechazan sin tocar el ticket (D-2).

    El cierre se reconoce por nombre `casefold() == "cerrado"` sobre ese
    mismo catalogo, nunca por un id fijo (D-3); si el nombre esta repetido,
    gana el de menor `estado_id`. La fecha solo se escribe si aun es `None`:
    reentrar en `Cerrado` jamas la sobrescribe. El unico `commit` del final
    hace estado y fecha una sola operacion (`constitucion.md` §3).

    Feature 005 (AC-15, D-1/D-12): la transicion `EnCurso -> Cerrado` esta
    **reservada al despacho transaccional**. Cuando el ticket esta en el
    `EnCurso` canonico y el destino es el `Cerrado` canonico, se responde 409
    con el detalle literal que dirige al endpoint de despacho, sin mutar el
    ticket. Ambos estados se resuelven por **nombre** (menor `estado_id` ante
    duplicados), nunca por el ultimo ordinal: en un catalogo degenerado el
    ultimo estado podria no ser `Cerrado`. La guardia va despues de validar el
    flujo (orden D-8) y antes de cualquier escritura.

    Feature 007 (D-5/AC-6): tras comprobar la existencia se verifica el alcance
    del rol; un ticket de otra institucion (Administrador/Bodeguero) o ajeno al
    Solicitante responde 404, igual que uno inexistente, antes de tocar nada.
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

    indice_actual = next(
        (i for i, e in enumerate(estados) if e.estado_id == ticket.estado_id), None
    )
    fuera_de_flujo = (
        indice_actual is None  # el ticket esta en un estado ya borrado
        or indice_destino == indice_actual
        or abs(indice_destino - indice_actual) != 1
        or indice_actual == len(estados) - 1  # el terminal no se sale nunca
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

    # Guardia AC-15 de la 005 (D-1, D-12): el cierre `EnCurso -> Cerrado` esta
    # reservado al despacho transaccional para que ningun cierre evite la rebaja
    # y la auditoria atomicas (`constitucion.md` §3). Se resuelve por **nombre
    # canonico** (menor `estado_id` ante duplicados) y no por el ultimo ordinal,
    # que en un catalogo degenerado podria no ser `Cerrado`. Va despues del flujo
    # (orden D-8) y antes de tocar el ticket.
    estado_en_curso = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_EN_CURSO)
    estado_cierre = _resolver_estado_por_nombre(estados, NOMBRE_ESTADO_CERRADO)
    if (
        estado_en_curso is not None
        and estado_cierre is not None
        and ticket.estado_id == estado_en_curso.estado_id
        and estado_destino.estado_id == estado_cierre.estado_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El cierre requiere despacho; use "
                f"POST /api/v1/tickets/{ticket_id}/despacho"
            ),
        )

    ticket.estado_id = estado_id
    if (
        estado_cierre is not None
        and estado_destino.estado_id == estado_cierre.estado_id
        and ticket.fecha_cierre is None
    ):
        ticket.fecha_cierre = datetime.utcnow()

    db.commit()
    db.refresh(ticket)
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
    solicitante y tanto el producto de cada detalle como el inventario que se
    rebaja deben pertenecer a esa misma institucion. Una referencia cruzada es
    una inconsistencia que impide resolver el despacho: responde **409**, se
    evalua antes de cualquier escritura y, como el resto de rechazos, no deja
    stock, entrega, estado ni auditoria parciales en la unica transaccion.
    """
    ticket = db.execute(
        select(Ticket).where(Ticket.ticket_id == ticket_id).with_for_update()
    ).scalar_one_or_none()
    if ticket is None:
        raise _ticket_no_encontrado()

    _verificar_alcance_de_ticket(db, ticket, identidad)

    # Institucion del ticket (la de su solicitante): todo detalle y el inventario
    # que se rebaje debe pertenecer a ella (D-2, AC-12).
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

    ids_producto = sorted({detalle.producto_id for detalle in detalles})

    filas_inventario = db.execute(
        select(Inventario).where(Inventario.producto_id.in_(ids_producto))
    ).scalars().all()
    inventario_por_producto: dict[int, list[Inventario]] = {}
    for fila in filas_inventario:
        inventario_por_producto.setdefault(fila.producto_id, []).append(fila)

    cantidad_requerida: dict[int, int] = {}
    for detalle in detalles:
        cantidad_requerida[detalle.producto_id] = (
            cantidad_requerida.get(detalle.producto_id, 0)
            + detalle.cantidad_solicitada
        )

    inventario_unico: dict[int, Inventario] = {}
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
        filas = inventario_por_producto.get(producto_id, [])
        if len(filas) != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El producto {producto_id} requiere exactamente una fila de "
                    f"inventario para despachar y tiene {len(filas)}"
                ),
            )
        inventario = filas[0]
        # AC-12: el inventario que se rebaja debe ser de la institucion del
        # ticket (su institucion se deriva del departamento).
        if not ambito_service.pertenece_al_alcance(
            ambito_service.institucion_de_inventario(db, inventario),
            institucion_ticket,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El inventario {inventario.inventario_id} del producto "
                    f"{producto_id} no pertenece a la institucion del ticket"
                ),
            )
        inventario_unico[producto_id] = inventario

    for producto_id, requerido in cantidad_requerida.items():
        disponible = inventario_unico[producto_id].stock_actual
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
            inventario = inventario_unico[detalle.producto_id]
            inventario.stock_actual -= detalle.cantidad_solicitada
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
                    inventario_id=inventario.inventario_id,
                )
            )

        ticket.estado_id = estado_cerrado.estado_id
        if ticket.fecha_cierre is None:
            ticket.fecha_cierre = datetime.utcnow()

        db.commit()
        db.refresh(ticket)
    except Exception:
        db.rollback()
        raise

    return ticket
