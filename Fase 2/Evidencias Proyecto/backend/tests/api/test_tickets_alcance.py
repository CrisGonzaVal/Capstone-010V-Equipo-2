"""T4 (Feature 007): propiedad, atribucion y ambito institucional en tickets.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`). Se siembran
**dos instituciones** (INST01 propia y INST02 ajena) con usuarios y tickets de cada
una y se observa, por rol, que:

  * `GET /tickets/`: el Solicitante ve solo sus tickets; Administrador/Bodeguero,
    solo los de su institucion; Superadmin, todos (D-3, AC-6, AC-8).
  * `GET /tickets/catalogos`: `solicitantes` se acota por rol (Solicitante solo su
    identidad; Administrador/Bodeguero su institucion; Superadmin global), y con la
    Feature 008 los `productos` y su `stock_total` pasan a ser institucionales (D-1,
    AC-6): el rol limitado solo ve (y suma el stock de) su institucion.
  * En una operacion permitida sobre un ticket de otra institucion (PATCH estado,
    despacho) el rol limitado recibe **404**, igual que para un id inexistente, sin
    mutar datos (D-5, AC-6).
  * `POST /tickets/`: **todo rol autorizado** queda atribuido a su identidad de
    sesion; `usuario_id` es opcional y su valor (propio, ajeno o inexistente) se
    ignora sin 422/403/404 (enmienda D-33/D-35 de la 003, AC-18/AC-20 de la 007 y
    AC-11 de la 008). La institucion del ticket y de sus detalles es la de sesion.
  * El despacho del ticket propio sigue siendo una transaccion ACID (Feature 005).

Fuera de alcance de T4: el 403 de rol (e.g. Solicitante en PATCH/despacho) ya lo fija
T2; aqui no se duplica.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import (
    Categoria,
    Departamento,
    DetalleTicket,
    EstadoTicket,
    HistorialTransicionTicket,
    Institucion,
    Inventario,
    Producto,
    Rol,
    Sede,
    StockSede,
    Ticket,
    Usuario,
)
from app.services.auth_service import IdentidadAutenticada

RUTA_TICKETS = "/api/v1/tickets/"
RUTA_CATALOGOS = "/api/v1/tickets/catalogos"


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

        # Feature 011 (T9): el departamento de INST01 y sus tickets necesitan sede;
        # el despacho rebaja `stock_sede` (no el inventario departamental legado).
        sede_propia = Sede(
            nombre="Sede Operaciones", institucion_id=datos_base["institucion_id"]
        )
        db.add(sede_propia)
        db.flush()
        departamento_propio = db.get(Departamento, datos_base["departamento_id"])
        departamento_propio.sede_id = sede_propia.sede_id
        db.add(
            StockSede(
                sede_id=sede_propia.sede_id,
                producto_id=datos_base["producto_id"],
                stock_actual=50,
                institucion_id=datos_base["institucion_id"],
            )
        )
        db.flush()

        # Institucion ajena INST02.
        institucion_ajena = Institucion(
            institucion_id="INST02",
            nombre="Instituto Ajeno",
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

        # Feature 008 (D-1/AC-6): el catalogo es institucional. Para demostrar el
        # aislamiento se crean dos productos **homonimos independientes** (mismo
        # nombre, id distinto), uno por institucion, cada uno con su propia
        # existencia: el `stock_total` del catalogo de una institucion no puede
        # sumar el de la otra.
        categoria_ajena = Categoria(
            nombre_cat="Insumos Ajenos",
            descripcion_cat="Catalogo de la institucion ajena",
            institucion_id=institucion_ajena.institucion_id,
        )
        db.add(categoria_ajena)
        db.flush()

        producto_institucional = Producto(
            nombre="Insumo Compartido",
            descripcion="Homonimo de INST01 (Operaciones)",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=datos_base["categoria_id"],
            institucion_id=datos_base["institucion_id"],
        )
        db.add(producto_institucional)
        db.flush()
        db.add(
            Inventario(
                stock_actual=40,
                ubicacion="Operaciones - C1",
                departamento_id=datos_base["departamento_id"],
                producto_id=producto_institucional.producto_id,
                institucion_id=datos_base["institucion_id"],
            )
        )
        # Feature 011 (M2): el catalogo agrega el saldo por sede, no el inventario
        # departamental legado.
        db.add(
            StockSede(
                sede_id=sede_propia.sede_id,
                producto_id=producto_institucional.producto_id,
                stock_actual=40,
                institucion_id=datos_base["institucion_id"],
            )
        )

        producto_homonimo_ajeno = Producto(
            nombre="Insumo Compartido",
            descripcion="Homonimo de INST02 (Bodega Sur)",
            unidad_medida="UNIDAD",
            stock_minimo=0,
            categoria_id=categoria_ajena.categoria_id,
            institucion_id=institucion_ajena.institucion_id,
        )
        db.add(producto_homonimo_ajeno)
        db.flush()
        db.add(
            Inventario(
                stock_actual=7,
                ubicacion="Bodega Sur - C1",
                departamento_id=departamento_ajeno.departamento_id,
                producto_id=producto_homonimo_ajeno.producto_id,
                institucion_id=institucion_ajena.institucion_id,
            )
        )
        db.flush()

        def nuevo_ticket(
            usuario_id: int,
            estado_id: int,
            asunto: str,
            producto_id: int,
            institucion_id: str,
            sede_id: int | None = None,
        ) -> int:
            # Feature 008 (T9): token institucional coherente. El detalle referencia
            # un producto de la misma institucion que el ticket, de modo que se
            # satisfacen las claves compuestas (detalle -> ticket y detalle ->
            # producto) y el esquema endurecido a NOT NULL (AC-4).
            # Feature 011 (T9): los tickets de INST01 llevan la instantanea de sede.
            ticket = Ticket(
                usuario_id=usuario_id,
                prioridad_id=datos_base["prioridad_id"],
                estado_id=estado_id,
                asunto=asunto,
                descripcion="Sembrado para pruebas de alcance.",
                institucion_id=institucion_id,
                sede_id=sede_id,
            )
            db.add(ticket)
            db.flush()
            db.add(
                DetalleTicket(
                    ticket_id=ticket.ticket_id,
                    producto_id=producto_id,
                    cantidad_solicitada=1,
                    cantidad_entregada=0,
                    institucion_id=institucion_id,
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
            "producto_institucional_id": producto_institucional.producto_id,
            "producto_homonimo_ajeno_id": producto_homonimo_ajeno.producto_id,
            "sede_id": sede_propia.sede_id,
            "estado_pendiente_id": estados["Pendiente"],
            "estado_en_revision_id": estados["EnRevision"],
            "estado_en_curso_id": estados["EnCurso"],
            "estado_cerrado_id": estados["Cerrado"],
            "ticket_propio_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["Pendiente"],
                "Propio Pendiente",
                datos_base["producto_id"],
                datos_base["institucion_id"],
                sede_propia.sede_id,
            ),
            "ticket_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id,
                estados["Pendiente"],
                "Ajeno Pendiente",
                producto_homonimo_ajeno.producto_id,
                institucion_ajena.institucion_id,
            ),
            "ticket_estado_propio_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["EnRevision"],
                "Propio EnRevision",
                datos_base["producto_id"],
                datos_base["institucion_id"],
                sede_propia.sede_id,
            ),
            "ticket_estado_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id,
                estados["EnRevision"],
                "Ajeno EnRevision",
                producto_homonimo_ajeno.producto_id,
                institucion_ajena.institucion_id,
            ),
            "ticket_despacho_propio_id": nuevo_ticket(
                solicitante.usuario_id,
                estados["EnCurso"],
                "Propio EnCurso",
                datos_base["producto_id"],
                datos_base["institucion_id"],
                sede_propia.sede_id,
            ),
            "ticket_despacho_ajeno_id": nuevo_ticket(
                usuario_ajeno.usuario_id,
                estados["EnCurso"],
                "Ajeno EnCurso",
                producto_homonimo_ajeno.producto_id,
                institucion_ajena.institucion_id,
            ),
        }
        db.commit()
        return ids
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers: identidad por rol, cliente real y lecturas por HTTP
# ---------------------------------------------------------------------------


def _identidad(
    rol: str, departamento_id, usuario_id: int, sede_id: int | None = None
) -> IdentidadAutenticada:
    """Identidad autenticada con rol, departamento e id de usuario dados.

    El usuario no se persiste: el filtro institucional lee `departamento_id`, la
    propiedad lee `usuario_id` y la autorizacion solo lee `rol.nombre_rol`.
    `sede_id` es opcional y solo lo usa la prueba de AC-20 (007) para distinguir
    `usuario.sede_id` de `departamento.sede_id`.
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Alcance",
        correo=f"sonda.{rol.lower()}@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
        sede_id=sede_id,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub=f"sub-{rol.lower()}")


