"""T2 (Feature 013): anulacion/rechazo, guards de `PATCH /estado` y orden (AC-1…AC-7).

Seam bajo prueba: la **interfaz HTTP** (`TestClient`), como en toda la suite.
El catalogo es el canonico de la 013 (`Pendiente → EnRevision → EnCurso →
Cerrado`, mas `Anulado` al final, fuera del flujo lineal) y los tickets se
siembran por ORM para poder estar en cualquier estado.

Fase ROJA de TDD: las rutas `/anulacion` y `/rechazo` y los guards de
`PATCH /estado` hacia/desde `Anulado` aun no existen (los cablea T7), de modo
que las pruebas caen en rojo por esas ausencias (404 del router o detalle sin
dirigir a la operacion), nunca por imports, fixtures ni sintaxis. Las pruebas
de regresion de la 004/005 (cierre reservado, despacho) ya pasan hoy y deben
seguirlo pasando tras T7-T9.
"""

from __future__ import annotations

import pytest

from ._soporte_ciclo_vida_013 import (
    CAMPOS_HISTORIAL,
    DETALLE_TICKET_NO_ENCONTRADO,
    abrir_ticket,
    cliente_con_rol,
    contar_en,
    leer_historial,
    leer_stock_sede,
    payload_alta,
    sembrar_mundo_013,
    sembrar_ticket,
    exigir_ruta,
)

RUTA_ANULACION = "/api/v1/tickets/{ticket_id}/anulacion"
RUTA_RECHAZO = "/api/v1/tickets/{ticket_id}/rechazo"


@pytest.fixture
def datos_013(motor, dos_instituciones):
    """Padron de dos instituciones + catalogo 013 + sede con stock 50."""
    return sembrar_mundo_013(motor, dos_instituciones)


def _cliente_solicitante(motor, datos):
    return cliente_con_rol(
        motor,
        "Solicitante",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Solicitante"],
    )


def _cliente_bodeguero(motor, datos):
    return cliente_con_rol(
        motor,
        "Bodeguero",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Bodeguero"],
    )


def _cliente_administrador(motor, datos):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuario_id"],
    )


def _anular_o_rechazar(cliente, ticket_id: int, operacion: str, motivo: str):
    return cliente.post(
        f"/api/v1/tickets/{ticket_id}/{operacion}", json={"motivo": motivo}
    )


# ---------------------------------------------------------------------------
# AC-1: anulacion desde Pendiente/EnRevision -> 200 con efectos completos
# ---------------------------------------------------------------------------


def test_anulacion_desde_pendiente_responde_200_con_historial_ac_1(
    motor, datos_013
):
    """AC-1: 200, ticket `Anulado`, `fecha_cierre` nula y fila con motivo literal."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )
    solicitante = datos_013["usuarios_inst01"]["Solicitante"]
    motivo = "Se anula por duplicado con otra solicitud"

    with _cliente_solicitante(motor, datos_013) as cliente:
        stock_antes = leer_stock_sede(
            motor, datos_013["sede_id"], datos_013["producto_id"]
        )
        movimientos_antes = contar_en(motor, "MovimientoInventario")
        respuesta = _anular_o_rechazar(cliente, ticket_id, "anulacion", motivo)

        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["estado_id"] == datos_013["estados"]["Anulado"]
        assert cuerpo["fecha_cierre"] is None, (
            "D-5: la anulacion no sella fecha_cierre"
        )
        assert leer_stock_sede(
            motor, datos_013["sede_id"], datos_013["producto_id"]
        ) == stock_antes, "la anulacion no mueve stock"
        assert contar_en(motor, "MovimientoInventario") == movimientos_antes, (
            "la anulacion no escribe movimientos de inventario"
        )

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1, (
            "exactamente la fila de la anulacion (el ticket no fue creado via API)"
        )
        fila = historial[0]
        assert CAMPOS_HISTORIAL <= set(fila), sorted(fila)
        assert fila["estado_origen_id"] == datos_013["estados"]["Pendiente"]
        assert fila["estado_destino_id"] == datos_013["estados"]["Anulado"]
        assert fila["usuario_id"] == solicitante, "el actor es el Solicitante"
        assert fila["motivo"] == motivo, "el motivo se persiste literal"
        assert fila["fecha_transicion"] is not None


def test_anulacion_desde_en_revision_tambien_es_200_ac_1(motor, datos_013):
    """AC-1: `EnRevision` tambien admite la anulacion (D-3, ambos inclusive)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnRevision"]
    )

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(
            cliente, ticket_id, "anulacion", "Revision cancelada por la jefatura"
        )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["estado_id"] == datos_013["estados"]["Anulado"]
        assert respuesta.json()["fecha_cierre"] is None


