"""(Feature 009, T6): contrato del read model `obtener_dashboard_analitico`.

Seam bajo prueba: la funcion publica de `app.services.dashboard_service` sobre un
motor SQLite en memoria. Como en `test_ambito_institucional_008.py`, la suite es
de **servicio** y no de HTTP: aqui se fija el contrato que T7 consumira desde el
router. Las respuestas HTTP equivalentes (200/401/403, response_model, OpenAPI)
se prueban en `tests/api/test_dashboard_analitico.py`, que queda rojo hasta que
T7 publique la ruta.

Las expectativas se derivan de las decisiones D-1..D-5 de la spec
(`docs/spec/features/009-dashboard-analitico-alertas/spec.md`):

  * unidades en stock: escalar global unico para Superadmin, por institucion para
    el resto (D-4 #1);
  * tickets activos: excluye solo el nombre literal "Cerrado" y respeta el
    alcance de tickets por rol (D-4 #2);
  * departamentos: por PK, incluidos los que no tienen inventario (D-4 #3);
  * alertas: filas criticas con `stock_actual <= stock_minimo`, y el KPI equivale
    a `len(alertas)` (D-1/D-4 #4/AC-5);
  * actividad: disponible para Superadmin/Administrador/Bodeguero, con orden
    `fecha DESC, id DESC` y limite 10; para Solicitante, `False` y lista vacia
    (D-5/AC-10);
  * ambito irresoluble para rol limitado: **403** (D-3/AC-11).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

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
    Ticket,
    Usuario,
)
from app.services import ambito_service, dashboard_service
from app.services.auth_service import IdentidadAutenticada

#: Stock minimo del producto "Papel Bond" y sus filas de borde (M-1/M/M+1).
M_PAPEL = 10


def _identidad(
    rol: str, departamento_id: int | None, usuario_id: int = 9999
) -> IdentidadAutenticada:
    """Identidad autenticada con el rol, el departamento y el id de usuario dados.

    El usuario no se persiste: la autorizacion solo lee `usuario.rol.nombre_rol`
    y `usuario.departamento_id -> departamento` por ORM, igual que en el resto de
    la suite.
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Servicio",
        correo="sonda.servicio@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-dashboard-servicio")


