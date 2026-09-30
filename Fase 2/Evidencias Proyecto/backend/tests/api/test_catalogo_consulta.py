"""Feature 002: consulta de existencias del catálogo y calidad de los listados.

El seam bajo prueba es la **interfaz HTTP** (`TestClient`), igual que en la suite de
la Feature 001: ninguna asercion consulta la base directamente y ningun test importa
`app.services`, asi que sobreviven a un refactor del service.

`datos_catalogo` se apoya en `datos_base` en vez de reemplazarlo, para no cambiar la
forma que consumen los 25 casos de la suite anterior.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.models import Categoria, Departamento, Inventario, Producto

RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"
RUTA_CATEGORIAS = "/api/v1/inventario/categorias"
RUTA_PRODUCTOS = "/api/v1/inventario/productos"
RUTA_STOCK = "/api/v1/inventario/stock"


@pytest.fixture
def datos_catalogo(motor, datos_base):
    """Amplia `datos_base` con los casos borde de la consulta de existencias.

    | Insumo                | Categoria | Min | Existencias                 | Para qué                        |
    |-----------------------|-----------|-----|-----------------------------|---------------------------------|
    | Cuaderno linedado     | Papeleria |  10 | Operaciones 50              | caso normal + match por descripcion |
    | Resma Carta 75g       | Papeleria |  20 | Operaciones 120, Bodega 30  | multi-sede: 1 producto, 2 sedes  |
    | Toner HP 26A          | Toner     |  10 | Bodega 3                    | critico                         |
    | Grapadora Estandar    | Toner     |   5 | ninguna                     | `sedes` vacio (spec D-4)         |
    | Boligrota Bic Cristal | Papeleria |  30 | Operaciones 30              | frontera `30 <= 30` (spec D-5)  |

    Sin ids fijos: los de `datos_base` y los que genera esta sesion. La unica
    excepcion es `institucion_id="INST01"`, que es un `VARCHAR` y no una secuencia.
    """
    db = sessionmaker(bind=motor)()
    try:
        categoria_toner = Categoria(
            nombre_cat="Toner y Cartuchos", descripcion_cat="Consumibles de impresion"
        )
        db.add(categoria_toner)
        db.flush()

        departamento_bodega = Departamento(
            nombre_dep="Bodega",
            descripcion="Deposito central",
            institucion_id="INST01",
        )
        db.add(departamento_bodega)
        db.flush()

        def nuevo_producto(nombre, descripcion, unidad, minimo, categoria_id):
            producto = Producto(
                nombre=nombre,
                descripcion=descripcion,
                unidad_medida=unidad,
                stock_minimo=minimo,
                categoria_id=categoria_id,
            )
            db.add(producto)
            db.flush()
            return producto

        def nueva_existencia(producto_id, stock, ubicacion, departamento_id):
            inventario = Inventario(
                stock_actual=stock,
                ubicacion=ubicacion,
                departamento_id=departamento_id,
                producto_id=producto_id,
            )
            db.add(inventario)
            db.flush()
            return inventario

        # Multi-sede: el mismo producto en dos departamentos.
        resma = nuevo_producto(
            "Resma Carta 75g",
            "Resma de 500 hojas tamano carta",
            "RESMA",
            20,
            datos_base["categoria_id"],
        )
        nueva_existencia(resma.producto_id, 120, "Bodega Central - A1", datos_base["departamento_id"])
        nueva_existencia(resma.producto_id, 30, "Bodega Central - A2", departamento_bodega.departamento_id)

        # Critico: 3 < 10.
        toner = nuevo_producto(
            "Toner HP 26A", "Cartucho negro HP26A", "UNIDAD", 10, categoria_toner.categoria_id
        )
        nueva_existencia(toner.producto_id, 3, "Bodega Central - B1", departamento_bodega.departamento_id)

        # Sin ninguna existencia: debe seguir apareciendo en el catalogo.
        nuevo_producto(
            "Grapadora Estandar", "Grapadora de escritorio 24/6", "UNIDAD", 5, categoria_toner.categoria_id
        )

        # Frontera: 30 <= 30, asi que es critico.
        boligrota = nuevo_producto(
            "Boligrota Bic Cristal", "Punta fina color negro", "UNIDAD", 30, datos_base["categoria_id"]
        )
        nueva_existencia(boligrota.producto_id, 30, "Bodega Central - C1", datos_base["departamento_id"])

        ids = {
            "categoria_toner_id": categoria_toner.categoria_id,
            "departamento_bodega_id": departamento_bodega.departamento_id,
            "producto_resma_id": resma.producto_id,
            "producto_toner_id": toner.producto_id,
            "producto_boligrota_id": boligrota.producto_id,
        }
        db.commit()
        return {**datos_base, **ids}
    finally:
        db.close()


# --- Helpers de lectura por el seam HTTP -------------------------------------


def _obtener(cliente, **parametros):
    respuesta = cliente.get(RUTA_EXISTENCIAS, params=parametros)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _por_id(existencias, producto_id):
    return next(existencia for existencia in existencias if existencia["producto_id"] == producto_id)


def _crear_producto(cliente, nombre, categoria_id):
    return cliente.post(
        RUTA_PRODUCTOS,
        json={
            "nombre": nombre,
            "descripcion": None,
            "unidad_medida": "UNIDAD",
            "stock_minimo": 1,
            "categoria_id": categoria_id,
        },
    )


# --- AC-1: la ruta existe y responde ------------------------------------------


def test_existencias_responde_200(cliente, datos_catalogo):
    existencias = _obtener(cliente)
    assert len(existencias) == 5
    assert len({existencia["nombre"] for existencia in existencias}) == 5


def test_openapi_declara_la_ruta_nueva_y_conserva_las_viejas(cliente):
    esquema = cliente.get("/openapi.json").json()

    assert RUTA_EXISTENCIAS in esquema["paths"]
    operacion = esquema["paths"][RUTA_EXISTENCIAS]["get"]
    esquema_respuesta = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema_respuesta["items"]["$ref"].endswith("ProductoExistenciaRespuesta")

    # Las rutas de inventario previas no desaparecen ni cambian de metodo.
    for ruta in (RUTA_CATEGORIAS, RUTA_PRODUCTOS, RUTA_STOCK, "/api/v1/inventario/movimientos"):
        assert set(esquema["paths"][ruta]) <= {"get", "post"}, ruta


# --- AC-2 a AC-4: forma de la respuesta --------------------------------------


def test_existencia_expone_categoria_y_sedes(cliente, datos_catalogo):
    for existencia in _obtener(cliente):
        assert existencia["categoria_nombre"]
        for sede in existencia["sedes"]:
            assert sede["departamento_nombre"] in {"Operaciones", "Bodega"}

    resma = _por_id(_obtener(cliente), datos_catalogo["producto_resma_id"])
    assert resma["categoria_nombre"] == "Papeleria"
    assert {sede["ubicacion"] for sede in resma["sedes"]} == {
        "Bodega Central - A1",
        "Bodega Central - A2",
    }


def test_producto_multi_sede_aparece_una_sola_vez(cliente, datos_catalogo):
    """Un producto en N sedes es UN elemento, no N filas (spec D-2, D-4)."""
    existencias = _obtener(cliente)
    apariciones = [e for e in existencias if e["producto_id"] == datos_catalogo["producto_resma_id"]]

    assert len(apariciones) == 1
    assert len(apariciones[0]["sedes"]) == 2
    assert apariciones[0]["stock_total"] == 150
    assert sum(sede["stock_actual"] for sede in apariciones[0]["sedes"]) == 150


def test_producto_sin_inventario_aparece_con_stock_cero(cliente, datos_catalogo):
    """Un insumo agotado no puede desaparecer del catalogo (spec D-4)."""
    existencias = _obtener(cliente)
    grapadora = next(e for e in existencias if e["nombre"] == "Grapadora Estandar")

    assert grapadora["sedes"] == []
    assert grapadora["stock_total"] == 0
    assert grapadora["es_critico"] is True


# --- AC-5 a AC-8: los cuatro filtros -----------------------------------------


def test_busqueda_por_texto_ignora_mayusculas(cliente, datos_catalogo):
    assert [e["nombre"] for e in _obtener(cliente, q="RESMA")] == ["Resma Carta 75g"]
    # El mismo producto, ahora por su descripcion.
    assert [e["nombre"] for e in _obtener(cliente, q="500 hojas")] == ["Resma Carta 75g"]
    assert _obtener(cliente, q="zzzz") == []


def test_filtro_por_categoria(cliente, datos_catalogo):
    toner = _obtener(cliente, categoria_id=datos_catalogo["categoria_toner_id"])
    assert {existencia["nombre"] for existencia in toner} == {"Toner HP 26A", "Grapadora Estandar"}
    assert all(e["categoria_id"] == datos_catalogo["categoria_toner_id"] for e in toner)

    # Una categoria que no existe no es un error: es un catalogo vacio.
    assert _obtener(cliente, categoria_id=999999) == []


def test_filtro_por_departamento_acota_sedes_y_total(cliente, datos_catalogo):
    solo_bodega = _obtener(cliente, departamento_id=datos_catalogo["departamento_bodega_id"])

    resma = _por_id(solo_bodega, datos_catalogo["producto_resma_id"])
    assert [sede["departamento_nombre"] for sede in resma["sedes"]] == ["Bodega"]
    # `stock_total` deja de sumar la sede que se filtro (spec D-4).
    assert resma["stock_total"] == 30

    # El cuaderno solo vive en Operaciones, asi que no aparece.
    ids_visibles = {existencia["producto_id"] for existencia in solo_bodega}
    assert datos_catalogo["producto_id"] not in ids_visibles


def test_filtro_solo_criticos(cliente, datos_catalogo):
    criticos = _obtener(cliente, solo_criticos="true")

    assert criticos
    assert all(existencia["es_critico"] is True for existencia in criticos)
    assert {existencia["nombre"] for existencia in criticos} == {
        "Toner HP 26A",
        "Grapadora Estandar",
        "Boligrota Bic Cristal",
    }


# --- AC-9, D-5: la regla de stock critico ------------------------------------


def test_stock_en_el_limite_minimo_es_critico(cliente, datos_catalogo):
    """La regla es `stock <= stock_minimo` (spec D-5), no `<`."""
    boligrota = _por_id(_obtener(cliente), datos_catalogo["producto_boligrota_id"])

    assert boligrota["stock_total"] == 30
    assert boligrota["stock_minimo"] == 30
    assert boligrota["es_critico"] is True


# --- AC-10: orden determinista -----------------------------------------------


def test_orden_es_determinista(cliente, datos_catalogo):
    primera = [e["producto_id"] for e in _obtener(cliente)]
    segunda = [e["producto_id"] for e in _obtener(cliente)]

    assert primera == segunda
    nombres = [existencia["nombre"] for existencia in _obtener(cliente)]
    assert nombres == sorted(nombres)


def test_sedes_vienen_ordenadas_por_departamento(cliente, datos_catalogo):
    resma = _por_id(_obtener(cliente), datos_catalogo["producto_resma_id"])
    nombres = [sede["departamento_nombre"] for sede in resma["sedes"]]

    assert nombres == sorted(nombres) == ["Bodega", "Operaciones"]


# --- Constitucion: la consulta es de solo lectura ----------------------------


def test_consultar_existencias_no_altera_el_stock(cliente, datos_catalogo):
    antes = cliente.get(RUTA_STOCK).json()

    _obtener(cliente)
    _obtener(cliente, q="resma", solo_criticos="true")
    _obtener(cliente, departamento_id=datos_catalogo["departamento_bodega_id"])

    assert cliente.get(RUTA_STOCK).json() == antes


# --- AC-12, AC-15: las rutas que ya existian --------------------------------


def test_listados_existentes_conservan_su_json_con_orden_determinista(cliente, datos_catalogo):
    """El unico cambio en estas tres rutas es que el orden deja de ser indefinido."""
    categorias = cliente.get(RUTA_CATEGORIAS).json()
    assert set(categorias[0]) == {"categoria_id", "nombre_cat", "descripcion_cat"}
    assert [c["nombre_cat"] for c in categorias] == sorted(c["nombre_cat"] for c in categorias)

    productos = cliente.get(RUTA_PRODUCTOS).json()
    assert set(productos[0]) == {
        "producto_id",
        "nombre",
        "descripcion",
        "unidad_medida",
        "stock_minimo",
        "categoria_id",
        "categoria",
    }
    assert [p["nombre"] for p in productos] == sorted(p["nombre"] for p in productos)

    stock = cliente.get(RUTA_STOCK).json()
    assert set(stock[0]) == {
        "inventario_id",
        "stock_actual",
        "ubicacion",
        "departamento_id",
        "producto_id",
        "producto",
    }
    assert [s["inventario_id"] for s in stock] == sorted(s["inventario_id"] for s in stock)


def test_listar_productos_evita_consultas_n_mas_uno(motor, cliente, datos_catalogo):
    """Con 5 productos debe haber 1 consulta a producto y 1 a categoria, no 6 (AC-15)."""
    sentencias = []

    def contar(_conexion, _cursor, statement, _parametros, _contexto, _executemany):
        # SQLAlchemy parte el SQL en varias lineas, asi que se colapsan los
        # espacios: " from producto" entonces no matchea un `join producto`.
        sentencias.append(" ".join(statement.lower().split()))

    event.listen(motor, "before_cursor_execute", contar)
    try:
        respuesta = cliente.get(RUTA_PRODUCTOS)
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    assert respuesta.status_code == 200, respuesta.text
    assert len([s for s in sentencias if " from producto" in s]) == 1, sentencias
    assert len([s for s in sentencias if " from categoria" in s]) == 1, sentencias


# --- AC-11: H-1 acotado en crear_producto ------------------------------------


def test_crear_producto_con_categoria_inexistente_responde_404(cliente, datos_catalogo):
    """Una FK invalida es un 4xx con mensaje, no un 500 (spec D-8)."""
    respuesta = _crear_producto(cliente, "Producto sin categoria", 999999)

    assert respuesta.status_code == 404, respuesta.text
    assert "categoria" in respuesta.json()["detail"]
    # Y no se crea a medias.
    nombres = [p["nombre"] for p in cliente.get(RUTA_PRODUCTOS).json()]
    assert "Producto sin categoria" not in nombres


def test_crear_producto_con_categoria_valida_sigue_creando(cliente, datos_catalogo):
    """Regresion: el camino feliz de POST /productos no se rompio con el 404."""
    respuesta = _crear_producto(cliente, "Resma bond", datos_catalogo["categoria_id"])

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "Resma bond"
    assert cuerpo["categoria"]["categoria_id"] == datos_catalogo["categoria_id"]

    # Y el producto recien creado ya aparece en la consulta de existencias, sin stock.
    nuevo = next(e for e in _obtener(cliente) if e["nombre"] == "Resma bond")
    assert nuevo["sedes"] == []
    assert nuevo["stock_total"] == 0
