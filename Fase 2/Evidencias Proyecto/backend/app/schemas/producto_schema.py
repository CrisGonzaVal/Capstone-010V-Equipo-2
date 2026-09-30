from typing import Optional

from pydantic import BaseModel, ConfigDict


class CategoriaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    categoria_id: int
    nombre_cat: str
    descripcion_cat: Optional[str] = None


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
    categoria: Optional[CategoriaRespuesta] = None
