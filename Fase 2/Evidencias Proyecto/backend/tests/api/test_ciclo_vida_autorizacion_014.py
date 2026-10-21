"""T2 (Feature 014): autorizacion, matriz, gating, OpenAPI e historial (AC-2, AC-12, AC-14, AC-15).

Seam bajo prueba: la **matriz central** (`app.core.permisos.MATRIZ_PERMISOS`,
transcrita a mano desde la spec, nunca leida como fuente), el contrato
`/openapi.json`, el mapa de capacidades y la interfaz HTTP del `app` real.

La 014 agrega cinco operaciones aditivas, exclusivas del Administrador
Institucional (mutaciones, historiales y listado de gestion) y gated bajo la
capacidad `catalogo`; no modifica ninguna fila previa. Un rol sin permiso recibe
**403 antes de mirar el recurso**; un recurso ajeno y uno inexistente responden
**404 identico** para un rol autorizado. El historial es solo lectura y el
listado de gestion convive con los listados operativos, que siguen filtrados
para todos los roles, incluido el Administrador (AC-2/AC-12/AC-15).

Fase ROJA de TDD: hoy la matriz no declara las cinco operaciones, las rutas no
estan publicadas y el mapa de capacidades no las asocia; los tests fallan por
esas ausencias (con `pytest.fail` explicito o con el 404 del router), nunca por
imports ni sintaxis.
"""

from __future__ import annotations

import pytest

from app.core import capacidades, permisos

from ._soporte_ciclo_vida_catalogo_014 import (
    CAMPOS_HISTORIAL_CATEGORIA,
    CAMPOS_HISTORIAL_PRODUCTO,
    CAPACIDADES_014,
    CLAVES_GESTION,
    CORREO_GATING,
    DETALLE_CATEGORIA_NO_ENCONTRADA,
    DETALLE_PRODUCTO_NO_ENCONTRADO,
    OPERACIONES_014,
    RUTA_CATEGORIA_ESTADO,
    RUTA_CATEGORIA_HISTORIAL,
    RUTA_GESTION,
    RUTA_PRODUCTO_ESTADO,
    RUTA_PRODUCTO_HISTORIAL,
    SIN_AUTENTICAR,
    activo_de_producto,
    cliente_de_rol,
    crear_categoria,
    crear_producto,
    exigir_capacidad_asociada,
    exigir_operacion,
    exigir_ruta,
    historial_categoria,
    historial_producto,
    listado_gestion,
    marcar_categoria,
    sembrar_contexto_capacidades,
    sembrar_mundo_014,
    transicionar_categoria,
    transicionar_producto,
)
from ._soporte_ciclo_vida_013 import OPERACIONES_013
from .test_ciclo_vida_autorizacion_013 import RETIRADAS_017
from .test_permisos_012 import MATRIZ_012

#: Metodos que FastAPI publica en `/openapi.json`.
_METODOS_OPENAPI = {"get", "put", "post", "delete", "patch"}
_PREFIJO_CONTRATO = "/api/v1/"


@pytest.fixture
def mundo(motor, dos_instituciones):
    return sembrar_mundo_014(motor, dos_instituciones)


def _admin(motor, datos, **opciones):
    return cliente_de_rol(motor, datos, "Administrador", **opciones)


def _cli(motor, datos, rol, **opciones):
    return cliente_de_rol(motor, datos, rol, **opciones)


# ---------------------------------------------------------------------------
# AC-2: matriz central aditiva
# ---------------------------------------------------------------------------


def test_matriz_declara_las_cinco_operaciones_exclusivas_del_administrador_ac_2():
    """AC-2/AC-12/AC-15: los roles de cada operacion nueva son los de la spec."""
    for clave, roles in OPERACIONES_014.items():
        obtenidos = permisos.MATRIZ_PERMISOS.get(clave)
        if obtenidos is None:
            pytest.fail(
                f"capacidad ausente (T6): MATRIZ_PERMISOS no declara {clave}; "
                "la Feature 014 la agrega en T6 con los roles de la spec."
            )
        assert set(obtenidos) == roles, (clave, sorted(obtenidos), sorted(roles))


