"""Feature 004: transiciones del flujo lineal y sellado de cierre de tickets.

El seam bajo prueba es la interfaz HTTP (`TestClient`), como en toda la suite:
los rechazos 409, los 404 de referencia y el sellado de `fecha_cierre` se
observan desde `PATCH /tickets/{id}/estado`, nunca tocando la sesion.

Las fixtures de catalogo reemplazan los dos estados de `datos_base`
(INGRESADO, CERRADO) por catalogos a medida, siguio siempre el orden de
`spec.md` §5. El DELETE es seguro porque en este punto no existe ningun
ticket que referencie los estados borrados.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.models import EstadoTicket


def _instalar_catalogo(motor, nombres):
    """Borra los estados y crea los de `nombres`, en ese orden de ids.

    Devuelve `{nombre: id}`. El orden de insercion es el orden del flujo
    (`estado_id` ascendente), que es como lo consumen las reglas de la 004.
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

    Un `dict` colapsaría un nombre duplicado a su última aparición; los casos de
    catálogo degenerado (p. ej. dos `Cerrado`) necesitan distinguir el id
    canónico (menor) del duplicado, así que la lista mantiene el orden de
    inserción, que es el del `estado_id`.
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


def _datos_prueba(datos_base):
    """Copia de `datos_base` sin los ids de los estados que ya no existen."""
    datos = {**datos_base}
    datos.pop("estado_ingresado_id")
    datos.pop("estado_cerrado_id")
    return datos


@pytest.fixture
def datos_flujo_canonico(motor, datos_base):
    """Catalogo canonico de 4 estados en orden, con `Cerrado` al final."""
    ids = _instalar_catalogo(
        motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado")
    )
    datos = _datos_prueba(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids["Pendiente"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["EnCurso"],
            "estado_cerrado_id": ids["Cerrado"],
            "estados_orden": [
                ids["Pendiente"],
                ids["EnRevision"],
                ids["EnCurso"],
                ids["Cerrado"],
            ],
        }
    )
    return datos


@pytest.fixture
def datos_flujo_cerrado_id_avanzado(motor, datos_base):
    """Catálogo canónico corrido: `EnCurso` es id 4 y `Cerrado` id 5, no el 4
    que asumía el código viejo. Sirve para probar que la guardia de cierre
    resuelve `EnCurso`/`Cerrado` por nombre, sin depender de un id fijo."""
    ids = _instalar_catalogo(
        motor, ("Archivado", "Pendiente", "EnRevision", "EnCurso", "Cerrado")
    )
    datos = _datos_prueba(datos_base)
    datos.update(
        {
            "estado_archivado_id": ids["Archivado"],
            "estado_en_revision_id": ids["EnRevision"],
            "estado_en_curso_id": ids["EnCurso"],
            "estado_cerrado_id": ids["Cerrado"],
        }
    )
    return datos


@pytest.fixture
def datos_flujo_cerrado_duplicado(motor, datos_base):
    """Dos `Cerrado`: el canónico (menor `estado_id`) no es el último ordinal.

    La lista conserva ambos ids; el `dict` habría colapsado el nombre. La
    guardia AC-15 debe reconocer el `Cerrado` canónico por menor id y no por ser
    el último del catálogo.
    """
    ids = _instalar_catalogo_lista(
        motor, ("Pendiente", "EnRevision", "EnCurso", "Cerrado", "Cerrado")
    )
    datos = _datos_prueba(datos_base)
    datos.update(
        {
            "estado_pendiente_id": ids[0],
            "estado_en_revision_id": ids[1],
            "estado_en_curso_id": ids[2],
            "estado_cerrado_id": ids[3],  # el de menor id: el canónico
            "estado_cerrado_duplicado_id": ids[4],
        }
    )
    return datos


@pytest.fixture
def datos_flujo_cerrado_minuscula(motor, datos_base):
    """Terminal llamado `CERRADO`: ejercita el `casefold()` del sellado."""
    ids = _instalar_catalogo(motor, ("Pendiente", "EnRevision", "CERRADO"))
    datos = _datos_prueba(datos_base)
    datos.update(
        {
            "estado_en_revision_id": ids["EnRevision"],
            "estado_cerrado_id": ids["CERRADO"],
        }
    )
    return datos


