from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Inventario,
    Prioridad,
    Producto,
    Ticket,
    Usuario,
)
from app.schemas.ticket_schema import (
    CatalogosTicketRespuesta,
    EstadoTicketRespuesta,
    PrioridadRespuesta,
    ProductoCatalogoRespuesta,
    SolicitanteRespuesta,
    TicketCrear,
)
from app.services.inventario_service import es_stock_critico


def obtener_catalogos(db: Session) -> CatalogosTicketRespuesta:
    """Read model de los cuatro catalogos que necesita el modal de alta.

    Cada lista se arma con la tecnica que le corresponde y no con una sola
    consulta para todo: los cuatro conjuntos no comparten clave y un `UNION`
    obligaria a castear filas de 3 columnas a 5.

    `es_critico` sale de `es_stock_critico()`, la MISMA funcion que aplica
    `GET /inventario/existencias`. Importar una funcion pura de otro service no
    duplica logica de negocio ni cruza features (esta es la capa de servicios):
    si la regla del stock critico cambia, cambia en un solo sitio.
    """
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
    consulta_productos = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Categoria.nombre_cat.label("categoria_nombre"),
            func.coalesce(func.sum(Inventario.stock_actual), 0).label("stock_total"),
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(Inventario, Inventario.producto_id == Producto.producto_id)
        .group_by(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Categoria.nombre_cat,
        )
        .order_by(Producto.nombre, Producto.producto_id)
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
            )
            for fila in db.execute(consulta_productos).all()
        ],
        solicitantes=[
            SolicitanteRespuesta.model_validate(fila)
            for fila in db.execute(consulta_solicitantes).mappings().all()
        ],
    )


def listar_tickets(db: Session, estado_id: Optional[int] = None) -> List[Ticket]:
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
    """
    consulta = (
        select(Ticket)
        .options(
            selectinload(Ticket.detalles).selectinload(DetalleTicket.producto)
        )
        .order_by(Ticket.fecha_creacion.desc(), Ticket.ticket_id.desc())
    )
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


def _verificar_productos(db: Session, detalles) -> None:
    """Valida todos los `producto_id` del payload antes de escribir nada.

    Los ids se deduplican con un `set` para que cinco lineas del mismo producto
    costen una sola busqueda, y el mensaje reporta **el id mas bajo** que falta
    (`sorted`) para que sea determinista entre ejecuciones.
    """
    ids_requeridos = {detalle.producto_id for detalle in detalles}
    faltantes = [id_ for id_ in sorted(ids_requeridos) if db.get(Producto, id_) is None]
    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe producto indicado: {faltantes[0]}",
        )


def crear_ticket(db: Session, datos: TicketCrear) -> Ticket:
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

    AC-17: si el estado destino es `Cerrado` (case-insensitive), se sella
    `fecha_cierre` en la propia creacion.
    """
    _verificar_referencia(db, Usuario, datos.usuario_id, "usuario")
    _verificar_referencia(db, Prioridad, datos.prioridad_id, "prioridad")
    _verificar_referencia(db, EstadoTicket, datos.estado_id, "estado")
    _verificar_productos(db, datos.detalles)

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
        nuevo_ticket = Ticket(**datos.model_dump(exclude={"detalles"}))
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
                )
            )

        db.commit()
        db.refresh(nuevo_ticket)
    except Exception:
        db.rollback()
        raise

    return nuevo_ticket


def actualizar_estado_ticket(db: Session, ticket_id: int, estado_id: int) -> Ticket:
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
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

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
    estado_cierre = next(
        (e for e in estados if e.nombre.casefold() == "cerrado"), None
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
