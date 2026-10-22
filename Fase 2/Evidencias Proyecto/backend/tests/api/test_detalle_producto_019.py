"""T1 (Feature 019): detalle de producto por alcance — pruebas rojas.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), igual que el
resto de la suite. La Feature 019 agrega **una** lectura aditiva
(`GET /api/v1/inventario/existencias/{producto_id}`) que devuelve el producto del
catalogo junto con su stock desglosado por sede, acotado al ambito del rol. No
cambia el modelo de datos, no altera ninguna operacion previa y no escribe nada.

Contrato que estas pruebas fijan (spec §5 D-1..D-8, §6 reglas, §7 AC y §8):

  * **Respuesta** -> `ProductoDetalleRespuesta` con exactamente 13 campos y
    `sedes: [{sede_id, sede_nombre, stock_actual}]` ordenado por
    `(sede_nombre, sede_id)` ascendente. `stock_total` es la suma de las sedes
    devueltas y `es_critico` se evalua solo sobre esas sedes.
  * **Ambito** -> Administrador: todas las sedes de su institucion; Bodeguero: su
    sede asignada; Solicitante: la sede de su departamento. Las sedes inactivas
    **no** se excluyen. Una institucion sin sedes devuelve `sedes: []`.
  * **Visibilidad** -> Administrador lee productos y categorias inactivos;
    Bodeguero y Solicitante, solo activos con categoria activa (404 identico para
    inexistente, ajeno y retirado).
  * **Precedencia** -> 401 -> 403 matriz -> 403 capacidad -> 403 institucion ->
    409 sede operativa no resoluble -> 404 producto -> 200. El 409 de sede
    precede al lookup del producto: responde 409 incluso con id inexistente,
    ajeno, retirado o cero.
  * **Identificador** -> un path no entero responde 422 por coercion de tipo;
    cero y negativos responden 404 despues del alcance.
  * **Solo lectura** -> la consulta no muta producto, categoria, `stock_sede`,
    movimientos ni historial, y no lee las filas legadas de `inventario`.

Fase ROJA de TDD (T1): hoy la ruta no esta publicada, el DTO no existe, el
servicio no esta implementado y la matriz/capacidad aun no declaran la operacion.
Cada prueba falla por esa ausencia de comportamiento con un motivo legible
(`pytest.fail`) —nunca por `ImportError`, setup defectuoso ni por un 404 espurio
del router—. Las guardas nombran la tarea que cierra cada capa: T2 (matriz,
capacidad y cardinalidad, al final de este modulo), T3 (DTO y registro aditivo),
T4 (servicio) y T5 (endpoint publicado).

La expectativa de autorizacion, gating y contrato (T2) se escribe **independiente
de la implementacion**: la operacion, sus roles, su capacidad y la cardinalidad se
transcriben de la spec §7/§8, nunca se leen de `MATRIZ_PERMISOS` ni de
`MAPA_OPERACION_CAPACIDAD`. Las aserciones absolutas de las Features 014 y 018
que exigian 61 se amplian a 62 en sus propios modulos, documentando que la 019
agrega esta lectura.

El mundo se reutiliza **sin moverlo**: `mundo` se importa tal cual desde
`test_filtros_inventario_018.py` (el plan §1.3 descarta refactorizar el soporte
compartido para no ampliar el cambio a la 018 ni a sus consumidores) y
`mundo_detalle` solo agrega encima los casos que el detalle necesita: saldo en la
sede inactiva, producto inactivo, producto con categoria inactiva e institucion
sin sedes.
"""

from __future__ import annotations

import inspect

import pytest

from app.core import capacidades, permisos
from app.models import (
    Categoria,
    Departamento,
    HistorialTransicionProducto,
    Institucion,
    MovimientoInventario,
    Producto,
    StockSede,
)

from ._soporte_ciclo_vida_catalogo_014 import (
    CORREO_GATING,
    cliente_de_rol,
    marcar_categoria,
    marcar_producto,
    sembrar_contexto_capacidades,
)
from ._soporte_sede_011 import SIN_AUTENTICAR, cliente, contar_en, sesion
from .test_filtros_inventario_018 import (  # noqa: F401  (fixture reexportado)
    _crear_categoria,
    _crear_producto,
    _fijar_stock,
    mundo,
)

# ---------------------------------------------------------------------------
# Contrato de ruta y campos (spec §8 y plan §1.1)
# ---------------------------------------------------------------------------

#: Operacion nueva y aditiva de la 019, con el parametro de path del contrato.
RUTA_DETALLE = "/api/v1/inventario/existencias/{producto_id}"

#: Campos exactos del DTO (spec §8). Ni `stock_sede_id`, ni saldo legado, ni
#: usuarios, ni movimientos.
CAMPOS_DETALLE = frozenset(
    {
        "producto_id",
        "nombre",
        "descripcion",
        "unidad_medida",
        "stock_minimo",
        "categoria_id",
        "categoria_nombre",
        "categoria_activa",
        "activo",
        "institucion_id",
        "stock_total",
        "es_critico",
        "sedes",
    }
)

