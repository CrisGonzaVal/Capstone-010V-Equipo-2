"""AC-8: `POST /api/v1/tickets/` es atomica.

Este archivo existe por una regresion concreta. La version previa del endpoint
hacia `db.commit()` apenas creaba el `Ticket` y recien despues agregaba los
`DetalleTicket`. Si un detalle fallaba (producto inexistente), el ticket ya
estaba commiteado y quedaba huerfano en `ticket` con cero detalles.

La extraccion a `ticket_service.py` lo corrige con `flush()` + un unico
`commit()`. Este test falla si alguien reintroduce el commit intermedio.

Las aserciones leen la API, no la base de datos: el rollback se comprueba
viendo que el ticket nunca aparecio en `GET /api/v1/tickets/`.
"""


def _cuerpo_ticket(datos_base, detalles, asunto="Ticket de prueba"):
    return {
        "usuario_id": datos_base["usuario_id"],
        "prioridad_id": datos_base["prioridad_id"],
        "estado_id": datos_base["estado_ingresado_id"],
        "asunto": asunto,
        "descripcion": "Descripcion de prueba.",
        "detalles": detalles,
    }


def test_detalle_invalido_no_deja_ticket_huerfano(cliente_sin_excepcion, datos_base):
    """1 detalle valido + 1 con producto inexistente no debe persistir nada."""
    cuerpo = _cuerpo_ticket(
        datos_base,
        detalles=[
            {"producto_id": datos_base["producto_id"], "cantidad_solicitada": 5},
            {"producto_id": 999999, "cantidad_solicitada": 1},
        ],
    )

    respuesta = cliente_sin_excepcion.post("/api/v1/tickets/", json=cuerpo)
    # DEFECTO CONOCIDO: la API responde 500 en vez de 4xx porque `crear_ticket`
    # no traduce el `IntegrityError`. Es preexistente (no lo introdujo la
    # extraccion a servicios) y esta fuera del alcance de la Feature 001, que
    # solo reordena codigo. Ver "Hallazgos de la Fase C" en `tasks.md`.
    assert respuesta.status_code == 500, respuesta.text

    # Lo que AC-8 protege de verdad: el ticket no debe existir. Esta asercion
    # falla si alguien reintroduce el `commit()` intermedio.
    assert cliente_sin_excepcion.get("/api/v1/tickets/").json() == []


def test_detalle_invalido_no_deja_ticket_por_mas_que_haya_tres_detalles(
    cliente_sin_excepcion, datos_base
):
    """El fallo en el ultimo de N detalles tambien revierte los anteriores."""
    detalles = [
        {"producto_id": datos_base["producto_id"], "cantidad_solicitada": n}
        for n in (1, 2, 3)
    ]
    detalles.append({"producto_id": 999999, "cantidad_solicitada": 4})

    respuesta = cliente_sin_excepcion.post(
        "/api/v1/tickets/", json=_cuerpo_ticket(datos_base, detalles)
    )
    assert respuesta.status_code == 500
    assert cliente_sin_excepcion.get("/api/v1/tickets/").json() == []


def test_ticket_valido_persiste_cabecera_y_detalles_juntos(cliente, datos_base):
    """Contraprueba del anterior: el camino feliz sigue funcionando."""
    cuerpo = _cuerpo_ticket(
        datos_base,
        detalles=[
            {"producto_id": datos_base["producto_id"], "cantidad_solicitada": 5},
            {"producto_id": datos_base["producto_id"], "cantidad_solicitada": 7},
        ],
    )

    respuesta = cliente.post("/api/v1/tickets/", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text

    listados = cliente.get("/api/v1/tickets/").json()
    assert len(listados) == 1
    assert len(listados[0]["detalles"]) == 2
    assert sorted(d["cantidad_solicitada"] for d in listados[0]["detalles"]) == [5, 7]


def test_detalle_invalido_no_altera_el_stock(cliente_sin_excepcion, datos_base):
    """Crear un ticket no debe mover inventario, ni siquiera al fallar.

    Marca el limite de la operacion: `crear_ticket` es atomica, pero todavia
    no descuenta stock. Ese descuento pertenece a la approbacion del ticket
    (Feature 004/005), no a la creacion.
    """
    stock_antes = cliente_sin_excepcion.get("/api/v1/inventario/stock").json()[0]["stock_actual"]

    cuerpo = _cuerpo_ticket(
        datos_base,
        detalles=[
            {"producto_id": datos_base["producto_id"], "cantidad_solicitada": 5},
            {"producto_id": 999999, "cantidad_solicitada": 1},
        ],
    )
    assert cliente_sin_excepcion.post("/api/v1/tickets/", json=cuerpo).status_code == 500

    stock_despues = cliente_sin_excepcion.get("/api/v1/inventario/stock").json()[0]["stock_actual"]
    assert stock_despues == stock_antes


def test_saldo_insuficiente_no_registra_movimiento(cliente, datos_base):
    """Trazabilidad absoluta (`constitucion.md` §2): un rechazo no deja rastro.

    Un movimiento rechazado no debe generar fila en `movimiento_inventario`, y el
    stock debe quedar intacto. Se verifica por la API: el stock no cambia y el
    siguiente movimiento valido debe partir del valor original, no de uno
    corrompido.
    """
    saldo_insuficiente = cliente.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo_movimiento": "SALIDA",
            "cantidad": 9999,
            "observacion": "Debe rechazarse",
            "inventario_id": datos_base["inventario_id"],
        },
    )
    assert saldo_insuficiente.status_code == 400, saldo_insuficiente.text

    stock = cliente.get("/api/v1/inventario/stock").json()
    assert stock[0]["stock_actual"] == 50

    # La siguiente operacion valida debe partir de 50, no del valor alterado.
    entrada = cliente.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo_movimiento": "ENTRADA",
            "cantidad": 10,
            "observacion": "Ingreso posterior",
            "inventario_id": datos_base["inventario_id"],
        },
    )
    assert entrada.status_code == 201, entrada.text
    assert entrada.json()["nuevo_stock"] == 60


def test_tipo_de_movimiento_invalido_no_registra_movimiento(cliente, datos_base):
    respuesta = cliente.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo_movimiento": "AJUSTE_MAGICO",
            "cantidad": 1,
            "observacion": "Tipo no permitido",
            "inventario_id": datos_base["inventario_id"],
        },
    )
    assert respuesta.status_code == 400, respuesta.text
    assert cliente.get("/api/v1/inventario/stock").json()[0]["stock_actual"] == 50
