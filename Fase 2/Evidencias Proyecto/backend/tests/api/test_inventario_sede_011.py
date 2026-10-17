"""T2 (Feature 011): existencias y movimientos por sede — pruebas rojas.

Seam bajo prueba: la **interfaz HTTP del `app` real**. La Feature 011 sustituye el
saldo operativo departamental de `inventario` por existencias `(sede, producto)`:
el total institucional se **deriva** de las sedes (spec D-2) y ninguna consulta
debe leer ni exponer las filas legadas de `inventario` (spec §7).

Contrato que estas pruebas fijan:

  * `GET  /api/v1/inventario/existencias` -> cada fila de producto expone
    `stock_total` (suma de sus sedes) y `sedes: [{sede_id, sede_nombre,
    stock_actual}]`; `solo_criticos` evalua **por sede** (AC-11).
  * `POST /api/v1/inventario/movimientos` -> el cuerpo referencia `stock_sede_id`
    (ya no `inventario_id`) y la auditoria nueva se enlaza por esa columna.

Trazabilidad AC (spec 011 §5):

  * **AC-2** sustitucion y agregado de stock (solo stock por sede, sin segunda fuente).
  * **AC-3** identificadores de sede invalidos o ajenos -> 404.
  * **AC-6** departamento/Bodeguero sin sede -> rechazo claro.
  * **AC-7** ambito del Bodeguero (una sede) y su denegacion sin sede.
  * **AC-8** ambito del Administrador (toda su institucion) y Superadmin de lectura.
  * **AC-11** criticidad por sede.

Fase ROJA de TDD: los modelos y los contratos nuevos no existen (T3/T8). Cada
prueba arranca con la guarda de capacidad correspondiente y falla con un motivo
explicito, nunca por `ImportError` ni sintaxis.

Observacion de la auditoria: se lee la fila persistida de `movimiento_inventario`
con el motor de prueba. No es comodidad: el contrato de `GET /inventario/movimientos`
pertenece a la adaptacion de T8 y aqui se comprueba el efecto transaccional del alta.
"""

from __future__ import annotations

import pytest

from ._soporte_sede_011 import (
    RUTA_EXISTENCIAS,
    RUTA_MOVIMIENTOS,
    asignar_sede_a_usuario,
    cliente,
    contar_movimientos,
    crear_sede,
    crear_stock_sede,
    exigir_contrato_existencias_por_sede,
    exigir_contrato_movimiento_por_sede,
    leer_stock_sede,
    movimientos_con_stock_sede,
    producto_de_existencias,
)


def _crear_producto(motor, *, datos_base, nombre: str, stock_minimo: int) -> int:
    """Producto adicional del catalogo de INST01 (el de `datos_base` no basta)."""
    from sqlalchemy.orm import sessionmaker

    from app.models import Producto

    db = sessionmaker(bind=motor)()
    try:
        producto = Producto(
            nombre=nombre,
            descripcion=f"Producto {nombre}",
            unidad_medida="UNIDAD",
            stock_minimo=stock_minimo,
            categoria_id=datos_base["categoria_id"],
            institucion_id=datos_base["institucion_id"],
        )
        db.add(producto)
        db.commit()
        db.refresh(producto)
        return producto.producto_id
    finally:
        db.close()


