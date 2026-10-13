"""Feature 005 (T7): read model del historial de movimientos (AC-17..AC-20, AC-23).

El seam observado es la **interfaz HTTP**: el historial se consulta con
`GET /inventario/movimientos` por el `TestClient`, como el resto de la suite, y
su contenido se compara contra los efectos persistidos por las operaciones
reales (el registro manual de la 002 y el despacho de la 005), nunca contra
columnas internas.

Fase ROJA de TDD: aqui todavia no existen ni la consulta del service (T8) ni la
ruta GET (T9). Cada prueba que lee el historial debe fallar por esa ausencia y
no por imports, fixtures o sintaxis. Ojo con la ruta: `POST /inventario/movimientos`
si existe (Feature 002), asi que un `GET` sobre el mismo path NO da 404 sino
**405 Method Not Allowed** con `Allow: POST`. Ese 405 es, precisamente, la
evidencia de que la ruta de lectura todavia no esta declarada.

Para los datos de fechas controladas se siembra `movimiento_inventario` con el
motor de la fixture: `fecha_movimiento` tiene `server_default` y el alta manual
no acepta fecha, de modo que no hay otra via de forzar el empate de fechas que
el orden debe desempatar por `movimiento_id` descendente (D-8/AC-19).
"""

from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import EstadoTicket, MovimientoInventario

#: Ruta contractual del historial (`spec.md` §5).
RUTA_HISTORIAL = "/api/v1/inventario/movimientos"

#: Las once claves del DTO `MovimientoInventarioRespuesta` (`spec.md` §5).
CAMPOS_HISTORIAL = {
    "movimiento_id",
    "tipo_movimiento",
    "cantidad",
    "fecha_movimiento",
    "observacion",
    "inventario_id",
    "producto_id",
    "producto_nombre",
    "departamento_id",
    "departamento_nombre",
    "ubicacion",
}


# --- Helpers compartidos con el flujo de despacho (T2) ---


def _instalar_catalogo(motor, nombres):
    """Borra los estados y crea `nombres` en ese orden de ids (canonico)."""
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


def _sembrar_movimiento(motor, inventario_id, fecha, observacion, tipo="ENTRADA", cantidad=1):
    """Inserta una fila de `movimiento_inventario` con fecha explicita.

    Devuelve el `movimiento_id` generado. Se usa el motor solo para fijar la
    fecha (control del orden), no para observar el comportamiento: la lectura
    bajo prueba sigue siendo HTTP.
    """
    db = sessionmaker(bind=motor)()
    try:
        movimiento = MovimientoInventario(
            tipo_movimiento=tipo,
            cantidad=cantidad,
            fecha_movimiento=fecha,
            observacion=observacion,
            inventario_id=inventario_id,
        )
        db.add(movimiento)
        db.commit()
        db.refresh(movimiento)
        return movimiento.movimiento_id
    finally:
        db.close()


@pytest.fixture
def datos_despacho(motor, datos_base):
    """Catalogo canonico del flujo sobre el producto e inventario de `datos_base`."""
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado"))
    datos = {**datos_base}
    datos.pop("estado_ingresado_id", None)
    datos.pop("estado_cerrado_id", None)
    datos.update(
        {
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["EnCurso"],
            "estado_cerrado_id": ids["Cerrado"],
        }
    )
    return datos


def _abrir_ticket_en_curso(cliente, datos, detalles) -> int:
    """Da de alta un ticket y lo lleva a `EnCurso` por la API; devuelve su id."""
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


def _leer_historial(cliente):
    """Consulta el historial por HTTP y exige el contrato 200 (AC-17/AC-18)."""
    respuesta = cliente.get(RUTA_HISTORIAL)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --- AC-17: lista vacia con el catalogo cargado y sin movimientos ---


def test_historial_sin_movimientos_devuelve_lista_vacia(cliente, datos_base):
    """AC-17: sin filas de auditoria el recurso responde 200 con `[]`."""
    cuerpo = _leer_historial(cliente)
    assert cuerpo == [], "el historial es una lista, incluso vacia"


