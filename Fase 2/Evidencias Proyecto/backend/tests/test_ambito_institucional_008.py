"""T5 (Feature 008): helpers compartidos de ambito institucional.

Seam bajo prueba: las funciones publicas de `app.services.ambito_service` que
T6/T7 consumiran para filtrar y validar pertenencia institucional. La suite es
de **servicio** (motor SQLite en memoria), no de HTTP, porque aqui se fija el
contrato que los servicios usaran; las respuestas HTTP que dependen de el se
prueban en las suites de endpoints.

Fuente de verdad independiente: la decision D-4 de la spec (`docs/spec/features/
008-particionamiento-institucional/spec.md`):

  * objeto ajeno al ambito -> **404** (ocultacion, igual que inexistente);
  * `departamento_id` explicitamente ajeno -> **403**;
  * ambito irresoluble para rol limitado -> **403** (nunca global);
  * Superadmin (unico rol global) no se restringe.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.models import (
    Categoria,
    Departamento,
    Institucion,
    Inventario,
    Producto,
    Rol,
    Ticket,
    Usuario,
)
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

#: Centinela: identidad con `departamento_id=None` (institucion no resoluble).
_SIN_DEPARTAMENTO = object()


@pytest.fixture
def ambito(motor, datos_base):
    """`datos_base` (INST01) + una institucion ajena INST02 con su propio arbol.

    Devuelve los ids de ambos arboles y el `institucion_id` de cada uno. El
    catalogo/producto/inventario de INST02 llevan su `institucion_id` explicito
    (T2 dejo la columna nullable y T5 no la puebla en los servicios).
    """
    db = sessionmaker(bind=motor)()
    try:
        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
        )
        db.add(institucion_ajena)
        db.flush()

        departamento_ajeno = Departamento(
            nombre_dep="Bodega Sur",
            descripcion="Deposito ajeno",
            institucion_id="INST02",
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

        categoria_ajena = Categoria(
            nombre_cat="Solo Ajeno",
            descripcion_cat="Catalogo ajeno",
            institucion_id="INST02",
        )
        db.add(categoria_ajena)
        db.flush()

        producto_ajeno = Producto(
            nombre="Insumo Ajeno",
            descripcion="Producto ajeno",
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

        ticket_propio = Ticket(
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=datos_base["estado_ingresado_id"],
            asunto="Ticket propio",
            institucion_id="INST01",
        )
        db.add(ticket_propio)
        db.flush()

        ticket_ajeno = Ticket(
            usuario_id=usuario_ajeno.usuario_id,
            prioridad_id=datos_base["prioridad_id"],
            estado_id=datos_base["estado_ingresado_id"],
            asunto="Ticket ajeno",
            institucion_id="INST02",
        )
        db.add(ticket_ajeno)
        db.commit()

        return {
            **datos_base,
            "inst_propia": "INST01",
            "inst_ajena": "INST02",
            "usuario_ajeno_id": usuario_ajeno.usuario_id,
            "departamento_ajeno_id": departamento_ajeno.departamento_id,
            "categoria_ajena_id": categoria_ajena.categoria_id,
            "producto_ajeno_id": producto_ajeno.producto_id,
            "inventario_ajeno_id": inventario_ajeno.inventario_id,
            "ticket_propio_id": ticket_propio.ticket_id,
            "ticket_ajeno_id": ticket_ajeno.ticket_id,
        }
    finally:
        db.close()


def _identidad(rol: str, departamento_id) -> IdentidadAutenticada:
    """Identidad autenticada no persistida con `rol` y `departamento_id`."""
    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="Ambito",
        correo="sonda.ambito.008@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-ambito-008")


def _db(motor):
    return sessionmaker(bind=motor)()


# ---------------------------------------------------------------------------
# Resolucion del ambito
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rol,departamento_esperado",
    [
        ("Administrador", "INST01"),
        ("Bodeguero", "INST01"),
        ("Solicitante", "INST01"),
    ],
)
def test_institucion_de_identidad_resuelve_por_departamento(
    motor, ambito, rol, departamento_esperado
):
    db = _db(motor)
    try:
        identidad = _identidad(rol, ambito["departamento_id"])
        assert (
            ambito_service.institucion_de_identidad(db, identidad)
            == departamento_esperado
        )
    finally:
        db.close()


def test_institucion_de_identidad_sin_departamento_es_none(motor, ambito):
    db = _db(motor)
    try:
        assert (
            ambito_service.institucion_de_identidad(db, _identidad("Administrador", None))
            is None
        )
    finally:
        db.close()


def test_alcance_institucional_superadmin_es_none(motor, ambito):
    """Superadmin es el unico rol con alcance global (`None`)."""
    db = _db(motor)
    try:
        assert (
            ambito_service.alcance_institucional(
                db, _identidad("Superadmin", None)
            )
            is None
        )
    finally:
        db.close()


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
def test_alcance_institucional_rol_limitado_devuelve_su_institucion(motor, ambito, rol):
    db = _db(motor)
    try:
        assert (
            ambito_service.alcance_institucional(
                db, _identidad(rol, ambito["departamento_id"])
            )
            == "INST01"
        )
    finally:
        db.close()


@pytest.mark.parametrize("departamento_id", [None, 999999])
def test_alcance_institucional_irresoluble_responde_403(motor, ambito, departamento_id):
    """Sin institucion resoluble, un rol limitado nunca degrada a global (403)."""
    db = _db(motor)
    try:
        with pytest.raises(HTTPException) as excinfo:
            ambito_service.alcance_institucional(
                db, _identidad("Administrador", departamento_id)
            )
        assert excinfo.value.status_code == 403
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Extraccion de la institucion de cada entidad
# ---------------------------------------------------------------------------


def test_institucion_de_departamento(motor, ambito):
    db = _db(motor)
    try:
        assert (
            ambito_service.institucion_de_departamento(db, ambito["departamento_id"])
            == "INST01"
        )
        assert (
            ambito_service.institucion_de_departamento(
                db, ambito["departamento_ajeno_id"]
            )
            == "INST02"
        )
        assert ambito_service.institucion_de_departamento(db, 999999) is None
        assert ambito_service.institucion_de_departamento(db, None) is None
    finally:
        db.close()


def test_institucion_de_usuario(motor, ambito):
    db = _db(motor)
    try:
        propio = db.get(Usuario, ambito["usuario_id"])
        ajeno = db.get(Usuario, ambito["usuario_ajeno_id"])
        assert ambito_service.institucion_de_usuario(db, propio) == "INST01"
        assert ambito_service.institucion_de_usuario(db, ajeno) == "INST02"
        assert ambito_service.institucion_de_usuario(db, None) is None
    finally:
        db.close()


def test_institucion_de_inventario(motor, ambito):
    db = _db(motor)
    try:
        propio = db.get(Inventario, ambito["inventario_id"])
        ajeno = db.get(Inventario, ambito["inventario_ajeno_id"])
        assert ambito_service.institucion_de_inventario(db, propio) == "INST01"
        assert ambito_service.institucion_de_inventario(db, ajeno) == "INST02"
        assert ambito_service.institucion_de_inventario(db, None) is None
    finally:
        db.close()


def test_institucion_de_ticket(motor, ambito):
    db = _db(motor)
    try:
        propio = db.get(Ticket, ambito["ticket_propio_id"])
        ajeno = db.get(Ticket, ambito["ticket_ajeno_id"])
        assert ambito_service.institucion_de_ticket(db, propio) == "INST01"
        assert ambito_service.institucion_de_ticket(db, ajeno) == "INST02"
        assert ambito_service.institucion_de_ticket(db, None) is None
    finally:
        db.close()


def test_institucion_de_recurso_lee_la_columna(motor, ambito):
    """`institucion_de_recurso` sirve a las entidades con `institucion_id` propio."""
    db = _db(motor)
    try:
        producto = db.get(Producto, ambito["producto_ajeno_id"])
        categoria = db.get(Categoria, ambito["categoria_ajena_id"])
        departamento = db.get(Departamento, ambito["departamento_id"])
        assert ambito_service.institucion_de_recurso(producto) == "INST02"
        assert ambito_service.institucion_de_recurso(categoria) == "INST02"
        assert ambito_service.institucion_de_recurso(departamento) == "INST01"
        assert ambito_service.institucion_de_recurso(None) is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pertenencia y ocultacion
# ---------------------------------------------------------------------------


def test_pertenece_al_alcance_global_acepta_cualquier_institucion():
    assert ambito_service.pertenece_al_alcance("INST02", None) is True
    assert ambito_service.pertenece_al_alcance(None, None) is True


def test_pertenece_al_alcance_limitado_solo_la_propia():
    assert ambito_service.pertenece_al_alcance("INST01", "INST01") is True
    assert ambito_service.pertenece_al_alcance("INST02", "INST01") is False
    assert ambito_service.pertenece_al_alcance(None, "INST01") is False


def test_exigir_pertenencia_oculta_recurso_ajeno_con_404():
    with pytest.raises(HTTPException) as excinfo:
        ambito_service.exigir_pertenencia(
            "INST02", "INST01", detalle="Producto no encontrado"
        )
    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Producto no encontrado"


def test_exigir_pertenencia_acepta_recurso_propio_y_global():
    # No lanza en ninguno de los dos casos.
    ambito_service.exigir_pertenencia("INST01", "INST01", detalle="x")
    ambito_service.exigir_pertenencia("INST02", None, detalle="x")


# ---------------------------------------------------------------------------
# Filtro de consultas
# ---------------------------------------------------------------------------


def test_filtrar_por_institucion_global_no_filtra(motor, ambito):
    db = _db(motor)
    try:
        consulta = ambito_service.filtrar_por_institucion(
            db.query(Categoria), Categoria.institucion_id, None
        )
        assert len(consulta.all()) == len(db.query(Categoria).all())
    finally:
        db.close()


def test_filtrar_por_institucion_limitado_acota(motor, ambito):
    db = _db(motor)
    try:
        consulta = ambito_service.filtrar_por_institucion(
            db.query(Categoria), Categoria.institucion_id, "INST02"
        )
        instituciones = {c.institucion_id for c in consulta.all()}
        assert instituciones == {"INST02"}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Departamento explicito ajeno: 403 (D-4)
# ---------------------------------------------------------------------------


def test_validar_departamento_ajeno_responde_403(motor, ambito):
    db = _db(motor)
    try:
        with pytest.raises(HTTPException) as excinfo:
            ambito_service.validar_departamento_en_alcance(
                db, ambito["departamento_ajeno_id"], "INST01"
            )
        assert excinfo.value.status_code == 403
    finally:
        db.close()


def test_validar_departamento_propio_y_global_no_lanza(motor, ambito):
    db = _db(motor)
    try:
        ambito_service.validar_departamento_en_alcance(
            db, ambito["departamento_id"], "INST01"
        )
        ambito_service.validar_departamento_en_alcance(
            db, ambito["departamento_ajeno_id"], None
        )
    finally:
        db.close()
