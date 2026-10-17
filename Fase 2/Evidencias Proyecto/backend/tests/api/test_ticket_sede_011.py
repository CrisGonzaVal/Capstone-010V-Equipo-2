"""T2 (Feature 011): sede del ticket y despacho por instantanea — pruebas rojas.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`POST /api/v1/tickets/`,
`POST /api/v1/tickets/{ticket_id}/despacho`) mas la lectura persistida de la
auditoria, que en esta tarea no tiene endpoint adaptado.

Regla de negocio que estas pruebas fijan (spec D-5 y decision 11 del usuario):

  * al **crear** el ticket se almacena en `ticket.sede_id` la sede vigente del
    departamento del solicitante (instantanea);
  * el **despacho** rebaja el stock de esa sede almacenada, **no** el de la sede a
    la que el departamento apunte en ese momento;
  * reasignar el departamento afecta a los tickets **futuros**;
  * un departamento sin sede impide crear el ticket (409) y un ticket legado sin
    sede no se despacha.

Trazabilidad AC (spec 011 §5):

  * **AC-6** sede de departamento y ausencia de asignacion.
  * **AC-9** instantanea de sede en ticket, despacho y auditoria.

Fase ROJA de TDD: ni la columna `ticket.sede_id` ni el contrato de respuesta ni el
despacho por sede existen todavia (T3/T9). Cada prueba arranca con la guarda de
capacidad y falla con un motivo explicito.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Ticket

from ._soporte_sede_011 import (
    RUTA_TICKETS,
    asignar_sede_a_departamento,
    cliente,
    contar_en,
    contar_movimientos,
    crear_sede,
    crear_stock_sede,
    exigir_contrato_ticket_con_sede,
    exigir_columna,
    instalar_catalogo_estados,
    leer_estado_de_ticket,
    leer_sede_de_ticket,
    leer_stock_sede,
    movimientos_con_stock_sede,
)

RUTA_DESPACHO = "/api/v1/tickets/{ticket_id}/despacho"


def _instalar_flujo(motor) -> dict[str, int]:
    return instalar_catalogo_estados(
        motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado")
    )


def _crear_ticket(
    cliente_http,
    *,
    usuario_id: int,
    prioridad_id: int,
    estado_id: int,
    producto_id: int,
    cantidad: int = 3,
    asunto: str = "Solicitud de insumos por sede",
):
    return cliente_http.post(
        RUTA_TICKETS,
        json={
            "usuario_id": usuario_id,
            "prioridad_id": prioridad_id,
            "estado_id": estado_id,
            "asunto": asunto,
            "descripcion": "Prueba de sede del ticket",
            "detalles": [{"producto_id": producto_id, "cantidad_solicitada": cantidad}],
        },
    )


def _crear_ticket_directo(
    motor,
    *,
    usuario_id: int,
    prioridad_id: int,
    estado_id: int,
    institucion_id: str,
    sede_id: int | None,
    asunto: str = "Ticket legado sin sede",
) -> int:
    """Inserta un ticket en la base, saltandose la API (caso legado de la migracion)."""
    exigir_columna(Ticket, "sede_id", "ticket")
    db = sessionmaker(bind=motor)()
    try:
        ticket = Ticket(
            usuario_id=usuario_id,
            prioridad_id=prioridad_id,
            estado_id=estado_id,
            asunto=asunto,
            institucion_id=institucion_id,
            sede_id=sede_id,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        return ticket.ticket_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AC-6/AC-9: la sede se almacena al crear
# ---------------------------------------------------------------------------


def test_crear_ticket_almacena_la_sede_del_departamento(motor, datos_base):
    """AC-9: el alta guarda la sede vigente del departamento del solicitante."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_id)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["Pendiente"],
            producto_id=datos_base["producto_id"],
        )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["sede_id"] == sede_id, "el ticket guarda la sede de su departamento"
    assert leer_sede_de_ticket(motor, cuerpo["ticket_id"]) == sede_id


