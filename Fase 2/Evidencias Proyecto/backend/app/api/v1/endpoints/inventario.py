from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.inventario_schema import InventarioRespuesta, MovimientoCrear
from app.schemas.producto_schema import (
    CategoriaRespuesta,
    ProductoCrear,
    ProductoRespuesta,
)
from app.services import inventario_service

router = APIRouter(prefix="/inventario", tags=["Inventario y Productos"])


@router.get(
    "/categorias",
    response_model=List[CategoriaRespuesta],
    summary="Listar categorias de productos",
)
def listar_categorias(db: Session = Depends(dependencies.get_db)):
    return inventario_service.listar_categorias(db)


@router.get(
    "/productos",
    response_model=List[ProductoRespuesta],
    summary="Listar productos del catalogo",
)
def listar_productos(db: Session = Depends(dependencies.get_db)):
    return inventario_service.listar_productos(db)


@router.post(
    "/productos",
    response_model=ProductoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un producto en el catalogo",
)
def crear_producto(datos: ProductoCrear, db: Session = Depends(dependencies.get_db)):
    return inventario_service.crear_producto(db, datos)


@router.get(
    "/stock",
    response_model=List[InventarioRespuesta],
    summary="Listar existencias, opcionalmente por departamento",
)
def listar_inventario(
    departamento_id: int = None, db: Session = Depends(dependencies.get_db)
):
    return inventario_service.listar_inventario(db, departamento_id)


@router.post(
    "/movimientos",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una entrada o salida de stock",
)
def registrar_movimiento(
    datos: MovimientoCrear, db: Session = Depends(dependencies.get_db)
):
    inventario = inventario_service.registrar_movimiento(db, datos)
    return {
        "message": "Movimiento registrado exitosamente",
        "nuevo_stock": inventario.stock_actual,
    }