@pytest.fixture
def escenario(motor):
    """Dos instituciones con valores distinguibles por cada regla del KPI.

    INSTA "Instituto Alfa":
      * departamentos "Operaciones", "Bodega", "Archivo" y "Sin Inventario"
        (vacio) => 4 registros (AC-3).
      * "Papel Bond" (minimo 10) con filas 9 (M-1), 10 (M) y 11 (M+1) (AC-4).
      * "Insumo Cero" (minimo 0) con una fila 0 (AC-4).
      * "Producto Sin Inventario" (minimo 5) sin filas (AC-4).
      * tickets con estados "Cerrado", "cerrado", "CERRADO", "EnCurso" y
        "Cancelado" (AC-2).
      => unidades 9+10+11+0 = 30; departamentos 4; alertas 3; tickets activos 4.

    INSTB "Instituto Beta":
      * "Operaciones" homonimo de INSTA (AC-3) y "Papel Bond" homonimo (minimo
        10) con una fila 3 (AC-4).
      => unidades 3; departamentos 1; alertas 1.
    """
    db = sessionmaker(bind=motor)()
    try:
        inst_a = Institucion(institucion_id="INSTA", nombre="Instituto Alfa", rut="11-1")
        inst_b = Institucion(institucion_id="INSTB", nombre="Instituto Beta", rut="22-2")
        db.add_all([inst_a, inst_b])
        db.flush()

        roles: dict[str, Rol] = {}
        for nombre in ("Superadmin", "Administrador", "Bodeguero", "Solicitante"):
            rol = Rol(nombre_rol=nombre, descripcion=f"Rol {nombre}")
            db.add(rol)
            db.flush()
            roles[nombre] = rol

        def departamento(nombre: str, institucion_id: str) -> Departamento:
            dep = Departamento(
                nombre_dep=nombre, descripcion=nombre, institucion_id=institucion_id
            )
            db.add(dep)
            db.flush()
            return dep

        dep_op_a = departamento("Operaciones", "INSTA")
        dep_bod_a = departamento("Bodega", "INSTA")
        dep_arc_a = departamento("Archivo", "INSTA")
        dep_vacia_a = departamento("Sin Inventario", "INSTA")
        dep_op_b = departamento("Operaciones", "INSTB")

        def usuario(nombre: str, rol: str, departamento_id: int) -> Usuario:
            u = Usuario(
                nombre=nombre,
                apellido="Escenario",
                correo=f"{nombre.lower()}.{rol.lower()}@compustock.cl",
                departamento_id=departamento_id,
                rol_id=roles[rol].rol_id,
            )
            db.add(u)
            db.flush()
            return u

        admin_a = usuario("Ada", "Administrador", dep_op_a.departamento_id)
        solic1_a = usuario("Sol", "Solicitante", dep_op_a.departamento_id)
        solic2_a = usuario("Dos", "Solicitante", dep_op_a.departamento_id)
        admin_b = usuario("Beto", "Administrador", dep_op_b.departamento_id)

        def categoria(institucion_id: str) -> Categoria:
            cat = Categoria(
                nombre_cat="Papeleria",
                descripcion_cat="Papeleria",
                institucion_id=institucion_id,
            )
            db.add(cat)
            db.flush()
            return cat

        cat_a = categoria("INSTA")
        cat_b = categoria("INSTB")

        def producto(nombre: str, stock_minimo: int, cat: Categoria) -> Producto:
            prod = Producto(
                nombre=nombre,
                descripcion=nombre,
                unidad_medida="UNIDAD",
                stock_minimo=stock_minimo,
                categoria_id=cat.categoria_id,
                institucion_id=cat.institucion_id,
            )
            db.add(prod)
            db.flush()
            return prod

        papel_a = producto("Papel Bond", M_PAPEL, cat_a)
        cero_a = producto("Insumo Cero", 0, cat_a)
        producto("Producto Sin Inventario", 5, cat_a)
        papel_b = producto("Papel Bond", M_PAPEL, cat_b)

        def inventario(
            prod: Producto, dep: Departamento, stock: int
        ) -> Inventario:
            inv = Inventario(
                stock_actual=stock,
                ubicacion=f"{dep.nombre_dep} ({prod.institucion_id})",
                departamento_id=dep.departamento_id,
                producto_id=prod.producto_id,
                institucion_id=prod.institucion_id,
            )
            db.add(inv)
            db.flush()
            return inv

        inv_papel_op_a = inventario(papel_a, dep_op_a, M_PAPEL - 1)
        inventario(papel_a, dep_bod_a, M_PAPEL)
        inventario(papel_a, dep_arc_a, M_PAPEL + 1)
        inventario(cero_a, dep_op_a, 0)
        inventario(papel_b, dep_op_b, 3)

        prioridad = Prioridad(nombre="ALTA", descripcion="Prioridad alta")
        db.add(prioridad)
        db.flush()

        estados: dict[str, EstadoTicket] = {}
        for nombre in ("Cerrado", "cerrado", "CERRADO", "EnCurso", "Cancelado"):
            estado = EstadoTicket(nombre=nombre, descripcion=nombre)
            db.add(estado)
            db.flush()
            estados[nombre] = estado

        def ticket(u: Usuario, estado_nombre: str, institucion_id: str) -> Ticket:
            t = Ticket(
                usuario_id=u.usuario_id,
                prioridad_id=prioridad.prioridad_id,
                estado_id=estados[estado_nombre].estado_id,
                asunto=f"Ticket {estado_nombre}",
                descripcion="Sembrado para el escenario de servicio.",
                institucion_id=institucion_id,
            )
            db.add(t)
            db.flush()
            return t

        ticket(solic1_a, "EnCurso", "INSTA")
        ticket(solic1_a, "Cerrado", "INSTA")
        ticket(solic1_a, "cerrado", "INSTA")
        ticket(solic2_a, "CERRADO", "INSTA")
        ticket(solic2_a, "Cancelado", "INSTA")
        ticket(admin_b, "EnCurso", "INSTB")
        db.commit()

        return {
            "dep_op_a": dep_op_a.departamento_id,
            "dep_op_b": dep_op_b.departamento_id,
            "dep_vacia_a": dep_vacia_a.departamento_id,
            "admin_a": admin_a.usuario_id,
            "solic1_a": solic1_a.usuario_id,
            "producto_papel_a": papel_a.producto_id,
            "producto_papel_b": papel_b.producto_id,
            "inventario_papel_op_a": inv_papel_op_a.inventario_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AC-13/AC-1: sin datos
# ---------------------------------------------------------------------------


def test_sin_datos_devuelve_ceros_y_listas_vacias(motor):
    """Sin filas, el servicio responde KPI en cero y listas vacias (AC-1/AC-13)."""
    db = sessionmaker(bind=motor)()
    try:
        resultado = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Superadmin", None)
        )
    finally:
        db.close()

    assert resultado.kpi.model_dump() == {
        "unidades_en_stock": 0,
        "tickets_activos": 0,
        "total_departamentos": 0,
        "total_alertas": 0,
    }
    assert resultado.alertas == []
    assert resultado.actividad_disponible is True
    assert resultado.actividad_movimientos == []


