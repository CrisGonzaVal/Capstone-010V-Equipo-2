"""T4 (Feature 007): propiedad, atribucion y ambito institucional en tickets.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`). Se siembran
**dos instituciones** (INST01 propia y INST02 ajena) con usuarios y tickets de cada
una y se observa, por rol, que:

  * `GET /tickets/`: el Solicitante ve solo sus tickets; Administrador/Bodeguero,
    solo los de su institucion; Superadmin, todos (D-3, AC-6, AC-8).
  * `GET /tickets/catalogos`: `solicitantes` se acota por rol (Solicitante solo su
    identidad; Administrador/Bodeguero su institucion; Superadmin global), mientras
    productos y `stock_total` siguen siendo globales (D-3, AC-9).
  * En una operacion permitida sobre un ticket de otra institucion (PATCH estado,
    despacho) el rol limitado recibe **404**, igual que para un id inexistente, sin
    mutar datos (D-5, AC-6).
  * `POST /tickets/`: el Solicitante queda atribuido a su identidad aunque envie
    otro `usuario_id`; Administrador/Bodeguero conservan `usuario_id` obligatorio y
    solo pueden elegir un solicitante de su institucion (D-3, AC-6).
  * El despacho del ticket propio sigue siendo una transaccion ACID (Feature 005).

Fuera de alcance de T4: el 403 de rol (e.g. Solicitante en PATCH/despacho) ya lo fija
T2; aqui no se duplica.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import (
    Departamento,
    DetalleTicket,
    EstadoTicket,
    Institucion,
    Inventario,
    Producto,
    Rol,
    Ticket,
    Usuario,
)
from app.services.auth_service import IdentidadAutenticada

RUTA_TICKETS = "/api/v1/tickets/"
RUTA_CATALOGOS = "/api/v1/tickets/catalogos"
RUTA_STOCK = "/api/v1/inventario/stock"


# ---------------------------------------------------------------------------
# Sembrado: INST01 (datos_base) + INST02 completa, con tickets de cada una
# ---------------------------------------------------------------------------


@pytest.fixture
def ambito_tickets(motor, datos_base):
    """`datos_base` (INST01) + INST02 con un solicitante ajeno y tickets cruzados.

    INST01 (propia): departamento "Operaciones", solicitante persistido y tres
    tickets suyos (Pendiente, EnRevision, EnCurso).

    INST02 (ajena): institucion, departamento "Bodega Sur", un usuario persistido,
    un producto del catalogo compartido con una sede en cada institucion (para
    demostrar el `stock_total` global de 47) y los tres tickets equivalentes pero
    ajenos. El producto de los tickets conserva una sola fila de inventario para
    no romper la regla de despacho de Feature 005 (exactamente una por producto).
    """
    db = sessionmaker(bind=motor)()
    try:
        # Estados canonicos del flujo (mismo catalogo que usa la 004/005).
        db.query(EstadoTicket).delete()
        db.flush()
        estados: dict[str, int] = {}
        for nombre in ("Pendiente", "EnRevision", "EnCurso", "Cerrado"):
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            estados[nombre] = estado.estado_id

        # Solicitante propio (INST01), persistido para que la atribucion lo acepte.
        solicitante = Usuario(
            nombre="Sofi",
            apellido="Solicitante",
            correo="sofi.solicitante@compustock.cl",
            departamento_id=datos_base["departamento_id"],
            rol_id=datos_base["rol_id"],
        )
        db.add(solicitante)
        db.flush()

        # Institucion ajena INST02.
        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
            rut="2-9",
            direccion="Otra Calle 456",
        )
        db.add(institucion_ajena)
        db.flush()

        departamento_ajeno = Departamento(
            nombre_dep="Bodega Sur",
            descripcion="Deposito de la institucion ajena",
            institucion_id=institucion_ajena.institucion_id,
        )
        db.add(departamento_ajeno)
        db.flush()

        usuario_ajeno = Usuario(
            nombre="Beto",
            apellido="Ajeno",
            correo="beto.ajeno.tickets@compustock.cl",
            departamento_id=departamento_ajeno.departamento_id,
            rol_id=datos_base["rol_id"],
        )
        db.add(usuario_ajeno)
        db.flush()

        # Producto del catalogo compartido con una sede en cada institucion: sirve
        # para demostrar que el `stock_total` del catalogo sigue siendo global.
        # (El producto de los tickets se deja con una sola fila de inventario para
        # no romper la regla de despacho de Feature 005: exactamente una por
        # producto.)
        producto_compartido = Producto(
            nombre="Insumo Compartido",
            descripcion="Producto con existencias en ambas instituciones",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
        )
        db.add(producto_compartido)
        db.flush()
        db.add(
            Inventario(
                stock_actual=40,
                ubicacion="Operaciones - C1",
                departamento_id=datos_base["departamento_id"],
                producto_id=producto_compartido.producto_id,
            )
        )
        db.add(
            Inventario(
                stock_actual=7,
                ubicacion="Bodega Sur - C1",
                departamento_id=departamento_ajeno.departamento_id,
                producto_id=producto_compartido.producto_id,
            )
        )
        db.flush()

        def nuevo_ticket(usuario_id: int, estado_id: int, asunto: str) -> int:
            ticket = Ticket(
                usuario_id=usuario_id,
                prioridad_id=datos_base["prioridad_id"],
                estado_id=estado_id,
                asunto=asunto,
                descripcion="Sembrado para pruebas de alcance.",
            )
            db.add(ticket)
            db.flush()
            db.add(
                DetalleTicket(
                    ticket_id=ticket.ticket_id,
                    producto_id=datos_base["producto_id"],
                    cantidad_solicitada=1,
                    cantidad_entregada=0,
                )
            )
            return ticket.ticket_id

        ids = {
            **datos_base,
            "inst_propia": "INST01",
            "inst_ajena": "INST02",
            "solicitante_id": solicitante.usuario_id,
            "dep_ajeno_id": departamento_ajeno.departamento_id,
            "usuario_ajeno_id": usuario_ajeno.usuario_id,
            "producto_compartido_id": producto_compartido.producto_id,
            "estado_pendiente_id": estados["Pendiente"],
            "estado_en_revision_id": estados["EnRevision"],
            "estado_en_curso_id": estados["EnCurso"],
            "estado_cerrado_id": estados["Cerrado"],
            "ticket_propio_id": nuevo_ticket(
                solicitante.usuario_id, estados["Pendiente"], "Propio Pendiente"
            ),
            "ticket_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id, estados["Pendiente"], "Ajeno Pendiente"
            ),
            "ticket_estado_propio_id": nuevo_ticket(
                solicitante.usuario_id, estados["EnRevision"], "Propio EnRevision"
            ),
            "ticket_estado_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id, estados["EnRevision"], "Ajeno EnRevision"
            ),
            "ticket_despacho_propio_id": nuevo_ticket(
                solicitante.usuario_id, estados["EnCurso"], "Propio EnCurso"
            ),
            "ticket_despacho_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id, estados["EnCurso"], "Ajeno EnCurso"
            ),
        }
        db.commit()
        return ids
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers: identidad por rol, cliente real y lecturas por HTTP
# ---------------------------------------------------------------------------


def _identidad(rol: str, departamento_id, usuario_id: int) -> IdentidadAutenticada:
    """Identidad autenticada con rol, departamento e id de usuario dados.

    El usuario no se persiste: el filtro institucional lee `departamento_id`, la
    propiedad lee `usuario_id` y la autorizacion solo lee `rol.nombre_rol`.
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Alcance",
        correo=f"sonda.{rol.lower()}@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub=f"sub-{rol.lower()}")


