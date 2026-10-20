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
    BaseControl,
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
from app.services.auth_service import IdentidadAutenticada

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

    # Feature 012: el canonico de control (`InstitucionControl` + `funcion_institucion`)
    # se crea **primero**, de modo que la tabla compartida `institucion` de SQLite
    # sea el superset (espejo tenant de dos columnas + `rut`/`direccion`/`activo`).
    # Luego `Base.metadata` crea el resto y **se salta** `institucion` por
    # `checkfirst`: en el contexto logico unico control y tenant comparten tabla.
    BaseControl.metadata.create_all(motor)
    Base.metadata.create_all(motor)
    yield motor
    # `funcion_institucion` (control-only) referencia `institucion`; se elimina
    # antes del `drop_all` del tenant, que no conoce la tabla auxiliar y de otro
    # modo chocaria con la FK activada.
    BaseControl.metadata.tables["funcion_institucion"].drop(motor, checkfirst=True)
    Base.metadata.drop_all(motor)
    motor.dispose()


def identidad_de_prueba() -> IdentidadAutenticada:
    """Identidad autenticada inyectable para la suite funcional legacy.

    Tras la Feature 006 el router agregado de v1 exige Bearer. Las pruebas de
    negocio, que no comprueban autenticacion, necesitan una identidad resuelta
    para seguir ejerciendo su comportamiento funcional. Se construye un usuario
    local valido (no persistido: los endpoints de negocio no consumen la
    identidad) con un `sub` de Clerk ficticio. Nunca se usa una clave real.

    Feature 007 (T2): la autorizacion por rol ya esta cableada a cada operacion;
    la identidad legacy se elegia **Superadmin** porque su alcance global cubria
    las 18 operaciones y la suite funcional no se convertia, sin querer, en una
    prueba de denegacion.

    Feature 008 (T5, D-3): el ajuste de la matriz retira a Superadmin la
    escritura de catalogo, stock/movimientos y tickets (ahora 403). El unico rol
    que conserva las tres familias de escritura es **Administrador**, y la
    identidad legacy pasa a ese rol. Su alcance institucional se resuelve por
    `departamento_id=1`, que en estas pruebas pertenece a INST01 (la unica
    institucion que siembra la suite funcional). Las pruebas de autorizacion
    construyen su propia identidad por rol (ver
    `tests/api/test_permisos_endpoints.py`).
    """
    usuario = Usuario(
        usuario_id=1,
        nombre="Identidad",
        apellido="De Prueba",
        correo="identidad.legacy@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Administrador")
    return IdentidadAutenticada(usuario=usuario, sub="sub-legacy-pruebas")


