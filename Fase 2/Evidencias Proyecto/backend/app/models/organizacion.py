"""Tabla puente auxiliar del modelo organizacional (Feature 011).

`DepartamentoEncargado` no es una entidad de dominio: es la asociacion auxiliar
muchos-a-muchos entre departamentos y sus encargados, del mismo modo que
`mapa_usuario_esquema` es auxiliar al modelo de doce entidades (ver la seccion
aprobada de `docs/spec/stack.md` "Evolucion del modelo organizacional e inventario
por sede"). Un departamento admite **varios** encargados (spec D-4), y cada uno es
un usuario Solicitante que pertenece al mismo departamento.

La tabla solo guarda la asociacion; las reglas de compatibilidad (rol, pertenencia,
usuario activo) las valida y filtra el servicio, sin triggers (spec D-4).
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DepartamentoEncargado(Base):
    """Asociacion `departamento <-> usuario encargado` (spec D-4)."""

    __tablename__ = "departamento_encargado"
    __table_args__ = (
        # Un usuario no puede repetir como encargado del mismo departamento; si
        # puede serlo de otro departamento distinto.
        UniqueConstraint(
            "departamento_id", "usuario_id", name="departamento_encargado_uk"
        ),
    )

    departamento_encargado_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    departamento_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departamento.departamento_id"),
        nullable=False,
        index=True,
    )
    usuario_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("usuario.usuario_id"),
        nullable=False,
        index=True,
    )

    departamento = relationship(
        "Departamento",
        primaryjoin="DepartamentoEncargado.departamento_id == Departamento.departamento_id",
        foreign_keys="DepartamentoEncargado.departamento_id",
    )
    usuario = relationship(
        "Usuario",
        primaryjoin="DepartamentoEncargado.usuario_id == Usuario.usuario_id",
        foreign_keys="DepartamentoEncargado.usuario_id",
    )
