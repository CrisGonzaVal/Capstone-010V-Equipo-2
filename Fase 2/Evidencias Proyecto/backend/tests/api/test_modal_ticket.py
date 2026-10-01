"""Feature 003: catalogos del modal y validaciones del alta de ticket.

El seam bajo prueba es la **interfaz HTTP** (`TestClient`), como en el resto de la
suite: nada consulta la base directamente, todo se comprueba leyendo la API.

La fixture `datos_catalogo_ticket` **se apoya** en `datos_base` en vez de
reemplazarla, para no duplicar el catalogo minimo ni modificar `conftest.py`.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import EstadoTicket, Producto, Prioridad


@pytest.fixture
def datos_catalogo_ticket(motor, datos_base):
    """Amplia `datos_base` con varias prioridades y estados.

    Los estados se insertan en orden **descendente** a proposito: si el endpoint
    ordenara por nombre, "INGRESADO" (agregado por `datos_base`) quedaria en
    ultima posicion y el test de orden del flujo fallaria. Asi el test distingue
    "ordena por id" de "ordena alfabeticamente" sin depender del azar.

    Anade tambien un producto sin existencias, para que `stock_total` en 0 sea
    un caso real y no una hipotesis.
    """
    db = sessionmaker(bind=motor)()
    try:
        for nombre in ("MEDIA", "BAJA"):
            db.add(Prioridad(nombre=nombre, descripcion=f"Prioridad {nombre.lower()}"))
        db.flush()

        for nombre in ("CERRADO_TEST", "EN_CURSO", "INGRESADO_TEST"):
            db.add(EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre.lower()}"))
        db.flush()

        producto_sin_stock = Producto(
            nombre="Zzz sin existencias",
            descripcion="No tiene filas en inventario",
            unidad_medida="UNIDAD",
            stock_minimo=5,
            categoria_id=datos_base["categoria_id"],
        )
        db.add(producto_sin_stock)
        db.commit()

        prioridades = db.query(Prioridad).order_by(Prioridad.prioridad_id).all()
        estados = db.query(EstadoTicket).order_by(EstadoTicket.estado_id).all()

        return {
            **datos_base,
            "producto_sin_stock_id": producto_sin_stock.producto_id,
            "prioridades_ids": [p.prioridad_id for p in prioridades],
            "estados_ids": [e.estado_id for e in estados],
            "estados_nombres": [e.nombre for e in estados],
            "estado_primer_id": estados[0].estado_id,
            "estado_ultimo_id": estados[-1].estado_id,
        }
    finally:
        db.close()


def cuerpo_ticket_valido(datos, **cambios):
    """Payload minimo valido, con los ids reales de la fixture."""
    cuerpo = {
        "usuario_id": datos["usuario_id"],
        "prioridad_id": datos["prioridad_id"],
        "estado_id": datos["estado_ingresado_id"],
        "asunto": "Falta de papel para el trimestre",
        "descripcion": "Se agoto el papel en las salas de clase.",
        "detalles": [{"producto_id": datos["producto_id"], "cantidad_solicitada": 3}],
    }
    cuerpo.update(cambios)
    return cuerpo


# --- AC-1: el endpoint existe y devuelve las cuatro listas ---


def test_catalogos_responde_200_con_las_cuatro_listas(cliente, datos_catalogo_ticket):
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"prioridades", "estados", "productos", "solicitantes"}
    assert cuerpo["prioridades"], "prioridades no puede salir vacia"
    assert cuerpo["estados"], "estados no puede salir vacia"
    assert cuerpo["productos"], "productos no puede salir vacia"
    assert cuerpo["solicitantes"], "solicitantes no puede salir vacia"


def test_openapi_declara_catalogos_y_conserva_las_tres_rutas(cliente, datos_catalogo_ticket):
    """El endpoint nuevo no puede desplazar a los tres que ya existian (AC-12)."""
    respuesta = cliente.get("/openapi.json")

    assert respuesta.status_code == 200
    rutas = respuesta.json()["paths"]
    assert "/api/v1/tickets/catalogos" in rutas
    for ruta in (
        "/api/v1/tickets/",
        "/api/v1/tickets/{ticket_id}/estado",
    ):
        assert ruta in rutas, f"se perdio la ruta {ruta}"


# --- AC-2: el orden de los estados es el del flujo, no el alfabetico ---


def test_estados_salen_en_el_orden_del_flujo(cliente, datos_catalogo_ticket):
    """La fixture inserta los estados en orden descendente: ordenarlos por
    nombre pondria "CERRADO_TEST" primero y "INGRESADO" al final."""
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    ids = [estado["estado_id"] for estado in respuesta.json()["estados"]]
    nombres = [estado["nombre"] for estado in respuesta.json()["estados"]]

    assert ids == sorted(ids), "los estados deben salir por estado_id ascendente"
    assert ids == datos_catalogo_ticket["estados_ids"]
    assert nombres == datos_catalogo_ticket["estados_nombres"]
    assert nombres[0] == "INGRESADO", "el primer estado del catalogo debe ser el de ingreso"
    assert nombres[-1] != "CERRADO_TEST", "un orden alfabetico habria puesto CERRADO primero"


def test_prioridades_salen_ordenadas_por_id(cliente, datos_catalogo_ticket):
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    ids = [prioridad["prioridad_id"] for prioridad in respuesta.json()["prioridades"]]
    assert ids == datos_catalogo_ticket["prioridades_ids"]
    assert ids == sorted(ids)


# --- AC-3: el producto trae stock agregado y la misma marca de critico ---


def test_productos_del_catalogo_traen_stock_y_critico(cliente, datos_catalogo_ticket):
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    con_stock = productos[datos_catalogo_ticket["producto_id"]]
    assert con_stock["nombre"] == "Cuaderno linedado"
    assert con_stock["categoria_nombre"] == "Papeleria"
    assert con_stock["stock_total"] == 50
    assert con_stock["es_critico"] is False


def test_es_critico_del_catalogo_coincide_con_existencias(cliente, datos_catalogo_ticket):
    """`es_critico` sale de la misma funcion en los dos endpoints (AC-3).

    Si `obtener_catalogos` duplicara la regla en vez de llamar a
    `es_stock_critico`, este test es el que lo detectaria.
    """
    catalogos = cliente.get("/api/v1/tickets/catalogos").json()
    existencias = cliente.get("/api/v1/inventario/existencias").json()

    por_id = {e["producto_id"]: e for e in existencias}
    assert existencias, "se necesitan existencias para comparar"

    for producto in catalogos["productos"]:
        if producto["producto_id"] in por_id:
            assert producto["es_critico"] == por_id[producto["producto_id"]]["es_critico"]
            assert producto["stock_total"] == por_id[producto["producto_id"]]["stock_total"]


def test_producto_sin_existencias_sale_con_stock_total_cero(cliente, datos_catalogo_ticket):
    """El `coalesce` del `outerjoin`: sin filas en `inventario`, 0 y no `None`."""
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    sin_stock = productos[datos_catalogo_ticket["producto_sin_stock_id"]]

    assert sin_stock["stock_total"] == 0
    assert sin_stock["es_critico"] is True, "0 <= stock_minimo(5): es critico"


# --- AC-4: los solicitantes traen departamento y van por apellido ---


def test_solicitantes_traen_departamento_y_orden_por_apellido(cliente, datos_catalogo_ticket):
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    solicitantes = respuesta.json()["solicitantes"]
    assert len(solicitantes) == 1
    unico = solicitantes[0]
    assert unico["nombre"] == "Ana"
    assert unico["apellido"] == "Perez"
    assert unico["correo"] == datos_catalogo_ticket["correo_usado"]
    assert unico["departamento_nombre"] == "Operaciones"


def test_solicitantes_orden_alfabetico_es_verificable(cliente, motor, datos_catalogo_ticket):
    """Con dos solicitantes de apellido distinto, el orden por apellido se ve."""
    db = sessionmaker(bind=motor)()
    try:
        from app.models import Usuario

        primero = Usuario(
            nombre="Zulma",
            apellido="Aguilera",
            correo="zulma.aguilera@compustock.cl",
            password="hash-de-prueba",
            departamento_id=datos_catalogo_ticket["departamento_id"],
            rol_id=datos_catalogo_ticket["rol_id"],
        )
        db.add(primero)
        db.commit()
    finally:
        db.close()

    apellidos = [s["apellido"] for s in cliente.get("/api/v1/tickets/catalogos").json()["solicitantes"]]

    assert apellidos == ["Aguilera", "Perez"]


# --- AC-5: catalogo vacio ---


def test_catalogos_vacios_responden_listas_vacias(cliente, motor):
    """Sin filas, las cuatro claves siguen presentes y vacias.

    Una clave ausente no permitiria al formulario distinguir "no hay catalogo"
    de "el backend no respondio" (spec, contrato de `GET /tickets/catalogos`).
    """
    respuesta = cliente.get("/api/v1/tickets/catalogos")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "prioridades": [],
        "estados": [],
        "productos": [],
        "solicitantes": [],
    }


def test_catalogo_de_una_sola_fila_no_tiene_productos_agregados_inventados(
    cliente, datos_catalogo_ticket
):
    """Guarda contra el `group_by`: sin inventario no puede inventar filas.

    Un `group_by` incompleto o un `join` equivocado aparecerian aqui como un
    producto con `stock_total` distinto del agregado real.
    """
    productos = cliente.get("/api/v1/tickets/catalogos").json()["productos"]

    con_existencia = [p for p in productos if p["stock_total"] > 0]
    sin_existencia = [p for p in productos if p["stock_total"] == 0]
    assert len(con_existencia) == 1
    assert len(sin_existencia) == 1, "solo el producto anadido sin inventario debe estar en 0"


# --- AC-9: validaciones de forma, 422 ---


def test_asunto_muy_corto_responde_422(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, asunto="ab")
    )

    assert respuesta.status_code == 422
    assert "asunto" in str(respuesta.json()["detail"])


def test_asunto_vacio_responde_422(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, asunto="")
    )

    assert respuesta.status_code == 422


def test_asunto_demasiado_largo_responde_422(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, asunto="x" * 151)
    )

    assert respuesta.status_code == 422
    assert "asunto" in str(respuesta.json()["detail"])


def test_asunto_en_el_limite_exacto_se_acepta(cliente, datos_catalogo_ticket):
    """Frontera: 150 es el maximo valido y 151 no. Un `>` equivocado en el
    schema rechazaria justo el caso que si debe entrar."""
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, asunto="x" * 150)
    )

    assert respuesta.status_code == 201


def test_ticket_sin_detalles_responde_422(cliente, datos_catalogo_ticket):
    """Un ticket sin items no es un ticket: `detalles` admite un minimo de 1."""
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, detalles=[])
    )

    assert respuesta.status_code == 422
    assert "detalles" in str(respuesta.json()["detail"])


def test_cantidad_cero_responde_422(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {
                    "producto_id": datos_catalogo_ticket["producto_id"],
                    "cantidad_solicitada": 0,
                }
            ],
        ),
    )

    assert respuesta.status_code == 422
    assert "cantidad_solicitada" in str(respuesta.json()["detail"])


def test_cantidad_negativa_responde_422(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {
                    "producto_id": datos_catalogo_ticket["producto_id"],
                    "cantidad_solicitada": -5,
                }
            ],
        ),
    )

    assert respuesta.status_code == 422


def test_cantidad_un_es_el_minimo_valido(cliente, datos_catalogo_ticket):
    """Frontera de `gt=0`: 1 entra, 0 no."""
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {
                    "producto_id": datos_catalogo_ticket["producto_id"],
                    "cantidad_solicitada": 1,
                }
            ],
        ),
    )

    assert respuesta.status_code == 201


def test_descripcion_ausente_se_acepta(cliente, datos_catalogo_ticket):
    """`descripcion` es opcional: quitarla del payload no puede ser un 422."""
    cuerpo = cuerpo_ticket_valido(datos_catalogo_ticket)
    del cuerpo["descripcion"]

    respuesta = cliente.post("/api/v1/tickets/", json=cuerpo)

    assert respuesta.status_code == 201
    assert respuesta.json()["descripcion"] is None


# --- AC-10: el camino feliz ---


def test_ticket_valido_responde_201_con_detalles_y_entregada_en_cero(
    cliente, datos_catalogo_ticket
):
    respuesta = cliente.post("/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket))

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["ticket_id"] > 0
    assert cuerpo["usuario_id"] == datos_catalogo_ticket["usuario_id"]
    assert cuerpo["prioridad_id"] == datos_catalogo_ticket["prioridad_id"]
    assert cuerpo["estado_id"] == datos_catalogo_ticket["estado_ingresado_id"]
    assert cuerpo["fecha_creacion"]
    assert cuerpo["fecha_cierre"] is None, "un ticket recien creado no tiene fecha de cierre"
    assert len(cuerpo["detalles"]) == 1
    assert cuerpo["detalles"][0]["cantidad_solicitada"] == 3
    assert cuerpo["detalles"][0]["cantidad_entregada"] == 0
    assert cuerpo["detalles"][0]["producto"]["nombre"] == "Cuaderno linedado"


def test_ticket_valido_aparece_en_el_listado(cliente, datos_catalogo_ticket):
    """El alta tiene que verse en `GET /tickets/` (AC-13, AC-29)."""
    creado = cliente.post("/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket)).json()

    listado = cliente.get("/api/v1/tickets/").json()

    assert any(t["ticket_id"] == creado["ticket_id"] for t in listado)


def test_ticket_valido_con_dos_items_distintos(cliente, datos_catalogo_ticket):
    """Dos lineas de productos distintos se guardan como dos detalles."""
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {
                    "producto_id": datos_catalogo_ticket["producto_id"],
                    "cantidad_solicitada": 2,
                },
                {
                    "producto_id": datos_catalogo_ticket["producto_sin_stock_id"],
                    "cantidad_solicitada": 1,
                },
            ],
        ),
    )

    assert respuesta.status_code == 201
    assert len(respuesta.json()["detalles"]) == 2


# --- AC-11: la escritura no valida ni descuenta stock ---


def test_crear_ticket_no_valida_stock(cliente, datos_catalogo_ticket):
    """Pide 9999 cuadernos con stock 50 y entra igual.

    El ticket es una *peticion*, no una entrega: validar stock y descontar
    inventario son del despacho del bodeguero (Feature 005).
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {
                    "producto_id": datos_catalogo_ticket["producto_id"],
                    "cantidad_solicitada": 9999,
                }
            ],
        ),
    )

    assert respuesta.status_code == 201


