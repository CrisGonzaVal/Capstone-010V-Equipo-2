"""T2 (Feature 013): motivo obligatorio de anulacion y rechazo (AC-8).

Seam bajo prueba: la interfaz HTTP (`TestClient`). El contrato que este modulo
fija (spec D-6/AC-8, plan decision 3): el motivo se valida **en el servicio**,
no en Pydantic, con longitud maxima 500 (la escala del `VARCHAR(500)` del
historial y de la descripcion del ticket); sin motivo valido no se escribe
nada, y con motivo valido la fila del historial lo conserva **literal**.

Fase ROJA de TDD: las rutas `/anulacion` y `/rechazo` aun no existen (T7), de
modo que los 422 esperados caen en rojo con el 404 del router. Ningun test
pasa hoy por el motivo equivocado: el router responde `Not Found`, que no es
422, 200 ni el detalle literal esperado.
"""

from __future__ import annotations

import pytest

from ._soporte_ciclo_vida_013 import (
    abrir_ticket,
    cliente_con_rol,
    leer_historial,
    sembrar_mundo_013,
    sembrar_ticket,
    exigir_ruta,
)

#: Longitud maxima del motivo (D-6: misma escala que la descripcion; el DDL
#: del historial la fija en VARCHAR(500)).
LONGITUD_MAXIMA_MOTIVO = 500


@pytest.fixture
def datos_013(motor, dos_instituciones):
    return sembrar_mundo_013(motor, dos_instituciones)


def _cliente_administrador(motor, datos):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuario_id"],
    )


def _ticket_en_pendiente(motor, datos) -> int:
    return sembrar_ticket(motor, datos, estado_id=datos["estados"]["Pendiente"])


def _sin_efectos(cliente, datos, ticket_id: int) -> None:
    """Comprueba que estado e historial quedaron intactos tras un rechazo."""
    assert abrir_ticket(cliente, ticket_id)["estado_id"] == datos["estados"][
        "Pendiente"
    ], "el 422 no puede modificar el estado"
    exigir_ruta("/api/v1/tickets/{ticket_id}/historial", "GET")
    assert leer_historial(cliente, ticket_id) == [], (
        "el 422 no puede agregar filas al historial"
    )


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_motivo_faltante_responde_422_ac_8(motor, datos_013, operacion):
    """AC-8: payload sin `motivo` -> 422, sin modificar estado ni historial."""
    ticket_id = _ticket_en_pendiente(motor, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{operacion}", json={}
        )

        assert respuesta.status_code == 422, respuesta.text
        _sin_efectos(cliente, datos_013, ticket_id)


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_motivo_vacio_responde_422_ac_8(motor, datos_013, operacion):
    """AC-8/D-6: motivo vacio -> 422, sin modificar estado ni historial."""
    ticket_id = _ticket_en_pendiente(motor, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{operacion}", json={"motivo": ""}
        )

        assert respuesta.status_code == 422, respuesta.text
        _sin_efectos(cliente, datos_013, ticket_id)


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_motivo_sobre_la_longitud_maxima_responde_422_ac_8(
    motor, datos_013, operacion
):
    """AC-8/D-6: 501 caracteres -> 422, sin modificar estado ni historial."""
    ticket_id = _ticket_en_pendiente(motor, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{operacion}",
            json={"motivo": "x" * (LONGITUD_MAXIMA_MOTIVO + 1)},
        )

        assert respuesta.status_code == 422, respuesta.text
        _sin_efectos(cliente, datos_013, ticket_id)


def test_motivo_en_el_limite_maximo_es_aceptado_y_se_persiste_literal_ac_8(
    motor, datos_013
):
    """AC-8: 500 caracteres caben; el motivo de la fila es literal (caseado)."""
    motivo = ("Motivo con Acentos, Mayusculas y espacios " * 12)[
        :LONGITUD_MAXIMA_MOTIVO
    ]
    assert len(motivo) == LONGITUD_MAXIMA_MOTIVO
    ticket_id = _ticket_en_pendiente(motor, datos_013)

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/anulacion", json={"motivo": motivo}
        )

        assert respuesta.status_code == 200, respuesta.text
        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1
        assert historial[0]["motivo"] == motivo, (
            "el motivo debe persistirse literal, sin normalizar"
        )
