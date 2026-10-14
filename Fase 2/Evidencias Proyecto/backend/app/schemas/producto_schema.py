from typing import Optional

from pydantic import BaseModel, ConfigDict


class CategoriaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    categoria_id: int
    nombre_cat: str
    descripcion_cat: Optional[str] = None
    # Feature 008 (AC-8): atribucion institucional para las lecturas globales del
    # Superadmin. Campo informativo; el servidor no acepta institucion del cliente.
    institucion_id: Optional[str] = None


class ProductoBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int = 0
    categoria_id: int


class ProductoCrear(ProductoBase):
    pass


class ProductoRespuesta(ProductoBase):
    model_config = ConfigDict(from_attributes=True)

    producto_id: int
    # Feature 008 (AC-8): institucion de pertenencia del producto, para que las
    # lecturas globales del Superadmin atribuyan cada registro.
    institucion_id: Optional[str] = None
    categoria: Optional[CategoriaRespuesta] = None