@pytest.fixture
def datos_flujo_cerrado_no_terminal(motor, datos_base):
    """`Cerrado` en medio del catalogo: un estado terminal jamas permite
    entrar dos veces, asi que solo un catalogo degenerado habilita la
    reentrada que D-3 debe sobrevivir."""
    ids = _instalar_catalogo(
        motor, ("Pendiente", "EnRevision", "Cerrado", "Archivado", "Reabierto")
    )
    datos = _datos_prueba(datos_base)
    datos.update(
        {
            "estado_en_revision_id": ids["EnRevision"],
            "estado_cerrado_id": ids["Cerrado"],
            "estado_archivado_id": ids["Archivado"],
        }
    )
    return datos


def crear_ticket_con_estado(cliente, datos, estado_id: int) -> int:
    """Alta via API en el estado indicado; devuelve el `ticket_id`."""
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos["usuario_id"],
            "prioridad_id": datos["prioridad_id"],
            "estado_id": estado_id,
            "asunto": "Papel y carpetas para la oficina central",
            "descripcion": "Se acabo el papel del trimestre.",
            "detalles": [
                {"producto_id": datos["producto_id"], "cantidad_solicitada": 3}
            ],
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["ticket_id"]


def ticket_en_api(cliente, ticket_id: int) -> dict:
    """Lee el ticket tal como lo ve un cliente: por la lista de `GET /tickets/`."""
    respuesta = cliente.get("/api/v1/tickets/")
    assert respuesta.status_code == 200, respuesta.text
    return next(t for t in respuesta.json() if t["ticket_id"] == ticket_id)


def cambiar_estado(cliente, ticket_id: int, estado_id: int):
    return cliente.patch(
        f"/api/v1/tickets/{ticket_id}/estado", json={"estado_id": estado_id}
    )


# --- Transiciones validas: un paso en cualquier direccion (AC-9, AC-10) ---


def test_avanzar_un_paso_pasa_al_siguiente_estado(cliente, datos_flujo_canonico):
    """Pendiente -> EnRevision es un paso: 200 y el ticket queda ahí."""
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_pendiente_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_en_revision_id"]
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == datos_flujo_canonico["estado_en_revision_id"]
    assert respuesta.json()["fecha_cierre"] is None, "avanzar a EnRevision no sella fecha"


def test_retroceder_un_paso_vuelve_al_estado_anterior(cliente, datos_flujo_canonico):
    """EnRevision -> Pendiente es un paso hacia atrás: 200."""
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_en_revision_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_pendiente_id"]
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == datos_flujo_canonico["estado_pendiente_id"]


# --- Rechazos del flujo (AC-13) ---


def test_salto_de_estado_se_rechaza_con_409(cliente, datos_flujo_canonico):
    """Pendiente -> EnCurso salta EnRevision: 409 y el ticket no cambia."""
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_pendiente_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_en_curso_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert ticket_en_api(cliente, ticket_id)["estado_id"] == datos_flujo_canonico[
        "estado_pendiente_id"
    ], "un 409 no puede dejar el ticket en otro estado"


def test_pedir_el_estado_actual_se_rechaza_con_409(cliente, datos_flujo_canonico):
    """Pedir el estado en el que ya está no es una transición: 409."""
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_pendiente_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_pendiente_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert ticket_en_api(cliente, ticket_id)["estado_id"] == datos_flujo_canonico[
        "estado_pendiente_id"
    ]


def test_retroceso_desde_el_terminal_se_rechaza_con_409(cliente, datos_flujo_canonico):
    """`Cerrado` es terminal: no sale ni retrocediendo (D-2)."""
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_cerrado_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_en_curso_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert ticket_en_api(cliente, ticket_id)["estado_id"] == datos_flujo_canonico[
        "estado_cerrado_id"
    ], "un ticket cerrado no se reabre"


# --- Referencias inexistentes (AC-14, AC-15, orden D-8) ---


