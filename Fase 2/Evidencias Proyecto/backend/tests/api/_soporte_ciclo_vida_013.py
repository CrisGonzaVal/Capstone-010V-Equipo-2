"""Soporte compartido de las pruebas rojas de la Feature 013 (ciclo de vida).

Los modulos `test_ciclo_vida_*_013.py` comparten cuatro necesidades:

1. **Contrato de rutas y operaciones.** La 013 agrega cinco operaciones
   (`POST .../anulacion`, `POST .../rechazo`, `PUT /tickets/{id}`,
   `GET /tickets/{id}`, `GET /tickets/{id}/historial`). Este modulo las fija
   como constantes para que todos los modulos hablen del mismo contrato.
2. **Fase roja explícita.** `exigir_ruta`/`exigir_operacion` fallan con
   `pytest.fail` mientras la 013 no cablee la API/matriz (T6/T7), de modo que
   una prueba que espera `404` o `403` nunca pase por el motivo equivocado
   (ruta u operación ausentes). El resto de pruebas cae en rojo natural porque
   el router responde 404 `Not Found` y los contratos esperan otros códigos o
   detalles.
3. **Construccion del mundo**: catalogo canonico de cinco estados (con
   `Anulado` al final, como lo siembra la 013), sede del departamento (Feature
   011) y siembra directa de tickets por ORM (tickets en cualquier estado, sin
   pasar por el alta).
4. **Observacion**: historial por HTTP, ticket releyendo `GET /tickets/`,
   stock por sede y conteo de movimientos (reutiliza `_soporte_sede_011`).

El seam bajo prueba en toda la 013 es la interfaz HTTP (`TestClient`), como en
el resto de la suite; este soporte no prueba nada por si solo.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos
from app.main import app
from app.models import DetalleTicket, EstadoTicket, Ticket

from ._soporte_sede_011 import (
    SIN_AUTENTICAR,
    asegurar_sede_de_departamento,
    cliente as cliente_con_rol,
    contar_en,
    identidad,
    leer_stock_sede,
    sesion,
)

# ---------------------------------------------------------------------------
# Contrato de rutas y operaciones (spec §6, plan §2)
# ---------------------------------------------------------------------------

RUTA_ANULACION = "/api/v1/tickets/{ticket_id}/anulacion"
RUTA_RECHAZO = "/api/v1/tickets/{ticket_id}/rechazo"
RUTA_EDICION = "/api/v1/tickets/{ticket_id}"
RUTA_DETALLE = "/api/v1/tickets/{ticket_id}"
RUTA_HISTORIAL = "/api/v1/tickets/{ticket_id}/historial"

_TODOS = {"Superadmin", "Administrador", "Bodeguero", "Solicitante"}

#: Las cinco operaciones nuevas con los roles exactos del AC-17 (transcritos
#: de la spec; nunca se leen de `MATRIZ_PERMISOS`, para evitar la prueba
#: tautologica).
OPERACIONES_013: dict[tuple[str, str], set[str]] = {
    ("POST", RUTA_ANULACION): {"Administrador", "Solicitante"},
    ("POST", RUTA_RECHAZO): {"Administrador", "Bodeguero"},
    ("PUT", RUTA_EDICION): {"Administrador", "Solicitante"},
    ("GET", RUTA_DETALLE): _TODOS,
    ("GET", RUTA_HISTORIAL): _TODOS,
}

#: Asociacion capacidad <-> operacion que la 013 debe agregar al mapa central
#: (plan §2: anulacion/rechazo -> `kanban`; edicion/detalle/historial ->
#: `tickets`), transcrita de la decision del plan.
CAPACIDADES_013: dict[tuple[str, str], str] = {
    ("POST", RUTA_ANULACION): "kanban",
    ("POST", RUTA_RECHAZO): "kanban",
    ("PUT", RUTA_EDICION): "tickets",
    ("GET", RUTA_DETALLE): "tickets",
    ("GET", RUTA_HISTORIAL): "tickets",
}

#: Campos que cada fila del historial debe exponer por API (stack §2: tabla
#: `historial_transicion_ticket`, AC-9).
CAMPOS_HISTORIAL: frozenset[str] = frozenset(
    {
        "historial_transicion_id",
        "ticket_id",
        "estado_origen_id",
        "estado_destino_id",
        "usuario_id",
        "fecha_transicion",
        "motivo",
    }
)

#: Detalle unico del 404 de ticket (inexistente y ajeno, ocultamiento D-8).
DETALLE_TICKET_NO_ENCONTRADO = "Ticket no encontrado"


# ---------------------------------------------------------------------------
# Guardas de la fase roja (patron de `_soporte_sede_011.py` de la 011)
# ---------------------------------------------------------------------------


def exigir_ruta(ruta: str, metodo: str) -> None:
    """Falla si la operacion aun no esta publicada en el contrato OpenAPI (T7).

    Sin esta guarda, una prueba que espera `403`/`404`-oculto pasaria por el
    motivo equivocado (ruta ausente en vez de autorizacion/ocultamiento).
    """
    operaciones = app.openapi().get("paths", {}).get(ruta, {})
    if metodo.lower() not in operaciones:
        pytest.fail(
            f"capacidad ausente (T9): {metodo.upper()} {ruta} no esta publicada "
            "en /openapi.json; la Feature 013 la cablea en T9."
        )


def exigir_operacion(metodo: str, ruta: str) -> None:
    """Falla si la operacion aun no esta declarada en la matriz central (T6)."""
    if (metodo.upper(), ruta) not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            f"capacidad ausente (T6): MATRIZ_PERMISOS no declara "
            f"{(metodo.upper(), ruta)}; la Feature 013 la agrega en T6."
        )


def exigir_capacidad_asociada(metodo: str, ruta: str) -> None:
    """Falla si la operacion aun no esta asociada a una capacidad (T6)."""
    from app.core import capacidades

    if capacidades.capacidad_de_operacion(metodo, ruta) is None:
        pytest.fail(
            f"capacidad ausente (T6): MAPA_OPERACION_CAPACIDAD no asocia "
            f"{(metodo.upper(), ruta)} a ninguna capacidad; la Feature 013 lo "
            "hace en T6."
        )


# ---------------------------------------------------------------------------
# Construccion del mundo
# ---------------------------------------------------------------------------


def instalar_catalogo_ciclo_vida(motor, nombres=None) -> dict[str, int]:
    """Reemplaza el catalogo de estados por los `nombres` pedidos.

    Por defecto instala el canonico de la 013 con `Anulado` al final del
    orden (es la quinta fila de la semilla, preservando el orden lineal de la
    004, D-4). Devuelve `{nombre exacto: id}`; las claves son los nombres tal
    cual, de modo que `Anulado` y `anulado` (casing) no colisionan.
    """
    if nombres is None:
        nombres = ("Pendiente", "EnRevision", "EnCurso", "Cerrado", "Anulado")
    db = sessionmaker(bind=motor)()
    try:
        db.query(EstadoTicket).delete()
        db.flush()
        ids: dict[str, int] = {}
        for nombre in nombres:
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            ids[nombre] = estado.estado_id
        db.commit()
        return ids
    finally:
        db.close()


def sembrar_mundo_013(motor, datos, *, nombres_estados=None, con_stock=True):
    """Catalogo de la 013 + sede del departamento sobre un padron existente.

    `datos` es `datos_base` o `dos_instituciones`. Devuelve `datos` ampliado
    con `estados` (`{nombre exacto: id}`), con `sede_id`. Si `con_stock`,
    siembra 50 unidades del producto base en la sede (precondicion de
    despacho).
    """
    sede = asegurar_sede_de_departamento(
        motor,
        datos,
        stocks={datos["producto_id"]: 50} if con_stock else None,
    )
    estados = instalar_catalogo_ciclo_vida(motor, nombres_estados)
    return {**datos, "estados": estados, "sede_id": sede["sede_id"]}


def sembrar_ticket(
    motor,
    datos: dict[str, Any],
    *,
    usuario_id: int | None = None,
    estado_id: int | None = None,
    institucion_id: str | None = None,
    sede_id: int | None = None,
    producto_id: int | None = None,
    cantidad: int = 3,
    asunto: str = "Ticket sembrado para el ciclo de vida 013",
) -> int:
    """Inserta un ticket con un detalle por ORM, sin pasar por el alta HTTP.

    Permite sembrar tickets en cualquier estado (incluido `Anulado` o
    `Cerrado`) y tickets "legados" sin fila de historial (AC-12). Devuelve el
    `ticket_id`.
    """
    institucion = institucion_id or datos["institucion_id"]
    if sede_id is None:
        sede_id = datos.get("sede_id")
    db = sessionmaker(bind=motor)()
    try:
        ticket = Ticket(
            usuario_id=(
                usuario_id
                if usuario_id is not None
                else datos["usuarios_inst01"]["Solicitante"]
            ),
            prioridad_id=datos["prioridad_id"],
            estado_id=(
                estado_id
                if estado_id is not None
                else datos["estados"]["Pendiente"]
            ),
            asunto=asunto,
            descripcion="Sembrado para las pruebas de la Feature 013.",
            institucion_id=institucion,
            sede_id=sede_id,
        )
        db.add(ticket)
        db.flush()
        db.add(
            DetalleTicket(
                ticket_id=ticket.ticket_id,
                producto_id=(
                    producto_id if producto_id is not None else datos["producto_id"]
                ),
                cantidad_solicitada=cantidad,
                cantidad_entregada=0,
                institucion_id=institucion,
            )
        )
        db.commit()
        return ticket.ticket_id
    finally:
        db.close()


def payload_alta(datos: dict[str, Any], estado_id: int, *, asunto=None) -> dict:
    """Payload valido de `POST /tickets/` sobre el catalogo del mundo 013."""
    return {
        "usuario_id": datos["usuarios_inst01"]["Solicitante"],
        "prioridad_id": datos["prioridad_id"],
        "estado_id": estado_id,
        "asunto": asunto or "Requerimiento de insumos para la 013",
        "descripcion": "Alta para las pruebas del ciclo de vida.",
        "detalles": [
            {"producto_id": datos["producto_id"], "cantidad_solicitada": 3}
        ],
    }


# ---------------------------------------------------------------------------
# Observacion de lo persistido
# ---------------------------------------------------------------------------


def leer_historial(cliente, ticket_id: int) -> list[dict]:
    """`GET /tickets/{id}/historial` como lo veria un cliente real."""
    respuesta = cliente.get(f"/api/v1/tickets/{ticket_id}/historial")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def abrir_ticket(cliente, ticket_id: int) -> dict:
    """Ticket tal como lo ve un cliente: por la lista de `GET /tickets/`."""
    respuesta = cliente.get("/api/v1/tickets/")
    assert respuesta.status_code == 200, respuesta.text
    return next(
        (t for t in respuesta.json() if t["ticket_id"] == ticket_id), None
    )


__all__ = [
    "CAMPOS_HISTORIAL",
    "CAPACIDADES_013",
    "DETALLE_TICKET_NO_ENCONTRADO",
    "OPERACIONES_013",
    "RUTA_DETALLE",
    "RUTA_EDICION",
    "RUTA_HISTORIAL",
    "RUTA_ANULACION",
    "RUTA_RECHAZO",
    "SIN_AUTENTICAR",
    "abrir_ticket",
    "asegurar_sede_de_departamento",
    "cliente_con_rol",
    "contar_en",
    "exigir_capacidad_asociada",
    "exigir_operacion",
    "exigir_ruta",
    "identidad",
    "instalar_catalogo_ciclo_vida",
    "leer_historial",
    "leer_stock_sede",
    "payload_alta",
    "sembrar_mundo_013",
    "sembrar_ticket",
    "sesion",
    "dependencies",
    "app",
]
