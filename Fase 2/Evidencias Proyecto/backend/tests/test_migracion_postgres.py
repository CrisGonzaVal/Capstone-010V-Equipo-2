"""T9 (Feature 008): pruebas de PostgreSQL 16 real para lo que SQLite no valida.

Seam bajo prueba: el **motor PostgreSQL 16** y los **scripts SQL** del proyecto
(`database/01_esquema.sql` y `database/98_migracion_particionamiento_institucional.sql`).
SQLite (la suite funcional, en memoria) no acredita lo que aqui se comprueba:

  * las **claves foraneas compuestas** institucionales rechazan de verdad una
    fila cruzada (producto/categoria, inventario/departamento, inventario/producto,
    detalle/ticket, detalle/producto) — SQLite las declara pero su enforcement de
    componentes compuestos no es el de PostgreSQL;
  * el **`NOT NULL`** de las columnas institucionales del DDL (el ORM de prueba
    tambien lo aplica desde T9, pero el DDL es la autoridad de datos reales);
  * la **migracion `98_`** sobre un esquema legado: preservacion de IDs/filas,
    idempotencia de una segunda ejecucion y **rollback completo** ante ambiguedad
    (el `DO $$` transaccional no tiene equivalente en SQLite);
  * `FOR UPDATE` y CHECK del DDL (documentados aparte; estos tests no re-prueban
    concurrencia, solo el esquema y la migracion).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_migracion_postgres.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan** con una razon clara y la suite
    local (SQLite) sigue verde. Se acepta tambien la forma con driver de
    SQLAlchemy (`postgresql+psycopg2://...`). La URL apunta a una base de
    mantenimiento donde el test **crea y destruye** una base temporal propia; no
    toca `apt_erp`.

NO se anade ninguna dependencia: `psycopg2` ya esta en `requirements.txt`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2
    import psycopg2.errors

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

# ---------------------------------------------------------------------------
# Rutas, URL y utilidades de conexion
# ---------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA_NUEVO = RAIZ / "database" / "01_esquema.sql"
MIGRACION = RAIZ / "database" / "98_migracion_particionamiento_institucional.sql"

#: Esquema LEGADO (pre-008) reconstruido: las tablas existen SIN las columnas
#: institucionales y con los nombres de FK que la migracion `98_` espera
#: (`producto_categoria_fk`, `inventario_departamento_fk`,
#: `inventario_producto_fk`, `detalle_ticket_ticket_fk`,
#: `detalle_ticket_producto_fk`). Es la forma exacta del `01_esquema.sql` previo a
#: la Feature 008; se mantiene aqui, en el test, para no reescribir SQL de
#: produccion ni depender de un archivo historico.
DDL_LEGADO = """
CREATE TABLE institucion (
    institucion_id VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    rut VARCHAR(20),
    direccion VARCHAR(200)
);

CREATE TABLE departamento (
    departamento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_dep VARCHAR(100) NOT NULL,
    descripcion VARCHAR(200),
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT departamento_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id)
);

CREATE TABLE rol (
    rol_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_rol VARCHAR(50) NOT NULL,
    descripcion VARCHAR(150)
);

CREATE TABLE usuario (
    usuario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE,
    departamento_id INTEGER NOT NULL,
    rol_id INTEGER NOT NULL,
    CONSTRAINT usuario_departamento_fk
        FOREIGN KEY (departamento_id) REFERENCES departamento(departamento_id),
    CONSTRAINT usuario_rol_fk
        FOREIGN KEY (rol_id) REFERENCES rol(rol_id)
);

CREATE TABLE categoria (
    categoria_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_cat VARCHAR(100) NOT NULL,
    descripcion_cat VARCHAR(200)
);

CREATE TABLE producto (
    producto_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    descripcion VARCHAR(250),
    unidad_medida VARCHAR(30),
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    categoria_id INTEGER NOT NULL,
    CONSTRAINT producto_categoria_fk
        FOREIGN KEY (categoria_id) REFERENCES categoria(categoria_id)
);

CREATE TABLE inventario (
    inventario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    ubicacion VARCHAR(100),
    departamento_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    CONSTRAINT inventario_departamento_fk
        FOREIGN KEY (departamento_id) REFERENCES departamento(departamento_id),
    CONSTRAINT inventario_producto_fk
        FOREIGN KEY (producto_id) REFERENCES producto(producto_id),
    CONSTRAINT inventario_producto_departamento_uk
        UNIQUE (departamento_id, producto_id)
);