#: Forma exacta de cada elemento de `sedes` (reutiliza `SedeExistenciaRespuesta`).
CAMPOS_SEDE = frozenset({"sede_id", "sede_nombre", "stock_actual"})

#: Roles que la matriz 019 debe conceder (transcrito de la spec, AC-10/AC-11).
ROLES_DETALLE = ("Administrador", "Bodeguero", "Solicitante")

#: La **unica** operacion que la 019 agrega a la matriz central (spec §8/AC-4/
#: AC-11, transcrita de la spec y no leida de `MATRIZ_PERMISOS`). Superadmin queda
#: fuera: no tiene lectura de negocio desde la Feature 017 y recibe 403.
OPERACIONES_019: dict[tuple[str, str], set[str]] = {
    ("GET", RUTA_DETALLE): set(ROLES_DETALLE),
}

#: La lectura nueva se gatea **solo** por la capacidad institucional `inventario`
#: (spec D-6/AC-11): no exige `catalogo` aunque la entrada de Gestion exista.
CAPACIDADES_019: dict[tuple[str, str], str] = {
    clave: "inventario" for clave in OPERACIONES_019
}

#: Cardinalidad de la matriz tras la ampliacion documentada de la 019 (61 -> 62).
TOTAL_OPERACIONES_019 = 62
#: Las operaciones vigentes antes de la 019 (baseline de las Features 014 y 018).
TOTAL_PREVIO_019 = 61

#: Respuestas que el contrato debe documentar para la lectura nueva (spec §8).
RESPUESTAS_DETALLE = frozenset({"200", "401", "403", "404", "409", "422"})


def _ruta(producto_id: object) -> str:
    """Ruta concreta del detalle para un identificador dado."""
    return RUTA_DETALLE.format(producto_id=producto_id)


# ---------------------------------------------------------------------------
# Guardas de la fase roja (patron de `_exigir_ruta_018`)
# ---------------------------------------------------------------------------


def _exigir_ruta_019(ruta: str = RUTA_DETALLE, metodo: str = "GET") -> None:
    """Falla si la operacion aun no esta publicada en `/openapi.json` (T5).

    Sin esta guarda, una prueba que espera `404` pasaria por el motivo
    equivocado: el router respondería 404 por ruta ausente en vez de por recurso
    oculto.
    """
    from app.main import app

    operaciones = app.openapi().get("paths", {}).get(ruta, {})
    if metodo.lower() not in operaciones:
        pytest.fail(
            f"capacidad ausente (T5): {metodo.upper()} {ruta} no esta publicada en "
            "/openapi.json; la Feature 019 la cablea en T5."
        )


def _exigir_dto_019() -> type:
    """Falla si el read model del detalle aun no existe con los campos exactos."""
    from app.schemas import inventario_schema

    dto = getattr(inventario_schema, "ProductoDetalleRespuesta", None)
    if dto is None:
        pytest.fail(
            "capacidad ausente (T3): `ProductoDetalleRespuesta` no existe en "
            "`app.schemas.inventario_schema`; la Feature 019 lo define en T3 con "
            "los 13 campos del §8."
        )
    faltantes = CAMPOS_DETALLE - set(getattr(dto, "model_fields", {}))
    if faltantes:
        pytest.fail(
            "capacidad ausente (T3): `ProductoDetalleRespuesta` no declara "
            f"{sorted(faltantes)}; el contrato de la Feature 019 (§8) aun no esta "
            "implementado."
        )
    return dto


def _exigir_operacion_019(clave: tuple[str, str]) -> None:
    """Falla si la matriz central aun no declara la operacion nueva (T3)."""
    if clave not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            "capacidad ausente (T2): MATRIZ_PERMISOS no declara "
            f"{(clave[0].upper(), clave[1])}; la Feature 019 la agrega en T3 con "
            "los tres roles institucionales de la spec."
        )


def _exigir_capacidad_019(clave: tuple[str, str]) -> None:
    """Falla si el mapa de capacidades aun no asocia la operacion nueva (T3)."""
    if capacidades.capacidad_de_operacion(*clave) is None:
        pytest.fail(
            "capacidad ausente (T2): MAPA_OPERACION_CAPACIDAD no asocia "
            f"{(clave[0].upper(), clave[1])} a ninguna capacidad; la Feature 019 "
            "la vincula solo a `inventario` en T3."
        )


def _exigir_servicio_019() -> None:
    """Falla si el servicio de lectura por ambito aun no esta implementado (T4)."""
    from app.services import inventario_service

    if not hasattr(inventario_service, "obtener_detalle_producto"):
        pytest.fail(
            "capacidad ausente (T4): `inventario_service.obtener_detalle_producto` "
            "no existe; la Feature 019 lo implementa en T4."
        )


# ---------------------------------------------------------------------------
# Mundo: el de la 018 mas los casos propios del detalle
# ---------------------------------------------------------------------------