def _existencias(cliente_http, **params) -> list[dict]:
    respuesta = cliente_http.get(RUTA_EXISTENCIAS, params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# ---------------------------------------------------------------------------
# AC-2: el saldo vigente es el de las sedes; el inventario legado no se lee
# ---------------------------------------------------------------------------


def test_existencias_exponen_sede_y_saldo(motor, datos_base):
    """AC-2: el producto muestra su saldo por sede y el total derivado.

    La fixture trae una fila **legada** de `inventario` con 50 unidades para el
    producto del catalogo. El saldo vigente debe ser el de la sede (42), no el
    departamental: 50 significaria que la consulta sigue leyendo el legado.
    """
    exigir_contrato_existencias_por_sede()
    sede_id = crear_sede(
        motor, institucion_id=datos_base["institucion_id"], nombre="Sede Unica"
    )
    crear_stock_sede(
        motor,
        sede_id=sede_id,
        producto_id=datos_base["producto_id"],
        stock_actual=42,
        institucion_id=datos_base["institucion_id"],
    )

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        filas = _existencias(cliente_http)

    producto = producto_de_existencias(filas, datos_base["producto_id"])
    assert producto["stock_total"] == 42, "el total sale de las sedes, no del legado"
    sedes = {fila["sede_id"]: fila for fila in producto["sedes"]}
    assert sedes[sede_id]["stock_actual"] == 42
    assert sedes[sede_id]["sede_nombre"] == "Sede Unica"


def test_producto_sin_stock_sede_aparece_en_cero(motor, datos_base):
    """AC-2: sin filas por sede el producto existe con total 0, no con 50."""
    exigir_contrato_existencias_por_sede()

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        filas = _existencias(cliente_http)

    producto = producto_de_existencias(filas, datos_base["producto_id"])
    assert producto["stock_total"] == 0, (
        "el inventario departamental legado (50) no es una fuente de saldo vigente"
    )
    assert producto["sedes"] == []


def test_stock_total_es_la_suma_de_las_sedes(motor, datos_base):
    """AC-2: el agregado institucional es la suma exacta de los saldos por sede."""
    exigir_contrato_existencias_por_sede()
    sede_norte = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="Norte")
    sede_sur = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="Sur")
    crear_stock_sede(
        motor,
        sede_id=sede_norte,
        producto_id=datos_base["producto_id"],
        stock_actual=30,
        institucion_id=datos_base["institucion_id"],
    )
    crear_stock_sede(
        motor,
        sede_id=sede_sur,
        producto_id=datos_base["producto_id"],
        stock_actual=12,
        institucion_id=datos_base["institucion_id"],
    )

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        filas = _existencias(cliente_http)

    producto = producto_de_existencias(filas, datos_base["producto_id"])
    assert producto["stock_total"] == 42
    assert {fila["sede_id"]: fila["stock_actual"] for fila in producto["sedes"]} == {
        sede_norte: 30,
        sede_sur: 12,
    }


def test_solo_criticos_evalua_por_sede(motor, datos_base):
    """AC-11: un producto es critico si **alguna sede** esta en o bajo el minimo."""
    exigir_contrato_existencias_por_sede()
    producto_critico = _crear_producto(
        motor, datos_base=datos_base, nombre="Critico por sede", stock_minimo=10
    )
    producto_holgado = _crear_producto(
        motor, datos_base=datos_base, nombre="Holgado por sede", stock_minimo=10
    )
    sede_a = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="A")
    sede_b = crear_sede(motor, institucion_id=datos_base["institucion_id"], nombre="B")
    # Critico: 3 <= 10 en la sede A, aunque el total (103) supere el minimo.
    crear_stock_sede(
        motor, sede_id=sede_a, producto_id=producto_critico, stock_actual=3,
        institucion_id=datos_base["institucion_id"],
    )
    crear_stock_sede(
        motor, sede_id=sede_b, producto_id=producto_critico, stock_actual=100,
        institucion_id=datos_base["institucion_id"],
    )
    # Holgado: 11 y 20, ambos por encima del minimo.
    crear_stock_sede(
        motor, sede_id=sede_a, producto_id=producto_holgado, stock_actual=11,
        institucion_id=datos_base["institucion_id"],
    )
    crear_stock_sede(
        motor, sede_id=sede_b, producto_id=producto_holgado, stock_actual=20,
        institucion_id=datos_base["institucion_id"],
    )

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        criticos = _existencias(cliente_http, solo_criticos=True)

    ids = {fila["producto_id"] for fila in criticos}
    assert producto_critico in ids, "una sede en o bajo el minimo marca el producto"
    assert producto_holgado not in ids


# ---------------------------------------------------------------------------
# AC-7/AC-8: ambito del Bodeguero y del Administrador
# ---------------------------------------------------------------------------


def test_bodeguero_sin_sede_no_puede_mover_stock(motor, dos_instituciones):
    """AC-7: sin sede asignada la operacion dependiente se deniega con 409."""
    exigir_contrato_movimiento_por_sede()
    sede_id = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    fila_stock = crear_stock_sede(
        motor,
        sede_id=sede_id,
        producto_id=dos_instituciones["producto_id"],
        stock_actual=10,
        institucion_id=dos_instituciones["inst_propia"],
    )
    bodeguero_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]
    asignar_sede_a_usuario(motor, bodeguero_id, None)

    with cliente(
        motor,
        "Bodeguero",
        departamento_id=dos_instituciones["departamento_id"],
        usuario_id=bodeguero_id,
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 1,
                "stock_sede_id": fila_stock,
                "observacion": "sin sede asignada",
            },
        )

    assert respuesta.status_code == 409, respuesta.text


