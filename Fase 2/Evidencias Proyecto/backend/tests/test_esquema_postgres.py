"""T9 (Feature 008): pruebas de PostgreSQL 16 real para el esquema canonico.

Seam bajo prueba: el **motor PostgreSQL 16** y el script de estructura
`database/01_esquema.sql` (instalacion limpia: `control` + un esquema tenant por
institucion). SQLite (la suite funcional, en memoria) no acredita lo que aqui se
comprueba:

  * las **claves foraneas compuestas** institucionales rechazan de verdad una
    fila cruzada (producto/categoria, inventario/departamento, inventario/producto,
    detalle/ticket, detalle/producto) — SQLite las declara pero su enforcement de
    componentes compuestos no es el de PostgreSQL;
  * el **`NOT NULL`** de las columnas institucionales del DDL (el ORM de prueba
    tambien lo aplica, pero el DDL es la autoridad de datos reales);
  * el **fallback SQL del nombre de esquema** (`pg_temp.nombre_esquema_tenant`)
    reproduce exactamente al de `app.services.tenant_service`.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_esquema_postgres.py

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
    """La constraint existe exactamente una vez en `control` (el DDL canonico).

    Los tenants replican los mismos nombres (5 en total); la instalacion limpia
    se acredita sobre el esquema global, que es el DDL escrito a mano.
    """
    return _un_escalar(
        conexion,
        "SELECT count(*) FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE c.conname = %s AND n.nspname = 'control'",
        (nombre,),
    ) == 1


def _columna_es_not_null(conexion, tabla: str, columna: str) -> bool:
    return _un_escalar(
        conexion,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'control' AND table_name = %s AND column_name = %s",
        (tabla, columna),
    ) == "NO"


def _columnas_de(conexion, tabla: str, esquema: str = "control") -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (esquema, tabla),
    )
    return {fila[0] for fila in filas}


def _default_de(conexion, tabla: str, columna: str) -> str | None:
    return _un_escalar(
        conexion,
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = 'control' AND table_name = %s AND column_name = %s",
        (tabla, columna),
    )


def _claves_foraneas(conexion, tabla: str, esquema: str = "control") -> set[tuple]:
    """`(columna, tabla_referida)` de las FK reales declaradas por el DDL."""
    filas = _ejecutar(
        conexion,
        """
        SELECT kcu.column_name, ccu.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = tc.constraint_name
         AND kcu.constraint_schema = tc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.constraint_schema = tc.constraint_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        """,
        (esquema, tabla),
    )
    return {(fila[0], fila[1]) for fila in filas}


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
    # Feature 014: el mundo sembrado declara explicitamente el estado activo del
    # catalogo (el DDL tambien lo deja por defecto, pero la regresion no debe
    # depender de esa ausencia de valor).
    cat_a = _un_escalar(
        conexion,
        "INSERT INTO categoria (nombre_cat, activo, institucion_id) "
        "VALUES ('Cat A', TRUE, 'A') RETURNING categoria_id",
    )
    cat_b = _un_escalar(
        conexion,
        "INSERT INTO categoria (nombre_cat, activo, institucion_id) "
        "VALUES ('Cat B', TRUE, 'B') RETURNING categoria_id",
    )
    prod_a = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, activo, categoria_id, institucion_id) "
        "VALUES ('Prod A', TRUE, %s, 'A') RETURNING producto_id",
        (cat_a,),
    )
    prod_b = _un_escalar(
        conexion,
        "INSERT INTO producto (nombre, activo, categoria_id, institucion_id) "
        "VALUES ('Prod B', TRUE, %s, 'B') RETURNING producto_id",
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
# Feature 014 / AC-14: estado reversible del catalogo e historiales en el DDL
# ---------------------------------------------------------------------------


def test_esquema_nuevo_declara_el_estado_del_catalogo_activo_por_defecto():
    """`categoria.activo` y `producto.activo`: booleanas, NOT NULL y TRUE por defecto.

    El estado inicial lo garantiza el DDL, no la aplicacion: una fila insertada
    sin declarar vigencia nace activa y el motor rechaza dejarla nula.
    """
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_NUEVO)
        ids = _sembrar_nuevo(conexion)

        for tabla in ("categoria", "producto"):
            assert _columna_es_not_null(conexion, tabla, "activo"), tabla
            assert (_default_de(conexion, tabla, "activo") or "").lower() == "true", tabla

        # Alta sin `activo`: el default del motor la deja activa.
        categoria = _ejecutar(
            conexion,
            "INSERT INTO categoria (nombre_cat, institucion_id) VALUES ('Cat C','A') "
            "RETURNING categoria_id, activo",
        )[0]
        assert categoria[1] is True, categoria
        producto = _ejecutar(
            conexion,
            "INSERT INTO producto (nombre, categoria_id, institucion_id) "
            "VALUES ('Prod C',%s,'A') RETURNING activo",
            (categoria[0],),
        )[0]
        assert producto[0] is True, producto

        # Null explicito: NotNullViolation, nunca una fila sin estado.
        _esperar_violacion(
            conexion,
            "INSERT INTO categoria (nombre_cat, activo, institucion_id) VALUES ('Cat N',NULL,'A')",
            (),
            psycopg2.errors.NotNullViolation,
        )
        assert _un_escalar(conexion, "SELECT count(*) FROM categoria") == 3
        assert ids["cat_a"] != categoria[0]


def test_esquema_nuevo_crea_los_historiales_de_catalogo_con_fk_reales():
    """Las dos tablas de historial existen, son NOT NULL en lo obligatorio y
    rechazan referencias inexistentes al recurso o al actor (FK real).

    La paridad control/tenant de su estructura se acredita en
    `test_ciclo_vida_catalogo_postgres_014.py`; aqui se comprueba el DDL canonico.
    """
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_NUEVO)
        ids = _sembrar_nuevo(conexion)
        usuario = _un_escalar(conexion, "SELECT min(usuario_id) FROM usuario")

        for tabla, pk, columna_recurso, recurso in (
            ("historial_transicion_producto", "historial_producto_id", "producto_id", "producto"),
            ("historial_transicion_categoria", "historial_categoria_id", "categoria_id", "categoria"),
        ):
            columnas = _columnas_de(conexion, tabla)
            assert {
                pk,
                columna_recurso,
                "usuario_id",
                "fecha_transicion",
                "activo_origen",
                "activo_destino",
                "motivo",
            } <= columnas, (tabla, columnas)
            for columna in (
                columna_recurso,
                "usuario_id",
                "fecha_transicion",
                "activo_origen",
                "activo_destino",
                "motivo",
            ):
                assert _columna_es_not_null(conexion, tabla, columna), (tabla, columna)

            fks = _claves_foraneas(conexion, tabla)
            assert (columna_recurso, recurso) in fks, (tabla, fks)
            assert ("usuario_id", "usuario") in fks, (tabla, fks)

            # Referencias inexistentes: el motor las rechaza.
            _esperar_violacion(
                conexion,
                f"INSERT INTO {tabla} ({columna_recurso}, usuario_id, activo_origen, "
                "activo_destino, motivo) VALUES (999999,%s,FALSE,TRUE,'x')",
                (usuario,),
                psycopg2.errors.ForeignKeyViolation,
            )
            _esperar_violacion(
                conexion,
                f"INSERT INTO {tabla} ({columna_recurso}, usuario_id, activo_origen, "
                "activo_destino, motivo) VALUES (%s,999999,FALSE,TRUE,'x')",
                (ids["prod_a"] if recurso == "producto" else ids["cat_a"],),
                psycopg2.errors.ForeignKeyViolation,
            )

            # El motivo vacio tampoco es un estado valido (columna obligatoria).
            _esperar_violacion(
                conexion,
                f"INSERT INTO {tabla} ({columna_recurso}, usuario_id, activo_origen, "
                "activo_destino, motivo) VALUES (%s,%s,FALSE,TRUE,NULL)",
                (ids["prod_a"] if recurso == "producto" else ids["cat_a"], usuario),
                psycopg2.errors.NotNullViolation,
            )

            # Una transicion coherente si se persiste.
            _ejecutar(
                conexion,
                f"INSERT INTO {tabla} ({columna_recurso}, usuario_id, activo_origen, "
                "activo_destino, motivo) VALUES (%s,%s,TRUE,FALSE,'baja de prueba')",
                (ids["prod_a"] if recurso == "producto" else ids["cat_a"], usuario),
            )
            assert _un_escalar(conexion, f"SELECT count(*) FROM {tabla}") == 1, tabla


# ---------------------------------------------------------------------------
# AC-21 (Feature 013): el fallback SQL del nombre replica 1:1 a Python
# ---------------------------------------------------------------------------


def test_nombre_esquema_sql_reproduce_exactamente_python():
    """`pg_temp.nombre_esquema_tenant` de `01_esquema.sql` replica a `tenant_service`."""
    from app.services.tenant_service import nombre_esquema_para_institucion

    bateria = [
        "INST-001",
        "INST-002",
        "CTRL-SAAS",
        "A",
        "inst 001",
        "Institución Ñandú",
        "①x②",
        "A--B",
    ]
    with _base_temporal() as conexion:
        _ejecutar_script(conexion, ESQUEMA_NUEVO)

        for identificador in bateria:
            del_sql = _un_escalar(
                conexion,
                "SELECT pg_temp.nombre_esquema_tenant(%s)",
                (identificador,),
            )
            assert del_sql == nombre_esquema_para_institucion(identificador), identificador
