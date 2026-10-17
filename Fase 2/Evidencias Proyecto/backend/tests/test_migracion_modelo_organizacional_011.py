"""T2 (Feature 011): migracion del modelo organizacional sobre PostgreSQL 16 — gated.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces, FKs
compuestas ni el DDL por esquema, asi que lo que la Feature 011 exige de la
migracion solo se puede acreditar aqui:

  * DDL de `control` y de cada tenant con las entidades nuevas (`sede`,
    `stock_sede`, `departamento_encargado`) y las columnas nuevas
    (`departamento.sede_id`, `usuario.sede_id`, `ticket.sede_id`,
    `movimiento_inventario.stock_sede_id`);
  * reparto determinista de sedes (2/3/4/2 para INST-001..004) y de departamentos
    por round-robin sobre `departamento_id` ascendente;
  * cuadre exacto: la suma de saldos por sede de cada producto es la suma
    departamental medida **antes** de migrar;
  * cada `(sede, producto)` arranca con un movimiento nuevo de consolidacion
    `ENTRADA` por exactamente su saldo;
  * la auditoria y el inventario legados quedan **identicos** (misma firma);
  * idempotencia, aborto ante estado parcial y version objetivo `011.1`;
  * instalacion limpia (`01_` + `02_`) con sedes y guardia fail-closed intacta.

Trazabilidad AC (spec 011 §5): AC-2, AC-9, AC-10, AC-12, AC-13.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_migracion_modelo_organizacional_011.py

Fase ROJA de TDD: el script `002_migracion_modelo_organizacional_011.sql` y el DDL
de la 011 aun no existen (T5), asi que cada prueba falla por el archivo ausente o
por la estructura ausente, nunca por un error de sintaxis del test.
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

#: Raiz de `Evidencias Proyecto/` (este archivo vive en `backend/tests/`).
RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA_SQL = RAIZ / "database" / "01_esquema.sql"
SEMILLA_SQL = RAIZ / "database" / "02_datos_semilla.sql"
MIGRACION_010 = (
    RAIZ / "database" / "migraciones" / "001_migracion_multitenant_esquemas.sql"
)
MIGRACION_011 = (
    RAIZ / "database" / "migraciones" / "002_migracion_modelo_organizacional_011.sql"
)

VERSION_ANTERIOR = "010.1"
VERSION_OBJETIVO = "011.1"

#: Instituciones del escenario y sedes que la migracion debe crear en cada una.
SEDES_ESPERADAS = {"INST-001": 2, "INST-002": 3, "INST-003": 4, "INST-004": 2}
DEPARTAMENTOS_POR_INSTITUCION = {
    "INST-001": 3,
    "INST-002": 4,
    "INST-003": 2,
    "INST-004": 1,
}
PRODUCTOS_POR_INSTITUCION = 2

#: Entidades y columnas que la Feature 011 agrega al DDL.
TABLAS_NUEVAS = ("sede", "stock_sede", "departamento_encargado")
COLUMNAS_NUEVAS = {
    "departamento": "sede_id",
    "usuario": "sede_id",
    "ticket": "sede_id",
    "movimiento_inventario": "stock_sede_id",
}

#: Esquema legado post-010 (12 tablas canonicas con el inventario departamental).
#: Se mantiene aqui, en el test, para no depender de un archivo historico.
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
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT departamento_institucion_uk
        UNIQUE (institucion_id, departamento_id)
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
    descripcion_cat VARCHAR(200),
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT categoria_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT categoria_institucion_uk
        UNIQUE (institucion_id, categoria_id)
);

CREATE TABLE producto (
    producto_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    descripcion VARCHAR(250),
    unidad_medida VARCHAR(30),
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    categoria_id INTEGER NOT NULL,
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT producto_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT producto_categoria_institucion_fk
        FOREIGN KEY (institucion_id, categoria_id)
        REFERENCES categoria(institucion_id, categoria_id),
    CONSTRAINT producto_institucion_uk
        UNIQUE (institucion_id, producto_id),
    CONSTRAINT producto_stock_minimo_ck CHECK (stock_minimo >= 0)
);

CREATE TABLE inventario (
    inventario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    ubicacion VARCHAR(100),
    departamento_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT inventario_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT inventario_departamento_institucion_fk
        FOREIGN KEY (institucion_id, departamento_id)
        REFERENCES departamento(institucion_id, departamento_id),
    CONSTRAINT inventario_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id),
    CONSTRAINT inventario_stock_ck CHECK (stock_actual >= 0),
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
        FOREIGN KEY (inventario_id) REFERENCES inventario(inventario_id),
    CONSTRAINT movimiento_cantidad_ck CHECK (cantidad > 0)
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
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT ticket_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT ticket_usuario_fk
        FOREIGN KEY (usuario_id) REFERENCES usuario(usuario_id),
    CONSTRAINT ticket_prioridad_fk
        FOREIGN KEY (prioridad_id) REFERENCES prioridad(prioridad_id),
    CONSTRAINT ticket_estado_fk
        FOREIGN KEY (estado_id) REFERENCES estado_ticket(estado_id),
    CONSTRAINT ticket_institucion_uk
        UNIQUE (institucion_id, ticket_id)
);

CREATE TABLE detalle_ticket (
    detalle_ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad_solicitada INTEGER NOT NULL,
    cantidad_entregada INTEGER NOT NULL DEFAULT 0,
    institucion_id VARCHAR(20) NOT NULL,
    CONSTRAINT detalle_ticket_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id),
    CONSTRAINT detalle_ticket_ticket_institucion_fk
        FOREIGN KEY (institucion_id, ticket_id)
        REFERENCES ticket(institucion_id, ticket_id),
    CONSTRAINT detalle_ticket_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id),
    CONSTRAINT detalle_cantidad_solicitada_ck CHECK (cantidad_solicitada > 0),
    CONSTRAINT detalle_cantidad_entregada_ck CHECK (cantidad_entregada >= 0)
);
"""


