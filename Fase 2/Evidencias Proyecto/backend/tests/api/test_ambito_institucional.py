"""T3 (Feature 007): ambito institucional en servicios de usuarios e inventario.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`). Se siembran
**dos instituciones** (una propia y una ajena) con departamentos, usuarios,
inventario, catalogo y movimientos propios, y se observa, por rol, que:

  * Administrador/Bodeguero/Solicitante solo ven y operan datos de su institucion
    (derivada de `usuario.departamento_id -> departamento.institucion_id`, D-4).
  * `departamento_id` de otra institucion en `/inventario/existencias` responde
    403 (no se filtra en silencio); un `sede_id` ajeno o distinto en
    `/inventario/stock` responde 404 (Feature 011, AC-3/AC-7).
  * Una identidad limitada sin institucion resoluble responde 403; nunca obtiene
    alcance global.
  * Superadmin conserva alcance global.
  * El catalogo de categoria/producto deja de ser global en 008 (D-1): el rol
    limitado solo recibe los registros de su institucion, y el acceso por objeto
    a un registro ajeno se oculta con 404.

Fuera de alcance de T3 (lo cubre T4): el filtro del catalogo de solicitantes de
`GET /tickets/catalogos` y la propiedad de tickets. Esta suite no los toca.
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
    Institucion,
    Inventario,
    MovimientoInventario,
    Producto,
    Rol,
    Sede,
    StockSede,
    Usuario,
)
from app.services.auth_service import IdentidadAutenticada

RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"
RUTA_STOCK = "/api/v1/inventario/stock"
RUTA_MOVIMIENTOS = "/api/v1/inventario/movimientos"
RUTA_CATEGORIAS = "/api/v1/inventario/categorias"
RUTA_PRODUCTOS = "/api/v1/inventario/productos"
RUTA_USUARIOS = "/api/v1/usuarios/"
RUTA_DEPARTAMENTOS = "/api/v1/usuarios/departamentos"
RUTA_INSTITUCIONES = "/api/v1/usuarios/instituciones"
RUTA_ROLES = "/api/v1/usuarios/roles"


# ---------------------------------------------------------------------------
# Sembrado de dos instituciones
# ---------------------------------------------------------------------------


@pytest.fixture
def ambito(motor, datos_base):
    """`datos_base` (institucion INST01) + una institucion ajena INST02 completa.

    INST01 (propia): la institucion/departamento/usuario/producto/inventario de
    `datos_base` ("Operaciones", inventario 50 del "Cuaderno linedado").

    INST02 (ajena): institucion, departamento "Bodega Sur", usuario persistido,
    inventario 7 del mismo producto, un producto y categoria propios, y sendos
    movimientos (propio y ajeno) para aislar el historial.
    """
    db = sessionmaker(bind=motor)()
    try:
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
            institucion_id=institucion_ajena.institucion_id,
        )
        db.add(departamento_ajeno)
        db.flush()

        usuario_ajeno = Usuario(
            nombre="Beto",
            apellido="Ajeno",
            correo="beto.ajeno@compustock.cl",
            departamento_id=departamento_ajeno.departamento_id,
            rol_id=datos_base["rol_id"],
        )
        db.add(usuario_ajeno)
        db.flush()

        # Feature 008 (D-1/D-2): el catalogo es institucional. INST02 tiene su
        # propio producto, y su inventario solo puede referenciar ese producto.
        categoria_ajena = Categoria(
            nombre_cat="Solo Ajeno",
            descripcion_cat="Catalogo de la institucion ajena",
            institucion_id="INST02",
        )
        db.add(categoria_ajena)
        db.flush()

        producto_ajeno = Producto(
            nombre="Insumo Ajeno",
            descripcion="Producto de la institucion ajena",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=categoria_ajena.categoria_id,
            institucion_id="INST02",
        )
        db.add(producto_ajeno)
        db.flush()

        inventario_ajeno = Inventario(
            stock_actual=7,
            ubicacion="Bodega Sur - S1",
            departamento_id=departamento_ajeno.departamento_id,
            producto_id=producto_ajeno.producto_id,
            institucion_id="INST02",
        )
        db.add(inventario_ajeno)
        db.flush()

        movimiento_ajeno = MovimientoInventario(
            tipo_movimiento="ENTRADA",
            cantidad=7,
            observacion="Ingreso ajeno",
            inventario_id=inventario_ajeno.inventario_id,
        )
        db.add(movimiento_ajeno)

        movimiento_propio = MovimientoInventario(
            tipo_movimiento="ENTRADA",
            cantidad=50,
            observacion="Ingreso propio",
            inventario_id=datos_base["inventario_id"],
        )
        db.add(movimiento_propio)

        # Feature 011 (T8): el saldo vigente vive por sede (`stock_sede`), no en
        # `inventario`. Se siembra una sede por institucion con el saldo del
        # producto, y se asigna cada departamento a su sede para resolver el
        # ambito operativo (Solicitante/Bodeguero).
        sede_propia = Sede(nombre="Operaciones", institucion_id="INST01")
        sede_ajena = Sede(nombre="Bodega Sur", institucion_id="INST02")
        db.add_all([sede_propia, sede_ajena])
        db.flush()
        departamento_propio = db.get(Departamento, datos_base["departamento_id"])
        departamento_propio.sede_id = sede_propia.sede_id
        departamento_ajeno.sede_id = sede_ajena.sede_id
        db.add_all(
            [
                StockSede(
                    sede_id=sede_propia.sede_id,
                    producto_id=datos_base["producto_id"],
                    stock_actual=50,
                    institucion_id="INST01",
                ),
                StockSede(
                    sede_id=sede_ajena.sede_id,
                    producto_id=producto_ajeno.producto_id,
                    stock_actual=7,
                    institucion_id="INST02",
                ),
            ]
        )
        db.commit()

        return {
            **datos_base,
            "inst_propia": "INST01",
            "inst_ajena": "INST02",
            "dep_ajeno_id": departamento_ajeno.departamento_id,
            "usuario_ajeno_id": usuario_ajeno.usuario_id,
            "inventario_ajeno_id": inventario_ajeno.inventario_id,
            "movimiento_ajeno_id": movimiento_ajeno.movimiento_id,
            "movimiento_propio_id": movimiento_propio.movimiento_id,
            "categoria_ajena_id": categoria_ajena.categoria_id,
            "producto_ajeno_id": producto_ajeno.producto_id,
            "sede_propia_id": sede_propia.sede_id,
            "sede_ajena_id": sede_ajena.sede_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers: identidad por rol/instituicion y cliente real
# ---------------------------------------------------------------------------


#: Centinela: identidad con `departamento_id=None` (institucion no resoluble).
_SIN_DEPARTAMENTO = object()


def _identidad(rol: str, departamento_id, sede_id=None) -> IdentidadAutenticada:
    """Identidad autenticada con el rol y el departamento dados.

    El usuario no se persiste: la derivacion institucional lee
    `usuario.departamento_id` y resuelve el `departamento` por ORM; la
    autorizacion solo lee `usuario.rol.nombre_rol`. Feature 011 (T8): `sede_id`
    puebla `usuario.sede_id` para resolver el ambito del Bodeguero.
    """
    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="Ambito",
        correo="sonda.ambito@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    if sede_id is not None:
        usuario.sede_id = sede_id
    return IdentidadAutenticada(usuario=usuario, sub="sub-ambito")


@contextmanager
def _cliente(motor, rol: str, departamento_id, sede_id=None):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    dep = None if departamento_id is _SIN_DEPARTAMENTO else departamento_id
    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = (
        lambda: _identidad(rol, dep, sede_id)
    )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _existencia(existencias, producto_id):
    return next(e for e in existencias if e["producto_id"] == producto_id)


def _stock_inventario_legado(motor, inventario_id: int) -> int:
    """Saldo de una fila legada de `inventario`, leido por ORM.

    Feature 011 (B1): `GET /inventario/stock` ya no expone el inventario
    departamental legado; los casos de movimiento legado observan su fila directa.
    """
    with sessionmaker(bind=motor)() as db:
        return db.get(Inventario, inventario_id).stock_actual


# ---------------------------------------------------------------------------
# Existencias: existencias/stock propios, catalogo global
# ---------------------------------------------------------------------------


def test_administrador_existencias_acota_a_su_institucion(motor, ambito):
    """El Administrador solo ve el stock de su institucion, no el de INST02.

    Feature 011 (T8): el saldo sale de `stock_sede` y la respuesta expone la sede.
    """
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_EXISTENCIAS)
    assert respuesta.status_code == 200, respuesta.text

    cuaderno = _existencia(respuesta.json(), ambito["producto_id"])
    assert cuaderno["stock_total"] == 50
    assert [s["sede_nombre"] for s in cuaderno["sedes"]] == ["Operaciones"]


def test_bodeguero_ajeno_existencias_solo_su_institucion(motor, ambito):
    """Un Bodeguero de INST02 ve su stock (7), no el de INST01 (50)."""
    with _cliente(
        motor, "Bodeguero", ambito["dep_ajeno_id"], ambito["sede_ajena_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_EXISTENCIAS)
    assert respuesta.status_code == 200, respuesta.text

    ajeno = _existencia(respuesta.json(), ambito["producto_ajeno_id"])
    assert ajeno["stock_total"] == 7
    assert [s["sede_nombre"] for s in ajeno["sedes"]] == ["Bodega Sur"]
    # El producto de INST01 no aparece en el catalogo de INST02 (D-1/AC-5).
    assert ambito["producto_id"] not in {
        e["producto_id"] for e in respuesta.json()
    }


def test_solicitante_existencias_solo_su_institucion(motor, ambito):
    """El Solicitante consulta existencias, acotadas a su institucion."""
    with _cliente(motor, "Solicitante", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_EXISTENCIAS)
    assert respuesta.status_code == 200, respuesta.text

    cuaderno = _existencia(respuesta.json(), ambito["producto_id"])
    assert cuaderno["stock_total"] == 50


def test_superadmin_existencias_es_global_y_atribuye_institucion(motor, ambito):
    """Superadmin ve ambas instituciones, cada producto con su `institucion_id` (AC-8)."""
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(RUTA_EXISTENCIAS)
    assert respuesta.status_code == 200, respuesta.text

    cuaderno = _existencia(respuesta.json(), ambito["producto_id"])
    assert cuaderno["stock_total"] == 50
    assert [s["sede_nombre"] for s in cuaderno["sedes"]] == ["Operaciones"]
    assert cuaderno["institucion_id"] == "INST01"

    ajeno = _existencia(respuesta.json(), ambito["producto_ajeno_id"])
    assert ajeno["stock_total"] == 7
    assert [s["sede_nombre"] for s in ajeno["sedes"]] == ["Bodega Sur"]
    assert ajeno["institucion_id"] == "INST02"


def test_catalogo_no_incluye_productos_de_otra_institucion(motor, ambito):
    """El catalogo deja de ser global (008 D-1): un Administrador de INST01 no ve
    el producto de INST02 en `/existencias` ni en `/productos`."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        existencias = cliente.get(RUTA_EXISTENCIAS).json()
        productos = cliente.get(RUTA_PRODUCTOS).json()

    assert ambito["producto_ajeno_id"] not in {
        e["producto_id"] for e in existencias
    }
    assert ambito["producto_ajeno_id"] not in {p["producto_id"] for p in productos}
    assert ambito["producto_id"] in {p["producto_id"] for p in productos}