@pytest.fixture
def mundo_detalle(motor, mundo):
    """Amplia `mundo` (018) con los escenarios que el detalle necesita.

    Sobre las sedes, departamentos, productos y saldos de la 018 agrega:

    * saldo de `Cinta adhesiva` en la sede **inactiva** `Central Inactiva` (4),
      para que el desglose del Administrador la incluya junto a `Sur` (3);
    * `Caja de archivo`, activo y con **todo** su saldo (20) en la sede
      inactiva: si esa fila se excluyera, el total seria 0 y el producto saldria
      critico, asi que `es_critico is False` prueba que la sede inactiva cuenta;
    * `Perforadora retirada`: producto **inactivo** con **categoria activa**;
    * `Grapadora retirada` + `Categoria retirada`: producto inactivo con
      **categoria inactiva** (unico caso valido: la 014 prohibe producto activo
      bajo categoria inactiva);
    * `INST03`, una institucion **sin sedes** con su departamento, categoria y
      producto, para el `sedes: []` de AC-2.

    No modifica `test_filtros_inventario_018.py` ni mueve sus fixtures: solo
    agrega filas en el motor efimero de este test.
    """
    inst = mundo["inst_propia"]

    # (1) Saldo en sede inactiva sobre un producto de la 018.
    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=mundo["sede_inactiva"],
        producto_id=mundo["producto_cinta"],
        cantidad=4,
    )

    # (2) Activo cuyo unico saldo vive en la sede inactiva.
    producto_solo_inactiva = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=mundo["categoria_id"],
        nombre="Caja de archivo",
        stock_minimo=10,
    )
    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=mundo["sede_inactiva"],
        producto_id=producto_solo_inactiva,
        cantidad=20,
    )

    # (3) Producto inactivo con categoria activa.
    producto_inactivo = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=mundo["categoria_id"],
        nombre="Perforadora retirada",
        stock_minimo=5,
    )
    marcar_producto(motor, producto_inactivo, False)
    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=mundo["sede_norte"],
        producto_id=producto_inactivo,
        cantidad=2,
    )

    # (4) Producto inactivo con categoria inactiva (invariante de la 014).
    categoria_retirada = _crear_categoria(
        motor, institucion_id=inst, nombre="Categoria retirada"
    )
    producto_cat_inactiva = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=categoria_retirada,
        nombre="Grapadora retirada",
        stock_minimo=1,
    )
    marcar_producto(motor, producto_cat_inactiva, False)
    marcar_categoria(motor, categoria_retirada, False)
    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=mundo["sede_sur"],
        producto_id=producto_cat_inactiva,
        cantidad=0,
    )

    # (5) Institucion sin sedes (AC-2).
    with sesion(motor) as db:
        db.add(Institucion(institucion_id="INST03", nombre="Instituto sin sedes"))
        db.flush()
        departamento = Departamento(
            nombre_dep="Unica",
            descripcion="Departamento unico de INST03",
            institucion_id="INST03",
        )
        db.add(departamento)
        db.flush()
        categoria = Categoria(
            nombre_cat="Unica",
            descripcion_cat="Categoria unica de INST03",
            institucion_id="INST03",
            activo=True,
        )
        db.add(categoria)
        db.flush()
        producto = Producto(
            nombre="Resma de papel",
            descripcion="Producto de una institucion sin sedes",
            unidad_medida="UNIDAD",
            stock_minimo=3,
            categoria_id=categoria.categoria_id,
            institucion_id="INST03",
            activo=True,
        )
        db.add(producto)
        db.commit()
        db.refresh(departamento)
        db.refresh(producto)
        institucion_sin_sedes = {
            "departamento_id": departamento.departamento_id,
            "producto_id": producto.producto_id,
        }

    return {
        **mundo,
        "producto_solo_inactiva": producto_solo_inactiva,
        "producto_inactivo": producto_inactivo,
        "categoria_retirada": categoria_retirada,
        "producto_cat_inactiva": producto_cat_inactiva,
        "inst_sin_sedes": institucion_sin_sedes,
    }


# ---------------------------------------------------------------------------
# Helpers de observacion HTTP
# ---------------------------------------------------------------------------


