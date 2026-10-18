"""T8 (Feature 012): gating, routing e aislamiento HTTP sobre PostgreSQL 16 - gated.

Complemento gated de la suite SQLite para los AC de backend de la Feature 012 que
solo se acreditan donde hay namespaces reales (`control` + esquemas tenant):

  * **Gating por capacidad** con llamadas HTTP directas (`get_db_negocio` resuelve
    el tenant de verdad): capacidad apagada -> 403 sin mutacion; habilitada ->
    disponible para el rol autorizado (AC-5/AC-13).
  * **Routing de institucion inactiva** sobre conexiones reales: `control.institucion.activo
    = False` deniega la operacion tenant con **401** antes de sesion/version; la
    reactivacion restaura el acceso (AC-2).
  * **Aislamiento cross-tenant** de las rutas organizacionales nuevas: un id de
    otra institucion se oculta con **404** y no aparece en los listados (AC-12).
  * **Dashboard SaaS** con instituciones homonimas, una inactiva (sin metricas) y
    una activa incompatible (fallo **completo**, nunca parcial) (AC-4).

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_gestion_administrativa_http_postgres_012.py

Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
mantenimiento donde el test crea y DESTRUYE bases temporales propias; nunca toca
`apt_erp`. NO se anade ninguna dependencia: `psycopg2` ya esta en
`requirements.txt`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema

from app.api import dependencies
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import (
    Base,
    ESQUEMA_CONTROL,
    crear_sesion_control,
    crear_sesion_esquema,
)
from app.main import app
from app.models import BaseControl, MapaUsuarioEsquema, Rol, Sede, Usuario, VersionEsquema
from app.schemas.control_schema import InstitucionAltaControlCrear
from app.services import control_service, tenant_service
from app.services.auth_service import IdentidadAutenticada

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

_INSTITUCION_A = "INST-012A"
_INSTITUCION_B = "INST-012B"
_NOMBRE_HOMONIMO = "Instituto Homonimo"


# ---------------------------------------------------------------------------
# Base temporal y utilidades
# ---------------------------------------------------------------------------


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


@contextmanager
def _base_temporal():
    dsn = (_POSTGRES_TEST_URL or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_012http_{uuid4().hex[:12]}"
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


def _datos(institucion_id: str, correo: str) -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id=institucion_id,
        nombre=_NOMBRE_HOMONIMO,
        correo_administrador=correo,
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo="Administracion",
    )


def _identidad_de_tenant(engine, institucion_id: str, correo: str) -> IdentidadAutenticada:
    """Identidad del Administrador aprovisionado, sin depender de la sesion abierta."""
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        usuario = sesion.execute(
            select(Usuario).where(Usuario.correo == correo)
        ).scalar_one()
        rol_nombre = usuario.rol.nombre_rol
        departamento_id = usuario.departamento_id
        usuario_id = usuario.usuario_id
    finally:
        sesion.close()
    fantasma = Usuario(
        usuario_id=usuario_id,
        nombre="Admin",
        apellido="012",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
    )
    fantasma.rol = Rol(nombre_rol=rol_nombre)
    return IdentidadAutenticada(usuario=fantasma, sub="sub-012-http")


def _crear_sede_en_tenant(engine, institucion_id: str, nombre: str) -> int:
    """Crea una sede adicional en el tenant y devuelve su id (colision de ids)."""
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        sede = Sede(nombre=nombre, institucion_id=institucion_id)
        sesion.add(sede)
        sesion.commit()
        return sede.sede_id
    finally:
        sesion.close()


def _contar_sedes(engine, institucion_id: str) -> int:
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        return sesion.execute(
            select(func.count()).select_from(Sede).where(
                Sede.institucion_id == institucion_id
            )
        ).scalar_one()
    finally:
        sesion.close()


def _capacidad(engine, institucion_id: str, funcion: str, habilitada: bool) -> None:
    sesion = crear_sesion_control(engine)
    try:
        control_service.actualizar_capacidad(
            sesion, institucion_id, funcion, habilitada
        )
    finally:
        sesion.close()


def _estado_institucion(engine, institucion_id: str, activo: bool) -> None:
    sesion = crear_sesion_control(engine)
    try:
        control_service.cambiar_estado_institucion(sesion, institucion_id, activo)
    finally:
        sesion.close()


@contextmanager
def _cliente(mundo, identidad: IdentidadAutenticada):
    """`TestClient` real: `get_db` en control; `get_db_negocio` resuelve el tenant."""
    Fabrica = sessionmaker(bind=mundo["motor_control"])

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: identidad
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixture: control + dos tenants homonimos aprovisionados de verdad
# ---------------------------------------------------------------------------


@pytest.fixture
def mundo_012():
    with _base_temporal() as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            # Feature 012: el canonico (con `activo`) y `funcion_institucion` viven
            # solo en control; se crean primero para que `institucion` sea superset.
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)

            datos_a = _datos(_INSTITUCION_A, "admin.a@012.cl")
            datos_b = _datos(_INSTITUCION_B, "admin.b@012.cl")
            sesion_control = crear_sesion_control(engine)
            try:
                # El control vigente porta su version objetivo (DDL 01 la siembra);
                # la resolucion de contexto que alimenta el gating la lee de aqui.
                sesion_control.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
                sesion_control.flush()
                control_service.aprovisionar_institucion(
                    sesion_control, datos_a, lambda _correo: True
                )
                control_service.aprovisionar_institucion(
                    sesion_control, datos_b, lambda _correo: True
                )
            finally:
                sesion_control.close()

            yield {
                "engine": engine,
                "motor_control": motor_control,
                "identidad_a": _identidad_de_tenant(
                    engine, _INSTITUCION_A, datos_a.correo_administrador
                ),
                "identidad_b": _identidad_de_tenant(
                    engine, _INSTITUCION_B, datos_b.correo_administrador
                ),
                # Sede que solo existe en B (colision de ids entre esquemas): sirve
                # para probar el aislamiento cross-tenant pidiendo su id desde A.
                "sede_b": _crear_sede_en_tenant(engine, _INSTITUCION_B, "Sede Ajena B"),
            }
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# AC-5/AC-13: gating por capacidad sobre HTTP directo
# ---------------------------------------------------------------------------


def test_gating_capacidad_catalogo_403_y_habilitada_restaura(mundo_012):
    _capacidad(mundo_012["engine"], _INSTITUCION_A, "catalogo", False)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        apagada = cliente.get("/api/v1/inventario/productos")
    assert apagada.status_code == 403, apagada.text

    _capacidad(mundo_012["engine"], _INSTITUCION_A, "catalogo", True)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        encendida = cliente.get("/api/v1/inventario/productos")
    assert encendida.status_code == 200, encendida.text


def test_gating_gestion_organizacional_403_sin_mutar_y_habilitada_crea(mundo_012):
    _capacidad(mundo_012["engine"], _INSTITUCION_A, "gestion_organizacional", False)
    sedes_antes = _contar_sedes(mundo_012["engine"], _INSTITUCION_A)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        bloqueado = cliente.post(
            "/api/v1/organizacion/sedes", json={"nombre": "Sede Bloqueada"}
        )
    assert bloqueado.status_code == 403, bloqueado.text
    assert _contar_sedes(mundo_012["engine"], _INSTITUCION_A) == sedes_antes

    _capacidad(mundo_012["engine"], _INSTITUCION_A, "gestion_organizacional", True)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        permitido = cliente.post(
            "/api/v1/organizacion/sedes", json={"nombre": "Sede Permitida"}
        )
    assert permitido.status_code == 201, permitido.text


# ---------------------------------------------------------------------------
# AC-2: institucion inactiva deniega (401) y la reactivacion restaura
# ---------------------------------------------------------------------------


def test_institucion_inactiva_deniega_401_y_reactivacion_restaura(mundo_012):
    _estado_institucion(mundo_012["engine"], _INSTITUCION_A, False)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        inactiva = cliente.get("/api/v1/inventario/productos")
    assert inactiva.status_code == 401, inactiva.text

    _estado_institucion(mundo_012["engine"], _INSTITUCION_A, True)
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        activa = cliente.get("/api/v1/inventario/productos")
    assert activa.status_code == 200, activa.text


# ---------------------------------------------------------------------------
# AC-12: aislamiento cross-tenant de las rutas organizacionales nuevas
# ---------------------------------------------------------------------------


def test_sede_ajena_se_oculta_404_y_no_aparece_en_el_listado(mundo_012):
    sede_ajena = mundo_012["sede_b"]
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        edicion = cliente.put(
            f"/api/v1/organizacion/sedes/{sede_ajena}",
            json={"nombre": "Intruso"},
        )
        listado = cliente.get("/api/v1/organizacion/sedes")
    assert edicion.status_code == 404, edicion.text
    assert listado.status_code == 200, listado.text
    filas = listado.json()
    assert filas, "el tenant A debe ver al menos su Sede Central"
    assert all(fila["institucion_id"] == _INSTITUCION_A for fila in filas)
    assert sede_ajena not in {fila["sede_id"] for fila in filas}


# ---------------------------------------------------------------------------
# Regresion: `/auth/me` de un usuario de tenant sobre PostgreSQL real
# ---------------------------------------------------------------------------


def test_auth_me_resuelve_identidad_de_tenant(mundo_012):
    """`GET /auth/me` debe resolver el usuario local del **tenant**, no control.

    Un rol limitado vive en el esquema de su institucion (Feature 010); si la
    releida de la identidad ocurre en `control` no hay fila y la respuesta seria
    un 401 espurio. Debe devolver 200 con su rol y su institucion efectiva.
    """
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        respuesta = cliente.get("/api/v1/auth/me")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["correo"] == "admin.a@012.cl"
    assert cuerpo["rol"] == "Administrador"
    assert cuerpo["institucion"] == {
        "institucion_id": _INSTITUCION_A,
        "nombre": _NOMBRE_HOMONIMO,
    }


# ---------------------------------------------------------------------------
# Regresion: alta de usuario por un Admin de tenant sobre PostgreSQL real
# ---------------------------------------------------------------------------


def _rol_y_departamento_admin(engine, institucion_id: str, correo: str) -> tuple[int, int]:
    esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
    sesion = crear_sesion_esquema(esquema, motor=engine)
    try:
        bodeguero = sesion.execute(
            select(Rol).where(Rol.nombre_rol == "Bodeguero")
        ).scalar_one()
        admin = sesion.execute(
            select(Usuario).where(Usuario.correo == correo)
        ).scalar_one()
        return bodeguero.rol_id, admin.departamento_id
    finally:
        sesion.close()


def test_alta_usuario_por_admin_de_tenant_persiste_en_su_esquema(mundo_012):
    """`POST /usuarios/` debe crear en el tenant (no en control) y vincular el correo.

    Con la sesion de control no habria rol/departamento del tenant y el alta
    respondia 403; ademas la vinculacion `mapa_usuario_esquema` debe quedar activa
    para que el correo resuelva (D-3). Sin el fix de sesion este test falla.
    """
    correo = "nuevo.bodega@012.cl"
    rol_id, departamento_id = _rol_y_departamento_admin(
        mundo_012["engine"], _INSTITUCION_A, "admin.a@012.cl"
    )
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
            lambda: (lambda _correo: True)
        )
        respuesta = cliente.post(
            "/api/v1/usuarios/",
            json={
                "nombre": "Nuevo",
                "apellido": "Bodega",
                "correo": correo,
                "departamento_id": departamento_id,
                "rol_id": rol_id,
            },
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["correo"] == correo

    # La fila vive en el esquema del tenant A.
    esquema = tenant_service.nombre_esquema_para_institucion(_INSTITUCION_A)
    sesion_tenant = crear_sesion_esquema(esquema, motor=mundo_012["engine"])
    try:
        creado = sesion_tenant.execute(
            select(Usuario).where(Usuario.correo == correo)
        ).scalar_one_or_none()
    finally:
        sesion_tenant.close()
    assert creado is not None, "el usuario debe persistir en el tenant del Admin"

    # La vinculacion queda registrada y activa en control.
    sesion_control = crear_sesion_control(mundo_012["engine"])
    try:
        mapa = sesion_control.get(MapaUsuarioEsquema, correo)
    finally:
        sesion_control.close()
    assert mapa is not None, "el alta debe registrar la vinculacion local (D-3)"
    assert mapa.activo is True
    assert mapa.institucion_id == _INSTITUCION_A
    assert mapa.nombre_esquema == esquema


# ---------------------------------------------------------------------------
# AC-4: dashboard SaaS con homonimos, inactiva y activa incompatible
# ---------------------------------------------------------------------------


def test_dashboard_saas_homonimos_e_inactiva_sin_metricas(mundo_012):
    _estado_institucion(mundo_012["engine"], _INSTITUCION_B, False)
    sesion = crear_sesion_control(mundo_012["engine"])
    try:
        resumen = control_service.dashboard_saas(sesion)
    finally:
        sesion.close()

    assert resumen.total_instituciones_activas == 1
    por_id = {fila.institucion_id: fila for fila in resumen.instituciones}
    assert set(por_id) == {_INSTITUCION_A, _INSTITUCION_B}

    activa = por_id[_INSTITUCION_A]
    inactiva = por_id[_INSTITUCION_B]
    # Homonimos: mismo nombre, atribucion por `institucion_id`, sin fusionarse.
    assert activa.nombre == inactiva.nombre == _NOMBRE_HOMONIMO
    assert activa.activo is True
    assert inactiva.activo is False
    assert inactiva.sedes is None, "una institucion inactiva no expone metricas"
    assert not inactiva.usuarios_por_rol


# ---------------------------------------------------------------------------
# T12: el listado de usuarios resuelve el tenant y publica estado/sede
# ---------------------------------------------------------------------------


def test_listado_usuarios_publica_estado_y_sede_desde_el_tenant(mundo_012):
    """`GET /usuarios/` lee el tenant (no control) y publica `activo`/`sede_id`."""
    with _cliente(mundo_012, mundo_012["identidad_a"]) as cliente:
        listado = cliente.get("/api/v1/usuarios/")
    assert listado.status_code == 200, listado.text
    filas = listado.json()
    assert filas, "el listado debe resolver el tenant de A, no el esquema de control"
    correos = {fila["correo"] for fila in filas}
    assert "admin.b@012.cl" not in correos, "no debe filtrar el tenant homonimo"
    admin = next(fila for fila in filas if fila["correo"] == "admin.a@012.cl")
    assert admin["activo"] is True, "el Administrador aprovisionado tiene mapa activo"
    assert "sede_id" in admin


def test_dashboard_saas_activa_incompatible_falla_completo(mundo_012):
    """AC-4: una activa requerida con version incompatible produce error, no parcial."""
    # B vuelve a estar activa pero con su tenant fuera de la version objetivo.
    _estado_institucion(mundo_012["engine"], _INSTITUCION_B, True)
    esquema_b = tenant_service.nombre_esquema_para_institucion(_INSTITUCION_B)
    sesion_b = crear_sesion_esquema(esquema_b, motor=mundo_012["engine"])
    try:
        sesion_b.execute(update(VersionEsquema).values(version="011.1"))
        sesion_b.commit()
    finally:
        sesion_b.close()

    sesion = crear_sesion_control(mundo_012["engine"])
    try:
        with pytest.raises(control_service.ErrorDashboardSaaS):
            control_service.dashboard_saas(sesion)
    finally:
        sesion.close()
