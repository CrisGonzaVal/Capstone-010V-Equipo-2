"""T2 (Feature 013): historial de transiciones (AC-9…AC-12).

Seam bajo prueba: la interfaz HTTP (`TestClient`). El historial es inmutable y
de solo lectura por API (D-10): una fila por mutacion (creacion con origen
nulo, cambio de estado de la 004, despacho de la 005, anulacion y rechazo de
la 013), ticket y fila persistidos juntos (AC-11) y sin trazabilidad fabricada
para transiciones previas a la feature (AC-12).

Fase ROJA de TDD: `GET /tickets/{id}/historial` y la escritura de filas aun no
existen (T4 modelo, T7 servicio/T9 ruta); las pruebas caen en rojo por esas
ausencias (404 del router o `pytest.fail` de la guarda), nunca por imports ni
sintaxis.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from ._soporte_ciclo_vida_013 import (
    CAMPOS_HISTORIAL,
    abrir_ticket,
    cliente_con_rol,
    leer_historial,
    payload_alta,
    sembrar_mundo_013,
    sembrar_ticket,
    exigir_ruta,
)

RUTA_HISTORIAL = "/api/v1/tickets/{ticket_id}/historial"


@pytest.fixture
def datos_013(motor, dos_instituciones):
    return sembrar_mundo_013(motor, dos_instituciones)


def _cliente_solicitante(motor, datos):
    return cliente_con_rol(
        motor,
        "Solicitante",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Solicitante"],
    )


def _cliente_administrador(motor, datos):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuario_id"],
    )


def _cliente_bodeguero(motor, datos):
    return cliente_con_rol(
        motor,
        "Bodeguero",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Bodeguero"],
    )


def _crear_ticket_via_api(cliente, datos) -> int:
    respuesta = cliente.post(
        "/api/v1/tickets/", json=payload_alta(datos, datos["estados"]["Pendiente"])
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["ticket_id"]


# ---------------------------------------------------------------------------
# AC-9: exactamente una fila por mutacion
# ---------------------------------------------------------------------------


def test_alta_registra_fila_de_creacion_con_origen_nulo_ac_9(motor, datos_013):
    """AC-9: la creacion registra origen nulo, destino = estado inicial, actor."""
    solicitante = datos_013["usuarios_inst01"]["Solicitante"]

    with _cliente_solicitante(motor, datos_013) as cliente:
        ticket_id = _crear_ticket_via_api(cliente, datos_013)

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1, historial
        fila = historial[0]
        assert CAMPOS_HISTORIAL <= set(fila), sorted(fila)
        assert fila["ticket_id"] == ticket_id
        assert fila["estado_origen_id"] is None, (
            "solo la creacion tiene origen nulo"
        )
        assert fila["estado_destino_id"] == datos_013["estados"]["Pendiente"]
        assert fila["usuario_id"] == solicitante, "el actor es el creador"
        assert fila["motivo"] is None, "la creacion no exige motivo"
        assert fila["fecha_transicion"] is not None


def test_cambio_de_estado_suma_exactamente_una_fila_ac_9(motor, datos_013):
    """AC-9: el cambio de estado de la 004 suma exactamente su fila."""
    with _cliente_solicitante(motor, datos_013) as cliente:
        ticket_id = _crear_ticket_via_api(cliente, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        cambio = cliente.patch(
            f"/api/v1/tickets/{ticket_id}/estado",
            json={"estado_id": datos_013["estados"]["EnRevision"]},
        )
        assert cambio.status_code == 200, cambio.text

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 2, historial
        nueva = historial[0]
        assert nueva["estado_origen_id"] == datos_013["estados"]["Pendiente"]
        assert nueva["estado_destino_id"] == datos_013["estados"]["EnRevision"]
        assert nueva["motivo"] is None, "el cambio de estado no exige motivo"


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_anulacion_y_rechazo_suman_exactamente_una_fila_ac_9(
    motor, datos_013, operacion
):
    """AC-9: anulacion y rechazo son mutaciones y cada una suma su fila."""
    with _cliente_solicitante(motor, datos_013) as cliente:
        ticket_id = _crear_ticket_via_api(cliente, datos_013)

    cliente_factory = (
        _cliente_solicitante if operacion == "anulacion" else _cliente_bodeguero
    )
    with cliente_factory(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{operacion}",
            json={"motivo": f"Motivo de {operacion}"},
        )
        assert respuesta.status_code == 200, respuesta.text

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 2, (
            "creacion + exactamente una fila de la mutacion; "
            f"{operacion}: {historial}"
        )
        assert historial[0]["estado_destino_id"] == datos_013["estados"]["Anulado"]
        assert historial[0]["motivo"] == f"Motivo de {operacion}"


# ---------------------------------------------------------------------------
# AC-10: orden determinista y solo lectura
# ---------------------------------------------------------------------------


def test_orden_mas_reciente_primero_con_desempate_por_id_ac_10(
    motor, datos_013
):
    """AC-10: `fecha_transicion DESC, historial_transicion_id DESC`."""
    with _cliente_solicitante(motor, datos_013) as cliente:
        ticket_id = _crear_ticket_via_api(cliente, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        for destino in ("EnRevision", "EnCurso"):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos_013["estados"][destino]},
            )
            assert respuesta.status_code == 200, respuesta.text

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 3, historial
        assert historial == sorted(
            historial,
            key=lambda fila: (fila["fecha_transicion"], fila["historial_transicion_id"]),
            reverse=True,
        ), "el historial debe venir ordenado mas reciente primero, con desempate"
        assert [fila["estado_destino_id"] for fila in historial] == [
            datos_013["estados"]["EnCurso"],
            datos_013["estados"]["EnRevision"],
            datos_013["estados"]["Pendiente"],
        ]


def test_historial_no_expone_operaciones_de_escritura_ac_10(cliente):
    """AC-10: bajo la ruta del historial solo hay `GET` (inmutable por API)."""
    exigir_ruta(RUTA_HISTORIAL, "GET")
    contrato = cliente.get("/openapi.json").json()
    operaciones = contrato["paths"].get(RUTA_HISTORIAL, {})
    assert set(operaciones) <= {"get"}, (
        f"el historial no admite escritura publica: {sorted(operaciones)}"
    )


# ---------------------------------------------------------------------------
# AC-11: atomicidad ticket <-> fila
# ---------------------------------------------------------------------------


def test_transicion_aceptada_persiste_estado_y_fila_juntos_ac_11(
    motor, datos_013
):
    """AC-11: la transicion aceptada deja el estado nuevo Y su fila, juntos."""
    exigir_ruta(RUTA_HISTORIAL, "GET")
    with _cliente_solicitante(motor, datos_013) as cliente:
        ticket_id = _crear_ticket_via_api(cliente, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.patch(
            f"/api/v1/tickets/{ticket_id}/estado",
            json={"estado_id": datos_013["estados"]["EnRevision"]},
        )

        assert respuesta.status_code == 200, respuesta.text
        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["EnRevision"]
        )
        filas = leer_historial(cliente, ticket_id)
        assert any(
            fila["estado_origen_id"] == datos_013["estados"]["Pendiente"]
            and fila["estado_destino_id"] == datos_013["estados"]["EnRevision"]
            for fila in filas
        ), "sin la fila del historial el estado no puede darse por persistido"


def test_si_la_fila_no_puede_registrarse_el_estado_no_cambia_ac_11(
    motor, cliente_sin_excepcion, datos_013
):
    """AC-11: si la fila falla, la transaccion revierte y el estado no cambia.

    Se provoca el fallo retirando la tabla del historial del motor de prueba
    (SQLite no tiene DDL transaccional, pero si `DROP TABLE IF EXISTS`); el
    servicio debe responder 500 sin dejar el ticket anulado. `cliente_sin_
    excepcion` convierte el fallo en 500 observable en vez de relanzarlo.
    """
    exigir_ruta(RUTA_HISTORIAL, "GET")
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )

    with motor.begin() as conexion:
        conexion.execute(text("DROP TABLE IF EXISTS historial_transicion_ticket"))

    respuesta = cliente_sin_excepcion.post(
        f"/api/v1/tickets/{ticket_id}/anulacion",
        json={"motivo": "La fila del historial no puede escribirse"},
    )

    assert respuesta.status_code == 500, (
        f"sin la tabla del historial la operacion debe fallar completa: {respuesta.text}"
    )
    assert abrir_ticket(cliente_sin_excepcion, ticket_id)["estado_id"] == (
        datos_013["estados"]["Pendiente"]
    ), "si la fila no pudo registrarse, el estado no puede quedar cambiado"


# ---------------------------------------------------------------------------
# AC-12: sin trazabilidad fabricada para transiciones previas
# ---------------------------------------------------------------------------


def test_ticket_legado_sin_transiciones_muestra_historial_vacio_ac_12(
    motor, datos_013
):
    """AC-12: un ticket anterior a la 013 sin transiciones posteriores: `[]`."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnRevision"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        assert leer_historial(cliente, ticket_id) == []


def test_anulacion_de_legado_no_inventa_fila_de_creacion_ac_12(
    motor, datos_013
):
    """AC-12: la anulacion de un legado registra solo SU fila, sin creacion."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/anulacion",
            json={"motivo": "Anulacion sobre un ticket legado"},
        )
        assert respuesta.status_code == 200, respuesta.text

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1, (
            "sin filas inventadas: solo la anulacion real; "
            f"historial: {historial}"
        )
        assert historial[0]["estado_origen_id"] == datos_013["estados"]["Pendiente"]
