from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.producto_schema import ProductoRespuesta


class InventarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inventario_id: int
    stock_actual: int
    ubicacion: Optional[str] = None
    departamento_id: int
    producto_id: int
    producto: Optional[ProductoRespuesta] = None


class MovimientoCrear(BaseModel):
    tipo_movimiento: str  # 'ENTRADA' o 'SALIDA'
    cantidad: int
    observacion: Optional[str] = None
    inventario_id: int