@contextmanager
def _cliente(motor, rol: str, departamento_id, usuario_id: int = 9999, sede_id=None):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = (
        lambda: _identidad(rol, departamento_id, usuario_id, sede_id)
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


def _stock_sede(motor, sede_id: int, producto_id: int) -> int:
    """Saldo persistido de un producto en una sede (Feature 011)."""
    with sessionmaker(bind=motor)() as db:
        fila = db.execute(
            select(StockSede).where(
                StockSede.sede_id == sede_id,
                StockSede.producto_id == producto_id,
            )
        ).scalar_one()
        return fila.stock_actual


def _payload(datos: dict, usuario_id: int | None = None) -> dict:
    """Payload valido del alta; `usuario_id` solo viaja si se pide.

    Enmienda D-33: el campo es opcional y su valor se ignora, asi que la omision
    es una variante valida del contrato.
    """
    cuerpo = {
        "prioridad_id": datos["prioridad_id"],
        "estado_id": datos["estado_pendiente_id"],
        "asunto": "Alta de ticket en pruebas de alcance",
        "descripcion": "Atribucion y ambito de tickets.",
        "detalles": [{"producto_id": datos["producto_id"], "cantidad_solicitada": 1}],
    }
    if usuario_id is not None:
        cuerpo["usuario_id"] = usuario_id
    return cuerpo


def _contar(motor, modelo) -> int:
    with sessionmaker(bind=motor)() as db:
        return db.query(modelo).count()


def _instituciones_persistidas(motor, ticket_id: int) -> dict:
    """`institucion_id` de la cabecera y de cada detalle del ticket."""
    with sessionmaker(bind=motor)() as db:
        ticket = db.get(Ticket, ticket_id)
        detalles = (
            db.query(DetalleTicket)
            .filter(DetalleTicket.ticket_id == ticket_id)
            .all()
        )
        return {
            "usuario_id": ticket.usuario_id,
            "sede_id": ticket.sede_id,
            "ticket": ticket.institucion_id,
            "detalles": [d.institucion_id for d in detalles],
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


def test_superadmin_recibe_403_en_listado_ac_15(motor, ambito_tickets):
    """Feature 017 (D-9/AC-15): el listado de tickets se retira al Superadmin."""
    with _cliente(motor, "Superadmin", None) as cliente:
        respuesta = cliente.get(RUTA_TICKETS)
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json() == {"detail": "Permiso insuficiente para la operacion"}


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


def test_catalogo_superadmin_recibe_403_ac_15(motor, ambito_tickets):
    """Feature 017 (D-9/AC-15, T10): el catalogo del modal es lectura de negocio.

    Superadmin gobernaba el SaaS y no inspecciona productos, stock ni
    solicitantes del tenant; los roles institucionales conservan el permiso.
    """
    with _cliente(motor, "Superadmin", None) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json() == {"detail": "Permiso insuficiente para la operacion"}


def test_catalogo_productos_y_stock_son_institucionales(motor, ambito_tickets):
    """Feature 008 (D-1/AC-6): el `stock_total` del catalogo solo suma la sede de
    la institucion del solicitante; el homonimo de la institucion ajena ni
    siquiera aparece, aunque comparta nombre."""
    with _cliente(
        motor, "Solicitante", ambito_tickets["departamento_id"], ambito_tickets["solicitante_id"]
    ) as cliente:
        respuesta = cliente.get(RUTA_CATALOGOS)
    assert respuesta.status_code == 200, respuesta.text

    productos = {p["producto_id"]: p for p in respuesta.json()["productos"]}
    # El producto propio aparece con su stock (40) y NO con el de la institucion
    # ajena (7); el homonimo ajeno no se filtra dentro del catalogo.
    propio = productos[ambito_tickets["producto_institucional_id"]]
    assert propio["stock_total"] == 40
    assert propio["institucion_id"] == "INST01"
    assert ambito_tickets["producto_homonimo_ajeno_id"] not in productos


# ---------------------------------------------------------------------------
# Mutacion por id: ticket ajeno oculto como 404, sin mutar
# ---------------------------------------------------------------------------


def test_administrador_patch_ticket_ajeno_404_sin_mutar(motor, ambito_tickets):
    # Feature 017 (D-9/AC-15): el Superadmin ya no lista tickets; el estado se
    # observa por ORM antes y despues.
    with sessionmaker(bind=motor)() as db:
        antes = db.get(Ticket, ambito_tickets["ticket_estado_ajeno_id"]).estado_id

    with _cliente(motor, "Administrador", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_estado_ajeno_id']}/estado",
            json={"estado_id": ambito_tickets["estado_en_curso_id"]},
        )

    with sessionmaker(bind=motor)() as db:
        despues = db.get(Ticket, ambito_tickets["ticket_estado_ajeno_id"]).estado_id

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
    # Actor persistido: el cambio de estado registra su fila de historial con
    # FK a `usuario` (013, AC-9); la sonda sintetica 9999 no existe en la BD.
    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
    ) as cliente:
        respuesta = cliente.patch(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_estado_propio_id']}/estado",
            json={"estado_id": ambito_tickets["estado_en_curso_id"]},
        )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado_id"] == ambito_tickets["estado_en_curso_id"]


def test_bodeguero_despacho_ticket_ajeno_404_sin_mutar(motor, ambito_tickets):
    with sessionmaker(bind=motor)() as db:
        antes = db.get(Ticket, ambito_tickets["ticket_despacho_ajeno_id"]).estado_id

    with _cliente(motor, "Bodeguero", ambito_tickets["departamento_id"]) as cliente:
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_despacho_ajeno_id']}/despacho",
            json={"usuario_id": ambito_tickets["usuario_id"]},
        )

    with sessionmaker(bind=motor)() as db:
        despues = db.get(Ticket, ambito_tickets["ticket_despacho_ajeno_id"]).estado_id

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
    # Actor persistido: el despacho registra su fila de historial (013, AC-9).
    with _cliente(
        motor,
        "Bodeguero",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
    ) as cliente:
        stock_antes = _stock_sede(
            motor,
            ambito_tickets["sede_id"],
            ambito_tickets["producto_id"],
        )
        respuesta = cliente.post(
            f"{RUTA_TICKETS}{ambito_tickets['ticket_despacho_propio_id']}/despacho",
            json={"usuario_id": ambito_tickets["usuario_id"]},
        )
        stock_despues = _stock_sede(
            motor,
            ambito_tickets["sede_id"],
            ambito_tickets["producto_id"],
        )
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

    persistido = _instituciones_persistidas(motor, respuesta.json()["ticket_id"])
    assert persistido["ticket"] == "INST01"
    assert persistido["detalles"] == ["INST01"]


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero", "Solicitante"])
@pytest.mark.parametrize("variante", ["omitido", "propio", "ajeno", "inexistente"])
def test_roles_autorizados_atienden_la_identidad_de_sesion(
    motor, ambito_tickets, rol, variante
):
    """AC-33/AC-18/AC-11: las cuatro variantes de payload dan 201 y autor de sesion.

    La identidad de sesion es un usuario persistido de INST01 (la fila del
    Solicitante) con el rol parametrizado: la autoria no depende del rol sino de
    la sesion, y el valor enviado en `usuario_id` se ignora por completo.
    """
    enviado = {
        "omitido": None,
        "propio": ambito_tickets["solicitante_id"],
        "ajeno": ambito_tickets["usuario_ajeno_id"],
        "inexistente": 987654,
    }[variante]

    with _cliente(
        motor,
        rol,
        ambito_tickets["departamento_id"],
        ambito_tickets["solicitante_id"],
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, enviado)
        )

    assert respuesta.status_code == 201, (rol, variante, respuesta.text)
    cuerpo = respuesta.json()
    assert cuerpo["usuario_id"] == ambito_tickets["solicitante_id"]
    assert cuerpo["sede_id"] == ambito_tickets["sede_id"]

    persistido = _instituciones_persistidas(motor, cuerpo["ticket_id"])
    assert persistido["usuario_id"] == ambito_tickets["solicitante_id"]
    assert persistido["ticket"] == "INST01"
    assert persistido["detalles"] == ["INST01"]