def _detalle(cliente_http, producto_id: object, **params) -> dict:
    """`GET /inventario/existencias/{id}` debe responder 200 (si no, su texto)."""
    respuesta = cliente_http.get(_ruta(producto_id), params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _sede_y_saldo(cuerpo: dict) -> list[list[object]]:
    """Pares `[nombre, saldo]` en el orden devuelto por la respuesta."""
    return [[sede["sede_nombre"], sede["stock_actual"]] for sede in cuerpo["sedes"]]


def _ids_de_sedes(cuerpo: dict) -> set[int]:
    """Ids de las sedes devueltas (aserciones de ambito)."""
    return {sede["sede_id"] for sede in cuerpo["sedes"]}


# ===========================================================================
# AC-1: contrato exacto, agregado y orden determinista
# ===========================================================================


def test_detalle_responde_200_con_los_campos_exactos_del_contrato(motor, mundo_detalle):
    """AC-1/§8: 13 campos exactos y cada sede con su forma pactada."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_id"])

    assert set(cuerpo) == CAMPOS_DETALLE, sorted(cuerpo)
    for sede in cuerpo["sedes"]:
        assert set(sede) == CAMPOS_SEDE, sorted(sede)

    assert cuerpo["producto_id"] == mundo_detalle["producto_id"]
    assert cuerpo["nombre"] == "Cuaderno linedado"
    assert cuerpo["descripcion"] == "Cuaderno de 100 hojas"
    assert cuerpo["unidad_medida"] == "UNIDAD"
    assert cuerpo["stock_minimo"] == 10
    assert cuerpo["categoria_id"] == mundo_detalle["categoria_id"]
    assert cuerpo["categoria_nombre"] == "Papeleria"
    assert cuerpo["categoria_activa"] is True
    assert cuerpo["activo"] is True
    assert cuerpo["institucion_id"] == mundo_detalle["inst_propia"]
    assert cuerpo["stock_total"] == 42
    assert cuerpo["es_critico"] is False
    assert _sede_y_saldo(cuerpo) == [["Norte", 30], ["Sur", 12]]


def test_detalle_total_es_la_suma_de_las_sedes_devueltas(motor, mundo_detalle):
    """AC-1/AC-7: `stock_total` es la suma de las sedes, no un saldo paralelo.

    `Cinta adhesiva` tiene 3 en `Sur` y 4 en la sede inactiva `Central Inactiva`.
    Las 50 unidades legadas de `inventario` del producto base no participan.
    """
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_cinta"])

    assert cuerpo["stock_total"] == 7
    assert cuerpo["stock_total"] == sum(
        sede["stock_actual"] for sede in cuerpo["sedes"]
    )
    assert _sede_y_saldo(cuerpo) == [["Central Inactiva", 4], ["Sur", 3]]


def test_detalle_ordena_las_sedes_por_nombre_e_id(motor, mundo_detalle):
    """AC-1/§8: orden determinista `(sede_nombre, sede_id)` ascendente.

    `Norte` se inserto antes que `Sur` en la 018, y `Central Inactiva` va primero
    por nombre aunque se haya insertado despues: el orden no es de insercion.
    """
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuaderno = _detalle(cliente_http, mundo_detalle["producto_id"])
        cinta = _detalle(cliente_http, mundo_detalle["producto_cinta"])

    assert [sede["sede_nombre"] for sede in cuaderno["sedes"]] == ["Norte", "Sur"]
    assert [sede["sede_nombre"] for sede in cinta["sedes"]] == [
        "Central Inactiva",
        "Sur",
    ]
    assert [sede["sede_id"] for sede in cinta["sedes"]] == [
        mundo_detalle["sede_inactiva"],
        mundo_detalle["sede_sur"],
    ]


def test_detalle_incluye_las_filas_de_sedes_inactivas(motor, mundo_detalle):
    """AC-2/AC-7/D-5: una sede inactiva aparece y su saldo cuenta.

    `Caja de archivo` solo tiene saldo en la sede inactiva: si se excluyera,
    `sedes` seria vacio y `es_critico` seria `0 <= 10` = True.
    """
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_solo_inactiva"])

    assert _ids_de_sedes(cuerpo) == {mundo_detalle["sede_inactiva"]}
    assert cuerpo["stock_total"] == 20
    assert cuerpo["es_critico"] is False, "20 > 10 en la sede inactiva visible"


# ===========================================================================
# AC-2: ambito por rol e isolamiento institucional
# ===========================================================================


def test_detalle_administrador_ve_todas_las_sedes_de_su_institucion(motor, mundo_detalle):
    """AC-2: Administrador recibe todas las filas `stock_sede` de su institucion."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_id"])

    assert _ids_de_sedes(cuerpo) == {
        mundo_detalle["sede_norte"],
        mundo_detalle["sede_sur"],
    }
    assert mundo_detalle["sede_ajena"] not in _ids_de_sedes(cuerpo)


def test_detalle_bodeguero_solo_ve_su_sede_asignada(motor, mundo_detalle):
    """AC-2/D-3: el Bodeguero recibe solo su sede, con el total de esa sede."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Bodeguero") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_id"])

    assert _ids_de_sedes(cuerpo) == {mundo_detalle["sede_norte"]}
    assert cuerpo["stock_total"] == 30


def test_detalle_solicitante_solo_ve_la_sede_de_su_departamento(motor, mundo_detalle):
    """AC-2/D-3: el Solicitante recibe la sede de su departamento (`Operaciones`)."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Solicitante") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_id"])

    assert _ids_de_sedes(cuerpo) == {mundo_detalle["sede_norte"]}
    assert cuerpo["stock_total"] == 30


def test_detalle_bodeguero_con_sede_inactiva_responde_200(motor, mundo_detalle):
    """AC-2/AC-5/regla 2: una sede asignada inactiva se resuelve y responde 200."""
    _exigir_ruta_019()
    with cliente(
        motor,
        "Bodeguero",
        departamento_id=mundo_detalle["departamento_id"],
        sede_id=mundo_detalle["sede_inactiva"],
    ) as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_cinta"])

    assert _ids_de_sedes(cuerpo) == {mundo_detalle["sede_inactiva"]}
    assert cuerpo["stock_total"] == 4


