"""T9 (Feature 010): migracion multi-tenant sobre PostgreSQL 16 real.

Complemento gated de la suite SQLite. SQLite no reproduce namespaces ni la
semantica de esquemas PostgreSQL, asi que la migracion de la base existente solo
puede acreditarse aqui:

  * **preflight fail-closed**: una fila sin institucion resoluble aborta SIN
    CAMBIOS (no se crea `control` ni ningun tenant);
  * **particion por institucion**: las filas llegan a su esquema tenant
    (`usuario` via `departamento`, `movimiento_inventario` via `inventario`), con
    IDs, relaciones y secuencias preservados;
  * **control**: registro de instituciones, catalogo `rol`, identidad Superadmin
    y mapa `correo -> esquema` de TODOS los usuarios locales;
  * **espejo + catalogos + version**: cada tenant tiene las doce tablas, la fila
    `institucion` espejo, `rol`/`prioridad`/`estado_ticket` replicados y
    `version_esquema = '010.1'`;
  * **idempotencia**: una segunda ejecucion no altera datos operativos;
  * **estado parcial**: un esquema tenant preexistente sin version objetivo
    aborta sin cambios.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_migracion_multitenant_010.py

    La URL apunta a una base de mantenimiento donde el test crea y DESTRUYE una
    base temporal propia; nunca toca `apt_erp` ni `compustock_db`. Sin
    `POSTGRES_TEST_URL` los tests se saltan con una razon clara. NO se anade
    ninguna dependencia: `psycopg2` ya esta en `requirements.txt`.
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

RAIZ = Path(__file__).resolve().parents[2]
MIGRACION = (
    RAIZ / "database" / "migraciones" / "001_migracion_multitenant_esquemas.sql"
)

VERSION_OBJETIVO = "010.1"

#: Esquema LEGADO post-008 reconstruido: las doce tablas canonicas en `public`,
#: con las columnas de pertenencia y las claves compuestas de la Feature 008 y
#: SIN el esquema de control. Es la forma exacta de `apt_erp` antes de la 010; se
#: mantiene aqui, en el test, para no depender de un archivo historico.
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

#: Doce tablas canonicas que todo tenant reproduce.
TABLAS_DOMINIO = (
    "institucion",
    "departamento",
    "rol",
    "usuario",
    "categoria",
    "producto",
    "inventario",
    "movimiento_inventario",
    "prioridad",
    "estado_ticket",
    "ticket",
    "detalle_ticket",
)


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
    nombre = f"compustock_010_{uuid4().hex[:12]}"
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
            # Sin parametros: psycopg2 no interpreta los `%` del SQL (el script
            # de migracion los usa en `format()`/`RAISE`).
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


def _esquema_existe(conexion, nombre: str) -> bool:
    return _un_escalar(
        conexion, "SELECT count(*) FROM pg_namespace WHERE nspname = %s", (nombre,)
    ) == 1


def _tablas_del_esquema(conexion, esquema: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (esquema,),
    )
    return {f[0] for f in filas}


def _conteo_tabla(conexion, esquema: str, tabla: str) -> int:
    return _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}"."{tabla}"')


def _ids(conexion, esquema: str, tabla: str, columna: str) -> list:
    return sorted(
        f[0]
        for f in _ejecutar(
            conexion, f'SELECT "{columna}" FROM "{esquema}"."{tabla}"'
        )
    )


def _siguiente_id(conexion, esquema: str, tabla: str, columna: str) -> int:
    return _un_escalar(
        conexion,
        "SELECT nextval(pg_get_serial_sequence(%s, %s))",
        (f"{esquema}.{tabla}", columna),
    )


# ---------------------------------------------------------------------------
# Sembrado del esquema legado
# ---------------------------------------------------------------------------


def _sembrar_legado(conexion) -> dict:
    """Dos instituciones con datos coherentes; devuelve los IDs usados."""
    _ejecutar(
        conexion,
        "INSERT INTO institucion (institucion_id, nombre) VALUES "
        "('INST-001','Instituto A'), ('INST-002','Instituto B')",
    )
    # Roles con IDs explicitos (como la base real: 1 Superadmin).
    _ejecutar(
        conexion,
        "INSERT INTO rol (rol_id, nombre_rol, descripcion) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Superadmin','Global'), (2,'Administrador','Admin'), "
        "(3,'Bodeguero','Bodega'), (4,'Solicitante','Solicita')",
    )
    _ejecutar(
        conexion,
        "SELECT setval(pg_get_serial_sequence('rol','rol_id'), 4, true)",
    )
    deps = {}
    for inst in ("INST-001", "INST-002"):
        deps[inst] = _un_escalar(
            conexion,
            "INSERT INTO departamento (nombre_dep, institucion_id) VALUES (%s, %s) "
            "RETURNING departamento_id",
            (f"Dep {inst}", inst),
        )
    usuarios = {
        "super": (1, "super@compustock.cl", "INST-001", 1),
        "admin_a": (2, "admin.a@inst1.cl", "INST-001", 2),
        "sol_a": (3, "sol.a@inst1.cl", "INST-001", 4),
        "bod_b": (4, "bod.b@inst2.cl", "INST-002", 3),
    }
    for _clave, (uid, correo, inst, rol) in usuarios.items():
        _ejecutar(
            conexion,
            "INSERT INTO usuario (usuario_id, nombre, apellido, correo, departamento_id, rol_id) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s)",
            (uid, "N", "A", correo, deps[inst], rol),
        )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('usuario','usuario_id'), 4, true)")

    # Catalogos.
    _ejecutar(
        conexion,
        "INSERT INTO prioridad (prioridad_id, nombre) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Alta'), (2,'Media'), (3,'Baja')",
    )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('prioridad','prioridad_id'), 3, true)")
    _ejecutar(
        conexion,
        "INSERT INTO estado_ticket (estado_id, nombre) OVERRIDING SYSTEM VALUE VALUES "
        "(1,'Pendiente'), (2,'EnRevision'), (3,'EnCurso'), (4,'Cerrado')",
    )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('estado_ticket','estado_id'), 4, true)")

    # Catalogo institucional + stock + tickets (IDs explicitos y preservados).
    cat = {}
    prod = {}
    inv = {}
    for idx, inst in enumerate(("INST-001", "INST-002"), start=1):
        cat[inst] = _un_escalar(
            conexion,
            "INSERT INTO categoria (categoria_id, nombre_cat, institucion_id) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s) RETURNING categoria_id",
            (idx, f"Cat {inst}", inst),
        )
        prod[inst] = _un_escalar(
            conexion,
            "INSERT INTO producto (producto_id, nombre, categoria_id, institucion_id) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s) RETURNING producto_id",
            (idx, f"Prod {inst}", cat[inst], inst),
        )
        inv[inst] = _un_escalar(
            conexion,
            "INSERT INTO inventario (inventario_id, stock_actual, departamento_id, producto_id, institucion_id) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s) RETURNING inventario_id",
            (idx, 10 * idx, deps[inst], prod[inst], inst),
        )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('categoria','categoria_id'), 2, true)")
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('producto','producto_id'), 2, true)")
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('inventario','inventario_id'), 2, true)")

    # Movimientos via inventario (uno por institucion).
    mov = {}
    for idx, inst in enumerate(("INST-001", "INST-002"), start=1):
        mov[inst] = _un_escalar(
            conexion,
            "INSERT INTO movimiento_inventario (movimiento_id, tipo_movimiento, cantidad, inventario_id) "
            "OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s) RETURNING movimiento_id",
            (idx, "ENTRADA", idx, inv[inst]),
        )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('movimiento_inventario','movimiento_id'), 2, true)")

    # Tickets + detalles (solo para INST-001).
    ticket_id = _un_escalar(
        conexion,
        "INSERT INTO ticket (ticket_id, usuario_id, prioridad_id, estado_id, asunto, institucion_id) "
        "OVERRIDING SYSTEM VALUE VALUES (1, 3, 1, 1, 'Asunto', 'INST-001') RETURNING ticket_id",
    )
    _ejecutar(
        conexion,
        "INSERT INTO detalle_ticket (detalle_ticket_id, ticket_id, producto_id, cantidad_solicitada, institucion_id) "
        "OVERRIDING SYSTEM VALUE VALUES (1, %s, %s, 5, 'INST-001')",
        (ticket_id, prod["INST-001"]),
    )
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('ticket','ticket_id'), 1, true)")
    _ejecutar(conexion, "SELECT setval(pg_get_serial_sequence('detalle_ticket','detalle_ticket_id'), 1, true)")

    return {
        "dept": deps,
        "prod": prod,
        "inv": inv,
        "mov": mov,
        "cat": cat,
        "usuarios": usuarios,
    }


# ---------------------------------------------------------------------------
# AC-10/AC-13: un tenant versionado por institucion, con espejo y catalogos
# ---------------------------------------------------------------------------


def test_migracion_crea_control_y_tenants_versionados():
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)

        _ejecutar_script(conexion, MIGRACION)

        # Control existe y conserva el registro institucional.
        assert _esquema_existe(conexion, "control")
        assert _conteo_tabla(conexion, "control", "institucion") == 2
        assert "mapa_usuario_esquema" in _tablas_del_esquema(conexion, "control")

        # Un esquema tenant por institucion, con las doce tablas + version.
        for inst in ("INST-001", "INST-002"):
            esquema = nombre_esquema_para_institucion(inst)
            assert _esquema_existe(conexion, esquema), esquema
            assert set(TABLAS_DOMINIO) <= _tablas_del_esquema(conexion, esquema)
            assert _conteo_tabla(conexion, esquema, "institucion") == 1, "espejo"
            # Version objetivo exacta, una sola fila.
            versiones = _ejecutar(
                conexion, f'SELECT version FROM "{esquema}".version_esquema'
            )
            assert versiones == [(VERSION_OBJETIVO,)]

        # Catalogos replicados por tenant: rol sin Superadmin, prioridad y
        # estado_ticket completos, con IDs preservados.
        tenant = nombre_esquema_para_institucion("INST-001")
        assert _ids(conexion, tenant, "rol", "rol_id") == [2, 3, 4]
        assert _ids(conexion, tenant, "prioridad", "prioridad_id") == [1, 2, 3]
        assert _ids(conexion, tenant, "estado_ticket", "estado_id") == [1, 2, 3, 4]


def test_migracion_particiona_por_institucion_preservando_ids_y_relaciones():
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        ids = _sembrar_legado(conexion)

        _ejecutar_script(conexion, MIGRACION)

        t1 = nombre_esquema_para_institucion("INST-001")
        t2 = nombre_esquema_para_institucion("INST-002")

        # usuario por departamento; el Superadmin NO se replica a ningun tenant.
        assert _ids(conexion, t1, "usuario", "usuario_id") == [2, 3]
        assert _ids(conexion, t2, "usuario", "usuario_id") == [4]

        # Resto de tablas por institucion_id directo.
        assert _ids(conexion, t1, "categoria", "categoria_id") == [1]
        assert _ids(conexion, t2, "categoria", "categoria_id") == [2]
        assert _ids(conexion, t1, "producto", "producto_id") == [1]
        assert _ids(conexion, t2, "producto", "producto_id") == [2]
        assert _ids(conexion, t1, "inventario", "inventario_id") == [1]
        assert _ids(conexion, t2, "inventario", "inventario_id") == [2]
        assert _ids(conexion, t1, "ticket", "ticket_id") == [1]
        assert _ids(conexion, t2, "ticket", "ticket_id") == []
        assert _ids(conexion, t1, "detalle_ticket", "detalle_ticket_id") == [1]

        # movimiento_inventario por inventario (una fila por institucion).
        assert _ids(conexion, t1, "movimiento_inventario", "movimiento_id") == [1]
        assert _ids(conexion, t2, "movimiento_inventario", "movimiento_id") == [2]

        # Relaciones internas del tenant coherentes: el detalle apunta al
        # producto local y el ticket al usuario local.
        assert _un_escalar(
            conexion,
            f'SELECT producto_id FROM "{t1}".detalle_ticket WHERE detalle_ticket_id = 1',
        ) == ids["prod"]["INST-001"]
        assert _un_escalar(
            conexion,
            f'SELECT usuario_id FROM "{t1}".ticket WHERE ticket_id = 1',
        ) == 3

        # Secuencias continuas por esquema (siguiente = max + 1).
        assert _siguiente_id(conexion, t1, "categoria", "categoria_id") == 2
        assert _siguiente_id(conexion, t1, "movimiento_inventario", "movimiento_id") == 2
        assert _siguiente_id(conexion, t2, "usuario", "usuario_id") == 5


def test_migracion_control_mapea_todos_los_usuarios():
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)

        _ejecutar_script(conexion, MIGRACION)

        filas = _ejecutar(
            conexion,
            "SELECT correo, institucion_id, nombre_esquema, activo "
            "FROM control.mapa_usuario_esquema ORDER BY correo",
        )
        mapa = {f[0]: f for f in filas}

        # Todos los usuarios locales del legado tienen una fila.
        assert len(mapa) == 4

        # Superadmin -> esquema reservado `control`.
        assert mapa["super@compustock.cl"][2] == "control"
        # Los demas, a su tenant derivado.
        assert mapa["admin.a@inst1.cl"][2] == nombre_esquema_para_institucion("INST-001")
        assert mapa["sol.a@inst1.cl"][2] == nombre_esquema_para_institucion("INST-001")
        assert mapa["bod.b@inst2.cl"][2] == nombre_esquema_para_institucion("INST-002")
        assert all(f[3] is True for f in filas)

        # Control conserva la identidad Superadmin (no todas las identidades).
        assert _conteo_tabla(conexion, "control", "usuario") == 1
        assert _un_escalar(
            conexion, "SELECT correo FROM control.usuario"
        ) == "super@compustock.cl"
        assert _conteo_tabla(conexion, "control", "departamento") == 1

        # El esquema legado `public` conserva sus filas intactas.
        assert _conteo_tabla(conexion, "public", "usuario") == 4
        assert _conteo_tabla(conexion, "public", "ticket") == 1


def test_migracion_segunda_ejecucion_es_idempotente():
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)

        _ejecutar_script(conexion, MIGRACION)

        t1 = nombre_esquema_para_institucion("INST-001")
        antes = {
            "usuario_t1": _conteo_tabla(conexion, t1, "usuario"),
            "mapa": _conteo_tabla(conexion, "control", "mapa_usuario_esquema"),
            "control_institucion": _conteo_tabla(conexion, "control", "institucion"),
            "version_t1": _conteo_tabla(conexion, t1, "version_esquema"),
        }

        # Segunda ejecucion: no altera nada.
        _ejecutar_script(conexion, MIGRACION)

        assert _conteo_tabla(conexion, t1, "usuario") == antes["usuario_t1"]
        assert _conteo_tabla(conexion, "control", "mapa_usuario_esquema") == antes["mapa"]
        assert _conteo_tabla(conexion, "control", "institucion") == antes["control_institucion"]
        assert _conteo_tabla(conexion, t1, "version_esquema") == antes["version_t1"]
        # El tenant sigue en la version objetivo.
        assert _ejecutar(
            conexion, f'SELECT version FROM "{t1}".version_esquema'
        ) == [(VERSION_OBJETIVO,)]


def test_nombre_esquema_sql_reproduce_exactamente_python():
    """El fallback SQL del nombre replica 1:1 a `tenant_service`."""
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
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)
        # Ejecuta la migracion para materializar `pg_temp.nombre_esquema_tenant`.
        _ejecutar_script(conexion, MIGRACION)

        for identificador in bateria:
            del_sql = _un_escalar(
                conexion,
                "SELECT pg_temp.nombre_esquema_tenant(%s)",
                (identificador,),
            )
            assert del_sql == nombre_esquema_para_institucion(identificador), identificador


def test_migracion_crea_superadmin_si_la_base_no_lo_trae():
    """Si el legado no trae Superadmin, control crea la identidad administrativa."""
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _ejecutar(
            conexion,
            "INSERT INTO institucion (institucion_id, nombre) VALUES ('INST-001','Instituto A')",
        )
        _ejecutar(
            conexion,
            "INSERT INTO rol (rol_id, nombre_rol) OVERRIDING SYSTEM VALUE VALUES (2,'Administrador')",
        )
        dep = _un_escalar(
            conexion,
            "INSERT INTO departamento (nombre_dep, institucion_id) VALUES ('Dep','INST-001') "
            "RETURNING departamento_id",
        )
        _ejecutar(
            conexion,
            "INSERT INTO usuario (nombre, apellido, correo, departamento_id, rol_id) "
            "VALUES ('Admin','A','admin@inst1.cl',%s,2)",
            (dep,),
        )

        _ejecutar_script(conexion, MIGRACION)

        # Control crea la institucion administrativa y la identidad Superadmin.
        assert _un_escalar(
            conexion,
            "SELECT count(*) FROM control.rol WHERE nombre_rol = 'Superadmin'",
        ) == 1
        assert _un_escalar(
            conexion,
            "SELECT count(*) FROM control.usuario u JOIN control.rol r ON r.rol_id = u.rol_id "
            "WHERE r.nombre_rol = 'Superadmin'",
        ) == 1
        assert _un_escalar(
            conexion,
            "SELECT count(*) FROM control.institucion WHERE institucion_id = 'CTRL-SAAS'",
        ) == 1

        # El usuario del tenant esta mapeado y su tenant tiene el rol Administrador.
        fila = _ejecutar(
            conexion,
            "SELECT nombre_esquema FROM control.mapa_usuario_esquema WHERE correo = 'admin@inst1.cl'",
        )
        assert fila == [(nombre_esquema_para_institucion("INST-001"),)]
        assert _ids(
            conexion, nombre_esquema_para_institucion("INST-001"), "rol", "rol_id"
        ) == [2]


# ---------------------------------------------------------------------------
# AC-10/AC-11: aborto sin cambios ante ambiguedad o estado parcial
# ---------------------------------------------------------------------------


def test_migracion_aborta_ante_fila_ambigua_sin_cambios():
    """Un movimiento sin inventario resoluble aborta y no crea control/tenants."""
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)
        # Se relaja la FK y se inserta un movimiento huerfano: institucion no
        # resoluble via inventario.
        _ejecutar(
            conexion,
            "ALTER TABLE movimiento_inventario DROP CONSTRAINT movimiento_inventario_fk",
        )
        _ejecutar(
            conexion,
            "INSERT INTO movimiento_inventario (movimiento_id, tipo_movimiento, cantidad, inventario_id) "
            "OVERRIDING SYSTEM VALUE VALUES (99, 'SALIDA', 1, 9999)",
        )

        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION)
        conexion.rollback()
        assert "movimiento_inventario" in str(excinfo.value).lower()

        # Sin cambios: ni control ni tenants.
        assert not _esquema_existe(conexion, "control")
        assert not _esquema_existe(
            conexion, nombre_esquema_para_institucion("INST-001")
        )
        assert _conteo_tabla(conexion, "public", "institucion") == 2


def test_migracion_aborta_ante_tenant_preexistente_sin_version():
    """Un esquema tenant preexistente sin version objetivo aborta sin cambios."""
    from app.services.tenant_service import nombre_esquema_para_institucion

    with _base_temporal() as conexion:
        _ejecutar(conexion, DDL_LEGADO)
        _sembrar_legado(conexion)
        esquema = nombre_esquema_para_institucion("INST-001")
        _ejecutar(conexion, f'CREATE SCHEMA "{esquema}"')

        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, MIGRACION)
        conexion.rollback()
        assert "estado parcial" in str(excinfo.value).lower()

        # El esquema de control no se creo (aborto antes de mutar).
        assert not _esquema_existe(conexion, "control")
