"""T2 (Feature 012): el espejo tenant de `institucion` no recibe `activo`.

Seam bajo prueba: la **metadata ORM**. El modelo `Institucion` es compartido por
control y tenants; la 012 separa el canonico de control (con `activo` y
`funcion_institucion`) del espejo tenant (solo `institucion_id` + `nombre`) sin
contaminar los tenants (D-1/D-2/D-6, diseno-tecnico.md §3).

Fase ROJA de TDD: el modelo de control dedicado (`app.models.control_canonico`)
aun no existe y `Institucion` todavia expone `rut`/`direccion`; cada prueba falla
por esa capacidad ausente, nunca por importacion ni sintaxis.
"""

from __future__ import annotations

import importlib

import pytest

from app.db.database import Base
from app.models.institucion import Institucion

COLUMNAS_ESPEJO = {"institucion_id", "nombre"}
CAPACIDADES = {
    "catalogo",
    "inventario",
    "tickets",
    "kanban",
    "dashboard",
    "gestion_organizacional",
}


def _modelo(nombre_modulo: str, nombre: str, motivo: str):
    try:
        modulo = importlib.import_module(nombre_modulo)
    except ImportError:
        pytest.fail(
            f"capacidad ausente (T3): falta el modulo {nombre_modulo} ({motivo})."
        )
    valor = getattr(modulo, nombre, None)
    if valor is None:
        pytest.fail(
            f"capacidad ausente (T3): {nombre_modulo}.{nombre} no existe ({motivo})."
        )
    return valor


# ---------------------------------------------------------------------------
# Espejo tenant: dos columnas, sin activo
# ---------------------------------------------------------------------------


def test_espejo_institucion_tiene_exactamente_dos_columnas():
    """D-1/AC-1: el espejo tenant se limita a `institucion_id` y `nombre`."""
    columnas = set(Institucion.__table__.columns.keys())
    assert columnas == COLUMNAS_ESPEJO, (
        "el espejo tenant `institucion` debe limitarse a "
        f"{sorted(COLUMNAS_ESPEJO)}; hoy tiene {sorted(columnas)}"
    )


def test_espejo_institucion_no_expone_activo():
    """D-2: `activo` es del canonico de control; nunca del espejo tenant."""
    assert not hasattr(Institucion, "activo"), (
        "`Institucion` (espejo tenant) no debe mapear `activo`"
    )
    assert "activo" not in Institucion.__table__.columns


def test_funcion_institucion_no_vive_en_la_metadata_tenant():
    """D-6: `funcion_institucion` es estructura auxiliar solo de control."""
    assert "funcion_institucion" not in Base.metadata.tables, (
        "`funcion_institucion` no debe formar parte de la metadata del tenant"
    )


# ---------------------------------------------------------------------------
# Canonico de control: activo y capacidades
# ---------------------------------------------------------------------------


def test_canonico_control_declara_institucion_con_activo():
    control_canonico = _modelo(
        "app.models.control_canonico", "InstitucionControl", "institucion canonica (T3)"
    )
    assert hasattr(control_canonico, "activo"), (
        "`InstitucionControl` debe mapear `activo` (control.institucion.activo)"
    )
    columnas = set(control_canonico.__table__.columns.keys())
    assert {"institucion_id", "nombre", "activo"} <= columnas, columnas


def test_canonico_control_declara_funcion_institucion():
    funcion = _modelo(
        "app.models.control_canonico", "FuncionInstitucion", "capacidades por tenant (T3)"
    )
    columnas = set(funcion.__table__.columns.keys())
    assert {"institucion_id", "funcion", "habilitada"} <= columnas, columnas
    pk = {col.name for col in funcion.__table__.primary_key.columns}
    assert pk == {"institucion_id", "funcion"}, pk


def test_canonico_control_expone_los_seis_identificadores():
    """D-6/AC-5: el conjunto cerrado de capacidades vive en la capa central."""
    capacidades = _modelo(
        "app.models.control_canonico", "CAPACIDADES", "conjunto cerrado de capacidades (T3)"
    )
    assert set(capacidades) == CAPACIDADES, capacidades


def test_canonico_control_tiene_metadata_propia():
    base_control = _modelo(
        "app.models.control_canonico", "BaseControl", "metadata control-only (T3)"
    )
    tablas = set(base_control.metadata.tables)
    assert "institucion" in tablas, tablas
    assert "funcion_institucion" in tablas, tablas