@contextmanager
def _cliente(motor, rol: str, departamento_id, usuario_id: int = 9999):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = (
        lambda: _identidad(rol, departamento_id, usuario_id)
    )
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _ticket(coleccion, ticket_id: int) -> dict:
    return next(t for t in coleccion if t["ticket_id"] == ticket_id)


def _ids(coleccion) -> set[int]:
    return {t["ticket_id"] for t in coleccion}


def _stock(cliente, inventario_id: int) -> int:
    respuesta = cliente.get(RUTA_STOCK)
    assert respuesta.status_code == 200, respuesta.text
    return next(
        i for i in respuesta.json() if i["inventario_id"] == inventario_id
    )["stock_actual"]


def _payload(datos: dict, usuario_id: int) -> dict:
    return {
        "usuario_id": usuario_id,
        "prioridad_id": datos["prioridad_id"],
        "estado_id": datos["estado_pendiente_id"],
        "asunto": "Alta de ticket en pruebas de alcance",
        "descripcion": "Atribucion y ambito de tickets.",
        "detalles": [{"producto_id": datos["producto_id"], "cantidad_solicitada": 1}],
    }


# ---------------------------------------------------------------------------
# Listado GET /tickets/: propiedad y ambito institucional
# ---------------------------------------------------------------------------