def test_detalle_de_una_institucion_sin_sedes_devuelve_vacio(motor, mundo_detalle):
    """AC-2: sin sedes en la institucion, `sedes: []` y total cero."""
    _exigir_ruta_019()
    institucion = mundo_detalle["inst_sin_sedes"]
    with cliente(
        motor,
        "Administrador",
        departamento_id=institucion["departamento_id"],
    ) as cliente_http:
        cuerpo = _detalle(cliente_http, institucion["producto_id"])

    assert cuerpo["institucion_id"] == "INST03"
    assert cuerpo["sedes"] == []
    assert cuerpo["stock_total"] == 0
    assert cuerpo["es_critico"] is True, "0 <= stock_minimo"


# ===========================================================================
# AC-3: visibilidad de productos y categorias inactivos
# ===========================================================================


@pytest.mark.parametrize("rol", ROLES_DETALLE)
def test_detalle_producto_activo_es_visible_para_los_tres_roles(motor, mundo_detalle, rol):
    """AC-3: producto activo con categoria activa dentro del ambito -> 200."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, rol) as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_id"])

    assert cuerpo["producto_id"] == mundo_detalle["producto_id"]
    assert cuerpo["activo"] is True
    assert cuerpo["categoria_activa"] is True


def test_detalle_administrador_lee_un_producto_inactivo(motor, mundo_detalle):
    """AC-3/D-4: el Administrador conserva los productos retirados de su tenant."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_inactivo"])

    assert cuerpo["activo"] is False
    assert cuerpo["categoria_activa"] is True
    assert cuerpo["stock_total"] == 2


def test_detalle_administrador_lee_un_producto_de_categoria_inactiva(
    motor, mundo_detalle
):
    """AC-3/D-4: producto inactivo bajo categoria inactiva sigue visible al Admin."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_cat_inactiva"])

    assert cuerpo["activo"] is False
    assert cuerpo["categoria_activa"] is False
    assert cuerpo["categoria_id"] == mundo_detalle["categoria_retirada"]


@pytest.mark.parametrize("producto", ["producto_inactivo", "producto_cat_inactiva"])
@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante"])
def test_detalle_operativo_no_ve_productos_ni_categorias_inactivos(
    motor, mundo_detalle, rol, producto
):
    """AC-3/D-4: los roles operativos solo leen activo con categoria activa (404)."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, rol) as cliente_http:
        respuesta = cliente_http.get(_ruta(mundo_detalle[producto]))

    assert respuesta.status_code == 404, respuesta.text


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante"])
def test_detalle_operativo_no_distingue_inexistente_ajeno_ni_retirado(
    motor, mundo_detalle, rol
):
    """AC-3/AC-4: los tres casos responden 404 con un cuerpo identico."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, rol) as cliente_http:
        inexistente = cliente_http.get(_ruta(999_999))
        ajeno = cliente_http.get(_ruta(mundo_detalle["producto_homonimo_ajeno_id"]))
        retirado = cliente_http.get(_ruta(mundo_detalle["producto_inactivo"]))

    for respuesta in (inexistente, ajeno, retirado):
        assert respuesta.status_code == 404, respuesta.text
    assert inexistente.json() == ajeno.json() == retirado.json()
    assert set(inexistente.json()) == {"detail"}, "el 404 no revela el recurso"


def test_detalle_administrador_oculta_un_producto_de_otra_institucion(motor, mundo_detalle):
    """AC-2/AC-4: un producto ajeno responde 404 identico a uno inexistente."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        ajeno = cliente_http.get(_ruta(mundo_detalle["producto_homonimo_ajeno_id"]))
        inexistente = cliente_http.get(_ruta(999_999))

    assert ajeno.status_code == 404, ajeno.text
    assert ajeno.json() == inexistente.json()


# ===========================================================================
# AC-4/AC-5: precedencia de autorizacion, ambito y recurso
# ===========================================================================


def test_detalle_sin_sesion_responde_401(motor, mundo_detalle):
    """AC-4/regla 1: la sesion ausente es lo primero (401)."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, SIN_AUTENTICAR) as cliente_http:
        respuesta = cliente_http.get(_ruta(mundo_detalle["producto_id"]))

    assert respuesta.status_code == 401, respuesta.text


def test_detalle_superadmin_responde_403_por_matriz(motor, mundo_detalle):
    """AC-4/D-6: Superadmin no tiene la lectura de negocio (403 de matriz)."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Superadmin") as cliente_http:
        respuesta = cliente_http.get(_ruta(mundo_detalle["producto_id"]))

    assert respuesta.status_code == 403, respuesta.text


@pytest.mark.parametrize("rol", ROLES_DETALLE)
def test_detalle_con_capacidad_inventario_apagada_responde_403(motor, mundo_detalle, rol):
    """AC-4/AC-10/D-6: el gating `inventario` es adicional a la matriz."""
    _exigir_ruta_019()
    sembrar_contexto_capacidades(motor, mundo_detalle, frozenset({"inventario"}))

    with cliente_de_rol(
        motor, mundo_detalle, rol, correo=CORREO_GATING
    ) as cliente_http:
        respuesta = cliente_http.get(_ruta(mundo_detalle["producto_id"]))

    assert respuesta.status_code == 403, respuesta.text


