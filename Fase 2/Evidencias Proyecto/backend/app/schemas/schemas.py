from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# --- USUARIOS & ROLES ---
class UsuarioBase(BaseModel):
    nombre: str
    apellido: str
    correo: EmailStr
    departamento_id: int
    rol_id: int

class UsuarioCreate(UsuarioBase):
    password: str

class UsuarioResponse(UsuarioBase):
    usuario_id: int
    
    class Config:
        from_attributes = True


# --- PRODUCTOS & CATEGORIAS ---
class CategoriaResponse(BaseModel):
    categoria_id: int
    nombre_cat: str
    descripcion_cat: Optional[str] = None

    class Config:
        from_attributes = True

class ProductoBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int = 0
    categoria_id: int

class ProductoCreate(ProductoBase):
    pass

class ProductoResponse(ProductoBase):
    producto_id: int
    categoria: Optional[CategoriaResponse] = None

    class Config:
        from_attributes = True


# --- INVENTARIO & MOVIMIENTOS ---
class InventarioResponse(BaseModel):
    inventario_id: int
    stock_actual: int
    ubicacion: Optional[str] = None
    departamento_id: int
    producto_id: int
    producto: Optional[ProductoResponse] = None

    class Config:
        from_attributes = True

class MovimientoCreate(BaseModel):
    tipo_movimiento: str  # 'ENTRADA' o 'SALIDA'
    cantidad: int
    observacion: Optional[str] = None
    inventario_id: int


# --- TICKETS & KANBAN ---
class DetalleTicketCreate(BaseModel):
    producto_id: int
    cantidad_solicitada: int

class DetalleTicketResponse(BaseModel):
    detalle_ticket_id: int
    producto_id: int
    cantidad_solicitada: int
    cantidad_entregada: int
    producto: Optional[ProductoResponse] = None

    class Config:
        from_attributes = True

class TicketCreate(BaseModel):
    usuario_id: int
    prioridad_id: int
    estado_id: int
    asunto: str
    descripcion: Optional[str] = None
    detalles: List[DetalleTicketCreate]

class TicketUpdateEstado(BaseModel):
    estado_id: int

class TicketResponse(BaseModel):
    ticket_id: int
    usuario_id: int
    prioridad_id: int
    estado_id: int
    asunto: str
    descripcion: Optional[str] = None
    fecha_creacion: datetime
    fecha_cierre: Optional[datetime] = None
    detalles: List[DetalleTicketResponse] = []

    class Config:
        from_attributes = True