def test_existencias_departamento_ajeno_responde_403(motor, ambito):
    """`departamento_id` de otra institucion responde 403, no una lista vacia."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(
            RUTA_EXISTENCIAS, params={"departamento_id": ambito["dep_ajeno_id"]}
        )
    assert respuesta.status_code == 403, respuesta.text


def test_existencias_departamento_propio_responde_200(motor, ambito):
    with _cliente(
        motor, "Bodeguero", ambito["departamento_id"], ambito["sede_propia_id"]
    ) as cliente:
        respuesta = cliente.get(
            RUTA_EXISTENCIAS, params={"departamento_id": ambito["departamento_id"]}
        )
    assert respuesta.status_code == 200, respuesta.text


def test_superadmin_existencias_departamento_ajeno_responde_200(motor, ambito):
    """Superadmin conserva alcance global: puede pedir cualquier departamento."""
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(
            RUTA_EXISTENCIAS, params={"departamento_id": ambito["dep_ajeno_id"]}
        )
    assert respuesta.status_code == 200, respuesta.text


# ---------------------------------------------------------------------------
# Stock: saldo por sede acotado por institucion y `sede_id` ajeno
# ---------------------------------------------------------------------------


def test_stock_administrador_solo_su_institucion(motor, ambito):
    """Feature 011 (B1): `/stock` expone el saldo por sede de su institucion."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_STOCK)
    assert respuesta.status_code == 200, respuesta.text

    sedes = {fila["sede_id"] for fila in respuesta.json()}
    assert ambito["sede_propia_id"] in sedes
    assert ambito["sede_ajena_id"] not in sedes, "no debe ver la sede de otro tenant"


