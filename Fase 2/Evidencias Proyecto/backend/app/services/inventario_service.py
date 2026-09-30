from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Categoria, Inventario, MovimientoInventario, Producto
from app.schemas.inventario_schema import MovimientoCrear
from app.schemas.producto_schema import ProductoCrear

TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA = "SALIDA"


def listar_categorias(db: Session) -> List[Categoria]:
    return db.query(Categoria).all()


def listar_productos(db: Session) -> List[Producto]:
    return db.query(Producto).all()


def crear_producto(db: Session, datos: ProductoCrear) -> Producto:
    nuevo_producto = Producto(**datos.model_dump())
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return nuevo_producto


def listar_inventario(db: Session, departamento_id: Optional[int] = None) -> List[Inventario]:
    consulta = db.query(Inventario)
    if departamento_id:
        consulta = consulta.filter(Inventario.departamento_id == departamento_id)
    return consulta.all()


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
