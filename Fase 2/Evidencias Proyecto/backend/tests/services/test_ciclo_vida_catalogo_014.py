"""T7 (Feature 014): contrato del servicio de ciclo de vida del catalogo.

Seam bajo prueba: las funciones publicas de `app.services.inventario_service`
sobre un motor SQLite en memoria. La Feature 014 fija las rutas y la
autorizacion HTTP en T9; aqui se acredita la logica que el router consumira:

* transiciones efectivas de producto y categoria con **exactamente una**
  transicion de historial, actor, motivo y estados origen/destino;
* repeticion idempotente: 200 con el estado actual, sin motivo, sin
  precondiciones y sin historial (AC-8);
* precedencia de negocio 404 -> 200 idempotente -> 422 motivo -> 409
  precondicion (AC-3);
* baja de producto con saldo cero en **todas** las filas de `stock_sede`; el
  `inventario` legado no participa (AC-6);
* baja de categoria sin productos activos y reactivacion solo bajo categoria
  activa, sin cascada (AC-5);
* alta vigente solo en categoria activa, producto nacido activo (AC-13);
* listado de gestion con ambos estados y aislado por tenant (AC-15);
* historial ordenado y exclusivo de su recurso (AC-12);
* atomicidad: estado e historial se confirman o revierten juntos.

Los escenarios de concurrencia real (AC-6/AC-16) se acreditan en PostgreSQL
gated (T10); SQLite ignora `FOR UPDATE`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    HistorialTransicionCategoria,
    HistorialTransicionProducto,
    Inventario,
    Producto,
    StockSede,
)
from app.schemas.producto_schema import TransicionCatalogo
from app.services import inventario_service

from tests.api._soporte_ciclo_vida_catalogo_014 import (
    crear_categoria,
    crear_producto,
    fijar_stock_sede,
    marcar_categoria,
    marcar_producto,
    sembrar_mundo_014,
)
from tests.api._soporte_sede_011 import identidad, sesion


@pytest.fixture
def mundo(motor, dos_instituciones):
    return sembrar_mundo_014(motor, dos_instituciones)


def _admin(datos):
    return identidad(
        "Administrador", datos["departamento_id"], datos["usuario_id"]
    )


_AUSENTE = object()


def _transicion(activo: bool, motivo=_AUSENTE) -> TransicionCatalogo:
    """Payload equivalente al HTTP: motivo omitible para la idempotencia."""
    if motivo is _AUSENTE:
        return TransicionCatalogo(activo=activo)
    return TransicionCatalogo(activo=activo, motivo=motivo)


def _historial_producto(motor, producto_id: int) -> list:
    with sesion(motor) as db:
        return db.execute(
            select(HistorialTransicionProducto)
            .where(HistorialTransicionProducto.producto_id == producto_id)
            .order_by(HistorialTransicionProducto.historial_producto_id)
        ).scalars().all()


# ---------------------------------------------------------------------------
# AC-13: alta vigente
# ---------------------------------------------------------------------------


def test_alta_de_producto_nace_activo_en_categoria_activa(motor, mundo):
    """AC-13: el alta vigente crea el producto en estado activo."""
    from app.schemas.producto_schema import ProductoCrear

    with sesion(motor) as db:
        producto = inventario_service.crear_producto(
            db,
            ProductoCrear(
                nombre="Alta 014",
                descripcion="Producto nuevo",
                unidad_medida="UNIDAD",
                stock_minimo=0,
                categoria_id=mundo["categoria_id"],
            ),
            _admin(mundo),
        )
        assert producto.activo is True
        assert db.get(Producto, producto.producto_id).activo is True


def test_alta_en_categoria_inactiva_responde_409_sin_escribir(motor, mundo):
    """AC-13: no se crea producto en una categoria retirada."""
    from app.schemas.producto_schema import ProductoCrear

    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada alta")
    marcar_categoria(motor, categoria, False)

    with sesion(motor) as db:
        productos_antes = db.execute(
            select(func.count()).select_from(Producto)
        ).scalar_one()
        with pytest.raises(Exception) as error:
            inventario_service.crear_producto(
                db,
                ProductoCrear(
                    nombre="No debe nacer",
                    descripcion="Categoria inactiva",
                    unidad_medida="UNIDAD",
                    stock_minimo=0,
                    categoria_id=categoria,
                ),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        assert db.execute(
            select(func.count()).select_from(Producto)
        ).scalar_one() == productos_antes


# ---------------------------------------------------------------------------
# AC-6: saldo cero en `stock_sede`
# ---------------------------------------------------------------------------


def test_baja_producto_sin_filas_de_stock_procede_y_escribe_historial(motor, mundo):
    """AC-6/AC-7: sin filas de stock el saldo es cero y la baja es efectiva."""
    producto = crear_producto(
        motor, mundo, nombre="Baja sin filas", stock_sede=None
    )

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Retiro sin existencias"),
            _admin(mundo),
        )
        assert resultado.activo is False

    filas = _historial_producto(motor, producto)
    assert len(filas) == 1, filas
    fila = filas[0]
    assert fila.activo_origen is True
    assert fila.activo_destino is False
    assert fila.motivo == "Retiro sin existencias"
    assert fila.usuario_id == mundo["usuario_id"]


def test_baja_producto_con_saldo_positivo_responde_409_sin_efectos(motor, mundo):
    """AC-6: cualquier fila de `stock_sede` con saldo distinto de cero bloquea."""
    producto = crear_producto(motor, mundo, nombre="Con saldo", stock_sede=7)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            inventario_service.transicionar_producto(
                db,
                producto,
                TransicionCatalogo(activo=False, motivo="Baja con saldo"),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        assert db.get(Producto, producto).activo is True
        fila = db.execute(
            select(StockSede).where(StockSede.producto_id == producto)
        ).scalar_one()
        assert fila.stock_actual == 7
    assert _historial_producto(motor, producto) == []


def test_baja_producto_con_saldos_en_cero_procede(motor, mundo):
    """AC-6: filas existentes todas en cero permiten la baja."""
    producto = crear_producto(motor, mundo, nombre="Saldo cero", stock_sede=0)

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Saldo cero en bodega"),
            _admin(mundo),
        )
        assert resultado.activo is False


def test_inventario_legado_positivo_no_impide_la_baja(motor, mundo):
    """AC-6: `inventario` legado no es saldo operativo y no participa."""
    base = mundo["producto_id"]
    fijar_stock_sede(motor, mundo, base, 0)
    with sesion(motor) as db:
        # El producto base conserva su fila legada con 50 unidades.
        assert db.execute(
            select(Inventario).where(Inventario.producto_id == base)
        ).scalars().all()

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db,
            base,
            TransicionCatalogo(activo=False, motivo="Solo queda inventario legado"),
            _admin(mundo),
        )
        assert resultado.activo is False


# ---------------------------------------------------------------------------
# AC-7: motivo de la transicion efectiva
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "motivo",
    [None, "", "   ", "x" * 501],
    ids=["nulo", "vacio", "solo_espacios", "501_caracteres"],
)
def test_motivo_invalido_responde_422_sin_cambios(motor, mundo, motivo):
    """AC-7: un motivo invalido responde 422 sin escribir estado ni historial."""
    producto = crear_producto(
        motor, mundo, nombre="Motivo invalido", stock_sede=None
    )

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            inventario_service.transicionar_producto(
                db,
                producto,
                TransicionCatalogo(activo=False, motivo=motivo),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 422
        db.rollback()

    with sesion(motor) as db:
        assert db.get(Producto, producto).activo is True
    assert _historial_producto(motor, producto) == []


def test_motivo_de_500_caracteres_se_persiste_literal(motor, mundo):
    """AC-7: el limite es 500 inclusive y el motivo se guarda sin recortar."""
    producto = crear_producto(
        motor, mundo, nombre="Motivo limite", stock_sede=None
    )
    motivo = "m" * 500

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo=motivo),
            _admin(mundo),
        )

    filas = _historial_producto(motor, producto)
    assert len(filas) == 1
    assert filas[0].motivo == motivo


# ---------------------------------------------------------------------------
# AC-8: idempotencia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "motivo",
    [_AUSENTE, None, "", "x" * 501],
    ids=["sin_motivo", "nulo", "vacio", "demasiado_largo"],
)
def test_repeticion_idempotente_no_exige_motivo_ni_escribe_historial(
    motor, mundo, motivo
):
    """AC-8: repetir el destino responde con el estado actual y sin historial."""
    producto = crear_producto(motor, mundo, nombre="Idempotente", stock_sede=None)

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Baja efectiva"),
            _admin(mundo),
        )

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db,
            producto,
            _transicion(False, motivo),
            _admin(mundo),
        )
        assert resultado.activo is False

    assert len(_historial_producto(motor, producto)) == 1


def test_idempotencia_no_evalua_la_precondicion_de_saldo(motor, mundo):
    """AC-8: un producto ya inactivo repite sin evaluar el saldo actual."""
    producto = crear_producto(
        motor, mundo, nombre="Inactivo con saldo", stock_sede=0
    )

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Baja con saldo cero"),
            _admin(mundo),
        )

    fijar_stock_sede(motor, mundo, producto, 9)

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db, producto, TransicionCatalogo(activo=False), _admin(mundo)
        )
        assert resultado.activo is False

    assert len(_historial_producto(motor, producto)) == 1


# ---------------------------------------------------------------------------
# AC-5: categoria <-> producto
# ---------------------------------------------------------------------------


def _historial_categoria(motor, categoria_id: int) -> list:
    with sesion(motor) as db:
        return db.execute(
            select(HistorialTransicionCategoria)
            .where(HistorialTransicionCategoria.categoria_id == categoria_id)
            .order_by(HistorialTransicionCategoria.historial_categoria_id)
        ).scalars().all()


def test_baja_categoria_con_producto_activo_responde_409(motor, mundo):
    """AC-5: una categoria con al menos un producto activo no se desactiva."""
    categoria = crear_categoria(motor, mundo, nombre="Con producto activo")
    crear_producto(
        motor, mundo, nombre="Activo de la categoria", categoria_id=categoria
    )

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            inventario_service.transicionar_categoria(
                db,
                categoria,
                TransicionCatalogo(activo=False, motivo="Intento con producto activo"),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        from app.models import Categoria

        assert db.get(Categoria, categoria).activo is True
    assert _historial_categoria(motor, categoria) == []


def test_baja_categoria_sin_productos_procede_y_reactivar_no_hace_cascada(
    motor, mundo
):
    """AC-5: la baja es valida y la reactivacion no reactiva productos."""
    categoria = crear_categoria(motor, mundo, nombre="Con productos retirados")
    producto = crear_producto(
        motor, mundo, nombre="Producto de la categoria", categoria_id=categoria
    )

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Retiro previo del producto"),
            _admin(mundo),
        )
        inventario_service.transicionar_categoria(
            db,
            categoria,
            TransicionCatalogo(activo=False, motivo="Retiro de la categoria"),
            _admin(mundo),
        )
        inventario_service.transicionar_categoria(
            db,
            categoria,
            TransicionCatalogo(activo=True, motivo="Reactivacion de la categoria"),
            _admin(mundo),
        )

    with sesion(motor) as db:
        from app.models import Categoria

        assert db.get(Categoria, categoria).activo is True
        assert db.get(Producto, producto).activo is False, (
            "reactivar la categoria no puede reactivar sus productos"
        )
    assert len(_historial_categoria(motor, categoria)) == 2


def test_reactivacion_producto_bajo_categoria_inactiva_responde_409(motor, mundo):
    """AC-5: no puede existir un producto activo bajo una categoria inactiva."""
    categoria = crear_categoria(motor, mundo, nombre="Categoria retirada")
    producto = crear_producto(
        motor,
        mundo,
        nombre="Producto retenido",
        categoria_id=categoria,
        stock_sede=None,
    )
    marcar_categoria(motor, categoria, False)
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            inventario_service.transicionar_producto(
                db,
                producto,
                TransicionCatalogo(
                    activo=True, motivo="Intento bajo categoria inactiva"
                ),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 409
        db.rollback()

    with sesion(motor) as db:
        assert db.get(Producto, producto).activo is False
    assert _historial_producto(motor, producto) == []


def test_reactivacion_producto_bajo_categoria_activa_procede(motor, mundo):
    """AC-5: con la categoria activa, la reactivacion es efectiva."""
    producto = crear_producto(
        motor, mundo, nombre="Reactivacion valida", stock_sede=None
    )
    marcar_producto(motor, producto, False)

    with sesion(motor) as db:
        resultado = inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=True, motivo="Reactivar el producto"),
            _admin(mundo),
        )
        assert resultado.activo is True

    filas = _historial_producto(motor, producto)
    assert len(filas) == 1
    assert filas[0].activo_origen is False
    assert filas[0].activo_destino is True


# ---------------------------------------------------------------------------
# AC-3/AC-12: 404 oculto y orden
# ---------------------------------------------------------------------------


def test_404_de_producto_ajeno_e_inexistente_es_identico(motor, mundo):
    """AC-3: un producto ajeno se oculta igual que uno inexistente."""
    for producto_id in (mundo["producto_homonimo_ajeno_id"], 999999):
        with sesion(motor) as db:
            with pytest.raises(Exception) as error:
                inventario_service.transicionar_producto(
                    db,
                    producto_id,
                    TransicionCatalogo(activo=False, motivo=""),
                    _admin(mundo),
                )
            assert getattr(error.value, "status_code", None) == 404
            assert getattr(error.value, "detail", None) == "Producto no encontrado"


def test_404_de_categoria_ajena_e_inexistente_es_identico(motor, mundo):
    """AC-3: una categoria ajena se oculta igual que una inexistente."""
    for categoria_id in (mundo["categoria_homonima_ajena_id"], 999999):
        with sesion(motor) as db:
            with pytest.raises(Exception) as error:
                inventario_service.transicionar_categoria(
                    db,
                    categoria_id,
                    TransicionCatalogo(activo=False, motivo=""),
                    _admin(mundo),
                )
            assert getattr(error.value, "status_code", None) == 404
            assert getattr(error.value, "detail", None) == "Categoria no encontrada"


def test_motivo_invalido_precede_a_la_precondicion_409(motor, mundo):
    """AC-3: con saldo positivo y motivo invalido gana el 422."""
    producto = crear_producto(motor, mundo, nombre="Dos fallos", stock_sede=5)

    with sesion(motor) as db:
        with pytest.raises(Exception) as error:
            inventario_service.transicionar_producto(
                db,
                producto,
                TransicionCatalogo(activo=False, motivo=""),
                _admin(mundo),
            )
        assert getattr(error.value, "status_code", None) == 422


# ---------------------------------------------------------------------------
# AC-12: historial
# ---------------------------------------------------------------------------


def test_historial_de_producto_ordena_reciente_primero_y_resuelve_actor(motor, mundo):
    """AC-12: historial completo, mas reciente primero, con actor resuelto."""
    producto = crear_producto(
        motor, mundo, nombre="Historial 014", stock_sede=None
    )

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Primera transicion"),
            _admin(mundo),
        )
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=True, motivo="Segunda transicion"),
            _admin(mundo),
        )

    with sesion(motor) as db:
        filas = inventario_service.listar_historial_producto(
            db, producto, _admin(mundo)
        )

    assert [fila.motivo for fila in filas] == [
        "Segunda transicion",
        "Primera transicion",
    ]
    assert filas[0].activo_origen is False
    assert filas[0].activo_destino is True
    assert filas[0].usuario_id == mundo["usuario_id"]
    assert filas[0].usuario_nombre == "Ana"
    assert filas[0].usuario_apellido == "Perez"
    assert filas[0].fecha_transicion is not None


def test_historial_de_categoria_registra_solo_sus_transiciones(motor, mundo):
    """AC-12: cada historial referencia exclusivamente su recurso."""
    categoria = crear_categoria(motor, mundo, nombre="Historial categoria")
    producto = crear_producto(
        motor,
        mundo,
        nombre="Producto de otra tabla",
        categoria_id=categoria,
        stock_sede=None,
    )

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Baja del producto"),
            _admin(mundo),
        )
        inventario_service.transicionar_categoria(
            db,
            categoria,
            TransicionCatalogo(activo=False, motivo="Baja de la categoria"),
            _admin(mundo),
        )

    with sesion(motor) as db:
        filas_categoria = inventario_service.listar_historial_categoria(
            db, categoria, _admin(mundo)
        )
        filas_producto = inventario_service.listar_historial_producto(
            db, producto, _admin(mundo)
        )

    assert len(filas_categoria) == 1
    assert filas_categoria[0].categoria_id == categoria
    assert filas_categoria[0].motivo == "Baja de la categoria"
    assert len(filas_producto) == 1
    assert filas_producto[0].producto_id == producto


# ---------------------------------------------------------------------------
# AC-15: listado de gestion
# ---------------------------------------------------------------------------


def test_gestion_incluye_activos_e_inactivos_del_tenant(motor, mundo):
    """AC-15: el listado administrativo devuelve ambos estados y aisla tenant."""
    producto = crear_producto(
        motor, mundo, nombre="Gestion producto", stock_sede=None
    )
    categoria = crear_categoria(motor, mundo, nombre="Gestion categoria")

    with sesion(motor) as db:
        inventario_service.transicionar_producto(
            db,
            producto,
            TransicionCatalogo(activo=False, motivo="Retiro para gestion"),
            _admin(mundo),
        )
        inventario_service.transicionar_categoria(
            db,
            categoria,
            TransicionCatalogo(activo=False, motivo="Retiro para gestion"),
            _admin(mundo),
        )

    with sesion(motor) as db:
        gestion = inventario_service.listar_gestion(db, _admin(mundo))

    productos = {fila.producto_id: fila for fila in gestion.productos}
    categorias = {fila.categoria_id: fila for fila in gestion.categorias}
    assert productos[producto].activo is False
    assert productos[mundo["producto_id"]].activo is True
    assert categorias[categoria].activo is False
    assert categorias[mundo["categoria_id"]].activo is True
    assert mundo["producto_homonimo_ajeno_id"] not in productos, (
        "el listado de gestion no puede incluir catalogo de otro tenant"
    )


# ---------------------------------------------------------------------------
# Atomicidad: estado y historial se confirman o revierten juntos
# ---------------------------------------------------------------------------


def test_fallo_al_escribir_el_historial_revierte_el_estado(motor, mundo):
    """AC-7/plan §2.4: sin actor persistido la FK falla y no queda estado parcial.

    El historial exige una FK real al usuario. Al forzar un actor inexistente,
    el `commit` unico falla: la fila de producto no puede quedar inactiva sin su
    transicion.
    """
    producto = crear_producto(
        motor, mundo, nombre="Atomicidad 014", stock_sede=None
    )
    actor_inexistente = identidad(
        "Administrador", mundo["departamento_id"], usuario_id=10_000_000
    )

    with sesion(motor) as db:
        with pytest.raises(IntegrityError):
            inventario_service.transicionar_producto(
                db,
                producto,
                TransicionCatalogo(activo=False, motivo="Transicion fallida"),
                actor_inexistente,
            )
        db.rollback()

    with sesion(motor) as db:
        assert db.get(Producto, producto).activo is True, (
            "el estado no puede persistirse sin su transicion de historial"
        )
        assert db.execute(
            select(func.count())
            .select_from(HistorialTransicionProducto)
            .where(HistorialTransicionProducto.producto_id == producto)
        ).scalar_one() == 0
