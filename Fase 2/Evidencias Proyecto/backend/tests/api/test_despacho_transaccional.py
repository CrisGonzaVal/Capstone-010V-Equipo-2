"""Feature 005 (T2): despacho exitoso y stock agregado por producto (AC-1..AC-3, AC-13).

El seam principal bajo prueba es la **interfaz HTTP** (`TestClient`), como en el
resto de la suite: el ticket (estado, `fecha_cierre`, cantidades entregadas) y el
stock se observan releyendo la API (`GET /tickets/`, `GET /inventario/existencias`).

Las salidas de auditoría se leen de la base con el motor de la fixture `motor`
por una razón de alcance, no de comodidad: el endpoint de historial
(`GET /inventario/movimientos`) pertenece a T9 y todavía no existe en T2, así que
el único modo de observar el movimiento `SALIDA` es la fila persistida. Cuando el
historial exista, su lectura por HTTP toma el relevo.

Fase ROJA de TDD: aquí todavía no existen ni la ruta de despacho (T5) ni el
servicio (T3), de modo que cada prueba debe fallar por la ruta ausente (el POST
responde 404), nunca por imports, fixtures o sintaxis.

El catálogo se instala con los nombres canónicos del flujo
`Pendiente → EnRevision → EnCurso → Cerrado`, imitando las fixtures de
`test_tablero_kanban.py`; no se codifican ids de catálogo.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import (
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Inventario,
    MovimientoInventario,
    Producto,
    Sede,
    StockSede,
)

from ._soporte_sede_011 import asegurar_sede_de_departamento

#: Sede del departamento de `datos_base`, fijada por el fixture autouse. Los tests
#: observan el saldo por sede a traves de `leer_stock`, que necesita saber cual es
#: (Feature 011: el saldo vigente vive en `stock_sede`, no en el inventario legado).
_SEDE_BASE_ID: int | None = None

#: Motor de la fixture, fijado por el fixture autouse. Sin el no se puede
#: resolver por ORM el producto de una fila de inventario legado, porque desde la
#: Feature 011 (B1) `GET /inventario/stock` ya no expone el inventario
#: departamental.
_MOTOR = None


@pytest.fixture(autouse=True)
def _sede_de_datos_base(motor, datos_base):
    """Feature 011 (T9): toda alta/despacho exige la sede del departamento.

    Se siembra una sede de INST01 para el departamento de `datos_base` con stock
    para su producto. `datos_despacho` anade despues el stock del producto escaso.
    """
    global _SEDE_BASE_ID, _MOTOR
    _MOTOR = motor
    _SEDE_BASE_ID = asegurar_sede_de_departamento(
        motor, datos_base, stocks={datos_base["producto_id"]: 50}
    )["sede_id"]


def _instalar_catalogo(motor, nombres):
    """Borra los estados existentes y crea `nombres` en ese orden de ids.

    Devuelve `{nombre: id}`. El orden de inserción es el del flujo
    (`estado_id` ascendente), que es como lo consumen las reglas de la 004/005.
    """
    db = sessionmaker(bind=motor)()
    try:
        db.query(EstadoTicket).delete()
        db.flush()
        ids = {}
        for nombre in nombres:
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            ids[nombre] = estado.estado_id
        db.commit()
        return ids
    finally:
        db.close()


def _instalar_catalogo_lista(motor, nombres):
    """Como `_instalar_catalogo` pero conserva ids repetidos en una lista.

    Un `dict` colapsaría un nombre duplicado a su última aparición, y los casos
    de AC-8 (menor `estado_id` gana) necesitan distinguir la primera de la
    segunda. La lista mantiene el orden de inserción, que es el del `estado_id`.
    """
    db = sessionmaker(bind=motor)()
    try:
        db.query(EstadoTicket).delete()
        db.flush()
        ids = []
        for nombre in nombres:
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            ids.append(estado.estado_id)
        db.commit()
        return ids
    finally:
        db.close()


def _quitar_estados_base(datos_base):
    """Copia de `datos_base` sin los ids de los estados que las fixtures borran."""
    datos = {**datos_base}
    datos.pop("estado_ingresado_id", None)
    datos.pop("estado_cerrado_id", None)
    return datos


@pytest.fixture
def datos_despacho(motor, datos_base):
    """Catálogo canónico del flujo más un segundo producto de stock escaso.

    Reutiliza el producto e inventario de `datos_base` (stock holgado, 50) para
    el despacho simple y las líneas repetidas del mismo producto, y agrega un
    producto de stock 4 para poder distinguir el éxito del agregado insuficiente
    (dos líneas de 3 sobre un stock total de 4).
    """
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado"))

    db = sessionmaker(bind=motor)()
    try:
        producto_escaso = Producto(
            nombre="Cinta escasa",
            descripcion="Producto con stock insuficiente para las pruebas",
            unidad_medida="ROLLO",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id=datos_base["institucion_id"],
        )
        db.add(producto_escaso)
        db.flush()

        inventario_escaso = Inventario(
            stock_actual=4,
            ubicacion="Bodega escasa",
            departamento_id=datos_base["departamento_id"],
            producto_id=producto_escaso.producto_id,
            institucion_id=datos_base["institucion_id"],
        )
        db.add(inventario_escaso)
        db.flush()

        # Feature 011 (T9): el saldo vigente del producto escaso vive en la sede
        # del departamento (el inventario legado de arriba solo da el id/mapa).
        db.add(
            StockSede(
                sede_id=_SEDE_BASE_ID,
                producto_id=producto_escaso.producto_id,
                stock_actual=4,
                institucion_id=datos_base["institucion_id"],
            )
        )
        db.commit()

        datos = {**datos_base}
        datos.pop("estado_ingresado_id", None)
        datos.pop("estado_cerrado_id", None)
        datos.update(
            {
                "estado_pendiente_id": ids["Pendiente"],
                "estado_en_revision_id": ids["EnRevision"],
                "estado_en_curso_id": ids["EnCurso"],
                "estado_cerrado_id": ids["Cerrado"],
                "producto_escaso_id": producto_escaso.producto_id,
                "inventario_escaso_id": inventario_escaso.inventario_id,
            }
        )
        return datos
    finally:
        db.close()


@pytest.fixture
def datos_sin_en_curso(motor, datos_base):
    """Catalogo sin el nombre `EnCurso`: el despacho no puede resolverlo (AC-8)."""
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "Cerrado"))
    datos = _quitar_estados_base(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_cerrado_id": ids["Cerrado"],
        }
    )
    return datos


@pytest.fixture
def datos_sin_cerrado(motor, datos_base):
    """Catalogo sin el nombre `Cerrado`: no hay destino de cierre (AC-8)."""
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "EnCurso"))
    datos = _quitar_estados_base(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["EnCurso"],
        }
    )
    return datos


@pytest.fixture
def datos_en_curso_duplicado(motor, datos_base):
    """Dos `EnCurso`: el elegible es el de menor `estado_id` (AC-8).

    La lista conserva ambos ids; el dict habría colapsado el nombre.
    """
    ids = _instalar_catalogo_lista(
        motor, ("Pendiente", "EnRevision", "EnCurso", "EnCurso", "Cerrado")
    )
    datos = _quitar_estados_base(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids[0],
            "estado_en_revision_id": ids[1],
            "estado_en_curso_id": ids[2],  # el de menor id: el canonico
            "estado_en_curso_duplicado_id": ids[3],
            "estado_cerrado_id": ids[4],
        }
    )
    return datos


@pytest.fixture
def datos_cerrado_duplicado(motor, datos_base):
    """Dos `Cerrado`: el destino canónico es el de menor `estado_id` (AC-8)."""
    ids = _instalar_catalogo_lista(
        motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado", "Cerrado")
    )
    datos = _quitar_estados_base(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids[0],
            "estado_en_revision_id": ids[1],
            "estado_en_curso_id": ids[2],
            "estado_cerrado_id": ids[3],  # el de menor id: el canonico
            "estado_cerrado_duplicado_id": ids[4],
        }
    )
    return datos


@pytest.fixture
def datos_minusculas(motor, datos_base):
    """Nombres canónicos en minúsculas: la resolución no distingue mayúsculas (AC-8)."""
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "encurso", "cerrado"))
    datos = _quitar_estados_base(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["encurso"],
            "estado_cerrado_id": ids["cerrado"],
        }
    )
    return datos


@pytest.fixture
def datos_inventario_invalido(motor, datos_base):
    """Catalogo canónico + dos productos sin saldo en la sede del ticket.

    Feature 011 (T9): el despacho lee solo `stock_sede` de la sede almacenada. Los
    casos de "inventario ausente/ambiguo" pasan a ser "sin saldo en la sede":
    `producto_sin_inventario_id` no tiene ninguna fila de `stock_sede`;
    `producto_dos_filas_id` solo tiene saldo en **otra** sede (la del segundo
    departamento), de modo que el despacho no lo usa y responde 409.
    """
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado"))

    db = sessionmaker(bind=motor)()
    try:
        primer_departamento = db.get(Departamento, datos_base["departamento_id"])
        segundo_departamento = Departamento(
            nombre_dep="Logistica",
            descripcion="Segundo deposito para el caso de saldo en otra sede",
            institucion_id=primer_departamento.institucion_id,
        )
        db.add(segundo_departamento)
        db.flush()

        sede_alterna = Sede(
            nombre="Sede Logistica", institucion_id=datos_base["institucion_id"]
        )
        db.add(sede_alterna)
        db.flush()
        segundo_departamento.sede_id = sede_alterna.sede_id

        sin_inventario = Producto(
            nombre="Producto sin inventario",
            descripcion="No tiene ninguna fila de stock_sede",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id=datos_base["institucion_id"],
        )
        dos_filas = Producto(
            nombre="Producto en dos depositos",
            descripcion="Solo tiene saldo en una sede distinta a la del ticket",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id=datos_base["institucion_id"],
        )
        db.add_all([sin_inventario, dos_filas])
        db.flush()

        stock_alterno = StockSede(
            sede_id=sede_alterna.sede_id,
            producto_id=dos_filas.producto_id,
            stock_actual=10,
            institucion_id=datos_base["institucion_id"],
        )
        db.add(stock_alterno)
        db.commit()

        datos = _quitar_estados_base(datos_base)
        datos.update(
            {
                "estado_pendiente_id": ids["Pendiente"],
                "estado_en_revision_id": ids["EnRevision"],
                "estado_en_curso_id": ids["EnCurso"],
                "estado_cerrado_id": ids["Cerrado"],
                "producto_sin_inventario_id": sin_inventario.producto_id,
                "producto_dos_filas_id": dos_filas.producto_id,
                "sede_alterna_id": sede_alterna.sede_id,
            }
        )
        return datos
    finally:
        db.close()


# --- Helpers de alta y avance al estado elegible ---


def abrir_ticket_en_curso(cliente, datos, detalles) -> int:
    """Da de alta un ticket en `Pendiente` y lo avanza a `EnCurso` por la API.

    Devuelve el `ticket_id`. Se avanza con el PATCH de la 004 (dos pasos
    contiguos) para llegar al único estado elegible sin sembrar la base a mano.
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos["usuario_id"],
            "prioridad_id": datos["prioridad_id"],
            "estado_id": datos["estado_pendiente_id"],
            "asunto": "Insumos para preparar y despachar",
            "descripcion": "Preparar el pedido del departamento para su entrega.",
            "detalles": detalles,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    ticket_id = respuesta.json()["ticket_id"]

    for estado_id in (datos["estado_en_revision_id"], datos["estado_en_curso_id"]):
        avance = cliente.patch(
            f"/api/v1/tickets/{ticket_id}/estado", json={"estado_id": estado_id}
        )
        assert avance.status_code == 200, avance.text

    return ticket_id


