"""T8 (Feature 012): gating de capacidades end-to-end sobre **rutas reales**.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`) con la
dependencia de capacidad cableada en cada router (`plan.md` §2). A diferencia de
`test_capacidades_gating_012.py` (que prueba `requiere_capacidad` sobre una
app-sonda), aqui se ejerce la operacion de negocio real: el gating es una
**condicion adicional** a la matriz central y responde **403 sin mutacion**,
incluso ante invocacion directa de la API (D-6/AC-5/AC-13).

Trazabilidad: AC-5 (capacidades y gating), AC-13 (contrato/403 adicional),
AC-1/AC-4 (dashboard y catalogo del tenant).

El mundo se siembra sobre el padron multiinstitucion (`dos_instituciones`) y un
contexto de control coherente: institucion canonica activa, mapa `correo ->
esquema` activo, version objetivo y las seis capacidades con las apagadas
explicitas. La resolucion de contexto es la real (`tenant_service`).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.main import app
from app.models import (
    CAPACIDADES,
    FuncionInstitucion,
    InstitucionControl,
    MapaUsuarioEsquema,
    Producto,
    Sede,
    VersionEsquema,
)

from ._soporte_sede_011 import identidad

_CORREO = "gating.inst01@compustock.cl"

#: Rutas reales asociadas a cada capacidad (transcritas del mapa central).
RUTA_CATALOGO = "/api/v1/inventario/productos"
RUTA_INVENTARIO = "/api/v1/inventario/stock"
RUTA_TICKETS = "/api/v1/tickets/"
RUTA_KANBAN = "/api/v1/tickets/{ticket_id}/estado"
RUTA_DASHBOARD = "/api/v1/dashboard/"
RUTA_SEDES = "/api/v1/organizacion/sedes"
RUTA_ROLES = "/api/v1/usuarios/roles"


# ---------------------------------------------------------------------------
# Contexto de control y cliente HTTP
# ---------------------------------------------------------------------------


def _sembrar_contexto(
    motor,
    datos,
    *,
    correo: str = _CORREO,
    capacidades_apagadas: frozenset[str] = frozenset(),
) -> None:
    """Instala control coherente para que el correo resuelva a INST01.

    Reutiliza el espejo INST01 ya creado por `dos_instituciones` (la tabla
    `institucion` es superset en SQLite) y agrega: mapa activo, version objetivo
    y las seis capacidades con las apagadas explicitas.
    """
    institucion_id = datos["inst_propia"]
    with sessionmaker(bind=motor)() as db:
        if db.get(InstitucionControl, institucion_id) is None:
            db.add(
                InstitucionControl(
                    institucion_id=institucion_id,
                    nombre="Instituto de Prueba",
                    activo=True,
                )
            )
            db.flush()
        if db.get(MapaUsuarioEsquema, correo) is None:
            db.add(
                MapaUsuarioEsquema(
                    correo=correo,
                    institucion_id=institucion_id,
                    nombre_esquema="tenant_inst01",
                    activo=True,
                )
            )
            db.flush()
        if db.execute(select(VersionEsquema)).scalars().first() is None:
            db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        for funcion in CAPACIDADES:
            fila = db.get(FuncionInstitucion, (institucion_id, funcion))
            habilitada = funcion not in capacidades_apagadas
            if fila is None:
                db.add(
                    FuncionInstitucion(
                        institucion_id=institucion_id,
                        funcion=funcion,
                        habilitada=habilitada,
                    )
                )
            else:
                fila.habilitada = habilitada
        db.commit()


@contextmanager
def _cliente(motor, rol: str, datos, *, correo: str = _CORREO):
    """`TestClient` del `app` real con identidad y sesion sobre el motor de prueba."""
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: identidad(
        rol, datos["departamento_id"], 9999, None, correo
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


def _contar(motor, entidad) -> int:
    with sessionmaker(bind=motor)() as db:
        return db.execute(select(func.count()).select_from(entidad)).scalar_one()


# ---------------------------------------------------------------------------
# AC-5/AC-13: 403 sin mutacion por capacidad apagada
# ---------------------------------------------------------------------------


def test_catalogo_apagado_bloquea_lectura_y_escritura_sin_mutar(motor, dos_instituciones):
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas={"catalogo"})
    productos_antes = _contar(motor, Producto)
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        lectura = cliente.get(RUTA_CATALOGO)
        escritura = cliente.post(
            RUTA_CATALOGO,
            json={
                "nombre": "Producto Bloqueado",
                "categoria_id": dos_instituciones["categoria_id"],
                "stock_minimo": 1,
            },
        )
    assert lectura.status_code == 403, lectura.text
    assert escritura.status_code == 403, escritura.text
    assert _contar(motor, Producto) == productos_antes, "el 403 no debe crear filas"


def test_catalogo_habilitado_permite_la_operacion(motor, dos_instituciones):
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas=set())
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        respuesta = cliente.get(RUTA_CATALOGO)
    assert respuesta.status_code == 200, respuesta.text


@pytest.mark.parametrize(
    "capacidad,metodo,ruta",
    (
        ("inventario", "GET", RUTA_INVENTARIO),
        ("tickets", "GET", RUTA_TICKETS),
        ("dashboard", "GET", RUTA_DASHBOARD),
        ("gestion_organizacional", "GET", RUTA_SEDES),
        ("gestion_organizacional", "GET", RUTA_ROLES),
    ),
)
def test_capacidad_apagada_bloquea_su_grupo(motor, dos_instituciones, capacidad, metodo, ruta):
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas={capacidad})
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        respuesta = cliente.request(metodo, ruta)
    assert respuesta.status_code == 403, (capacidad, respuesta.text)


@pytest.mark.parametrize(
    "capacidad,metodo,ruta",
    (
        ("inventario", "GET", RUTA_INVENTARIO),
        ("tickets", "GET", RUTA_TICKETS),
        ("dashboard", "GET", RUTA_DASHBOARD),
        ("gestion_organizacional", "GET", RUTA_SEDES),
        ("gestion_organizacional", "GET", RUTA_ROLES),
    ),
)
def test_capacidad_habilitada_no_bloquea_su_grupo(motor, dos_instituciones, capacidad, metodo, ruta):
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas=set())
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        respuesta = cliente.request(metodo, ruta)
    assert respuesta.status_code != 403, (capacidad, respuesta.text)


def test_kanban_apagado_bloquea_el_cambio_de_estado(motor, dos_instituciones):
    """El gating corre antes de la regla de negocio: un ticket inexistente da 403."""
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas={"kanban"})
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        bloqueado = cliente.patch(
            RUTA_KANBAN.format(ticket_id=999999), json={"estado_id": 1}
        )
        _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas=set())
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        # habilitada: el mismo ticket inexistente deja de ser 403 y es 404.
        habilitado = cliente.patch(
            RUTA_KANBAN.format(ticket_id=999999), json={"estado_id": 1}
        )
    assert bloqueado.status_code == 403, bloqueado.text
    assert habilitado.status_code == 404, habilitado.text


def test_gestion_organizacional_apagada_no_crea_sede(motor, dos_instituciones):
    _sembrar_contexto(
        motor, dos_instituciones, capacidades_apagadas={"gestion_organizacional"}
    )
    sedes_antes = _contar(motor, Sede)
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        respuesta = cliente.post(RUTA_SEDES, json={"nombre": "Sede Bloqueada"})
    assert respuesta.status_code == 403, respuesta.text
    assert _contar(motor, Sede) == sedes_antes, "el 403 no debe crear la sede"

    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas=set())
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        permitido = cliente.post(RUTA_SEDES, json={"nombre": "Sede Permitida"})
    assert permitido.status_code == 201, permitido.text


# ---------------------------------------------------------------------------
# AC-13: la capacidad es adicional a la matriz, no su sustituto
# ---------------------------------------------------------------------------


def test_capacidad_habilitada_no_concede_permiso_de_rol(motor, dos_instituciones):
    """Con catalogo habilitado, un rol sin permiso de matriz sigue recibiendo 403."""
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas=set())
    with _cliente(motor, "Bodeguero", dos_instituciones) as cliente:
        respuesta = cliente.post(
            RUTA_CATALOGO,
            json={
                "nombre": "Producto Bodeguero",
                "categoria_id": dos_instituciones["categoria_id"],
                "stock_minimo": 1,
            },
        )
    assert respuesta.status_code == 403, respuesta.text


def test_capacidad_apagada_deniega_adicionalmente_al_rol_autorizado(motor, dos_instituciones):
    """El rol autorizado (Administrador) recibe 403 si la capacidad esta apagada."""
    _sembrar_contexto(motor, dos_instituciones, capacidades_apagadas={"catalogo"})
    with _cliente(motor, "Administrador", dos_instituciones) as cliente:
        respuesta = cliente.get(RUTA_CATALOGO)
    assert respuesta.status_code == 403, respuesta.text
