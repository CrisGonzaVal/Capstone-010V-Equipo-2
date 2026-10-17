"""Correccion de integracion T12/T14 (Feature 011): lectura global del tablero.

`GET /api/v1/tickets/` con una identidad **Superadmin** (lectura global en
PostgreSQL) devolvia **500** `ResponseValidationError` con
`DetachedInstanceError` al serializar `detalles[].producto.categoria`.

Cadena causal:

1. `global_service._LectorPostgres.sesion` abre una sesion por tenant sobre la
   conexion `REPEATABLE READ` compartida y la **cierra** al salir del bloque.
2. `ticket_service.listar_tickets` carga eager `detalles` y `detalle.producto`
   (`selectinload` en cadena), pero **no** `producto.categoria`.
3. FastAPI serializa la respuesta **despues** de que `agregar_lista_global`
   cerro la sesion, de modo que el `lazy="select"` de `Producto.categoria`
   intenta cargar sobre un objeto ya desasociado -> `DetachedInstanceError`.

No es un defecto de la Feature 011: el camino (`global_service`, el wiring del
endpoint y la cadena de `selectinload`) es **identico** al commit de la 010; la
suite SQLite no lo reproduce porque su `_LectorLogico` reutiliza la sesion viva.
Por eso se acredita aqui, contra PostgreSQL 16 real y por la interfaz HTTP
publica, siguiendo el patron gated del repositorio.

COMO ACTIVARLA
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_lectura_global_tickets_011.py

    Sin `POSTGRES_TEST_URL` la prueba se **salta**. La URL apunta a una base de
    mantenimiento donde el modulo crea y DESTRUYE bases/esquemas temporales
    propios; nunca toca `apt_erp`.
"""

from __future__ import annotations

import importlib
import os

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import Base, ESQUEMA_CONTROL

# La infraestructura temporal y el cliente HTTP real de la lectura global ya
# viven en el modulo gated de la 010; se reutilizan para no duplicarlos.
from tests.test_integracion_multitenant_010 import (
    _base_temporal,
    _cliente_http,
    _esquema,
    _url_sqlalchemy,
)

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

_CORREO_SUPER = "super.tablero011@compustock.cl"
_CORREO_TENANT = "bodega.tablero011@compustock.cl"