# ---------------------------------------------------------------------------
# AC-2: 409 desde EnCurso/Cerrado/Anulado, sin efectos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "estado", ["EnCurso", "Cerrado", "Anulado"], ids=["en_curso", "cerrado", "anulado"]
)
def test_anulacion_desde_estado_inadmisible_responde_409_sin_efectos_ac_2(
    motor, datos_013, estado
):
    """AC-2: 409 sin tocar el ticket ni agregar filas al historial."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"][estado]
    )

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(
            cliente, ticket_id, "anulacion", "Motivo valido pero estado inadmisible"
        )

        assert respuesta.status_code == 409, respuesta.text
        despues = abrir_ticket(cliente, ticket_id)
        assert despues["estado_id"] == datos_013["estados"][estado], (
            "un 409 no puede modificar el estado"
        )
        assert despues["fecha_cierre"] is None, (
            "un 409 de anulacion no puede sellar fecha_cierre"
        )
        exigir_ruta("/api/v1/tickets/{ticket_id}/historial", "GET")
        assert leer_historial(cliente, ticket_id) == [], (
            "un 409 no puede agregar filas al historial"
        )


# ---------------------------------------------------------------------------
# AC-3: rechazo por Bodeguero/Administrador
# ---------------------------------------------------------------------------


def test_rechazo_por_bodeguero_desde_pendiente_es_200_ac_3(motor, datos_013):
    """AC-3: el Bodeguero rechaza con motivo y el ticket queda `Anulado`."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )
    motivo = "Sin stock disponible en la sede para esta solicitud"

    with _cliente_bodeguero(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(cliente, ticket_id, "rechazo", motivo)

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["estado_id"] == datos_013["estados"]["Anulado"]
        assert respuesta.json()["fecha_cierre"] is None

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1
        assert historial[0]["usuario_id"] == datos_013["usuarios_inst01"]["Bodeguero"]
        assert historial[0]["motivo"] == motivo
        assert historial[0]["estado_destino_id"] == datos_013["estados"]["Anulado"]


def test_rechazo_por_administrador_desde_en_revision_es_200_ac_3(
    motor, datos_013
):
    """AC-3: el Administrador tambien rechaza, con los mismos efectos."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnRevision"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(
            cliente, ticket_id, "rechazo", "Rechazo institucional"
        )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["estado_id"] == datos_013["estados"]["Anulado"]


def test_rechazo_desde_en_curso_responde_409_sin_efectos_ac_3(motor, datos_013):
    """AC-3: desde `EnCurso` el rechazo no admite; 409 sin efectos (D-3)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(
            cliente, ticket_id, "rechazo", "Motivo valido pero estado inadmisible"
        )

        assert respuesta.status_code == 409, respuesta.text
        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["EnCurso"]
        )
        exigir_ruta("/api/v1/tickets/{ticket_id}/historial", "GET")
        assert leer_historial(cliente, ticket_id) == []


# ---------------------------------------------------------------------------
# AC-4: `PATCH /estado` no lleva a `Anulado` ni sale de el
# ---------------------------------------------------------------------------


def test_patch_estado_no_lleva_a_anulado_y_dirige_a_la_operacion_ac_4(
    motor, datos_013
):
    """AC-4/D-4: hacia `Anulado` responde 409 cuyo detalle dirige a la operacion."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = cliente.patch(
            f"/api/v1/tickets/{ticket_id}/estado",
            json={"estado_id": datos_013["estados"]["Anulado"]},
        )

        assert respuesta.status_code == 409, respuesta.text
        detalle = respuesta.json()["detail"].lower()
        assert "anulacion" in detalle or "rechazo" in detalle, (
            f"el 409 debe dirigir a la operacion correspondiente; detal: {detalle}"
        )
        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["Pendiente"]
        )


def test_patch_estado_no_sale_de_anulado_ac_4(motor, datos_013):
    """AC-4: `Anulado` es terminal tambien para el flujo lineal (D-4)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Anulado"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        for destino in ("EnRevision", "Pendiente", "EnCurso", "Cerrado"):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos_013["estados"][destino]},
            )
            assert respuesta.status_code == 409, (destino, respuesta.text)
            assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
                datos_013["estados"]["Anulado"]
            ), f"nada puede sacar el ticket de Anulado ({destino})"