def test_matriz_conserva_las_operaciones_previas_intactas_ac_2():
    """AC-2: la 014 solo agrega filas; ninguna operacion previa cambia."""
    for clave in OPERACIONES_014:
        exigir_operacion(*clave)
    for clave, roles in MATRIZ_012.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion {clave} desaparecio de la matriz"
        esperado = set(roles) - ({"Superadmin"} if clave in RETIRADAS_017 else set())
        assert set(actual) == esperado, clave
    for clave, roles in OPERACIONES_013.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion de la 013 {clave} desaparecio"
        assert set(actual) == roles, clave


def test_matriz_tiene_exactamente_60_operaciones_tras_014():
    """AC-2: 55 previas + las 5 nuevas de la 014.

    El nombre conserva el baseline historico de la 014, pero el total absoluto se
    amplia **explicitamente** a 61 por la Feature 018 (spec D-6/AC-8, plan §1.4):
    la 018 agrega `GET /api/v1/inventario/ambito` sin cambiar ninguna fila de la
    014. No es una reescritura silenciosa del contrato, es una ampliacion
    documentada.
    """
    total = len(permisos.MATRIZ_PERMISOS)
    assert total == 61, (
        "la matriz debe tener 61 operaciones (55 previas + 5 de la 014 + la de "
        f"ambito de la 018); tiene {total}"
    )


def test_capacidad_catalogo_asociada_a_las_cinco_operaciones_ac_2():
    """AC-2/plan §2.6: toda operacion nueva queda gated bajo `catalogo`."""
    for clave, esperada in CAPACIDADES_014.items():
        exigir_capacidad_asociada(*clave)
        assert capacidades.capacidad_de_operacion(*clave) == esperada, clave


# ---------------------------------------------------------------------------
# AC-14: contrato OpenAPI
# ---------------------------------------------------------------------------


def test_openapi_publica_las_cinco_operaciones_ac_14(cliente):
    """AC-14: las cinco rutas nuevas estan publicadas en `/openapi.json`."""
    contrato = cliente.get("/openapi.json").json()
    for metodo, ruta in OPERACIONES_014:
        operaciones = contrato["paths"].get(ruta, {})
        if metodo.lower() not in operaciones:
            pytest.fail(
                f"capacidad ausente (T9): {metodo} {ruta} no esta publicada en "
                "/openapi.json; la Feature 014 la cablea en T9."
            )


def test_openapi_tiene_60_operaciones_tras_014(cliente):
    """AC-14: el contrato v1 publica las operaciones de la matriz vigente.

    El nombre conserva el baseline historico de la 014; el total absoluto se
    amplia **explicitamente** a 61 por la Feature 018 (spec D-6/AC-8, plan §1.4),
    que publica `GET /api/v1/inventario/ambito` sin alterar las cinco rutas de la
    014. Ampliacion documentada, no reescritura silenciosa.
    """
    contrato = cliente.get("/openapi.json").json()
    total = sum(
        1
        for ruta, operaciones in contrato["paths"].items()
        if ruta.startswith(_PREFIJO_CONTRATO)
        for metodo in operaciones
        if metodo in _METODOS_OPENAPI
    )
    assert total == 61, f"/openapi.json debe publicar 61 operaciones v1; publica {total}"


@pytest.mark.parametrize(
    "clave",
    [
        ("PATCH", RUTA_PRODUCTO_ESTADO),
        ("PATCH", RUTA_CATEGORIA_ESTADO),
        ("GET", RUTA_PRODUCTO_HISTORIAL),
        ("GET", RUTA_CATEGORIA_HISTORIAL),
    ],
)
def test_openapi_documenta_errores_de_mutaciones_e_historial_ac_14(cliente, clave):
    """AC-14: mutaciones e historial documentan 401/403/404, y ademas 409/422."""
    metodo, ruta = clave
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"].get(ruta, {}).get(metodo.lower())
    if operacion is None:
        pytest.fail(
            f"capacidad ausente (T9): {metodo} {ruta} no esta publicada en "
            "/openapi.json; la Feature 014 la cablea en T9."
        )
    respuestas = set(operacion.get("responses", {}))
    descripcion = operacion.get("description", "")
    assert {"401", "403", "404"} <= respuestas, (clave, sorted(respuestas))
    assert "409" in respuestas or "409" in descripcion, (clave, sorted(respuestas))
    assert "422" in respuestas or "422" in descripcion, (clave, sorted(respuestas))


