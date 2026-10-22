"""T2 (Feature 013): autorizacion, matriz, OpenAPI y gating (AC-17…AC-19).

Seam bajo prueba: la **matriz central** (`app.core.permisos.MATRIZ_PERMISOS`,
transcrita a mano desde la spec, nunca leida como fuente), el contrato
`/openapi.json` y la interfaz HTTP del `app` real.

La 013 agrega cinco operaciones aditivas (AC-17): la matriz pasa de 44 a 49
sin modificar ninguna fila previa; Superadmin obtiene 403 en toda escritura y
conserva lectura de detalle/historial; un ticket ajeno responde 404 identico
al inexistente (AC-18); las operaciones quedan sujetas al gating de
capacidades de la 012 (kanban x2, tickets x3; plan §2).

Fase ROJA de TDD: hoy la matriz no declara las cinco operaciones, las rutas no
estan publicadas y el mapa de capacidades no las asocia; los tests fallan por
esas ausencias (con `pytest.fail` explicito o con el 404 del router), nunca
por imports ni sintaxis.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.main import app
from app.models import (
    CAPACIDADES,
    FuncionInstitucion,
    InstitucionControl,
    MapaUsuarioEsquema,
    Ticket,
    VersionEsquema,
)

from .test_permisos_012 import MATRIZ_012
from ._soporte_ciclo_vida_013 import (
    CAPACIDADES_013,
    DETALLE_TICKET_NO_ENCONTRADO,
    OPERACIONES_013,
    RUTA_DETALLE,
    RUTA_EDICION,
    RUTA_HISTORIAL,
    RUTA_ANULACION,
    RUTA_RECHAZO,
    abrir_ticket,
    cliente_con_rol,
    exigir_operacion,
    exigir_ruta,
    leer_historial,
    sembrar_mundo_013,
    sembrar_ticket,
    sesion,
)

#: Campos que el detalle del ticket debe exponer (cabecera + fechas + items).
CAMPOS_DETALLE: frozenset[str] = frozenset(
    {
        "ticket_id",
        "usuario_id",
        "prioridad_id",
        "estado_id",
        "asunto",
        "descripcion",
        "fecha_creacion",
        "fecha_cierre",
        "detalles",
    }
)

#: Metodos que FastAPI publica en `/openapi.json`.
_METODOS_OPENAPI = {"get", "put", "post", "delete", "patch"}

#: Prefijo del contrato de negocio. `GET /` y `GET /health` son rutas de
#: infraestructura fuera de `/api/v1` (no son operaciones de la matriz): hoy
#: el esquema publica 46 pares metodo+ruta (44 de matriz + 2 de infra), y con
#: la 013 pasara a 51 (49 de matriz + 2 de infra). El conteo del AC-17 es sobre
#: las operaciones del contrato v1.
PREFIJO_CONTRATO = "/api/v1/"

_CORREO_GATING = "gating013.inst01@compustock.cl"


@pytest.fixture
def datos_013(motor, dos_instituciones):
    return sembrar_mundo_013(motor, dos_instituciones)


def _cliente_administrador(motor, datos, correo=None):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuario_id"],
        **({"correo": correo} if correo else {}),
    )


def _cliente_solicitante(motor, datos):
    return cliente_con_rol(
        motor,
        "Solicitante",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Solicitante"],
    )


def _cliente_bodeguero(motor, datos):
    return cliente_con_rol(
        motor,
        "Bodeguero",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Bodeguero"],
    )


def _cliente_superadmin(motor, datos):
    return cliente_con_rol(
        motor,
        "Superadmin",
        departamento_id=datos["departamento_id"],
        usuario_id=datos["usuarios_inst01"]["Superadmin"],
    )


def _cliente_admin_ajeno(motor, datos):
    return cliente_con_rol(
        motor,
        "Administrador",
        departamento_id=datos["departamento_ajeno_id"],
        usuario_id=datos["usuarios_inst02"]["Administrador"],
    )


# ---------------------------------------------------------------------------
# AC-17: matriz central aditiva (44 -> 49)
# ---------------------------------------------------------------------------


def test_matriz_declara_las_cinco_operaciones_con_los_roles_exactos_ac_17():
    """AC-17: los roles de cada operacion nueva son exactamente los de la spec."""
    for clave, roles in OPERACIONES_013.items():
        obtenidos = permisos.MATRIZ_PERMISOS.get(clave)
        if obtenidos is None:
            pytest.fail(
                f"capacidad ausente (T6): MATRIZ_PERMISOS no declara {clave}; "
                "la Feature 013 la agrega en T6 con los roles del AC-17."
            )
        assert set(obtenidos) == roles, (clave, sorted(obtenidos), sorted(roles))


#: Feature 017 (D-9/AC-15): lecturas de negocio retiradas al Superadmin. La
#: 013 las conservaba para los cuatro roles; la 017 solo retira ese rol.
RETIRADAS_017: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/dashboard/"),
        ("GET", "/api/v1/tickets/catalogos"),
        ("GET", "/api/v1/tickets/"),
        ("GET", "/api/v1/tickets/{ticket_id}"),
        ("GET", "/api/v1/tickets/{ticket_id}/historial"),
        ("GET", "/api/v1/inventario/movimientos"),
        ("GET", "/api/v1/inventario/categorias"),
        ("GET", "/api/v1/inventario/categorias/{categoria_id}"),
        ("GET", "/api/v1/inventario/productos"),
        ("GET", "/api/v1/inventario/productos/{producto_id}"),
        ("GET", "/api/v1/inventario/existencias"),
        ("GET", "/api/v1/inventario/stock"),
    }
)


def test_matriz_conserva_las_44_operaciones_previas_intactas_ac_17():
    """AC-17: la 013 no retira ni relaja ninguna de las 44 filas vigentes.

    Feature 017: las 11 lecturas de D-9 ajustan solo el rol Superadmin; los
    roles institucionales conservan exactamente el conjunto de la 012.
    """
    assert len(MATRIZ_012) == 44
    for clave, roles in MATRIZ_012.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion {clave} desaparecio de la matriz"
        if clave in RETIRADAS_017:
            assert set(actual) == set(roles) - {"Superadmin"}, clave
        else:
            assert set(actual) == roles, clave


def test_matriz_no_baja_de_las_55_operaciones_tras_017():
    """AC-17/plan §2: 44 previas + 5 nuevas de la 013 + 6 de la 017.

    La 014 y las features posteriores solo agregan filas: el criterio que la 013
    protege es que la matriz no pierda ninguna de las 55 vigentes, no que el
    total congele ese numero.
    """
    totales = len(permisos.MATRIZ_PERMISOS)
    assert totales >= 55, (
        "la matriz no puede bajar de las 55 operaciones vigentes tras la 017 "
        f"(49 de la 013 + 5 de control 017 + el reenvio ordinario); tiene {totales}"
    )


def test_superadmin_no_obtiene_ninguna_escritura_nueva_ac_17():
    """AC-17/D-8: Superadmin queda fuera de toda escritura de la 013."""
    escrituras = ("POST", "PUT")
    for (metodo, ruta), roles in OPERACIONES_013.items():
        if metodo in escrituras:
            assert "Superadmin" not in roles, (metodo, ruta)
            assert "Superadmin" not in permisos.MATRIZ_PERMISOS[(metodo, ruta)], (
                metodo,
                ruta,
            )


# ---------------------------------------------------------------------------
# AC-17: contrato OpenAPI (49 operaciones y respuestas documentadas)
# ---------------------------------------------------------------------------


def test_openapi_publica_las_cinco_operaciones_ac_17(cliente):
    """AC-17: las cinco rutas nuevas estan publicadas en `/openapi.json`."""
    contrato = cliente.get("/openapi.json").json()
    for clave in OPERACIONES_013:
        metodo, ruta = clave
        operaciones = contrato["paths"].get(ruta, {})
        if metodo.lower() not in operaciones:
            pytest.fail(
                f"capacidad ausente (T9): {metodo} {ruta} no esta publicada en "
                "/openapi.json; la Feature 013 la cablea en T9."
            )


def test_openapi_no_baja_de_las_55_operaciones_tras_017(cliente):
    """AC-17: el contrato v1 publica al menos las 55 operaciones de la 017.

    Las features posteriores agregan operaciones de forma aditiva (la 014 suma
    cinco); el contrato no puede quedarse por debajo de la fase de la 013/017.
    """
    contrato = cliente.get("/openapi.json").json()
    total = sum(
        1
        for ruta, operaciones in contrato["paths"].items()
        if ruta.startswith(PREFIJO_CONTRATO)
        for metodo in operaciones
        if metodo in _METODOS_OPENAPI
    )
    assert total >= 55, (
        "/openapi.json no puede publicar menos de las 55 operaciones del contrato "
        f"v1 vigentes tras la 017; publica {total}"
    )


@pytest.mark.parametrize("clave", sorted(OPERACIONES_013))
def test_openapi_documenta_401_403_404_en_las_operaciones_nuevas_ac_17(
    cliente, clave
):
    """AC-17: toda operacion nueva documenta 401, 403 y 404 (patron 007/008)."""
    exigir_operacion(*clave)
    metodo, ruta = clave
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"][ruta][metodo.lower()]
    respuestas = set(operacion.get("responses", {}))
    assert {"401", "403", "404"} <= respuestas, (clave, sorted(respuestas))


@pytest.mark.parametrize(
    "clave",
    [("POST", RUTA_ANULACION), ("POST", RUTA_RECHAZO), ("PUT", RUTA_EDICION)],
)
def test_openapi_documenta_409_y_422_en_las_escrituras_ac_17(cliente, clave):
    """AC-17: anulacion/rechazo/edicion documentan 409 y 422 (spec §6)."""
    exigir_operacion(*clave)
    metodo, ruta = clave
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"][ruta][metodo.lower()]
    respuestas = set(operacion.get("responses", {}))
    descripcion = operacion.get("description", "")
    assert "409" in respuestas or "409" in descripcion, (
        f"falta documentar el 409 en {clave}: {sorted(respuestas)}"
    )
    assert "422" in respuestas or "422" in descripcion, (
        f"falta documentar el 422 en {clave}: {sorted(respuestas)}"
    )


# ---------------------------------------------------------------------------
# AC-18: ocultamiento 404 identico
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operacion,fabrica",
    [
        ("anulacion", "solicitante"),
        ("rechazo", "admin_ajeno"),
    ],
    ids=["anulacion_del_solicitante", "rechazo_de_otra_institucion"],
)
def test_operar_ticket_ajeno_responde_404_identico_ac_18(
    motor, datos_013, operacion, fabrica
):
    """AC-18: una escritura autorizada sobre un ticket ajeno oculta con 404.

    `anulacion` se ejerce con el Solicitante (autorizado por la matriz, D-7:
    solo los suyos) sobre un ticket de Ana; `rechazo`, con el Administrador de
    otra institucion, que si esta autorizado para rechazar pero el ticket queda
    fuera de su alcance. El Solicitante **no puede rechazar ningun** ticket, ni
    siquiera el suyo (AC-17: matriz exacta; su 403 de rol sin permiso lo fija
    `test_rol_sin_permiso_de_escritura_recibe_403_ac_17` en este mismo modulo),
    de modo que su denegacion de rechazo es 403 de matriz —independiente del
    ticket, sin revelar existencia— y no un 404 de ocultamiento.
    """
    ticket_id = sembrar_ticket(
        motor, datos_013,
        usuario_id=datos_013["usuario_id"],  # de Ana, no del Solicitante
    )
    fabricas = {
        "solicitante": _cliente_solicitante,
        "admin_ajeno": _cliente_admin_ajeno,
    }

    with fabricas[fabrica](motor, datos_013) as cliente:
        ajeno = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{operacion}",
            json={"motivo": "Motivo valido sobre un ticket ajeno"},
        )
        inexistente = cliente.post(
            f"/api/v1/tickets/999999/{operacion}",
            json={"motivo": "Motivo valido sobre un ticket inexistente"},
        )

        assert ajeno.status_code == 404, ajeno.text
        assert ajeno.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO
        assert inexistente.json()["detail"] == ajeno.json()["detail"], (
            "el 404 del ajeno debe ser indistinguible del del inexistente"
        )


@pytest.mark.parametrize("metodo_ruta", [("get", "detalle"), ("get", "historial")])
def test_leer_ajeno_responde_404_identico_ac_18(motor, datos_013, metodo_ruta):
    """AC-18: detalle e historial de un ticket ajeno ocultan con 404 identico."""
    _, lectura = metodo_ruta
    ticket_id = sembrar_ticket(motor, datos_013)

    with _cliente_admin_ajeno(motor, datos_013) as cliente:
        if lectura == "detalle":
            ajeno = cliente.get(f"/api/v1/tickets/{ticket_id}")
            inexistente = cliente.get("/api/v1/tickets/999999")
        else:
            ajeno = cliente.get(f"/api/v1/tickets/{ticket_id}/historial")
            inexistente = cliente.get("/api/v1/tickets/999999/historial")

        assert ajeno.status_code == 404, ajeno.text
        assert ajeno.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO
        assert inexistente.json()["detail"] == ajeno.json()["detail"]


@pytest.mark.parametrize(
    "rol,no_rol",
    [("Solicitante", "rechazo"), ("Bodeguero", "anulacion")],
    ids=["solicitante_no_rechaza", "bodeguero_no_anula"],
)
def test_rol_sin_permiso_de_escritura_recibe_403_ac_17(motor, datos_013, rol, no_rol):
    """AC-17/D-7: los conjuntos de roles de anulacion y rechazo son distintos."""
    ticket_id = sembrar_ticket(motor, datos_013)
    fabrica = {
        "Solicitante": _cliente_solicitante,
        "Bodeguero": _cliente_bodeguero,
    }[rol]

    with fabrica(motor, datos_013) as cliente:
        respuesta = cliente.post(
            f"/api/v1/tickets/{ticket_id}/{no_rol}",
            json={"motivo": "Este rol no puede operar esta accion"},
        )

        assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# AC-19: lectura de detalle e historial por rol
# ---------------------------------------------------------------------------


def test_superadmin_obtiene_403_en_toda_escritura_nueva_ac_17(motor, datos_013):
    """AC-17/D-8: Superadmin no opera tickets: 403 en anulacion, rechazo y edicion."""
    ticket_id = sembrar_ticket(motor, datos_013)

    with _cliente_superadmin(motor, datos_013) as cliente:
        anulacion = cliente.post(
            f"/api/v1/tickets/{ticket_id}/anulacion", json={"motivo": "Escritura"}
        )
        rechazo = cliente.post(
            f"/api/v1/tickets/{ticket_id}/rechazo", json={"motivo": "Escritura"}
        )
        edicion = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json={
                "asunto": "Escritura prohibida del Superadmin",
                "descripcion": "No debe pasar.",
                "prioridad_id": datos_013["prioridad_id"],
                "detalles": [
                    {"producto_id": datos_013["producto_id"], "cantidad_solicitada": 1}
                ],
            },
        )

        for respuesta in (anulacion, rechazo, edicion):
            assert respuesta.status_code == 403, respuesta.text
        # Feature 017: el Superadmin ya no puede leer `GET /tickets/`; la
        # ausencia de mutacion se observa por ORM.
        with sesion(motor) as db:
            assert db.get(Ticket, ticket_id).estado_id == (
                datos_013["estados"]["Pendiente"]
            ), "el 403 no puede mutar el ticket"


def test_superadmin_lee_detalle_e_historial_ac_19(motor, datos_013):
    """Feature 017 (D-9/AC-15): el detalle y el historial ya no son del Superadmin.

    La 013 AC-19 concedia esta lectura global; la 017 la retira y responde 403
    sin datos. Los roles institucionales conservan su lectura (AC-19).
    """
    ticket_id = sembrar_ticket(motor, datos_013)

    with _cliente_superadmin(motor, datos_013) as cliente:
        detalle = cliente.get(f"/api/v1/tickets/{ticket_id}")
        assert detalle.status_code == 403, detalle.text
        assert detalle.json() == {
            "detail": "Permiso insuficiente para la operacion"
        }

        historial = cliente.get(f"/api/v1/tickets/{ticket_id}/historial")
        assert historial.status_code == 403, historial.text
        assert historial.json() == {
            "detail": "Permiso insuficiente para la operacion"
        }


def test_solicitante_lee_su_detalle_y_no_el_ajeno_ac_19(motor, datos_013):
    """AC-19: el Solicitante lee los suyos; el ajeno responde 404 oculto."""
    propio = sembrar_ticket(
        motor, datos_013,
        usuario_id=datos_013["usuarios_inst01"]["Solicitante"],
    )
    ajeno = sembrar_ticket(motor, datos_013, usuario_id=datos_013["usuario_id"])

    with _cliente_solicitante(motor, datos_013) as cliente:
        respuesta_propio = cliente.get(f"/api/v1/tickets/{propio}")
        assert respuesta_propio.status_code == 200, respuesta_propio.text
        assert CAMPOS_DETALLE <= set(respuesta_propio.json())
        assert respuesta_propio.json()["detalles"], (
            "el detalle debe traer los items con sus cantidades"
        )

        respuesta_ajeno = cliente.get(f"/api/v1/tickets/{ajeno}")
        assert respuesta_ajeno.status_code == 404
        assert respuesta_ajeno.json()["detail"] == DETALLE_TICKET_NO_ENCONTRADO


@pytest.mark.parametrize("fabrica", ["administrador", "bodeguero"])
def test_administrador_y_bodeguero_leen_el_detalle_de_su_institucion_ac_19(
    motor, datos_013, fabrica
):
    """AC-19: Administrador y Bodeguero leen el detalle de su institucion."""
    ticket_id = sembrar_ticket(motor, datos_013)
    fabricas = {
        "administrador": _cliente_administrador,
        "bodeguero": _cliente_bodeguero,
    }

    with fabricas[fabrica](motor, datos_013) as cliente:
        detalle = cliente.get(f"/api/v1/tickets/{ticket_id}")
        assert detalle.status_code == 200, detalle.text
        assert CAMPOS_DETALLE <= set(detalle.json())


# ---------------------------------------------------------------------------
# AC-17 (gating 012): capacidades apagadas -> 403 sin mutacion
# ---------------------------------------------------------------------------


def _sembrar_contexto_capacidades(motor, datos, capacidades_apagadas=frozenset()):
    """Control coherente para que el correo del gating resuelva a INST01.

    Mismo patron que `test_gating_capacidades_endpoints_012.py`: institucion
    canonica activa, mapa `correo -> esquema` activo, version objetivo y las
    seis capacidades con las apagadas explicitas.
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
        if db.get(MapaUsuarioEsquema, _CORREO_GATING) is None:
            db.add(
                MapaUsuarioEsquema(
                    correo=_CORREO_GATING,
                    institucion_id=institucion_id,
                    nombre_esquema="tenant_inst01",
                    activo=True,
                )
            )
            db.flush()
        if db.execute(select(VersionEsquema)).scalars().first() is None:
            db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        for funcion in CAPACIDADES:
            habilitada = funcion not in capacidades_apagadas
            db.add(
                FuncionInstitucion(
                    institucion_id=institucion_id,
                    funcion=funcion,
                    habilitada=habilitada,
                )
            )
        db.commit()