# ---------------------------------------------------------------------------
# AC-5: despacho intacto y su fila de historial
# ---------------------------------------------------------------------------


def test_en_curso_a_cerrado_sigue_reservado_al_despacho_ac_5(motor, datos_013):
    """AC-5/AC-15-005: el 409 y su detalle literal quedan intactos (regresion)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        respuesta = cliente.patch(
            f"/api/v1/tickets/{ticket_id}/estado",
            json={"estado_id": datos_013["estados"]["Cerrado"]},
        )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == (
        "El cierre requiere despacho; use "
        f"POST /api/v1/tickets/{ticket_id}/despacho"
    )


def test_despacho_registra_su_transicion_en_el_historial_ac_5(motor, datos_013):
    """AC-5/AC-9: el despacho de la 005 es una mutacion y suma su fila."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        despacho = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": datos_013["usuarios_inst01"]["Bodeguero"]},
        )
        assert despacho.status_code == 200, despacho.text
        assert despacho.json()["fecha_cierre"] is not None, (
            "el despacho sigue sellando fecha_cierre (004/005 intactos)"
        )

        historial = leer_historial(cliente, ticket_id)
        assert len(historial) == 1, (
            "exactamente la fila del despacho (ticket sembrado por ORM, sin "
            f"creacion via API); historial: {historial}"
        )
        fila = historial[0]
        assert fila["estado_origen_id"] == datos_013["estados"]["EnCurso"]
        assert fila["estado_destino_id"] == datos_013["estados"]["Cerrado"]
        assert fila["motivo"] is None, "el despacho no exige motivo"


def test_despacho_de_un_anulado_responde_409_sin_movimientos_ac_5(
    motor, datos_013
):
    """AC-5: un ticket `Anulado` no es despachable (409, estado no elegible)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Anulado"]
    )
    movimientos_antes = contar_en(motor, "MovimientoInventario")
    stock_antes = leer_stock_sede(
        motor, datos_013["sede_id"], datos_013["producto_id"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": datos_013["usuarios_inst01"]["Bodeguero"]},
        )

        assert respuesta.status_code == 409, respuesta.text
        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["Anulado"]
        )
        assert contar_en(motor, "MovimientoInventario") == movimientos_antes
        assert leer_stock_sede(
            motor, datos_013["sede_id"], datos_013["producto_id"]
        ) == stock_antes


# ---------------------------------------------------------------------------
# AC-6: fecha_cierre solo por cierre; anulacion no la sella
# ---------------------------------------------------------------------------


def test_alta_en_cerrado_sella_fecha_cierre_ac_6(motor, datos_013):
    """AC-6/AC-17-004: `Cerrado` por alta directa conserva su sellado (regresion)."""
    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.post(
            "/api/v1/tickets/",
            json=payload_alta(datos_013, datos_013["estados"]["Cerrado"]),
        )

        assert respuesta.status_code == 201, respuesta.text
        assert respuesta.json()["fecha_cierre"] is not None


def test_despacho_sella_fecha_cierre_ac_6(motor, datos_013):
    """AC-6: `Cerrado` por despacho conserva el sellado (regresion 005)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": datos_013["usuarios_inst01"]["Bodeguero"]},
        )

        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["fecha_cierre"] is not None


# ---------------------------------------------------------------------------
# D-11: un ticket nuevo no puede nacer en `Anulado`
# ---------------------------------------------------------------------------


def test_alta_en_anulado_responde_409_sin_ticket_d11(motor, datos_013):
    """D-11/plan decision 8: `Anulado` no es elegible para alta (409).

    El estado existe en el catalogo, por lo que el rechazo es 409 (precondicion)
    y no 404/422; el alta no puede dejar ni ticket ni detalle parciales.
    """
    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta = cliente.post(
            "/api/v1/tickets/",
            json=payload_alta(datos_013, datos_013["estados"]["Anulado"]),
        )

        assert respuesta.status_code == 409, respuesta.text
        assert cliente.get("/api/v1/tickets/").json() == [], (
            "un 409 de alta no puede dejar un ticket creado"
        )