def test_detalle_con_catalogo_habilitado_e_inventario_apagado_responde_403(
    motor, mundo_detalle
):
    """AC-8/AC-10/AC-11/D-6: la entrada desde Gestion no exime del gating.

    Con `catalogo` habilitada (la lista de gestion sigue visible) e `inventario`
    apagada, el detalle responde 403: no se exige `catalogo`, pero si
    `inventario`.
    """
    _exigir_ruta_019()
    sembrar_contexto_capacidades(motor, mundo_detalle, frozenset({"inventario"}))

    with cliente_de_rol(
        motor, mundo_detalle, "Administrador", correo=CORREO_GATING
    ) as cliente_http:
        catalogo = cliente_http.get("/api/v1/inventario/gestion")
        detalle = cliente_http.get(_ruta(mundo_detalle["producto_id"]))

    assert catalogo.status_code == 200, catalogo.text
    assert detalle.status_code == 403, detalle.text


def test_detalle_con_institucion_no_resoluble_responde_403(motor, mundo_detalle):
    """AC-4/regla 1: `alcance_institucional` deniega antes de mirar el producto."""
    _exigir_ruta_019()
    with cliente(
        motor,
        "Administrador",
        departamento_id=888_888,
    ) as cliente_http:
        respuesta = cliente_http.get(_ruta(mundo_detalle["producto_id"]))

    assert respuesta.status_code == 403, respuesta.text


@pytest.mark.parametrize(
    "caso", ["visible", "inexistente", "ajeno", "retirado", "cero"]
)
def test_detalle_bodeguero_sin_sede_responde_409_antes_de_mirar_el_producto(
    motor, mundo_detalle, caso
):
    """AC-5/regla 1: la sede se resuelve antes del lookup del producto.

    Un Bodeguero sin sede asignada (`None`) recibe 409 incluso cuando el id es
    inexistente, ajeno, retirado o cero: el 409 no revela nada del producto.
    """
    _exigir_ruta_019()
    identificadores = {
        "visible": mundo_detalle["producto_id"],
        "inexistente": 999_999,
        "ajeno": mundo_detalle["producto_homonimo_ajeno_id"],
        "retirado": mundo_detalle["producto_inactivo"],
        "cero": 0,
    }
    with cliente(
        motor,
        "Bodeguero",
        departamento_id=mundo_detalle["departamento_id"],
    ) as cliente_http:
        respuesta = cliente_http.get(_ruta(identificadores[caso]))

    assert respuesta.status_code == 409, respuesta.text
    assert "sede" in respuesta.json()["detail"].lower()


@pytest.mark.parametrize("caso", ["inexistente", "ajeno"])
def test_detalle_solicitante_sin_sede_departamental_responde_409(
    motor, mundo_detalle, caso
):
    """AC-5/regla 1: el Solicitante sin sede resoluble tambien recibe 409 primero."""
    _exigir_ruta_019()
    identificadores = {
        "inexistente": 999_999,
        "ajeno": mundo_detalle["producto_homonimo_ajeno_id"],
    }
    with cliente(
        motor,
        "Solicitante",
        departamento_id=mundo_detalle["dep_sin_sede"],
    ) as cliente_http:
        respuesta = cliente_http.get(_ruta(identificadores[caso]))

    assert respuesta.status_code == 409, respuesta.text
    assert "sede" in respuesta.json()["detail"].lower()


# ===========================================================================
# AC-6/AC-7: producto sin filas de stock y criticidad por sede visible
# ===========================================================================


def test_detalle_producto_sin_stock_responde_200_vacio(motor, mundo_detalle):
    """AC-6/D-7: producto visible sin filas -> `sedes: []`, total 0 y critico."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_goma"])

    assert cuerpo["sedes"] == []
    assert cuerpo["stock_total"] == 0
    assert cuerpo["stock_minimo"] == 10
    assert cuerpo["es_critico"] is True, "0 <= stock_minimo"


def test_detalle_sin_stock_en_el_ambito_no_hereda_sedes_de_fuera(motor, mundo_detalle):
    """AC-6: las sedes fuera del ambito no aparecen ni cambian el total.

    `Cinta adhesiva` solo tiene saldo fuera de la sede del Solicitante.
    """
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Solicitante") as cliente_http:
        cuerpo = _detalle(cliente_http, mundo_detalle["producto_cinta"])

    assert cuerpo["sedes"] == []
    assert cuerpo["stock_total"] == 0
    assert cuerpo["es_critico"] is True


def test_detalle_criticidad_solo_considera_las_sedes_devueltas(motor, mundo_detalle):
    """AC-7: `Regla metalica` es critica en el agregado y holgada en una sola sede."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        agregado = _detalle(cliente_http, mundo_detalle["producto_regla"])
    with cliente_de_rol(motor, mundo_detalle, "Bodeguero") as cliente_http:
        solo_norte = _detalle(cliente_http, mundo_detalle["producto_regla"])

    assert _sede_y_saldo(agregado) == [["Norte", 100], ["Sur", 3]]
    assert agregado["es_critico"] is True, "Sur (3) <= 10"
    assert _sede_y_saldo(solo_norte) == [["Norte", 100]]
    assert solo_norte["es_critico"] is False, "100 > 10 en la unica sede visible"


