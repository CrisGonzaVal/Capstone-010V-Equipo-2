"""T7 (Feature 008): aislamiento institucional de tickets, catalogos y despacho.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), con dos
instituciones plenamente sembradas (INST01 propia, INST02 ajena) y catalogos
homonimos independientes. Se comprueba:

  * `GET /tickets/catalogos` (AC-6): los productos y su `stock_total` son
    institucionales; el homonimo de otra institucion no aparece ni influye.
  * `POST /tickets/` (AC-11): un solicitante ajeno o un producto ajeno se
    ocultan con **404**, sin dejar ticket ni detalle parciales; el Solicitante
    conserva la autoatribucion de 007 y el ticket/detalle se poblan con la
    institucion efectiva.
  * `PATCH /tickets/{ticket_id}/estado` y despacho (AC-7/AC-9): un ticket ajeno
    responde 404 sin mutar.
  * Despacho (AC-12): producto o inventario de institucion cruzada, falta de
    stock o fallo de commit no dejan stock, entrega, estado ni auditoria
    parciales; el caso valido actualiza las cuatro capas en una transaccion.

La institucion del ticket se ancla a la de su solicitante (`usuario ->
departamento -> institucion`); los detalles deben referenciar producto de esa
misma institucion. Los campos `institucion_id` no viajan en `TicketRespuesta`,
asi que su poblamiento se observa sobre la fila persistida con el motor de la
fixture, como en el resto de la suite cuando el contrato no lo expone.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Institucion,
    Inventario,
    MovimientoInventario,
    Producto,
    Rol,
    Ticket,
    Usuario,
)
from app.services.auth_service import IdentidadAutenticada

RUTA_TICKETS = "/api/v1/tickets/"
RUTA_CATALOGOS = "/api/v1/tickets/catalogos"
RUTA_STOCK = "/api/v1/inventario/stock"


# ---------------------------------------------------------------------------
# Sembrado: INST01 (datos_base) + INST02 completa, con homonimos y cruces
# ---------------------------------------------------------------------------


@pytest.fixture
def particion(motor, datos_base):
    """Dos instituciones con catalogo/stock homonimo y casos de cruce.

    INST01 (propia): `datos_base` + el solicitante persistido "Sofi" + un
    producto homonimo con stock 40.

    INST02 (ajena): institucion, departamento "Bodega Sur", usuario "Beto",
    categoria/producto propios y un producto homonimo (mismo nombre que el de
    INST01) con stock 7.

    Se anaden ademas dos casos de cruce para el despacho: un detalle cuyo
    producto es de INST02 y un producto de INST01 cuya unica existencia vive en
    un departamento de INST02 (inventario con `institucion_id` NULL para que la
    FK compuesta no lo bloquee; `institucion_de_inventario` lo detecta por el
    departamento).
    """
    db = sessionmaker(bind=motor)()
    try:
        # Las dos filas de cruce deliberadas (`inventario_cruzado` y el detalle del
        # `ticket_cruce_producto`) son estados que la Feature 008 ya declara
        # imposibles por las claves compuestas; se siembran con las FK
        # desactivadas para poder ejercer la defensa en profundidad del servicio
        # (AC-12), igual que el detalle huerfano inyectado en
        # `test_despacho_transaccional.py`. Se restauran antes de ceder el motor a
        # los tests.
        with motor.connect() as conexion:
            conexion.exec_driver_sql("PRAGMA foreign_keys=OFF")

        db.query(EstadoTicket).delete()
        db.flush()
        estados: dict[str, int] = {}
        for nombre in ("Pendiente", "EnRevision", "EnCurso", "Cerrado"):
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            estados[nombre] = estado.estado_id

        # Solicitante propio (INST01), persistido para la autoatribucion.
        solicitante = Usuario(
            nombre="Sofi",
            apellido="Solicitante",
            correo="sofi.particion@compustock.cl",
            departamento_id=datos_base["departamento_id"],
            rol_id=datos_base["rol_id"],
        )
        db.add(solicitante)
        db.flush()

        # INST02 completa.
        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
            rut="2-9",
            direccion="Otra Calle 456",
        )
        db.add(institucion_ajena)
        db.flush()
        departamento_ajeno = Departamento(
            nombre_dep="Bodega Sur",
            descripcion="Deposito de la institucion ajena",
            institucion_id="INST02",
        )
        db.add(departamento_ajeno)
        db.flush()
        usuario_ajeno = Usuario(
            nombre="Beto",
            apellido="Ajeno",
            correo="beto.particion@compustock.cl",
            departamento_id=departamento_ajeno.departamento_id,
            rol_id=datos_base["rol_id"],
        )
        db.add(usuario_ajeno)
        db.flush()
        categoria_ajena = Categoria(
            nombre_cat="Insumos Ajenos",
            descripcion_cat="Catalogo de la institucion ajena",
            institucion_id="INST02",
        )
        db.add(categoria_ajena)
        db.flush()
        producto_ajeno = Producto(
            nombre="Insumo Compartido",
            descripcion="Homonimo de INST02",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=categoria_ajena.categoria_id,
            institucion_id="INST02",
        )
        db.add(producto_ajeno)
        db.flush()
        inventario_ajeno = Inventario(
            stock_actual=7,
            ubicacion="Bodega Sur - C1",
            departamento_id=departamento_ajeno.departamento_id,
            producto_id=producto_ajeno.producto_id,
            institucion_id="INST02",
        )
        db.add(inventario_ajeno)
        db.flush()

        # Homonimo propio (INST01) con su existencia.
        producto_propio = Producto(
            nombre="Insumo Compartido",
            descripcion="Homonimo de INST01",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id="INST01",
        )
        db.add(producto_propio)
        db.flush()
        inventario_propio = Inventario(
            stock_actual=40,
            ubicacion="Operaciones - C1",
            departamento_id=datos_base["departamento_id"],
            producto_id=producto_propio.producto_id,
            institucion_id="INST01",
        )
        db.add(inventario_propio)
        db.flush()

        # Producto INST01 cuya unica existencia vive en un departamento ajeno.
        producto_cruce_inventario = Producto(
            nombre="Producto con inventario cruzado",
            descripcion="Producto propio con existencia en un deposito ajeno",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id="INST01",
        )
        db.add(producto_cruce_inventario)
        db.flush()
        inventario_cruzado = Inventario(
            stock_actual=5,
            ubicacion="Deposito ajeno",
            departamento_id=departamento_ajeno.departamento_id,
            producto_id=producto_cruce_inventario.producto_id,
            institucion_id="INST02",
        )
        db.add(inventario_cruzado)
        db.flush()

        def nuevo_ticket(usuario_id, estado_id, asunto, producto_id, institucion_id=None):
            ticket = Ticket(
                usuario_id=usuario_id,
                prioridad_id=datos_base["prioridad_id"],
                estado_id=estado_id,
                asunto=asunto,
                institucion_id=institucion_id,
            )
            db.add(ticket)
            db.flush()
            db.add(
                DetalleTicket(
                    ticket_id=ticket.ticket_id,
                    producto_id=producto_id,
                    cantidad_solicitada=2,
                    cantidad_entregada=0,
                    institucion_id=institucion_id,
                )
            )
            return ticket.ticket_id

        ids = {
            **datos_base,
            "inst_propia": "INST01",
            "inst_ajena": "INST02",
            "solicitante_id": solicitante.usuario_id,
            "usuario_ajeno_id": usuario_ajeno.usuario_id,
            "dep_ajeno_id": departamento_ajeno.departamento_id,
            "categoria_ajena_id": categoria_ajena.categoria_id,
            "producto_ajeno_id": producto_ajeno.producto_id,
            "inventario_ajeno_id": inventario_ajeno.inventario_id,
            "producto_propio_id": producto_propio.producto_id,
            "inventario_propio_id": inventario_propio.inventario_id,
            "producto_cruce_inventario_id": producto_cruce_inventario.producto_id,
            "inventario_cruzado_id": inventario_cruzado.inventario_id,
            "estado_pendiente_id": estados["Pendiente"],
            "estado_en_revision_id": estados["EnRevision"],
            "estado_en_curso_id": estados["EnCurso"],
            "estado_cerrado_id": estados["Cerrado"],
            "ticket_ajeno_estado_id": nuevo_ticket(
                usuario_ajeno.usuario_id,
                estados["EnRevision"],
                "Ajeno EnRevision",
                producto_ajeno.producto_id,
                institucion_id="INST02",
            ),
            "ticket_cruce_producto_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["EnCurso"],
                "Cruce de producto",
                producto_ajeno.producto_id,
                institucion_id="INST01",
            ),
            "ticket_cruce_inventario_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["EnCurso"],
                "Cruce de inventario",
                producto_cruce_inventario.producto_id,
                institucion_id="INST01",
            ),
            "ticket_falta_stock_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["EnCurso"],
                "Falta de stock",
                producto_propio.producto_id,
                institucion_id="INST01",
            ),
        }
        # El ticket de falta de stock pide 100 sobre un stock de 40.
        db.query(DetalleTicket).filter(
            DetalleTicket.ticket_id == ids["ticket_falta_stock_id"]
        ).update({"cantidad_solicitada": 100})
        db.commit()
        with motor.connect() as conexion:
            conexion.exec_driver_sql("PRAGMA foreign_keys=ON")
        return ids
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers: identidad, cliente real y observadores
# ---------------------------------------------------------------------------


def _identidad(rol: str, departamento_id, usuario_id: int = 9999) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Particion",
        correo=f"sonda.particion.{rol.lower()}@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub=f"sub-particion-{rol.lower()}")


@contextmanager
def _cliente(motor, rol: str, departamento_id, usuario_id: int = 9999, *, sin_excepcion=False):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = (
        lambda: _identidad(rol, departamento_id, usuario_id)
    )
    try:
        with TestClient(app, raise_server_exceptions=not sin_excepcion) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _payload(datos: dict, usuario_id: int, producto_id: int, cantidad: int = 1) -> dict:
    return {
        "usuario_id": usuario_id,
        "prioridad_id": datos["prioridad_id"],
        "estado_id": datos["estado_pendiente_id"],
        "asunto": "Alta de ticket institucional",
        "descripcion": "Prueba de aislamiento institucional.",
        "detalles": [{"producto_id": producto_id, "cantidad_solicitada": cantidad}],
    }


def _ticket(listado, ticket_id):
    return next(t for t in listado if t["ticket_id"] == ticket_id)


def _stock(cliente, inventario_id: int) -> int:
    respuesta = cliente.get(RUTA_STOCK)
    assert respuesta.status_code == 200, respuesta.text
    return next(
        i for i in respuesta.json() if i["inventario_id"] == inventario_id
    )["stock_actual"]


def _stock_persistido(motor, inventario_id: int) -> int:
    """`stock_actual` leido de la fila: sirve para inventarios fuera del alcance del
    actor, que no aparecen en `GET /inventario/stock`."""
    db = sessionmaker(bind=motor)()
    try:
        return db.get(Inventario, inventario_id).stock_actual
    finally:
        db.close()


def _salidas_del_ticket(motor, ticket_id: int) -> list[dict]:
    db = sessionmaker(bind=motor)()
    try:
        marca = f"Despacho ticket_id={ticket_id};"
        return [
            {
                "movimiento_id": m.movimiento_id,
                "tipo_movimiento": m.tipo_movimiento,
                "cantidad": m.cantidad,
                "inventario_id": m.inventario_id,
                "observacion": m.observacion,
            }
            for m in db.query(MovimientoInventario).all()
            if (m.observacion or "").startswith(marca)
        ]
    finally:
        db.close()


def _instituciones_persistidas(motor, ticket_id: int) -> dict:
    """`institucion_id` de la cabecera y de cada detalle del ticket."""
    db = sessionmaker(bind=motor)()
    try:
        ticket = db.get(Ticket, ticket_id)
        detalles = (
            db.query(DetalleTicket)
            .filter(DetalleTicket.ticket_id == ticket_id)
            .all()
        )
        return {
            "ticket": ticket.institucion_id,
            "detalles": [d.institucion_id for d in detalles],
        }
    finally:
        db.close()


def _contar_tickets(motor) -> int:
    db = sessionmaker(bind=motor)()
    try:
        return db.query(Ticket).count()
    finally:
        db.close()


def _contar_detalles(motor) -> int:
    db = sessionmaker(bind=motor)()
    try:
        return db.query(DetalleTicket).count()
    finally:
        db.close()


def _abrir_ticket_en_curso(cliente, datos, usuario_id, producto_id, cantidad=3) -> int:
    """Alta por API en `Pendiente` y avance a `EnCurso` (dos pasos contiguos)."""
    respuesta = cliente.post(
        RUTA_TICKETS, json=_payload(datos, usuario_id, producto_id, cantidad)
    )
    assert respuesta.status_code == 201, respuesta.text
    ticket_id = respuesta.json()["ticket_id"]
    for estado_id in (datos["estado_en_revision_id"], datos["estado_en_curso_id"]):
        avance = cliente.patch(
            f"{RUTA_TICKETS}{ticket_id}/estado", json={"estado_id": estado_id}
        )
        assert avance.status_code == 200, avance.text
    return ticket_id


def _verificar_sin_efectos(cliente, motor, ticket_id, estado_esperado, stock_esperado):
    ticket = _ticket(cliente.get(RUTA_TICKETS).json(), ticket_id)
    assert ticket["estado_id"] == estado_esperado, "un rechazo no cambia el estado"
    assert ticket["fecha_cierre"] is None, "un rechazo no sella el cierre"
    assert all(
        d["cantidad_entregada"] == 0 for d in ticket["detalles"]
    ), "un rechazo no deja entregas"
    for inventario_id, esperado in stock_esperado.items():
        assert (
            _stock_persistido(motor, inventario_id) == esperado
        ), "un rechazo no rebaja stock"
    assert _salidas_del_ticket(motor, ticket_id) == [], "un rechazo no audita"


# ---------------------------------------------------------------------------
# Catalogos (AC-6)
# ---------------------------------------------------------------------------


def test_catalogos_solicitante_solo_su_institucion(motor, particion):
    with _cliente(
        motor, "Solicitante", particion["departamento_id"], particion["solicitante_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    propio = productos[particion["producto_propio_id"]]
    assert propio["stock_total"] == 40
    assert propio["institucion_id"] == "INST01"
    assert particion["producto_ajeno_id"] not in productos


def test_catalogos_bodeguero_ajeno_no_suma_stock_propio(motor, particion):
    with _cliente(motor, "Bodeguero", particion["dep_ajeno_id"]) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    ajeno = productos[particion["producto_ajeno_id"]]
    assert ajeno["stock_total"] == 7
    assert ajeno["institucion_id"] == "INST02"
    assert particion["producto_propio_id"] not in productos


def test_catalogos_superadmin_global_atribuye_institucion(motor, particion):
    with _cliente(motor, "Superadmin", None) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    assert productos[particion["producto_propio_id"]]["institucion_id"] == "INST01"
    assert productos[particion["producto_ajeno_id"]]["institucion_id"] == "INST02"


# ---------------------------------------------------------------------------
# Creacion (AC-11)
# ---------------------------------------------------------------------------


def test_crear_ticket_con_producto_ajeno_404_sin_parcial(motor, particion):
    inicio_tickets = _contar_tickets(motor)
    inicio_detalles = _contar_detalles(motor)

    with _cliente(motor, "Administrador", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS,
            json=_payload(
                particion, particion["solicitante_id"], particion["producto_ajeno_id"]
            ),
        )

    assert respuesta.status_code == 404, respuesta.text
    assert _contar_tickets(motor) == inicio_tickets
    assert _contar_detalles(motor) == inicio_detalles


def test_crear_ticket_con_solicitante_ajeno_404_sin_parcial(motor, particion):
    inicio_tickets = _contar_tickets(motor)

    with _cliente(motor, "Administrador", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS,
            json=_payload(
                particion, particion["usuario_ajeno_id"], particion["producto_propio_id"]
            ),
        )

    assert respuesta.status_code == 404, respuesta.text
    assert _contar_tickets(motor) == inicio_tickets


def test_crear_ticket_puebla_institucion_en_ticket_y_detalle(motor, particion):
    with _cliente(motor, "Administrador", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS,
            json=_payload(
                particion, particion["solicitante_id"], particion["producto_propio_id"]
            ),
        )
    assert respuesta.status_code == 201, respuesta.text

    persistido = _instituciones_persistidas(motor, respuesta.json()["ticket_id"])
    assert persistido["ticket"] == "INST01"
    assert persistido["detalles"] == ["INST01"]


def test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion(motor, particion):
    with _cliente(
        motor, "Solicitante", particion["departamento_id"], particion["solicitante_id"]
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS,
            json=_payload(
                particion, particion["usuario_ajeno_id"], particion["producto_propio_id"]
            ),
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["usuario_id"] == particion["solicitante_id"]

    persistido = _instituciones_persistidas(motor, respuesta.json()["ticket_id"])
    assert persistido["ticket"] == "INST01"


# ---------------------------------------------------------------------------
# PATCH estado (AC-7) y despacho (AC-9/AC-12)
# ---------------------------------------------------------------------------


def test_patch_ticket_ajeno_404_sin_cambiar(motor, particion):
    with _cliente(motor, "Superadmin", None) as supervisor:
        antes = _ticket(
            supervisor.get(RUTA_TICKETS).json(), particion["ticket_ajeno_estado_id"]
        )["estado_id"]

    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}{particion['ticket_ajeno_estado_id']}/estado",
            json={"estado_id": particion["estado_en_curso_id"]},
        )

    with _cliente(motor, "Superadmin", None) as supervisor:
        despues = _ticket(
            supervisor.get(RUTA_TICKETS).json(), particion["ticket_ajeno_estado_id"]
        )["estado_id"]

    assert respuesta.status_code == 404, respuesta.text
    assert despues == antes


def test_despacho_producto_cruzado_409_sin_efectos(motor, particion):
    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{particion['ticket_cruce_producto_id']}/despacho",
            json={"usuario_id": particion["usuario_id"]},
        )
        _verificar_sin_efectos(
            cliente,
            motor,
            particion["ticket_cruce_producto_id"],
            particion["estado_en_curso_id"],
            {
                particion["inventario_ajeno_id"]: 7,
                particion["inventario_propio_id"]: 40,
            },
        )

    assert respuesta.status_code == 409, respuesta.text
    assert "institucion" in respuesta.json()["detail"].lower()


def test_despacho_inventario_cruzado_409_sin_efectos(motor, particion):
    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{particion['ticket_cruce_inventario_id']}/despacho",
            json={"usuario_id": particion["usuario_id"]},
        )
        _verificar_sin_efectos(
            cliente,
            motor,
            particion["ticket_cruce_inventario_id"],
            particion["estado_en_curso_id"],
            {particion["inventario_cruzado_id"]: 5},
        )

    assert respuesta.status_code == 409, respuesta.text
    assert "institucion" in respuesta.json()["detail"].lower()


def test_despacho_falta_stock_409_sin_efectos(motor, particion):
    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{particion['ticket_falta_stock_id']}/despacho",
            json={"usuario_id": particion["usuario_id"]},
        )
        _verificar_sin_efectos(
            cliente,
            motor,
            particion["ticket_falta_stock_id"],
            particion["estado_en_curso_id"],
            {particion["inventario_propio_id"]: 40},
        )

    assert respuesta.status_code == 409, respuesta.text


def test_despacho_valido_actualiza_stock_entrega_estado_y_auditoria(motor, particion):
    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        stock_inicial = _stock(cliente, particion["inventario_propio_id"])
        ticket_id = _abrir_ticket_en_curso(
            cliente,
            particion,
            particion["solicitante_id"],
            particion["producto_propio_id"],
            cantidad=3,
        )
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{ticket_id}/despacho",
            json={"usuario_id": particion["usuario_id"]},
        )

        assert respuesta.status_code == 200, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["estado_id"] == particion["estado_cerrado_id"]
        assert [d["cantidad_entregada"] for d in cuerpo["detalles"]] == [3]
        assert _stock(cliente, particion["inventario_propio_id"]) == stock_inicial - 3

        salidas = _salidas_del_ticket(motor, ticket_id)
        assert len(salidas) == 1
        assert salidas[0]["tipo_movimiento"] == "SALIDA"
        assert salidas[0]["cantidad"] == 3
        assert salidas[0]["inventario_id"] == particion["inventario_propio_id"]


def test_despacho_revierte_todo_si_el_commit_falla(motor, particion):
    """AC-12: un fallo del `commit` revierte las cuatro capas que toca el despacho.

    Se inyecta el fallo en `Session.commit` cuando el servicio ya muto inventario,
    detalles, ticket y movimientos; se observa la respuesta 500 y que ninguna
    capa quede a medias. Se usa un cliente sin relanzar excepciones.
    """
    from sqlalchemy.orm import Session

    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente_previo:
        stock_inicial = _stock(cliente_previo, particion["inventario_propio_id"])
        ticket_id = _abrir_ticket_en_curso(
            cliente_previo,
            particion,
            particion["solicitante_id"],
            particion["producto_propio_id"],
            cantidad=3,
        )

    def commit_que_falla(self):
        raise RuntimeError("fallo de commit inyectado en el despacho")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Session, "commit", commit_que_falla)
    try:
        with _cliente(
            motor, "Bodeguero", particion["departamento_id"], sin_excepcion=True
        ) as cliente:
            respuesta = cliente.post(
                f"{RUTA_TICKETS}{ticket_id}/despacho",
                json={"usuario_id": particion["usuario_id"]},
            )
            assert respuesta.status_code == 500, respuesta.text
    finally:
        monkeypatch.undo()

    with _cliente(motor, "Bodeguero", particion["departamento_id"]) as cliente:
        _verificar_sin_efectos(
            cliente,
            motor,
            ticket_id,
            particion["estado_en_curso_id"],
            {particion["inventario_propio_id"]: stock_inicial},
        )