def test_stock_superadmin_es_global(motor, ambito):
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(RUTA_STOCK)
    assert respuesta.status_code == 200, respuesta.text

    sedes = {fila["sede_id"] for fila in respuesta.json()}
    assert {ambito["sede_propia_id"], ambito["sede_ajena_id"]} <= sedes


def test_stock_sede_ajena_responde_404(motor, ambito):
    """Feature 011 (AC-3/AC-7): un `sede_id` ajeno se oculta con 404."""
    with _cliente(
        motor, "Bodeguero", ambito["departamento_id"], ambito["sede_propia_id"]
    ) as cliente:
        respuesta = cliente.get(
            RUTA_STOCK, params={"sede_id": ambito["sede_ajena_id"]}
        )
    assert respuesta.status_code == 404, respuesta.text


# ---------------------------------------------------------------------------
# Movimientos: lectura y registro acotados a la institucion
# ---------------------------------------------------------------------------


def test_movimientos_bodeguero_solo_su_institucion(motor, ambito):
    with _cliente(motor, "Bodeguero", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_MOVIMIENTOS)
    assert respuesta.status_code == 200, respuesta.text

    ids = {fila["movimiento_id"] for fila in respuesta.json()}
    assert ambito["movimiento_propio_id"] in ids
    assert ambito["movimiento_ajeno_id"] not in ids