# ---------------------------------------------------------------------------
# AC-7: orden de respuestas 404 -> 409 -> 422 ante problemas simultaneos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_orden_404_ante_422_con_ticket_inexistente_y_motivo_invalido_ac_7(
    motor, datos_013, operacion
):
    """AC-7: inexistente gana a motivo invalido; el 404 es el de ocultamiento."""
    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(cliente, 999999, operacion, "")

    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO, (
        "el 404 debe ser el de ocultamiento, no un 422 de Pydantic ni el "
        f"'Not Found' del router: {respuesta.text}"
    )


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_orden_409_ante_422_con_estado_inadmisible_y_motivo_invalido_ac_7(
    motor, datos_013, operacion
):
    """AC-7: estado inadmisible gana a motivo invalido (409, no 422)."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(cliente, ticket_id, operacion, "")

    assert respuesta.status_code == 409, respuesta.text


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_422_de_motivo_invalido_no_modifica_nada_ac_7(
    motor, datos_013, operacion
):
    """AC-7/AC-8: con ticket adelible y motivo invalido el 422 no escribe nada."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Pendiente"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(cliente, ticket_id, operacion, "")

        assert respuesta.status_code == 422, respuesta.text
        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["Pendiente"]
        ), "el 422 no puede modificar el estado"
        exigir_ruta("/api/v1/tickets/{ticket_id}/historial", "GET")
        assert leer_historial(cliente, ticket_id) == [], (
            "el 422 no puede agregar filas al historial"
        )


