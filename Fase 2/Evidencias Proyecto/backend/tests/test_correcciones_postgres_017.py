"""Feature 017, T11: correcciones que solo PostgreSQL 16 puede acreditar (gated).

  * AC-3/C-B: reintento de un alta institucional **parcialmente confirmada**. El
    esquema/usuario quedaron creados y el commit de control fallo; el reintento
    completa solo control sin recrear esquema/usuario ni reemitir invitacion, y
    un resto incompatible responde 503 recuperable.
  * C-G: carrera de bajas concurrentes de dos Administradores distintos. Al
    menos un Administrador activo sobrevive y una de las operaciones recibe 409.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_correcciones_postgres_017.py

    Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
    mantenimiento donde se crean y DESTRUYEN bases temporales propias; nunca se
    toca `apt_erp`.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.schema import CreateSchema

from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL, crear_sesion_control, crear_sesion_esquema
from app.models import (
    BaseControl,
    Departamento,
    InstitucionControl,
    MapaUsuarioEsquema,
    Rol,
    Usuario,
    VersionEsquema,
)
from app.schemas.control_schema import ESTADO_OPERATIVA, InstitucionAltaControlCrear
from app.schemas.usuario_schema import MotivoMutacion
from app.services import control_service, organizacion_service, tenant_service
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
    nombre = f"compustock_017t11_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    url = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        yield url
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
def _motor_con_control():
    with _base_temporal() as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)
            yield engine
        finally:
            engine.dispose()


def _datos(institucion_id: str, correo: str) -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id=institucion_id,
        nombre=f"Institucion {institucion_id}",
        correo_administrador=correo,
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo="Administracion",
    )


def _superadmin() -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Super",
        apellido="Admin",
        correo="superadmin@011.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Superadmin")
    return IdentidadAutenticada(usuario=usuario, sub="sub-011")


def _tenant(engine, institucion_id: str):
    return crear_sesion_esquema(
        tenant_service.nombre_esquema_para_institucion(institucion_id),
        motor=engine,
    )


def _segundo_administrador(engine, institucion_id: str, correo: str) -> int:
    sesion = _tenant(engine, institucion_id)
    try:
        rol = sesion.execute(
            select(Rol).where(Rol.nombre_rol == "Administrador")
        ).scalar_one()
        departamento = sesion.execute(
            select(Departamento).where(Departamento.institucion_id == institucion_id)
        ).scalars().first()
        usuario = Usuario(
            nombre="Segundo",
            apellido="Admin",
            correo=correo,
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
        sesion.add(usuario)
        sesion.commit()
        return usuario.usuario_id
    finally:
        sesion.close()


def _mapa(engine, institucion_id: str, correo: str, *, activo: bool = True) -> None:
    sesion = crear_sesion_control(engine)
    try:
        sesion.add(
            MapaUsuarioEsquema(
                correo=security.normalizar_correo(correo),
                institucion_id=institucion_id,
                nombre_esquema=tenant_service.nombre_esquema_para_institucion(
                    institucion_id
                ),
                activo=activo,
                estado_invitacion="aceptada",
            )
        )
        sesion.commit()
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# AC-3/C-B: reintento de alta institucional parcial
# ---------------------------------------------------------------------------


def test_reintento_completa_control_sin_duplicar_tenant_usuario_ni_invitacion():
    institucion_id = "INST-T011A"
    correo = "admin.t011a@ejemplo.cl"
    datos = _datos(institucion_id, correo)

    with _motor_con_control() as engine:
        nombre_esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)
        sesion = crear_sesion_control(engine)
        creadas: list[str] = []
        try:
            # Estado parcial: el tenant se confirma y el commit de control no.
            control_service._provisionar_tenant_postgres(
                sesion,
                datos,
                nombre_esquema,
                estado_invitacion="pendiente",
                invitacion_id="inv_original",
                expira_en=None,
            )
            sesion.rollback()
            assert sesion.get(InstitucionControl, institucion_id) is None

            def crear(correo_, ignore_existing=False):
                creadas.append(correo_)
                raise AssertionError("el reintento no debe crear otra invitacion")

            respuesta = control_service.aprovisionar_institucion(
                sesion,
                datos,
                lambda _c: True,
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    identidad_existente=False,
                    invitacion_pendiente=True,
                    invitacion_id="inv_original",
                ),
                crear_invitacion_fn=crear,
            )
        finally:
            sesion.close()

        assert creadas == []
        assert respuesta.estado == ESTADO_OPERATIVA
        assert respuesta.nombre_esquema == nombre_esquema

        # Un unico esquema tenant y una unica fila de usuario inicial.
        esquemas = [
            nombre
            for nombre in inspect(engine).get_schema_names()
            if nombre.startswith("tenant_")
        ]
        assert esquemas == [nombre_esquema], esquemas
        sesion_tenant = _tenant(engine, institucion_id)
        try:
            usuarios = sesion_tenant.execute(
                select(Usuario).where(Usuario.correo == correo)
            ).scalars().all()
            assert len(usuarios) == 1
            versiones = sesion_tenant.execute(
                select(VersionEsquema.version)
            ).scalars().all()
            assert versiones == [VERSION_ESQUEMA_OBJETIVO]
        finally:
            sesion_tenant.close()

        control = crear_sesion_control(engine)
        try:
            mapa = control.execute(
                select(MapaUsuarioEsquema).where(MapaUsuarioEsquema.correo == correo)
            ).scalar_one()
            assert mapa.invitacion_id == "inv_original"
            assert mapa.estado_invitacion == "pendiente"
            assert control.get(InstitucionControl, institucion_id) is not None
        finally:
            control.close()


def test_reintento_con_esquema_incompatible_responde_503_recuperable():
    institucion_id = "INST-T011B"
    datos = _datos(institucion_id, "admin.t011b@ejemplo.cl")
    nombre_esquema = tenant_service.nombre_esquema_para_institucion(institucion_id)

    with _motor_con_control() as engine:
        with engine.begin() as conexion:
            conexion.execute(CreateSchema(nombre_esquema))
        sesion = crear_sesion_control(engine)
        try:
            with pytest.raises(control_service.ErrorAltaParcialIncompatible):
                control_service.aprovisionar_institucion(
                    sesion, datos, lambda _c: True
                )
            assert sesion.get(InstitucionControl, institucion_id) is None
        finally:
            sesion.close()


# ---------------------------------------------------------------------------
# C-G: carrera del ultimo Administrador
# ---------------------------------------------------------------------------


def test_bajas_concurrentes_de_administradores_nunca_dejan_cero_activos():
    institucion_id = "INST-T011C"
    datos = _datos(institucion_id, "admin.t011c@ejemplo.cl")

    with _motor_con_control() as engine:
        sesion = crear_sesion_control(engine)
        try:
            control_service.aprovisionar_institucion(sesion, datos, lambda _c: True)
        finally:
            sesion.close()
        admin_original = None
        sesion_tenant = _tenant(engine, institucion_id)
        try:
            admin_original = sesion_tenant.execute(
                select(Usuario).where(
                    Usuario.correo == security.normalizar_correo(
                        datos.correo_administrador
                    )
                )
            ).scalar_one().usuario_id
        finally:
            sesion_tenant.close()
        segundo_correo = "segundo.t011c@ejemplo.cl"
        segundo = _segundo_administrador(engine, institucion_id, segundo_correo)
        _mapa(engine, institucion_id, segundo_correo)

        barrera = threading.Barrier(2)
        resultados: list[str] = []
        bloqueo = threading.Lock()

        def _baja(usuario_id: int, clave: str) -> None:
            tenant = _tenant(engine, institucion_id)
            control = crear_sesion_control(engine)
            try:
                barrera.wait(timeout=15)
                organizacion_service.cambiar_estado_usuario(
                    tenant,
                    control,
                    usuario_id,
                    False,
                    _superadmin(),
                    motivo=MotivoMutacion(codigo="seguridad_acceso"),
                    idempotencia=clave,
                    institucion_id=institucion_id,
                )
                resultado = "ok"
            except HTTPException as exc:
                resultado = str(exc.status_code)
            except Exception as exc:  # pragma: no cover - diagnostico
                resultado = f"error:{type(exc).__name__}"
            finally:
                control.close()
                tenant.close()
            with bloqueo:
                resultados.append(resultado)

        hilos = [
            threading.Thread(target=_baja, args=(admin_original, "baja-t011-original")),
            threading.Thread(target=_baja, args=(segundo, "baja-t011-segundo")),
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        assert sorted(resultados) == ["409", "ok"], resultados

        control = crear_sesion_control(engine)
        try:
            mapas = control.execute(
                select(MapaUsuarioEsquema).where(
                    MapaUsuarioEsquema.institucion_id == institucion_id
                )
            ).scalars().all()
        finally:
            control.close()
        activos = [mapa for mapa in mapas if mapa.activo]
        assert len(activos) == 1, [(m.correo, m.activo) for m in mapas]