def test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion(
    motor, ambito_tickets
):
    """AC-11: un `usuario_id` ajeno ya no produce 404; se ignora y no duplica."""
    inicio = _contar(motor, Ticket)

    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["usuario_ajeno_id"])
        )

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["usuario_id"] == ambito_tickets["usuario_id"]
    assert _contar(motor, Ticket) == inicio + 1

    persistido = _instituciones_persistidas(motor, respuesta.json()["ticket_id"])
    assert persistido["usuario_id"] == ambito_tickets["usuario_id"]
    assert persistido["ticket"] == "INST01"
    assert persistido["detalles"] == ["INST01"]


def test_administrador_crea_para_solicitante_propio_201(motor, ambito_tickets):
    """Aunque el payload nombre al Solicitante, el autor es el Administrador."""
    # Actor persistido: la creacion registra su fila de historial (013, AC-9).
    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["solicitante_id"])
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["usuario_id"] == ambito_tickets["usuario_id"]


def test_departamento_sin_sede_responde_409_sin_ticket_detalle_ni_historial(
    motor, ambito_tickets
):
    """D-35/AC-20: sin sede departamental el alta es 409 y no escribe nada."""
    with sessionmaker(bind=motor)() as db:
        departamento = db.get(Departamento, ambito_tickets["departamento_id"])
        departamento.sede_id = None
        db.commit()

    tickets_antes = _contar(motor, Ticket)
    detalles_antes = _contar(motor, DetalleTicket)
    historial_antes = _contar(motor, HistorialTransicionTicket)

    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["solicitante_id"])
        )

    assert respuesta.status_code == 409, respuesta.text
    assert _contar(motor, Ticket) == tickets_antes
    assert _contar(motor, DetalleTicket) == detalles_antes
    assert _contar(motor, HistorialTransicionTicket) == historial_antes