def _sembrar_tenant_con_ticket(motor_tenant, institucion_id: str) -> dict:
    """Un tenant con un ticket y un detalle cuyo producto tiene categoria."""
    modelos = importlib.import_module("app.models")
    sesion = Session(bind=motor_tenant)
    try:
        sesion.add(modelos.Institucion(institucion_id=institucion_id, nombre="Inst T"))
        rol = modelos.Rol(nombre_rol="Administrador", descripcion="rol")
        sesion.add(rol)
        sesion.flush()

        departamento = modelos.Departamento(
            nombre_dep="Operaciones", descripcion="d", institucion_id=institucion_id
        )
        sesion.add(departamento)
        sesion.flush()

        usuario = modelos.Usuario(
            nombre="U",
            apellido="T",
            correo="u.tablero011@compustock.cl",
            departamento_id=departamento.departamento_id,
            rol_id=rol.rol_id,
        )
        categoria = modelos.Categoria(
            nombre_cat="Papeleria", institucion_id=institucion_id
        )
        prioridad = modelos.Prioridad(nombre="ALTA", descripcion="alta")
        estado = modelos.EstadoTicket(nombre="Pendiente", descripcion="pendiente")
        sesion.add_all([usuario, categoria, prioridad, estado])
        sesion.flush()

        producto = modelos.Producto(
            nombre="Cuaderno linedado",
            descripcion="detalle con categoria",
            unidad_medida="UNIDAD",
            stock_minimo=10,
            categoria_id=categoria.categoria_id,
            institucion_id=institucion_id,
        )
        sesion.add(producto)
        sesion.flush()

        ticket = modelos.Ticket(
            usuario_id=usuario.usuario_id,
            prioridad_id=prioridad.prioridad_id,
            estado_id=estado.estado_id,
            asunto="Papel para la oficina central",
            descripcion="Sembrado para el tablero",
            institucion_id=institucion_id,
        )
        sesion.add(ticket)
        sesion.flush()

        sesion.add(
            modelos.DetalleTicket(
                ticket_id=ticket.ticket_id,
                producto_id=producto.producto_id,
                cantidad_solicitada=2,
                cantidad_entregada=0,
                institucion_id=institucion_id,
            )
        )
        sesion.add(modelos.VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        sesion.commit()
        return {
            "ticket_id": ticket.ticket_id,
            "producto_id": producto.producto_id,
            "categoria_nombre": "Papeleria",
        }
    finally:
        sesion.close()


def _sembrar_control(motor_control, esq_tenant: str, institucion_id: str) -> None:
    """Institucion, la identidad Superadmin global y el mapa `correo -> esquema`."""
    modelos = importlib.import_module("app.models")
    sesion = Session(bind=motor_control)
    try:
        sesion.add_all(
            [
                modelos.Institucion(institucion_id=institucion_id, nombre="Inst T"),
                modelos.Institucion(institucion_id="CTRL-SAAS", nombre="CompuStock SaaS"),
            ]
        )
        rol_super = modelos.Rol(nombre_rol="Superadmin", descripcion="global")
        sesion.add(rol_super)
        sesion.flush()
        departamento = modelos.Departamento(
            nombre_dep="Control", descripcion="d", institucion_id=institucion_id
        )
        sesion.add(departamento)
        sesion.flush()
        sesion.add(
            modelos.Usuario(
                nombre="Super",
                apellido="Admin",
                correo=_CORREO_SUPER,
                departamento_id=departamento.departamento_id,
                rol_id=rol_super.rol_id,
            )
        )
        sesion.add_all(
            [
                # La identidad global vive en `control` (no es un tenant).
                modelos.MapaUsuarioEsquema(
                    correo=_CORREO_SUPER,
                    institucion_id="CTRL-SAAS",
                    nombre_esquema=ESQUEMA_CONTROL,
                    activo=True,
                ),
                # Un tenant registrado con una lectura que el global agrega.
                modelos.MapaUsuarioEsquema(
                    correo=_CORREO_TENANT,
                    institucion_id=institucion_id,
                    nombre_esquema=esq_tenant,
                    activo=True,
                ),
            ]
        )
        sesion.commit()
    finally:
        sesion.close()


@pytest.fixture
def mundo_ticket_global():
    """Base temporal con `control` + un tenant con un ticket por detalle."""
    from app.services.auth_service import IdentidadAutenticada

    modelos = importlib.import_module("app.models")
    institucion_id = "INST-T"
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                from sqlalchemy.schema import CreateSchema

                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            Base.metadata.create_all(bind=motor_control)

            with _esquema(engine, "tenant_tablero") as (esq_tenant, motor_tenant):
                sembrado = _sembrar_tenant_con_ticket(motor_tenant, institucion_id)
                _sembrar_control(motor_control, esq_tenant, institucion_id)

                sesion_control = Session(bind=motor_control)
                try:
                    usuario = modelos.Usuario(
                        usuario_id=1,
                        nombre="Super",
                        apellido="Admin",
                        correo=_CORREO_SUPER,
                        departamento_id=1,
                        rol_id=1,
                    )
                    usuario.rol = modelos.Rol(nombre_rol="Superadmin")
                    identidad_super = IdentidadAutenticada(
                        usuario=usuario, sub="sub-tablero-011"
                    )
                    yield {
                        "engine": engine,
                        "control": sesion_control,
                        "esq_tenant": esq_tenant,
                        "identidad_super": identidad_super,
                        **sembrado,
                    }
                finally:
                    sesion_control.close()
        finally:
            engine.dispose()


def test_lectura_global_de_tickets_responde_200_con_categoria(mundo_ticket_global):
    """`GET /tickets/` global (Superadmin) serializa `detalle.producto.categoria`.

    Antes de la correccion respondia 500: la sesion por tenant se cerraba antes
    de la serializacion y `categoria` no estaba cargada eager.
    """
    from app.api import dependencies

    with _cliente_http(
        mundo_ticket_global,
        {dependencies.get_current_user: lambda: mundo_ticket_global["identidad_super"]},
    ) as cliente:
        respuesta = cliente.get("/api/v1/tickets/")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    ticket = next(
        t for t in cuerpo if t["ticket_id"] == mundo_ticket_global["ticket_id"]
    )
    assert ticket["detalles"], "el ticket sembrado debe traer su detalle"
    categoria = ticket["detalles"][0]["producto"]["categoria"]
    assert categoria is not None, "la categoria debe viajar en la respuesta"
    assert categoria["nombre_cat"] == mundo_ticket_global["categoria_nombre"]
