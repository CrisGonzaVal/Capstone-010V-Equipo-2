from datetime import datetime
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
    # Feature 008 (AC-8): institucion del inventario, derivada del departamento.
    institucion_id: Optional[str] = None
    producto: Optional[ProductoRespuesta] = None


class MovimientoInventarioRespuesta(BaseModel):
    """Read model de `GET /inventario/movimientos`.

    NO lleva `model_config = ConfigDict(from_attributes=True)`: la consulta
    cruza `movimiento_inventario`, `inventario`, `producto` y `departamento`
    con joins, asi que lo arma el service a partir de un mapping de columnas
    (plan §3.4). Sus campos son exactamente los del contrato de `spec.md` §5.
    """

    movimiento_id: int
    tipo_movimiento: str
    cantidad: int
    fecha_movimiento: datetime
    observacion: Optional[str] = None
    inventario_id: int
    producto_id: int
    producto_nombre: str
    departamento_id: int
    departamento_nombre: str
    ubicacion: Optional[str] = None
    # Feature 008 (AC-8): institucion del inventario del movimiento, para que las
    # lecturas globales del Superadmin atribuyan cada fila de auditoria.
    institucion_id: Optional[str] = None


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
    # Feature 008 (AC-8): institucion del producto, para la atribucion de las
    # lecturas globales del Superadmin.
    institucion_id: Optional[str] = None
    sedes: List[SedeExistenciaRespuesta]
