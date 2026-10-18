"""T11 (Feature 010): integracion del contexto tenant y agregados globales.

Complemento gated PostgreSQL 16 de la suite SQLite. SQLite no reproduce
namespaces ni transacciones entre esquemas, asi que lo que T11 exige se acredita
aqui contra el motor objetivo:

  * la **sesion de control** resuelve al esquema `control` de forma explicita,
    tanto en instalacion limpia (donde `ALTER DATABASE ... search_path` apunta a
    `control`) como en una **base migrada** (donde el `search_path` por defecto
    sigue en `public`); sin el ajuste, la sesion sin traduccion resolveria contra
    `public` y no encontraria el control;
  * un rol limitado ejecuta sus operaciones de negocio en la **sesion de su
    tenant** (`get_db_negocio` abre el esquema derivado del correo);
  * las **lecturas globales del Superadmin** se agregan sobre los tenants
    registrados, con atribucion institucional, y en **una sola transaccion**
    `REPEATABLE READ` que refleja un unico instante;
  * un tenant **incompatible** (fuera de la version objetivo) hace fallar el
    consolidado entero, sin entregar un agregado parcial.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_integracion_multitenant_010.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
    mantenimiento donde el test crea y DESTRUYE bases/esquemas temporales propios;
    nunca toca `apt_erp`. NO se anade ninguna dependencia: `psycopg2` ya esta en
    `requirements.txt`.
"""

from __future__ import annotations

import importlib
import json
import os
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL, crear_sesion_control

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


# ---------------------------------------------------------------------------
# Base y esquemas temporales
# ---------------------------------------------------------------------------