def test_solicitante_lista_solo_sus_tickets(motor, ambito_tickets):
    with _cliente(
        motor, "Solicitante", ambito_tickets["departamento_id"], ambito_tickets["solicitante_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_TICKETS)
    assert respuesta.status_code == 200, respuesta.text

    assert _ids(respuesta.json()) == {
        ambito_tickets["ticket_propio_id"],
        ambito_tickets["ticket_estado_propio_id"],
        ambito_tickets["ticket_despacho_propio_id"],
    }


def test_administrador_lista_solo_su_institucion(motor, ambito_tickets):
    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_TICKETS)
    assert respuesta.status_code == 200, respuesta.text

    ids = _ids(respuesta.json())
    assert ambito_tickets["ticket_propio_id"] in ids
    assert ambito_tickets["ticket_ajeno_id"] not in ids
    assert ambito_tickets["ticket_estado_ajeno_id"] not in ids
    assert ambito_tickets["ticket_despacho_ajeno_id"] not in ids


def test_bodeguero_lista_solo_su_institucion(motor, ambito_tickets):
    with _cliente(motor, "Bodeguero", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_TICKETS)
    assert respuesta.status_code == 200, respuesta.text

    ids = _ids(respuesta.json())
    assert ambito_tickets["ticket_propio_id"] in ids
    assert ambito_tickets["ticket_ajeno_id"] not in ids


def test_superadmin_lista_global(motor, ambito_tickets):
    with _cliente(motor, "Superadmin", None) as cliente:
        respuesta = cliente.get(RUTA_TICKETS)
    assert respuesta.status_code == 200, respuesta.text

    ids = _ids(respuesta.json())
    assert {
        ambito_tickets["ticket_propio_id"],
        ambito_tickets["ticket_ajeno_id"],
    } <= ids


# ---------------------------------------------------------------------------
# Catalogo GET /tickets/catalogos: solicitantes acotados, stock global
# ---------------------------------------------------------------------------


def test_catalogo_solicitante_solo_su_identidad(motor, ambito_tickets):
    with _cliente(
        motor, "Solicitante", ambito_tickets["departamento_id"], ambito_tickets["solicitante_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    solicitantes = {s["usuario_id"] for s in respuesta.json()["solicitantes"]}
    assert solicitantes == {ambito_tickets["solicitante_id"]}


def test_catalogo_administrador_solo_su_institucion(motor, ambito_tickets):
    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    solicitantes = {s["usuario_id"] for s in respuesta.json()["solicitantes"]}
    assert ambito_tickets["solicitante_id"] in solicitantes
    assert ambito_tickets["usuario_ajeno_id"] not in solicitantes


def test_catalogo_superadmin_es_global(motor, ambito_tickets):
    with _cliente(motor, "Superadmin", None) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    solicitantes = {s["usuario_id"] for s in respuesta.json()["solicitantes"]}
    assert {
        ambito_tickets["solicitante_id"],
        ambito_tickets["usuario_ajeno_id"],
    } <= solicitantes


def test_catalogo_productos_y_stock_siguen_globales(motor, ambito_tickets):
    """El `stock_total` del catalogo agrega todas las sedes, para cualquier rol."""
    with _cliente(
        motor, "Solicitante", ambito_tickets["departamento_id"], ambito_tickets["solicitante_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    producto = next(
        p
        for p in respuesta.json()["productos"]
        if p["producto_id"] == ambito_tickets["producto_compartido_id"]
    )
    assert producto["stock_total"] == 47


# ---------------------------------------------------------------------------
# Mutacion por id: ticket ajeno oculto como 404, sin mutar
# ---------------------------------------------------------------------------


def test_administrador_patch_ticket_ajeno_404_sin_mutar(motor, ambito_tickets):
    with _cliente(motor, "Superadmin", None) as supervisor:
        antes = _ticket(
            supervisor.get(RUTA_TICKETS).json(), ambito_tickets["ticket_estado_ajeno_id"]
        )["estado_id"]

    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_estado_ajeno_id']}/estado",
            json={"estado_id": ambito_tickets["estado_en_curso_id"]},
        )

    with _cliente(motor, "Superadmin", None) as supervisor:
        despues = _ticket(
            supervisor.get(RUTA_TICKETS).json(), ambito_tickets["ticket_estado_ajeno_id"]
        )["estado_id"]

    assert respuesta.status_code == 404, respuesta.text
    assert despues == antes


def test_administrador_patch_ticket_inexistente_404(motor, ambito_tickets):
    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}999999/estado",
            json={"estado_id": ambito_tickets["estado_en_curso_id"]},
        )
    assert respuesta.status_code == 404, respuesta.text


def test_administrador_patch_ticket_propio_200(motor, ambito_tickets):
    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_estado_propio_id']}/estado",
            json={"estado_id": ambito_tickets["estado_en_curso_id"]},
        )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == ambito_tickets["estado_en_curso_id"]