def test_openapi_documenta_gestion_con_401_y_403_ac_14(cliente):
    """AC-14: el listado de gestion documenta exito, autenticacion y autorizacion."""
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"].get(RUTA_GESTION, {}).get("get")
    if operacion is None:
        pytest.fail(
            f"capacidad ausente (T9): GET {RUTA_GESTION} no esta publicada en "
            "/openapi.json; la Feature 014 la cablea en T9."
        )
    respuestas = set(operacion.get("responses", {}))
    assert {"200", "401", "403"} <= respuestas, sorted(respuestas)


@pytest.mark.parametrize("ruta", [RUTA_PRODUCTO_HISTORIAL, RUTA_CATEGORIA_HISTORIAL])
def test_historial_no_expone_escritura_ac_12(motor, mundo, ruta):
    """AC-12/D-8: las tablas de historial son inmutables y de solo lectura por API."""
    exigir_ruta(ruta, "GET")
    from app.main import app

    operaciones = app.openapi().get("paths", {}).get(ruta, {})
    assert set(operaciones) <= {"get"}, (
        f"el historial no admite escritura publica: {sorted(operaciones)}"
    )


# ---------------------------------------------------------------------------
# AC-2: autenticacion y autorizacion antes del recurso
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clave",
    [
        ("PATCH", RUTA_PRODUCTO_ESTADO),
        ("PATCH", RUTA_CATEGORIA_ESTADO),
        ("GET", RUTA_PRODUCTO_HISTORIAL),
        ("GET", RUTA_CATEGORIA_HISTORIAL),
        ("GET", RUTA_GESTION),
    ],
)
def test_sin_sesion_responde_401_ac_2(motor, mundo, clave):
    """AC-2: toda operacion nueva exige autenticacion."""
    metodo, ruta = clave
    exigir_ruta(ruta, metodo)
    ruta_concreta = ruta.format(producto_id=1, categoria_id=1)
    with cliente_de_rol(motor, mundo, SIN_AUTENTICAR) as cliente:
        respuesta = cliente.request(metodo, ruta_concreta, json={"activo": False})
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante", "Superadmin"])
def test_mutacion_de_rol_no_administrador_recibe_403_antes_del_recurso(
    motor, mundo, rol
):
    """AC-2: el 403 de matriz precede a la existencia del recurso.

    Se usa un id inexistente a proposito: si la respuesta fuese 404, el rol
    estaria mirando el recurso antes de autorizarse.
    """
    exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
    with _cli(motor, mundo, rol) as cliente:
        producto = transicionar_producto(
            cliente, 999999, activo=False, motivo="Rol sin permiso"
        )
        assert producto.status_code == 403, producto.text

        exigir_ruta(RUTA_CATEGORIA_ESTADO, "PATCH")
        categoria = transicionar_categoria(
            cliente, 999999, activo=False, motivo="Rol sin permiso"
        )
        assert categoria.status_code == 403, categoria.text


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante", "Superadmin"])
def test_historial_y_gestion_reciben_403_para_no_administradores_ac_12_15(
    motor, mundo, rol
):
    """AC-12/AC-15: Bodeguero, Solicitante y Superadmin no leen historial ni gestion."""
    exigir_ruta(RUTA_PRODUCTO_HISTORIAL, "GET")
    exigir_ruta(RUTA_CATEGORIA_HISTORIAL, "GET")
    exigir_ruta(RUTA_GESTION, "GET")
    with _cli(motor, mundo, rol) as cliente:
        for ruta in (
            RUTA_PRODUCTO_HISTORIAL.format(producto_id=999999),
            RUTA_CATEGORIA_HISTORIAL.format(categoria_id=999999),
            RUTA_GESTION,
        ):
            respuesta = cliente.get(ruta)
            assert respuesta.status_code == 403, (ruta, respuesta.text)


