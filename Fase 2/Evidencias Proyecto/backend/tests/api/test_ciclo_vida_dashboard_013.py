"""T2 (Feature 013): KPI de «tickets activos» del dashboard (AC-22).

Seam bajo prueba: la interfaz HTTP (`TestClient`) sobre `GET /dashboard/`.
La 009 contaba como activo todo ticket cuyo estado no es exactamente
`Cerrado`; con el estado nuevo, un ticket `Anulado` contaria para siempre.
La regla pasa a excluir **ambos** nombres canonicos (`Cerrado` y `Anulado`),
por nombre exacto (sin ids fijos y sin insensibilidad al casing, conservando
la decision documentada de la 009), sin tocar el resto de KPI, el log de
alertas ni el ambito por rol.

Fase ROJA de TDD: hoy `Anulado` sigue contando como activo, de modo que los
conteos nuevos caen en rojo por esa ausencia; el test de regresion del resto
del dashboard ya pasa y debe seguirlo pasando.
"""

from __future__ import annotations

import pytest

from ._soporte_ciclo_vida_013 import (
    cliente_con_rol,
    sembrar_mundo_013,
    sembrar_ticket,
)

#: El catalogo instala ademas el estado `anulado` en minusculas: con la
#: exclusion por nombre EXACTO de la 009 (que la 013 conserva) ese estado si
#: cuenta como activo. Una exclusion insensible al casing lo excluiria.
NOMBRES_ESTADOS = ("Pendiente", "EnRevision", "EnCurso", "Cerrado", "Anulado", "anulado")


@pytest.fixture
def datos_013(motor, dos_instituciones):
    return sembrar_mundo_013(
        motor, dos_instituciones, nombres_estados=NOMBRES_ESTADOS
    )


def _leer_dashboard(cliente) -> dict:
    respuesta = cliente.get("/api/v1/dashboard/")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _sembrar_poblacion_kpi(motor, datos) -> None:
    """Cinco tickets de INST01 con valores distintos de KPI."""
    solicitante = datos["usuarios_inst01"]["Solicitante"]
    for estado in ("EnCurso", "Cerrado", "Anulado", "anulado"):
        sembrar_ticket(
            motor, datos,
            usuario_id=solicitante,
            estado_id=datos["estados"][estado],
            asunto=f"Ticket {estado} para el KPI",
        )
    sembrar_ticket(
        motor, datos,
        usuario_id=datos["usuario_id"],  # de Ana (Administrador)
        estado_id=datos["estados"]["EnRevision"],
        asunto="Ticket EnRevision del Administrador",
    )


def test_kpi_tickets_activos_excluye_anulado_por_nombre_ac_22(motor, datos_013):
    """AC-22: `Cerrado` y `Anulado` se excluyen; `anulado` minuscula cuenta."""
    _sembrar_poblacion_kpi(motor, datos_013)

    with cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos_013["departamento_id"],
        usuario_id=datos_013["usuario_id"],
    ) as cliente:
        kpi = _leer_dashboard(cliente)["kpi"]

    assert kpi["tickets_activos"] == 3, (
        "EnCurso + EnRevision + 'anulado' (minuscula); los nombres exactos "
        f"'Cerrado' y 'Anulado' se excluyen; kpi: {kpi}"
    )


def test_kpi_del_solicitante_no_cuenta_sus_anulados_ac_22(motor, datos_013):
    """AC-22: el alcance por rol se conserva y tambien excluye `Anulado`."""
    _sembrar_poblacion_kpi(motor, datos_013)

    with cliente_con_rol(
        motor,
        "Solicitante",
        departamento_id=datos_013["departamento_id"],
        usuario_id=datos_013["usuarios_inst01"]["Solicitante"],
    ) as cliente:
        kpi = _leer_dashboard(cliente)["kpi"]

    assert kpi["tickets_activos"] == 2, (
        "del Solicitante solo cuentan sus activos: EnCurso y 'anulado'; "
        f"kpi: {kpi}"
    )


def test_kpi_resto_del_dashboard_intacto_ac_22(motor, datos_013):
    """AC-22: el resto de KPI, el log de alertas y la actividad no cambian."""
    _sembrar_poblacion_kpi(motor, datos_013)

    with cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos_013["departamento_id"],
        usuario_id=datos_013["usuario_id"],
    ) as cliente:
        cuerpo = _leer_dashboard(cliente)

    kpi = cuerpo["kpi"]
    assert kpi["unidades_en_stock"] == 50, (
        "el stock por sede de la sede base no cambia"
    )
    assert kpi["total_departamentos"] == 1, "el conteo de departamentos no cambia"
    assert kpi["total_alertas"] == 0, "stock 50 sobre minimo 10 no es critico"
    assert cuerpo["alertas"] == []
    assert cuerpo["actividad_disponible"] is True
    assert cuerpo["actividad_movimientos"] == [], (
        "sin movimientos de inventario no hay actividad"
    )