def test_capacidad_kanban_apagada_bloquea_anulacion_y_rechazo_sin_mutar_ac_17(
    motor, datos_013
):
    """AC-17/plan §2: anulacion y rechazo quedan gated bajo `kanban`."""
    for clave in (("POST", RUTA_ANULACION), ("POST", RUTA_RECHAZO)):
        from app.core import capacidades as mapa_capacidades

        assert mapa_capacidades.capacidad_de_operacion(*clave) == "kanban", (
            f"{clave} debe quedar asociada a la capacidad `kanban` (plan §2)"
        )
    _sembrar_contexto_capacidades(motor, datos_013, {"kanban"})
    ticket_id = sembrar_ticket(motor, datos_013)

    with _cliente_administrador(motor, datos_013, correo=_CORREO_GATING) as cliente:
        for operacion in ("anulacion", "rechazo"):
            respuesta = cliente.post(
                f"/api/v1/tickets/{ticket_id}/{operacion}",
                json={"motivo": "La capacidad kanban esta apagada"},
            )
            assert respuesta.status_code == 403, (operacion, respuesta.text)

        assert abrir_ticket(cliente, ticket_id)["estado_id"] == (
            datos_013["estados"]["Pendiente"]
        ), "el 403 de gating no puede mutar el ticket"
        exigir_ruta(RUTA_HISTORIAL, "GET")
        assert leer_historial(cliente, ticket_id) == []