# ---------------------------------------------------------------------------
# AC-1: unidades en stock por ambito
# ---------------------------------------------------------------------------


def test_unidades_en_stock_suma_solo_el_ambito(motor, escenario):
    """AC-1/AC-8: la suma no cruza instituciones y el global es un unico escalar."""
    db = sessionmaker(bind=motor)()
    try:
        insta = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_a"])
        )
        instb = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_b"])
        )
        global_ = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Superadmin", None)
        )
    finally:
        db.close()

    assert insta.kpi.unidades_en_stock == 30
    assert instb.kpi.unidades_en_stock == 3
    assert isinstance(global_.kpi.unidades_en_stock, int)
    assert global_.kpi.unidades_en_stock == 33


# ---------------------------------------------------------------------------
# AC-2: tickets activos
# ---------------------------------------------------------------------------


def test_tickets_activos_excluye_solo_el_nombre_literal(motor, escenario):
    """AC-2: solo el nombre exacto "Cerrado" se excluye; el casing distinto cuenta."""
    db = sessionmaker(bind=motor)()
    try:
        insta = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_a"])
        )
    finally:
        db.close()

    assert insta.kpi.tickets_activos == 4


def test_tickets_activos_solicitante_cuenta_solo_los_propios(motor, escenario):
    """AC-2/AC-9: el Solicitante cuenta solo sus propios tickets activos."""
    db = sessionmaker(bind=motor)()
    try:
        insta = dashboard_service.obtener_dashboard_analitico(
            db,
            _identidad("Solicitante", escenario["dep_op_a"], escenario["solic1_a"]),
        )
    finally:
        db.close()

    assert insta.kpi.tickets_activos == 2


# ---------------------------------------------------------------------------
# AC-3: departamentos por PK
# ---------------------------------------------------------------------------


def test_departamentos_cuenta_por_pk_incluido_sin_inventario(motor, escenario):
    """AC-3: se cuentan registros de departamento, incluido uno sin inventario."""
    db = sessionmaker(bind=motor)()
    try:
        insta = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_a"])
        )
        global_ = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Superadmin", None)
        )
    finally:
        db.close()

    assert insta.kpi.total_departamentos == 4
    assert global_.kpi.total_departamentos == 5


# ---------------------------------------------------------------------------
# AC-4/AC-5: alertas por fila y KPI == len(alertas)
# ---------------------------------------------------------------------------


def test_alertas_por_fila_y_kpi_igual_al_listado(motor, escenario):
    """AC-4/AC-5: critico es `stock_actual <= stock_minimo` por fila; M+1 queda fuera."""
    db = sessionmaker(bind=motor)()
    try:
        insta = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_a"])
        )
        global_ = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Superadmin", None)
        )
    finally:
        db.close()

    claves = {
        (a.producto_nombre, a.departamento_nombre, a.stock_actual)
        for a in insta.alertas
    }
    assert claves == {
        ("Papel Bond", "Operaciones", 9),
        ("Papel Bond", "Bodega", 10),
        ("Insumo Cero", "Operaciones", 0),
    }
    assert insta.kpi.total_alertas == len(insta.alertas) == 3
    assert global_.kpi.total_alertas == len(global_.alertas) == 4