@pytest.mark.parametrize("operacion", ["anulacion", "rechazo"])
def test_409_de_estado_inadmisible_con_motivo_valido_ac_7(
    motor, datos_013, operacion
):
    """AC-7: con ambos problemas, el 409 observado lleva el motivo al servicio."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["Cerrado"]
    )

    with _cliente_administrador(motor, datos_013) as cliente:
        respuesta = _anular_o_rechazar(
            cliente, ticket_id, operacion, "Motivo valido que nunca debe persistirse"
        )

        assert respuesta.status_code == 409, respuesta.text
        exigir_ruta("/api/v1/tickets/{ticket_id}/historial", "GET")
        assert leer_historial(cliente, ticket_id) == []


# ---------------------------------------------------------------------------
# AC-26: terminalidad por nombre en CUALQUIER catalogo (enmienda D-4)
# ---------------------------------------------------------------------------


def _mundo_catalogo_degenerado(motor, datos, nombres_estados):
    """Mundo 013 con un catalogo degenerado a medida (sin `Anulado` canonico
    al final, con `Cerrado` en medio, etc.)."""
    return sembrar_mundo_013(motor, datos, nombres_estados=nombres_estados)


def test_catalogo_degenerado_sin_salida_desde_cerrado_ac_26(motor, dos_instituciones):
    """AC-26: `Cerrado` en medio del catalogo sigue sin admitir salida (409)."""
    datos = _mundo_catalogo_degenerado(
        motor,
        dos_instituciones,
        ("Pendiente", "EnRevision", "Cerrado", "Archivado", "Anulado"),
    )
    assert datos["estados"]["Cerrado"] < datos["estados"]["Anulado"], (
        "precondicion del caso degenerado: Cerrado NO es el ultimo del catalogo"
    )
    ticket_id = sembrar_ticket(
        motor, datos, estado_id=datos["estados"]["Cerrado"]
    )

    with _cliente_administrador(motor, datos) as cliente:
        for destino in ("Pendiente", "EnRevision", "Archivado", "Anulado"):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos["estados"][destino]},
            )
            assert respuesta.status_code == 409, (destino, respuesta.text)
            if destino != "Anulado":
                # Hacia `Anulado` manda el guard que dirige a la operacion de
                # anulacion/rechazo; los demas 409 de salida desde `Cerrado`
                # declaran el cierre definitivo y el despacho como unico camino.
                assert "despacho" in respuesta.json()["detail"].lower(), (
                    destino, respuesta.text
                )
            assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
                datos["estados"]["Cerrado"]
            ), f"nada puede sacar el ticket de Cerrado ({destino})"


def test_catalogo_degenerado_sin_salida_desde_anulado_ac_26(motor, dos_instituciones):
    """AC-26: `Anulado` en medio del catalogo sigue sin admitir salida (409)."""
    datos = _mundo_catalogo_degenerado(
        motor,
        dos_instituciones,
        ("Pendiente", "Anulado", "EnRevision", "EnCurso", "Cerrado"),
    )
    assert datos["estados"]["Anulado"] < datos["estados"]["Cerrado"], (
        "precondicion del caso degenerado: Anulado NO es el ultimo del catalogo"
    )
    ticket_id = sembrar_ticket(
        motor, datos, estado_id=datos["estados"]["Anulado"]
    )

    with _cliente_administrador(motor, datos) as cliente:
        for destino in ("Pendiente", "EnRevision", "EnCurso", "Cerrado"):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos["estados"][destino]},
            )
            assert respuesta.status_code == 409, (destino, respuesta.text)
            detalle = respuesta.json()["detail"].lower()
            assert "anulacion" in detalle or "rechazo" in detalle, (
                f"el 409 debe dirigir a la operacion correspondiente: {detalle}"
            )
            assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
                datos["estados"]["Anulado"]
            ), f"nada puede sacar el ticket de Anulado ({destino})"


def test_reentrada_en_cerrado_es_imposible_en_catalogo_degenerado_ac_26(
    motor, dos_instituciones
):
    """AC-26: ninguna peticion de cambio de estado puede llevar un ticket **a**
    `Cerrado`, ni siquiera desde un estado contiguo en catalogo degenerado."""
    datos = _mundo_catalogo_degenerado(
        motor, dos_instituciones, ("Pendiente", "EnRevision", "Cerrado", "Archivado")
    )
    ticket_archivado = sembrar_ticket(
        motor, datos, estado_id=datos["estados"]["Archivado"],
        asunto="Ticket archivado que intenta reentrar en Cerrado",
    )
    ticket_en_revision = sembrar_ticket(
        motor, datos, estado_id=datos["estados"]["EnRevision"],
        asunto="Ticket en revision contiguo a un Cerrado degenerado",
    )

    with _cliente_administrador(motor, datos) as cliente:
        # Ambos son contiguos a `Cerrado` en este catalogo degenerado: sin la
        # terminalidad por nombre, las dos peticiones cerrarian el ticket.
        for ticket_id in (ticket_archivado, ticket_en_revision):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos["estados"]["Cerrado"]},
            )
            assert respuesta.status_code == 409, (ticket_id, respuesta.text)
            assert respuesta.json()["detail"] == (
                "El cierre requiere despacho; use "
                f"POST /api/v1/tickets/{ticket_id}/despacho"
            ), "el despacho transaccional es el unico camino a Cerrado (005)"
            assert abrir_ticket(cliente, ticket_id)["estado_id"] != (
                datos["estados"]["Cerrado"]
            ), "ninguna peticion puede llevar el ticket a Cerrado"


def test_ticket_despachado_no_vuelve_a_un_estado_despachable_ac_26(
    motor, datos_013
):
    """AC-26: sin salida desde `Cerrado` no hay doble rebaja de stock."""
    ticket_id = sembrar_ticket(
        motor, datos_013, estado_id=datos_013["estados"]["EnCurso"]
    )

    with _cliente_bodeguero(motor, datos_013) as cliente:
        despacho = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": datos_013["usuarios_inst01"]["Bodeguero"]},
        )
        assert despacho.status_code == 200, despacho.text
        fecha_sellada = despacho.json()["fecha_cierre"]
        stock_tras_despacho = leer_stock_sede(
            motor, datos_013["sede_id"], datos_013["producto_id"]
        )
        movimientos_tras_despacho = contar_en(motor, "MovimientoInventario")

        # Un ticket despachado no vuelve a ningun estado despachable.
        for destino in ("EnCurso", "EnRevision", "Pendiente"):
            respuesta = cliente.patch(
                f"/api/v1/tickets/{ticket_id}/estado",
                json={"estado_id": datos_013["estados"][destino]},
            )
            assert respuesta.status_code == 409, (destino, respuesta.text)
            despues = abrir_ticket(cliente, ticket_id)
            assert despues["estado_id"] == datos_013["estados"]["Cerrado"]
            assert despues["fecha_cierre"] == fecha_sellada, (
                "los 409 no pueden sobrescribir la fecha sellada por el despacho"
            )

        # Sin estado despachable no hay segundo despacho ni segunda rebaja.
        reintento = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": datos_013["usuarios_inst01"]["Bodeguero"]},
        )
        assert reintento.status_code == 409, reintento.text
        assert leer_stock_sede(
            motor, datos_013["sede_id"], datos_013["producto_id"]
        ) == stock_tras_despacho, "sin doble rebaja de stock"
        assert contar_en(motor, "MovimientoInventario") == movimientos_tras_despacho, (
            "sin movimientos de una segunda rebaja"
        )
