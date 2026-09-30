from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.inventario_schema import (
    InventarioRespuesta,
    MovimientoCrear,
    ProductoExistenciaRespuesta,
)
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
    status_code=status.HTTP_200_OK,
    summary="Listar categorias de productos",
)
def listar_categorias(db: Session = Depends(dependencies.get_db)):
    return inventario_service.listar_categorias(db)


@router.get(
    "/productos",
    response_model=List[ProductoRespuesta],
    status_code=status.HTTP_200_OK,
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
    "/existencias",
    response_model=List[ProductoExistenciaRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Catalogo de insumos con existencias agrupadas por producto",
    description=(
        "Devuelve **un elemento por producto del catalogo**, con el total de stock "
        "y el desglose por sede. Un producto sin existencias aparece con `sedes` "
        "vacio y `stock_total` en 0, en vez de desaparecer. `solo_criticos` se "
        "evalua sobre el total: un producto con `stock_total <= stock_minimo` "
        "queda marcado como critico."
    ),
)
def listar_existencias(
    q: Optional[str] = Query(
        default=None,
        description="Busqueda parcial, sin distincion de mayusculas, sobre nombre y descripcion.",
    ),
    categoria_id: Optional[int] = Query(default=None, description="Filtra por categoria."),
    departamento_id: Optional[int] = Query(
        default=None, description="Acota el stock y las sedes a un departamento.",
    ),
    solo_criticos: bool = Query(
        default=False, description="Deja solo los productos con stock igual o bajo el minimo."
    ),
    db: Session = Depends(dependencies.get_db),
):
    return inventario_service.listar_existencias(
        db,
        q=q,
        categoria_id=categoria_id,
        departamento_id=departamento_id,
        solo_criticos=solo_criticos,
    )


@router.get(
    "/stock",
    response_model=List[InventarioRespuesta],
    status_code=status.HTTP_200_OK,
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