# ---------------------------------------------------------------------------
# Conexion y utilidades
# ---------------------------------------------------------------------------


def _sin_driver(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _url_con_base(url: str, nombre: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))


@contextmanager
def _base_temporal():
    """Crea una base PostgreSQL efimera y la destruye al salir (nunca `apt_erp`)."""
    dsn = _sin_driver(_POSTGRES_TEST_URL or "")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_011_{uuid4().hex[:12]}"
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


def _ejecutar(conexion, sql: str, params=None):
    with conexion.cursor() as cur:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        filas = cur.fetchall() if cur.description else []
    conexion.commit()
    return filas


def _un_escalar(conexion, sql: str, params=None):
    return _ejecutar(conexion, sql, params)[0][0]


def _ejecutar_script(conexion, ruta: Path) -> None:
    _ejecutar(conexion, ruta.read_text(encoding="utf-8"))


def _existe_archivo(ruta: Path) -> None:
    if not ruta.exists():
        pytest.fail(
            f"capacidad ausente (T5): falta el script {ruta.name}; la Feature 011 "
            "lo crea en T5 y hasta entonces esta prueba esta en rojo."
        )


def _esquema_existe(conexion, nombre: str) -> bool:
    return (
        _un_escalar(
            conexion,
            "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
            (nombre,),
        )
        == 1
    )


def _tablas_del_esquema(conexion, esquema: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (esquema,),
    )
    return {fila[0] for fila in filas}


def _columnas_de_tabla(conexion, esquema: str, tabla: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (esquema, tabla),
    )
    return {fila[0] for fila in filas}


def _conteo_tabla(conexion, esquema: str, tabla: str) -> int:
    return _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}"."{tabla}"')


def _valores(conexion, sql: str, params=None):
    return _ejecutar(conexion, sql, params)


# ---------------------------------------------------------------------------
# Sembrado legado y mediciones
# ---------------------------------------------------------------------------