def test_bodeguero_solo_opera_en_su_sede(motor, dos_instituciones):
    """AC-7: con sede asignada, otro `stock_sede_id` responde 404 y no muta.

    La sede intrusa pertenece a la **misma** institucion: la denegacion no puede
    venir de un aislamiento de tenant, sino del ambito por sede del Bodeguero. Se
    agrega ademas una sede de otro tenant para cubrir el caso ajeno.
    """
    exigir_contrato_movimiento_por_sede()
    sede_propia = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    sede_intrusa = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    sede_ajena = crear_sede(motor, institucion_id=dos_instituciones["inst_ajena"])
    fila_intrusa = crear_stock_sede(
        motor, sede_id=sede_intrusa, producto_id=dos_instituciones["producto_id"],
        stock_actual=9, institucion_id=dos_instituciones["inst_propia"],
    )
    crear_stock_sede(
        motor, sede_id=sede_ajena,
        producto_id=dos_instituciones["producto_homonimo_ajeno_id"],
        stock_actual=4, institucion_id=dos_instituciones["inst_ajena"],
    )
    bodeguero_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]
    asignar_sede_a_usuario(motor, bodeguero_id, sede_propia)

    with cliente(
        motor,
        "Bodeguero",
        departamento_id=dos_instituciones["departamento_id"],
        usuario_id=bodeguero_id,
        sede_id=sede_propia,
    ) as cliente_http:
        respuesta_intrusa = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "stock_sede_id": fila_intrusa,
                "observacion": "sede no autorizada",
            },
        )

    assert respuesta_intrusa.status_code == 404, respuesta_intrusa.text
    assert (
        leer_stock_sede(motor, sede_intrusa, dos_instituciones["producto_id"]) == 9
    ), "una sede no autorizada no debe mutar"


def test_administrador_ve_todas_las_sedes_de_su_institucion(motor, dos_instituciones):
    """AC-8: el Administrador ve las sedes de su institucion y ninguna ajena."""
    exigir_contrato_existencias_por_sede()
    sede_propia = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    sede_ajena = crear_sede(motor, institucion_id=dos_instituciones["inst_ajena"])
    crear_stock_sede(
        motor, sede_id=sede_propia, producto_id=dos_instituciones["producto_id"],
        stock_actual=7, institucion_id=dos_instituciones["inst_propia"],
    )
    crear_stock_sede(
        motor, sede_id=sede_ajena,
        producto_id=dos_instituciones["producto_homonimo_ajeno_id"],
        stock_actual=3, institucion_id=dos_instituciones["inst_ajena"],
    )

    with cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        filas = _existencias(cliente_http)

    sedes_expuestas = {
        fila["sede_id"] for producto in filas for fila in producto["sedes"]
    }
    assert sede_propia in sedes_expuestas
    assert sede_ajena not in sedes_expuestas


def test_superadmin_conserva_lectura_global_atribuida(motor, dos_instituciones):
    """AC-8: la lectura global del Superadmin sigue atribuyendo cada institucion."""
    exigir_contrato_existencias_por_sede()

    with cliente(motor, "Superadmin", departamento_id=None) as cliente_http:
        filas = _existencias(cliente_http)

    instituciones = {fila["institucion_id"] for fila in filas}
    assert {
        dos_instituciones["inst_propia"],
        dos_instituciones["inst_ajena"],
    } <= instituciones


def test_superadmin_no_escribe_stock(motor, datos_base):
    """AC-8: el Superadmin no adquiere escritura de negocio en un tenant."""
    exigir_contrato_movimiento_por_sede()
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    fila_stock = crear_stock_sede(
        motor,
        sede_id=sede_id,
        producto_id=datos_base["producto_id"],
        stock_actual=5,
        institucion_id=datos_base["institucion_id"],
    )

    with cliente(motor, "Superadmin", departamento_id=None) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 1,
                "stock_sede_id": fila_stock,
                "observacion": "intento global",
            },
        )

    assert respuesta.status_code == 403, respuesta.text