def test_bodeguero_despacho_ticket_ajeno_404_sin_mutar(motor, ambito_tickets):
    with _cliente(motor, "Superadmin", None) as supervisor:
        antes = _ticket(
            supervisor.get(RUTA_TICKETS).json(), ambito_tickets["ticket_despacho_ajeno_id"]
        )["estado_id"]

    with _cliente(motor, "Bodeguero", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_despacho_ajeno_id']}/despacho",
            json={"usuario_id": ambito_tickets["usuario_id"]},
        )

    with _cliente(motor, "Superadmin", None) as supervisor:
        despues = _ticket(
            supervisor.get(RUTA_TICKETS).json(), ambito_tickets["ticket_despacho_ajeno_id"]
        )["estado_id"]

    assert respuesta.status_code == 404, respuesta.text
    assert despues == antes


def test_bodeguero_despacho_ticket_inexistente_404(motor, ambito_tickets):
    with _cliente(motor, "Bodeguero", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}999999/despacho",
            json={"usuario_id": ambito_tickets["usuario_id"]},
        )
    assert respuesta.status_code == 404, respuesta.text


def test_bodeguero_despacho_propio_200_sigue_transaccional(motor, ambito_tickets):
    """El despacho del ticket propio no se rompe y sigue rebajando stock."""
    with _cliente(motor, "Bodeguero", ambito_tickets["departamento_id"]) as cliente:
        stock_antes = _stock(cliente, ambito_tickets["inventario_id"])
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_despacho_propio_id']}/despacho",
            json={"usuario_id": ambito_tickets["usuario_id"]},
        )
        stock_despues = _stock(cliente, ambito_tickets["inventario_id"])
        ticket = _ticket(
            cliente.get(RUTA_TICKETS).json(), ambito_tickets["ticket_despacho_propio_id"]
        )

    assert respuesta.status_code == 200, respuesta.text
    assert ticket["estado_id"] == ambito_tickets["estado_cerrado_id"]
    assert stock_despues == stock_antes - 1


# ---------------------------------------------------------------------------
# Creacion POST /tickets/: atribucion y contrato
# ---------------------------------------------------------------------------


def test_solicitante_crea_y_se_atribuye_su_identidad(motor, ambito_tickets):
    """Aunque envie el `usuario_id` de otro, el ticket es del Solicitante."""
    with _cliente(
        motor, "Solicitante", ambito_tickets["departamento_id"], ambito_tickets["solicitante_id"]
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["usuario_ajeno_id"])
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["usuario_id"] == ambito_tickets["solicitante_id"]


def test_administrador_crea_para_solicitante_de_otra_institucion_403_sin_mutar(
    motor, ambito_tickets
):
    with _cliente(motor, "Superadmin", None) as supervisor:
        antes = len(supervisor.get(RUTA_TICKETS).json())

    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["usuario_ajeno_id"])
        )

    with _cliente(motor, "Superadmin", None) as supervisor:
        despues = len(supervisor.get(RUTA_TICKETS).json())

    assert respuesta.status_code == 403, respuesta.text
    assert despues == antes


def test_administrador_crea_para_solicitante_propio_201(motor, ambito_tickets):
    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["solicitante_id"])
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["usuario_id"] == ambito_tickets["solicitante_id"]


@pytest.mark.parametrize("rol", ["Superadmin", "Administrador", "Bodeguero"])
def test_otros_roles_conservan_usuario_id_obligatorio(motor, ambito_tickets, rol):
    """Sin `usuario_id` el contrato vigente responde 422 para los demas roles."""
    payload = _payload(ambito_tickets, ambito_tickets["solicitante_id"])
    payload.pop("usuario_id")
    with _cliente(motor, rol, ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(RUTA_TICKETS, json=payload)
    assert respuesta.status_code == 422, respuesta.text
