"""Fixtures compartidas para la suite de la Feature 001.

El seam bajo prueba es la **interfaz HTTP** (`TestClient`), nunca la capa de
servicios ni la sesion de SQLAlchemy. `tests/api/` verifica unicamente
comportamiento observable desde la API.

La base es SQLite en memoria para que la suite corra sin depender del
contenedor de PostgreSQL. Las aserciones no consultan la base directamente:
todo se comprueba leyendo la API, igual que lo haria un cliente real.
"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dependencies
from app.db.database import Base
from app.main import app
from app.models import (
    Categoria,
    Departamento,
    EstadoTicket,
    Institucion,
    Inventario,
    Prioridad,
    Producto,
    Rol,
    Usuario,
)

#: Motor en memoria. `StaticPool` mantiene una sola conexion para que la base
#: sobreviva entre el hilo de `TestClient` y el hilo principal.
SQLITE_MEMORIA = "sqlite+pysqlite:///:memory:"


@pytest.fixture
def motor():
    """Motor efimero con las 12 tablas creadas, con FKs activadas."""
    motor = create_engine(
        SQLITE_MEMORIA,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(motor, "connect")
    def activar_llaves_foraneas(conexion, _registro):
        # SQLite ignora las FKs salvo que se activen explicitamente. Sin esto,
        # el test de atomicidad (AC-8) no podria provocar la violacion que
        # dispara el rollback.
        conexion.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(motor)
    yield motor
    Base.metadata.drop_all(motor)
    motor.dispose()


@contextmanager
def _cliente_de_prueba(motor, **opciones):
    """Enlaza `get_db` al motor en memoria durante el contexto."""
    FabricaSesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db_de_prueba():
        db = FabricaSesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = obtener_db_de_prueba
    try:
        with TestClient(app, **opciones) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente(motor):
    """`TestClient` con `get_db` redirigido al motor en memoria."""
    with _cliente_de_prueba(motor) as cliente_http:
        yield cliente_http


@pytest.fixture
def cliente_sin_excepcion(motor):
    """Igual que `cliente`, pero las excepciones no manejadas se vuelven 500.

    `TestClient` por defecto relanza la excepcion en vez de responder, lo que
    impide observar que la API devuelve 500 ante un error de base de datos.
    """
    with _cliente_de_prueba(motor, raise_server_exceptions=False) as cliente_http:
        yield cliente_http


@pytest.fixture
def datos_base(motor):
    """Catalogo minimo para poder crear tickets, usuarios y movimientos.

    Devuelve un dict con los ids generados por SQLite, porque en PostgreSQL las
    secuencias de identidad arrancan donde deje la ultima prueba y no es
    assumible un id fijo (ver nota sobre `ESTADO_CERRADO_ID` en
    `docs/spec/features/001-reestructuracion-modular/tasks.md`).
    """
    db = sessionmaker(bind=motor)()
    try:
        rol = Rol(nombre_rol="ADMINISTRADOR_INSTITUCIONAL", descripcion="Rol de prueba")
        db.add(rol)
        db.flush()

        institucion = Institucion(
            institucion_id="INST01",
            nombre="Instituto de Prueba",
            rut="1-9",
            direccion="Calle Falsa 123",
        )
        db.add(institucion)
        db.flush()

        departamento = Departamento(
            nombre_dep="Operaciones",
            descripcion="Departamento de prueba",
            institucion_id=institucion.institucion_id,
        )
        db.add(departamento)
        db.flush()

        usuario = Usuario(
            nombre="Ana",
            apellido="Perez",
            correo="ana.prueba@compustock.cl",
            password="hash-de-prueba",
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
        db.add(usuario)
        db.flush()

        prioridad = Prioridad(nombre="ALTA", descripcion="Prioridad alta")
        db.add(prioridad)
        db.flush()

        estado_ingresado = EstadoTicket(nombre="INGRESADO", descripcion="Ticket recien creado")
        db.add(estado_ingresado)
        db.flush()

        estado_cerrado = EstadoTicket(nombre="CERRADO", descripcion="Ticket cerrado")
        db.add(estado_cerrado)
        db.flush()

        categoria = Categoria(nombre_cat="Papeleria", descripcion_cat="Insumos de papeleria")
        db.add(categoria)
        db.flush()

        producto = Producto(
            nombre="Cuaderno linedado",
            descripcion="Cuaderno de 100 hojas",
            unidad_medida="UNIDAD",
            stock_minimo=10,
            categoria_id=categoria.categoria_id,
        )
        db.add(producto)
        db.flush()

        inventario = Inventario(
            stock_actual=50,
            ubicacion="Bodega central",
            departamento_id=departamento.departamento_id,
            producto_id=producto.producto_id,
        )
        db.add(inventario)
        db.commit()

        return {
            "rol_id": rol.rol_id,
            "departamento_id": departamento.departamento_id,
            "usuario_id": usuario.usuario_id,
            "prioridad_id": prioridad.prioridad_id,
            "estado_ingresado_id": estado_ingresado.estado_id,
            "estado_cerrado_id": estado_cerrado.estado_id,
            "categoria_id": categoria.categoria_id,
            "producto_id": producto.producto_id,
            "inventario_id": inventario.inventario_id,
            "correo_usado": usuario.correo,
        }
    finally:
        db.close()
