"""T2 (Feature 014): estado, precondiciones, motivo e idempotencia (AC-1, AC-3, AC-5…AC-8, AC-13).

Seam bajo prueba: la interfaz HTTP (`TestClient`). Fija el contrato de las
transiciones de ciclo de vida del catalogo:

* toda mutacion expresa el estado **destino** (`{"activo": bool}`) y responde
  **200** con el recurso y su estado persistido, tanto si la transicion es real
  como si es una repeticion idempotente (D-4/D-9);
* el motivo libre es obligatorio solo en una transicion real: ausente, vacio,
  solo espacios o de mas de 500 caracteres responde **422**; hasta 500 se
  persiste literal en el historial (D-8);
* el orden es 404 (existencia/pertenencia) -> 200 idempotente -> 422 (motivo) ->
  409 (precondicion), y todo fallo deja estado, stock, movimientos e historial
  intactos (D-9/AC-3);
* baja de producto: saldo cero en **todas** las filas de `stock_sede`
  (`inventario` legado no participa); baja de categoria: sin productos activos;
  reactivar producto exige categoria activa; reactivar categoria no reactiva
  productos (D-5/D-6/AC-5/AC-6);
* el alta vigente de producto solo crea en categoria activa y el producto nace
  activo (AC-13); desactivar no borra ni altera referencias (AC-1).

Fase ROJA de TDD: las rutas y las columnas `activo`/tablas de historial aun no
existen (T4 modelo/DDL, T7 servicio, T9 rutas); las pruebas caen en rojo por esas
ausencias (404 del router, `pytest.fail` de las guardas o campos ausentes), nunca
por imports ni sintaxis.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import (
    Categoria,
    DetalleTicket,
    MovimientoInventario,
    Producto,
    StockSede,
)

from ._soporte_ciclo_vida_catalogo_014 import (
    AUSENTE,
    CAMPOS_HISTORIAL_PRODUCTO,
    CAMPOS_HISTORIAL_CATEGORIA,
    DETALLE_CATEGORIA_NO_ENCONTRADA,
    DETALLE_PRODUCTO_NO_ENCONTRADO,
    RUTA_CATEGORIA_ESTADO,
    RUTA_PRODUCTO_ESTADO,
    activo_de_categoria,
    activo_de_producto,
    cliente_de_rol,
    contar,
    crear_categoria,
    crear_producto,
    exigir_columna,
    exigir_ruta,
    fijar_stock_sede,
    historial_categoria,
    historial_producto,
    marcar_categoria,
    marcar_producto,
    sembrar_mundo_014,
    sesion,
    transicionar_categoria,
    transicionar_producto,
)
from ._soporte_ciclo_vida_013 import sembrar_ticket


@pytest.fixture
def mundo(motor, dos_instituciones):
    return sembrar_mundo_014(motor, dos_instituciones)


def _admin(motor, datos, **opciones):
    return cliente_de_rol(motor, datos, "Administrador", **opciones)


def _solicitante(motor, datos, **opciones):
    return cliente_de_rol(motor, datos, "Solicitante", **opciones)


def _stock_sede_id(motor, datos, producto_id: int) -> int:
    with sesion(motor) as db:
        fila = db.execute(
            select(StockSede).where(
                StockSede.sede_id == datos["sede_id"],
                StockSede.producto_id == producto_id,
            )
        ).scalar_one()
        return fila.stock_sede_id


# ---------------------------------------------------------------------------
# AC-13: estado inicial y alta en categoria activa
# ---------------------------------------------------------------------------


def test_producto_nuevo_nace_activo_ac_13(motor, mundo):
    """AC-13: el alta vigente crea el producto en estado `activo`."""
    with _admin(motor, mundo) as cliente:
        respuesta = cliente.post(
            "/api/v1/inventario/productos",
            json={
                "nombre": "Producto nacido activo 014",
                "descripcion": "Alta de la 014",
                "unidad_medida": "UNIDAD",
                "stock_minimo": 1,
                "categoria_id": mundo["categoria_id"],
            },
        )
        assert respuesta.status_code == 201, respuesta.text
        cuerpo = respuesta.json()
        assert "activo" in cuerpo, (
            "el recurso creado debe exponer `activo` (AC-13); "
            f"campos: {sorted(cuerpo)}"
        )
        assert cuerpo["activo"] is True
        assert activo_de_producto(motor, cuerpo["producto_id"]) is True


def test_alta_en_categoria_inactiva_responde_409_sin_escritura_ac_13(motor, mundo):
    """AC-13: crear producto en categoria inactiva es 409 y no escribe fila."""
    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada 014")
    marcar_categoria(motor, categoria, False)
    productos_antes = contar(motor, Producto)

    with _admin(motor, mundo) as cliente:
        respuesta = cliente.post(
            "/api/v1/inventario/productos",
            json={
                "nombre": "Producto en categoria inactiva",
                "descripcion": "No debe crearse",
                "unidad_medida": "UNIDAD",
                "stock_minimo": 0,
                "categoria_id": categoria,
            },
        )
        assert respuesta.status_code == 409, respuesta.text

    assert contar(motor, Producto) == productos_antes, (
        "un 409 de alta en categoria inactiva no puede dejar fila"
    )


# ---------------------------------------------------------------------------
# AC-6: saldo cero en `stock_sede`
# ---------------------------------------------------------------------------


def test_baja_producto_con_saldo_positivo_responde_409_sin_efectos_ac_6(motor, mundo):
    """AC-6: cualquier fila de `stock_sede` con saldo > 0 bloquea la baja."""
    producto = crear_producto(motor, mundo, nombre="Con saldo", stock_sede=7)
    stock_sede_id = _stock_sede_id(motor, mundo, producto)

    with _admin(motor, mundo) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo="Baja con saldo"
        )
        assert respuesta.status_code == 409, respuesta.text

        assert activo_de_producto(motor, producto) is True
        assert historial_producto(cliente, producto) == []
    with sesion(motor) as db:
        assert db.get(StockSede, stock_sede_id).stock_actual == 7
        assert (
            db.execute(
                select(MovimientoInventario).where(
                    MovimientoInventario.stock_sede_id == stock_sede_id
                )
            ).scalars().all()
            == []
        ), "la baja rechazada no puede crear movimientos de stock"


def test_baja_producto_sin_filas_de_stock_procede_ac_6(motor, mundo):
    """AC-6: sin filas en `stock_sede` el saldo es cero y la baja procede."""
    producto = crear_producto(motor, mundo, nombre="Sin fila de stock", stock_sede=None)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo="Baja sin existencias"
        )
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["activo"] is False
        assert activo_de_producto(motor, producto) is False
        filas = historial_producto(cliente, producto)
        assert len(filas) == 1, filas


def test_baja_producto_con_saldos_en_cero_procede_ac_6(motor, mundo):
    """AC-6: filas existentes todas en cero permiten la desactivacion."""
    producto = crear_producto(motor, mundo, nombre="Saldo cero", stock_sede=0)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo="Saldo cero en bodega"
        )
        assert respuesta.status_code == 200, respuesta.text
        assert activo_de_producto(motor, producto) is False


def test_inventario_legado_positivo_no_impide_la_baja_ac_6(motor, mundo):
    """AC-6: `inventario` legado no es saldo operativo y no participa."""
    # El producto base de la fixture tiene una fila legada de `inventario` con 50;
    # se le da saldo operativo cero en `stock_sede` para aislar la precondicion.
    base = mundo["producto_id"]
    fijar_stock_sede(motor, mundo, base, 0)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, base, activo=False, motivo="Solo queda inventario legado"
        )
        assert respuesta.status_code == 200, respuesta.text
        assert activo_de_producto(motor, base) is False


# ---------------------------------------------------------------------------
# AC-5: dependencia categoria <-> producto
# ---------------------------------------------------------------------------


def test_baja_categoria_con_producto_activo_responde_409_ac_5(motor, mundo):
    """AC-5: una categoria con al menos un producto activo no se desactiva."""
    categoria = crear_categoria(motor, mundo, nombre="Con producto activo")
    crear_producto(motor, mundo, nombre="Activo de la categoria", categoria_id=categoria)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Intento con producto activo"
        )
        assert respuesta.status_code == 409, respuesta.text
        assert activo_de_categoria(motor, categoria) is True
        assert historial_categoria(cliente, categoria) == []


def test_baja_categoria_sin_productos_procede_ac_5(motor, mundo):
    """AC-5: la condicion «todos sus productos inactivos» se cumple vaciamente."""
    categoria = crear_categoria(motor, mundo, nombre="Vacia")

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Categoria sin productos"
        )
        assert respuesta.status_code == 200, respuesta.text
        assert activo_de_categoria(motor, categoria) is False
        filas = historial_categoria(cliente, categoria)
        assert len(filas) == 1, filas
        assert CAMPOS_HISTORIAL_CATEGORIA <= set(filas[0]), sorted(filas[0])


def test_baja_categoria_con_todos_sus_productos_inactivos_y_sin_cascada_ac_5(
    motor, mundo
):
    """AC-5: tras retirar todos sus productos, la categoria baja; reactivarla no
    reactiva los productos."""
    categoria = crear_categoria(motor, mundo, nombre="Con productos retirados")
    producto = crear_producto(
        motor, mundo, nombre="Producto de la categoria", categoria_id=categoria
    )

    with _admin(motor, mundo) as cliente:
        retiro_producto = transicionar_producto(
            cliente, producto, activo=False, motivo="Retiro previo del producto"
        )
        assert retiro_producto.status_code == 200, retiro_producto.text

        retiro_categoria = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Retiro de la categoria"
        )
        assert retiro_categoria.status_code == 200, retiro_categoria.text
        assert activo_de_categoria(motor, categoria) is False

        reactivacion = transicionar_categoria(
            cliente, categoria, activo=True, motivo="Reactivacion de la categoria"
        )
        assert reactivacion.status_code == 200, reactivacion.text
        assert activo_de_categoria(motor, categoria) is True
        assert activo_de_producto(motor, producto) is False, (
            "reactivar la categoria no puede reactivar sus productos en cascada"
        )


def test_reactivacion_producto_bajo_categoria_activa_procede_ac_5(motor, mundo):
    """AC-5: con la categoria activa, la reactivacion del producto procede."""
    producto = crear_producto(motor, mundo, nombre="Reactivacion valida", stock_sede=None)
    marcar_producto(motor, producto, False)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, producto, activo=True, motivo="Reactivar el producto"
        )
        assert respuesta.status_code == 200, respuesta.text
        assert activo_de_producto(motor, producto) is True
        filas = historial_producto(cliente, producto)
        assert len(filas) == 1, filas
        assert filas[0]["activo_origen"] is False
        assert filas[0]["activo_destino"] is True
        assert filas[0]["motivo"] == "Reactivar el producto"


def test_reactivacion_producto_bajo_categoria_inactiva_responde_409_ac_5(motor, mundo):
    """AC-5: no puede existir un producto activo bajo una categoria inactiva."""
    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada")
    producto = crear_producto(
        motor, mundo, nombre="Producto retenido", categoria_id=categoria, stock_sede=None
    )
    marcar_categoria(motor, categoria, False)
    marcar_producto(motor, producto, False)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, producto, activo=True, motivo="Intento bajo categoria inactiva"
        )
        assert respuesta.status_code == 409, respuesta.text
        assert activo_de_producto(motor, producto) is False
        assert historial_producto(cliente, producto) == []


# ---------------------------------------------------------------------------
# AC-1: la baja no borra ni altera referencias
# ---------------------------------------------------------------------------


def test_baja_conserva_referencias_stock_movimientos_y_tickets_ac_1(motor, mundo):
    """AC-1: desactivar no borra producto, stock, movimientos ni detalles."""
    producto = crear_producto(motor, mundo, nombre="Referenciado", stock_sede=0)
    stock_sede_id = _stock_sede_id(motor, mundo, producto)
    ticket_id = sembrar_ticket(
        motor, mundo, producto_id=producto, cantidad=2, asunto="Ticket previo a la baja"
    )

    with _admin(motor, mundo) as cliente:
        entrada = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 4,
                "observacion": "Entrada previa a la baja",
                "stock_sede_id": stock_sede_id,
            },
        )
        assert entrada.status_code == 201, entrada.text
        salida = cliente.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo_movimiento": "SALIDA",
                "cantidad": 4,
                "observacion": "Salida previa a la baja",
                "stock_sede_id": stock_sede_id,
            },
        )
        assert salida.status_code == 201, salida.text

        antes = {
            "productos": contar(motor, Producto),
            "detalles": contar(motor, DetalleTicket),
            "movimientos": contar(motor, MovimientoInventario),
            "stock": contar(motor, StockSede),
        }

        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo="Retiro sin borrado"
        )
        assert respuesta.status_code == 200, respuesta.text

        despues = {
            "productos": contar(motor, Producto),
            "detalles": contar(motor, DetalleTicket),
            "movimientos": contar(motor, MovimientoInventario),
            "stock": contar(motor, StockSede),
        }
        assert despues == antes, (
            "la baja logica no puede borrar ni alterar referencias (AC-1): "
            f"{antes} -> {despues}"
        )

        # El detalle del ticket previo sigue resolviendo el producto inactivo.
        tickets = cliente.get("/api/v1/tickets/")
        assert tickets.status_code == 200, tickets.text
        ticket = next(t for t in tickets.json() if t["ticket_id"] == ticket_id)
        assert ticket["detalles"][0]["producto"]["nombre"] == "Referenciado"


def test_no_existe_operacion_de_borrado_fisico_ac_1(motor, mundo):
    """AC-1/D-3: bajo producto y categoria solo se publican lectura y transicion."""
    for ruta, prohibidos in (
        (RUTA_PRODUCTO_ESTADO, {"delete"}),
        (RUTA_CATEGORIA_ESTADO, {"delete", "put"}),
    ):
        exigir_ruta(ruta, "PATCH")
        operaciones = app_paths_para(ruta)
        presentes = prohibidos & set(operaciones)
        assert not presentes, (
            "no existe borrado ni reemplazo fisico del catalogo (D-3); "
            f"metodos publicados en {ruta}: {sorted(operaciones)}"
        )

    # La transicion de categoria tampoco borra la fila: solo cambia su estado.
    categoria = crear_categoria(motor, mundo, nombre="Categoria sin borrado")
    antes = contar(motor, Categoria)
    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Retiro sin borrado"
        )
        assert respuesta.status_code == 200, respuesta.text
    despues = contar(motor, Categoria)
    assert despues == antes, (
        "la baja logica de categoria no puede borrar filas (AC-1): "
        f"{antes} -> {despues}"
    )
    assert activo_de_categoria(motor, categoria) is False


def app_paths_para(ruta: str) -> dict:
    from app.main import app

    return app.openapi().get("paths", {}).get(ruta, {})


# ---------------------------------------------------------------------------
# AC-7: motivo e historial de la transicion efectiva
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "motivo",
    [AUSENTE, None, "", "   ", "x" * 501],
    ids=["ausente", "nulo", "vacio", "solo_espacios", "501_caracteres"],
)
def test_motivo_invalido_responde_422_sin_cambios_ac_7(motor, mundo, motivo):
    """AC-7: ausente, vacio, solo espacios o >500 responde 422 sin efectos."""
    producto = crear_producto(motor, mundo, nombre="Motivo invalido", stock_sede=None)

    with _admin(motor, mundo) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo=motivo
        )
        assert respuesta.status_code == 422, respuesta.text
        assert activo_de_producto(motor, producto) is True
        assert historial_producto(cliente, producto) == []


def test_motivo_de_500_caracteres_se_persiste_exacto_ac_7(motor, mundo):
    """AC-7: el limite es 500 inclusive y el motivo se guarda literal."""
    producto = crear_producto(motor, mundo, nombre="Motivo limite", stock_sede=None)
    motivo = "m" * 500
    actor = mundo["usuario_id"]

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo=motivo
        )
        assert respuesta.status_code == 200, respuesta.text
        assert respuesta.json()["activo"] is False

        filas = historial_producto(cliente, producto)
        assert len(filas) == 1, filas
        fila = filas[0]
        assert CAMPOS_HISTORIAL_PRODUCTO <= set(fila), sorted(fila)
        assert fila["producto_id"] == producto
        assert fila["usuario_id"] == actor
        assert fila["fecha_transicion"] is not None
        assert fila["activo_origen"] is True
        assert fila["activo_destino"] is False
        assert fila["motivo"] == motivo, "el motivo debe persistirse literal"


# ---------------------------------------------------------------------------
# AC-8: idempotencia sin motivo ni precondiciones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "motivo", [AUSENTE, "", "x" * 501], ids=["sin_motivo", "vacio", "demasiado_largo"]
)
def test_repeticion_idempotente_responde_200_sin_motivo_ni_historial_ac_8(
    motor, mundo, motivo
):
    """AC-8: repetir el estado destino responde 200 aunque falte el motivo."""
    producto = crear_producto(motor, mundo, nombre="Idempotente", stock_sede=None)

    with _admin(motor, mundo) as cliente:
        primera = transicionar_producto(
            cliente, producto, activo=False, motivo="Baja efectiva"
        )
        assert primera.status_code == 200, primera.text
        assert len(historial_producto(cliente, producto)) == 1

        repetida = transicionar_producto(
            cliente, producto, activo=False, motivo=motivo
        )
        assert repetida.status_code == 200, repetida.text
        assert repetida.json()["activo"] is False
        assert len(historial_producto(cliente, producto)) == 1, (
            "la repeticion idempotente no puede agregar historial"
        )


def test_idempotencia_no_evalua_la_precondicion_de_saldo_ac_8(motor, mundo):
    """AC-8: un producto ya inactivo repite 200 aunque hoy tenga saldo positivo."""
    producto = crear_producto(motor, mundo, nombre="Inactivo con saldo", stock_sede=0)

    with _admin(motor, mundo) as cliente:
        primera = transicionar_producto(
            cliente, producto, activo=False, motivo="Baja con saldo cero"
        )
        assert primera.status_code == 200, primera.text

    fijar_stock_sede(motor, mundo, producto, 9)

    with _admin(motor, mundo) as cliente:
        repetida = transicionar_producto(
            cliente, producto, activo=False, motivo=AUSENTE
        )
        assert repetida.status_code == 200, repetida.text
        assert repetida.json()["activo"] is False
        assert len(historial_producto(cliente, producto)) == 1


# ---------------------------------------------------------------------------
# AC-3: precedencia y fallos sin efectos
# ---------------------------------------------------------------------------


def test_404_de_ambito_precede_al_motivo_invalido_ac_3(motor, mundo):
    """AC-3: un recurso ajeno responde 404 antes de validar el motivo (422)."""
    ajeno = mundo["producto_homonimo_ajeno_id"]

    with _admin(motor, mundo) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        respuesta_ajena = transicionar_producto(
            cliente, ajeno, activo=False, motivo=""
        )
        respuesta_inexistente = transicionar_producto(
            cliente, 999999, activo=False, motivo=""
        )

        assert respuesta_ajena.status_code == 404, respuesta_ajena.text
        assert respuesta_inexistente.status_code == 404, respuesta_inexistente.text
        assert respuesta_ajena.json()["detail"] == DETALLE_PRODUCTO_NO_ENCONTRADO
        assert (
            respuesta_inexistente.json()["detail"]
            == respuesta_ajena.json()["detail"]
        ), "el 404 del ajeno debe ser indistinguible del inexistente"
        assert activo_de_producto(motor, ajeno) is True


def test_404_de_categoria_oculta_antes_del_motivo_ac_3(motor, mundo):
    """AC-3: el mismo orden se aplica a la categoria."""
    ajeno = mundo["categoria_homonima_ajena_id"]

    with _admin(motor, mundo) as cliente:
        exigir_ruta(
            "/api/v1/inventario/categorias/{categoria_id}/estado", "PATCH"
        )
        respuesta = transicionar_categoria(cliente, ajeno, activo=False, motivo="")
        assert respuesta.status_code == 404, respuesta.text
        assert respuesta.json()["detail"] == DETALLE_CATEGORIA_NO_ENCONTRADA
        assert activo_de_categoria(motor, ajeno) is True


def test_motivo_invalido_precede_a_la_precondicion_409_ac_3(motor, mundo):
    """AC-3: con saldo positivo y motivo invalido gana el 422, no el 409."""
    producto = crear_producto(motor, mundo, nombre="Dos fallos", stock_sede=5)

    with _admin(motor, mundo) as cliente:
        respuesta = transicionar_producto(cliente, producto, activo=False, motivo="")
        assert respuesta.status_code == 422, respuesta.text
        assert activo_de_producto(motor, producto) is True
        assert historial_producto(cliente, producto) == []


def test_orden_observable_de_validacion_ac_3(motor, mundo):
    """AC-3/D-9: 404 -> 200 idempotente -> 422 -> 409 sobre el mismo recurso.

    Un producto ya inactivo responde 200 sin motivo; uno activo con motivo
    invalido, 422; uno activo con saldo positivo y motivo valido, 409. Ninguna
    de las tres respuestas escribe historial salvo la primera transicion real.
    """
    inactivo = crear_producto(motor, mundo, nombre="Ya inactivo", stock_sede=None)
    marcar_producto(motor, inactivo, False)
    con_saldo = crear_producto(motor, mundo, nombre="Con saldo", stock_sede=1)

    with _admin(motor, mundo) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        idempotente = transicionar_producto(
            cliente, inactivo, activo=False, motivo=AUSENTE
        )
        sin_motivo = transicionar_producto(
            cliente, con_saldo, activo=False, motivo=AUSENTE
        )
        con_conflicto = transicionar_producto(
            cliente, con_saldo, activo=False, motivo="Baja con saldo"
        )

        assert idempotente.status_code == 200, idempotente.text
        assert sin_motivo.status_code == 422, sin_motivo.text
        assert con_conflicto.status_code == 409, con_conflicto.text
        assert historial_producto(cliente, inactivo) == []
        assert historial_producto(cliente, con_saldo) == []
        assert activo_de_producto(motor, con_saldo) is True


def test_fallo_de_autorizacion_no_escribe_estado_ni_historial_ac_3(motor, mundo):
    """AC-3: un rol sin permiso (403) no deja ningun efecto."""
    producto = crear_producto(motor, mundo, nombre="Sin permiso", stock_sede=None)
    exigir_columna(Producto, "activo", "producto")

    with _solicitante(motor, mundo) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        respuesta = transicionar_producto(
            cliente, producto, activo=False, motivo="No autorizado"
        )
        assert respuesta.status_code == 403, respuesta.text
    assert activo_de_producto(motor, producto) is True