def test_estado_inexistente_responde_404_sin_modificar(
    cliente_sin_excepcion, datos_flujo_canonico
):
    """Un estado que no existe en el catálogo es 404 nombrando la referencia.

    Se usa `cliente_sin_excepcion` para observar la respuesta en vez de una
    excepcion relanzada: si el service deja que la FK reviente en el `commit`,
    hoy sale un 500 y el test queda en rojo limpio.
    """
    ticket_id = crear_ticket_con_estado(
        cliente_sin_excepcion,
        datos_flujo_canonico,
        datos_flujo_canonico["estado_pendiente_id"],
    )

    respuesta = cambiar_estado(cliente_sin_excepcion, ticket_id, 999999)

    assert respuesta.status_code == 404, respuesta.text
    assert "estado" in respuesta.json()["detail"].lower()
    assert ticket_en_api(cliente_sin_excepcion, ticket_id)["estado_id"] == (
        datos_flujo_canonico["estado_pendiente_id"]
    ), "un 404 no puede modificar el ticket"


def test_ticket_inexistente_responde_404(cliente, datos_flujo_canonico):
    """PATCH sobre un ticket que no existe: 404 nombrando el ticket."""
    respuesta = cambiar_estado(
        cliente, 999999, datos_flujo_canonico["estado_en_revision_id"]
    )

    assert respuesta.status_code == 404, respuesta.text
    assert "ticket" in respuesta.json()["detail"].lower()


def test_el_ticket_se_valida_antes_que_el_estado(cliente, datos_flujo_canonico):
    """D-8: con ticket y estado inexistentes a la vez, el 404 es del ticket."""
    respuesta = cambiar_estado(cliente, 999999, 888888)

    assert respuesta.status_code == 404, respuesta.text
    detalle = respuesta.json()["detail"].lower()
    assert "ticket" in detalle, f"deberia quejarse primero del ticket, no de: {detalle}"
    assert "estado" not in detalle


# --- Cierre manual reservado al despacho (AC-15) ---


def test_avanzar_a_cerrado_esta_reservado_al_despacho(cliente, datos_flujo_canonico):
    """Migrado de AC-16 (004): `EnCurso -> Cerrado` por PATCH ya no cierra.

    La spec 005 reserva ese cierre al despacho transaccional, de modo que el
    PATCH responde 409 con el detalle literal, sin mover el ticket ni sellar
    `fecha_cierre`. El sellado por cierre se cubre en el despacho.
    """
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_en_curso_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_cerrado_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == (
        "El cierre requiere despacho; use "
        f"POST /api/v1/tickets/{ticket_id}/despacho"
    )

    ticket = ticket_en_api(cliente, ticket_id)
    assert ticket["estado_id"] == datos_flujo_canonico["estado_en_curso_id"], (
        "un 409 por cierre reservado no puede mover el ticket"
    )
    assert ticket["fecha_cierre"] is None, (
        "el PATCH no sella cierre: el sellado corresponde al despacho"
    )