def test_departamento_sin_sede_no_crea_ticket_responde_409(motor, datos_base):
    """AC-6: sin sede asignada el alta responde 409 y no deja ticket."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], None)
    tickets_antes = contar_en(motor, Ticket)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["Pendiente"],
            producto_id=datos_base["producto_id"],
        )

    assert respuesta.status_code == 409, respuesta.text
    assert contar_en(motor, Ticket) == tickets_antes, "no debe quedar ticket parcial"


# ---------------------------------------------------------------------------
# AC-9: despacho desde la instantanea, no desde la sede vigente del departamento
# ---------------------------------------------------------------------------


def test_ticket_abierto_despacha_desde_la_sede_almacenada(motor, datos_base):
    """AC-9: reasignar el departamento no redirige un ticket ya emitido.

    El ticket nace en la sede A (stock 50). Antes del despacho el departamento se
    reasigna a la sede B (stock 7, insuficiente para la cantidad pedida): si el
    despacho derivara la sede del departamento en ese instante, fallaria con 409.
    Debe rebajar A y dejar B intacta. Un ticket **nuevo** si usa B.
    """
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    sede_a = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="A")
    sede_b = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="B")
    crear_stock_sede(
        motor, sede_id=sede_a, producto_id=datos_base["producto_id"],
        stock_actual=50, institucion_id=datos_base["institucion_id"],
    )
    crear_stock_sede(
        motor, sede_id=sede_b, producto_id=datos_base["producto_id"],
        stock_actual=7, institucion_id=datos_base["institucion_id"],
    )
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_a)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        alta = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["EnCurso"],
            producto_id=datos_base["producto_id"],
            cantidad=5,
        )
        assert alta.status_code == 201, alta.text
        ticket_id = alta.json()["ticket_id"]

        # Reasignacion posterior: el ticket ya emitido conserva su instantanea.
        asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_b)

        despacho = cliente_http.post(
            RUTA_DESPACHO.format(ticket_id=ticket_id),
            json={"usuario_id": datos_base["usuario_id"]},
        )
        futuro = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["Pendiente"],
            producto_id=datos_base["producto_id"],
            asunto="Ticket posterior a la reasignacion",
            cantidad=1,
        )

    assert despacho.status_code == 200, despacho.text
    assert leer_stock_sede(motor, sede_a, datos_base["producto_id"]) == 45
    assert leer_stock_sede(motor, sede_b, datos_base["producto_id"]) == 7, (
        "la sede vigente del departamento no debe rebajarse"
    )
    assert leer_sede_de_ticket(motor, ticket_id) == sede_a
    assert futuro.status_code == 201, futuro.text
    assert futuro.json()["sede_id"] == sede_b, "el ticket futuro usa la sede vigente"


def test_stock_insuficiente_en_la_sede_del_ticket_responde_409(motor, datos_base):
    """AC-9: sin saldo en la sede almacenada el despacho no cambia nada."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    crear_stock_sede(
        motor, sede_id=sede_id, producto_id=datos_base["producto_id"],
        stock_actual=1, institucion_id=datos_base["institucion_id"],
    )
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_id)
    auditorias_antes = contar_movimientos(motor)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        alta = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["EnCurso"],
            producto_id=datos_base["producto_id"],
            cantidad=5,
        )
        ticket_id = alta.json()["ticket_id"]
        despacho = cliente_http.post(
            RUTA_DESPACHO.format(ticket_id=ticket_id),
            json={"usuario_id": datos_base["usuario_id"]},
        )

    assert despacho.status_code == 409, despacho.text
    assert leer_stock_sede(motor, sede_id, datos_base["producto_id"]) == 1
    assert contar_movimientos(motor) == auditorias_antes, "sin auditoria parcial"
    assert leer_estado_de_ticket(motor, ticket_id) == ids["EnCurso"], (
        "el estado del ticket no debe cambiar"
    )


def test_despacho_registra_movimiento_por_stock_sede(motor, datos_base):
    """AC-9: la salida de auditoria referencia la sede y deja el legado intacto."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    crear_stock_sede(
        motor, sede_id=sede_id, producto_id=datos_base["producto_id"],
        stock_actual=20, institucion_id=datos_base["institucion_id"],
    )
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_id)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        alta = _crear_ticket(
            cliente_http,
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=ids["EnCurso"],
            producto_id=datos_base["producto_id"],
            cantidad=4,
        )
        ticket_id = alta.json()["ticket_id"]
        despacho = cliente_http.post(
            RUTA_DESPACHO.format(ticket_id=ticket_id),
            json={"usuario_id": datos_base["usuario_id"]},
        )

    assert despacho.status_code == 200, despacho.text
    salidas = [
        movimiento
        for movimiento in movimientos_con_stock_sede(motor)
        if movimiento.tipo_movimiento == "SALIDA"
    ]
    assert len(salidas) == 1
    assert salidas[0].stock_sede_id is not None
    assert salidas[0].cantidad == 4
    assert salidas[0].inventario_id is None
    assert despacho.json()["detalles"][0]["cantidad_entregada"] == 4


def test_ticket_legado_sin_sede_no_se_despacha(motor, datos_base):
    """AC-9: un ticket sin instantanea de sede no se despacha hasta migrarlo."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    ticket_id = _crear_ticket_directo(
        motor,
        usuario_id=datos_base["usuario_id"],
        prioridad_id=datos_base["prioridad_id"],
        estado_id=ids["EnCurso"],
        institucion_id=datos_base["institucion_id"],
        sede_id=None,
    )

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        despacho = cliente_http.post(
            RUTA_DESPACHO.format(ticket_id=ticket_id),
            json={"usuario_id": datos_base["usuario_id"]},
        )

    assert despacho.status_code == 409, despacho.text
    assert leer_estado_de_ticket(motor, ticket_id) == ids["EnCurso"]


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante"])
def test_crear_ticket_sin_sede_de_departamento_afecta_a_todos_los_roles_creadores(
    motor, dos_instituciones, rol
):
    """AC-6: la ausencia de sede bloquea el alta con independencia del rol creador."""
    exigir_contrato_ticket_con_sede()
    ids = _instalar_flujo(motor)
    asignar_sede_a_departamento(motor, dos_instituciones["departamento_id"], None)

    with cliente(
        motor,
        rol,
        departamento_id=dos_instituciones["departamento_id"],
        usuario_id=dos_instituciones["usuarios_inst01"][rol],
    ) as cliente_http:
        respuesta = _crear_ticket(
            cliente_http,
            usuario_id=dos_instituciones["usuarios_inst01"][rol],
            prioridad_id=dos_instituciones["prioridad_id"],
            estado_id=ids["Pendiente"],
            producto_id=dos_instituciones["producto_id"],
        )

    assert respuesta.status_code == 409, (rol, respuesta.text)
