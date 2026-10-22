"""T8 (Feature 014): filtros operativos y reglas de catalogo en los servicios.

Seam bajo prueba: las funciones publicas de `inventario_service`,
`ticket_service` y `dashboard_service` sobre un motor SQLite en memoria. Las
rutas HTTP y su autorizacion se fijan en T9; aqui se acredita la logica que los
routers consumen (D-7, AC-4, AC-9, AC-10):

* disponibilidad operativa = `producto.activo AND categoria.activo`, aplicada
  igual en existencias, listados de catalogo, stock por sede y catalogos de
  ticket;
* un movimiento nuevo sobre producto inactivo responde 409 sin mutar saldo ni
  dejar auditoria;
* un alta de ticket sobre producto inactivo responde 409 sin escritura;
* la edicion de un ticket `Pendiente` conserva (y permite cambiar cantidad de)
  un producto inactivo que ya figura en los detalles actuales, y rechaza con
  409 uno que no figura, sin reemplazar el conjunto previo;
* las referencias historicas (tickets cerrados y movimientos previos) siguen
  resolviendo producto y categoria aunque esten inactivos;
* el dashboard excluye inactivos del listado y del conteo de alertas, sin tocar
  los demas KPI.

El despacho no tiene regla especial de catalogo: su semantica vigente no cambia
y se cubre en la suite HTTP de tickets.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import (
    Categoria,
    DetalleTicket,
    MovimientoInventario,
    Producto,
    StockSede,
    Ticket,
)
from app.schemas.inventario_schema import MovimientoCrear
from app.schemas.ticket_schema import DetalleTicketCrear, TicketCrear, TicketEditar
from app.services import dashboard_service, inventario_service, ticket_service

from tests.api._soporte_ciclo_vida_catalogo_014 import (
    crear_categoria,
    crear_producto,
    fijar_stock_sede,
    marcar_categoria,
    marcar_producto,
    sembrar_mundo_014,
)
from tests.api._soporte_ciclo_vida_013 import sembrar_ticket
from tests.api._soporte_sede_011 import identidad, sesion


@pytest.fixture
def mundo(motor, dos_instituciones):
    return sembrar_mundo_014(motor, dos_instituciones)


def _admin(datos):
    return identidad(
        "Administrador", datos["departamento_id"], datos["usuario_id"]
    )


def _solicitante(datos):
    return identidad(
        "Solicitante",
        datos["departamento_id"],
        datos["usuarios_inst01"]["Solicitante"],
    )


def _stock_sede_id(motor, datos, producto_id: int) -> int:
    with sesion(motor) as db:
        return db.execute(
            select(StockSede.stock_sede_id).where(
                StockSede.sede_id == datos["sede_id"],
                StockSede.producto_id == producto_id,
            )
        ).scalar_one()


def _ids(coleccion, atributo: str) -> set[int]:
    return {getattr(fila, atributo) for fila in coleccion}


# ---------------------------------------------------------------------------
# AC-4: disponibilidad operativa = producto activo AND categoria activa
# ---------------------------------------------------------------------------


def test_existencias_excluye_producto_inactivo_y_categoria_inactiva(motor, mundo):
    """AC-4: la lectura operativa omite ambas formas de retiro."""
    inactivo = crear_producto(
        motor, mundo, nombre="Existencias retirado", stock_sede=0
    )
    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada existencias")
    de_categoria = crear_producto(
        motor,
        mundo,
        nombre="Existencias de categoria retirada",
        categoria_id=categoria,
        stock_sede=0,
    )
    marcar_producto(motor, inactivo, False)
    marcar_producto(motor, de_categoria, False)
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        existencias = inventario_service.listar_existencias(db, identidad=_admin(mundo))

    ids = _ids(existencias, "producto_id")
    assert inactivo not in ids
    assert de_categoria not in ids
    assert mundo["producto_id"] in ids, "el producto activo sigue visible"


def test_producto_activo_bajo_categoria_inactiva_tampoco_es_operativo(motor, mundo):
    """AC-4: el predicado es conjunto; no basta con que el producto este activo."""
    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada conjunta")
    producto = crear_producto(
        motor,
        mundo,
        nombre="Producto activo de categoria retirada",
        categoria_id=categoria,
        stock_sede=0,
    )
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        existencias = inventario_service.listar_existencias(db, identidad=_admin(mundo))
        productos = inventario_service.listar_productos(db, _admin(mundo))

    assert producto not in _ids(existencias, "producto_id")
    assert producto not in _ids(productos, "producto_id")


def test_listados_de_catalogo_excluyen_inactivos_para_administrador(motor, mundo):
    """AC-4: el Administrador tampoco ve inactivos en los listados operativos."""
    producto = crear_producto(
        motor, mundo, nombre="Catalogo retirado", stock_sede=0
    )
    categoria = crear_categoria(motor, mundo, nombre="Categoria de catalogo retirada")
    marcar_producto(motor, producto, False)
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        productos = inventario_service.listar_productos(db, _admin(mundo))
        categorias = inventario_service.listar_categorias(db, _admin(mundo))

    assert producto not in _ids(productos, "producto_id")
    assert categoria not in _ids(categorias, "categoria_id")
    assert mundo["producto_id"] in _ids(productos, "producto_id")
    assert mundo["categoria_id"] in _ids(categorias, "categoria_id")


def test_stock_por_sede_excluye_inactivos(motor, mundo):
    """AC-4: la serie operativa de saldo no expone productos retirados."""
    producto = crear_producto(
        motor, mundo, nombre="Stock retirado", stock_sede=0
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        filas = inventario_service.listar_stock_sede(db, identidad=_admin(mundo))

    assert producto not in _ids(filas, "producto_id")
    assert mundo["producto_id"] in _ids(filas, "producto_id")


def test_catalogos_de_ticket_excluyen_inactivos(motor, mundo):
    """AC-4: el selector de alta no ofrece productos ni de categoria retirada."""
    producto = crear_producto(
        motor, mundo, nombre="No ofertable servicio", stock_sede=0
    )
    categoria = crear_categoria(motor, mundo, nombre="Categoria no ofertable")
    de_categoria = crear_producto(
        motor,
        mundo,
        nombre="No ofertable por categoria",
        categoria_id=categoria,
        stock_sede=0,
    )
    marcar_producto(motor, producto, False)
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        catalogos = ticket_service.obtener_catalogos(db, _solicitante(mundo))

    ids = _ids(catalogos.productos, "producto_id")
    assert producto not in ids
    assert de_categoria not in ids
    assert mundo["producto_id"] in ids


def test_historial_de_ticket_resuelve_producto_inactivo(motor, mundo):
    """AC-4: el detalle de un ticket previo conserva su referencia historica."""
    producto = crear_producto(
        motor, mundo, nombre="Historico ticket 014", stock_sede=0
    )
    ticket_id = sembrar_ticket(
        motor,
        mundo,
        producto_id=producto,
        estado_id=mundo["estados"]["Cerrado"],
        asunto="Ticket cerrado antes del retiro",
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        tickets = ticket_service.listar_tickets(db, identidad=_admin(mundo))

    ticket = next(fila for fila in tickets if fila.ticket_id == ticket_id)
    detalle = ticket.detalles[0]
    assert detalle.producto.nombre == "Historico ticket 014"
    assert detalle.producto.categoria.nombre_cat == "Papeleria"


def test_historial_de_movimientos_resuelve_producto_inactivo(motor, mundo):
    """AC-4: la auditoria previa no se filtra ni se reescribe al retirar."""
    producto = crear_producto(
        motor, mundo, nombre="Historico movimiento 014", stock_sede=0
    )
    stock_sede_id = _stock_sede_id(motor, mundo, producto)
    with sesion(motor) as db:
        inventario_service.registrar_movimiento(
            db,
            MovimientoCrear(
                tipo_movimiento="ENTRADA",
                cantidad=4,
                observacion="Entrada previa al retiro",
                stock_sede_id=stock_sede_id,
            ),
            _admin(mundo),
        )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        movimientos = inventario_service.listar_movimientos(db, _admin(mundo))

    del_producto = [
        fila for fila in movimientos if fila.producto_id == producto
    ]
    assert len(del_producto) == 1
    assert del_producto[0].producto_nombre == "Historico movimiento 014"


# ---------------------------------------------------------------------------
# AC-9: movimientos y tickets
# ---------------------------------------------------------------------------


def test_movimiento_sobre_producto_inactivo_responde_409_sin_cambios(motor, mundo):
    """AC-9: ningun movimiento nuevo se registra sobre un producto retirado."""
    producto = crear_producto(
        motor, mundo, nombre="Movimiento prohibido servicio", stock_sede=0
    )
    stock_sede_id = _stock_sede_id(motor, mundo, producto)
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        movimientos_antes = db.execute(
            select(func.count()).select_from(MovimientoInventario)
        ).scalar_one()
        with pytest.raises(Exception) as error:
            inventario_service.registrar_movimiento(
                db,
                MovimientoCrear(
                    tipo_movimiento="ENTRADA",
                    cantidad=5,
                    observacion="No debe registrarse",
                    stock_sede_id=stock_sede_id,
                ),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        assert db.get(StockSede, stock_sede_id).stock_actual == 0
        assert db.execute(
            select(func.count()).select_from(MovimientoInventario)
        ).scalar_one() == movimientos_antes


def test_alta_de_ticket_con_producto_inactivo_responde_409_sin_escritura(motor, mundo):
    """AC-9: un ticket nuevo no puede pedir un producto retirado."""
    producto = crear_producto(
        motor, mundo, nombre="No solicitable servicio", stock_sede=0
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        tickets_antes = db.execute(
            select(func.count()).select_from(Ticket)
        ).scalar_one()
        detalles_antes = db.execute(
            select(func.count()).select_from(DetalleTicket)
        ).scalar_one()
        with pytest.raises(Exception) as error:
            ticket_service.crear_ticket(
                db,
                TicketCrear(
                    usuario_id=mundo["usuarios_inst01"]["Solicitante"],
                    prioridad_id=mundo["prioridad_id"],
                    estado_id=mundo["estados"]["Pendiente"],
                    asunto="Solicitud de producto inactivo",
                    descripcion="No debe crearse.",
                    detalles=[
                        DetalleTicketCrear(
                            producto_id=producto, cantidad_solicitada=2
                        )
                    ],
                ),
                _solicitante(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        assert db.execute(
            select(func.count()).select_from(Ticket)
        ).scalar_one() == tickets_antes
        assert db.execute(
            select(func.count()).select_from(DetalleTicket)
        ).scalar_one() == detalles_antes, "el 409 no puede dejar detalle parcial"


def test_alta_de_ticket_con_producto_de_categoria_inactiva_responde_409(motor, mundo):
    """AC-4/AC-9: la disponibilidad para el alta es el predicado conjunto."""
    categoria = crear_categoria(motor, mundo, nombre="Categoria no solicitable")
    producto = crear_producto(
        motor,
        mundo,
        nombre="Activo de categoria no solicitable",
        categoria_id=categoria,
        stock_sede=0,
    )
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            ticket_service.crear_ticket(
                db,
                TicketCrear(
                    usuario_id=mundo["usuarios_inst01"]["Solicitante"],
                    prioridad_id=mundo["prioridad_id"],
                    estado_id=mundo["estados"]["Pendiente"],
                    asunto="Solicitud de categoria inactiva",
                    descripcion="No debe crearse.",
                    detalles=[
                        DetalleTicketCrear(
                            producto_id=producto, cantidad_solicitada=1
                        )
                    ],
                ),
                _solicitante(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()


def test_edicion_pendiente_conserva_inactivo_existente_y_cambia_cantidad(motor, mundo):
    """AC-9: el item inactivo ya presente se conserva con su nueva cantidad."""
    producto = crear_producto(
        motor, mundo, nombre="Item retenido servicio", stock_sede=0
    )
    ticket_id = sembrar_ticket(motor, mundo, producto_id=producto, cantidad=3)
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        ticket_service.editar_ticket(
            db,
            ticket_id,
            TicketEditar(
                asunto="Edicion con item inactivo existente",
                descripcion="Se conserva el producto y se cambia la cantidad.",
                prioridad_id=mundo["prioridad_id"],
                detalles=[
                    DetalleTicketCrear(
                        producto_id=producto, cantidad_solicitada=5
                    )
                ],
            ),
            _solicitante(mundo),
        )

    with sesion(motor) as db:
        detalles = db.execute(
            select(DetalleTicket).where(DetalleTicket.ticket_id == ticket_id)
        ).scalars().all()
    assert [
        (fila.producto_id, fila.cantidad_solicitada) for fila in detalles
    ] == [(producto, 5)]


def test_edicion_pendiente_rechaza_inactivo_no_presente_sin_reemplazar(motor, mundo):
    """AC-9: un producto inactivo ajeno al ticket se rechaza con 409 sin cambios."""
    producto = crear_producto(
        motor, mundo, nombre="No presente servicio", stock_sede=0
    )
    ticket_id = sembrar_ticket(
        motor, mundo, producto_id=mundo["producto_id"], cantidad=3
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            ticket_service.editar_ticket(
                db,
                ticket_id,
                TicketEditar(
                    asunto="Intento de agregar un producto inactivo",
                    descripcion="No debe pasar.",
                    prioridad_id=mundo["prioridad_id"],
                    detalles=[
                        DetalleTicketCrear(
                            producto_id=producto, cantidad_solicitada=1
                        )
                    ],
                ),
                _solicitante(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        detalles = db.execute(
            select(DetalleTicket).where(DetalleTicket.ticket_id == ticket_id)
        ).scalars().all()
    assert [
        (fila.producto_id, fila.cantidad_solicitada) for fila in detalles
    ] == [(mundo["producto_id"], 3)], (
        "el 409 no puede reemplazar el conjunto de detalles"
    )


def test_edicion_pendiente_valida_el_conjunto_completo_antes_de_escribir(motor, mundo):
    """AC-9: si una linea es valida y otra inactiva-no-presente, no hay escritura."""
    producto = crear_producto(
        motor, mundo, nombre="Linea invalida servicio", stock_sede=0
    )
    ticket_id = sembrar_ticket(
        motor, mundo, producto_id=mundo["producto_id"], cantidad=3
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            ticket_service.editar_ticket(
                db,
                ticket_id,
                TicketEditar(
                    asunto="Conjunto con una linea invalida",
                    descripcion="Nada debe reemplazarse.",
                    prioridad_id=mundo["prioridad_id"],
                    detalles=[
                        DetalleTicketCrear(
                            producto_id=mundo["producto_id"],
                            cantidad_solicitada=7,
                        ),
                        DetalleTicketCrear(
                            producto_id=producto, cantidad_solicitada=1
                        ),
                    ],
                ),
                _solicitante(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        detalles = db.execute(
            select(DetalleTicket).where(DetalleTicket.ticket_id == ticket_id)
        ).scalars().all()
    assert [
        (fila.producto_id, fila.cantidad_solicitada) for fila in detalles
    ] == [(mundo["producto_id"], 3)]


# ---------------------------------------------------------------------------
# AC-10: dashboard
# ---------------------------------------------------------------------------


def test_dashboard_excluye_inactivos_de_alertas_y_conteo(motor, mundo):
    """AC-10: alertas y `total_alertas` omiten producto y categoria inactivos."""
    activo = crear_producto(
        motor, mundo, nombre="Critico activo servicio", stock_minimo=10, stock_sede=1
    )
    inactivo = crear_producto(
        motor, mundo, nombre="Critico inactivo servicio", stock_minimo=10, stock_sede=1
    )
    categoria = crear_categoria(motor, mundo, nombre="Critica retirada servicio")
    de_categoria = crear_producto(
        motor,
        mundo,
        nombre="Critico de categoria retirada servicio",
        categoria_id=categoria,
        stock_minimo=10,
        stock_sede=1,
    )
    marcar_producto(motor, inactivo, False)
    marcar_producto(motor, de_categoria, False)
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        dashboard = dashboard_service.obtener_dashboard_analitico(db, _admin(mundo))

    ids = _ids(dashboard.alertas, "producto_id")
    assert activo in ids
    assert inactivo not in ids
    assert de_categoria not in ids
    assert dashboard.kpi.total_alertas == len(dashboard.alertas)


def test_dashboard_conserva_los_demas_kpi(motor, mundo):
    """AC-10: el filtro de alertas no altera unidades, tickets ni departamentos."""
    crear_producto(
        motor, mundo, nombre="KPI critico inactivo", stock_minimo=10, stock_sede=1
    )
    with sesion(motor) as db:
        antes = dashboard_service.obtener_dashboard_analitico(db, _admin(mundo))

    inactivo = crear_producto(
        motor, mundo, nombre="KPI retirado", stock_minimo=10, stock_sede=3
    )
    marcar_producto(motor, inactivo, False)

    with sesion(motor) as db:
        despues = dashboard_service.obtener_dashboard_analitico(db, _admin(mundo))

    assert despues.kpi.unidades_en_stock == antes.kpi.unidades_en_stock + 3
    assert despues.kpi.tickets_activos == antes.kpi.tickets_activos
    assert despues.kpi.total_departamentos == antes.kpi.total_departamentos
    assert despues.kpi.total_alertas == antes.kpi.total_alertas
