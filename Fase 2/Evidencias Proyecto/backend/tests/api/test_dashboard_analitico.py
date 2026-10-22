"""T1 (Feature 009): pruebas rojas de contrato, permisos y casos base del dashboard.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), igual que el
resto de `tests/api/`. El dashboard analitico consolidado se consulta con
`GET /api/v1/dashboard/`; aqui se fija el contrato de respuesta (claves
`snake_case` del plan §1), los estatus base (`200`/`401`/`403`) y el **no cambio**
del permiso vigente de `GET /api/v1/inventario/movimientos` (Solicitante excluido).

Fase ROJA de TDD: las tareas T5-T7 todavia no crean el schema, el servicio ni el
router del dashboard, y la operacion no esta en la matriz central. Por eso cada
caso rojo debe fallar **solo** por la ruta/contrato inexistente (un `404` en las
peticiones, la ruta ausente en `/openapi.json` o la operacion ausente de la
matriz), nunca por imports rotos, fixtures invalidas ni sintaxis. Este modulo no
importa schemas ni servicios del dashboard a proposito: la respuesta se contrasta
como **JSON literal** contra el contrato aprobado.

Los valores concretos de KPI y las reglas de conteo (T2) se fijan con un escenario
autocontenido y expectativas observables por HTTP (JSON literal), sin importar
schemas ni servicios del dashboard. Los casos de aislamiento multiinstitucion
profundo (T3) y de actividad/orden (T4) se cubren en sus propias tareas.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.db.database import Base
from app.main import app
from app.models import (
    Categoria,
    Departamento,
    EstadoTicket,
    Institucion,
    Inventario,
    MovimientoInventario,
    Prioridad,
    Producto,
    Rol,
    Sede,
    StockSede,
    Ticket,
    Usuario,
)
from app.services.auth_service import IdentidadAutenticada

#: Ruta contractual del dashboard consolidado (plan §1).
RUTA_DASHBOARD = "/api/v1/dashboard/"
#: Ruta historica cuyo permiso vigente (403 a Solicitante) no debe cambiar.
RUTA_MOVIMIENTOS = "/api/v1/inventario/movimientos"

#: Secciones del DTO `DashboardAnaliticoRespuesta` (plan §1).
CAMPOS_RESPUESTA = {
    "kpi",
    "alertas",
    "actividad_disponible",
    "actividad_movimientos",
}
#: Campos del KPI consolidado (plan §1).
CAMPOS_KPI = {
    "unidades_en_stock",
    "tickets_activos",
    "total_departamentos",
    "total_alertas",
}
#: Campos de cada fila del log de alertas (Feature 011: la alerta es por sede).
CAMPOS_ALERTA = {
    "sede_id",
    "sede_nombre",
    "producto_id",
    "producto_nombre",
    "stock_actual",
    "stock_minimo",
    "institucion_id",
    "institucion_nombre",
}
#: Campos de cada fila de la actividad reciente (Feature 011: proyeccion unica;
#: `sede` para movimientos nuevos y `departamento`/`ubicacion` para los legados).
CAMPOS_ACTIVIDAD = {
    "movimiento_id",
    "tipo_movimiento",
    "cantidad",
    "fecha_movimiento",
    "producto_id",
    "producto_nombre",
    "sede_id",
    "sede_nombre",
    "departamento_id",
    "departamento_nombre",
    "ubicacion",
    "institucion_id",
    "institucion_nombre",
}

# --- T2: bordes del escenario de criticidad (D-1) --------------------------
#: Stock minimo del producto "Papel Bond" y sus tres filas de borde.
M_PAPEL = 10
STOCK_M_MENOS_1 = M_PAPEL - 1
STOCK_M = M_PAPEL
STOCK_M_MAS_1 = M_PAPEL + 1
#: Stock de la fila homonima de INSTB (bajo el minimo, critica).
STOCK_PAPEL_B = 3

#: Centinela para distinguir "sin autenticar" de "rol ausente" (`None`).
_SIN_AUTENTICAR = object()

#: Los cuatro roles de la semilla: todos pueden consultar el dashboard (plan §1).
_ROLES = ("Superadmin", "Administrador", "Bodeguero", "Solicitante")


def _identidad(
    rol: str, departamento_id: int | None, usuario_id: int = 9999
) -> IdentidadAutenticada:
    """Identidad autenticada con el rol, el departamento y el id de usuario dados.

    El usuario no se persiste: la autorizacion solo lee `usuario.rol.nombre_rol` y
    la resolucion de ambito deriva la institucion de `usuario.departamento_id ->
    departamento` por ORM. Para Superadmin el departamento es irrelevante (alcance
    global); para los roles limitados apunta al departamento sembrado. `usuario_id`
    permite al Solicitante apuntar a un usuario persistido cuyos tickets son los
    unicos visibles (AC-2).
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Dashboard",
        correo="sonda.dashboard@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-dashboard")


@contextmanager
def _cliente(
    motor,
    rol=_SIN_AUTENTICAR,
    *,
    departamento_id: int | None = None,
    usuario_id: int = 9999,
):
    """`TestClient` del `app` real con `get_db` en SQLite y la identidad por rol.

    Con `rol=_SIN_AUTENTICAR` no se overridea `get_current_user`, de modo que la
    sesion ausente/invalida ejerce el 401 real.
    """
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if rol is not _SIN_AUTENTICAR:
        app.dependency_overrides[dependencies.get_current_user] = lambda: _identidad(
            rol, departamento_id, usuario_id
        )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _leer_dashboard(cliente) -> dict:
    """Consulta el dashboard por HTTP y exige el 200 contractual."""
    respuesta = cliente.get(RUTA_DASHBOARD)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# ---------------------------------------------------------------------------