def _sembrar_legado(conexion) -> dict:
    """Cuatro instituciones con departamentos, catalogo, stock y tickets."""
    _ejecutar(
        conexion,
        "INSERT INTO institucion (institucion_id, nombre) VALUES "
        + ", ".join(
            f"('{inst}', 'Institucion {indice}')"
            for indice, inst in enumerate(SEDES_ESPERADAS, start=1)
        ),
    )
    _ejecutar(
        conexion,
        "INSERT INTO rol (rol_id, nombre_rol, descripcion) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Superadmin','Global'), (2,'Administrador','Admin'), "
        "(3,'Bodeguero','Bodega'), (4,'Solicitante','Solicita')",
    )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('rol','rol_id'), 4, true)")

    departamentos: dict[str, list[int]] = {}
    usuarios: dict[str, dict[str, int]] = {}
    productos: dict[str, list[int]] = {}
    inventarios: dict[str, list[int]] = {}

    for indice, (inst, cantidad_deps) in enumerate(
        DEPARTAMENTOS_POR_INSTITUCION.items(), start=1
    ):
        departamentos[inst] = []
        for numero in range(1, cantidad_deps + 1):
            departamento_id = _un_escalar(
                conexion,
                "INSERT INTO departamento (nombre_dep, institucion_id) "
                "VALUES (%s, %s) RETURNING departamento_id",
                (f"Dep {numero} {inst}", inst),
            )
            departamentos[inst].append(departamento_id)

        usuarios[inst] = {}
        for sufijo, rol_id in (
            ("administrador", 2),
            ("bodeguero", 3),
            ("solicitante", 4),
        ):
            usuarios[inst][sufijo] = _un_escalar(
                conexion,
                "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING usuario_id",
                (
                    sufijo.capitalize(),
                    inst,
                    f"{sufijo}.{inst.lower()}@compustock.cl",
                    departamentos[inst][0],
                    rol_id,
                ),
            )
        productos[inst] = []
        categoria_id = _un_escalar(
            conexion,
            "INSERT INTO categoria (nombre_cat, institucion_id) "
            "VALUES (%s, %s) RETURNING categoria_id",
            (f"Catalogo {inst}", inst),
        )
        for numero in range(1, PRODUCTOS_POR_INSTITUCION + 1):
            producto_id = _un_escalar(
                conexion,
                "INSERT INTO producto (nombre, unidad_medida, stock_minimo, categoria_id, institucion_id) "
                "VALUES (%s, 'UNIDAD', %s, %s, %s) RETURNING producto_id",
                (f"Producto {numero} {inst}", 10 if numero == 1 else 5, categoria_id, inst),
            )
            productos[inst].append(producto_id)

        inventarios[inst] = []
        for posicion, departamento_id in enumerate(departamentos[inst]):
            for numero, producto_id in enumerate(productos[inst]):
                stock = 6 + posicion * 4 + numero
                inventario_id = _un_escalar(
                    conexion,
                    "INSERT INTO inventario (stock_actual, ubicacion, departamento_id, producto_id, institucion_id) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING inventario_id",
                    (stock, f"Estante {numero}", departamento_id, producto_id, inst),
                )
                inventarios[inst].append(inventario_id)
                _ejecutar(
                    conexion,
                    "INSERT INTO movimiento_inventario (tipo_movimiento, cantidad, inventario_id) "
                    "VALUES ('ENTRADA', %s, %s)",
                    (stock, inventario_id),
                )

    # Superadmin local (vive en control tras la migracion, no se replica a tenant).
    _ejecutar(
        conexion,
        "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
        "VALUES ('Super', 'Admin', 'super@compustock.cl', %s, 1)",
        (departamentos["INST-001"][0],),
    )

    _ejecutar(
        conexion,
        "INSERT INTO prioridad (prioridad_id, nombre) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Alta'), (2,'Media'), (3,'Baja')",
    )
    _ejecutar(
        conexion,
        "INSERT INTO estado_ticket (estado_id, nombre) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Pendiente'), (2,'EnRevision'), (3,'EnCurso'), (4,'Cerrado')",
    )
    for inst in SEDES_ESPERADAS:
        ticket_id = _un_escalar(
            conexion,
            "INSERT INTO ticket (usuario_id, prioridad_id, estado_id, asunto, institucion_id) "
            "VALUES (%s, 1, 1, %s, %s) RETURNING ticket_id",
            (usuarios[inst]["solicitante"], f"Solicitud {inst}", inst),
        )
        _ejecutar(
            conexion,
            "INSERT INTO detalle_ticket (ticket_id, producto_id, cantidad_solicitada, institucion_id) "
            "VALUES (%s, %s, 2, %s)",
            (ticket_id, productos[inst][0], inst),
        )

    return {
        "departamentos": departamentos,
        "usuarios": usuarios,
        "productos": productos,
    }


