"""T3 (Feature 011): modelo ORM del modelo organizacional — pruebas de metadata.

Seam bajo prueba: **la metadata/DDL del ORM** (`Base.metadata`) ejercida sobre
SQLite en memoria con FKs activadas (`tests/conftest.py::motor`). Es la fase de
modelo de la Feature 011: aqui se fija que las entidades nuevas existan, que sus
claves y `CHECK` hagan cumplir el contrato de la spec y que los datos legados
sigan siendo representables.

Trazabilidad AC (spec 011 §5): AC-2 (stock por sede sin segunda fuente),
AC-4 (encargados como asociacion auxiliar), AC-9 (instantanea de sede en ticket)
y las restricciones §7 (filas legadas y sus FK intactas).

Fase ROJA de TDD: las entidades `Sede`, `StockSede` y `DepartamentoEncargado` y
las columnas `*.sede_id`/`stock_sede_id` no existen todavia; cada prueba falla con
`KeyError`/`AttributeError` explicito o `pytest.fail`, nunca por sintaxis.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models import (
    Departamento,
    Institucion,
    Inventario,
    MovimientoInventario,
    Rol,
    Ticket,
    Usuario,
)

#: Entidades nuevas y columnas nuevas que la Feature 011 agrega al modelo.
TABLAS_NUEVAS = ("sede", "stock_sede", "departamento_encargado")
COLUMNAS_NUEVAS = (
    ("departamento", "sede_id"),
    ("usuario", "sede_id"),
    ("ticket", "sede_id"),
    ("movimiento_inventario", "stock_sede_id"),
)


def _modelo(nombre: str):
    """Entidad del paquete `app.models`, o `pytest.fail` si T3 aun no la creo."""
    import app.models as modelos

    entidad = getattr(modelos, nombre, None)
    if entidad is None:
        pytest.fail(
            f"capacidad ausente (T3): `app.models.{nombre}` no existe todavia; "
            "la Feature 011 lo crea en T3 y hasta entonces esta prueba esta en rojo."
        )
    return entidad


def _sesion(motor):
    return sessionmaker(autocommit=False, autoflush=False, bind=motor)()


def _fila_base(motor) -> dict:
    """Institucion, rol, departamento y usuario minimos para las pruebas de metadata."""
    db = _sesion(motor)
    try:
        rol = Rol(rol_id=1, nombre_rol="Administrador", descripcion="Rol de prueba")
        db.add(rol)
        institucion = Institucion(
            institucion_id="INST011", nombre="Instituto 011", direccion="Calle 1"
        )
        db.add(institucion)
        db.flush()
        departamento = Departamento(
            nombre_dep="Operaciones", descripcion="Departamento de prueba",
            institucion_id=institucion.institucion_id,
        )
        db.add(departamento)
        db.flush()
        usuario = Usuario(
            nombre="Ana", apellido="Perez", correo="ana.011@compustock.cl",
            departamento_id=departamento.departamento_id, rol_id=1,
        )
        db.add(usuario)
        db.flush()
        db.commit()
        return {
            "institucion_id": institucion.institucion_id,
            "departamento_id": departamento.departamento_id,
            "usuario_id": usuario.usuario_id,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Metadata: entidades y columnas nuevas
# ---------------------------------------------------------------------------


def test_metadata_declara_las_entidades_nuevas(motor):
    """AC-2/AC-4: las tres estructuras nuevas forman parte de la metadata."""
    tablas = set(Base.metadata.tables)
    for tabla in TABLAS_NUEVAS:
        assert tabla in tablas, f"falta la tabla {tabla}"


def test_columnas_nuevas_son_nullable_con_su_fk(motor):
    """AC-9 y restricciones §7: las columnas nuevas son nullable y con FK.

    `departamento.sede_id`, `usuario.sede_id`, `ticket.sede_id` y
    `movimiento_inventario.stock_sede_id` no son `NOT NULL`: la obligatoriedad es
    operativa (spec D-5) y los registros legados deben seguir siendo
    representables. `inventario_id` conserva su FK a la tabla legada, pero deja de
    ser obligatorio para admitir los movimientos **nuevos**, que se enlazan por
    `stock_sede_id` y dejan `inventario_id` nulo (spec D-2 y §7).
    """
    destinos = {
        ("departamento", "sede_id"): "sede",
        ("usuario", "sede_id"): "sede",
        ("ticket", "sede_id"): "sede",
        ("movimiento_inventario", "stock_sede_id"): "stock_sede",
    }
    for tabla, columna in COLUMNAS_NUEVAS:
        assert tabla in Base.metadata.tables, f"falta la tabla {tabla}"
        columnas = Base.metadata.tables[tabla].columns
        assert columna in columnas, f"falta {tabla}.{columna}"
        assert columnas[columna].nullable is True, f"{tabla}.{columna} debe ser nullable"
        fks = {fk.target_fullname for fk in columnas[columna].foreign_keys}
        assert any(
            destinos[(tabla, columna)] in fk for fk in fks
        ), f"{tabla}.{columna} debe referenciar {destinos[(tabla, columna)]}"

    columnas_legadas = Base.metadata.tables["movimiento_inventario"].columns
    assert columnas_legadas["inventario_id"].nullable is True, (
        "un movimiento nuevo se enlaza por stock_sede_id y deja inventario_id nulo"
    )
    assert {
        fk.target_fullname for fk in columnas_legadas["inventario_id"].foreign_keys
    } == {"inventario.inventario_id"}, "la FK historica se conserva"


# ---------------------------------------------------------------------------
# AC-2: sede y stock por sede
# ---------------------------------------------------------------------------


def test_sede_pertenece_a_una_institucion_y_declara_unicidad_compuesta(motor):
    """AC-2/AC-3: la sede es local a su institucion y sirve de destino a la FK."""
    Sede = _modelo("Sede")
    columnas = Base.metadata.tables["sede"].columns
    assert columnas["institucion_id"].nullable is False, (
        "cada sede pertenece a exactamente una institucion"
    )
    unicos = {
        tuple(sorted(restriccion.columns.keys()))
        for restriccion in Base.metadata.tables["sede"].constraints
        if restriccion.__class__.__name__ == "UniqueConstraint"
    }
    assert ("institucion_id", "sede_id") in unicos, (
        "la sede necesita la clave compuesta que la FK de stock_sede usa como destino"
    )
    assert columnas["direccion"].nullable is True, "la direccion es opcional"

    datos = _fila_base(motor)
    db = _sesion(motor)
    try:
        sede = Sede(nombre="Sede Central", institucion_id=datos["institucion_id"])
        db.add(sede)
        db.commit()
        db.refresh(sede)

        assert sede.sede_id is not None
        assert sede.institucion_id == datos["institucion_id"]
        assert sede.direccion is None
    finally:
        db.close()


def test_stock_sede_exige_unicidad_por_sede_y_producto(motor, datos_base):
    """AC-2: una sola fila de saldo por `(sede, producto)`."""
    Sede = _modelo("Sede")
    StockSede = _modelo("StockSede")
    sede_id = _crear_sede(motor, Sede, datos_base["institucion_id"], "Unica")

    db = _sesion(motor)
    try:
        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=datos_base["producto_id"],
                stock_actual=10,
                institucion_id=datos_base["institucion_id"],
            )
        )
        db.commit()

        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=datos_base["producto_id"],
                stock_actual=3,
                institucion_id=datos_base["institucion_id"],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_stock_sede_rechaza_saldos_negativos(motor, datos_base):
    """AC-2: el `CHECK` del esquema impide un saldo negativo."""
    Sede = _modelo("Sede")
    StockSede = _modelo("StockSede")
    sede_id = _crear_sede(motor, Sede, datos_base["institucion_id"], "No negativa")

    db = _sesion(motor)
    try:
        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=datos_base["producto_id"],
                stock_actual=-1,
                institucion_id=datos_base["institucion_id"],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_stock_sede_rechaza_producto_de_otra_institucion(motor, dos_instituciones):
    """AC-2/AC-3: las FK compuestas impiden asociar sede y producto cruzados."""
    Sede = _modelo("Sede")
    StockSede = _modelo("StockSede")
    sede_id = _crear_sede(motor, Sede, dos_instituciones["inst_propia"], "Propia")

    db = _sesion(motor)
    try:
        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=dos_instituciones["producto_homonimo_ajeno_id"],
                stock_actual=5,
                institucion_id=dos_instituciones["inst_propia"],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_sede_expone_su_stock_y_su_institucion(motor, datos_base):
    """AC-2: las relaciones ORM de la sede resuelven sus saldos y su institucion."""
    Sede = _modelo("Sede")
    StockSede = _modelo("StockSede")
    sede_id = _crear_sede(motor, Sede, datos_base["institucion_id"], "Relacionada")

    db = _sesion(motor)
    try:
        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=datos_base["producto_id"],
                stock_actual=7,
                institucion_id=datos_base["institucion_id"],
            )
        )
        db.commit()

        sede = db.get(Sede, sede_id)
        assert sede.institucion.institucion_id == datos_base["institucion_id"]
        assert len(sede.stocks) == 1
        assert sede.stocks[0].stock_actual == 7
        assert sede.stocks[0].producto.producto_id == datos_base["producto_id"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AC-4: asociacion auxiliar de encargados
# ---------------------------------------------------------------------------


def test_departamento_encargado_es_auxiliar_y_con_unicidad(motor):
    """AC-4: la tabla puente admite pares unicos y rechaza repetidos."""
    DepartamentoEncargado = _modelo("DepartamentoEncargado")
    datos = _fila_base(motor)

    db = _sesion(motor)
    try:
        db.add(
            DepartamentoEncargado(
                departamento_id=datos["departamento_id"],
                usuario_id=datos["usuario_id"],
            )
        )
        db.commit()

        db.add(
            DepartamentoEncargado(
                departamento_id=datos["departamento_id"],
                usuario_id=datos["usuario_id"],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_departamento_encargado_exige_referencias_existentes(motor):
    """AC-4: las FK locales rechazan un departamento o usuario inexistente."""
    DepartamentoEncargado = _modelo("DepartamentoEncargado")
    datos = _fila_base(motor)

    db = _sesion(motor)
    try:
        db.add(
            DepartamentoEncargado(
                departamento_id=datos["departamento_id"], usuario_id=999_999
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AC-9 y restricciones §7: instantanea de sede y datos legados
# ---------------------------------------------------------------------------


def test_las_entidades_legadas_conservan_su_estructura(motor):
    """Restricciones §7: `inventario` no se reescribe ni pierde su unicidad."""
    inspector = inspect(motor)
    columnas = {columna["name"] for columna in inspector.get_columns("inventario")}
    assert {"inventario_id", "stock_actual", "departamento_id", "producto_id"} <= columnas
    unicos = {
        tuple(sorted(restriccion["column_names"]))
        for restriccion in inspector.get_unique_constraints("inventario")
    }
    assert ("departamento_id", "producto_id") in unicos, (
        "la unicidad departamental legada se conserva"
    )


def test_movimiento_legado_sin_stock_sede_sigue_siendo_valido(motor, datos_base):
    """Restricciones §7: un movimiento historico sin referencia nueva es valido."""
    db = _sesion(motor)
    try:
        movimiento = MovimientoInventario(
            tipo_movimiento="ENTRADA",
            cantidad=4,
            observacion="historial legado",
            inventario_id=datos_base["inventario_id"],
        )
        db.add(movimiento)
        db.commit()
        db.refresh(movimiento)

        assert movimiento.movimiento_id is not None
        assert movimiento.stock_sede_id is None
        inventario = db.get(Inventario, datos_base["inventario_id"])
        assert inventario.stock_actual == 50, "el saldo legado no se altera"
    finally:
        db.close()


def test_movimiento_nuevo_puede_referenciar_stock_sede(motor, datos_base):
    """AC-2/AC-9: un movimiento nuevo se enlaza al stock por sede."""
    Sede = _modelo("Sede")
    StockSede = _modelo("StockSede")
    sede_id = _crear_sede(motor, Sede, datos_base["institucion_id"], "Con auditoria")

    db = _sesion(motor)
    try:
        fila = StockSede(
            sede_id=sede_id,
            producto_id=datos_base["producto_id"],
            stock_actual=9,
            institucion_id=datos_base["institucion_id"],
        )
        db.add(fila)
        db.flush()

        db.add(
            MovimientoInventario(
                tipo_movimiento="ENTRADA",
                cantidad=9,
                observacion="consolidacion",
                stock_sede_id=fila.stock_sede_id,
            )
        )
        db.commit()

        movimiento = db.execute(select(MovimientoInventario)).scalars().one()
        assert movimiento.inventario_id is None
        assert movimiento.stock_sede.stock_actual == 9
        assert movimiento.stock_sede.sede.sede_id == sede_id
    finally:
        db.close()


def test_ticket_y_departamento_exponen_su_sede(motor, datos_base):
    """AC-9: departamento, usuario y ticket resuelven su sede por relacion ORM."""
    Sede = _modelo("Sede")
    sede_id = _crear_sede(motor, Sede, datos_base["institucion_id"], "Ticket")

    db = _sesion(motor)
    try:
        departamento = db.get(Departamento, datos_base["departamento_id"])
        departamento.sede_id = sede_id
        usuario = db.get(Usuario, datos_base["usuario_id"])
        usuario.sede_id = sede_id

        ticket = Ticket(
            usuario_id=datos_base["usuario_id"],
            prioridad_id=datos_base["prioridad_id"],
            estado_id=datos_base["estado_ingresado_id"],
            asunto="Ticket con sede",
            institucion_id=datos_base["institucion_id"],
            sede_id=sede_id,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        assert departamento.sede.sede_id == sede_id
        assert usuario.sede.sede_id == sede_id
        assert ticket.sede.sede_id == sede_id
    finally:
        db.close()


def _crear_sede(motor, Sede, institucion_id: str, nombre: str) -> int:
    """Crea una sede y devuelve su id (ayudante compartido de estas pruebas)."""
    db = _sesion(motor)
    try:
        sede = Sede(nombre=nombre, institucion_id=institucion_id)
        db.add(sede)
        db.commit()
        db.refresh(sede)
        return sede.sede_id
    finally:
        db.close()