def test_departamento_sin_sede_ignora_usuario_sede_id_y_responde_409(
    motor, ambito_tickets
):
    """AC-20 (007, enmienda 22/Oct/2026): no hay fallback a `usuario.sede_id`.

    El departamento de la identidad no tiene sede, pero el usuario de sesion
    apunta a una sede **valida**. Si el servicio usara `usuario.sede_id` como
    sustituto de `departamento.sede_id`, el alta responderia 201; la regla
    vigente exige **409** sin ticket, detalle ni historial. Este caso es el que
    distingue ambas fuentes de sede; los demas tests de 409 usan
    `usuario.sede_id = NULL` y no protegen esta clausura.
    """
    sede_valida = ambito_tickets["sede_id"]
    with sessionmaker(bind=motor)() as db:
        departamento = db.get(Departamento, ambito_tickets["departamento_id"])
        departamento.sede_id = None
        db.commit()

    tickets_antes = _contar(motor, Ticket)
    detalles_antes = _contar(motor, DetalleTicket)
    historial_antes = _contar(motor, HistorialTransicionTicket)

    # La identidad de sesion si tiene una sede valida: el fallback la usaria.
    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
        sede_id=sede_valida,
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["solicitante_id"])
        )

    assert respuesta.status_code == 409, respuesta.text
    assert _contar(motor, Ticket) == tickets_antes
    assert _contar(motor, DetalleTicket) == detalles_antes
    assert _contar(motor, HistorialTransicionTicket) == historial_antes