def _totales_por_producto(conexion, esquema: str) -> dict[int, int]:
    """Suma departamental por producto (referencia externa del cuadre)."""
    filas = _valores(
        conexion,
        f'SELECT producto_id, sum(stock_actual) FROM "{esquema}".inventario '
        "GROUP BY producto_id",
    )
    return {fila[0]: fila[1] for fila in filas}


def _firma_inventario(conexion, esquema: str):
    return _valores(
        conexion,
        f'SELECT inventario_id, stock_actual, departamento_id, producto_id '
        f'FROM "{esquema}".inventario ORDER BY inventario_id',
    )


def _firma_movimientos_legados(conexion, esquema: str):
    return _valores(
        conexion,
        f'SELECT movimiento_id, tipo_movimiento, cantidad, inventario_id '
        f'FROM "{esquema}".movimiento_inventario '
        "WHERE inventario_id IS NOT NULL ORDER BY movimiento_id",
    )


def _esquema_de_institucion(conexion, institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _migrar_a_011(conexion) -> None:
    _existe_archivo(MIGRACION_011)
    _ejecutar_script(conexion, MIGRACION_011)


@contextmanager
def _base_migrada():
    """Base temporal con el estado post-010 y las mediciones previas ya tomadas."""
    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)
        _ejecutar_script(conexion, MIGRACION_010)

        mediciones = {}
        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            mediciones[inst] = {
                "totales": _totales_por_producto(conexion, esquema),
                "inventario": _firma_inventario(conexion, esquema),
                "movimientos": _firma_movimientos_legados(conexion, esquema),
            }
        yield conexion, mediciones


# ---------------------------------------------------------------------------
# AC-10/AC-12: estructura, sedes y version
# ---------------------------------------------------------------------------


def test_migracion_011_crea_estructura_y_versiona():
    """AC-12: `control` y cada tenant reciben la estructura nueva y `011.1`."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)

        assert _esquema_existe(conexion, "control")
        assert "version_esquema" in _tablas_del_esquema(conexion, "control")
        version_control = _valores(
            conexion, "SELECT version FROM control.version_esquema"
        )
        assert version_control == [(VERSION_OBJETIVO,)], (
            "control tambien queda en la version objetivo"
        )

        for inst, sedes_esperadas in SEDES_ESPERADAS.items():
            esquema = _esquema_de_institucion(conexion, inst)
            assert _esquema_existe(conexion, esquema)
            tablas = _tablas_del_esquema(conexion, esquema)
            for tabla in TABLAS_NUEVAS:
                assert tabla in tablas, (inst, tabla)
            for tabla, columna in COLUMNAS_NUEVAS.items():
                assert columna in _columnas_de_tabla(conexion, esquema, tabla), (
                    inst,
                    tabla,
                    columna,
                )
            assert _valores(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            ) == [(VERSION_OBJETIVO,)]
            assert (
                _conteo_tabla(conexion, esquema, "sede") == sedes_esperadas
            ), f"{inst} debe recibir {sedes_esperadas} sedes"


def test_migracion_011_reparte_departamentos_por_round_robin():
    """AC-10: el departamento i va a la sede i mod N, con orden determinista."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)

        for inst, sedes_esperadas in SEDES_ESPERADAS.items():
            esquema = _esquema_de_institucion(conexion, inst)
            departamentos = [
                fila[0]
                for fila in _valores(
                    conexion,
                    f'SELECT departamento_id FROM "{esquema}".departamento '
                    "ORDER BY departamento_id",
                )
            ]
            sedes = [
                fila[0]
                for fila in _valores(
                    conexion,
                    f'SELECT sede_id FROM "{esquema}".sede ORDER BY sede_id',
                )
            ]
            asignadas = {
                fila[0]: fila[1]
                for fila in _valores(
                    conexion,
                    f'SELECT departamento_id, sede_id FROM "{esquema}".departamento '
                    "ORDER BY departamento_id",
                )
            }
            assert len(departamentos) == DEPARTAMENTOS_POR_INSTITUCION[inst]
            assert len(sedes) == sedes_esperadas
            esperado = {
                departamento_id: sedes[posicion % sedes_esperadas]
                for posicion, departamento_id in enumerate(departamentos)
            }
            assert asignadas == esperado, f"reparto no determinista en {inst}"