# ---------------------------------------------------------------------------
# AC-2: 404 identico (inexistente vs ajeno)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recurso",
    ["producto_mutacion", "categoria_mutacion", "producto_historial", "categoria_historial"],
)
def test_recurso_ajeno_e_inexistente_responden_404_identico_ac_2(motor, mundo, recurso):
    """AC-2/AC-12: un recurso de otro tenant se oculta igual que uno inexistente."""
    with _admin(motor, mundo) as cliente:
        if recurso == "producto_mutacion":
            exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
            ajeno = transicionar_producto(
                cliente, mundo["producto_homonimo_ajeno_id"], activo=False, motivo="x"
            )
            inexistente = transicionar_producto(
                cliente, 999999, activo=False, motivo="x"
            )
            detalle = DETALLE_PRODUCTO_NO_ENCONTRADO
        elif recurso == "categoria_mutacion":
            exigir_ruta(RUTA_CATEGORIA_ESTADO, "PATCH")
            ajeno = transicionar_categoria(
                cliente, mundo["categoria_homonima_ajena_id"], activo=False, motivo="x"
            )
            inexistente = transicionar_categoria(
                cliente, 999999, activo=False, motivo="x"
            )
            detalle = DETALLE_CATEGORIA_NO_ENCONTRADA
        elif recurso == "producto_historial":
            exigir_ruta(RUTA_PRODUCTO_HISTORIAL, "GET")
            ajeno = cliente.get(
                RUTA_PRODUCTO_HISTORIAL.format(
                    producto_id=mundo["producto_homonimo_ajeno_id"]
                )
            )
            inexistente = cliente.get(
                RUTA_PRODUCTO_HISTORIAL.format(producto_id=999999)
            )
            detalle = DETALLE_PRODUCTO_NO_ENCONTRADO
        else:
            exigir_ruta(RUTA_CATEGORIA_HISTORIAL, "GET")
            ajeno = cliente.get(
                RUTA_CATEGORIA_HISTORIAL.format(
                    categoria_id=mundo["categoria_homonima_ajena_id"]
                )
            )
            inexistente = cliente.get(
                RUTA_CATEGORIA_HISTORIAL.format(categoria_id=999999)
            )
            detalle = DETALLE_CATEGORIA_NO_ENCONTRADA

        assert ajeno.status_code == 404, ajeno.text
        assert inexistente.status_code == 404, inexistente.text
        assert ajeno.json()["detail"] == detalle
        assert inexistente.json()["detail"] == ajeno.json()["detail"]


# ---------------------------------------------------------------------------
# AC-2: gating de la capacidad `catalogo`
# ---------------------------------------------------------------------------


def test_capacidad_catalogo_apagada_bloquea_las_cinco_operaciones_sin_mutar_ac_2(
    motor, mundo
):
    """AC-2/plan §2.6: capacidad apagada -> 403 sin estado ni historial."""
    sembrar_contexto_capacidades(motor, mundo, frozenset({"catalogo"}))
    producto = crear_producto(motor, mundo, nombre="Gated 014", stock_sede=None)
    categoria = crear_categoria(motor, mundo, nombre="Categoria gated")

    with _admin(motor, mundo, correo=CORREO_GATING) as cliente:
        exigir_ruta(RUTA_PRODUCTO_ESTADO, "PATCH")
        respuesta_producto = transicionar_producto(
            cliente, producto, activo=False, motivo="Capacidad apagada"
        )
        respuesta_categoria = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Capacidad apagada"
        )
        respuesta_historial = cliente.get(
            RUTA_PRODUCTO_HISTORIAL.format(producto_id=producto)
        )
        respuesta_historial_categoria = cliente.get(
            RUTA_CATEGORIA_HISTORIAL.format(categoria_id=categoria)
        )
        respuesta_gestion = cliente.get(RUTA_GESTION)

        for respuesta in (
            respuesta_producto,
            respuesta_categoria,
            respuesta_historial,
            respuesta_historial_categoria,
            respuesta_gestion,
        ):
            assert respuesta.status_code == 403, respuesta.text

        assert activo_de_producto(motor, producto) is True, (
            "el 403 de gating no puede mutar el estado"
        )
    with _admin(motor, mundo) as cliente:
        assert historial_producto(cliente, producto) == []
        assert historial_categoria(cliente, categoria) == []


# ---------------------------------------------------------------------------
# AC-12/AC-15: historial correcto y listado de gestion
# ---------------------------------------------------------------------------


