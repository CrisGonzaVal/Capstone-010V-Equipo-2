from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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

# Estado que sella la fecha de cierre del ticket.
# Ver nota en tasks.md: el script de inicializacion no define los ids de
# estado_ticket (solo DDL, sin INSERT), asi que este 4 no tiene referente
# canonico. Sustituir por una busqueda por nombre en Feature 004/005.
ESTADO_CERRADO_ID = 4


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
    consulta = db.query(Ticket)
    if estado_id:
        consulta = consulta.filter(Ticket.estado_id == estado_id)
    return consulta.all()


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
    """
    _verificar_referencia(db, Usuario, datos.usuario_id, "usuario")
    _verificar_referencia(db, Prioridad, datos.prioridad_id, "prioridad")
    _verificar_referencia(db, EstadoTicket, datos.estado_id, "estado")
    _verificar_productos(db, datos.detalles)

    try:
        nuevo_ticket = Ticket(**datos.model_dump(exclude={"detalles"}))
        db.add(nuevo_ticket)
        db.flush()  # asigna ticket_id sin cerrar la transaccion

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
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")

    ticket.estado_id = estado_id
    if estado_id == ESTADO_CERRADO_ID:
        ticket.fecha_cierre = datetime.utcnow()

    db.commit()
    db.refresh(ticket)
    return ticket