# AC-13: contrato consolidado y estatus 200
# ---------------------------------------------------------------------------


def test_dashboard_consolidado_responde_200_con_el_contrato(motor, datos_base):
    """El dashboard devuelve una sola respuesta con las cuatro secciones del DTO.

    Administrador con ambito resoluble (INST01) sobre `datos_base`. En rojo falla
    con 404: la ruta todavia no existe (la crea T7).
    """
    with _cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    assert set(cuerpo) == CAMPOS_RESPUESTA, "secciones del DTO consolidado"
    assert set(cuerpo["kpi"]) == CAMPOS_KPI, "campos del KPI consolidado"
    for campo in CAMPOS_KPI:
        assert isinstance(cuerpo["kpi"][campo], int), campo
    assert isinstance(cuerpo["alertas"], list)
    assert isinstance(cuerpo["actividad_disponible"], bool)
    assert isinstance(cuerpo["actividad_movimientos"], list)


def test_dashboard_superadmin_recibe_403_sin_datos_ac_15(motor):
    """Feature 017 (D-9/AC-15): el Superadmin ya no consulta el dashboard.

    La semantica de ceros sin filas queda cubierta por el servicio; aqui se fija
    la frontera HTTP: 403 y ningun campo de negocio.
    """
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json() == {"detail": "Permiso insuficiente para la operacion"}
    assert "kpi" not in respuesta.json()


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_dashboard_permite_a_los_tres_roles_institucionales(motor, datos_base, rol):
    """Feature 017 (D-9/AC-15): los tres roles institucionales conservan el 200."""
    with _cliente(
        motor, rol, departamento_id=datos_base["departamento_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 200, (rol, respuesta.text)


def test_dashboard_sin_sesion_responde_401(motor):
    """AC-14: sin Bearer valido la sesion se rechaza con 401.

    En rojo falla con 404 (la ruta aun no existe); cuando T7 la publique, el 401
    de `get_current_user` es el esperado.
    """
    with _cliente(motor, _SIN_AUTENTICAR) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 401, respuesta.text


# ---------------------------------------------------------------------------
# AC-10: Solicitante sin actividad de movimientos y 403 vigente del historial
# ---------------------------------------------------------------------------


def test_dashboard_solicitante_no_expone_actividad(motor, datos_base):
    """AC-10: el Solicitante obtiene su dashboard con actividad no disponible.

    La seccion se distingue por `actividad_disponible=false` con lista vacia; no
    se consulta el historial de movimientos desde el dashboard.
    """
    with _cliente(
        motor, "Solicitante", departamento_id=datos_base["departamento_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["actividad_disponible"] is False
    assert cuerpo["actividad_movimientos"] == []


def test_movimientos_sigue_denegado_a_solicitante(motor, datos_base):
    """AC-10/AC-14: el permiso vigente de `GET /inventario/movimientos` no cambia.

    El Solicitante recibe 403 en el historial; el dashboard no es una via para
    ampliar esa denegacion. Esta expectativa debe mantenerse verde: fija la no
    regresion del permiso.
    """
    with _cliente(
        motor, "Solicitante", departamento_id=datos_base["departamento_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_MOVIMIENTOS)

    assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# AC-14: contrato OpenAPI del dashboard
# ---------------------------------------------------------------------------


def test_openapi_del_dashboard_declara_200_y_response_model():
    """AC-14: el GET del dashboard publica 200 explicito, DTO y sin query params.

    En rojo falla porque la ruta aun no esta en `/openapi.json` (T7 la publica).
    """
    contrato = app.openapi()
    assert RUTA_DASHBOARD in contrato["paths"], "la ruta del dashboard debe publicarse"

    operacion = contrato["paths"][RUTA_DASHBOARD]["get"]

    assert operacion.get("summary"), "la operacion debe declarar un resumen"
    assert "200" in operacion["responses"], "el 200 debe declararse explicitamente"
    assert "401" in operacion["responses"], "el 401 debe documentarse"
    assert "403" in operacion["responses"], "el 403 debe documentarse"

    esquema = operacion["responses"]["200"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].endswith("DashboardAnaliticoRespuesta"), esquema
    assert operacion.get("parameters", []) == [], "el dashboard no recibe query params"


# ---------------------------------------------------------------------------
# T2 — Reglas de KPI y filas criticas (AC-1, AC-2, AC-3, AC-4)
#
# Escenario autocontenido y sin ids fijos: cada borde del conteo se identifica por
# nombre/valor. Los datos se siembran por ORM (fixture), pero las expectativas se
# observan solo por HTTP contra el JSON literal del contrato.
# ---------------------------------------------------------------------------


@pytest.fixture
def escenario_kpi(motor):
    """Dos instituciones con valores distinguibles para cada regla del KPI.

    INSTA "Instituto Alfa":
      * departamentos "Operaciones", "Bodega", "Archivo" y "Sin Inventario" (vacio)
        => 4 registros, uno de ellos sin filas de inventario (AC-3).
      * "Papel Bond" (minimo 10) con filas 9 (M-1), 10 (M) y 11 (M+1) (AC-4).
      * "Insumo Cero" (minimo 0) con una fila 0 (AC-4).
      * "Producto Sin Inventario" (minimo 5) sin filas (AC-4).
      * tickets de dos solicitantes con estados "Cerrado", "cerrado", "CERRADO",
        "EnCurso" y "Cancelado" (AC-2).
      => unidades 9+10+11+0 = 30; departamentos 4; alertas 3; tickets activos 4.

    INSTB "Instituto Beta":
      * departamento "Operaciones" homonimo de INSTA (AC-3) y "Papel Bond"
        homonimo (minimo 10) con una fila 3 (AC-4).
      * un ticket activo para que el conteo global difiera del institucional.
      => unidades 3; departamentos 1; alertas 1; tickets activos 1.
    """
    db = sessionmaker(bind=motor)()
    try:
        inst_a = Institucion(institucion_id="INSTA", nombre="Instituto Alfa")
        inst_b = Institucion(institucion_id="INSTB", nombre="Instituto Beta")
        db.add_all([inst_a, inst_b])
        db.flush()

        roles = {}
        for nombre in ("Superadmin", "Administrador", "Bodeguero", "Solicitante"):
            rol = Rol(nombre_rol=nombre, descripcion=f"Rol {nombre}")
            db.add(rol)
            db.flush()
            roles[nombre] = rol

        def _departamento(nombre, institucion_id):
            dep = Departamento(
                nombre_dep=nombre, descripcion=nombre, institucion_id=institucion_id
            )
            db.add(dep)
            db.flush()
            return dep

        dep_op_a = _departamento("Operaciones", "INSTA")
        dep_bod_a = _departamento("Bodega", "INSTA")
        dep_arc_a = _departamento("Archivo", "INSTA")
        dep_vacia_a = _departamento("Sin Inventario", "INSTA")
        dep_op_b = _departamento("Operaciones", "INSTB")

        def _usuario(nombre, rol, departamento_id):
            usuario = Usuario(
                nombre=nombre,
                apellido="Escenario",
                correo=f"{nombre.lower()}.{rol.nombre_rol.lower()}@compustock.cl",
                departamento_id=departamento_id,
                rol_id=rol.rol_id,
            )
            db.add(usuario)
            db.flush()
            return usuario

        admin_a = _usuario("Ada", roles["Administrador"], dep_op_a.departamento_id)
        solic1_a = _usuario("Sol", roles["Solicitante"], dep_op_a.departamento_id)
        solic2_a = _usuario("Dos", roles["Solicitante"], dep_op_a.departamento_id)
        admin_b = _usuario("Beto", roles["Administrador"], dep_op_b.departamento_id)

        def _categoria(nombre, institucion_id):
            cat = Categoria(
                nombre_cat=nombre, descripcion_cat=nombre, institucion_id=institucion_id
            )
            db.add(cat)
            db.flush()
            return cat

        cat_a = _categoria("Papeleria", "INSTA")
        cat_b = _categoria("Papeleria", "INSTB")

        def _producto(nombre, stock_minimo, categoria):
            prod = Producto(
                nombre=nombre,
                descripcion=nombre,
                unidad_medida="UNIDAD",
                stock_minimo=stock_minimo,
                categoria_id=categoria.categoria_id,
                institucion_id=categoria.institucion_id,
            )
            db.add(prod)
            db.flush()
            return prod

        papel_a = _producto("Papel Bond", M_PAPEL, cat_a)
        cero_a = _producto("Insumo Cero", 0, cat_a)
        sin_inv_a = _producto("Producto Sin Inventario", 5, cat_a)
        papel_b = _producto("Papel Bond", M_PAPEL, cat_b)

        def _inventario(producto, departamento, stock):
            inv = Inventario(
                stock_actual=stock,
                ubicacion=f"{departamento.nombre_dep} ({producto.institucion_id})",
                departamento_id=departamento.departamento_id,
                producto_id=producto.producto_id,
                institucion_id=producto.institucion_id,
            )
            db.add(inv)
            db.flush()
            return inv

        inv_m_menos_1 = _inventario(papel_a, dep_op_a, STOCK_M_MENOS_1)
        inv_m = _inventario(papel_a, dep_bod_a, STOCK_M)
        inv_m_mas_1 = _inventario(papel_a, dep_arc_a, STOCK_M_MAS_1)
        inv_cero = _inventario(cero_a, dep_op_a, 0)
        inv_papel_b = _inventario(papel_b, dep_op_b, STOCK_PAPEL_B)

        # Feature 011 (spec D-6/AC-11): la fuente vigente de saldo es `stock_sede`.
        # Se crea una sede por departamento (con su denominacion) y las filas de
        # stock equivalentes a las de `inventario`; esas filas legadas quedan para
        # los movimientos historicos de la actividad.
        def _sede(nombre, dep, institucion_id):
            sede = Sede(nombre=nombre, institucion_id=institucion_id)
            db.add(sede)
            db.flush()
            dep.sede_id = sede.sede_id
            db.flush()
            return sede

        sede_op_a = _sede("Operaciones", dep_op_a, "INSTA")
        sede_bod_a = _sede("Bodega", dep_bod_a, "INSTA")
        sede_arc_a = _sede("Archivo", dep_arc_a, "INSTA")
        _sede("Sin Inventario", dep_vacia_a, "INSTA")
        sede_op_b = _sede("Operaciones", dep_op_b, "INSTB")

        def _stock_sede(prod, sede, stock):
            fila = StockSede(
                stock_actual=stock,
                sede_id=sede.sede_id,
                producto_id=prod.producto_id,
                institucion_id=prod.institucion_id,
            )
            db.add(fila)
            db.flush()
            return fila

        stock_papel_op_a = _stock_sede(papel_a, sede_op_a, STOCK_M_MENOS_1)
        _stock_sede(papel_a, sede_bod_a, STOCK_M)
        _stock_sede(papel_a, sede_arc_a, STOCK_M_MAS_1)
        _stock_sede(cero_a, sede_op_a, 0)
        _stock_sede(papel_b, sede_op_b, STOCK_PAPEL_B)

        prioridad = Prioridad(nombre="ALTA", descripcion="Prioridad alta")
        db.add(prioridad)
        db.flush()

        estados = {}
        for nombre in ("Cerrado", "cerrado", "CERRADO", "EnCurso", "Cancelado"):
            estado = EstadoTicket(nombre=nombre, descripcion=nombre)
            db.add(estado)
            db.flush()
            estados[nombre] = estado

        def _ticket(usuario, estado_nombre, institucion_id):
            ticket = Ticket(
                usuario_id=usuario.usuario_id,
                prioridad_id=prioridad.prioridad_id,
                estado_id=estados[estado_nombre].estado_id,
                asunto=f"Ticket {estado_nombre}",
                descripcion="Sembrado para el escenario de KPI.",
                institucion_id=institucion_id,
            )
            db.add(ticket)
            db.flush()
            return ticket

        _ticket(solic1_a, "EnCurso", "INSTA")
        _ticket(solic1_a, "Cerrado", "INSTA")
        _ticket(solic1_a, "cerrado", "INSTA")
        _ticket(solic2_a, "CERRADO", "INSTA")
        _ticket(solic2_a, "Cancelado", "INSTA")
        _ticket(admin_b, "EnCurso", "INSTB")
        db.commit()

        return {
            "inst_a": "INSTA",
            "inst_b": "INSTB",
            "nombre_inst_a": "Instituto Alfa",
            "nombre_inst_b": "Instituto Beta",
            "dep_op_a": dep_op_a.departamento_id,
            "dep_vacia_a": dep_vacia_a.departamento_id,
            "dep_op_b": dep_op_b.departamento_id,
            "admin_a": admin_a.usuario_id,
            "solic1_a": solic1_a.usuario_id,
            "producto_papel_a": papel_a.producto_id,
            "producto_papel_b": papel_b.producto_id,
            "producto_sin_inventario_a": sin_inv_a.producto_id,
            "inventario_papel_op_a": inv_m_menos_1.inventario_id,
            "inventario_papel_b": inv_papel_b.inventario_id,
            "sede_papel_op_a": sede_op_a.sede_id,
            "stock_sede_papel_op_a": stock_papel_op_a.stock_sede_id,
        }
    finally:
        db.close()


# --- AC-1: unidades en stock ------------------------------------------------


def test_kpi_unidades_en_stock_suma_solo_las_filas_del_ambito(motor, escenario_kpi):
    """AC-1/AC-8: la suma de `stock_actual` no cruza instituciones.

    INSTA suma 9+10+11+0 = 30; INSTB suma 3. Valores distintos a proposito para
    que una fuga de ambito cambie la cifra.
    """
    with _cliente(
        motor,
        "Administrador",
        departamento_id=escenario_kpi["dep_op_a"],
        usuario_id=escenario_kpi["admin_a"],
    ) as cliente_a:
        kpi_a = _leer_dashboard(cliente_a)["kpi"]
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_b"]
    ) as cliente_b:
        kpi_b = _leer_dashboard(cliente_b)["kpi"]

    assert kpi_a["unidades_en_stock"] == 30, "9 + 10 + 11 + 0 dentro de INSTA"
    assert kpi_b["unidades_en_stock"] == 3, "solo la fila de INSTB"


# --- AC-2: tickets activos --------------------------------------------------


def test_kpi_tickets_activos_excluye_solo_el_nombre_literal_cerrado(
    motor, escenario_kpi
):
    """AC-2: solo el nombre exacto "Cerrado" se excluye; el casing distinto cuenta.

    INSTA tiene 5 tickets: EnCurso y "cerrado" de Sol, "CERRADO" y "Cancelado" de
    Dos (los cuatro activos), y un unico "Cerrado" excluido => 4. Una exclusion
    insensible a mayusculas daria 2.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        kpi = _leer_dashboard(cliente)["kpi"]

    assert kpi["tickets_activos"] == 4


def test_kpi_tickets_activos_solicitante_cuenta_solo_los_propios(motor, escenario_kpi):
    """AC-2/AC-9: el Solicitante cuenta solo sus propios tickets visibles.

    Sol tiene 2 activos (EnCurso, "cerrado"); los de Dos no entran.
    """
    with _cliente(
        motor,
        "Solicitante",
        departamento_id=escenario_kpi["dep_op_a"],
        usuario_id=escenario_kpi["solic1_a"],
    ) as cliente:
        kpi = _leer_dashboard(cliente)["kpi"]

    assert kpi["tickets_activos"] == 2


# --- AC-3: departamentos ----------------------------------------------------


def test_kpi_departamentos_cuenta_por_pk_incluido_sin_inventario(motor, escenario_kpi):
    """AC-3: se cuentan registros de departamento, incluido uno sin inventario.

    INSTA tiene "Operaciones", "Bodega", "Archivo" y "Sin Inventario" (vacio) => 4.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        kpi = _leer_dashboard(cliente)["kpi"]

    assert kpi["total_departamentos"] == 4


def test_kpi_departamentos_superadmin_recibe_403_ac_15(
    motor, escenario_kpi
):
    """Feature 017 (D-9/AC-15): el conteo global de departamentos se retira.

    La suma entre instituciones queda cubierta por el servicio del dashboard; la
    API ya no la expone al Superadmin.
    """
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 403, respuesta.text
    assert "kpi" not in respuesta.json()


# --- AC-4: filas criticas ---------------------------------------------------


def test_alertas_marca_igual_o_menor_al_minimo_y_excluye_m_mas_1(motor, escenario_kpi):
    """AC-4: critico es `stock_actual <= stock_minimo` por fila; M+1 no lo es.

    INSTA aporta tres filas criticas: Papel Bond en "Operaciones" (9) y "Bodega"
    (10) e Insumo Cero en "Operaciones" (0). Papel Bond en "Archivo" (11) queda
    fuera aunque el agregado del producto este por encima del minimo.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        cuerpo = _leer_dashboard(cliente)

    claves = {
        (a["producto_nombre"], a["sede_nombre"], a["stock_actual"])
        for a in cuerpo["alertas"]
    }
    assert claves == {
        ("Papel Bond", "Operaciones", 9),
        ("Papel Bond", "Bodega", 10),
        ("Insumo Cero", "Operaciones", 0),
    }
    assert cuerpo["kpi"]["total_alertas"] == 3 == len(cuerpo["alertas"])


def test_alerta_incluye_minimo_cero_con_stock_cero(motor, escenario_kpi):
    """AC-4/D-1: una fila con stock 0 y minimo 0 es critica."""
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        alertas = _leer_dashboard(cliente)["alertas"]

    alerta = next(a for a in alertas if a["producto_nombre"] == "Insumo Cero")
    assert alerta["stock_actual"] == 0
    assert alerta["stock_minimo"] == 0


def test_producto_sin_inventario_no_genera_alerta(motor, escenario_kpi):
    """AC-4: un producto sin filas de inventario no constituye alerta."""
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        alertas = _leer_dashboard(cliente)["alertas"]

    nombres = {a["producto_nombre"] for a in alertas}
    assert "Producto Sin Inventario" not in nombres


def test_alerta_expone_los_campos_del_contrato(motor, escenario_kpi):
    """AC-4: cada fila de alerta trae exactamente los campos del plan §1.

    Feature 017 (D-9/AC-15): se observa con el Administrador de INSTA; el
    Superadmin ya no tiene esta lectura.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        alertas = _leer_dashboard(cliente)["alertas"]

    assert alertas, "el escenario tiene filas criticas"
    for alerta in alertas:
        assert set(alerta) == CAMPOS_ALERTA


def test_alertas_homonimos_se_atribuyen_por_institucion(motor, escenario_kpi):
    """AC-4/AC-7: los productos homonimos no se fusionan y cada fila lleva su institucion.

    Feature 017 (D-9/AC-15): cada Administrador ve solo su institucion; con dos
    lecturas se comprueba que "Papel Bond" conserva el `producto_id` de origen y
    nunca se fusiona entre instituciones.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente_a:
        alertas_a = _leer_dashboard(cliente_a)["alertas"]
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_b"]
    ) as cliente_b:
        alertas_b = _leer_dashboard(cliente_b)["alertas"]

    papel_a = [a for a in alertas_a if a["producto_nombre"] == "Papel Bond"]
    papel_b = [a for a in alertas_b if a["producto_nombre"] == "Papel Bond"]
    assert {a["producto_id"] for a in papel_a} == {
        escenario_kpi["producto_papel_a"]
    }
    assert {a["producto_id"] for a in papel_b} == {
        escenario_kpi["producto_papel_b"]
    }
    assert {a["institucion_id"] for a in papel_a} == {"INSTA"}
    assert {a["institucion_id"] for a in papel_b} == {"INSTB"}
    assert {a["institucion_nombre"] for a in papel_a} == {"Instituto Alfa"}
    assert {a["institucion_nombre"] for a in papel_b} == {"Instituto Beta"}


# ---------------------------------------------------------------------------
# T3 — Aislamiento, atribucion y cambio de umbral sin alertas persistidas
# (AC-5, AC-7, AC-8, AC-11, AC-12, AC-13)
# ---------------------------------------------------------------------------


def _conteo_filas_por_tabla(motor) -> dict[str, int]:
    """Cuenta las filas de cada tabla del esquema con Core tipado (sin SQL raw).

    Se usa para auditar que una lectura o un movimiento de stock no crea filas
    fuera de las tablas esperadas (no hay persistencia de alertas, AC-12/AC-13).
    """
    db = sessionmaker(bind=motor)()
    try:
        return {
            tabla.name: db.execute(
                select(func.count()).select_from(tabla)
            ).scalar_one()
            for tabla in Base.metadata.sorted_tables
        }
    finally:
        db.close()


def _cuerpo_movimiento(inventario_id: int, tipo: str, cantidad: int) -> dict:
    return {
        "tipo_movimiento": tipo,
        "cantidad": cantidad,
        "observacion": f"Movimiento {tipo} del escenario de umbral",
        "inventario_id": inventario_id,
    }


def _cuerpo_movimiento_sede(stock_sede_id: int, tipo: str, cantidad: int) -> dict:
    """Movimiento nuevo de la Feature 011 (referencia por `stock_sede_id`)."""
    return {
        "tipo_movimiento": tipo,
        "cantidad": cantidad,
        "observacion": f"Movimiento {tipo} del escenario de umbral por sede",
        "stock_sede_id": stock_sede_id,
    }


# --- AC-8: los cuatro roles limitados solo ven su institucion -----------------


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_rol_limitado_solo_ve_su_institucion_y_el_parametro_ajeno_se_ignora(
    motor, escenario_kpi, rol
):
    """AC-8: ningun KPI/alerta de INSTB aparece para un rol de INSTA.

    Un `institucion_id` adversarial en la query se ignora: la respuesta es identica
    a la peticion sin parametro. Las cifras (30 unidades, 3 alertas, 4
    departamentos) son las de INSTA, no las globales (33/4/5).
    """
    with _cliente(
        motor,
        rol,
        departamento_id=escenario_kpi["dep_op_a"],
        usuario_id=escenario_kpi["admin_a"],
    ) as cliente:
        sin_parametro = _leer_dashboard(cliente)
        con_parametro = cliente.get(
            RUTA_DASHBOARD, params={"institucion_id": escenario_kpi["inst_b"]}
        ).json()

    assert con_parametro == sin_parametro, "el parametro del cliente no amplia el ambito"
    assert sin_parametro["kpi"]["unidades_en_stock"] == 30
    assert sin_parametro["kpi"]["total_alertas"] == 3
    assert sin_parametro["kpi"]["total_departamentos"] == 4
    assert escenario_kpi["producto_papel_b"] not in {
        a["producto_id"] for a in sin_parametro["alertas"]
    }
    assert "INSTB" not in {a["institucion_id"] for a in sin_parametro["alertas"]}


# --- AC-11: ambito irresoluble responde 403 -----------------------------------


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_ambito_irresoluble_responde_403(motor, escenario_kpi, rol):
    """AC-11: un rol limitado sin institucion resoluble recibe 403, nunca global.

    El usuario no apunta a ningun departamento, de modo que el ambito no se deriva
    y el servidor deniega con 403 en vez de degradar a global.
    """
    with _cliente(motor, rol, departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 403, respuesta.text


# --- AC-5: KPI y listado son el mismo y unico conjunto ------------------------


def test_kpi_total_alertas_es_el_mismo_conjunto_que_el_listado(motor, escenario_kpi):
    """AC-5: `total_alertas` cuenta exactamente las filas del listado, sin fusionar.

    Feature 017 (D-9/AC-15): la lectura global ya no se expone; INSTA mantiene
    tres filas y el KPI equivale siempre a `len(alertas)`.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        insta = _leer_dashboard(cliente)

    assert insta["kpi"]["total_alertas"] == len(insta["alertas"]) == 3

    with _cliente(motor, "Superadmin", departamento_id=None) as supervisor:
        respuesta = supervisor.get(RUTA_DASHBOARD)
    assert respuesta.status_code == 403, respuesta.text


# --- AC-12/AC-13: cruce de umbral por movimiento real, sin persistir alertas --


def test_cruce_de_umbral_por_movimiento_real_no_persiste_alertas(motor, escenario_kpi):
    """AC-5/AC-12 (Feature 011): la sede critica entra y sale del log por el estado.

    Se parte de la sede Papel Bond/Operaciones en 9 (minimo 10, critica). Una
    ENTRADA real de 5 por el endpoint de movimientos (referencia nueva
    `stock_sede_id`) la lleva a 14 (no critica) y desaparece del log; una SALIDA
    real de 5 la devuelve a 9 y reaparece. El unico cambio de auditoria son las
    dos filas de `movimiento_inventario`; no se crea ninguna fila de alerta (el
    total de filas del esquema crece exactamente 2).
    """
    stock_sede_id = escenario_kpi["stock_sede_papel_op_a"]
    sede_id = escenario_kpi["sede_papel_op_a"]
    producto_id = escenario_kpi["producto_papel_a"]

    def _alerta_de_la_sede(cliente):
        return [
            a
            for a in _leer_dashboard(cliente)["alertas"]
            if a["sede_id"] == sede_id and a["producto_id"] == producto_id
        ]

    filas_antes = _conteo_filas_por_tabla(motor)

    with _cliente(
        motor,
        "Administrador",
        departamento_id=escenario_kpi["dep_op_a"],
        usuario_id=escenario_kpi["admin_a"],
    ) as cliente:
        assert _alerta_de_la_sede(cliente), "la sede 9/10 arranca critica"

        entrada = cliente.post(
            RUTA_MOVIMIENTOS,
            json=_cuerpo_movimiento_sede(stock_sede_id, "ENTRADA", 5),
        )
        assert entrada.status_code == 201, entrada.text
        assert _alerta_de_la_sede(cliente) == [], "la entrada la saca del umbral"
        kpi_sin_alerta = _leer_dashboard(cliente)["kpi"]

        salida = cliente.post(
            RUTA_MOVIMIENTOS,
            json=_cuerpo_movimiento_sede(stock_sede_id, "SALIDA", 5),
        )
        assert salida.status_code == 201, salida.text
        assert _alerta_de_la_sede(cliente), "la salida la vuelve a marcar critica"
        kpi_con_alerta = _leer_dashboard(cliente)["kpi"]

    assert kpi_sin_alerta["total_alertas"] == 2
    assert kpi_con_alerta["total_alertas"] == 3

    filas_despues = _conteo_filas_por_tabla(motor)
    diferencia_total = sum(filas_despues.values()) - sum(filas_antes.values())
    assert diferencia_total == 2, "solo los dos movimientos cambian el total de filas"
    assert (
        filas_despues["movimiento_inventario"] - filas_antes["movimiento_inventario"]
        == 2
    )


def test_no_existe_tabla_ni_columna_de_alertas():
    """AC-13/D-6: el log es derivado; no hay tabla ni columna de alertas.

    Se revisa el metadata ORM (la unica fuente del esquema en pruebas): ninguna
    tabla ni columna contiene "alerta".
    """
    for nombre_tabla in Base.metadata.tables:
        assert "alerta" not in nombre_tabla.lower(), nombre_tabla
    for tabla in Base.metadata.sorted_tables:
        for columna in tabla.columns:
            assert "alerta" not in columna.name.lower(), (tabla.name, columna.name)


# --- AC-7: escalar global unico y filas con atribucion institucional ----------


def test_superadmin_unidades_en_stock_recibe_403_ac_15(motor, escenario_kpi):
    """Feature 017 (D-9/AC-15): el KPI global de unidades se retira al Superadmin.

    El escalar global sigue verificado en el servicio del dashboard; la API ya no
    lo expone a Superadmin.
    """
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 403, respuesta.text
    assert "kpi" not in respuesta.json()


def test_superadmin_filas_de_alertas_y_actividad_recibe_403_ac_15(
    motor, escenario_kpi
):
    """Feature 017 (D-9/AC-15): la atribucion global se retira de la API.

    Se registra un movimiento real por institucion y se comprueba que el
    Superadmin recibe 403 sin alertas ni actividad.
    """
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente_a:
        entrada_a = cliente_a.post(
            RUTA_MOVIMIENTOS,
            json=_cuerpo_movimiento(escenario_kpi["inventario_papel_op_a"], "ENTRADA", 1),
        )
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_b"]
    ) as cliente_b:
        entrada_b = cliente_b.post(
            RUTA_MOVIMIENTOS,
            json=_cuerpo_movimiento(escenario_kpi["inventario_papel_b"], "ENTRADA", 1),
        )
    assert entrada_a.status_code == 201, entrada_a.text
    assert entrada_b.status_code == 201, entrada_b.text

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_DASHBOARD)

    assert respuesta.status_code == 403, respuesta.text
    assert set(respuesta.json()) == {"detail"}


# ---------------------------------------------------------------------------
# T4 — Actividad: limite, orden, atribucion y permiso del Solicitante
# (AC-6, AC-7, AC-10)
# ---------------------------------------------------------------------------


def _sembrar_movimiento(
    motor,
    inventario_id: int,
    fecha: datetime,
    *,
    tipo: str = "ENTRADA",
    cantidad: int = 1,
    observacion: str = "Sembrado para la actividad",
) -> int:
    """Inserta una fila de `movimiento_inventario` con fecha explicita.

    Devuelve el `movimiento_id` generado. Se usa el motor solo para fijar la fecha
    (control del orden); la lectura bajo prueba sigue siendo HTTP.
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


# --- AC-6/AC-7: limite fijo y orden determinista ------------------------------


def test_actividad_limita_a_diez_y_ordena_descendente(motor, escenario_kpi):
    """AC-6/D-5: solo las diez mas recientes, `fecha DESC` y desempate `id DESC`.

    Se siembran 12 movimientos en tres fechas: 6 recientes, 3 medias y 3 antiguas.
    El resultado debe traer las 6 recientes, las 3 medias y la mas nueva de las
    antiguas (10 en total); las dos antiguas de menor id quedan fuera. Una lectura
    sin limite traeria 12 y una ordenacion por insercion invertiria el empate.
    """
    inventario_id = escenario_kpi["inventario_papel_op_a"]
    fecha_nueva = datetime(2026, 3, 10, 9, 0, 0)
    fecha_media = datetime(2026, 2, 10, 9, 0, 0)
    fecha_vieja = datetime(2026, 1, 10, 9, 0, 0)

    nuevas = [
        _sembrar_movimiento(motor, inventario_id, fecha_nueva, observacion=f"nueva {i}")
        for i in range(6)
    ]
    medias = [
        _sembrar_movimiento(motor, inventario_id, fecha_media, observacion=f"media {i}")
        for i in range(3)
    ]
    viejas = [
        _sembrar_movimiento(motor, inventario_id, fecha_vieja, observacion=f"vieja {i}")
        for i in range(3)
    ]

    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        actividad = _leer_dashboard(cliente)["actividad_movimientos"]

    ids = [m["movimiento_id"] for m in actividad]
    esperado = sorted(nuevas, reverse=True) + sorted(medias, reverse=True) + [max(viejas)]
    assert ids == esperado, "diez mas recientes con desempate por id descendente"
    assert len(ids) == 10

    excluidas = {min(viejas), sorted(viejas)[1]}
    assert excluidas.isdisjoint(ids), "las dos filas mas antiguas no aparecen"

    fechas = [m["fecha_movimiento"] for m in actividad]
    assert fechas == sorted(fechas, reverse=True), "las fechas vienen descendentes"


def test_actividad_desempata_por_id_descendente_ante_fechas_iguales(motor, escenario_kpi):
    """AC-6/D-5: con la misma fecha, el orden es `movimiento_id` descendente.

    Tres movimientos con fecha identica: si el desempate no existiera saldrian en
    orden de insercion (id ascendente) y la prueba fallaria.
    """
    inventario_id = escenario_kpi["inventario_papel_op_a"]
    fecha = datetime(2026, 2, 20, 12, 0, 0)
    ids = [
        _sembrar_movimiento(motor, inventario_id, fecha, observacion=f"empate {i}")
        for i in range(3)
    ]

    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        actividad = _leer_dashboard(cliente)["actividad_movimientos"]

    assert [m["movimiento_id"] for m in actividad] == sorted(ids, reverse=True)


# --- AC-7: campos y atribucion por fila --------------------------------------


def test_actividad_expone_campos_ubicacion_y_atribucion(motor, escenario_kpi):
    """AC-7: cada fila trae los campos del DTO con su institucion y ubicacion.

    Feature 017 (D-9/AC-15): cada Administrador lee solo su institucion; con las
    dos lecturas se verifica `institucion_id`/`institucion_nombre`, el
    `producto_id` de origen (sin fusionar homonimos) y la `ubicacion`.
    """
    fecha = datetime(2026, 4, 1, 8, 0, 0)
    _sembrar_movimiento(
        motor, escenario_kpi["inventario_papel_op_a"], fecha, observacion="INSTA"
    )
    _sembrar_movimiento(
        motor, escenario_kpi["inventario_papel_b"], fecha, observacion="INSTB"
    )

    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente_a:
        actividad_a = _leer_dashboard(cliente_a)["actividad_movimientos"]
    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_b"]
    ) as cliente_b:
        actividad_b = _leer_dashboard(cliente_b)["actividad_movimientos"]

    propio = next(
        m for m in actividad_a if m["producto_id"] == escenario_kpi["producto_papel_a"]
    )
    ajeno = next(
        m for m in actividad_b if m["producto_id"] == escenario_kpi["producto_papel_b"]
    )

    for movimiento in (propio, ajeno):
        assert set(movimiento) == CAMPOS_ACTIVIDAD

    assert propio["institucion_id"] == "INSTA"
    assert propio["producto_nombre"] == "Papel Bond"
    assert propio["departamento_nombre"] == "Operaciones"
    assert propio["institucion_nombre"] == "Instituto Alfa"
    assert propio["ubicacion"] == "Operaciones (INSTA)"

    assert ajeno["institucion_id"] == "INSTB"
    assert ajeno["institucion_nombre"] == "Instituto Beta"
    assert ajeno["ubicacion"] == "Operaciones (INSTB)"


def test_actividad_de_rol_limitado_no_incluye_otra_institucion(motor, escenario_kpi):
    """AC-7/AC-8: un rol de INSTA no ve movimientos de INSTB en su actividad."""
    fecha = datetime(2026, 5, 1, 0, 0, 0)
    movimiento_propio = _sembrar_movimiento(
        motor, escenario_kpi["inventario_papel_op_a"], fecha
    )
    movimiento_ajeno = _sembrar_movimiento(
        motor, escenario_kpi["inventario_papel_b"], fecha
    )

    with _cliente(
        motor, "Administrador", departamento_id=escenario_kpi["dep_op_a"]
    ) as cliente:
        actividad = _leer_dashboard(cliente)["actividad_movimientos"]

    ids = {m["movimiento_id"] for m in actividad}
    assert ids == {movimiento_propio}
    assert movimiento_ajeno not in ids


# --- AC-10: el Solicitante no recibe actividad y conserva 403 -----------------


def test_solicitante_sin_actividad_y_403_en_el_historial(motor, escenario_kpi):
    """AC-10: el Solicitante no recibe actividad y el historial sigue denegado.

    Aunque existan movimientos, el dashboard del Solicitante responde 200 con
    `actividad_disponible=false` y lista vacia; la invocacion directa a
    `GET /inventario/movimientos` responde 403 (permiso vigente sin cambios).
    """
    _sembrar_movimiento(
        motor, escenario_kpi["inventario_papel_op_a"], datetime(2026, 1, 1, 0, 0, 0)
    )

    with _cliente(
        motor,
        "Solicitante",
        departamento_id=escenario_kpi["dep_op_a"],
        usuario_id=escenario_kpi["solic1_a"],
    ) as cliente:
        cuerpo = _leer_dashboard(cliente)
        directo = cliente.get(RUTA_MOVIMIENTOS)

    assert cuerpo["actividad_disponible"] is False
    assert cuerpo["actividad_movimientos"] == []
    assert directo.status_code == 403, directo.text
