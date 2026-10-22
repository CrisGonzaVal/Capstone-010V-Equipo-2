"""Instalacion limpia de Compustock: `01_esquema.sql` + `02_datos_semilla.sql` - gated.

Seam bajo prueba: los dos scripts de instalacion ejecutados en ese orden sobre
una base vacia, tal como lo hace el volumen de `docker compose`
(`docker-entrypoint-initdb.d`). SQLite no reproduce namespaces, FKs compuestas
ni el DDL por esquema, asi que lo que la instalacion limpia exige solo se
acredita contra PostgreSQL 16 real:

  * `control` con las 22 tablas globales (Feature 017 anade
    `registro_motivo_constancia`; la 014, los dos historiales de transicion del
    catalogo) y **un esquema tenant por institucion** con las 19 tablas de
    negocio replicadas;
  * reparto deterministico de sedes (2/3/4/2 para INST-001..004) y de
    departamentos por round-robin sobre `departamento_id` ascendente;
  * cuadre por producto dentro de cada tenant: la suma departamental de
    `inventario` es igual a la suma por sede de `stock_sede`;
  * `control` queda como contexto global (sin filas de negocio), con la
    topologia (4 instituciones + 24 capacidades), el catalogo de roles y el
    estado `Anulado`, y el mapa `correo -> esquema` con las 12 identidades;
  * version objetivo `014.1` en `control` y en cada tenant (expectativa
    planificada de la Feature 014: se fija como literal, no se sigue del token),
    con el catalogo sembrado activo por tenant y el routing exigiendo esa misma
    version (una version menor no se enruta);
  * guardia fail-closed: una segunda ejecucion de `02_` aborta sin cambios.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_instalacion_limpia_postgres.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan** con una razon clara y la
    suite local (SQLite) sigue verde. La URL apunta a una base de mantenimiento
    donde el test **crea y destruye** una base temporal propia; no toca `apt_erp`.

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

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from app.core.config import VERSION_ESQUEMA_OBJETIVO

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
ESQUEMA_SQL = RAIZ / "database" / "01_esquema.sql"
SEMILLA_SQL = RAIZ / "database" / "02_datos_semilla.sql"

#: Reparto fijo de sedes por institucion (Feature 011, D-7).
SEDES_ESPERADAS = {"INST-001": 2, "INST-002": 3, "INST-003": 4, "INST-004": 2}

#: Version objetivo planificada de la Feature 014 (AC-14). Se fija como literal
#: para que la expectativa no siga automaticamente al token del codigo: T4 crea
#: el DDL y T5 sube `VERSION_ESQUEMA_OBJETIVO` a este mismo valor.
VERSION_OBJETIVO_014 = "014.1"

#: Las 22 tablas globales de `control`.
TABLAS_CONTROL = {
    "institucion",
    "sede",
    "departamento",
    "rol",
    "usuario",
    "departamento_encargado",
    "categoria",
    "producto",
    "inventario",
    "stock_sede",
    "movimiento_inventario",
    "prioridad",
    "estado_ticket",
    "ticket",
    "detalle_ticket",
    "historial_transicion_ticket",
    # Feature 014 (stack §2): los dos historiales del ciclo de vida del catalogo
    # son entidades de dominio y se crean en control y en cada tenant.
    "historial_transicion_producto",
    "historial_transicion_categoria",
    "funcion_institucion",
    "mapa_usuario_esquema",
    "version_esquema",
    "registro_motivo_constancia",
}

#: Las 19 tablas de negocio que cada tenant replica. Las tres auxiliares de
#: control (capacidades, mapa y motivos/constancias) nunca viajan al tenant.
TABLAS_TENANT = TABLAS_CONTROL - {
    "funcion_institucion",
    "mapa_usuario_esquema",
    "registro_motivo_constancia",
}

#: Conteos de `control` tras la semilla (topologia y contexto global).
CONTROL_ESPERADO = {
    "institucion": 4,
    "funcion_institucion": 24,
    "rol": 4,
    "estado_ticket": 1,
    "mapa_usuario_esquema": 12,
    "version_esquema": 1,
    "registro_motivo_constancia": 0,
}

#: Tablas de negocio que `control` debe dejar vacias (su lugar es cada tenant) y
#: los dos historiales de la 014, que no se siembran con transiciones ficticias.
CONTROL_VACIAS = (
    "sede",
    "departamento",
    "usuario",
    "departamento_encargado",
    "categoria",
    "producto",
    "inventario",
    "stock_sede",
    "movimiento_inventario",
    "prioridad",
    "ticket",
    "detalle_ticket",
    "historial_transicion_ticket",
    "historial_transicion_producto",
    "historial_transicion_categoria",
)

#: Catalogo sembrado por tenant (Feature 014): la semilla solo puebla INST-001 e
#: INST-002 (productos 1..10 y 11..14; categorias 1..6 y 7..10). Los otros dos
#: tenants nacen legitimamente sin catalogo. Toda fila sembrada es activa.
CATALOGO_POR_TENANT = {
    "INST-001": {"categoria": 6, "producto": 10},
    "INST-002": {"categoria": 4, "producto": 4},
    "INST-003": {"categoria": 0, "producto": 0},
    "INST-004": {"categoria": 0, "producto": 0},
}

#: Totales de la semilla repartidos entre los cuatro tenants.
TOTALES_TENANT = {
    "sede": 11,
    "departamento": 10,
    "usuario": 12,
    "departamento_encargado": 5,
    "categoria": 10,
    "producto": 14,
    "inventario": 14,
    "stock_sede": 14,
    "movimiento_inventario": 14,
    "ticket": 10,
    "detalle_ticket": 10,
    "historial_transicion_ticket": 0,
    # Feature 014: la semilla no inventa transiciones de catalogo.
    "historial_transicion_producto": 0,
    "historial_transicion_categoria": 0,
}


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
    nombre = f"compustock_limpia_{uuid4().hex[:12]}"
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


def _instalar(conexion) -> None:
    """Corre la instalacion limpia completa, en el orden del volumen."""
    _ejecutar_script(conexion, ESQUEMA_SQL)
    _ejecutar_script(conexion, SEMILLA_SQL)


def _tablas_del_esquema(conexion, esquema: str) -> set[str]:
    filas = _ejecutar(
        conexion,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (esquema,),
    )
    return {fila[0] for fila in filas}


def _conteo_tabla(conexion, esquema: str, tabla: str) -> int:
    return _un_escalar(conexion, f'SELECT count(*) FROM "{esquema}"."{tabla}"')


def _esquema_de_institucion(institucion_id: str) -> str:
    from app.services.tenant_service import nombre_esquema_para_institucion

    return nombre_esquema_para_institucion(institucion_id)


def _instituciones(conexion) -> list[str]:
    return [
        fila[0]
        for fila in _ejecutar(
            conexion, "SELECT institucion_id FROM control.institucion ORDER BY institucion_id"
        )
    ]


def _version_de(conexion, esquema: str) -> str:
    return _un_escalar(conexion, f'SELECT version FROM "{esquema}".version_esquema')


# ---------------------------------------------------------------------------
# Estructura: control + un tenant por institucion
# ---------------------------------------------------------------------------


def test_instalacion_limpia_crea_control_y_tenants_versionados():
    with _base_temporal() as conexion:
        _instalar(conexion)

        assert len(TABLAS_CONTROL) == 22, len(TABLAS_CONTROL)
        assert len(TABLAS_TENANT) == 19, len(TABLAS_TENANT)
        assert _tablas_del_esquema(conexion, "control") == TABLAS_CONTROL
        instituciones = _instituciones(conexion)
        assert instituciones == list(SEDES_ESPERADAS)

        for institucion_id in instituciones:
            esquema = _esquema_de_institucion(institucion_id)
            assert _tablas_del_esquema(conexion, esquema) == TABLAS_TENANT, institucion_id
            assert _version_de(conexion, esquema) == VERSION_OBJETIVO_014, institucion_id

        assert _version_de(conexion, "control") == VERSION_OBJETIVO_014
        assert _conteo_tabla(conexion, "control", "version_esquema") == 1


def test_el_token_de_codigo_apunta_a_la_version_014_1():
    """AC-14: el objetivo del despliegue es `014.1` (lo sube T5 con el DDL de T4)."""
    assert VERSION_ESQUEMA_OBJETIVO == VERSION_OBJETIVO_014, VERSION_ESQUEMA_OBJETIVO


def test_estructura_de_invitacion_y_motivos_vive_solo_en_control():
    """Feature 017/AC-18: columnas y auxiliar solo en `control`, fuera de tenants.

    Verifica el catalogo real de PostgreSQL: las cuatro columnas de invitacion
    y la tabla `registro_motivo_constancia` con su clave idempotente unica, su
    `CHECK` de estado y su `FK` local a `institucion`. Cada tenant conserva sus 19
    tablas de negocio y **no** recibe ninguna de las estructuras auxiliares.
    """
    with _base_temporal() as conexion:
        _instalar(conexion)

        columnas = {
            fila[0]
            for fila in _ejecutar(
                conexion,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'control' AND table_name = 'mapa_usuario_esquema'",
            )
        }
        assert {
            "estado_invitacion",
            "invitacion_id",
            "invitacion_expira_en",
            "invitacion_aceptada_en",
        } <= columnas, columnas

        # La semilla solo vincula identidades Clerk existentes: nacen aceptadas.
        assert _ejecutar(
            conexion,
            "SELECT DISTINCT estado_invitacion FROM control.mapa_usuario_esquema",
        ) == [("aceptada",)]

        # Un estado fuera del catalogo cerrado es rechazado por el CHECK.
        with pytest.raises(psycopg2.Error):
            _ejecutar(
                conexion,
                "UPDATE control.mapa_usuario_esquema "
                "SET estado_invitacion = 'inventado' "
                "WHERE correo = (SELECT min(correo) FROM control.mapa_usuario_esquema)",
            )
        conexion.rollback()

        columnas_registro = {
            fila[0]
            for fila in _ejecutar(
                conexion,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'control' AND table_name = 'registro_motivo_constancia'",
            )
        }
        assert {
            "registro_id",
            "tipo_registro",
            "actor_correo",
            "usuario_objetivo_id",
            "correo_objetivo",
            "institucion_id",
            "accion",
            "codigo_motivo",
            "texto_motivo",
            "fecha_registro",
            "clave_idempotente",
            "invitacion_id",
            "resultado_revocacion",
        } <= columnas_registro, columnas_registro
        assert not any(
            "url" in nombre or "enlace" in nombre or "link" in nombre
            for nombre in columnas_registro
        ), columnas_registro

        # Clave idempotente unica a nivel de base.
        _ejecutar(
            conexion,
            "INSERT INTO control.registro_motivo_constancia "
            "(tipo_registro, actor_correo, institucion_id, accion, clave_idempotente) "
            "VALUES ('justificacion', 'admin@compustock.cl', 'INST-001', "
            "'edicion_usuario', 'idem-017-gated')",
        )
        with pytest.raises(psycopg2.Error):
            _ejecutar(
                conexion,
                "INSERT INTO control.registro_motivo_constancia "
                "(tipo_registro, actor_correo, institucion_id, accion, clave_idempotente) "
                "VALUES ('justificacion', 'admin@compustock.cl', 'INST-001', "
                "'edicion_usuario', 'idem-017-gated')",
            )
        conexion.rollback()

        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            tablas = _tablas_del_esquema(conexion, esquema)
            assert tablas == TABLAS_TENANT, institucion_id
            columnas_tenant = {
                fila[0]
                for fila in _ejecutar(
                    conexion,
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s",
                    (esquema,),
                )
            }
            assert not (
                {
                    "estado_invitacion",
                    "invitacion_id",
                    "invitacion_expira_en",
                    "invitacion_aceptada_en",
                }
                & columnas_tenant
            ), (institucion_id, columnas_tenant)


# ---------------------------------------------------------------------------
# Reparto: sedes, ambito departamental y cuadre de stock
# ---------------------------------------------------------------------------


def test_instalacion_limpia_reparte_sedes_y_cuadra_stock():
    with _base_temporal() as conexion:
        _instalar(conexion)

        for institucion_id, sedes_esperadas in SEDES_ESPERADAS.items():
            esquema = _esquema_de_institucion(institucion_id)

            assert _conteo_tabla(conexion, esquema, "sede") == sedes_esperadas, institucion_id
            assert (
                _un_escalar(
                    conexion,
                    f'SELECT count(*) FROM "{esquema}".departamento WHERE sede_id IS NULL',
                )
                == 0
            ), f"{institucion_id} tiene departamentos sin sede"

            # Todo ticket historico quedo con su sede asignada.
            assert (
                _un_escalar(
                    conexion,
                    f'SELECT count(*) FROM "{esquema}".ticket WHERE sede_id IS NULL',
                )
                == 0
            ), f"{institucion_id} tiene tickets sin sede"

            # Cuadre por producto: inventario departamental == stock por sede.
            descuadres = _un_escalar(
                conexion,
                f"""
                SELECT count(*) FROM (
                    SELECT i.producto_id,
                           sum(i.stock_actual) AS departamental,
                           coalesce((
                               SELECT sum(s.stock_actual)
                               FROM "{esquema}".stock_sede s
                               WHERE s.producto_id = i.producto_id
                           ), 0) AS por_sede
                    FROM "{esquema}".inventario i
                    GROUP BY i.producto_id
                ) AS totales
                WHERE departamental <> por_sede
                """,
            )
            assert descuadres == 0, f"{institucion_id} no cuadra por producto"


# ---------------------------------------------------------------------------
# Contexto global: `control` sin negocio, mapa completo y totales repartidos
# ---------------------------------------------------------------------------


def test_control_queda_como_contexto_global_y_los_totales_viven_en_los_tenants():
    with _base_temporal() as conexion:
        _instalar(conexion)

        for tabla, esperado in CONTROL_ESPERADO.items():
            assert _conteo_tabla(conexion, "control", tabla) == esperado, tabla
        for tabla in CONTROL_VACIAS:
            assert _conteo_tabla(conexion, "control", tabla) == 0, tabla
        assert _un_escalar(
            conexion, "SELECT count(*) FROM control.estado_ticket WHERE nombre = 'Anulado'"
        ) == 1

        esquemas = [_esquema_de_institucion(inst) for inst in _instituciones(conexion)]
        for tabla, total in TOTALES_TENANT.items():
            suma = sum(_conteo_tabla(conexion, esquema, tabla) for esquema in esquemas)
            assert suma == total, (tabla, suma)

        # Rol y estado se replican en cada tenant (el Superadmin vive solo en control).
        for esquema in esquemas:
            assert _conteo_tabla(conexion, esquema, "rol") == 3, esquema
            assert _conteo_tabla(conexion, esquema, "estado_ticket") == 5, esquema
            assert _conteo_tabla(conexion, esquema, "prioridad") == 3, esquema


# ---------------------------------------------------------------------------
# Guardia fail-closed de la semilla
# ---------------------------------------------------------------------------


def test_guardia_fail_closed_aborta_la_segunda_semilla():
    """La semilla no es reejecutable: aborta antes de tocar nada (reset = `down -v`)."""
    with _base_temporal() as conexion:
        _instalar(conexion)

        with pytest.raises(psycopg2.Error) as excinfo:
            _ejecutar_script(conexion, SEMILLA_SQL)
        conexion.rollback()
        assert "abortada" in str(excinfo.value).lower(), excinfo.value


# ---------------------------------------------------------------------------
# Feature 014: catalogo sembrado activo en cada tenant (AC-13)
# ---------------------------------------------------------------------------


def test_instalacion_limpia_siembra_el_catalogo_activo_por_tenant():
    """AC-13/AC-14: filas activas segun el reparto aprobado, ninguna inactiva.

    La semilla siembra categorias y productos con `activo = TRUE` explicito y no
    inventa transiciones: los dos historiales quedan vacios en todos los esquemas
    (se comprueba en este mismo archivo via `TOTALES_TENANT`/`CONTROL_VACIAS`).
    """
    with _base_temporal() as conexion:
        _instalar(conexion)

        for institucion_id, esperado in CATALOGO_POR_TENANT.items():
            esquema = _esquema_de_institucion(institucion_id)
            for tabla, filas in esperado.items():
                assert _conteo_tabla(conexion, esquema, tabla) == filas, (
                    institucion_id,
                    tabla,
                )
                assert (
                    _un_escalar(
                        conexion,
                        f'SELECT count(*) FROM "{esquema}"."{tabla}" '
                        "WHERE activo IS NOT TRUE",
                    )
                    == 0
                ), (institucion_id, tabla)


# ---------------------------------------------------------------------------
# Feature 014: version unica, compatible con el objetivo y exigida por routing
# ---------------------------------------------------------------------------

#: Version menor instalada en un tenant: el routing la deniega en cerrado.
VERSION_MENOR_INCOMPATIBLE = "013.1"


def _motor_sqlalchemy(conexion):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    # psycopg2 2.9+ no expone `password` en `get_dsn_parameters()`; se reutiliza
    # la URL del harness cambiando solo el nombre de la base.
    nombre_base = conexion.get_dsn_parameters()["dbname"]
    url = _url_con_base(_sin_driver(_POSTGRES_TEST_URL or ""), nombre_base)
    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, poolclass=NullPool, future=True)


@contextmanager
def _sesion_control(conexion):
    """Sesion ligada al esquema `control` de la base temporal (patron `get_db`)."""
    from sqlalchemy.orm import Session

    motor = _motor_sqlalchemy(conexion)
    try:
        con_control = motor.execution_options(schema_translate_map={None: "control"})
        sesion = Session(bind=con_control)
        try:
            yield sesion
        finally:
            sesion.close()
    finally:
        motor.dispose()


def test_instalacion_limpia_enruta_en_014_1_y_deniega_una_version_menor():
    """AC-14: la version instalada es la unica, compatible y exigida por routing.

    Con la instalacion limpia (`01_` + `02_`) el token del codigo y el de los
    esquemas coinciden (`014.1`) y la identidad mapeada se enruta; bajada la
    version del tenant a una menor, el routing la deniega en cerrado (mismo
    patron que la regresion de cadena de la Feature 013).
    """
    from app.db.database import crear_sesion_esquema
    from app.services import tenant_service

    with _base_temporal() as conexion:
        _instalar(conexion)

        # Una sola version, la del codigo, en control y en cada tenant.
        assert VERSION_ESQUEMA_OBJETIVO == VERSION_OBJETIVO_014
        assert _version_de(conexion, "control") == VERSION_ESQUEMA_OBJETIVO
        for institucion_id in _instituciones(conexion):
            esquema = _esquema_de_institucion(institucion_id)
            assert _version_de(conexion, esquema) == VERSION_ESQUEMA_OBJETIVO, esquema

        filas = _ejecutar(
            conexion,
            "SELECT correo, nombre_esquema FROM control.mapa_usuario_esquema "
            "ORDER BY correo LIMIT 1",
        )
        assert filas, "la semilla debe mapear al menos un correo a su tenant"
        correo, esquema = filas[0]

        # Mismo cableado que `get_db` en produccion (`dependencies.py`).
        motor = _motor_sqlalchemy(conexion)
        abrir_sesion_tenant = lambda esq: crear_sesion_esquema(esq, motor=motor)  # noqa: E731
        try:
            with _sesion_control(conexion) as sesion:
                contexto = tenant_service.resolver_contexto_solicitud(
                    sesion, correo, abrir_sesion_tenant=abrir_sesion_tenant
                )
            assert contexto.nombre_esquema == esquema
            assert contexto.version == VERSION_ESQUEMA_OBJETIVO

            # Tenant con una version menor: no se enruta.
            _ejecutar(
                conexion,
                f'UPDATE "{esquema}".version_esquema SET version = %s',
                (VERSION_MENOR_INCOMPATIBLE,),
            )
            with _sesion_control(conexion) as sesion:
                with pytest.raises(tenant_service.ErrorTenant):
                    tenant_service.resolver_contexto_solicitud(
                        sesion, correo, abrir_sesion_tenant=abrir_sesion_tenant
                    )

            # Restaurada la version objetivo, vuelve a enrutar.
            _ejecutar(
                conexion,
                f'UPDATE "{esquema}".version_esquema SET version = %s',
                (VERSION_ESQUEMA_OBJETIVO,),
            )
            with _sesion_control(conexion) as sesion:
                contexto = tenant_service.resolver_contexto_solicitud(
                    sesion, correo, abrir_sesion_tenant=abrir_sesion_tenant
                )
            assert contexto.version == VERSION_ESQUEMA_OBJETIVO
        finally:
            motor.dispose()