def test_el_cierre_manual_con_cerrado_duplicado_usa_el_de_menor_id(
    cliente, datos_flujo_cerrado_duplicado
):
    """AC-15/D-12: la guardia reconoce el `Cerrado` canónico (menor `estado_id`).

    En este catálogo hay dos `Cerrado` y el canónico (menor id) **no** es el
    último ordinal. Si la guardia comparara contra el último estado del catálogo
    en vez de resolver por nombre, este PATCH cerraría el ticket con un 200; el
    409 exacto prueba que usa el `Cerrado` de menor id.
    """
    ticket_id = crear_ticket_con_estado(
        cliente,
        datos_flujo_cerrado_duplicado,
        datos_flujo_cerrado_duplicado["estado_en_curso_id"],
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_duplicado["estado_cerrado_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == (
        "El cierre requiere despacho; use "
        f"POST /api/v1/tickets/{ticket_id}/despacho"
    )

    ticket = ticket_en_api(cliente, ticket_id)
    assert ticket["estado_id"] == datos_flujo_cerrado_duplicado["estado_en_curso_id"]
    assert ticket["fecha_cierre"] is None


def test_el_cierre_reservado_no_depende_del_id_del_estado(
    cliente, datos_flujo_cerrado_id_avanzado
):
    """Migrado de AC-18 (004): con `EnCurso` id 4 y `Cerrado` id 5, la guardia
    sigue disparando porque resuelve por nombre, no por el id 4 fijo."""
    ticket_id = crear_ticket_con_estado(
        cliente,
        datos_flujo_cerrado_id_avanzado,
        datos_flujo_cerrado_id_avanzado["estado_en_curso_id"],
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_id_avanzado["estado_cerrado_id"]
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == (
        "El cierre requiere despacho; use "
        f"POST /api/v1/tickets/{ticket_id}/despacho"
    )
    assert ticket_en_api(cliente, ticket_id)["estado_id"] == (
        datos_flujo_cerrado_id_avanzado["estado_en_curso_id"]
    )


def test_una_transicion_no_reservada_desde_en_curso_sigue_siendo_200(
    cliente, datos_flujo_canonico
):
    """AC-15: solo `EnCurso -> Cerrado` está reservado; retroceder sigue valiendo.

    Las demás transiciones válidas de la 004 conservan su comportamiento: desde
    `EnCurso` el retroceso a `EnRevision` responde 200.
    """
    ticket_id = crear_ticket_con_estado(
        cliente, datos_flujo_canonico, datos_flujo_canonico["estado_en_curso_id"]
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_canonico["estado_en_revision_id"]
    )

    assert respuesta.status_code == 200, respuesta.text
    assert (
        respuesta.json()["estado_id"]
        == datos_flujo_canonico["estado_en_revision_id"]
    )


# --- Sellado de la fecha de cierre (AC-18) ---


def test_el_sellado_no_distingue_mayusculas(cliente, datos_flujo_cerrado_minuscula):
    """El terminal se llama `CERRADO`; aun asi debe sellar (D-3, AC-18)."""
    ticket_id = crear_ticket_con_estado(
        cliente,
        datos_flujo_cerrado_minuscula,
        datos_flujo_cerrado_minuscula["estado_en_revision_id"],
    )

    respuesta = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_minuscula["estado_cerrado_id"]
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["fecha_cierre"] is not None, (
        "CERRADO, Cerrado y cerrado valen lo mismo"
    )


def test_reentrar_en_cerrado_conserva_la_fecha_original(
    cliente, datos_flujo_cerrado_no_terminal
):
    """D-3: con catalogo degenerado se entra dos veces; nunca se sobrescribe."""
    ticket_id = crear_ticket_con_estado(
        cliente,
        datos_flujo_cerrado_no_terminal,
        datos_flujo_cerrado_no_terminal["estado_en_revision_id"],
    )

    primera = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_no_terminal["estado_cerrado_id"]
    )
    assert primera.status_code == 200, primera.text
    fecha_sellada = primera.json()["fecha_cierre"]
    assert fecha_sellada is not None, "la primera entrada en Cerrado debe sellar"

    fuera = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_no_terminal["estado_archivado_id"]
    )
    assert fuera.status_code == 200, fuera.text
    assert fuera.json()["fecha_cierre"] == fecha_sellada, (
        "salir de Cerrado no puede borrar la fecha"
    )

    segunda = cambiar_estado(
        cliente, ticket_id, datos_flujo_cerrado_no_terminal["estado_cerrado_id"]
    )
    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["fecha_cierre"] == fecha_sellada, (
        "la reentrada en Cerrado debe conservar la fecha original, no sellar otra"
    )


def test_crear_ticket_en_cerrado_sella_fecha_cierre(
    cliente, datos_flujo_canonico
):
    """AC-17: alta directa en estado `Cerrado` sella `fecha_cierre` al instante."""
    ticket_id = crear_ticket_con_estado(
        cliente,
        datos_flujo_canonico,
        datos_flujo_canonico["estado_cerrado_id"],
    )

    ticket = ticket_en_api(cliente, ticket_id)

    assert ticket["fecha_cierre"] is not None, (
        "crear ticket en Cerrado debe sellar fecha_cierre"
    )
    assert ticket["estado_id"] == datos_flujo_canonico["estado_cerrado_id"]


# --- Listado: orden explícito y sin N+1 (AC-27) ---