# ===========================================================================
# AC-9: el detalle no hereda los filtros de la lista
# ===========================================================================


def test_detalle_ignora_los_filtros_seleccionados_en_la_lista(motor, mundo_detalle):
    """AC-9/D-3: sede, departamento, texto y criticidad de la lista no acotan el detalle."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        sin_filtros = _detalle(cliente_http, mundo_detalle["producto_id"])
        con_filtros = _detalle(
            cliente_http,
            mundo_detalle["producto_id"],
            sede_id=mundo_detalle["sede_sur"],
            departamento_id=mundo_detalle["dep_almacen"],
            q="Cinta",
            solo_criticos=True,
        )

    assert con_filtros == sin_filtros
    assert _ids_de_sedes(con_filtros) == {
        mundo_detalle["sede_norte"],
        mundo_detalle["sede_sur"],
    }


# ===========================================================================
# AC-10/§8: identificador invalido
# ===========================================================================


@pytest.mark.parametrize("producto_id", [0, -1])
def test_detalle_con_id_cero_o_negativo_responde_404(motor, mundo_detalle, producto_id):
    """§8/regla 5: cero y negativos no identifican producto y responden 404."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        respuesta = cliente_http.get(_ruta(producto_id))

    assert respuesta.status_code == 404, respuesta.text


def test_detalle_con_id_no_entero_responde_422(motor, mundo_detalle):
    """§8/regla 5/AC-10: un path no entero recibe 422 por coercion de tipo."""
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        respuesta = cliente_http.get(_ruta("abc"))

    assert respuesta.status_code == 422, respuesta.text


# ===========================================================================
# AC-12: solo lectura y coexistencia con la lectura de catalogo
# ===========================================================================


def test_detalle_no_modifica_ninguna_fila_ni_consulta_el_saldo_legado(
    motor, mundo_detalle
):
    """AC-12/D-5: la consulta no muta estado y no suma las filas de `inventario`.

    El producto base conserva sus 50 unidades legadas en `inventario`; el detalle
    informa 42 (30 + 12 de `stock_sede`), que es la unica fuente de saldo.
    """
    _exigir_ruta_019()
    antes = {
        "productos": contar_en(motor, Producto),
        "categorias": contar_en(motor, Categoria),
        "stock_sede": contar_en(motor, StockSede),
        "movimientos": contar_en(motor, MovimientoInventario),
        "historial": contar_en(motor, HistorialTransicionProducto),
    }

    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        detalle = _detalle(cliente_http, mundo_detalle["producto_id"])
        _detalle(cliente_http, mundo_detalle["producto_inactivo"])
        _detalle(cliente_http, mundo_detalle["producto_goma"])

    despues = {
        "productos": contar_en(motor, Producto),
        "categorias": contar_en(motor, Categoria),
        "stock_sede": contar_en(motor, StockSede),
        "movimientos": contar_en(motor, MovimientoInventario),
        "historial": contar_en(motor, HistorialTransicionProducto),
    }

    assert detalle["stock_total"] == 42, "no incluye las 50 unidades legadas"
    assert despues == antes, "el detalle es de solo lectura"


def test_detalle_coexiste_con_la_lectura_de_catalogo_por_producto(motor, mundo_detalle):
    """AC-12: `GET /inventario/productos/{id}` sigue siendo solo producto.

    La lectura nueva no la sustituye ni le agrega `sedes`/`stock_total`; su
    capacidad sigue siendo `catalogo`.
    """
    _exigir_ruta_019()
    with cliente_de_rol(motor, mundo_detalle, "Administrador") as cliente_http:
        producto = cliente_http.get(
            f"/api/v1/inventario/productos/{mundo_detalle['producto_id']}"
        )

    assert producto.status_code == 200, producto.text
    cuerpo = producto.json()
    assert cuerpo["producto_id"] == mundo_detalle["producto_id"]
    assert "sedes" not in cuerpo
    assert "stock_total" not in cuerpo


# ===========================================================================
# AC-11 (capa T3/T4): read model y servicio con el contrato pactado
# ===========================================================================


def test_dto_del_detalle_declara_exactamente_los_campos_del_contrato():
    """AC-1/AC-11/§8: 13 campos, sedes reutilizadas y sin `from_attributes`."""
    dto = _exigir_dto_019()

    assert set(dto.model_fields) == CAMPOS_DETALLE, sorted(dto.model_fields)
    from app.schemas.inventario_schema import SedeExistenciaRespuesta

    anotacion = dto.model_fields["sedes"].annotation
    assert "SedeExistenciaRespuesta" in str(anotacion)
    assert set(SedeExistenciaRespuesta.model_fields) == CAMPOS_SEDE
    assert "from_attributes" not in getattr(dto, "model_config", {})


def test_servicio_del_detalle_expone_la_lectura_por_ambito():
    """AC-12/plan §1.1: `obtener_detalle_producto(db, producto_id, identidad)`."""
    _exigir_servicio_019()
    from app.services import inventario_service

    parametros = inspect.signature(
        inventario_service.obtener_detalle_producto
    ).parameters
    for nombre in ("db", "producto_id", "identidad"):
        assert nombre in parametros, sorted(parametros)


