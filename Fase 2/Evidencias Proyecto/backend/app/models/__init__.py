"""Modelos SQLAlchemy del dominio, agrupados por modulo funcional.

Re-exporta los modelos para que `from app.models import Ticket` siga siendo
valido, igual que cuando vivian todos en `models.py`. El re-export tambien
garantiza que SQLAlchemy los registre todos antes de configurar los mappers, y que
`Base.metadata` (DDL por esquema, `schema_translate_map`) vea las entidades nuevas
de la Feature 011 (`Sede`, `StockSede`, `DepartamentoEncargado`).
"""

from app.db.database import Base
from app.models.control import (
    ESTADOS_INVITACION,
    TIPOS_REGISTRO_MOTIVO,
    MapaUsuarioEsquema,
    RegistroMotivoConstancia,
    VersionEsquema,
)
from app.models.control_canonico import (
    CAPACIDADES,
    BaseControl,
    FuncionInstitucion,
    InstitucionControl,
)
from app.models.institucion import Departamento, Institucion
from app.models.inventario import Inventario, MovimientoInventario
from app.models.organizacion import DepartamentoEncargado
from app.models.producto import (
    Categoria,
    HistorialTransicionCategoria,
    HistorialTransicionProducto,
    Producto,
)
from app.models.rol import Rol
from app.models.sede import Sede, StockSede
from app.models.ticket import (
    DetalleTicket,
    EstadoTicket,
    HistorialTransicionTicket,
    Prioridad,
    Ticket,
)
from app.models.usuario import Usuario

__all__ = [
    "CAPACIDADES",
    "Base",
    "BaseControl",
    "Categoria",
    "Departamento",
    "DepartamentoEncargado",
    "DetalleTicket",
    "ESTADOS_INVITACION",
    "EstadoTicket",
    "FuncionInstitucion",
    "HistorialTransicionCategoria",
    "HistorialTransicionProducto",
    "HistorialTransicionTicket",
    "Institucion",
    "InstitucionControl",
    "Inventario",
    "MapaUsuarioEsquema",
    "MovimientoInventario",
    "Prioridad",
    "Producto",
    "RegistroMotivoConstancia",
    "Rol",
    "Sede",
    "StockSede",
    "TIPOS_REGISTRO_MOTIVO",
    "Ticket",
    "Usuario",
    "VersionEsquema",
]