def test_migracion_011_conserva_los_totales_por_producto():
    """AC-10: la suma de saldos por sede iguala el total medido antes de migrar."""
    with _base_migrada() as (conexion, mediciones):
        _migrar_a_011(conexion)

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            filas = _valores(
                conexion,
                f'SELECT producto_id, sum(stock_actual) FROM "{esquema}".stock_sede '
                "GROUP BY producto_id",
            )
            obtenido = {fila[0]: fila[1] for fila in filas}
            assert obtenido == mediciones[inst]["totales"], (
                f"{inst}: el cuadre por producto debe ser exacto"
            )


def test_migracion_011_cada_saldo_equivale_a_sus_movimientos_de_consolidacion():
    """AC-10: cada `(sede, producto)` arranca con movimientos `ENTRADA` nuevos."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            filas = _valores(
                conexion,
                f"SELECT s.stock_sede_id, s.stock_actual, "
                f"coalesce((SELECT sum(m.cantidad) FROM \"{esquema}\".movimiento_inventario m "
                f"WHERE m.stock_sede_id = s.stock_sede_id AND m.tipo_movimiento = 'ENTRADA'), 0) "
                f'FROM "{esquema}".stock_sede s ORDER BY s.stock_sede_id',
            )
            assert filas, f"{inst}: debe haber saldos por sede"
            for stock_sede_id, stock_actual, consolidado in filas:
                assert stock_actual == consolidado, (
                    f"{inst}: el saldo de {stock_sede_id} debe cuadrar con su "
                    "consolidacion"
                )

            enlaces_invalidos = _un_escalar(
                conexion,
                f'SELECT count(*) FROM "{esquema}".movimiento_inventario '
                "WHERE stock_sede_id IS NOT NULL AND inventario_id IS NOT NULL",
            )
            assert enlaces_invalidos == 0, (
                "un movimiento nuevo usa stock por sede y no el inventario legado"
            )


def test_migracion_011_no_reescribe_auditoria_ni_inventario_legado():
    """AC-10: el inventario y los movimientos historicos conservan su firma."""
    with _base_migrada() as (conexion, mediciones):
        _migrar_a_011(conexion)

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            assert _firma_inventario(conexion, esquema) == mediciones[inst]["inventario"]
            assert (
                _firma_movimientos_legados(conexion, esquema)
                == mediciones[inst]["movimientos"]
            ), "los movimientos historicos no se actualizan, borran ni reasignan"


def test_migracion_011_asigna_sede_a_los_tickets_historicos():
    """AC-9/AC-10: los tickets legados quedan atribuidos a la sede de su departamento."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            filas = _valores(
                conexion,
                f"SELECT t.ticket_id, t.sede_id, d.sede_id "
                f'FROM "{esquema}".ticket t '
                f'JOIN "{esquema}".usuario u ON u.usuario_id = t.usuario_id '
                f'JOIN "{esquema}".departamento d ON d.departamento_id = u.departamento_id',
            )
            assert filas, f"{inst}: no hay tickets del seed"
            for ticket_id, sede_ticket, sede_departamento in filas:
                assert sede_ticket is not None, (inst, ticket_id)
                assert sede_ticket == sede_departamento, (inst, ticket_id)