# ===========================================================================
# AC-4/AC-10/AC-11/AC-13 (T2): matriz, gating, contrato y cardinalidad 62
# ===========================================================================


def test_matriz_declara_una_sola_operacion_de_detalle_para_los_tres_roles():
    """AC-4/AC-11/§8: exactamente una operacion GET con los tres roles de la spec.

    Se transcribe de la spec (Administrador, Bodeguero y Solicitante) y no se lee
    de `MATRIZ_PERMISOS`: la igualdad de conjuntos falla tanto si falta un rol
    como si se concede otro (por ejemplo, Superadmin).
    """
    assert len(OPERACIONES_019) == 1, "la 019 agrega exactamente una operacion"
    for clave, roles in OPERACIONES_019.items():
        _exigir_operacion_019(clave)
        assert set(permisos.MATRIZ_PERMISOS[clave]) == roles, (
            f"{(clave[0].upper(), clave[1])} debe conceder {sorted(roles)}; "
            f"declara {sorted(permisos.MATRIZ_PERMISOS[clave])}"
        )
        assert "Superadmin" not in permisos.MATRIZ_PERMISOS[clave], (
            "Superadmin no tiene lectura de negocio (AC-4/D-6)"
        )


def test_matriz_excluye_a_superadmin_de_la_operacion_de_detalle():
    """AC-4/D-6: de los roles conocidos, solo Superadmin queda fuera.

    La 017 retiro a Superadmin de las lecturas de negocio; esta lectura nueva no
    puede reintroducirlo. Se comprueba la exclusion sobre el conjunto cerrado de
    roles conocidos, no solo sobre los tres concedidos.
    """
    for clave in OPERACIONES_019:
        _exigir_operacion_019(clave)
        concedidos = set(permisos.MATRIZ_PERMISOS[clave])
        assert concedidos - set(permisos.ROLES_CONOCIDOS) == set(), (
            f"{(clave[0].upper(), clave[1])} concede roles desconocidos: "
            f"{sorted(concedidos - set(permisos.ROLES_CONOCIDOS))}"
        )
        assert set(permisos.ROLES_CONOCIDOS) - concedidos == {"Superadmin"}, (
            "Superadmin no tiene lectura de negocio (AC-4/D-6); "
            f"faltan {sorted(set(permisos.ROLES_CONOCIDOS) - concedidos)}"
        )


def test_capacidad_inventario_asociada_a_la_operacion_de_detalle():
    """AC-10/AC-11/D-6: gating solo por `inventario`, nunca por `catalogo`."""
    for clave, esperada in CAPACIDADES_019.items():
        _exigir_capacidad_019(clave)
        obtenida = capacidades.capacidad_de_operacion(*clave)
        assert obtenida == esperada, (clave, obtenida, esperada)


def test_matriz_tiene_exactamente_62_operaciones_tras_019():
    """AC-11: 61 vigentes + la lectura aditiva de la 019.

    La ampliacion 61 -> 62 se documenta aqui y en las aserciones absolutas de
    `test_ciclo_vida_autorizacion_014.py` y `test_filtros_inventario_018.py`; no
    reescribe ninguna transcripcion historica de roles.
    """
    total = len(permisos.MATRIZ_PERMISOS)
    previas = set(permisos.MATRIZ_PERMISOS) - set(OPERACIONES_019)
    assert total == TOTAL_OPERACIONES_019, (
        f"la matriz debe tener {TOTAL_OPERACIONES_019} operaciones tras la 019 "
        f"({TOTAL_PREVIO_019} previas + la de detalle); tiene {total}"
    )
    assert len(previas) == TOTAL_PREVIO_019, (
        "la operacion nueva no puede sustituir a ninguna previa; "
        f"quedan {len(previas)} operaciones anteriores"
    )


def test_openapi_publica_la_operacion_de_detalle(cliente):
    """AC-11: la ruta pactada aparece publicada en `/openapi.json`."""
    _exigir_ruta_019()
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"].get(RUTA_DETALLE, {}).get("get")
    assert operacion is not None, (
        f"GET {RUTA_DETALLE} no esta publicada en /openapi.json"
    )


def test_openapi_documenta_las_respuestas_del_detalle(cliente):
    """AC-11/§8: exito 200 y errores aplicables 401/403/404/409/422.

    Se afirma sobre las respuestas declaradas del contrato; el 409 del rol
    operativo sin sede y el 422 de coercion del path forman parte del pacto.
    """
    _exigir_ruta_019()
    contrato = cliente.get("/openapi.json").json()
    operacion = contrato["paths"].get(RUTA_DETALLE, {}).get("get")
    if operacion is None:
        pytest.fail(
            f"capacidad ausente (T5): GET {RUTA_DETALLE} no esta publicada en "
            "/openapi.json; la Feature 019 la cablea en T5."
        )
    respuestas = set(operacion.get("responses", {}))
    assert RESPUESTAS_DETALLE <= respuestas, (
        f"el contrato debe documentar {sorted(RESPUESTAS_DETALLE)}; "
        f"documenta {sorted(respuestas)}"
    )
