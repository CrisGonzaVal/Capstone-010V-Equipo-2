from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Categoria, Departamento, Inventario, MovimientoInventario, Producto
from app.schemas.inventario_schema import (
    MovimientoCrear,
    ProductoExistenciaRespuesta,
    SedeExistenciaRespuesta,
)
from app.schemas.producto_schema import ProductoCrear

TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA = "SALIDA"


def es_stock_critico(stock_actual: int, stock_minimo: int) -> bool:
    """Regla unica de stock critico (`spec.md` D-5).

    La usan tanto el armado de la respuesta como el filtro `solo_criticos`, para
    que el estado que ve el usuario y el filtro que produjo su lista no puedan
    discrepar. El `<=` es deliberado: con `stock_minimo = 0` (default del modelo)
    un producto en cero queda marcado como critico, que es lo correcto.
    """
    return stock_actual <= stock_minimo


def listar_categorias(db: Session) -> List[Categoria]:
    return db.query(Categoria).order_by(Categoria.nombre_cat).all()


def listar_productos(db: Session) -> List[Producto]:
    # `selectinload` evita el N+1: sin el, cada producto dispara su propia consulta
    # a `categoria` al serializar la respuesta.
    return (
        db.query(Producto)
        .options(selectinload(Producto.categoria))
        .order_by(Producto.nombre, Producto.producto_id)
        .all()
    )


def crear_producto(db: Session, datos: ProductoCrear) -> Producto:
    # Sin esta comprobacion, la FK viola en el `commit()` y FastAPI responde 500
    # a un cliente que solo mando una categoria que no existe (spec D-8).
    if db.get(Categoria, datos.categoria_id) is None:
        raise HTTPException(status_code=404, detail="No existe la categoria indicada")

    nuevo_producto = Producto(**datos.model_dump())
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return nuevo_producto


def listar_inventario(db: Session, departamento_id: Optional[int] = None) -> List[Inventario]:
    consulta = db.query(Inventario)
    if departamento_id:
        consulta = consulta.filter(Inventario.departamento_id == departamento_id)
    return consulta.order_by(Inventario.inventario_id).all()


def listar_existencias(
    db: Session,
    q: Optional[str] = None,
    categoria_id: Optional[int] = None,
    departamento_id: Optional[int] = None,
    solo_criticos: bool = False,
) -> List[ProductoExistenciaRespuesta]:
    """Un elemento por producto del catalogo, con su stock y el desglose por sede.

    Es la unica lectura que cruza varias tablas, asi que -a diferencia del resto
    del servicio- usa `select()` de SQLAlchemy 2.0 con los onclause explicitos
    (`plan.md` §3.2.2). `categoria` entra con join interno porque
    `producto.categoria_id` es NOT NULL con FK; `inventario` y `departamento`
    entran con `outerjoin` para que un producto sin existencias no desaparezca
    del catalogo (spec D-4).
    """
    consulta = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.descripcion,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Categoria.categoria_id,
            Categoria.nombre_cat,
            Inventario.inventario_id,
            Inventario.stock_actual,
            Inventario.ubicacion,
            Departamento.departamento_id,
            Departamento.nombre_dep,
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(Inventario, Producto.producto_id == Inventario.producto_id)
        .outerjoin(Departamento, Inventario.departamento_id == Departamento.departamento_id)
    )

    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(Producto.nombre.ilike(patron) | Producto.descripcion.ilike(patron))
    if categoria_id is not None:
        consulta = consulta.where(Categoria.categoria_id == categoria_id)
    if departamento_id is not None:
        # Degrada el `outerjoin` de inventario a INNER: aqui solo interesan los
        # productos que tienen existencias en esa sede.
        consulta = consulta.where(Inventario.departamento_id == departamento_id)

    consulta = consulta.order_by(
        Producto.nombre,
        Producto.producto_id,
        Departamento.nombre_dep,
        Departamento.departamento_id,
    )

    # Acumulador por producto. Las claves coinciden con los campos del schema
    # salvo `es_critico`, que se calcula al final, asi que el DTO se arma con
    # `**acumulador` sin ir completando un BaseModel mutable.
    acumuladores: dict[int, dict] = {}

    for fila in db.execute(consulta).all():
        if fila.producto_id not in acumuladores:
            acumuladores[fila.producto_id] = {
                "producto_id": fila.producto_id,
                "nombre": fila.nombre,
                "descripcion": fila.descripcion,
                "unidad_medida": fila.unidad_medida,
                "stock_minimo": fila.stock_minimo,
                "categoria_id": fila.categoria_id,
                "categoria_nombre": fila.nombre_cat,
                "stock_total": 0,
                "sedes": [],
            }
        acumulador = acumuladores[fila.producto_id]

        # `inventario_id` llega en None cuando el producto no tiene existencias.
        if fila.inventario_id is not None:
            acumulador["stock_total"] += fila.stock_actual
            acumulador["sedes"].append(
                SedeExistenciaRespuesta(
                    inventario_id=fila.inventario_id,
                    departamento_id=fila.departamento_id,
                    departamento_nombre=fila.nombre_dep,
                    stock_actual=fila.stock_actual,
                    ubicacion=fila.ubicacion,
                )
            )

    # `dict` conserva el orden de insercion, asi que el `ORDER BY` se propaga
    # solo y no hay que reordenar.
    existencias = [
        ProductoExistenciaRespuesta(
            **acumulador,
            es_critico=es_stock_critico(acumulador["stock_total"], acumulador["stock_minimo"]),
        )
        for acumulador in acumuladores.values()
    ]

    # `solo_criticos` no cabe en el `WHERE`: es un predicado sobre `stock_total`,
    # que no existe hasta agrupar. La base ya filtro por texto, categoria y sede.
    if solo_criticos:
        existencias = [existencia for existencia in existencias if existencia.es_critico]

    return existencias


def registrar_movimiento(db: Session, movimiento: MovimientoCrear) -> Inventario:
    """Aplica un movimiento de stock y deja rastro en `movimiento_inventario`.

    Trazabilidad Absoluta (`constitucion.md` §2): el registro de auditoria se
    escribe en la misma transaccion que la mutacion del stock, o no se escribe.
    """
    inventario = (
        db.query(Inventario)
        .filter(Inventario.inventario_id == movimiento.inventario_id)
        .first()
    )
    if not inventario:
        raise HTTPException(status_code=404, detail="Inventario no encontrado")

    tipo = movimiento.tipo_movimiento.upper()
    if tipo == TIPO_ENTRADA:
        inventario.stock_actual += movimiento.cantidad
    elif tipo == TIPO_SALIDA:
        if inventario.stock_actual < movimiento.cantidad:
            raise HTTPException(
                status_code=400,
                detail="Stock insuficiente para realizar la salida",
            )
        inventario.stock_actual -= movimiento.cantidad
    else:
        raise HTTPException(
            status_code=400,
            detail="Tipo de movimiento invalido (Use 'ENTRADA' o 'SALIDA')",
        )

    db.add(MovimientoInventario(**movimiento.model_dump()))
    db.commit()
    db.refresh(inventario)
    return inventario