# --- AC-18: campos asociados completos (origen: registro manual de la 002) ---


def test_historial_expone_los_campos_asociados_del_movimiento(
    cliente, motor, datos_base
):
    """AC-18/AC-22: el movimiento manual aparece con producto, departamento y ubicacion.

    Se crea por HTTP con el registro manual de la 002 (misma tabla) y se lee por
    HTTP en el historial; asi el caso comprueba tambien que un movimiento ajeno
    al despacho entra en la misma lectura.
    """
    registro = cliente.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo_movimiento": "ENTRADA",
            "cantidad": 5,
            "observacion": "Ingreso de reposicion",
            "inventario_id": datos_base["inventario_id"],
        },
    )
    assert registro.status_code == 201, registro.text

    cuerpo = _leer_historial(cliente)
    assert len(cuerpo) == 1, f"se esperaba el movimiento manual: {cuerpo}"
    movimiento = cuerpo[0]

    assert set(movimiento) == CAMPOS_HISTORIAL, "faltan campos del contrato (§5)"
    assert movimiento["tipo_movimiento"] == "ENTRADA"
    assert movimiento["cantidad"] == 5
    assert movimiento["observacion"] == "Ingreso de reposicion"
    assert movimiento["inventario_id"] == datos_base["inventario_id"]
    assert movimiento["producto_id"] == datos_base["producto_id"]
    assert movimiento["producto_nombre"] == "Cuaderno linedado"
    assert movimiento["departamento_id"] == datos_base["departamento_id"]
    assert movimiento["departamento_nombre"] == "Operaciones"
    assert movimiento["ubicacion"] == "Bodega central"


# --- AC-19: orden determinista por fecha DESC y desempate por id DESC ---


def test_historial_ordena_por_fecha_desc_y_desempata_por_id_desc(
    cliente, motor, datos_base
):
    """AC-19/D-8: fecha descendente; ante empate, `movimiento_id` descendente.

    Se siembran tres filas con fechas controladas: dos comparten la MISMA fecha
    (`empate`) para forzar el desempate por id, y una es mas reciente. El orden
    esperado es `reciente`, luego el empate de id mayor y por ultimo el de id
    menor: si el desempate no existiera, el par empatado saldria en orden de
    insercion (id ascendente) y la prueba fallaria.
    """
    inventario_id = datos_base["inventario_id"]
    fecha_vieja = datetime(2026, 1, 1, 10, 0, 0)
    fecha_nueva = datetime(2026, 1, 2, 10, 0, 0)

    id_viejo_primero = _sembrar_movimiento(
        motor, inventario_id, fecha_vieja, "empate insertado primero"
    )
    id_reciente = _sembrar_movimiento(
        motor, inventario_id, fecha_nueva, "movimiento mas reciente"
    )
    id_viejo_segundo = _sembrar_movimiento(
        motor, inventario_id, fecha_vieja, "empate insertado despues"
    )

    cuerpo = _leer_historial(cliente)

    assert [m["movimiento_id"] for m in cuerpo] == [
        id_reciente,
        id_viejo_segundo,
        id_viejo_primero,
    ], "fecha DESC y, ante empate, movimiento_id DESC"

    fechas = [m["fecha_movimiento"] for m in cuerpo]
    assert fechas == sorted(fechas, reverse=True), "las fechas deben venir descendentes"


# --- AC-20: la salida del despacho aparece en el historial ---