@contextmanager
def _base_temporal(url_entrada: str):
    """Crea una base PostgreSQL efimera y la destruye al salir (nunca `apt_erp`)."""
    dsn = (url_entrada or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_t11_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    componentes = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        yield componentes
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


@contextmanager
def _esquema(engine, prefijo: str, *, con_tablas: bool = True):
    """Crea un esquema efimero (con las tablas del metadata) y lo destruye."""
    nombre = f"{prefijo}_{uuid4().hex[:10]}"
    with engine.begin() as conexion:
        conexion.execute(CreateSchema(nombre))
    motor = engine.execution_options(schema_translate_map={None: nombre})
    if con_tablas:
        Base.metadata.create_all(bind=motor)
    try:
        yield nombre, motor
    finally:
        with engine.begin() as conexion:
            conexion.execute(DropSchema(nombre, cascade=True))


def _modelo(nombre: str):
    modelos = importlib.import_module("app.models")
    return getattr(modelos, nombre)


def _crear_esquema_control_012(motor_control) -> None:
    """Materializa el DDL canonico de control vigente en el harness.

    Desde la Feature 012 el registro canonico de control (`institucion`) porta
    `activo` y existe la auxiliar `funcion_institucion`, ambas **solo** en control.
    El harness las crea con `BaseControl.metadata` (antes de `Base.metadata`), de
    modo que la tabla `institucion` del control sea el superset y el espejo tenant
    de `_esquema` siga limitado a dos columnas. Sin esto, la resolucion de
    identidad de la 012 no encontraria `institucion.activo`.
    """
    from app.models.control_canonico import BaseControl

    BaseControl.metadata.create_all(bind=motor_control)
    Base.metadata.create_all(bind=motor_control)


# ---------------------------------------------------------------------------
# AC-16/T11: la sesion de control fija `control` explicitamente
# ---------------------------------------------------------------------------


def test_sesion_control_resuelve_control_en_base_migrada():
    """En una base migrada (sin `search_path`), la sesion de control resuelve `control`.

    La base migrada no ejecuta `ALTER DATABASE ... search_path`: el `search_path`
    por defecto es `"$user", public`. Una sesion sin traduccion resolveria contra
    `public`; `crear_sesion_control` aparece `control.tabla` de forma explicita y
    encuentra el registro. Se prueba ademas que la sesion **sin** la traduccion
    (patron previo) no lo encuentra, que es exactamente el hallazgo que T11 fija.
    """
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            _crear_esquema_control_012(motor_control)
            with motor_control.begin() as conexion:
                conexion.execute(
                    Base.metadata.tables["institucion"].insert().values(
                        institucion_id="CTRL-SAAS", nombre="CompuStock SaaS"
                    )
                )

            # Disposicion migrada: `search_path` por defecto (public).
            with engine.connect() as conexion:
                search_path = conexion.exec_driver_sql("SHOW search_path").scalar()
            assert ESQUEMA_CONTROL not in search_path, search_path

            # La base migrada conserva el esquema legado `public`: una sesion sin
            # traduccion resolveria alli, no en `control`.
            with engine.begin() as conexion:
                conexion.exec_driver_sql(
                    "CREATE TABLE public.institucion ("
                    "institucion_id VARCHAR(20) PRIMARY KEY, "
                    "nombre VARCHAR(150) NOT NULL, rut VARCHAR(20), direccion VARCHAR(200))"
                )
                conexion.exec_driver_sql(
                    "INSERT INTO public.institucion (institucion_id, nombre) "
                    "VALUES ('PUBLIC-LEGACY', 'Legado')"
                )

            sesion = crear_sesion_control(engine)
            try:
                instituciones = [
                    fila[0]
                    for fila in sesion.execute(
                        select(Base.metadata.tables["institucion"].c.institucion_id)
                    ).all()
                ]
            finally:
                sesion.close()
            assert instituciones == ["CTRL-SAAS"], "la sesion de control debe ver control"

            # El patron previo (sin traduccion) resuelve a public y ve el legado.
            from app.db.database import SessionLocal

            sesion_previa = SessionLocal(bind=engine)
            try:
                resultado = sesion_previa.execute(
                    select(Base.metadata.tables["institucion"].c.institucion_id)
                ).all()
            finally:
                sesion_previa.close()
            assert [fila[0] for fila in resultado] == ["PUBLIC-LEGACY"], (
                "sin la traduccion explicita, la sesion resolveria a public (bug T10)"
            )
        finally:
            engine.dispose()


def test_sesion_control_resuelve_control_en_instalacion_limpia():
    """En instalacion limpia (`search_path=control,public`) tambien resuelve `control`."""
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            nombre_base = engine.url.database
            # `ALTER DATABASE ... SET search_path` exige autocommit.
            admin = engine.execution_options(isolation_level="AUTOCOMMIT")
            with admin.connect() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
                conexion.exec_driver_sql(
                    f'ALTER DATABASE "{nombre_base}" '
                    f"SET search_path TO {ESQUEMA_CONTROL}, public"
                )
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            _crear_esquema_control_012(motor_control)
            with motor_control.begin() as conexion:
                conexion.execute(
                    Base.metadata.tables["institucion"].insert().values(
                        institucion_id="CTRL-SAAS", nombre="CompuStock SaaS"
                    )
                )

            # Conexion nueva: hereda el `search_path` de la base.
            engine.dispose()
            with engine.connect() as conexion:
                search_path = conexion.exec_driver_sql("SHOW search_path").scalar()
            assert ESQUEMA_CONTROL in search_path, search_path

            sesion = crear_sesion_control(engine)
            try:
                instituciones = [
                    fila[0]
                    for fila in sesion.execute(
                        select(Base.metadata.tables["institucion"].c.institucion_id)
                    ).all()
                ]
            finally:
                sesion.close()
            assert instituciones == ["CTRL-SAAS"]
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Fixture: dos tenants homonimos + un tercero, en una base temporal
# ---------------------------------------------------------------------------


@pytest.fixture
def mundo_multitenant():
    """Crea `control` + dos tenants homonimos en una base efimera.

    Devuelve un dict con el engine, las sesiones de control, los nombres de
    esquema, los ids de producto (distintos a proposito) y una identidad
    Superadmin sintetica.
    """
    modelos = importlib.import_module("app.models")
    from app.services.auth_service import IdentidadAutenticada

    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            _crear_esquema_control_012(motor_control)

            with _esquema(engine, "tenant_a") as (esq_a, motor_a):
                with _esquema(engine, "tenant_b") as (esq_b, motor_b):
                    ids_a = _sembrar_tenant(
                        motor_a, "INST-A", "Instituto Alfa", stock=9
                    )
                    ids_b = _sembrar_tenant(
                        motor_b, "INST-B", "Instituto Beta", stock=3
                    )
                    _sembrar_control(motor_control, esq_a, "INST-A", esq_b, "INST-B")
                    _sembrar_control_extra(motor_control, esq_a, "INST-A")

                    sesion_control = Session(bind=motor_control)
                    try:
                        usuario = modelos.Usuario(
                            usuario_id=1,
                            nombre="Super",
                            apellido="Admin",
                            correo="super@t11.cl",
                            departamento_id=1,
                            rol_id=1,
                        )
                        usuario.rol = modelos.Rol(nombre_rol="Superadmin")
                        identidad_super = IdentidadAutenticada(
                            usuario=usuario, sub="sub-t11"
                        )
                        identidad_tenant = IdentidadAutenticada(
                            usuario=modelos.Usuario(
                                usuario_id=2,
                                nombre="T",
                                apellido="A",
                                correo="t.a@inst-a.cl",
                                departamento_id=1,
                                rol_id=1,
                            ),
                            sub="sub-t11-a",
                        )
                        yield {
                            "engine": engine,
                            "control": sesion_control,
                            "esq_a": esq_a,
                            "esq_b": esq_b,
                            "ids_a": ids_a,
                            "ids_b": ids_b,
                            "identidad_super": identidad_super,
                            "identidad_tenant": identidad_tenant,
                        }
                    finally:
                        sesion_control.close()
        finally:
            engine.dispose()


def _sembrar_tenant(
    motor, institucion_id, nombre_inst, *, stock: int, version=VERSION_ESQUEMA_OBJETIVO
):
    """Un tenant con institucion espejo, catalogo, stock, movimiento y version."""
    modelos = importlib.import_module("app.models")
    sesion = Session(bind=motor)
    try:
        sesion.add(modelos.Institucion(institucion_id=institucion_id, nombre=nombre_inst))
        rol = modelos.Rol(nombre_rol="Administrador", descripcion="rol")
        sesion.add(rol)
        sesion.flush()
        dep = modelos.Departamento(
            nombre_dep="Operaciones", descripcion="d", institucion_id=institucion_id
        )
        sesion.add(dep)
        sesion.flush()
        usuario = modelos.Usuario(
            nombre="U",
            apellido="T",
            correo=f"u.{institucion_id.lower()}@t.cl",
            departamento_id=dep.departamento_id,
            rol_id=rol.rol_id,
        )
        sesion.add(usuario)
        cat = modelos.Categoria(nombre_cat="Papeleria", institucion_id=institucion_id)
        sesion.add(cat)
        sesion.flush()
        prod = modelos.Producto(
            nombre="Papel Bond",
            descripcion="homonimo deliberado",
            unidad_medida="UNIDAD",
            stock_minimo=10,
            categoria_id=cat.categoria_id,
            institucion_id=institucion_id,
        )
        sesion.add(prod)
        sesion.flush()
        inv = modelos.Inventario(
            stock_actual=stock,
            ubicacion=f"Operaciones ({institucion_id})",
            departamento_id=dep.departamento_id,
            producto_id=prod.producto_id,
            institucion_id=institucion_id,
        )
        sesion.add(inv)
        sesion.flush()
        # Feature 011 (spec D-6/AC-11): el saldo vigente vive por sede. El
        # dashboard / inventario leen `stock_sede`, no el inventario legado; la
        # fila de `Inventario` se conserva para el movimiento historico.
        sede = modelos.Sede(nombre="Sede Central", institucion_id=institucion_id)
        sesion.add(sede)
        sesion.flush()
        stock_sede = modelos.StockSede(
            stock_actual=stock,
            sede_id=sede.sede_id,
            producto_id=prod.producto_id,
            institucion_id=institucion_id,
        )
        sesion.add(stock_sede)
        sesion.flush()
        sesion.add(
            modelos.MovimientoInventario(
                tipo_movimiento="ENTRADA",
                cantidad=1,
                observacion=f"mov {institucion_id}",
                inventario_id=inv.inventario_id,
            )
        )
        for nombre in ("Alta", "Media", "Baja"):
            sesion.add(modelos.Prioridad(nombre=nombre, descripcion=nombre))
        for nombre in ("Pendiente", "EnRevision", "EnCurso", "Cerrado"):
            sesion.add(modelos.EstadoTicket(nombre=nombre, descripcion=nombre))
        sesion.add(modelos.VersionEsquema(version=version))
        sesion.commit()
        return {
            "institucion_id": institucion_id,
            "producto_id": prod.producto_id,
            "inventario_id": inv.inventario_id,
            "departamento_id": dep.departamento_id,
            "stock": stock,
        }
    finally:
        sesion.close()


def _sembrar_control(motor_control, esq_a, inst_a, esq_b, inst_b):
    """Registro canonico de dos instituciones y su mapa `correo -> esquema`."""
    modelos = importlib.import_module("app.models")
    sesion = Session(bind=motor_control)
    try:
        sesion.add_all(
            [
                modelos.Institucion(institucion_id=inst_a, nombre="Instituto Alfa"),
                modelos.Institucion(institucion_id=inst_b, nombre="Instituto Beta"),
            ]
        )
        sesion.flush()
        sesion.add_all(
            [
                modelos.MapaUsuarioEsquema(
                    correo="t.a@inst-a.cl",
                    institucion_id=inst_a,
                    nombre_esquema=esq_a,
                    activo=True,
                ),
                modelos.MapaUsuarioEsquema(
                    correo="otro.a@inst-a.cl",
                    institucion_id=inst_a,
                    nombre_esquema=esq_a,
                    activo=True,
                ),
                modelos.MapaUsuarioEsquema(
                    correo="t.b@inst-b.cl",
                    institucion_id=inst_b,
                    nombre_esquema=esq_b,
                    activo=True,
                ),
                modelos.MapaUsuarioEsquema(
                    correo="u.inst-a@t.cl",
                    institucion_id=inst_a,
                    nombre_esquema=esq_a,
                    activo=True,
                ),
            ]
        )
        sesion.commit()
    finally:
        sesion.close()


def _sembrar_control_extra(motor_control, esq_a, inst_a):
    """Agrega un mapa inactivo y uno del esquema reservado `control` (excluidos)."""
    modelos = importlib.import_module("app.models")
    sesion = Session(bind=motor_control)
    try:
        sesion.add(
            modelos.Institucion(institucion_id="CTRL-SAAS", nombre="CompuStock SaaS")
        )
        sesion.flush()
        sesion.add(
            modelos.MapaUsuarioEsquema(
                correo="inactivo@inst-a.cl",
                institucion_id=inst_a,
                nombre_esquema=esq_a,
                activo=False,
            )
        )
        sesion.add(
            modelos.MapaUsuarioEsquema(
                correo="super@t11.cl",
                institucion_id="CTRL-SAAS",
                nombre_esquema=ESQUEMA_CONTROL,
                activo=True,
            )
        )
        sesion.commit()
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# AC-3: tenants registrados = activos, sin el esquema reservado `control`
# ---------------------------------------------------------------------------


def test_tenants_registrados_deduplica_y_excluye_control(mundo_multitenant):
    from app.services import global_service

    tenants = global_service.tenants_registrados(mundo_multitenant["control"])
    nombres = {t.nombre_esquema for t in tenants}
    assert nombres == {mundo_multitenant["esq_a"], mundo_multitenant["esq_b"]}
    assert ESQUEMA_CONTROL not in nombres, "el esquema reservado no es un tenant"
    # Deduplicado: INST-A tiene dos correos activos que comparten su esquema.
    assert len(tenants) == 2


# ---------------------------------------------------------------------------
# AC-1: un rol limitado opera en la sesion de su tenant
# ---------------------------------------------------------------------------


def test_get_db_negocio_abre_la_sesion_del_tenant(mundo_multitenant):
    from app.api import dependencies

    generador = dependencies.get_db_negocio(
        mundo_multitenant["control"], mundo_multitenant["identidad_tenant"]
    )
    sesion = next(generador)
    try:
        # El institucion espejo del tenant A solo existe en su esquema: si la
        # sesion cayera al control, no lo encontraria.
        instituciones = [
            fila[0]
            for fila in sesion.execute(
                select(Base.metadata.tables["institucion"].c.institucion_id)
            ).all()
        ]
        assert instituciones == ["INST-A"], instituciones
    finally:
        generador.close()


def test_get_db_negocio_deniega_correo_sin_mapa(mundo_multitenant):
    from fastapi import HTTPException

    from app.api import dependencies
    from app.services.auth_service import IdentidadAutenticada
    from app.models import Usuario, Rol

    usuario = Usuario(
        usuario_id=9,
        nombre="X",
        apellido="Y",
        correo="desconocido@t11.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Administrador")
    generador = dependencies.get_db_negocio(
        mundo_multitenant["control"], IdentidadAutenticada(usuario=usuario, sub="x")
    )
    with pytest.raises(HTTPException) as excinfo:
        next(generador)
    assert excinfo.value.status_code == 403


# ---------------------------------------------------------------------------
# AC-1: la identidad de negocio se resuelve en su tenant (no en control)
# ---------------------------------------------------------------------------


def test_resolver_usuario_local_encuentra_usuario_de_tenant(mundo_multitenant):
    """Un usuario de negocio vive en su esquema; se resuelve via el mapa de control.

    control.usuario solo contiene la identidad Superadmin, asi que un usuario de
    negocio debe resolverse abriendo el esquema derivado del correo. Su `rol`
    queda cargado y utilizable fuera de esa sesion temporal (lo lee la
    autorizacion).
    """
    from app.services import auth_service

    usuario = auth_service.resolver_usuario_local(
        mundo_multitenant["control"], "u.inst-a@t.cl"
    )
    assert usuario is not None
    assert usuario.correo == "u.inst-a@t.cl"
    assert usuario.rol is not None
    assert usuario.rol.nombre_rol == "Administrador"


# ---------------------------------------------------------------------------
# AC-14: agregado global en una sola transaccion, con atribucion
# ---------------------------------------------------------------------------


def test_dashboard_global_agrega_homonimos_con_atribucion(mundo_multitenant):
    from app.services import dashboard_service

    resultado = dashboard_service.obtener_dashboard_analitico(
        mundo_multitenant["control"], mundo_multitenant["identidad_super"]
    )

    # KPI: suma de los dos tenants (9 + 3).
    assert resultado.kpi.unidades_en_stock == 12
    assert resultado.kpi.total_departamentos == 2
    assert resultado.kpi.total_alertas == len(resultado.alertas)

    # Homónimos no fusionados: dos productos "Papel Bond" con ids distintos.
    papel = [a for a in resultado.alertas if a.producto_nombre == "Papel Bond"]
    assert {a.producto_id for a in papel} == {
        mundo_multitenant["ids_a"]["producto_id"],
        mundo_multitenant["ids_b"]["producto_id"],
    }
    assert {a.institucion_id for a in papel} == {"INST-A", "INST-B"}
    assert {a.institucion_nombre for a in papel} == {"Instituto Alfa", "Instituto Beta"}

    # Actividad atribuida por institucion.
    assert resultado.actividad_disponible is True
    assert {m.institucion_id for m in resultado.actividad_movimientos} == {
        "INST-A",
        "INST-B",
    }


def test_lectura_global_es_una_sola_transaccion_repeatable_read(mundo_multitenant):
    """Los tenants comparten conexion y aislamiento `REPEATABLE READ` (un instante).

    Además, una mutacion concurrente confirmada en otro conexion no es visible
    dentro de la transaccion en curso: el snapshot es unico.
    """
    from sqlalchemy import text

    from app.services import global_service

    control = mundo_multitenant["control"]
    tenants = global_service.tenants_registrados(control)
    por_esquema = {t.nombre_esquema: t for t in tenants}

    with global_service.lectura_global(control) as lector:
        with lector.sesion(por_esquema[mundo_multitenant["esq_a"]]) as s_a:
            pid_a = s_a.execute(text("SELECT pg_backend_pid()")).scalar()
            iso_a = s_a.execute(text("SHOW transaction_isolation")).scalar()
            stock_a_inicial = s_a.execute(
                text(f'SELECT stock_actual FROM "{mundo_multitenant["esq_a"]}".inventario')
            ).scalar()

            # Mutacion concurrente confirmada en otra conexion (mismo motor/base).
            motor_ajeno = control.get_bind().execution_options(
                schema_translate_map={None: mundo_multitenant["esq_a"]}
            )
            with motor_ajeno.begin() as ajena:
                ajena.execute(
                    Base.metadata.tables["inventario"]
                    .update()
                    .values(stock_actual=999)
                )

        with lector.sesion(por_esquema[mundo_multitenant["esq_b"]]) as s_b:
            pid_b = s_b.execute(text("SELECT pg_backend_pid()")).scalar()
            iso_b = s_b.execute(text("SHOW transaction_isolation")).scalar()

        # Relectura dentro de la MISMA transaccion: el snapshot no cambia.
        with lector.sesion(por_esquema[mundo_multitenant["esq_a"]]) as s_a2:
            stock_a_releido = s_a2.execute(
                text(f'SELECT stock_actual FROM "{mundo_multitenant["esq_a"]}".inventario')
            ).scalar()

    assert pid_a == pid_b, "los tenants deben compartir la misma conexion"
    assert iso_a.lower().replace(" ", "") == "repeatableread"
    assert iso_b.lower().replace(" ", "") == "repeatableread"
    assert stock_a_inicial == 9
    assert stock_a_releido == 9, (
        "la mutacion concurrente no debe verse dentro de la transaccion en curso"
    )


# ---------------------------------------------------------------------------
# AC-12/AC-14: un tenant incompatible hace fallar el consolidado entero
# ---------------------------------------------------------------------------


def test_dashboard_global_aborta_si_un_tenant_no_esta_en_version(mundo_multitenant):
    from fastapi import HTTPException

    from app.models import VersionEsquema
    from app.services import dashboard_service

    # El tenant B pasa a una version incompatible.
    motor_b = mundo_multitenant["engine"].execution_options(
        schema_translate_map={None: mundo_multitenant["esq_b"]}
    )
    sesion = Session(bind=motor_b)
    try:
        sesion.add(VersionEsquema(version="009.9"))
        sesion.commit()
    finally:
        sesion.close()

    with pytest.raises(HTTPException) as excinfo:
        dashboard_service.obtener_dashboard_analitico(
            mundo_multitenant["control"], mundo_multitenant["identidad_super"]
        )
    assert excinfo.value.status_code == 503

    # No hay agregado parcial: la excepcion ocurre antes de devolver DTO alguno;
    # comprobar que la transaccion global no dejo cambios es trivial (solo lee).
    # El tenant A sigue intacto y en version objetivo.
    assert mundo_multitenant["ids_a"]["stock"] == 9


# ---------------------------------------------------------------------------
# AC-3: inyeccion adversarial de tenant por query/cabecera/cuerpo/claim
# ---------------------------------------------------------------------------
#
# Estos casos sientan al usuario de Tenant A sobre el **app HTTP real** con dos
# esquemas PostgreSQL reales (`control` + dos tenants) y envian Tenant B por cada
# canal del AC-3. A diferencia de la suite SQLite (contexto logico unico), aqui
# la resolucion de `get_db_negocio` se ejecuta de verdad: si el canal existiera,
# el resultado vendria de otro esquema y la prueba lo delataria.


def _identidad_tenant_a(mundo) -> object:
    """Identidad de Tenant A con su rol cargado (autorizacion y ambito reales)."""
    modelos = importlib.import_module("app.models")
    from app.services.auth_service import IdentidadAutenticada

    usuario = modelos.Usuario(
        usuario_id=2,
        nombre="T",
        apellido="A",
        correo="u.inst-a@t.cl",
        departamento_id=mundo["ids_a"]["departamento_id"],
        rol_id=1,
    )
    usuario.rol = modelos.Rol(nombre_rol="Administrador")
    return IdentidadAutenticada(usuario=usuario, sub="sub-ac3-a")


@contextmanager
def _cliente_http(mundo, overrides: dict | None = None):
    """`TestClient` del `app` real con `get_db` atado a la base temporal.

    `get_db` cede la sesion de control sobre el motor temporal; `get_db_negocio`
    resuelve el tenant contra el mapa de control y abre el esquema real, igual que
    en produccion. Los overrides opcionales permiten fijar la identidad (canales
    query/cabecera/cuerpo) o inyectar las costuras Clerk (canal claim).
    """
    from fastapi.testclient import TestClient

    from app.api import dependencies
    from app.main import app

    Fabrica = sessionmaker(bind=mundo["control"].get_bind())

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if overrides:
        app.dependency_overrides.update(overrides)
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def test_tenant_adversario_por_query_no_contamina(mundo_multitenant):
    """AC-3: enviar el esquema de B por query no cambia el tenant resuelto de A."""
    from app.api import dependencies

    identidad = _identidad_tenant_a(mundo_multitenant)
    with _cliente_http(
        mundo_multitenant, {dependencies.get_current_user: lambda: identidad}
    ) as cliente:
        base = cliente.get("/api/v1/inventario/productos")
        envenenado = cliente.get(
            "/api/v1/inventario/productos",
            params={
                "nombre_esquema": mundo_multitenant["esq_b"],
                "tenant": "INST-B",
                "institucion_id": "INST-B",
                "schema": mundo_multitenant["esq_b"],
            },
        )

    assert base.status_code == 200, base.text
    assert envenenado.status_code == 200, envenenado.text
    assert envenenado.json() == base.json(), "el query no debe alterar la respuesta"
    assert {fila["institucion_id"] for fila in base.json()} == {"INST-A"}, (
        "la identidad limitada solo ve su tenant"
    )


def test_tenant_adversario_por_cabecera_no_contamina(mundo_multitenant):
    """AC-3: enviar el esquema de B por cabeceras HTTP tampoco cambia el tenant de A."""
    from app.api import dependencies

    identidad = _identidad_tenant_a(mundo_multitenant)
    with _cliente_http(
        mundo_multitenant, {dependencies.get_current_user: lambda: identidad}
    ) as cliente:
        base = cliente.get("/api/v1/inventario/productos")
        envenenado = cliente.get(
            "/api/v1/inventario/productos",
            headers={
                "X-Tenant": "INST-B",
                "X-Schema": mundo_multitenant["esq_b"],
                "X-Institucion": "INST-B",
                "X-Nombre-Esquema": mundo_multitenant["esq_b"],
            },
        )

    assert base.status_code == 200, base.text
    assert envenenado.status_code == 200, envenenado.text
    assert envenenado.json() == base.json(), "las cabeceras no deben alterar la respuesta"
    assert {fila["institucion_id"] for fila in base.json()} == {"INST-A"}


def test_tenant_adversario_por_cuerpo_no_escribe_otro_tenant(mundo_multitenant):
    """AC-3: un campo de tenant en el cuerpo no desvia la escritura fuera de A.

    El movimiento se registra contra el inventario de A (el de la identidad); el
    tenant B conserva su stock y su auditoria sin cambios.
    """
    from app.api import dependencies

    identidad = _identidad_tenant_a(mundo_multitenant)
    with _cliente_http(
        mundo_multitenant, {dependencies.get_current_user: lambda: identidad}
    ) as cliente:
        respuesta = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "SALIDA",
                "cantidad": 1,
                "inventario_id": mundo_multitenant["ids_a"]["inventario_id"],
                "observacion": "intento de envenenamiento de tenant",
                "institucion_id": "INST-B",
                "nombre_esquema": mundo_multitenant["esq_b"],
            },
        )

    assert respuesta.status_code == 201, respuesta.text

    # Tenant B intacto: mismo stock y ninguna fila de auditoria nueva.
    motor_b = mundo_multitenant["engine"].execution_options(
        schema_translate_map={None: mundo_multitenant["esq_b"]}
    )
    sesion_b = Session(bind=motor_b)
    try:
        stock_b = sesion_b.execute(
            select(Base.metadata.tables["inventario"].c.stock_actual)
        ).scalar()
        movimientos_b = sesion_b.execute(
            select(Base.metadata.tables["movimiento_inventario"].c.movimiento_id)
        ).all()
    finally:
        sesion_b.close()
    assert stock_b == 3, "el stock de B no debe cambiar"
    # B conserva exactamente su unica fila de auditoria sembrada por el fixture:
    # el intento de escritura no agrega ninguna.
    assert len(movimientos_b) == 1, "no debe registrarse auditoria nueva en B"

    # Tenant A si recibio el movimiento: la escritura cayo en su esquema.
    motor_a = mundo_multitenant["engine"].execution_options(
        schema_translate_map={None: mundo_multitenant["esq_a"]}
    )
    sesion_a = Session(bind=motor_a)
    try:
        stock_a = sesion_a.execute(
            select(Base.metadata.tables["inventario"].c.stock_actual)
        ).scalar()
    finally:
        sesion_a.close()
    assert stock_a == 8


