"""Servicio de capacidades funcionales por institucion (Feature 012, D-6/AC-5).

Lee el estado de una capacidad de una institucion desde la estructura auxiliar
`control.funcion_institucion`. Es la consulta que compone el gating adicional a
la matriz central: el rol autorizado por la matriz puede seguir recibiendo 403 si
la capacidad funcional de su institucion esta apagada.

Regla de ausencia de fila (diseno-tecnico.md §2): el aprovisionamiento y la
migracion siembran **siempre** las seis filas por institucion, de modo que la
ausencia de una fila no es una desactivacion explicita. Siguiendo D-6 ("no se
infiere el estado a partir de datos presentes"), una fila ausente se trata como
**habilitada**: la capacidad solo se deshabilita con `habilitada = False`
explicito. Esto evita que una institucion historica (o un contexto de prueba sin
siembra) quede inutilizada por la mera ausencia de la fila de capacidad.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.control_canonico import FuncionInstitucion


def capacidad_habilitada(db: Session, institucion_id: str, funcion: str) -> bool:
    """`True` si la capacidad `funcion` de `institucion_id` no esta apagada.

    Devuelve `False` **solo** si existe una fila con `habilitada = False`. Una
    institucion sin fila para esa capacidad (o una fila con `habilitada = True`)
    devuelve `True`: la desactivacion es un estado explicito persistido, no una
    ausencia (diseno-tecnico.md §2).
    """
    habilitada = db.execute(
        select(FuncionInstitucion.habilitada).where(
            FuncionInstitucion.institucion_id == institucion_id,
            FuncionInstitucion.funcion == funcion,
        )
    ).scalar_one_or_none()
    return habilitada is not False
