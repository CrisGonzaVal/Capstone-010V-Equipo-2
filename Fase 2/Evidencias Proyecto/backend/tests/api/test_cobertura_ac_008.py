"""T9 (Feature 008): huecos de cobertura de AC sobre el padron de dos instituciones.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), sobre la
fixture compartida `dos_instituciones` (dos instituciones con catalogos
homonimos y los cuatro roles persistidos). Cubre los AC que la suite previa no
fijaba de forma explicita:

  * **AC-3**: `rol`, `prioridad` y `estado_ticket` son catalogos globales
    compartidos: un usuario de INST01 y uno de INST02 reciben exactamente el
    mismo catalogo de flujo.
  * **AC-1 / AC-6**: dos instituciones contienen una categoria y un producto con
    el mismo nombre; son registros independientes y cada uno tiene su propio
    stock; la lectura global de Superadmin los atribuye a su institucion sin
    mezclar los totales.
  * **AC-5**: ningun id ni filtro enviado por el cliente amplia el alcance: un
    parametro `institucion_id` inventado se ignora y filtrar por una categoria
    ajena devuelve un catalogo vacio, nunca registros de otra institucion.

No duplica los casos ya cubiertos por `test_ambito_institucional.py`,
`test_tickets_institucional.py` ni `test_cobertura` de catalogo/stock.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import Rol, Sede, StockSede, Usuario
from app.services.auth_service import IdentidadAutenticada

RUTA_CATALOGOS = "/api/v1/tickets/catalogos"
RUTA_ROLES = "/api/v1/usuarios/roles"
RUTA_PRODUCTOS = "/api/v1/inventario/productos"
RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"


def _identidad(rol: str, departamento_id) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="Cobertura008",
        correo="sonda.cobertura008@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-cobertura-008")


@contextmanager
def _cliente(motor, rol: str, departamento_id):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(
        rol, departamento_id
    )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-3: catalogos de flujo globales y compartidos
# ---------------------------------------------------------------------------


def test_catalogos_de_flujo_son_compartidos_por_ambas_instituciones(
    motor, dos_instituciones
):
    with _cliente(motor, "Administrador", dos_instituciones["departamento_id"]) as propio:
        catalogos_propios = propio.get(RUTA_CATALOGOS).json()
        roles_propios = {
            (r["rol_id"], r["nombre_rol"]) for r in propio.get(RUTA_ROLES).json()
        }
    with _cliente(
        motor, "Administrador", dos_instituciones["departamento_ajeno_id"]
    ) as ajeno:
        catalogos_ajenos = ajeno.get(RUTA_CATALOGOS).json()
        roles_ajenos = {
            (r["rol_id"], r["nombre_rol"]) for r in ajeno.get(RUTA_ROLES).json()
        }

    assert catalogos_propios["prioridades"], "el catalogo debe tener prioridades"
    assert catalogos_propios["estados"], "el catalogo debe tener estados"
    assert catalogos_propios["prioridades"] == catalogos_ajenos["prioridades"]
    assert catalogos_propios["estados"] == catalogos_ajenos["estados"]
    assert roles_propios == roles_ajenos
    # Los cuatro roles compartidos estan presentes en el catalogo global.
    assert {"Superadmin", "Administrador", "Bodeguero", "Solicitante"} <= {
        nombre for _, nombre in roles_propios
    }


# ---------------------------------------------------------------------------
# AC-1 / AC-6: homonimos independientes con stock independiente
# ---------------------------------------------------------------------------


def _sembrar_stock_sede(motor, institucion_id: str, producto_id: int, stock: int) -> None:
    """Siembra el saldo vigente de un producto en una sede nueva (Feature 011, D-2)."""
    db = sessionmaker(bind=motor)()
    try:
        sede = Sede(nombre=f"Sede {institucion_id}", institucion_id=institucion_id)
        db.add(sede)
        db.flush()
        db.add(
            StockSede(
                sede_id=sede.sede_id,
                producto_id=producto_id,
                stock_actual=stock,
                institucion_id=institucion_id,
            )
        )
        db.commit()
    finally:
        db.close()


def test_homonimos_son_registros_independientes_con_stock_propio(
    motor, dos_instituciones
):
    # Feature 011 (T8): el saldo vigente sale de `stock_sede`, no del inventario
    # departamental legado. Se siembra una sede con saldo por institucion.
    _sembrar_stock_sede(motor, "INST01", dos_instituciones["producto_id"], 50)
    _sembrar_stock_sede(
        motor, "INST02", dos_instituciones["producto_homonimo_ajeno_id"], 5
    )

    with _cliente(motor, "Superadmin", None) as supervisor:
        existencias = supervisor.get(RUTA_EXISTENCIAS).json()

    propio = next(
        e for e in existencias if e["producto_id"] == dos_instituciones["producto_id"]
    )
    ajeno = next(
        e
        for e in existencias
        if e["producto_id"] == dos_instituciones["producto_homonimo_ajeno_id"]
    )

    # Mismo nombre, ids distintos: registros independientes (AC-1).
    assert propio["nombre"] == ajeno["nombre"] == "Cuaderno linedado"
    assert propio["producto_id"] != ajeno["producto_id"]
    # Stock independiente y atribucion explicita por institucion (AC-1, AC-6, AC-8).
    assert propio["stock_total"] == 50
    assert ajeno["stock_total"] == dos_instituciones["stock_homonimo_ajeno"] == 5
    assert propio["institucion_id"] == "INST01"
    assert ajeno["institucion_id"] == "INST02"


# ---------------------------------------------------------------------------
# AC-5: el cliente no amplia el alcance con ids ni filtros
# ---------------------------------------------------------------------------


def test_parametro_institucion_del_cliente_no_amplia_el_alcance(
    motor, dos_instituciones
):
    """Un `institucion_id` inventado en la query no cambia el catalogo recibido."""
    with _cliente(motor, "Administrador", dos_instituciones["departamento_id"]) as cliente:
        respuesta = cliente.get(
            RUTA_PRODUCTOS, params={"institucion_id": dos_instituciones["inst_ajena"]}
        )

    assert respuesta.status_code == 200, respuesta.text
    ids = {p["producto_id"] for p in respuesta.json()}
    assert dos_instituciones["producto_id"] in ids
    assert dos_instituciones["producto_homonimo_ajeno_id"] not in ids


def test_filtro_por_categoria_ajena_no_expone_catalogo_ajeno(
    motor, dos_instituciones
):
    """Filtrar existencias por una categoria de otra institucion da catalogo vacio."""
    with _cliente(motor, "Administrador", dos_instituciones["departamento_id"]) as cliente:
        respuesta = cliente.get(
            RUTA_EXISTENCIAS,
            params={"categoria_id": dos_instituciones["categoria_homonima_ajena_id"]},
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_rol_limitado_por_objeto_ajeno_siempre_oculta(motor, dos_instituciones, rol):
    """AC-5/AC-9: por id de producto ajeno, el rol limitado de INST01 recibe 404."""
    with _cliente(motor, rol, dos_instituciones["departamento_id"]) as cliente:
        ajeno = cliente.get(
            f"{RUTA_PRODUCTOS}/{dos_instituciones['producto_homonimo_ajeno_id']}"
        )
        inexistente = cliente.get(f"{RUTA_PRODUCTOS}/999999")

    assert ajeno.status_code == 404, ajeno.text
    assert ajeno.json() == inexistente.json()