def test_movimientos_superadmin_es_global(motor, ambito):
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(RUTA_MOVIMIENTOS)
    assert respuesta.status_code == 200, respuesta.text

    ids = {fila["movimiento_id"] for fila in respuesta.json()}
    assert {ambito["movimiento_propio_id"], ambito["movimiento_ajeno_id"]} <= ids


def test_registrar_movimiento_en_inventario_ajeno_responde_403_sin_mutar(motor, ambito):
    """Un Bodeguero no puede mover stock de otra institucion ni cambia filas.

    La fila legada se observa por ORM: desde la Feature 011 (B1)
    `GET /inventario/stock` no expone el inventario departamental.
    """
    antes = _stock_inventario_legado(motor, ambito["inventario_ajeno_id"])
    with _cliente(motor, "Bodeguero", ambito["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "observacion": "Intento ajeno",
                "inventario_id": ambito["inventario_ajeno_id"],
            },
        )
    despues = _stock_inventario_legado(motor, ambito["inventario_ajeno_id"])

    assert respuesta.status_code == 403, respuesta.text
    assert despues == antes


def test_registrar_movimiento_en_inventario_propio_responde_201(motor, ambito):
    with _cliente(motor, "Bodeguero", ambito["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "observacion": "Ingreso propio valido",
                "inventario_id": ambito["inventario_id"],
            },
        )
    assert respuesta.status_code == 201, respuesta.text