def test_historial_devuelve_las_transiciones_recientes_primero_ac_12(motor, mundo):
    """AC-12: orden determinista y campos completos de actor/recurso/estado/motivo."""
    producto = crear_producto(motor, mundo, nombre="Historial 014", stock_sede=None)

    with _admin(motor, mundo) as cliente:
        assert historial_producto(cliente, producto) == [], (
            "un recurso sin transiciones expone una lista vacia"
        )
        baja = transicionar_producto(
            cliente, producto, activo=False, motivo="Primera transicion"
        )
        assert baja.status_code == 200, baja.text
        alta = transicionar_producto(
            cliente, producto, activo=True, motivo="Segunda transicion"
        )
        assert alta.status_code == 200, alta.text

        filas = historial_producto(cliente, producto)
        assert len(filas) == 2, filas
        for fila in filas:
            assert CAMPOS_HISTORIAL_PRODUCTO <= set(fila), sorted(fila)
            assert fila["producto_id"] == producto
            assert fila["usuario_id"] == mundo["usuario_id"]
            assert fila["fecha_transicion"] is not None
        assert [fila["motivo"] for fila in filas] == [
            "Segunda transicion",
            "Primera transicion",
        ], "el historial se ordena mas reciente primero"
        assert filas[0]["activo_origen"] is False
        assert filas[0]["activo_destino"] is True


def test_historial_de_categoria_registra_solo_sus_transiciones_ac_12(motor, mundo):
    """AC-12: cada historial referencia exclusivamente su recurso."""
    categoria = crear_categoria(motor, mundo, nombre="Historial categoria")
    producto = crear_producto(
        motor, mundo, nombre="Producto de otra tabla", categoria_id=categoria,
        stock_sede=None,
    )

    with _admin(motor, mundo) as cliente:
        transicion_producto = transicionar_producto(
            cliente, producto, activo=False, motivo="Baja del producto"
        )
        assert transicion_producto.status_code == 200, transicion_producto.text
        transicion_categoria = transicionar_categoria(
            cliente, categoria, activo=False, motivo="Baja de la categoria"
        )
        assert transicion_categoria.status_code == 200, transicion_categoria.text

        filas_categoria = historial_categoria(cliente, categoria)
        assert len(filas_categoria) == 1, filas_categoria
        assert CAMPOS_HISTORIAL_CATEGORIA <= set(filas_categoria[0])
        assert filas_categoria[0]["categoria_id"] == categoria
        assert filas_categoria[0]["motivo"] == "Baja de la categoria"

        filas_producto = historial_producto(cliente, producto)
        assert len(filas_producto) == 1, filas_producto
        assert filas_producto[0]["producto_id"] == producto


def test_gestion_incluye_activos_e_inactivos_solo_para_administrador_ac_15(motor, mundo):
    """AC-15: gestion devuelve ambos estados; la operativa sigue filtrada."""
    producto = crear_producto(motor, mundo, nombre="Gestion producto", stock_sede=None)
    categoria = crear_categoria(motor, mundo, nombre="Gestion categoria")

    with _admin(motor, mundo) as cliente:
        assert transicionar_producto(
            cliente, producto, activo=False, motivo="Retiro para gestion"
        ).status_code == 200
        assert transicionar_categoria(
            cliente, categoria, activo=False, motivo="Retiro para gestion"
        ).status_code == 200

        gestion = listado_gestion(cliente)
        assert CLAVES_GESTION <= set(gestion), sorted(gestion)
        productos = {fila["producto_id"]: fila for fila in gestion["productos"]}
        categorias = {fila["categoria_id"]: fila for fila in gestion["categorias"]}
        assert productos[producto]["activo"] is False, productos[producto]
        assert productos[mundo["producto_id"]]["activo"] is True
        assert categorias[categoria]["activo"] is False, categorias[categoria]
        assert categorias[mundo["categoria_id"]]["activo"] is True

        operativos = cliente.get("/api/v1/inventario/productos")
        assert operativos.status_code == 200, operativos.text
        ids_operativos = {fila["producto_id"] for fila in operativos.json()}
        assert producto not in ids_operativos, (
            "el listado operativo sigue filtrado tambien para el Administrador"
        )