def despachar(cliente, ticket_id: int, payload):
    return cliente.post(f"/api/v1/tickets/{ticket_id}/despacho", json=payload)


def crear_ticket_en_estado(cliente, datos, estado_id: int, detalles) -> int:
    """Alta por API en un estado arbitrario; devuelve el `ticket_id`.

    Sirve para los casos que no parten de `EnCurso` (estado no elegible,
    catalogos degenerados) sin sembrar la tabla a mano.
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos["usuario_id"],
            "prioridad_id": datos["prioridad_id"],
            "estado_id": estado_id,
            "asunto": "Insumos para preparar y despachar",
            "descripcion": "Preparar el pedido del departamento para su entrega.",
            "detalles": detalles,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["ticket_id"]


# --- Observadores (HTTP y persistido) ---


def leer_ticket(cliente, ticket_id: int) -> dict:
    """Relee el ticket como lo ve un cliente: por `GET /tickets/`."""
    respuesta = cliente.get("/api/v1/tickets/")
    assert respuesta.status_code == 200, respuesta.text
    return next(t for t in respuesta.json() if t["ticket_id"] == ticket_id)


def leer_stock(cliente, inventario_id: int) -> int:
    """Saldo por sede del producto de una fila de inventario legado.

    Feature 011 (T9/B1): el despacho ya no rebaja el inventario departamental sino
    `stock_sede`. La fila legada se usa solo para localizar su producto (por ORM:
    `GET /inventario/stock` dejo de exponer el inventario departamental), y el
    saldo se lee en la sede del departamento (la unica que el despacho toca en
    esta suite). Asi los casos previos siguen midiendo el efecto real del despacho.
    """
    with sessionmaker(bind=_MOTOR)() as db:
        producto_id = db.get(Inventario, inventario_id).producto_id

    existencias = cliente.get("/api/v1/inventario/existencias")
    assert existencias.status_code == 200, existencias.text
    producto = next(
        e for e in existencias.json() if e["producto_id"] == producto_id
    )
    return next(
        s["stock_actual"]
        for s in producto["sedes"]
        if s["sede_id"] == _SEDE_BASE_ID
    )


def salidas_persistidas(motor) -> list[dict]:
    """Filas de `movimiento_inventario` como dicts, para observarlas por DB.

    No hay endpoint de historial en T2 (llega en T9), así que la auditoría de la
    salida se comprueba sobre la fila persistida. Se copian los campos dentro de
    la sesión para no depender de instancias ORM ya desligadas.
    """
    db = sessionmaker(bind=motor)()
    try:
        registros = (
            db.query(MovimientoInventario)
            .order_by(MovimientoInventario.movimiento_id)
            .all()
        )
        return [
            {
                "movimiento_id": m.movimiento_id,
                "tipo_movimiento": m.tipo_movimiento,
                "cantidad": m.cantidad,
                "observacion": m.observacion,
                "inventario_id": m.inventario_id,
            }
            for m in registros
        ]
    finally:
        db.close()


def salidas_del_ticket(motor, ticket_id: int) -> list[dict]:
    """Salidas correlacionadas con un ticket por su observación D-6."""
    marca = f"Despacho ticket_id={ticket_id};"
    return [
        m
        for m in salidas_persistidas(motor)
        if (m["observacion"] or "").startswith(marca)
    ]


def verificar_sin_efectos(
    cliente, motor, ticket_id: int, estado_esperado_id: int, inventarios: dict
):
    """Un rechazo de negocio no puede dejar rastro en ninguna de las cuatro capas.

    Observa, en este orden, el ticket (estado y `fecha_cierre`), sus detalles
    (`cantidad_entregada` en 0), el inventario que se habría rebajado y la
    auditoría (cero movimientos del ticket). `inventarios` mapea
    `inventario_id` → stock que debe permanecer intacto.
    """
    ticket = leer_ticket(cliente, ticket_id)
    assert (
        ticket["estado_id"] == estado_esperado_id
    ), "un rechazo no puede cambiar el estado del ticket"
    assert ticket["fecha_cierre"] is None, "un rechazo no puede sellar el cierre"
    assert all(
        detalle["cantidad_entregada"] == 0 for detalle in ticket["detalles"]
    ), "un rechazo no puede dejar entregas, ni parciales"
    for inventario_id, stock_esperado in inventarios.items():
        assert (
            leer_stock(cliente, inventario_id) == stock_esperado
        ), f"un rechazo no puede rebajar el inventario {inventario_id}"
    assert (
        salidas_del_ticket(motor, ticket_id) == []
    ), "un rechazo no puede crear movimientos de auditoría"


# --- AC-1: despacho exitoso cierra el ticket ---


def test_despacho_cierra_el_ticket_con_fecha_y_entregas_completas(
    cliente, datos_despacho
):
    """AC-1: 200, estado `Cerrado`, `fecha_cierre` no nula y entrega completa."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado_id"] == datos_despacho["estado_cerrado_id"]
    assert cuerpo["fecha_cierre"] is not None
    assert [d["cantidad_entregada"] for d in cuerpo["detalles"]] == [3]
    assert [
        d["cantidad_solicitada"] for d in cuerpo["detalles"]
    ] == [3], "la entrega es completa, no parcial (D-2)"

    persistido = leer_ticket(cliente, ticket_id)
    assert persistido["estado_id"] == datos_despacho["estado_cerrado_id"]
    assert persistido["fecha_cierre"] is not None


