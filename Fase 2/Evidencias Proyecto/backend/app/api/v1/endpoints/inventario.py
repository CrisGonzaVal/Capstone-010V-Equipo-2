from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.models import Producto, Inventario, MovimientoInventario, Categoria
from app.schemas.schemas import ProductoCreate, ProductoResponse, InventarioResponse, MovimientoCreate, CategoriaResponse

router = APIRouter(prefix="/inventario", tags=["Inventario y Productos"])

@router.get("/categorias", response_model=List[CategoriaResponse])
def listar_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).all()

@router.get("/productos", response_model=List[ProductoResponse])
def listar_productos(db: Session = Depends(get_db)):
    return db.query(Producto).all()

@router.post("/productos", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
def crear_producto(producto: ProductoCreate, db: Session = Depends(get_db)):
    db_producto = Producto(**producto.model_dump())
    db.add(db_producto)
    db.commit()
    db.refresh(db_producto)
    return db_producto

@router.get("/stock", response_model=List[InventarioResponse])
def listar_inventario(departamento_id: int = None, db: Session = Depends(get_db)):
    query = db.query(Inventario)
    if departamento_id:
        query = query.filter(Inventario.departamento_id == departamento_id)
    return query.all()

@router.post("/movimientos", status_code=status.HTTP_201_CREATED)
def registrar_movimiento(movimiento: MovimientoCreate, db: Session = Depends(get_db)):
    inventario = db.query(Inventario).filter(Inventario.inventario_id == movimiento.inventario_id).first()
    if not inventario:
        raise HTTPException(status_code=404, detail="Inventario no encontrado")
    
    if movimiento.tipo_movimiento.upper() == 'ENTRADA':
        inventario.stock_actual += movimiento.cantidad
    elif movimiento.tipo_movimiento.upper() == 'SALIDA':
        if inventario.stock_actual < movimiento.cantidad:
            raise HTTPException(status_code=400, detail="Stock insuficiente para realizar la salida")
        inventario.stock_actual -= movimiento.cantidad
    else:
        raise HTTPException(status_code=400, detail="Tipo de movimiento inválido (Use 'ENTRADA' o 'SALIDA')")

    db_mov = MovimientoInventario(**movimiento.model_dump())
    db.add(db_mov)
    db.commit()
    
    return {"message": "Movimiento registrado exitosamente", "nuevo_stock": inventario.stock_actual}
