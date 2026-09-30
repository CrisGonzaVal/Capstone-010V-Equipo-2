"""Modelos SQLAlchemy del dominio, agrupados por modulo funcional.

Re-exporta los 12 modelos para que `from app.models import Ticket` siga siendo
valido, igual que cuando vivian todos en `models.py`. El re-export tambien
garantiza que SQLAlchemy los registre todos antes de configurar los mappers.
"""

from app.db.database import Base
from app.models.institucion import Departamento, Institucion
from app.models.inventario import Inventario, MovimientoInventario
from app.models.producto import Categoria, Producto
from app.models.rol import Rol
from app.models.ticket import DetalleTicket, EstadoTicket, Prioridad, Ticket
from app.models.usuario import Usuario

__all__ = [
    "Base",
    "Categoria",
    "Departamento",
    "DetalleTicket",
    "EstadoTicket",
    "Institucion",
    "Inventario",
    "MovimientoInventario",
    "Prioridad",
    "Producto",
    "Rol",
    "Ticket",
    "Usuario",
]