# --- AC-2: rebaja exacta y salida auditada ---


def test_despacho_rebaja_el_stock_del_inventario_unico(cliente, datos_despacho):
    """AC-2: el inventario único del producto baja exactamente lo solicitado."""
    stock_inicial = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 200, respuesta.text
    assert leer_stock(cliente, datos_despacho["inventario_id"]) == stock_inicial - 3


def test_despacho_registra_una_salida_con_observacion_literal(
    cliente, motor, datos_despacho
):
    """AC-2/D-6: una salida `SALIDA` por el inventario correcto y observación exacta."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 200, respuesta.text
    detalle = respuesta.json()["detalles"][0]
    observacion_esperada = (
        f"Despacho ticket_id={ticket_id}; "
        f"detalle_id={detalle['detalle_ticket_id']}; "
        f"producto_id={datos_despacho['producto_id']}"
    )

    salidas = salidas_del_ticket(motor, ticket_id)
    assert len(salidas) == 1, f"se esperaba una sola salida para el ticket: {salidas}"
    salida = salidas[0]
    assert salida["tipo_movimiento"] == "SALIDA"
    assert salida["cantidad"] == 3
    assert salida["inventario_id"] is None, (
        "Feature 011: el movimiento nuevo se enlaza por stock_sede_id"
    )
    assert salida["observacion"] == observacion_esperada


# --- AC-3: varias líneas del mismo producto ---


def test_despacho_de_dos_lineas_del_mismo_producto_suma_stock_y_deja_una_por_linea(
    cliente, motor, datos_despacho
):
    """AC-3: dos líneas del mismo producto, un movimiento por línea y suma total."""
    stock_inicial = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [
            {"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3},
            {"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 4},
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 200, respuesta.text
    detalles = sorted(
        respuesta.json()["detalles"], key=lambda d: d["detalle_ticket_id"]
    )
    assert [d["cantidad_entregada"] for d in detalles] == [3, 4]
    assert leer_stock(cliente, datos_despacho["inventario_id"]) == stock_inicial - 7

    salidas = salidas_del_ticket(motor, ticket_id)
    assert len(salidas) == 2, "cada línea conserva su propio movimiento (D-7)"
    assert sorted(m["cantidad"] for m in salidas) == [3, 4]
    assert {m["inventario_id"] for m in salidas} == {None}, (
        "Feature 011: los movimientos nuevos dejan inventario_id nulo"
    )
    assert {m["tipo_movimiento"] for m in salidas} == {"SALIDA"}

    persistido = leer_ticket(cliente, ticket_id)
    assert persistido["estado_id"] == datos_despacho["estado_cerrado_id"]
    assert persistido["fecha_cierre"] is not None
    assert sorted(
        d["cantidad_entregada"] for d in persistido["detalles"]
    ) == [3, 4], "las dos líneas quedan entregadas por separado y de forma persistida"


def test_despacho_rechaza_el_agregado_insuficiente_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-3: dos líneas del mismo producto suman 6 > stock 4 → 409 sin escrituras.

    Es el caso de insuficiencia agregada; su cobertura de rechazos se consolida
    en T4, pero aquí separa el éxito del exceso de stock con la misma forma de
    datos (mismo producto en dos líneas).
    """
    stock_inicial = leer_stock(cliente, datos_despacho["inventario_escaso_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [
            {"producto_id": datos_despacho["producto_escaso_id"], "cantidad_solicitada": 3},
            {"producto_id": datos_despacho["producto_escaso_id"], "cantidad_solicitada": 3},
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    assert leer_stock(cliente, datos_despacho["inventario_escaso_id"]) == stock_inicial
    assert (
        leer_ticket(cliente, ticket_id)["estado_id"]
        == datos_despacho["estado_en_curso_id"]
    ), "un rechazo por stock no puede cambiar el estado"
    assert salidas_del_ticket(motor, ticket_id) == []


# --- AC-13/§5: payload inválido ---


def test_despacho_sin_payload_responde_422(cliente, datos_despacho):
    """§5: el payload con `usuario_id` es obligatorio."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = cliente.post(f"/api/v1/tickets/{ticket_id}/despacho")

    assert respuesta.status_code == 422, respuesta.text


def test_despacho_con_usuario_id_no_entero_responde_422(cliente, datos_despacho):
    """§5: `usuario_id` no entero es un error de forma, no de referencia."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(cliente, ticket_id, {"usuario_id": "no-es-entero"})

    assert respuesta.status_code == 422, respuesta.text


# ==========================================================================
# T4 — Rechazos y casos límite (AC-4..AC-14)
#
# Cada caso verifica el status contractual y, además, el estado final de las
# cuatro capas que el despacho toca: ticket, detalles, inventario y auditoría.
# ==========================================================================


# --- AC-4: stock insuficiente cancela todo el despacho ---


def test_despacho_rechaza_stock_insuficiente_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-4: una línea por encima del stock → 409 y ninguna capa cambia.

    El producto escaso tiene 4 unidades y se piden 5; se comparan los dos
    inventarios (el escaso y el holgado) para descartar efectos colaterales.
    """
    stock_escaso = leer_stock(cliente, datos_despacho["inventario_escaso_id"])
    stock_holgado = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [
            {
                "producto_id": datos_despacho["producto_escaso_id"],
                "cantidad_solicitada": 5,
            }
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    assert "stock" in respuesta.json()["detail"].lower()
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {
            datos_despacho["inventario_escaso_id"]: stock_escaso,
            datos_despacho["inventario_id"]: stock_holgado,
        },
    )


def test_despacho_no_deja_efectos_parciales_si_un_producto_anterior_si_tenia_stock(
    cliente, motor, datos_despacho
):
    """AC-4: con una línea suficiente ANTES de otra insuficiente no hay efectos.

    Es el caso que distingue "validar todo antes de escribir" (D-3) de un
    descuento línea a línea: la primera línea tiene stock de sobra y aun así no
    puede quedar rebajada cuando la segunda no alcanza.
    """
    stock_holgado = leer_stock(cliente, datos_despacho["inventario_id"])
    stock_escaso = leer_stock(cliente, datos_despacho["inventario_escaso_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [
            {"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3},
            {
                "producto_id": datos_despacho["producto_escaso_id"],
                "cantidad_solicitada": 5,
            },
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {
            datos_despacho["inventario_id"]: stock_holgado,
            datos_despacho["inventario_escaso_id"]: stock_escaso,
        },
    )
    entregas = {
        detalle["producto_id"]: detalle["cantidad_entregada"]
        for detalle in leer_ticket(cliente, ticket_id)["detalles"]
    }
    assert entregas[datos_despacho["producto_id"]] == 0, (
        "la línea con stock suficiente tampoco puede quedar entregada cuando "
        "otra línea del mismo despacho falla (D-3)"
    )


# --- AC-5: ticket inexistente ---


def test_despacho_de_ticket_inexistente_responde_404_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-5: un ticket que no existe → 404 y ningún movimiento en toda la tabla."""
    respuesta = despachar(
        cliente, 999999, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 404, respuesta.text
    assert "ticket" in respuesta.json()["detail"].lower()
    assert salidas_persistidas(motor) == [], "un 404 no puede escribir auditoría"


# --- AC-6: actor inexistente ---


def test_despacho_con_usuario_inexistente_responde_404_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-6: el `usuario_id` debe existir → 404, sin tocar el ticket ni el stock."""
    stock = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(cliente, ticket_id, {"usuario_id": 999999})

    assert respuesta.status_code == 404, respuesta.text
    assert "usuario" in respuesta.json()["detail"].lower()
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {datos_despacho["inventario_id"]: stock},
    )


# --- AC-7: estado no elegible / ya despachado ---


def test_despacho_rechaza_estado_no_elegible_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-7: un ticket que no está en `EnCurso` → 409 sin efectos."""
    stock = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = crear_ticket_en_estado(
        cliente,
        datos_despacho,
        datos_despacho["estado_pendiente_id"],
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_pendiente_id"],
        {datos_despacho["inventario_id"]: stock},
    )


def test_redespachar_un_ticket_cerrado_responde_409_sin_duplicar(
    cliente, motor, datos_despacho
):
    """AC-7: un segundo despacho del mismo ticket → 409 y un único juego de salidas."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )
    primera = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )
    assert primera.status_code == 200, primera.text
    stock_tras_primera = leer_stock(cliente, datos_despacho["inventario_id"])
    salidas_tras_primera = salidas_del_ticket(motor, ticket_id)
    assert len(salidas_tras_primera) == 1

    segunda = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert segunda.status_code == 409, segunda.text
    integro = leer_ticket(cliente, ticket_id)
    assert integro["estado_id"] == datos_despacho["estado_cerrado_id"]
    assert integro["fecha_cierre"] is not None
    assert all(
        detalle["cantidad_entregada"] == 3 for detalle in integro["detalles"]
    ), "el reintento no puede alterar la entrega ya registrada"
    assert leer_stock(cliente, datos_despacho["inventario_id"]) == stock_tras_primera
    assert (
        salidas_del_ticket(motor, ticket_id) == salidas_tras_primera
    ), "un reenvío no puede duplicar los movimientos del despacho"


# --- AC-8: resolución de estados por nombre ---


def test_despacho_sin_en_curso_en_el_catalogo_responde_409_sin_efectos(
    cliente, motor, datos_sin_en_curso
):
    """AC-8: sin el nombre `EnCurso` no hay estado elegible → 409 sin escribir."""
    stock = leer_stock(cliente, datos_sin_en_curso["inventario_id"])
    ticket_id = crear_ticket_en_estado(
        cliente,
        datos_sin_en_curso,
        datos_sin_en_curso["estado_pendiente_id"],
        [{"producto_id": datos_sin_en_curso["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_sin_en_curso["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_sin_en_curso["estado_pendiente_id"],
        {datos_sin_en_curso["inventario_id"]: stock},
    )


def test_despacho_sin_cerrado_en_el_catalogo_responde_409_sin_efectos(
    cliente, motor, datos_sin_cerrado
):
    """AC-8: sin el nombre `Cerrado` no hay destino de cierre → 409 sin escribir."""
    stock = leer_stock(cliente, datos_sin_cerrado["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_sin_cerrado,
        [{"producto_id": datos_sin_cerrado["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_sin_cerrado["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_sin_cerrado["estado_en_curso_id"],
        {datos_sin_cerrado["inventario_id"]: stock},
    )


def test_despacho_con_en_curso_duplicado_usa_el_de_menor_id(
    cliente, datos_en_curso_duplicado
):
    """AC-8: con dos `EnCurso`, el elegible es el de menor `estado_id`.

    El ticket avanza al `EnCurso` de menor id (el canónico). Si el servicio
    hubiera tomado el duplicado de id mayor, el ticket no estaría en él y la
    respuesta sería 409; el 200 prueba funcionalmente la regla del menor id.
    """
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_en_curso_duplicado,
        [
            {
                "producto_id": datos_en_curso_duplicado["producto_id"],
                "cantidad_solicitada": 3,
            }
        ],
    )

    respuesta = despachar(
        cliente,
        ticket_id,
        {"usuario_id": datos_en_curso_duplicado["usuario_id"]},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == datos_en_curso_duplicado["estado_cerrado_id"]


def test_despacho_con_cerrado_duplicado_cierra_en_el_de_menor_id(
    cliente, datos_cerrado_duplicado
):
    """AC-8: con dos `Cerrado`, el destino es el de menor `estado_id`, no el otro."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_cerrado_duplicado,
        [
            {
                "producto_id": datos_cerrado_duplicado["producto_id"],
                "cantidad_solicitada": 3,
            }
        ],
    )

    respuesta = despachar(
        cliente,
        ticket_id,
        {"usuario_id": datos_cerrado_duplicado["usuario_id"]},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert (
        respuesta.json()["estado_id"] == datos_cerrado_duplicado["estado_cerrado_id"]
    ), "debe cerrar en el `Cerrado` canónico (menor estado_id)"
    assert (
        respuesta.json()["estado_id"]
        != datos_cerrado_duplicado["estado_cerrado_duplicado_id"]
    )


def test_despacho_resuelve_los_nombres_sin_distinguir_mayusculas(
    cliente, motor, datos_minusculas
):
    """AC-8: `encurso`/`cerrado` en el catálogo gobiernan el despacho igual."""
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_minusculas,
        [{"producto_id": datos_minusculas["producto_id"], "cantidad_solicitada": 3}],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_minusculas["usuario_id"]}
    )

    assert respuesta.status_code == 200, respuesta.text
    cerrado = leer_ticket(cliente, ticket_id)
    assert cerrado["estado_id"] == datos_minusculas["estado_cerrado_id"]
    assert cerrado["fecha_cierre"] is not None
    assert len(salidas_del_ticket(motor, ticket_id)) == 1


# --- AC-9: inventario ausente o ambiguo ---


def test_despacho_rechaza_producto_sin_fila_de_inventario(
    cliente, motor, datos_inventario_invalido
):
    """AC-9: un detalle sin saldo en la sede del ticket → 409 sin efectos."""
    stock = leer_stock(cliente, datos_inventario_invalido["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_inventario_invalido,
        [
            {
                "producto_id": datos_inventario_invalido["producto_sin_inventario_id"],
                "cantidad_solicitada": 1,
            }
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_inventario_invalido["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    assert "stock" in respuesta.json()["detail"].lower()
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_inventario_invalido["estado_en_curso_id"],
        {datos_inventario_invalido["inventario_id"]: stock},
    )


def test_despacho_rechaza_producto_con_saldo_solo_en_otra_sede(
    cliente, motor, datos_inventario_invalido
):
    """AC-9: el despacho no usa el saldo de otra sede; 409 sin elegir bodega.

    Feature 011 (T9): la unicidad `(sede_id, producto_id)` hace imposible el caso
    de "dos filas del mismo producto" del modelo departamental; su equivalente es
    un producto con saldo **solo en otra sede**, que el despacho no debe tocar.
    """
    stock = leer_stock(cliente, datos_inventario_invalido["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_inventario_invalido,
        [
            {
                "producto_id": datos_inventario_invalido["producto_dos_filas_id"],
                "cantidad_solicitada": 1,
            }
        ],
    )

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_inventario_invalido["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    assert "stock" in respuesta.json()["detail"].lower()
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_inventario_invalido["estado_en_curso_id"],
        {datos_inventario_invalido["inventario_id"]: stock},
    )


# --- AC-10: ticket sin detalles ---


def test_despacho_de_ticket_sin_detalles_responde_409_sin_efectos(
    cliente, motor, datos_despacho
):
    """AC-10: un ticket sin líneas → 409 sin estado, fecha, stock ni movimientos.

    El alta exige al menos una línea, así que la ausencia se provoca borrando el
    detalle persistido con el motor de la fixture.
    """
    stock = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )
    db = sessionmaker(bind=motor)()
    try:
        db.query(DetalleTicket).filter(
            DetalleTicket.ticket_id == ticket_id
        ).delete()
        db.commit()
    finally:
        db.close()

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {datos_despacho["inventario_id"]: stock},
    )


# --- AC-14: producto de un detalle persistido no resoluble ---


def test_despacho_rechaza_detalle_con_producto_no_resoluble(
    cliente, motor, datos_despacho
):
    """AC-14/D-11: un detalle huérfano es 409 (integridad), no 404, y no escribe.

    La FK `detalle_ticket.producto_id` impide el caso en operación normal, así
    que la inconsistencia se inyecta con el motor de la fixture: se desactiva la
    comprobación de FKs mientras se añade la fila huérfana y se restaura después.
    """
    stock = leer_stock(cliente, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    with motor.connect() as conexion:
        conexion.exec_driver_sql("PRAGMA foreign_keys=OFF")
    db = sessionmaker(bind=motor)()
    try:
        db.add(
            DetalleTicket(
                ticket_id=ticket_id,
                producto_id=999999,
                cantidad_solicitada=1,
                cantidad_entregada=0,
                institucion_id=datos_despacho["institucion_id"],
            )
        )
        db.commit()
    finally:
        db.close()

    respuesta = despachar(
        cliente, ticket_id, {"usuario_id": datos_despacho["usuario_id"]}
    )

    assert respuesta.status_code == 409, respuesta.text
    assert "producto" in respuesta.json()["detail"].lower()
    verificar_sin_efectos(
        cliente,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {datos_despacho["inventario_id"]: stock},
    )


# --- AC-11: rollback ante fallo de escritura/commit ---


def test_despacho_revierte_todo_si_el_commit_falla(
    cliente_sin_excepcion, motor, datos_despacho, monkeypatch
):
    """AC-11: un fallo del `commit` revierte rebajas, entregas, estado y salidas.

    Se inyecta el fallo en `Session.commit` (justo después de que el servicio ya
    mutó inventario, detalles, ticket y movimientos) y se observa la respuesta
    500 y el estado persistido. Con `cliente_sin_excepcion` la excepción se
    convierte en 500 en vez de relanzarse al test.
    """
    from sqlalchemy.orm import Session

    stock = leer_stock(cliente_sin_excepcion, datos_despacho["inventario_id"])
    ticket_id = abrir_ticket_en_curso(
        cliente_sin_excepcion,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )

    def commit_que_falla(self):
        raise RuntimeError("fallo de commit inyectado para probar el rollback")

    monkeypatch.setattr(Session, "commit", commit_que_falla)

    respuesta = despachar(
        cliente_sin_excepcion,
        ticket_id,
        {"usuario_id": datos_despacho["usuario_id"]},
    )

    assert respuesta.status_code == 500, respuesta.text

    # Restaurar `commit` para poder releer el estado tal como quedó en la base.
    monkeypatch.undo()

    verificar_sin_efectos(
        cliente_sin_excepcion,
        motor,
        ticket_id,
        datos_despacho["estado_en_curso_id"],
        {datos_despacho["inventario_id"]: stock},
    )
    assert (
        salidas_persistidas(motor) == []
    ), "el rollback debe borrar también los movimientos a medio escribir"


# ==========================================================================
# T5 — Contrato OpenAPI de la ruta de despacho (AC-1, AC-21)
# ==========================================================================


def test_openapi_declara_el_contrato_del_despacho(cliente):
    """AC-21: `/openapi.json` documenta ruta, payload, 200 y errores relevantes.

    El proyecto **no usa `responses=`** en ningún endpoint: los códigos de error
    se documentan en la `description` y así los asertan los contratos previos
    (p. ej. `test_el_contrato_del_patch_documenta_404_409_y_sellado`). Se sigue
    ese mismo patrón aquí en lugar de introducir una convención nueva.
    """
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"]["/api/v1/tickets/{ticket_id}/despacho"]["post"]

    assert operacion["summary"], "la operación debe declarar un resumen"

    peticion = operacion["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert peticion.endswith("TicketDespacho"), peticion

    respuesta = operacion["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert respuesta.endswith("TicketRespuesta"), respuesta

    descripcion = operacion["description"]
    for codigo in ("404", "409", "422"):
        assert codigo in descripcion, f"falta documentar el {codigo}"


def test_openapi_declara_la_respuesta_200_explicita(cliente):
    """AC-21: el 200 de despacho es explícito y reutiliza `TicketRespuesta`."""
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"]["/api/v1/tickets/{ticket_id}/despacho"]["post"]

    assert "200" in operacion["responses"], "el 200 debe declararse explícitamente"
    esquema = contrato["components"]["schemas"]["TicketRespuesta"]
    assert {"ticket_id", "estado_id", "fecha_cierre", "detalles"} <= set(
        esquema["properties"]
    ), "la respuesta del despacho debe exponer el ticket actualizado con sus detalles"