@contextmanager
def _cliente_de_prueba(motor, **opciones):
    """Enlaza `get_db` al motor en memoria durante el contexto.

    Ademas overridea `get_current_user` con `identidad_de_prueba` para que la
    suite funcional legacy vuelva a ejercer su comportamiento de negocio bajo el
    router protegido. Este override vive **solo** en el harness de tests y no se
    aplica a `test_auth.py`, cuyas pruebas de seguridad construyen su propio
    cliente sin el override.
    """
    FabricaSesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db_de_prueba():
        db = FabricaSesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = obtener_db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = identidad_de_prueba
    # Feature 012 (D-3/AC-8): el alta local verifica el correo contra Clerk. La
    # costura se overridea para no invocar la red (el alta no crea identidades).
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda _correo: True)
    )
    from tests.soporte_frontera_017 import instalar_frontera_clerk

    instalar_frontera_clerk(identidad_existente=True)
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
    assumible un id fijo: los tests no codifican ids de catalogo.
    """
    db = sessionmaker(bind=motor)()
    try:
        rol = Rol(nombre_rol="Administrador", descripcion="Rol de prueba")
        db.add(rol)
        db.flush()

        # Rol asignable por el rol legacy (Feature 008: la identidad de la suite
        # funcional es Administrador, que solo puede asignar Bodeguero/Solicitante,
        # D-6/AC-10). El catalogo minimo lo necesita para el alta de usuarios.
        rol_bodeguero = Rol(nombre_rol="Bodeguero", descripcion="Rol asignable de prueba")
        db.add(rol_bodeguero)
        db.flush()

        institucion = Institucion(
            institucion_id="INST01",
            nombre="Instituto de Prueba",
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

        # Feature 008 (D-1): el catalogo es institucional. La institucion de
        # `datos_base` es INST01, y la pertenencia se ancla en las columnas
        # `institucion_id` que T6 puebla (el DDL de instalacion nueva las declara
        # NOT NULL; aqui sostienen las FK compuestas).
        categoria = Categoria(
            nombre_cat="Papeleria",
            descripcion_cat="Insumos de papeleria",
            institucion_id=institucion.institucion_id,
        )
        db.add(categoria)
        db.flush()

        producto = Producto(
            nombre="Cuaderno linedado",
            descripcion="Cuaderno de 100 hojas",
            unidad_medida="UNIDAD",
            stock_minimo=10,
            categoria_id=categoria.categoria_id,
            institucion_id=institucion.institucion_id,
        )
        db.add(producto)
        db.flush()

        inventario = Inventario(
            stock_actual=50,
            ubicacion="Bodega central",
            departamento_id=departamento.departamento_id,
            producto_id=producto.producto_id,
            institucion_id=institucion.institucion_id,
        )
        db.add(inventario)
        db.commit()

        return {
            "rol_id": rol.rol_id,
            "rol_nombre": rol.nombre_rol,
            "rol_bodeguero_id": rol_bodeguero.rol_id,
            "departamento_id": departamento.departamento_id,
            "institucion_id": institucion.institucion_id,
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


@pytest.fixture
def dos_instituciones(motor, datos_base):
    """Padron multiinstitucion compartido (Feature 008, T9).

    Sobre `datos_base` (INST01: institucion, departamento "Operaciones", catalogo
    "Papeleria"/"Cuaderno linedado" con existencia 50, usuario Administrador Ana y
    los roles Administrador/Bodeguero) agrega:

    * el catalogo global de los cuatro roles (Superadmin y Solicitante);
    * INST02 ("Instituto Ajeno") con su departamento y un usuario persistido por
      cada uno de los cuatro roles;
    * una categoria y un producto **homonimos** de los de INST01 ("Papeleria" /
      "Cuaderno linedado"), con su propia existencia (stock 5), para comprobar el
      aislamiento de catalogo y stock (AC-1, AC-5, AC-6).

    No construye las identidades de prueba: cada suite decide el rol y el
    departamento del actor. Aporta un mundo coherente de dos instituciones y
    cuatro roles que las suites no tienen que resembrar, y con las columnas
    institucionales pobladas (el esquema las exige NOT NULL desde T9).
    """
    db = sessionmaker(bind=motor)()
    try:
        rol_superadmin = Rol(nombre_rol="Superadmin", descripcion="Rol global")
        rol_solicitante = Rol(nombre_rol="Solicitante", descripcion="Rol limitado")
        db.add_all([rol_superadmin, rol_solicitante])
        db.flush()

        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
        )
        db.add(institucion_ajena)
        db.flush()

        departamento_ajeno = Departamento(
            nombre_dep="Bodega Sur",
            descripcion="Deposito de la institucion ajena",
            institucion_id="INST02",
        )
        db.add(departamento_ajeno)
        db.flush()

        roles = {
            "Administrador": datos_base["rol_id"],
            "Bodeguero": datos_base["rol_bodeguero_id"],
            "Solicitante": rol_solicitante.rol_id,
            "Superadmin": rol_superadmin.rol_id,
        }

        # INST01: Ana (datos_base) ya es Administrador; se agregan los otros tres.
        usuarios_inst01 = {"Administrador": datos_base["usuario_id"]}
        for nombre_rol, rol_id in roles.items():
            if nombre_rol == "Administrador":
                continue
            usuario = Usuario(
                nombre=nombre_rol,
                apellido="Inst01",
                correo=f"{nombre_rol.lower()}.inst01@compustock.cl",
                departamento_id=datos_base["departamento_id"],
                rol_id=rol_id,
            )
            db.add(usuario)
            db.flush()
            usuarios_inst01[nombre_rol] = usuario.usuario_id

        # INST02: un usuario por rol.
        usuarios_inst02: dict[str, int] = {}
        for nombre_rol, rol_id in roles.items():
            usuario = Usuario(
                nombre=nombre_rol,
                apellido="Inst02",
                correo=f"{nombre_rol.lower()}.inst02@compustock.cl",
                departamento_id=departamento_ajeno.departamento_id,
                rol_id=rol_id,
            )
            db.add(usuario)
            db.flush()
            usuarios_inst02[nombre_rol] = usuario.usuario_id

        # Homonimos institucionales con existencia independiente (AC-1, AC-6).
        categoria_homonima = Categoria(
            nombre_cat="Papeleria",
            descripcion_cat="Homonimo de INST02",
            institucion_id="INST02",
        )
        db.add(categoria_homonima)
        db.flush()

        producto_homonimo = Producto(
            nombre="Cuaderno linedado",
            descripcion="Homonimo de INST02",
            unidad_medida="UNIDAD",
            stock_minimo=10,
            categoria_id=categoria_homonima.categoria_id,
            institucion_id="INST02",
        )
        db.add(producto_homonimo)
        db.flush()

        inventario_homonimo = Inventario(
            stock_actual=5,
            ubicacion="Bodega Sur - H1",
            departamento_id=departamento_ajeno.departamento_id,
            producto_id=producto_homonimo.producto_id,
            institucion_id="INST02",
        )
        db.add(inventario_homonimo)
        db.commit()

        return {
            **datos_base,
            "inst_propia": "INST01",
            "inst_ajena": "INST02",
            "departamento_ajeno_id": departamento_ajeno.departamento_id,
            "categoria_homonima_ajena_id": categoria_homonima.categoria_id,
            "producto_homonimo_ajeno_id": producto_homonimo.producto_id,
            "inventario_homonimo_ajeno_id": inventario_homonimo.inventario_id,
            "stock_homonimo_ajeno": 5,
            "usuarios_inst01": usuarios_inst01,
            "usuarios_inst02": usuarios_inst02,
        }
    finally:
        db.close()