# ---------------------------------------------------------------------------
# Institucion no resoluble: 403 para el rol limitado, global para Superadmin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ruta,params",
    [
        (RUTA_EXISTENCIAS, None),
        (RUTA_STOCK, None),
        (RUTA_USUARIOS, None),
    ],
)
def test_rol_limitado_sin_institucion_resoluble_responde_403(
    motor, ambito, ruta, params
):
    """Sin departamento (o con uno inexistente) el rol limitado nunca es global."""
    with _cliente(motor, "Administrador", _SIN_DEPARTAMENTO) as cliente:
        sin_departamento = cliente.get(ruta, params=params)
    with _cliente(motor, "Administrador", 999999) as cliente:
        departamento_inexistente = cliente.get(ruta, params=params)

    assert sin_departamento.status_code == 403, sin_departamento.text
    assert departamento_inexistente.status_code == 403, departamento_inexistente.text


def test_superadmin_sin_departamento_conserva_alcance_global(motor, ambito):
    """Superadmin no necesita institucion resoluble: es el unico rol global."""
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        existencias = cliente.get(RUTA_EXISTENCIAS)
        usuarios = cliente.get(RUTA_USUARIOS)
    assert existencias.status_code == 200, existencias.text
    assert usuarios.status_code == 200, usuarios.text


# ---------------------------------------------------------------------------
# Catalogo de usuarios, departamentos, instituciones y roles
# ---------------------------------------------------------------------------


def test_usuarios_administrador_solo_su_institucion(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_USUARIOS)
    assert respuesta.status_code == 200, respuesta.text

    correos = {u["correo"] for u in respuesta.json()}
    assert "ana.prueba@compustock.cl" in correos
    assert "beto.ajeno@compustock.cl" not in correos


def test_usuarios_superadmin_es_global(motor, ambito):
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(RUTA_USUARIOS)
    assert respuesta.status_code == 200, respuesta.text

    correos = {u["correo"] for u in respuesta.json()}
    assert {
        "ana.prueba@compustock.cl",
        "beto.ajeno@compustock.cl",
    } <= correos


def test_departamentos_administrador_solo_su_institucion(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_DEPARTAMENTOS)
    assert respuesta.status_code == 200, respuesta.text

    ids = {d["departamento_id"] for d in respuesta.json()}
    assert ambito["departamento_id"] in ids
    assert ambito["dep_ajeno_id"] not in ids


def test_instituciones_administrador_solo_la_propia(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_INSTITUCIONES)
    assert respuesta.status_code == 200, respuesta.text

    ids = {i["institucion_id"] for i in respuesta.json()}
    assert ids == {ambito["inst_propia"]}


def test_instituciones_superadmin_ve_todas(motor, ambito):
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(RUTA_INSTITUCIONES)
    assert respuesta.status_code == 200, respuesta.text

    ids = {i["institucion_id"] for i in respuesta.json()}
    assert {ambito["inst_propia"], ambito["inst_ajena"]} <= ids


def test_roles_son_compartidos_para_el_administrador(motor, ambito):
    """Los roles del catalogo son compartidos: no se filtran por institucion."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_ROLES)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()


def test_categorias_y_productos_son_institucionales(motor, ambito):
    """008 D-1: el catalogo de categorias/productos deja de ser global; el rol
    limitado solo recibe los registros de su institucion."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        categorias = cliente.get(RUTA_CATEGORIAS)
        productos = cliente.get(RUTA_PRODUCTOS)

    assert categorias.status_code == 200, categorias.text
    assert productos.status_code == 200, productos.text
    assert ambito["categoria_ajena_id"] not in {
        c["categoria_id"] for c in categorias.json()
    }
    assert ambito["producto_ajeno_id"] not in {
        p["producto_id"] for p in productos.json()
    }
    assert {c["institucion_id"] for c in categorias.json()} == {"INST01"}
    assert {p["institucion_id"] for p in productos.json()} == {"INST01"}


