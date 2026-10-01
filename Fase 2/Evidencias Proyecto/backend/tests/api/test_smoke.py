"""AC-7: los endpoints de la API responden correctamente tras la
reestructuracion (Feature 001, Fase C). La清单 de lectura incluye
`/inventario/existencias` desde la Feature 002.

Se verifica el seam HTTP completo, incluidas las rutas de error, porque una
extraccion de servicios que rompe un `HTTPException` sigue pareciendo sana si
solo se prueban los casos felices.
"""

import pytest


def _crear_usuario(datos_base):
    return {
        "nombre": "Carlos",
        "apellido": "Munoz",
        "correo": "carlos.munoz@compustock.cl",
        "password": "hash-de-prueba",
        "departamento_id": datos_base["departamento_id"],
        "rol_id": datos_base["rol_id"],
    }


CASOS_LECTURA = [
    ("raiz", "GET", "/", 200),
    ("salud", "GET", "/health", 200),
    ("usuarios", "GET", "/api/v1/usuarios/", 200),
    ("roles", "GET", "/api/v1/usuarios/roles", 200),
    ("departamentos", "GET", "/api/v1/usuarios/departamentos", 200),
    ("instituciones", "GET", "/api/v1/usuarios/instituciones", 200),
    ("categorias", "GET", "/api/v1/inventario/categorias", 200),
    ("productos", "GET", "/api/v1/inventario/productos", 200),
    ("stock", "GET", "/api/v1/inventario/stock", 200),
    ("existencias", "GET", "/api/v1/inventario/existencias", 200),
    ("tickets", "GET", "/api/v1/tickets/", 200),
]


@pytest.mark.parametrize("nombre", [caso[0] for caso in CASOS_LECTURA])
def test_endpoint_de_lectura_responde(cliente, datos_base, nombre):
    """Las 11 operaciones GET responden 200 con el catalogo sembrado."""
    _, metodo, ruta, esperado = next(caso for caso in CASOS_LECTURA if caso[0] == nombre)
    respuesta = cliente.request(metodo, ruta)
    assert respuesta.status_code == esperado, respuesta.text
    assert respuesta.json() is not None


def test_crear_usuario_responde_201(cliente, datos_base):
    respuesta = cliente.post("/api/v1/usuarios/", json=_crear_usuario(datos_base))
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["correo"] == "carlos.munoz@compustock.cl"
    assert cuerpo["nombre"] == "Carlos"


def test_crear_usuario_con_correo_duplicado_responde_400(cliente, datos_base):
    """Regla de negocio que hoy vivia dentro del endpoint y ahora en el servicio."""
    nuevo = {**_crear_usuario(datos_base), "correo": "unicamente.nuevo@compustock.cl"}
    assert cliente.post("/api/v1/usuarios/", json=nuevo).status_code == 201

    duplicado = cliente.post("/api/v1/usuarios/", json={**nuevo, "nombre": "Otro"})
    assert duplicado.status_code == 400, duplicado.text


def test_crear_usuario_con_correo_invalido_responde_422(cliente, datos_base):
    """`EmailStr` de Pydantic v2 debe seguir rechazando correos mal formados."""
    respuesta = cliente.post(
        "/api/v1/usuarios/",
        json={**_crear_usuario(datos_base), "correo": "no-es-un-correo"},
    )
    assert respuesta.status_code == 422, respuesta.text


def test_crear_producto_responde_201(cliente, datos_base):
    respuesta = cliente.post(
        "/api/v1/inventario/productos",
        json={
            "nombre": "Resma de papel bond",
            "descripcion": "Resma 500 hojas",
            "unidad_medida": "RESMA",
            "stock_minimo": 3,
            "categoria_id": datos_base["categoria_id"],
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["nombre"] == "Resma de papel bond"


def test_registrar_movimiento_responde_201(cliente, datos_base):
    respuesta = cliente.post(
        "/api/v1/inventario/movimientos",
        json={
            "tipo_movimiento": "ENTRADA",
            "cantidad": 25,
            "observacion": "Recepcion de mercaderia",
            "inventario_id": datos_base["inventario_id"],
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    # 50 iniciales + 25 de entrada.
    assert respuesta.json()["nuevo_stock"] == 75


def test_crear_ticket_responde_201(cliente, datos_base):
    respuesta = cliente.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos_base["usuario_id"],
            "prioridad_id": datos_base["prioridad_id"],
            "estado_id": datos_base["estado_ingresado_id"],
            "asunto": "Falta de cuadernos en bodega",
            "descripcion": "Se requieren 12 unidades para el trimestre.",
            "detalles": [{"producto_id": datos_base["producto_id"], "cantidad_solicitada": 12}],
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["asunto"] == "Falta de cuadernos en bodega"
    assert len(cuerpo["detalles"]) == 1
    assert cuerpo["detalles"][0]["cantidad_solicitada"] == 12


def test_actualizar_estado_ticket_responde_200(cliente, datos_base):
    """Cierra el ticket usando el id real de CERRADO, no una constante fija."""
    creado = cliente.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos_base["usuario_id"],
            "prioridad_id": datos_base["prioridad_id"],
            "estado_id": datos_base["estado_ingresado_id"],
            "asunto": "Ticket a cerrar",
            "detalles": [{"producto_id": datos_base["producto_id"], "cantidad_solicitada": 1}],
        },
    ).json()

    respuesta = cliente.patch(
        f"/api/v1/tickets/{creado['ticket_id']}/estado",
        json={"estado_id": datos_base["estado_cerrado_id"]},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == datos_base["estado_cerrado_id"]


def test_actualizar_estado_de_ticket_inexistente_responde_404(cliente, datos_base):
    respuesta = cliente.patch(
        "/api/v1/tickets/999999/estado",
        json={"estado_id": datos_base["estado_cerrado_id"]},
    )
    assert respuesta.status_code == 404, respuesta.text


def test_ticket_con_producto_inexistente_responde_404(cliente_sin_excepcion, datos_base):
    """Regresion de un defecto PREEXISTENTE que la Feature 001 documento.

    `crear_ticket` no capturaba el `IntegrityError` de un `producto_id` que no
    existe y FastAPI respondia 500. Este test fijaba ese 500 como
    comportamiento esperado, con un docstring que decia "cuando se corrija,
    este test debe pasar a 400".

    La Feature 003 lo corrige: las referencias se comprueban antes de escribir,
    asi que ahora es un 404 que nombra el producto. Se mantiene el test porque
    la asercion es la que vigila el defecto, y `cliente_sin_excepcion` sigue
    pniendo que si algo vuelve a reventar por debajo, se veria.
    """
    respuesta = cliente_sin_excepcion.post(
        "/api/v1/tickets/",
        json={
            "usuario_id": datos_base["usuario_id"],
            "prioridad_id": datos_base["prioridad_id"],
            "estado_id": datos_base["estado_ingresado_id"],
            "asunto": "Producto inexistente",
            "detalles": [{"producto_id": 999999, "cantidad_solicitada": 1}],
        },
    )
    assert respuesta.status_code == 404, respuesta.text
    assert "999999" in respuesta.json()["detail"]
