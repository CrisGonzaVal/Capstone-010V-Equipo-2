from typing import List, Optional

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


class SedeExistenciaRespuesta(BaseModel):
    """Fila de `inventario` con el nombre del departamento resuelto.

    El nombre viaja desde el backend para que la vista no tenga que cruzar ids
    contra `/usuarios/departamentos`, que vive en otra feature
    (`docs/spec/features/002-catalogo-insumos/spec.md`, D-3).
    """

    inventario_id: int
    departamento_id: int
    departamento_nombre: str
    stock_actual: int
    ubicacion: Optional[str] = None


class ProductoExistenciaRespuesta(BaseModel):
    """Read model de `GET /inventario/existencias`.

    NO lleva `model_config = ConfigDict(from_attributes=True)`: lo arma el
    service a mano porque cruza cuatro tablas y agrega. Con `from_attributes`,
    Pydantic buscaria `stock_total`, `es_critico` y `sedes` en el objeto ORM y
    no los encontraria (spec D-7).
    """

    producto_id: int
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int
    categoria_id: int
    categoria_nombre: str
    stock_total: int
    es_critico: bool
    sedes: List[SedeExistenciaRespuesta]