def test_alerta_incluye_minimo_cero_y_atribucion_global(motor, escenario):
    """AC-4/AC-7: una fila con stock 0 y minimo 0 es critica; Superadmin atribuye."""
    db = sessionmaker(bind=motor)()
    try:
        global_ = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Superadmin", None)
        )
    finally:
        db.close()

    cero = next(
        a for a in global_.alertas if a.producto_nombre == "Insumo Cero"
    )
    assert cero.stock_actual == 0
    assert cero.stock_minimo == 0

    papel = [a for a in global_.alertas if a.producto_nombre == "Papel Bond"]
    assert {a.producto_id for a in papel} == {
        escenario["producto_papel_a"],
        escenario["producto_papel_b"],
    }
    assert {a.institucion_id for a in papel} == {"INSTA", "INSTB"}
    assert {a.institucion_nombre for a in papel} == {
        "Instituto Alfa",
        "Instituto Beta",
    }

    assert "Producto Sin Inventario" not in {a.producto_nombre for a in global_.alertas}


# ---------------------------------------------------------------------------
# AC-6/AC-7: actividad (orden, limite, atribucion)
# ---------------------------------------------------------------------------


def test_actividad_ordena_por_fecha_y_id_descendente_con_limite(motor, escenario):
    """AC-6: solo las diez mas recientes, `fecha DESC` y desempate `id DESC`."""
    db = sessionmaker(bind=motor)()
    try:
        inventario_id = escenario["inventario_papel_op_a"]
        nueva = datetime(2026, 3, 10, 9, 0, 0)
        media = datetime(2026, 2, 10, 9, 0, 0)
        vieja = datetime(2026, 1, 10, 9, 0, 0)

        def sembrar(fecha: datetime) -> int:
            mov = MovimientoInventario(
                tipo_movimiento="ENTRADA",
                cantidad=1,
                fecha_movimiento=fecha,
                observacion="Sembrado para la actividad",
                inventario_id=inventario_id,
            )
            db.add(mov)
            db.flush()
            return mov.movimiento_id

        nuevas = [sembrar(nueva) for _ in range(6)]
        medias = [sembrar(media) for _ in range(3)]
        viejas = [sembrar(vieja) for _ in range(3)]
        db.commit()

        resultado = dashboard_service.obtener_dashboard_analitico(
            db, _identidad("Administrador", escenario["dep_op_a"])
        )
        solicitante = dashboard_service.obtener_dashboard_analitico(
            db,
            _identidad("Solicitante", escenario["dep_op_a"], escenario["solic1_a"]),
        )
    finally:
        db.close()

    ids = [m.movimiento_id for m in resultado.actividad_movimientos]
    esperado = sorted(nuevas, reverse=True) + sorted(medias, reverse=True) + [max(viejas)]
    assert ids == esperado
    assert len(ids) == 10

    fechas = [m.fecha_movimiento for m in resultado.actividad_movimientos]
    assert fechas == sorted(fechas, reverse=True)

    assert solicitante.actividad_disponible is False
    assert solicitante.actividad_movimientos == []


# ---------------------------------------------------------------------------
# AC-11: ambito irresoluble de un rol limitado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_ambito_irresoluble_responde_403(motor, escenario, rol):
    """AC-11: un rol limitado sin institucion resoluble recibe 403, nunca global."""
    db = sessionmaker(bind=motor)()
    try:
        with pytest.raises(HTTPException) as excinfo:
            dashboard_service.obtener_dashboard_analitico(
                db, _identidad(rol, None)
            )
    finally:
        db.close()

    assert excinfo.value.status_code == 403


def test_alcance_institucional_global_para_superadmin(motor):
    """D-3: solo Superadmin resuelve `None` (alcance global); no exige institucion."""
    db = sessionmaker(bind=motor)()
    try:
        assert (
            ambito_service.alcance_institucional(db, _identidad("Superadmin", None))
            is None
        )
    finally:
        db.close()