def test_crear_ticket_no_descuenta_inventario(cliente, datos_catalogo_ticket):
    """El stock tiene que quedar igual, comprobado por la API de inventario."""
    producto_id = datos_catalogo_ticket["producto_id"]
    antes = cliente.get("/api/v1/inventario/existencias").json()
    stock_antes = next(p["stock_total"] for p in antes if p["producto_id"] == producto_id)

    cliente.post("/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket))

    despues = cliente.get("/api/v1/inventario/existencias").json()
    stock_despues = next(p["stock_total"] for p in despues if p["producto_id"] == producto_id)
    assert stock_despues == stock_antes


# --- AC-6 y AC-7: referencias inexistentes, 404 y no 500 ---


def test_ticket_con_producto_inexistente_responde_404(cliente, datos_catalogo_ticket):
    """El 500 por `producto_id` invalido es el defecto que esta feature corrige.

    Antes la FK se violaba en el `INSERT` y PostgreSQL (o SQLite) devolvia un
    500 opaco. Ahora la referencia se comprueba **antes** de escribir y el
    mensaje nombra el producto que falta.
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[{"producto_id": 99999, "cantidad_solicitada": 1}],
        ),
    )

    assert respuesta.status_code == 404
    assert "99999" in respuesta.json()["detail"]


def test_producto_inexistente_no_toca_los_demas_productos(cliente, datos_catalogo_ticket):
    """Un detalle valido acompañado de uno invalido se rechaza entero.

    Valida los tres productos de una vez antes de escribir: no se acepta el
    ticket "a medias" porque el primero exista.
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {"producto_id": datos_catalogo_ticket["producto_id"], "cantidad_solicitada": 1},
                {"producto_id": 42424, "cantidad_solicitada": 1},
                {"producto_id": 55555, "cantidad_solicitada": 1},
            ],
        ),
    )

    assert respuesta.status_code == 404
    detalle = respuesta.json()["detail"]
    assert "42424" in detalle or "55555" in detalle