def test_ticket_guarda_la_sede_del_departamento_no_la_del_usuario(
    motor, ambito_tickets
):
    """AC-20 (007, enmienda 22/Oct/2026): la sede del ticket es la departamental.

    La identidad de sesion tiene `usuario.sede_id` apuntando a una sede
    **distinta** de la de su departamento. El alta responde 201 y la instantanea
    `ticket.sede_id` copia `departamento.sede_id`, nunca `usuario.sede_id`.
    """
    sede_departamento = ambito_tickets["sede_id"]
    with sessionmaker(bind=motor)() as db:
        sede_usuario = Sede(
            nombre="Sede Alterna del Usuario",
            institucion_id=ambito_tickets["institucion_id"],
        )
        db.add(sede_usuario)
        db.commit()
        sede_usuario_id = sede_usuario.sede_id

    assert sede_usuario_id != sede_departamento, "el caso debe distinguir las sedes"

    with _cliente(
        motor,
        "Administrador",
        ambito_tickets["departamento_id"],
        ambito_tickets["usuario_id"],
        sede_id=sede_usuario_id,
    ) as cliente:
        respuesta = cliente.post(
            RUTA_TICKETS, json=_payload(ambito_tickets, ambito_tickets["solicitante_id"])
        )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["sede_id"] == sede_departamento
    assert cuerpo["sede_id"] != sede_usuario_id

    persistido = _instituciones_persistidas(motor, cuerpo["ticket_id"])
    assert persistido["sede_id"] == sede_departamento
    assert persistido["sede_id"] != sede_usuario_id