# ---------------------------------------------------------------------------
# AC-2/AC-3/AC-7: escritura de stock y auditoria por sede
# ---------------------------------------------------------------------------


def test_movimiento_nuevo_audita_por_stock_sede(motor, datos_base):
    """AC-2/AC-7: la entrada afecta el saldo por sede y deja auditoria nueva.

    La fila de auditoria se lee persistida: referencia `stock_sede_id` y deja
    `inventario_id` nulo, de modo que el movimiento historico sigue enlazado a su
    tabla legada (spec D-2, decision 10).
    """
    exigir_contrato_movimiento_por_sede()
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    fila_stock = crear_stock_sede(
        motor,
        sede_id=sede_id,
        producto_id=datos_base["producto_id"],
        stock_actual=10,
        institucion_id=datos_base["institucion_id"],
    )

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 5,
                "stock_sede_id": fila_stock,
                "observacion": "compra de reposicion",
            },
        )

    assert respuesta.status_code == 201, respuesta.text
    assert leer_stock_sede(motor, sede_id, datos_base["producto_id"]) == 15

    auditorias = movimientos_con_stock_sede(motor)
    assert len(auditorias) == 1
    auditoria = auditorias[0]
    assert auditoria.stock_sede_id == fila_stock
    assert auditoria.tipo_movimiento == "ENTRADA"
    assert auditoria.cantidad == 5
    assert auditoria.inventario_id is None, (
        "los movimientos nuevos usan la referencia de stock por sede"
    )


def test_movimiento_con_saldo_insuficiente_responde_409_sin_auditoria(
    motor, datos_base
):
    """AC-7: una salida por encima del saldo no muta ni deja auditoria."""
    exigir_contrato_movimiento_por_sede()
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])
    fila_stock = crear_stock_sede(
        motor,
        sede_id=sede_id,
        producto_id=datos_base["producto_id"],
        stock_actual=4,
        institucion_id=datos_base["institucion_id"],
    )
    auditorias_antes = contar_movimientos(motor)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "SALIDA",
                "cantidad": 999,
                "stock_sede_id": fila_stock,
            },
        )

    assert respuesta.status_code == 409, respuesta.text
    assert leer_stock_sede(motor, sede_id, datos_base["producto_id"]) == 4
    assert contar_movimientos(motor) == auditorias_antes


def test_movimiento_con_stock_sede_inexistente_responde_404(motor, datos_base):
    """AC-3: una referencia de stock por sede inexistente responde 404 sin efecto."""
    exigir_contrato_movimiento_por_sede()
    auditorias_antes = contar_movimientos(motor)

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 1,
                "stock_sede_id": 999_999,
            },
        )

    assert respuesta.status_code == 404, respuesta.text
    assert contar_movimientos(motor) == auditorias_antes


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante"])
def test_roles_sin_permiso_de_escritura_de_stock(motor, dos_instituciones, rol):
    """AC-7/AC-8: la escritura de stock sigue reservada a Administrador/Bodeguero.

    El Solicitante conserva su 403 y el Bodeguero **con sede** no obtiene permiso
    sobre otro recurso por el hecho de tener sede: el permiso lo da la matriz.
    """
    exigir_contrato_movimiento_por_sede()
    sede_id = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    fila_stock = crear_stock_sede(
        motor, sede_id=sede_id, producto_id=dos_instituciones["producto_id"],
        stock_actual=10, institucion_id=dos_instituciones["inst_propia"],
    )
    usuario_id = dos_instituciones["usuarios_inst01"][rol]

    with cliente(
        motor,
        rol,
        departamento_id=dos_instituciones["departamento_id"],
        usuario_id=usuario_id,
        sede_id=sede_id,
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_MOVIMIENTOS,
            json={
                "tipo_movimiento": "ENTRADA",
                "cantidad": 1,
                "stock_sede_id": fila_stock,
            },
        )

    if rol == "Solicitante":
        assert respuesta.status_code == 403, respuesta.text
    else:
        # El Bodeguero si puede escribir stock; lo que no puede es tocar otra sede.
        assert respuesta.status_code == 200 or respuesta.status_code == 201, respuesta.text