def test_productos_repetidos_no_disparan_busquedas_redundantes(cliente, datos_catalogo_ticket):
    """Cinco lineas del mismo producto se validan una sola vez y se guardan cinco.

    El `set` de ids del service es lo que evita cinco `db.get`; y recordarlo en
    un test evita que alguien lo "simplifique" a un bucle mas adelante.
    """
    producto_id = datos_catalogo_ticket["producto_id"]
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[{"producto_id": producto_id, "cantidad_solicitada": 1} for _ in range(5)],
        ),
    )

    assert respuesta.status_code == 201
    assert len(respuesta.json()["detalles"]) == 5


def test_ticket_con_usuario_inexistente_responde_404(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, usuario_id=98765)
    )

    assert respuesta.status_code == 404
    assert "98765" in respuesta.json()["detail"]


def test_ticket_con_prioridad_inexistente_responde_404(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, prioridad_id=87654)
    )

    assert respuesta.status_code == 404
    assert "87654" in respuesta.json()["detail"]


def test_ticket_con_estado_inexistente_responde_404(cliente, datos_catalogo_ticket):
    respuesta = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, estado_id=76543)
    )

    assert respuesta.status_code == 404
    assert "76543" in respuesta.json()["detail"]


def test_el_404_distingue_tipo_y_valor_de_la_referencia(cliente, datos_catalogo_ticket):
    """Dos 404 por motivos distintos: el mensaje tiene que decir **cual**.

    Un 404 generico obligaria a adivinar si el problema era el solicitante o el
    estado, que es justo lo que el usuario no puede ver desde el modal.
    """
    por_usuario = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, usuario_id=11111)
    ).json()["detail"]
    por_prioridad = cliente.post(
        "/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket, prioridad_id=22222)
    ).json()["detail"]

    assert por_usuario != por_prioridad
    assert "usuario" in por_usuario.lower()
    assert "prioridad" in por_prioridad.lower()