def test_superadmin_categorias_y_productos_atribuyen_institucion(motor, ambito):
    """Superadmin ve el catalogo global con `institucion_id` por registro (AC-8)."""
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        categorias = cliente.get(RUTA_CATEGORIAS).json()
        productos = cliente.get(RUTA_PRODUCTOS).json()

    assert {c["institucion_id"] for c in categorias} >= {"INST01", "INST02"}
    producto_ajeno = next(p for p in productos if p["producto_id"] == ambito["producto_ajeno_id"])
    assert producto_ajeno["institucion_id"] == "INST02"


# ---------------------------------------------------------------------------
# Acceso por objeto (008 AC-9): ajeno oculto con 404, igual que inexistente
# ---------------------------------------------------------------------------


def test_producto_ajeno_responde_404_igual_que_inexistente(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        propio = cliente.get(f"{RUTA_PRODUCTOS}/{ambito['producto_id']}")
        ajeno = cliente.get(f"{RUTA_PRODUCTOS}/{ambito['producto_ajeno_id']}")
        inexistente = cliente.get(f"{RUTA_PRODUCTOS}/999999")

    assert propio.status_code == 200, propio.text
    assert ajeno.status_code == 404, ajeno.text
    assert inexistente.status_code == 404, inexistente.text
    assert ajeno.json() == inexistente.json()


def test_categoria_ajena_responde_404_igual_que_inexistente(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        propio = cliente.get(f"{RUTA_CATEGORIAS}/{ambito['categoria_id']}")
        ajeno = cliente.get(f"{RUTA_CATEGORIAS}/{ambito['categoria_ajena_id']}")
        inexistente = cliente.get(f"{RUTA_CATEGORIAS}/999999")

    assert propio.status_code == 200, propio.text
    assert ajeno.status_code == 404, ajeno.text
    assert inexistente.status_code == 404, inexistente.text
    assert ajeno.json() == inexistente.json()


def test_superadmin_producto_por_objeto_es_global(motor, ambito):
    with _cliente(motor, "Superadmin", _SIN_DEPARTAMENTO) as cliente:
        ajeno = cliente.get(f"{RUTA_PRODUCTOS}/{ambito['producto_ajeno_id']}")
    assert ajeno.status_code == 200, ajeno.text
    assert ajeno.json()["institucion_id"] == "INST02"


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_rol_limitado_sin_institucion_producto_por_objeto_403(motor, ambito, rol):
    with _cliente(motor, rol, _SIN_DEPARTAMENTO) as cliente:
        respuesta = cliente.get(f"{RUTA_PRODUCTOS}/{ambito['producto_id']}")
    assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# Escritura de catalogo (008 AC-2/AC-10): categoria institucional y sin mutacion
# ---------------------------------------------------------------------------


def test_crear_producto_con_categoria_ajena_responde_404_sin_persistir(motor, ambito):
    """AC-9/AC-10: la categoria ajena no habilita el alta ni deja fila."""
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        antes = cliente.get(RUTA_PRODUCTOS).json()
        respuesta = cliente.post(
            RUTA_PRODUCTOS,
            json={
                "nombre": "Producto cruce",
                "descripcion": None,
                "unidad_medida": "UNIDAD",
                "stock_minimo": 1,
                "categoria_id": ambito["categoria_ajena_id"],
            },
        )
        despues = cliente.get(RUTA_PRODUCTOS).json()

    assert respuesta.status_code == 404, respuesta.text
    assert despues == antes


def test_crear_producto_propio_queda_en_la_institucion_del_usuario(motor, ambito):
    with _cliente(motor, "Administrador", ambito["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_PRODUCTOS,
            json={
                "nombre": "Producto propio",
                "descripcion": None,
                "unidad_medida": "UNIDAD",
                "stock_minimo": 1,
                "categoria_id": ambito["categoria_id"],
            },
        )

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["institucion_id"] == "INST01"