CREATE TABLE movimiento_inventario (
    movimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_movimiento VARCHAR(20) NOT NULL,
    cantidad INTEGER NOT NULL,
    fecha_movimiento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacion VARCHAR(250),
    inventario_id INTEGER NOT NULL,
    CONSTRAINT movimiento_inventario_fk
        FOREIGN KEY (inventario_id) REFERENCES inventario(inventario_id)
);

CREATE TABLE prioridad (
    prioridad_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

CREATE TABLE estado_ticket (
    estado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

CREATE TABLE ticket (
    ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    prioridad_id INTEGER NOT NULL,
    estado_id INTEGER NOT NULL,
    asunto VARCHAR(150) NOT NULL,
    descripcion VARCHAR(500),
    fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_cierre TIMESTAMP,
    CONSTRAINT ticket_usuario_fk
        FOREIGN KEY (usuario_id) REFERENCES usuario(usuario_id),
    CONSTRAINT ticket_prioridad_fk
        FOREIGN KEY (prioridad_id) REFERENCES prioridad(prioridad_id),
    CONSTRAINT ticket_estado_fk
        FOREIGN KEY (estado_id) REFERENCES estado_ticket(estado_id)
);

CREATE TABLE detalle_ticket (
    detalle_ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad_solicitada INTEGER NOT NULL,
    cantidad_entregada INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT detalle_ticket_ticket_fk
        FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id),
    CONSTRAINT detalle_ticket_producto_fk
        FOREIGN KEY (producto_id) REFERENCES producto(producto_id)
);
"""


def _sin_driver(url: str) -> str:
    """URL de SQLAlchemy -> DSN de psycopg2 (`+psycopg2` no es valido alli)."""
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _url_con_base(url: str, nombre: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))


@contextmanager
def _base_temporal():
    """Crea una base PostgreSQL efimera y la destruye al salir.

    La base se crea contra la base de mantenimiento que indique
    `POSTGRES_TEST_URL`; el test se conecta luego a la base nueva. Nunca toca
    `apt_erp`.
    """
    dsn = _sin_driver(_POSTGRES_TEST_URL or "")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_test_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    try:
        conexion = psycopg2.connect(_url_con_base(dsn, nombre))
        try:
            yield conexion
        finally:
            conexion.close()
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _ejecutar_script(conexion, ruta: Path) -> None:
    with conexion.cursor() as cur:
        cur.execute(ruta.read_text(encoding="utf-8"))
    conexion.commit()


def _ejecutar(conexion, sql: str, params=()):
    with conexion.cursor() as cur:
        cur.execute(sql, params)
        filas = cur.fetchall() if cur.description else []
    conexion.commit()
    return filas


def _un_escalar(conexion, sql: str, params=()):
    filas = _ejecutar(conexion, sql, params)
    return filas[0][0]


def _constraint_existe(conexion, nombre: str) -> bool:
    return _un_escalar(
        conexion, "SELECT count(*) FROM pg_constraint WHERE conname = %s", (nombre,)
    ) == 1


def _columna_es_not_null(conexion, tabla: str, columna: str) -> bool:
    return _un_escalar(
        conexion,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (tabla, columna),
    ) == "NO"


def _columna_existe(conexion, tabla: str, columna: str) -> bool:
    return _un_escalar(
        conexion,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (tabla, columna),
    ) == 1


# ---------------------------------------------------------------------------
# Sembrado sobre el esquema NUEVO (01_esquema.sql)
# ---------------------------------------------------------------------------


def _sembrar_nuevo(conexion) -> dict:
    """Dos instituciones coherentes sobre el esquema de instalacion nueva."""
    _ejecutar(
        conexion,
        "INSERT INTO institucion (institucion_id, nombre) VALUES ('A','Inst A'),('B','Inst B')",
    )
    dep_a = _un_escalar(
        conexion,
        "INSERT INTO departamento (nombre_dep, institucion_id) VALUES ('Dep A','A') RETURNING departamento_id",
    )
    dep_b = _un_escalar(
        conexion,
        "INSERT INTO departamento (nombre_dep, institucion_id) VALUES ('Dep B','B') RETURNING departamento_id",
    )
    rol = _un_escalar(
        conexion, "INSERT INTO rol (nombre_rol) VALUES ('Administrador') RETURNING rol_id"
    )
    u_a = _un_escalar(
        conexion,
        "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
        "VALUES ('U','A','ua@test.cl',%s,%s) RETURNING usuario_id",
        (dep_a, rol),
    )
    u_b = _un_escalar(
        conexion,
        "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
        "VALUES ('U','B','ub@test.cl',%s,%s) RETURNING usuario_id",
        (dep_b, rol),
    )
    cat_a = _un_escalar(
        conexion,
        "INSERT INTO categoria (nombre_cat, institucion_id) VALUES ('Cat A','A') RETURNING categoria_id",
    )
    cat_b = _un_escalar(
        conexion,
        "INSERT INTO categoria (nombre_cat, institucion_id) VALUES ('Cat B','B') RETURNING categoria_id",
    )
    prod_a = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, categoria_id, institucion_id) VALUES ('Prod A',%s,'A') RETURNING producto_id",
        (cat_a,),
    )
    prod_b = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, categoria_id, institucion_id) VALUES ('Prod B',%s,'B') RETURNING producto_id",
        (cat_b,),
    )
    prioridad = _un_escalar(
        conexion, "INSERT INTO prioridad (nombre) VALUES ('ALTA') RETURNING prioridad_id"
    )
    estado = _un_escalar(
        conexion,
        "INSERT INTO estado_ticket (nombre) VALUES ('INGRESADO') RETURNING estado_id",
    )
    ticket_a = _un_escalar(
        conexion,
        "INSERT INTO ticket (usuario_id, prioridad_id, estado_id, asunto, institucion_id) "
        "VALUES (%s,%s,%s,'T A','A') RETURNING ticket_id",
        (u_a, prioridad, estado),
    )
    conexion.commit()
    return {
        "dep_a": dep_a,
        "dep_b": dep_b,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "ticket_a": ticket_a,
    }


def _esperar_violacion(conexion, sql: str, params=(), tipo=None):
    """Ejecuta una escritura invalida y exige que el motor la rechace.

    Tras el error, la transaccion queda abortada: se hace `rollback` para dejar la
    conexion usable por la siguiente asercion.
    """
    with pytest.raises(tipo or psycopg2.Error):
        with conexion.cursor() as cur:
            cur.execute(sql, params)
    conexion.rollback()


# ---------------------------------------------------------------------------
# AC-2 / AC-4: esquema nuevo rechaza referencias cruzadas y exige NOT NULL
# ---------------------------------------------------------------------------


def test_esquema_nuevo_rechaza_referencias_cruzadas_entre_instituciones():
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_NUEVO)
        ids = _sembrar_nuevo(conexion)

        # producto con categoria de otra institucion -> FK compuesta.
        _esperar_violacion(
            conexion,
            "INSERT INTO producto (nombre, categoria_id, institucion_id) VALUES ('X',%s,'A')",
            (ids["cat_b"],),
            psycopg2.errors.ForeignKeyViolation,
        )
        # inventario con departamento de otra institucion que su producto.
        _esperar_violacion(
            conexion,
            "INSERT INTO inventario (stock_actual, departamento_id, producto_id, institucion_id) "
            "VALUES (1,%s,%s,'A')",
            (ids["dep_b"], ids["prod_a"]),
            psycopg2.errors.ForeignKeyViolation,
        )
        # inventario con producto de otra institucion que su departamento.
        _esperar_violacion(
            conexion,
            "INSERT INTO inventario (stock_actual, departamento_id, producto_id, institucion_id) "
            "VALUES (1,%s,%s,'A')",
            (ids["dep_a"], ids["prod_b"]),
            psycopg2.errors.ForeignKeyViolation,
        )
        # detalle de un ticket con producto de otra institucion.
        _esperar_violacion(
            conexion,
            "INSERT INTO detalle_ticket (ticket_id, producto_id, cantidad_solicitada, cantidad_entregada, institucion_id) "
            "VALUES (%s,%s,1,0,'A')",
            (ids["ticket_a"], ids["prod_b"]),
            psycopg2.errors.ForeignKeyViolation,
        )

        # Ninguna fila cruzada quedo persistida.
        assert _un_escalar(conexion, "SELECT count(*) FROM producto") == 2
        assert _un_escalar(conexion, "SELECT count(*) FROM inventario") == 0
        assert _un_escalar(conexion, "SELECT count(*) FROM detalle_ticket") == 0

        # Las constraints compuestas quedaron declaradas en el catalogo.
        for nombre in (
            "producto_categoria_institucion_fk",
            "inventario_departamento_institucion_fk",
            "inventario_producto_institucion_fk",
            "detalle_ticket_ticket_institucion_fk",
            "detalle_ticket_producto_institucion_fk",
            "departamento_institucion_uk",
            "categoria_institucion_uk",
            "producto_institucion_uk",
            "ticket_institucion_uk",
        ):
            assert _constraint_existe(conexion, nombre), nombre


def test_esquema_nuevo_exige_institucion_not_null():
    """SQLite declara el NOT NULL pero su enforcement de FKs difiere; aqui es real."""
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_NUEVO)
        ids = _sembrar_nuevo(conexion)

        for tabla, columna in (
            ("categoria", "institucion_id"),
            ("producto", "institucion_id"),
            ("inventario", "institucion_id"),
            ("ticket", "institucion_id"),
            ("detalle_ticket", "institucion_id"),
        ):
            assert _columna_es_not_null(conexion, tabla, columna), (tabla, columna)

        # Insertar sin institucion es un NotNullViolation, no una fila valida.
        _esperar_violacion(
            conexion,
            "INSERT INTO producto (nombre, categoria_id, institucion_id) VALUES ('N',%s,NULL)",
            (ids["cat_a"],),
            psycopg2.errors.NotNullViolation,
        )


# ---------------------------------------------------------------------------
# AC-14: la migracion preserva filas e identificadores
# ---------------------------------------------------------------------------


def _sembrar_legado(conexion, *, con_ambiguedad: bool = False) -> dict:
    """Esquema legado con dos instituciones coherentes (opcional: un ambiguo)."""
    _ejecutar(
        conexion,
        "INSERT INTO institucion (institucion_id, nombre) VALUES ('A','Inst A'),('B','Inst B')",
    )
    dep_a = _un_escalar(
        conexion,
        "INSERT INTO departamento (nombre_dep, institucion_id) VALUES ('Dep A','A') RETURNING departamento_id",
    )
    dep_b = _un_escalar(
        conexion,
        "INSERT INTO departamento (nombre_dep, institucion_id) VALUES ('Dep B','B') RETURNING departamento_id",
    )
    rol = _un_escalar(
        conexion, "INSERT INTO rol (nombre_rol) VALUES ('Administrador') RETURNING rol_id"
    )
    u_a = _un_escalar(
        conexion,
        "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
        "VALUES ('U','A','ua@test.cl',%s,%s) RETURNING usuario_id",
        (dep_a, rol),
    )
    u_b = _un_escalar(
        conexion,
        "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
        "VALUES ('U','B','ub@test.cl',%s,%s) RETURNING usuario_id",
        (dep_b, rol),
    )
    cat_a = _un_escalar(
        conexion, "INSERT INTO categoria (nombre_cat) VALUES ('Cat A') RETURNING categoria_id"
    )
    cat_b = _un_escalar(
        conexion, "INSERT INTO categoria (nombre_cat) VALUES ('Cat B') RETURNING categoria_id"
    )
    prod_a = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, categoria_id) VALUES ('Prod A',%s) RETURNING producto_id",
        (cat_a,),
    )
    prod_b = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, categoria_id) VALUES ('Prod B',%s) RETURNING producto_id",
        (cat_b,),
    )
    inv_a = _un_escalar(
        conexion,
        "INSERT INTO inventario (stock_actual, departamento_id, producto_id) "
        "VALUES (40,%s,%s) RETURNING inventario_id",
        (dep_a, prod_a),
    )
    inv_b = _un_escalar(
        conexion,
        "INSERT INTO inventario (stock_actual, departamento_id, producto_id) "
        "VALUES (7,%s,%s) RETURNING inventario_id",
        (dep_b, prod_b),
    )
    _ejecutar(
        conexion,
        "INSERT INTO movimiento_inventario (tipo_movimiento, cantidad, observacion, inventario_id) "
        "VALUES ('ENTRADA',40,'Ingreso A',%s)",
        (inv_a,),
    )
    prioridad = _un_escalar(
        conexion, "INSERT INTO prioridad (nombre) VALUES ('ALTA') RETURNING prioridad_id"
    )
    estado = _un_escalar(
        conexion,
        "INSERT INTO estado_ticket (nombre) VALUES ('INGRESADO') RETURNING estado_id",
    )
    ticket_a = _un_escalar(
        conexion,
        "INSERT INTO ticket (usuario_id, prioridad_id, estado_id, asunto) "
        "VALUES (%s,%s,%s,'T A') RETURNING ticket_id",
        (u_a, prioridad, estado),
    )
    ticket_b = _un_escalar(
        conexion,
        "INSERT INTO ticket (usuario_id, prioridad_id, estado_id, asunto) "
        "VALUES (%s,%s,%s,'T B') RETURNING ticket_id",
        (u_b, prioridad, estado),
    )
    det_a = _un_escalar(
        conexion,
        "INSERT INTO detalle_ticket (ticket_id, producto_id, cantidad_solicitada, cantidad_entregada) "
        "VALUES (%s,%s,1,0) RETURNING detalle_ticket_id",
        (ticket_a, prod_a),
    )
    det_b = _un_escalar(
        conexion,
        "INSERT INTO detalle_ticket (ticket_id, producto_id, cantidad_solicitada, cantidad_entregada) "
        "VALUES (%s,%s,1,0) RETURNING detalle_ticket_id",
        (ticket_b, prod_b),
    )
    ids = {
        "dep_a": dep_a,
        "dep_b": dep_b,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "inv_a": inv_a,
        "inv_b": inv_b,
        "ticket_a": ticket_a,
        "ticket_b": ticket_b,
        "det_a": det_a,
        "det_b": det_b,
        "usuario_a": u_a,
        "usuario_b": u_b,
        "prioridad": prioridad,
        "estado": estado,
    }
    if con_ambiguedad:
        # `prod_x` es existencia de A (inventario en Dep A) y a la vez pedido por
        # un ticket cuyo solicitante vive en B -> dos instituciones candidatas.
        prod_x = _un_escalar(
            conexion,
            "INSERT INTO producto (nombre, categoria_id) VALUES ('Prod X',%s) RETURNING producto_id",
            (cat_a,),
        )
        _ejecutar(
            conexion,
            "INSERT INTO inventario (stock_actual, departamento_id, producto_id) VALUES (3,%s,%s)",
            (dep_a, prod_x),
        )
        ticket_x = _un_escalar(
            conexion,
            "INSERT INTO ticket (usuario_id, prioridad_id, estado_id, asunto) "
            "VALUES (%s,%s,%s,'T X') RETURNING ticket_id",
            (u_b, prioridad, estado),
        )
        _ejecutar(
            conexion,
            "INSERT INTO detalle_ticket (ticket_id, producto_id, cantidad_solicitada, cantidad_entregada) "
            "VALUES (%s,%s,1,0)",
            (ticket_x, prod_x),
        )
        ids.update({"prod_x": prod_x, "ticket_x": ticket_x})
    conexion.commit()
    return ids


def _conteos(conexion) -> dict:
    return {
        tabla: _un_escalar(conexion, f"SELECT count(*) FROM {tabla}")
        for tabla in (
            "institucion",
            "usuario",
            "departamento",
            "categoria",
            "producto",
            "inventario",
            "movimiento_inventario",
            "ticket",
            "detalle_ticket",
        )
    }


def _ids(conexion, tabla: str, columna_pk: str) -> set[int]:
    filas = _ejecutar(conexion, f"SELECT {columna_pk} FROM {tabla}")
    return {fila[0] for fila in filas}


def test_migracion_preserva_filas_ids_y_agrega_constraints():
    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        ids = _sembrar_legado(conexion)

        antes = _conteos(conexion)
        ids_producto = _ids(conexion, "producto", "producto_id")
        ids_inventario = _ids(conexion, "inventario", "inventario_id")
        ids_ticket = _ids(conexion, "ticket", "ticket_id")

        _ejecutar_script(conexion, MIGRACION)

        assert _conteos(conexion) == antes, "la migracion no debe alterar conteos"
        assert _ids(conexion, "producto", "producto_id") == ids_producto
        assert _ids(conexion, "inventario", "inventario_id") == ids_inventario
        assert _ids(conexion, "ticket", "ticket_id") == ids_ticket

        # Pertenencia inferida correctamente desde las referencias persistidas.
        pertenencia = {
            tabla: dict(
                _ejecutar(
                    conexion,
                    f"SELECT {pk}, institucion_id FROM {tabla}",
                    (),
                )
            )
            for tabla, pk in (
                ("categoria", "categoria_id"),
                ("producto", "producto_id"),
                ("inventario", "inventario_id"),
                ("ticket", "ticket_id"),
                ("detalle_ticket", "detalle_ticket_id"),
            )
        }
        assert pertenencia["categoria"] == {ids["cat_a"]: "A", ids["cat_b"]: "B"}
        assert pertenencia["producto"] == {ids["prod_a"]: "A", ids["prod_b"]: "B"}
        assert pertenencia["inventario"] == {ids["inv_a"]: "A", ids["inv_b"]: "B"}
        assert pertenencia["ticket"] == {ids["ticket_a"]: "A", ids["ticket_b"]: "B"}
        assert pertenencia["detalle_ticket"] == {ids["det_a"]: "A", ids["det_b"]: "B"}

        # El DDL y las constraints institucionales quedaron aplicados.
        for tabla in ("categoria", "producto", "inventario", "ticket", "detalle_ticket"):
            assert _columna_es_not_null(conexion, tabla, "institucion_id"), tabla
        for nombre in (
            "producto_categoria_institucion_fk",
            "inventario_departamento_institucion_fk",
            "inventario_producto_institucion_fk",
            "detalle_ticket_ticket_institucion_fk",
            "detalle_ticket_producto_institucion_fk",
        ):
            assert _constraint_existe(conexion, nombre), nombre

        # La migracion no re-ejecuta retiro de password (no forma parte de 98_).
        assert _columna_existe(conexion, "usuario", "correo")


def test_migracion_segunda_ejecucion_es_idempotente():
    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)

        _ejecutar_script(conexion, MIGRACION)
        despues_primera = _conteos(conexion)
        pertenencia_primera = dict(
            _ejecutar(conexion, "SELECT producto_id, institucion_id FROM producto")
        )

        # Segunda ejecucion: guard de idempotencia (categoria.institucion_id existe).
        _ejecutar_script(conexion, MIGRACION)

        assert _conteos(conexion) == despues_primera
        assert dict(
            _ejecutar(conexion, "SELECT producto_id, institucion_id FROM producto")
        ) == pertenencia_primera
        # Una unica `departamento_institucion_uk`: la segunda pasada no la duplica.
        assert (
            _un_escalar(
                conexion,
                "SELECT count(*) FROM pg_constraint WHERE conname = 'departamento_institucion_uk'",
            )
            == 1
        )


def test_migracion_aborta_ambiguedad_sin_cambios_y_reintenta_tras_corregir():
    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        ids = _sembrar_legado(conexion, con_ambiguedad=True)

        antes = _conteos(conexion)

        # La migracion aborta identificando el producto ambiguo.
        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION)
        conexion.rollback()
        mensaje = str(excinfo.value)
        assert "ambigu" in mensaje.lower()
        assert "producto" in mensaje.lower()
        assert str(ids["prod_x"]) in mensaje, mensaje

        # Rollback completo: no se agrego ninguna columna ni constraint ni fila.
        assert not _columna_existe(conexion, "categoria", "institucion_id")
        assert not _constraint_existe(conexion, "categoria_institucion_uk")
        assert _conteos(conexion) == antes

        # Correccion manual: el solicitante del ticket de `prod_x` pasa a INST A.
        _ejecutar(
            conexion,
            "UPDATE ticket SET usuario_id = %s WHERE ticket_id = %s",
            (ids["usuario_a"], ids["ticket_x"]),
        )

        # Reintento: ahora migra sin ambiguedad y preserva las filas.
        _ejecutar_script(conexion, MIGRACION)
        assert _conteos(conexion) == antes
        assert _columna_es_not_null(conexion, "producto", "institucion_id")
        assert dict(
            _ejecutar(conexion, "SELECT producto_id, institucion_id FROM producto")
        )[ids["prod_x"]] == "A"
