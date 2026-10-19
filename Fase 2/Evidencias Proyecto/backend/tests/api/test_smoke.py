"""AC-7: los endpoints de la API responden correctamente tras la
reestructuracion (Feature 001, Fase C). La清单 de lectura incluye
`/inventario/existencias` desde la Feature 002.

Se verifica el seam HTTP completo, incluidas las rutas de error, porque una
extraccion de servicios que rompe un `HTTPException` sigue pareciendo sana si
solo se prueban los casos felices.
"""

import pytest

from ._soporte_sede_011 import asegurar_sede_de_departamento


@pytest.fixture(autouse=True)
def _sede_del_departamento(motor, datos_base):
    """Feature 011 (T9): el alta de ticket exige sede en el departamento.

    El smoke crea tickets sobre `datos_base`; desde T9 el departamento debe tener
    una sede asignada, asi que se siembra la precondicion para toda la suite.
    """
    asegurar_sede_de_departamento(motor, datos_base)


def _crear_usuario(datos_base):
    return {
        "nombre": "Carlos",
        "apellido": "Munoz",
        "correo": "carlos.munoz@compustock.cl",
        "departamento_id": datos_base["departamento_id"],
        # La identidad legacy es Administrador (Feature 008): solo puede asignar
        # Bodeguero/Solicitante (D-6/AC-10). El rol "Administrador" de `datos_base`
        # queda reservado a los casos de la regla de rol asignable.
        "rol_id": datos_base["rol_bodeguero_id"],
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


def test_actualizar_estado_ticket_hacia_cerrado_responde_409(cliente, datos_base):
    """Ajustado por la enmienda D-4 de la 013 (AC-26): el cierre por `PATCH`
    ya no existe en **ningun** catalogo.

    Este smoke cerraba el ticket con `INGRESADO → CERRADO` = 200; con la
    terminalidad por nombre, el unico camino a `Cerrado` es el despacho
    transaccional de la 005, de modo que esa misma peticion responde hoy 409
    con su detalle literal y sin tocar el ticket. El flujo lineal entre
    estados operativos sigue respondiendo 200 (verificado en el modulo de la
    004)."""
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
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == (
        "El cierre requiere despacho; use "
        f"POST /api/v1/tickets/{creado['ticket_id']}/despacho"
    )
    tickets = cliente.get("/api/v1/tickets/").json()
    ticket = next(t for t in tickets if t["ticket_id"] == creado["ticket_id"])
    assert ticket["estado_id"] == datos_base["estado_ingresado_id"], (
        "el 409 no puede mover el ticket"
    )
    assert ticket["fecha_cierre"] is None, "el PATCH no sella cierre"


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
