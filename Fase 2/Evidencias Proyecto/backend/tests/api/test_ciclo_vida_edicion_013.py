"""T2 (Feature 013): edicion del ticket en `Pendiente` (AC-13…AC-16).

Seam bajo prueba: la interfaz HTTP (`TestClient`). El contrato (spec D-9):
`PUT /tickets/{id}` reemplaza asunto, descripcion, prioridad y el **conjunto
completo** de detalles solo en `Pendiente`; valida todo antes de escribir
(referencias 404, forma 422) y nunca toca estado, solicitante, sede ni
institucion. Bodeguero y Superadmin no editan (403); un ticket ajeno responde
404 identico al inexistente (D-8).

Fase ROJA de TDD: la ruta `PUT /tickets/{ticket_id}` aun no existe (T9); los
403/409/422/200 esperados caen en rojo con el 404 del router o con el detalle
`Not Found` que no coincide con el de ocultamiento, nunca por imports ni
sintaxis.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Prioridad, Producto

from ._soporte_ciclo_vida_013 import (
    DETALLE_TICKET_NO_ENCONTRADO,
    abrir_ticket,
    cliente_con_rol,
    sembrar_mundo_013,
    sembrar_ticket,
)

RUTA_EDICION = "/api/v1/tickets/{ticket_id}"


def _agregar_prioridad_y_producto(motor, datos):
    """Segunda prioridad (BAJA) y segundo producto de INST01 para editar."""
    db = sessionmaker(bind=motor)()
    try:
        prioridad_baja = Prioridad(nombre="BAJA", descripcion="Prioridad baja")
        db.add(prioridad_baja)
        db.flush()
        producto_extra = Producto(
            nombre="Resma de papel bond",
            descripcion="Segundo producto para reemplazar detalles",
            unidad_medida="RESMA",
            stock_minimo=5,
            categoria_id=datos["categoria_id"],
            institucion_id=datos["institucion_id"],
        )
        db.add(producto_extra)
        db.commit()
        return {
            **datos,
            "prioridad_baja_id": prioridad_baja.prioridad_id,
            "producto_extra_id": producto_extra.producto_id,
        }
    finally:
        db.close()


@pytest.fixture
def datos_013(motor, dos_instituciones):
    return _agregar_prioridad_y_producto(
        motor, sembrar_mundo_013(motor, dos_instituciones)
    )


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


def _cliente_admin_ajeno(motor, datos):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_ajeno_id"],
        usuario_id=datos["usuarios_inst02"]["Administrador"],
    )


def _payload_edicion(datos, **sobrescritos) -> dict:
    payload = {
        "asunto": "Asunto reescrito en la 013",
        "descripcion": "Descripcion reescrita en la 013.",
        "prioridad_id": datos["prioridad_baja_id"],
        "detalles": [
            {"producto_id": datos["producto_extra_id"], "cantidad_solicitada": 5},
            {"producto_id": datos["producto_id"], "cantidad_solicitada": 2},
        ],
    }
    payload.update(sobrescritos)
    return payload


def _detalles_de(ticket: dict) -> list[tuple[int, int]]:
    return [(d["producto_id"], d["cantidad_solicitada"]) for d in ticket["detalles"]]


def _assert_intacto(cliente, motor, datos, ticket_id: int, asunto_original: str):
    """Cabecera y detalles sin ningun cambio parcial."""
    ticket = abrir_ticket(cliente, ticket_id)
    assert ticket["asunto"] == asunto_original, "la cabecera no puede cambiar"
    assert ticket["estado_id"] == datos["estados"]["Pendiente"]
    assert _detalles_de(ticket) == [(datos["producto_id"], 3)], (
        "los detalles no pueden cambiar parcialmente"
    )


# ---------------------------------------------------------------------------
# AC-13: reemplazo integro en Pendiente
# ---------------------------------------------------------------------------


def test_edicion_en_pendiente_reemplaza_cabecera_y_detalles_ac_13(
    motor, datos_013
):
    """AC-13: 200 con cabecera reflejada y el conjunto de items reemplazado."""
    asunto_original = "Ticket con detalle a reemplazar"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )

        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["asunto"] == "Asunto reescrito en la 013"
        assert cuerpo["descripcion"] == "Descripcion reescrita en la 013."
        assert cuerpo["prioridad_id"] == datos_013["prioridad_baja_id"]

        ticket = abrir_ticket(cliente, ticket_id)
        assert ticket["asunto"] == "Asunto reescrito en la 013"
        assert ticket["prioridad_id"] == datos_013["prioridad_baja_id"]
        assert sorted(_detalles_de(ticket)) == sorted(
            [
                (datos_013["producto_extra_id"], 5),
                (datos_013["producto_id"], 2),
            ]
        ), "el conjunto de detalles se reemplaza por completo (la linea vieja no queda)"


def test_edicion_conserva_estado_solicitante_sede_e_institucion_ac_13(
    motor, datos_013
):
    """AC-13: estado, solicitante, sede e institucion quedan intactos."""
    ticket_id = sembrar_ticket(motor, datos_013)
    solicitante = datos_013["usuarios_inst01"]["Solicitante"]

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )
        assert respuesta.status_code == 200, respuesta.text

        ticket = abrir_ticket(cliente, ticket_id)
        assert ticket["estado_id"] == datos_013["estados"]["Pendiente"], (
            "la edicion no puede mover el estado"
        )
        assert ticket["usuario_id"] == solicitante, (
            "la edicion no puede reatribuir el solicitante"
        )
        assert ticket["sede_id"] == datos_013["sede_id"], (
            "la edicion no puede mover la sede instantanea"
        )

    # La institucion no cambia: el ticket sigue siendo de INST01 (visible para
    # su Administrador e invisible para el de INST02).
    with _cliente_administrador(motor, datos_013) as cliente:
        assert abrir_ticket(cliente, ticket_id) is not None
    with _cliente_admin_ajeno(motor, datos_013) as cliente:
        assert abrir_ticket(cliente, ticket_id) is None, (
            "un ticket editado no puede cambiar de institucion"
        )


# ---------------------------------------------------------------------------
# AC-14: 409 fuera de Pendiente
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["EnRevision", "EnCurso", "Cerrado", "Anulado"])
def test_edicion_fuera_de_pendiente_responde_409_sin_efectos_ac_14(
    motor, datos_013, estado
):
    """AC-14: fuera de `Pendiente` la edicion es 409 y no toca cabecera ni items."""
    asunto_original = f"Ticket en estado {estado} no editable"
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"][estado],
        asunto=asunto_original,
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )

        assert respuesta.status_code == 409, respuesta.text
        ticket = abrir_ticket(cliente, ticket_id)
        assert ticket["estado_id"] == datos_013["estados"][estado]
        assert ticket["asunto"] == asunto_original
        assert _detalles_de(ticket) == [(datos_013["producto_id"], 3)]


# ---------------------------------------------------------------------------
# AC-15: validacion total antes de escribir (sin escritura parcial)
# ---------------------------------------------------------------------------


def test_edicion_con_prioridad_inexistente_responde_404_sin_escritura_ac_15(
    motor, datos_013
):
    """AC-15: prioridad inexistente -> 404 nombrando la referencia, sin escribir."""
    asunto_original = "Ticket ante una prioridad inexistente"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(datos_013, prioridad_id=999999),
        )

        assert respuesta.status_code == 404, respuesta.text
        assert "prioridad" in respuesta.json()["detail"].lower(), (
            f"debe nombrar la referencia fallida: {respuesta.text}"
        )
        _assert_intacto(cliente, motor, datos_013, ticket_id, asunto_original)


def test_edicion_con_producto_inexistente_responde_404_sin_escritura_ac_15(
    motor, datos_013
):
    """AC-15: producto inexistente -> 404 nombrando la referencia, sin escribir."""
    asunto_original = "Ticket ante un producto inexistente"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(
                datos_013,
                detalles=[{"producto_id": 999999, "cantidad_solicitada": 1}],
            ),
        )

        assert respuesta.status_code == 404, respuesta.text
        assert "producto" in respuesta.json()["detail"].lower()
        _assert_intacto(cliente, motor, datos_013, ticket_id, asunto_original)


def test_edicion_con_producto_ajeno_responde_404_ocultado_sin_escritura_ac_15(
    motor, datos_013
):
    """AC-15/AC-8-008: un producto de otra institucion se oculta con 404."""
    asunto_original = "Ticket ante un producto ajeno"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)
    producto_ajeno = datos_013["producto_homonimo_ajeno_id"]

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(
                datos_013,
                detalles=[{"producto_id": producto_ajeno, "cantidad_solicitada": 1}],
            ),
        )

        assert respuesta.status_code == 404, respuesta.text
        assert respuesta.json()["detail"] == (
            f"No existe producto indicado: {producto_ajeno}"
        ), "el 404 del producto ajeno debe ser identico al de uno inexistente"
        _assert_intacto(cliente, motor, datos_013, ticket_id, asunto_original)


@pytest.mark.parametrize("cantidad", [0, -3], ids=["cantidad_cero", "cantidad_negativa"])
def test_edicion_con_cantidad_no_positiva_responde_422_sin_escritura_ac_15(
    motor, datos_013, cantidad
):
    """AC-15: cantidad no positiva -> 422 de forma, sin cabecera ni items."""
    asunto_original = f"Ticket con cantidad no positiva ({cantidad})"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(
                datos_013,
                detalles=[
                    {"producto_id": datos_013["producto_id"], "cantidad_solicitada": cantidad}
                ],
            ),
        )

        assert respuesta.status_code == 422, respuesta.text
        _assert_intacto(cliente, motor, datos_013, ticket_id, asunto_original)


def test_edicion_con_detalles_vacios_responde_422_sin_escritura_ac_15(
    motor, datos_013
):
    """AC-15/D-9: `detalles` vacio -> 422 (misma regla que el alta)."""
    asunto_original = "Ticket con detalles vacios"
    ticket_id = sembrar_ticket(motor, datos_013, asunto=asunto_original)

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(datos_013, detalles=[]),
        )

        assert respuesta.status_code == 422, respuesta.text
        _assert_intacto(cliente, motor, datos_013, ticket_id, asunto_original)


# ---------------------------------------------------------------------------
# AC-16: autorizacion de la edicion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["Bodeguero", "Superadmin"])
def test_bodeguero_y_superadmin_no_pueden_editar_ac_16(motor, datos_013, rol):
    """AC-16/AC-17: el Bodeguero y el Superadmin no editan tickets (403)."""
    ticket_id = sembrar_ticket(motor, datos_013)
    cliente_factory = cliente_con_rol(
        motor,
        rol,
        departamento_id=datos_013["departamento_id"],
        usuario_id=datos_013["usuarios_inst01"][rol],
    )

    with cliente_factory as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )

        assert respuesta.status_code == 403, respuesta.text
        _assert_intacto(cliente, motor, datos_013, ticket_id, "Ticket sembrado para el ciclo de vida 013")


def test_solicitante_no_edita_ticket_ajeno_y_el_404_es_identico_ac_16(
    motor, datos_013
):
    """AC-16/AC-18: ajeno e inexistente responden el mismo 404 de ocultamiento."""
    ticket_id = sembrar_ticket(
        motor, datos_013,
        usuario_id=datos_013["usuario_id"],  # propio de Ana (Administrador)
        asunto="Ticket ajeno al Solicitante que lo edita",
    )

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta_ajeno = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )
        respuesta_inexistente = cliente.put(
            "/api/v1/tickets/999999", json=_payload_edicion(datos_013)
        )

        assert respuesta_ajeno.status_code == 404, respuesta_ajeno.text
        assert respuesta_ajeno.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO
        assert respuesta_inexistente.status_code == 404
        assert respuesta_inexistente.json()["detail"] == (
            respuesta_ajeno.json()["detail"]
        ), "el 404 del ajeno debe ser identico al del inexistente"


def test_administrador_de_otra_institucion_edita_con_404_ocultado_ac_16(
    motor, datos_013
):
    """AC-16/AC-18: el Administrador de INST02 no edita tickets de INST01."""
    ticket_id = sembrar_ticket(
        motor, datos_013,
        usuario_id=datos_013["usuarios_inst01"]["Solicitante"],
        asunto="Ticket de INST01 frente al Administrador de INST02",
    )

    with _cliente_admin_ajeno(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}", json=_payload_edicion(datos_013)
        )

        assert respuesta.status_code == 404, respuesta.text
        assert respuesta.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO


def test_administrador_edita_tickets_de_su_institucion_ac_16(motor, datos_013):
    """AC-16/D-9: el Administrador comparte la edicion dentro de su institucion."""
    asunto_original = "Ticket mal emitido que corrige el Administrador"
    ticket_id = sembrar_ticket(
        motor, datos_013,
        usuario_id=datos_013["usuarios_inst01"]["Solicitante"],
        asunto=asunto_original,
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json=_payload_edicion(datos_013, asunto="Corregido por el Administrador"),
        )

        assert respuesta.status_code == 200, respuesta.text
        assert abrir_ticket(cliente, ticket_id)["asunto"] == (
            "Corregido por el Administrador"
        )