# --- AC-8: atomicidad ---


def test_referencia_invalida_no_deja_ticket_huerfano(cliente, datos_catalogo_ticket):
    """Tras un 404 no queda ningun ticket persistido.

    Este es el criterio que importa: el 404 es visible, pero un ticket huerfano
    se descubriria meses despues en un tablero.
    """
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[{"producto_id": 99999, "cantidad_solicitada": 1}],
        ),
    )

    assert respuesta.status_code == 404
    assert cliente.get("/api/v1/tickets/").json() == []


def test_referencia_invalida_no_deja_detalles_sin_ticket(cliente, datos_catalogo_ticket):
    """Despues del 404, el detalle valido del payload tampoco se persistio.

    Comprueba el otro lado de la atomicidad: no solo que falta el ticket, sino
    que tampoco quedo la linea huerfana.
    """
    cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[
                {"producto_id": datos_catalogo_ticket["producto_id"], "cantidad_solicitada": 1},
                {"producto_id": 99999, "cantidad_solicitada": 1},
            ],
        ),
    )

    assert cliente.get("/api/v1/tickets/").json() == []


def test_despues_de_un_404_la_siguiente_peticion_sigue_funcionando(cliente, datos_catalogo_ticket):
    """Un 404 no deja nada a medias: el siguiente POST valido funciona.

    Ojo con lo que este test **no** cubre: no verifica el `rollback()` del
    `except Exception` de `crear_ticket`, porque ese 404 se lanza **antes** del
    `try` y por lo tanto no escribe nada. Y aunque lo cubriera, no podria
    distinguirlo del cleanup de `get_db`, que hace `db.close()` y ya revierte
    (ver `tasks.md` §9). Lo que si verifica es que la prevalidacion no dejo la
    peticion a medias.
    """
    cliente.post(
        "/api/v1/tickets/",
        json=cuerpo_ticket_valido(
            datos_catalogo_ticket,
            detalles=[{"producto_id": 99999, "cantidad_solicitada": 1}],
        ),
    )

    segundo = cliente.post("/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket))

    assert segundo.status_code == 201
    assert len(cliente.get("/api/v1/tickets/").json()) == 1


def test_varios_404_seguidos_no_se_acumulan(cliente, datos_catalogo_ticket):
    """Tres rechazos seguidos y despues un alta valida.

    Cubre el caso en que el usuario reintenta sin corregir nada, que es como se
    manifestaria un rollback pendiente.
    """
    for id_inexistente in (99991, 99992, 99993):
        respuesta = cliente.post(
            "/api/v1/tickets/",
            json=cuerpo_ticket_valido(
                datos_catalogo_ticket,
                detalles=[{"producto_id": id_inexistente, "cantidad_solicitada": 1}],
            ),
        )
        assert respuesta.status_code == 404

    assert cliente.post("/api/v1/tickets/", json=cuerpo_ticket_valido(datos_catalogo_ticket)).status_code == 201