def test_migracion_011_es_idempotente():
    """AC-10: una segunda ejecucion no duplica sedes, saldos ni auditoria."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)

        antes = {}
        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            antes[inst] = {
                tabla: _conteo_tabla(conexion, esquema, tabla)
                for tabla in ("sede", "stock_sede", "movimiento_inventario", "version_esquema")
            }

        _migrar_a_011(conexion)

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            for tabla, conteo in antes[inst].items():
                assert _conteo_tabla(conexion, esquema, tabla) == conteo, (inst, tabla)
            assert _valores(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            ) == [(VERSION_OBJETIVO,)]


def test_migracion_011_aborta_ante_estado_parcial_sin_cambios():
    """AC-10: un tenant con estructura parcial aborta y no consolida nada."""
    with _base_migrada() as (conexion, _mediciones):
        esquema_parcial = _esquema_de_institucion(conexion, "INST-002")
        _ejecutar(conexion, f'CREATE TABLE "{esquema_parcial}".sede (sede_id integer)')

        _existe_archivo(MIGRACION_011)
        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION_011)
        conexion.rollback()
        assert "parcial" in str(excinfo.value).lower() or "sede" in str(
            excinfo.value
        ).lower(), excinfo.value

        for inst in SEDES_ESPERADAS:
            esquema = _esquema_de_institucion(conexion, inst)
            assert "stock_sede" not in _tablas_del_esquema(conexion, esquema), inst
            assert _valores(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            ) == [(VERSION_ANTERIOR,)], f"{inst} no debe quedar versionado en 011.1"


def test_migracion_011_exige_unicidad_y_stock_no_negativo():
    """AC-2: la tabla de saldos por sede hace cumplir unicidad y no-negatividad."""
    with _base_migrada() as (conexion, _mediciones):
        _migrar_a_011(conexion)
        esquema = _esquema_de_institucion(conexion, "INST-001")

        fila = _valores(
            conexion,
            f'SELECT sede_id, producto_id FROM "{esquema}".stock_sede '
            "ORDER BY stock_sede_id LIMIT 1",
        )
        assert fila, "el seed debe producir al menos un saldo por sede"
        sede_id, producto_id = fila[0]

        with pytest.raises(psycopg2.Error):
            _ejecutar(
                conexion,
                f'INSERT INTO "{esquema}".stock_sede (sede_id, producto_id, stock_actual) '
                "VALUES (%s, %s, 1)",
                (sede_id, producto_id),
            )
        conexion.rollback()

        with pytest.raises(psycopg2.Error):
            _ejecutar(
                conexion,
                f'UPDATE "{esquema}".stock_sede SET stock_actual = -5 WHERE sede_id = %s',
                (sede_id,),
            )
        conexion.rollback()


# ---------------------------------------------------------------------------
# AC-13: instalacion limpia y guardia fail-closed
# ---------------------------------------------------------------------------


def test_instalacion_limpia_crea_sedes_y_conserva_la_guardia():
    """AC-12/AC-13: `01_` + `02_` dejan sedes QA coherentes y abortan al repetirse."""
    with _base_temporal() as conexion:
        _existe_archivo(ESQUEMA_SQL)
        _existe_archivo(SEMILLA_SQL)
        _ejecutar_script(conexion, ESQUEMA_SQL)
        _ejecutar_script(conexion, SEMILLA_SQL)

        tablas = _tablas_del_esquema(conexion, "control")
        for tabla in TABLAS_NUEVAS:
            assert tabla in tablas, tabla

        assert _conteo_tabla(conexion, "control", "institucion") == len(SEDES_ESPERADAS)
        for inst, sedes_esperadas in SEDES_ESPERADAS.items():
            conteo = _un_escalar(
                conexion,
                "SELECT count(*) FROM control.sede WHERE institucion_id = %s",
                (inst,),
            )
            assert conteo == sedes_esperadas, (inst, conteo)

        departamentos_sin_sede = _un_escalar(
            conexion,
            "SELECT count(*) FROM control.departamento "
            "WHERE institucion_id = ANY(%s) AND sede_id IS NULL",
            (list(SEDES_ESPERADAS),),
        )
        assert departamentos_sin_sede == 0, "todos los departamentos QA tienen sede"

        cuadre = _un_escalar(
            conexion,
            "SELECT count(*) FROM ("
            "  SELECT i.producto_id, sum(i.stock_actual) AS departamental,"
            "         coalesce((SELECT sum(s.stock_actual) FROM control.stock_sede s"
            "                   WHERE s.producto_id = i.producto_id), 0) AS por_sede"
            "  FROM control.inventario i GROUP BY i.producto_id"
            ") AS totales WHERE departamental <> por_sede",
        )
        assert cuadre == 0, "la semilla limpia debe cuadrar por producto"

        # La guardia fail-closed sigue viva: una segunda semilla aborta.
        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, SEMILLA_SQL)
        conexion.rollback()
        assert "abortada" in str(excinfo.value).lower(), excinfo.value