def test_capacidad_tickets_apagada_bloquea_edicion_detalle_e_historial_ac_17(
    motor, datos_013
):
    """AC-17/plan §2: edicion, detalle e historial quedan gated bajo `tickets`."""
    for clave in (
        ("PUT", RUTA_EDICION),
        ("GET", RUTA_DETALLE),
        ("GET", RUTA_HISTORIAL),
    ):
        from app.core import capacidades as mapa_capacidades

        assert mapa_capacidades.capacidad_de_operacion(*clave) == "tickets", (
            f"{clave} debe quedar asociada a la capacidad `tickets` (plan §2)"
        )
    _sembrar_contexto_capacidades(motor, datos_013, {"tickets"})
    ticket_id = sembrar_ticket(motor, datos_013)

    with _cliente_administrador(motor, datos_013, correo=_CORREO_GATING) as cliente:
        edicion = cliente.put(
            f"/api/v1/tickets/{ticket_id}",
            json={
                "asunto": "Edicion bloqueada por capacidad",
                "descripcion": "No debe pasar.",
                "prioridad_id": datos_013["prioridad_id"],
                "detalles": [
                    {"producto_id": datos_013["producto_id"], "cantidad_solicitada": 1}
                ],
            },
        )
        detalle = cliente.get(f"/api/v1/tickets/{ticket_id}")
        historial = cliente.get(f"/api/v1/tickets/{ticket_id}/historial")

        for respuesta in (edicion, detalle, historial):
            assert respuesta.status_code == 403, respuesta.text

        # Sin mutacion observable: `GET /tickets/` tambien esta gated bajo la
        # capacidad `tickets`, asi que la cabecera se observa por ORM.
        with sesion(motor) as db:
            assert db.get(Ticket, ticket_id).asunto == (
                "Ticket sembrado para el ciclo de vida 013"
            ), "el 403 de gating no puede mutar la cabecera"


def test_historial_y_detalle_comparten_capacidad_tickets_con_el_alta_ac_17():
    """Coherencia 013↔012: las tres operaciones `tickets` nuevas existen en el mapa."""
    from app.core import capacidades as mapa_capacidades

    for clave, capacidad in CAPACIDADES_013.items():
        if capacidad == "tickets":
            assert mapa_capacidades.capacidad_de_operacion(*clave) == capacidad, clave