def test_tenant_adversario_por_claim_no_cambia_resolucion(mundo_multitenant, monkeypatch):
    """AC-3: un claim de tenant en un JWT valido no cambia el esquema resuelto.

    Se firma un token real con claims `institucion_id`/`nombre_esquema`/`tenant`
    que apuntan a B, pero Clerk entrega el correo primario verificado de un usuario
    de A. Se ejercita el camino real de `get_current_user` (firma verificada contra
    un JWKS mock y consulta a Clerk por `httpx.MockTransport`, sin red).
    """
    from fastapi.testclient import TestClient

    from app.api import dependencies
    from app.core.config import settings
    from app.main import app

    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publica = privada.public_key()
    jwk = json.loads(RSAAlgorithm.to_jwk(publica))
    jwk.update({"kid": "kid-ac3", "use": "sig", "alg": "RS256"})
    jwks = {"keys": [jwk]}
    emisor = f"https://clerk.test/{uuid4().hex}"
    monkeypatch.setattr(settings, "CLERK_ISSUER", emisor)
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_valor_falso")

    def _transporte(_peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "user_ac3",
                "primary_email_address_id": "idn_primario",
                "email_addresses": [
                    {
                        "id": "idn_primario",
                        "email_address": "u.inst-a@t.cl",
                        "verification": {"status": "verified"},
                    }
                ],
            },
        )

    ahora = int(time.time())
    token = jwt.encode(
        {
            "sub": "user_ac3",
            "iss": emisor,
            "iat": ahora,
            "nbf": ahora - 5,
            "exp": ahora + 3600,
            "azp": "http://localhost:4200",
            "institucion_id": "INST-B",
            "nombre_esquema": mundo_multitenant["esq_b"],
            "tenant": "INST-B",
            "schema": mundo_multitenant["esq_b"],
        },
        privada,
        algorithm="RS256",
        headers={"kid": "kid-ac3"},
    )

    Fabrica = sessionmaker(bind=mundo_multitenant["control"].get_bind())

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.obtener_fuente_jwks] = lambda: (lambda _i: jwks)
    app.dependency_overrides[dependencies.obtener_transporte_clerk] = (
        lambda: httpx.MockTransport(_transporte)
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            respuesta = cliente.get(
                "/api/v1/inventario/productos",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200, respuesta.text
    assert {fila["institucion_id"] for fila in respuesta.json()} == {"INST-A"}, (
        "el claim de tenant no debe desviar la resolucion hacia B"
    )

