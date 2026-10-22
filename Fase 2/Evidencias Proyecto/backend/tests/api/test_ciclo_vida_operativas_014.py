"""T2 (Feature 014): efecto en consultas y operaciones de inventario, tickets y dashboard.

Seam bajo prueba: la interfaz HTTP (`TestClient`). Fija las reglas de visibilidad
y compatibilidad de la 014 (D-7/AC-4/AC-9/AC-10):

* productos inactivos, y productos cuya categoria esta inactiva, se excluyen de
  `GET /inventario/existencias`, de los listados operativos del catalogo, de los
  catalogos de ticket y de los filtros operativos; las categorias inactivas
  tambien se excluyen de esos listados;
* las referencias historicas (detalles de tickets y movimientos previos) siguen
  resolviendo producto y categoria aunque esten inactivos;
* un movimiento nuevo sobre producto inactivo responde 409 sin cambios; el alta
  de ticket con producto inactivo responde 409 sin escritura; la edicion de un
  ticket `Pendiente` conserva y permite cambiar la cantidad de un producto
  inactivo que **ya figura** en sus detalles, pero rechaza con 409 uno nuevo;
* el despacho de tickets abiertos no tiene regla especial de catalogo: con saldo
  cero falla con el error vigente de stock insuficiente y sin efectos parciales;
* el dashboard de la 009 excluye inactivos del stock critico, del conteo y del
  listado de alertas (AC-10).

Fase ROJA de TDD: la columna `activo`, las tablas de historial y los filtros aun
no existen (T4/T8); las pruebas caen en rojo por esas ausencias, nunca por
imports ni sintaxis.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import MovimientoInventario, StockSede, Ticket

from ._soporte_ciclo_vida_catalogo_014 import (
    cliente_de_rol,
    contar,
    crear_categoria,
    crear_producto,
    exigir_ruta,
    fijar_stock_sede,
    marcar_producto,
    sembrar_mundo_014,
    sesion,
    transicionar_categoria,
    transicionar_producto,
)
from ._soporte_ciclo_vida_013 import sembrar_ticket

RUTA_PRODUCTO_ESTADO = "/api/v1/inventario/productos/{producto_id}/estado"


@pytest.fixture
def mundo(motor, dos_instituciones):
    return sembrar_mundo_014(motor, dos_instituciones)


def _admin(motor, datos, **opciones):
    return cliente_de_rol(motor, datos, "Administrador", **opciones)


def _cli(motor, datos, rol, **opciones):
    return cliente_de_rol(motor, datos, rol, **opciones)


def _retirar_producto(motor, datos, producto_id: int, motivo: str = "Retiro 014") -> None:
    """Desactiva un producto por la via real (exige saldo cero)."""
    exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
    with _admin(motor, datos) as cliente:
        respuesta = transicionar_producto(
            cliente, producto_id, activo=False, motivo=motivo
        )
        assert respuesta.status_code == 200, respuesta.text


def _stock_sede_id(motor, datos, producto_id: int) -> int:
    with sesion(motor) as db:
        return db.execute(
            select(StockSede).where(
                StockSede.sede_id == datos["sede_id"],
                StockSede.producto_id == producto_id,
            )
        ).scalar_one().stock_sede_id


def _ids(cuerpo: list[dict], clave: str) -> set[int]:
    return {fila[clave] for fila in cuerpo}


# ---------------------------------------------------------------------------
# AC-4: inactivos excluidos de operativas y existencias
# ---------------------------------------------------------------------------


def test_existencias_excluye_producto_inactivo_y_categoria_inactiva_ac_4(motor, mundo):
    """AC-4: `GET /inventario/existencias` omite ambos casos de vigencia."""
    inactivo = crear_producto(motor, mundo, nombre="Producto retirado 014", stock_sede=0)
    _retirar_producto(motor, mundo, inactivo)

    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada 014")
    de_categoria_inactiva = crear_producto(
        motor, mundo, nombre="Producto de categoria retirada",
        categoria_id=categoria, stock_sede=0,
    )
    _retirar_producto(motor, mundo, de_categoria_inactiva)
    with _admin(motor, mundo) as cliente:
        respuesta_categoria = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Retiro de la categoria"
        )
        assert respuesta_categoria.status_code == 200, respuesta_categoria.text

    with _admin(motor, mundo) as cliente:
        respuesta = cliente.get("/api/v1/inventario/existencias")
        assert respuesta.status_code == 200, respuesta.text
        ids = _ids(respuesta.json(), "producto_id")
        assert inactivo not in ids
        assert de_categoria_inactiva not in ids
        assert mundo["producto_id"] in ids, "el producto activo sigue visible"


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_listados_operativos_excluyen_inactivos_para_todos_los_roles_ac_4(
    motor, mundo, rol
):
    """AC-4: el filtro es uniforme; no hay excepcion para el Administrador."""
    categoria = crear_categoria(motor, mundo, nombre=f"Categoria inactiva {rol}")
    producto = crear_producto(
        motor, mundo, nombre=f"Producto inactivo {rol}", stock_sede=0
    )
    _retirar_producto(motor, mundo, producto)
    with _admin(motor, mundo) as cliente:
        assert transicionar_categoria(
            cliente, categoria, activo=False, motivo="Categoria sin productos"
        ).status_code == 200

    with _cli(motor, mundo, rol) as cliente:
        productos = cliente.get("/api/v1/inventario/productos")
        categorias = cliente.get("/api/v1/inventario/categorias")
        assert productos.status_code == 200, productos.text
        assert categorias.status_code == 200, categorias.text
        assert producto not in _ids(productos.json(), "producto_id")
        assert categoria not in _ids(categorias.json(), "categoria_id")
        assert mundo["producto_id"] in _ids(productos.json(), "producto_id")


def test_catalogos_de_ticket_excluyen_producto_inactivo_ac_4(motor, mundo):
    """AC-4: el selector de alta de ticket no ofrece productos inactivos."""
    producto = crear_producto(motor, mundo, nombre="No ofertable 014", stock_sede=0)
    _retirar_producto(motor, mundo, producto)

    with _cli(motor, mundo, "Solicitante") as cliente:
        respuesta = cliente.get("/api/v1/tickets/catalogos")
        assert respuesta.status_code == 200, respuesta.text
        ids = _ids(respuesta.json()["productos"], "producto_id")
        assert producto not in ids
        assert mundo["producto_id"] in ids


def test_referencias_historicas_siguen_resolviendo_inactivos_ac_4(motor, mundo):
    """AC-4: ticket y movimiento previos conservan producto/categoria resueltos."""
    producto = crear_producto(motor, mundo, nombre="Historico 014", stock_sede=0)
    stock_sede_id = _stock_sede_id(motor, mundo, producto)

    with _admin(motor, mundo) as cliente:
        entrada = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 3,
                "observacion": "Entrada previa a la baja 014",
                "stock_sede_id": stock_sede_id,
            },
        )
        assert entrada.status_code == 201, entrada.text
        salida = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "SALIDA",
                "cantidad": 3,
                "observacion": "Salida previa a la baja 014",
                "stock_sede_id": stock_sede_id,
            },
        )
        assert salida.status_code == 201, salida.text

    ticket_id = sembrar_ticket(
        motor,
        mundo,
        producto_id=producto,
        estado_id=mundo["estados"]["Cerrado"],
        asunto="Ticket cerrado antes del retiro",
    )
    _retirar_producto(motor, mundo, producto)

    with _admin(motor, mundo) as cliente:
        tickets = cliente.get("/api/v1/tickets/")
        assert tickets.status_code == 200, tickets.text
        ticket = next(t for t in tickets.json() if t["ticket_id"] == ticket_id)
        detalle = ticket["detalles"][0]
        assert detalle["producto"]["nombre"] == "Historico 014"
        assert detalle["producto"]["categoria"]["nombre_cat"] == "Papeleria"

        movimientos = cliente.get("/api/v1/inventario/movimientos")
        assert movimientos.status_code == 200, movimientos.text
        del_producto = [
            fila
            for fila in movimientos.json()
            if fila["producto_id"] == producto
        ]
        assert len(del_producto) == 2, del_producto
        assert all(fila["producto_nombre"] == "Historico 014" for fila in del_producto)


# ---------------------------------------------------------------------------
# AC-9: movimientos y tickets
# ---------------------------------------------------------------------------


def test_movimiento_sobre_producto_inactivo_responde_409_sin_cambios_ac_9(motor, mundo):
    """AC-9: no se registra stock nuevo sobre un producto inactivo."""
    producto = crear_producto(motor, mundo, nombre="Movimiento prohibido", stock_sede=0)
    stock_sede_id = _stock_sede_id(motor, mundo, producto)
    _retirar_producto(motor, mundo, producto)
    movimientos_antes = contar(motor, MovimientoInventario)

    with _admin(motor, mundo) as cliente:
        respuesta = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "observacion": "No debe registrarse",
                "stock_sede_id": stock_sede_id,
            },
        )
        assert respuesta.status_code == 409, respuesta.text

    with sesion(motor) as db:
        assert db.get(StockSede, stock_sede_id).stock_actual == 0
    assert contar(motor, MovimientoInventario) == movimientos_antes


def test_alta_de_ticket_con_producto_inactivo_responde_409_sin_escritura_ac_9(
    motor, mundo
):
    """AC-9: un ticket nuevo no puede solicitar un producto inactivo."""
    producto = crear_producto(motor, mundo, nombre="No solicitable 014", stock_sede=0)
    _retirar_producto(motor, mundo, producto)
    tickets_antes = contar(motor, Ticket)

    with _cli(motor, mundo, "Solicitante") as cliente:
        respuesta = cliente.post(
            "/api/v1/tickets/",
            json={
                "usuario_id": mundo["usuarios_inst01"]["Solicitante"],
                "prioridad_id": mundo["prioridad_id"],
                "estado_id": mundo["estados"]["Pendiente"],
                "asunto": "Solicitud de producto inactivo",
                "descripcion": "No debe crearse.",
                "detalles": [
                    {"producto_id": producto, "cantidad_solicitada": 2}
                ],
            },
        )
        assert respuesta.status_code == 409, respuesta.text

    assert contar(motor, Ticket) == tickets_antes, (
        "el 409 del alta no puede dejar ticket ni detalle parcial"
    )


def test_edicion_pendiente_conserva_inactivo_existente_y_cambia_cantidad_ac_9(
    motor, mundo
):
    """AC-9: si el producto inactivo ya figura en los detalles, se conserva."""
    producto = crear_producto(motor, mundo, nombre="Item retenido 014", stock_sede=0)
    ticket_id = sembrar_ticket(motor, mundo, producto_id=producto, cantidad=3)
    _retirar_producto(motor, mundo, producto)

    with _cli(motor, mundo, "Solicitante") as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json={
                "asunto": "Edicion con item inactivo existente",
                "descripcion": "Se conserva el producto y se cambia la cantidad.",
                "prioridad_id": mundo["prioridad_id"],
                "detalles": [
                    {"producto_id": producto, "cantidad_solicitada": 5}
                ],
            },
        )
        assert respuesta.status_code == 200, respuesta.text

        tickets = cliente.get("/api/v1/tickets/")
        assert tickets.status_code == 200, tickets.text
        ticket = next(t for t in tickets.json() if t["ticket_id"] == ticket_id)
        detalles = [
            (fila["producto_id"], fila["cantidad_solicitada"])
            for fila in ticket["detalles"]
        ]
        assert detalles == [(producto, 5)], detalles


def test_edicion_pendiente_rechaza_inactivo_no_presente_ac_9(motor, mundo):
    """AC-9: un producto inactivo que no figura en el ticket se rechaza con 409."""
    producto = crear_producto(motor, mundo, nombre="No presente 014", stock_sede=0)
    ticket_id = sembrar_ticket(
        motor, mundo, producto_id=mundo["producto_id"], cantidad=3
    )
    _retirar_producto(motor, mundo, producto)

    with _cli(motor, mundo, "Solicitante") as cliente:
        respuesta = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json={
                "asunto": "Intento de agregar un producto inactivo",
                "descripcion": "No debe pasar.",
                "prioridad_id": mundo["prioridad_id"],
                "detalles": [
                    {"producto_id": producto, "cantidad_solicitada": 1}
                ],
            },
        )
        assert respuesta.status_code == 409, respuesta.text

        tickets = cliente.get("/api/v1/tickets/")
        assert tickets.status_code == 200, tickets.text
        ticket = next(t for t in tickets.json() if t["ticket_id"] == ticket_id)
        assert [
            (fila["producto_id"], fila["cantidad_solicitada"])
            for fila in ticket["detalles"]
        ] == [(mundo["producto_id"], 3)], "el 409 no puede reemplazar los detalles"


def test_despacho_abierto_con_saldo_cero_conserva_el_error_vigente_ac_9(motor, mundo):
    """AC-9: el despacho no tiene regla especial; con saldo cero falla como antes."""
    producto = crear_producto(motor, mundo, nombre="Despacho sin saldo", stock_sede=0)
    ticket_id = sembrar_ticket(
        motor,
        mundo,
        producto_id=producto,
        cantidad=3,
        estado_id=mundo["estados"]["EnCurso"],
    )
    _retirar_producto(motor, mundo, producto)
    movimientos_antes = contar(motor, MovimientoInventario)

    with _admin(motor, mundo) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/despacho",
            json={"usuario_id": mundo["usuario_id"]},
        )
        assert respuesta.status_code == 409, respuesta.text
        assert "insuficiente" in respuesta.json()["detail"].lower(), respuesta.json()

        tickets = cliente.get("/api/v1/tickets/")
        ticket = next(t for t in tickets.json() if t["ticket_id"] == ticket_id)
        assert ticket["estado_id"] == mundo["estados"]["EnCurso"], (
            "el fallo de despacho no puede cambiar el estado"
        )
    assert contar(motor, MovimientoInventario) == movimientos_antes


# ---------------------------------------------------------------------------
# AC-10: dashboard
# ---------------------------------------------------------------------------


def test_dashboard_excluye_inactivos_de_alertas_y_conteo_ac_10(motor, mundo):
    """AC-10: alertas y su conteo omiten producto inactivo y categoria inactiva."""
    critico_activo = crear_producto(
        motor, mundo, nombre="Critico activo 014", stock_minimo=10, stock_sede=1
    )
    critico_inactivo = crear_producto(
        motor, mundo, nombre="Critico inactivo 014", stock_minimo=10, stock_sede=1
    )
    categoria = crear_categoria(motor, mundo, nombre="Categoria critica 014")
    critico_de_categoria = crear_producto(
        motor,
        mundo,
        nombre="Critico de categoria inactiva",
        categoria_id=categoria,
        stock_minimo=10,
        stock_sede=1,
    )
    # La preparacion fija el estado directamente: AC-6 impide retirar por HTTP un
    # producto con saldo positivo, y el escenario necesita ese saldo para que la
    # alerta exista y su exclusion discrimine. Mismo patron que la prueba de
    # servicio de AC-10.
    marcar_producto(motor, critico_inactivo, False)
    marcar_producto(motor, critico_de_categoria, False)
    with _admin(motor, mundo) as cliente:
        assert transicionar_categoria(
            cliente, categoria, activo=False, motivo="Categoria sin productos activos"
        ).status_code == 200

    with _admin(motor, mundo) as cliente:
        respuesta = cliente.get("/api/v1/dashboard/")
        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        ids_alertas = _ids(cuerpo["alertas"], "producto_id")
        assert critico_activo in ids_alertas
        assert critico_inactivo not in ids_alertas
        assert critico_de_categoria not in ids_alertas
        assert cuerpo["kpi"]["total_alertas"] == len(cuerpo["alertas"]), (
            "el conteo de alertas debe coincidir con el listado filtrado"
        )
