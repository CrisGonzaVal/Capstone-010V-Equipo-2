"""Feature 008 (T2): pertenencia institucional y claves compuestas del modelo.

Seam bajo prueba: el **modelo ORM y las constraints que el esquema exige**. La
tarea T2 define el modelo y el DDL de instalacion nueva; los servicios que
pueblan `institucion_id` llegan en T5-T7, por eso aqui se ejercita la integridad
directamente contra la sesion, con `PRAGMA foreign_keys=ON` (lo activa la fixture
`motor` de `conftest.py`).

Lo que se fija (AC-2, AC-4):

  * las claves unicas compuestas y FK compuestas declaradas en el modelo;
  * que una referencia cruzada entre instituciones (producto/categoria,
    inventario/departamento, inventario/producto, detalle/ticket, detalle/producto)
    se **rechaza** y no deja fila persistida;
  * que las relaciones validas dentro de una misma institucion si persisten.

SQLite valida las FK compuestas porque la fixture activa `foreign_keys` y todos
los componentes del lado hijo van no nulos en los casos cruzados; las semantica
que SQLite no cubre (p. ej. `NOT NULL` del DDL de instalacion) se confirman en
PostgreSQL 16 al cierre.
"""

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Institucion,
    Inventario,
    Prioridad,
    Producto,
    Rol,
    Ticket,
    Usuario,
)


@pytest.fixture
def sesion(motor):
    db = sessionmaker(bind=motor)()
    try:
        yield db
    finally:
        db.close()


def _sembrar_institucion(db, codigo: str) -> dict:
    """Crea un grafo institucional coherente y devuelve sus entidades."""
    db.add(Institucion(institucion_id=codigo, nombre=f"Institucion {codigo}"))
    db.flush()

    departamento = Departamento(
        nombre_dep=f"Departamento {codigo}", institucion_id=codigo
    )
    db.add(departamento)
    db.flush()

    rol = Rol(nombre_rol="Administrador")
    db.add(rol)
    db.flush()

    usuario = Usuario(
        nombre="Usuario",
        apellido=codigo,
        correo=f"usuario.{codigo}@compustock.cl",
        departamento_id=departamento.departamento_id,
        rol_id=rol.rol_id,
    )
    db.add(usuario)
    db.flush()

    categoria = Categoria(nombre_cat=f"Categoria {codigo}", institucion_id=codigo)
    db.add(categoria)
    db.flush()

    producto = Producto(
        nombre=f"Producto {codigo}",
        categoria_id=categoria.categoria_id,
        institucion_id=codigo,
    )
    db.add(producto)
    db.flush()

    prioridad = Prioridad(nombre="ALTA")
    db.add(prioridad)
    db.flush()

    estado = EstadoTicket(nombre="INGRESADO")
    db.add(estado)
    db.flush()

    ticket = Ticket(
        usuario_id=usuario.usuario_id,
        prioridad_id=prioridad.prioridad_id,
        estado_id=estado.estado_id,
        asunto=f"Asunto {codigo}",
        institucion_id=codigo,
    )
    db.add(ticket)
    db.flush()

    return {
        "departamento": departamento,
        "usuario": usuario,
        "categoria": categoria,
        "producto": producto,
        "ticket": ticket,
    }


def _nombres(constraints) -> set[str]:
    return {c.name for c in constraints if c.name}


# --- Declaracion de constraints en el modelo ---------------------------------


def test_modelo_declara_claves_compuestas_institucionales():
    esperadas = {
        "departamento_institucion_uk",
        "categoria_institucion_uk",
        "producto_institucion_uk",
        "ticket_institucion_uk",
    }
    declaradas = set()
    for tabla in (Departamento, Categoria, Producto, Ticket):
        declaradas |= _nombres(
            c for c in tabla.__table__.constraints if isinstance(c, UniqueConstraint)
        )
    assert esperadas <= declaradas


def test_modelo_declara_fk_compuestas_institucionales():
    esperadas = {
        "producto_categoria_institucion_fk",
        "inventario_departamento_institucion_fk",
        "inventario_producto_institucion_fk",
        "detalle_ticket_ticket_institucion_fk",
        "detalle_ticket_producto_institucion_fk",
    }
    declaradas = set()
    for tabla in (Producto, Inventario, DetalleTicket):
        declaradas |= _nombres(
            c for c in tabla.__table__.constraints if isinstance(c, ForeignKeyConstraint)
        )
    assert esperadas <= declaradas


# --- Referencias cruzadas rechazadas (AC-2, AC-4) ----------------------------


def test_producto_con_categoria_ajena_es_rechazado(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    sesion.add(
        Producto(
            nombre="Cruce categoria",
            categoria_id=b["categoria"].categoria_id,
            institucion_id="A",
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(Producto).filter_by(nombre="Cruce categoria").count() == 0


def test_inventario_con_departamento_ajeno_es_rechazado(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    sesion.add(
        Inventario(
            stock_actual=1,
            departamento_id=b["departamento"].departamento_id,
            producto_id=a["producto"].producto_id,
            institucion_id="A",
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(Inventario).count() == 0


def test_inventario_con_producto_ajeno_es_rechazado(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    sesion.add(
        Inventario(
            stock_actual=1,
            departamento_id=a["departamento"].departamento_id,
            producto_id=b["producto"].producto_id,
            institucion_id="A",
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(Inventario).count() == 0


def test_detalle_con_producto_ajeno_es_rechazado(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    sesion.add(
        DetalleTicket(
            ticket_id=a["ticket"].ticket_id,
            producto_id=b["producto"].producto_id,
            cantidad_solicitada=1,
            cantidad_entregada=0,
            institucion_id="A",
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(DetalleTicket).count() == 0


def test_detalle_con_ticket_ajeno_es_rechazado(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    sesion.add(
        DetalleTicket(
            ticket_id=b["ticket"].ticket_id,
            producto_id=a["producto"].producto_id,
            cantidad_solicitada=1,
            cantidad_entregada=0,
            institucion_id="A",
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(DetalleTicket).count() == 0


# --- Relaciones validas persistidas ------------------------------------------


def test_relaciones_intrainstitucionales_persisten(sesion):
    a = _sembrar_institucion(sesion, "A")
    b = _sembrar_institucion(sesion, "B")

    inventario = Inventario(
        stock_actual=5,
        ubicacion="Bodega A",
        departamento_id=a["departamento"].departamento_id,
        producto_id=a["producto"].producto_id,
        institucion_id="A",
    )
    detalle = DetalleTicket(
        ticket_id=a["ticket"].ticket_id,
        producto_id=a["producto"].producto_id,
        cantidad_solicitada=2,
        cantidad_entregada=0,
        institucion_id="A",
    )
    sesion.add_all([inventario, detalle])
    sesion.commit()

    assert sesion.query(Inventario).count() == 1
    assert sesion.query(DetalleTicket).count() == 1
    # Los homonimos de B no se mezclan: son registros independientes (AC-1).
    assert a["producto"].producto_id != b["producto"].producto_id
    assert a["categoria"].categoria_id != b["categoria"].categoria_id