def test_listar_tickets_ordena_por_fecha_desc_y_ticket_id_desc(
    cliente, datos_flujo_canonico
):
    """AC-27: `fecha_creacion DESC` y, en empate, `ticket_id DESC`.

    En SQLite `CURRENT_TIMESTAMP` tiene resolución de segundo, así que tres
    altas seguidas comparten `fecha_creacion` y el desempate por `ticket_id`
    descendente es el que decide el orden observable.
    """
    ids = [
        crear_ticket_con_estado(
            cliente,
            datos_flujo_canonico,
            datos_flujo_canonico["estado_pendiente_id"],
        )
        for _ in range(3)
    ]

    respuesta = cliente.get("/api/v1/tickets/")
    assert respuesta.status_code == 200, respuesta.text
    devueltos = respuesta.json()

    def clave(ticket):
        return (ticket["fecha_creacion"], ticket["ticket_id"])

    assert devueltos == sorted(devueltos, key=clave, reverse=True), (
        "el listado debe venir ordenado por fecha_creacion DESC y, en empate, "
        f"ticket_id DESC; ids creados: {ids}"
    )
    assert [t["ticket_id"] for t in devueltos] == sorted(ids, reverse=True)


def test_listar_tickets_no_hace_consultas_por_ticket(
    cliente, motor, datos_flujo_canonico
):
    """AC-27: con carga eager en cadena, el nº de SELECT no crece con los tickets.

    Se cuenta con `before_cursor_execute` sobre el motor de la fixture y se
    compara 1 ticket contra 3. Se compara el conteo y no un número exacto
    porque los `PRAGMA` de SQLite no son estables entre versiones.
    """
    contador = {"n": 0}

    def contar(*_args, **_kwargs):
        contador["n"] += 1

    event.listen(motor, "before_cursor_execute", contar)
    try:
        crear_ticket_con_estado(
            cliente,
            datos_flujo_canonico,
            datos_flujo_canonico["estado_pendiente_id"],
        )
        contador["n"] = 0
        assert cliente.get("/api/v1/tickets/").status_code == 200
        with_uno = contador["n"]

        for _ in range(2):
            crear_ticket_con_estado(
                cliente,
                datos_flujo_canonico,
                datos_flujo_canonico["estado_pendiente_id"],
            )
        contador["n"] = 0
        assert cliente.get("/api/v1/tickets/").status_code == 200
        with_tres = contador["n"]
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    assert with_tres == with_uno, (
        "el listado no puede emitir una consulta por ticket (N+1): "
        f"{with_uno} queries con 1 ticket y {with_tres} con 3"
    )
    # Feature 008: la identidad de la suite funcional es un rol limitado
    # (Administrador), asi que el listado resuelve su ambito institucional con una
    # consulta fija adicional (`alcance_institucional`); por eso el tope sube de 4
    # a 5. Lo que protege esta prueba es que el numero NO crezca con los tickets.
    assert with_tres <= 5, (
        "carga eager en cadena debe resolverlo en pocas consultas fijas: "
        f"{with_tres} consultas con 3 tickets"
    )


# --- Contrato OpenAPI del cambio de estado (AGENTS §11) ---


def test_el_contrato_del_patch_documenta_404_409_y_sellado(cliente):
    """`/openapi.json` del PATCH menciona los rechazos y el sellado."""
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"]["/api/v1/tickets/{ticket_id}/estado"]["patch"]
    descripcion = operacion["description"]

    assert "404" in descripcion, "falta documentar los 404 de ticket/estado"
    assert "409" in descripcion, "falta documentar el 409 de flujo"
    assert "fecha_cierre" in descripcion, "falta documentar el sellado de cierre"


def test_el_contrato_del_patch_documenta_el_cierre_reservado(cliente):
    """AC-15/AC-21: el PATCH documenta el 409 reservado al despacho, literal.

    El 409 de negocio se documenta en la `description` (convención del
    proyecto, que no usa `responses=`), y el detalle exacto del rechazo debe
    aparecer verificable en `/openapi.json`, no solo en la respuesta HTTP.
    """
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"]["/api/v1/tickets/{ticket_id}/estado"]["patch"]
    descripcion = operacion["description"]

    literal = (
        "El cierre requiere despacho; use POST "
        "/api/v1/tickets/{ticket_id}/despacho"
    )
    assert literal in descripcion, (
        "falta el detalle literal del cierre reservado al despacho (AC-15)"
    )