def test_la_salida_de_un_despacho_aparece_en_el_historial(cliente, motor, datos_despacho):
    """AC-20/D-6: el `SALIDA` del despacho se lee con cantidad, observacion e inventario.

    Se corre el flujo HTTP real de despacho y luego se consulta el historial por
    HTTP: el movimiento debe traer el tipo, la cantidad, la observacion literal
    D-6 y el inventario de destino esperados, ademas de los datos asociados.
    """
    ticket_id = _abrir_ticket_en_curso(
        cliente,
        datos_despacho,
        [{"producto_id": datos_despacho["producto_id"], "cantidad_solicitada": 3}],
    )
    despacho = cliente.post(
        f"/api/v1/tickets/{ticket_id}/despacho",
        json={"usuario_id": datos_despacho["usuario_id"]},
    )
    assert despacho.status_code == 200, despacho.text
    detalle_id = despacho.json()["detalles"][0]["detalle_ticket_id"]

    cuerpo = _leer_historial(cliente)
    salidas = [m for m in cuerpo if m["tipo_movimiento"] == "SALIDA"]
    assert len(salidas) == 1, f"se esperaba una salida de despacho: {cuerpo}"

    salida = salidas[0]
    assert set(salida) == CAMPOS_HISTORIAL, "faltan campos del contrato (§5)"
    assert salida["cantidad"] == 3
    assert salida["observacion"] == (
        f"Despacho ticket_id={ticket_id}; "
        f"detalle_id={detalle_id}; "
        f"producto_id={datos_despacho['producto_id']}"
    )
    assert salida["inventario_id"] == datos_despacho["inventario_id"]
    assert salida["producto_nombre"] == "Cuaderno linedado"
    assert salida["departamento_nombre"] == "Operaciones"
    assert salida["ubicacion"] == "Bodega central"


# --- AC-20: el recurso es de solo lectura (sin modificar ni borrar) ---


def test_el_historial_solo_declara_lectura_en_el_contrato(cliente):
    """AC-20: el contrato expone `get` (y el `post` manual) y ningun verbo de mutacion.

    En rojo falla porque el `get` aun no esta declarado; cuando T9 lo agregue,
    la prueba exige que no aparezca `put`, `patch` ni `delete` para el historial.
    """
    contrato = cliente.get("/openapi.json").json()
    metodos = contrato["paths"][RUTA_HISTORIAL]

    assert "get" in metodos, "el historial debe declarar la lectura por GET"
    assert (
        metodos.keys() & {"put", "patch", "delete"} == set()
    ), f"el historial no ofrece modificacion ni borrado: {sorted(metodos)}"


@pytest.mark.parametrize("verbo", ["put", "patch", "delete"])
def test_el_historial_rechaza_verbos_de_mutacion_por_http(cliente, verbo):
    """AC-20: no hay ruta de modificar/borrar; el verbo responde 404 o 405.

    Ante la ausencia de la operacion, FastAPI responde 405 (el path existe por
    el POST manual) o 404 si no existiera ningun metodo; ambos descartan
    cualquier efecto sobre los registros.
    """
    respuesta = getattr(cliente, verbo)(RUTA_HISTORIAL)
    assert respuesta.status_code in (404, 405), respuesta.text


# --- AC-21: contrato OpenAPI del historial y del POST manual (T11) ---


def test_openapi_del_historial_declara_el_200_el_read_model_y_el_orden(cliente):
    """AC-21: el GET declara 200, el DTO nuevo y el orden determinista.

    El 200 debe ser explicito y la respuesta del `response_model`
    `MovimientoInventarioRespuesta`; la `description` fija el orden que el
    service garantiza (`fecha_movimiento` DESC, desempate `movimiento_id` DESC).
    """
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"][RUTA_HISTORIAL]["get"]

    assert operacion["summary"], "la operacion debe declarar un resumen"
    assert "200" in operacion["responses"], "el 200 debe declararse explicitamente"

    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["type"] == "array", "el historial es una lista, incluso vacia"
    assert esquema["items"]["$ref"].endswith("MovimientoInventarioRespuesta"), esquema

    descripcion = operacion["description"]
    assert "fecha_movimiento" in descripcion and "movimiento_id" in descripcion, (
        "la descripcion debe documentar el orden determinista del historial"
    )


def test_openapi_del_registro_manual_conserva_201_y_su_payload(cliente):
    """AC-22: el POST manual de movimientos conserva su contrato previo (201).

    No se amplia en la 005; la asercion fija que sigue declarando 201 y el
    `requestBody` del `MovimientoCrear` de la Feature 002.
    """
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"][RUTA_HISTORIAL]["post"]

    assert "201" in operacion["responses"], "el alta manual sigue respondiendo 201"
    peticion = operacion["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert peticion.endswith("MovimientoCrear"), peticion
