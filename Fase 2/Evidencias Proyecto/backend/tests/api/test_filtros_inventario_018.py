"""T1 (Feature 018): filtros de existencias por sede y departamento — pruebas rojas.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), igual que el
resto de la suite. La Feature 018 es **aditiva**: agrega la lectura minima de
ambito (`GET /api/v1/inventario/ambito`) para Administrador y Bodeguero, y el
parametro de filtro `sede_id` a `GET /api/v1/inventario/existencias`. No cambia el
modelo de datos, no reasigna saldo por departamento y no altera ninguna operacion
existente de la matriz.

Contrato que estas pruebas fijan (spec §7 y plan §1.2):

  * **Ambito** -> `{sedes: [{sede_id, sede_nombre}], departamentos:
    [{departamento_id, departamento_nombre, sede_id}]}`, solo filas activas y
    departamentos con sede asignada. Administrador: su institucion; Bodeguero:
    unicamente su sede. Bodeguero sin sede: **409**. Solicitante/Superadmin:
    **403**. Capacidad `inventario` apagada: **403**. Orden determinista.
  * **Existencias + `sede_id`** -> la lista se acota a esa sede y `stock_total`,
    `es_critico` y `sedes[]` describen solo ese saldo. Un `sede_id` inexistente o
    ajeno al esquema del actor responde **200 con lista vacia** (es un filtro de
    lista, no un recurso: el 404 de `GET /inventario/stock` de la Feature 011
    queda intacto). `sede_id` + `departamento_id` incoherentes: **200/[]**.
    Productos sin fila de stock: visibles sin filtro organizacional (`sedes: []`,
    `stock_total: 0`) y ocultos cuando hay filtro.
  * **Matriz, capacidad y OpenAPI** -> una sola operacion nueva con
    `{Administrador, Bodeguero}`, matriz **60 -> 61**, gating `inventario` y
    contrato publicado.

Fase ROJA de TDD: hoy la ruta de ambito no existe, `existencias` no acepta
`sede_id`, la matriz no declara la operacion nueva y el mapa de capacidades no la
asocia. Cada prueba falla por esa ausencia de comportamiento con un motivo
legible —nunca por `ImportError` ni por sintaxis— salvo las guardas de regresion,
que deben seguir verdes desde el primer dia.

Salvedad de QA (plan §1.4): el **403** de un `departamento_id` de otra
institucion se afirma **solo en este arnes SQLite**, donde la fila ajena es
visible; en PostgreSQL cross-schema la entidad no existe en el esquema del actor
y el resultado correcto es 200/`[]`. No se escribe ninguna prueba gated que
espere ese 403.
"""

from __future__ import annotations

import pytest

from app.core import capacidades, permisos
from app.models import Categoria, Departamento, Producto, Sede, StockSede

from ._soporte_ciclo_vida_catalogo_014 import (
    CORREO_GATING,
    OPERACIONES_014,
    cliente_de_rol,
    sembrar_contexto_capacidades,
)
from ._soporte_ciclo_vida_013 import OPERACIONES_013
from ._soporte_sede_011 import (
    SIN_AUTENTICAR,
    cliente,
    producto_de_existencias,
    sesion,
)
from .test_ciclo_vida_autorizacion_013 import RETIRADAS_017
from .test_permisos_012 import MATRIZ_012

# ---------------------------------------------------------------------------
# Contrato de rutas, campos y operaciones (plan §1.2)
# ---------------------------------------------------------------------------

#: Lectura minima de ambito para los selectores de la vista de existencias.
RUTA_AMBITO = "/api/v1/inventario/ambito"
#: Lectura de existencias, ampliada con el filtro `sede_id`.
RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"

#: Campos exactos de cada fila (spec §7: "campos minimos"). Ni usuarios, ni
#: tickets, ni stock, ni otra institucion.
CAMPOS_SEDE = frozenset({"sede_id", "sede_nombre"})
CAMPOS_DEPARTAMENTO = frozenset(
    {"departamento_id", "departamento_nombre", "sede_id"}
)
#: Claves exactas del cuerpo de ambito: nada de productos, stock ni agregados.
CLAVES_AMBITO = frozenset({"sedes", "departamentos"})

#: La unica operacion que la 018 agrega a la matriz central (spec D-6/AC-8),
#: transcrita de la spec y no leida de `MATRIZ_PERMISOS`.
OPERACIONES_018: dict[tuple[str, str], set[str]] = {
    ("GET", RUTA_AMBITO): {"Administrador", "Bodeguero"},
}

#: Toda operacion nueva queda gateada por la capacidad `inventario`, que ya
#: existe: la 018 no amplia el conjunto cerrado de la 012 (plan §1.1.4).
CAPACIDADES_018: dict[tuple[str, str], str] = {
    clave: "inventario" for clave in OPERACIONES_018
}

#: Total de operaciones de la matriz tras la ampliacion explicita de la 018.
TOTAL_OPERACIONES_018 = 61

_METODOS_OPENAPI = {"get", "put", "post", "delete", "patch"}
_PREFIJO_CONTRATO = "/api/v1/"


# ---------------------------------------------------------------------------
# Guardas de la fase roja
# ---------------------------------------------------------------------------


def _exigir_ruta_018(ruta: str, metodo: str = "GET") -> None:
    """Falla si la operacion aun no esta publicada en `/openapi.json` (T4)."""
    from app.main import app

    operaciones = app.openapi().get("paths", {}).get(ruta, {})
    if metodo.lower() not in operaciones:
        pytest.fail(
            f"capacidad ausente (T4): {metodo.upper()} {ruta} no esta publicada en "
            "/openapi.json; la Feature 018 la cablea en T4."
        )


def _exigir_operacion_018(metodo: str, ruta: str) -> None:
    """Falla si la matriz central aun no declara la operacion nueva (T2)."""
    if (metodo.upper(), ruta) not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            "capacidad ausente (T2): MATRIZ_PERMISOS no declara "
            f"{(metodo.upper(), ruta)}; la Feature 018 la agrega en T2."
        )


def _exigir_capacidad_018(metodo: str, ruta: str) -> None:
    """Falla si el mapa de capacidades aun no asocia la operacion nueva (T2)."""
    if capacidades.capacidad_de_operacion(metodo, ruta) is None:
        pytest.fail(
            "capacidad ausente (T2): MAPA_OPERACION_CAPACIDAD no asocia "
            f"{(metodo.upper(), ruta)} a ninguna capacidad; la Feature 018 la "
            "vincula a `inventario` en T2."
        )


# ---------------------------------------------------------------------------
# Construccion del mundo
# ---------------------------------------------------------------------------


def _crear_sede(
    motor, *, institucion_id: str, nombre: str, activo: bool = True
) -> int:
    """Sede de una institucion con su estado de vigencia explicito."""
    with sesion(motor) as db:
        fila = Sede(
            nombre=nombre, institucion_id=institucion_id, activo=activo
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.sede_id


def _crear_departamento(
    motor,
    *,
    institucion_id: str,
    nombre: str,
    sede_id: int | None = None,
    activo: bool = True,
) -> int:
    """Departamento con sede opcional y estado de vigencia explicito."""
    with sesion(motor) as db:
        fila = Departamento(
            nombre_dep=nombre,
            descripcion=f"Departamento de prueba {nombre}",
            institucion_id=institucion_id,
            sede_id=sede_id,
            activo=activo,
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.departamento_id


def _crear_categoria(motor, *, institucion_id: str, nombre: str) -> int:
    """Categoria vigente del tenant."""
    with sesion(motor) as db:
        fila = Categoria(
            nombre_cat=nombre,
            descripcion_cat=f"Categoria de prueba {nombre}",
            institucion_id=institucion_id,
            activo=True,
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.categoria_id


def _crear_producto(
    motor,
    *,
    institucion_id: str,
    categoria_id: int,
    nombre: str,
    stock_minimo: int = 0,
) -> int:
    """Producto vigente del tenant, sin fila de stock (la crea `_fijar_stock`)."""
    with sesion(motor) as db:
        fila = Producto(
            nombre=nombre,
            descripcion=f"Producto de prueba {nombre}",
            unidad_medida="UNIDAD",
            stock_minimo=stock_minimo,
            categoria_id=categoria_id,
            institucion_id=institucion_id,
            activo=True,
        )
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.producto_id


def _fijar_stock(
    motor, *, institucion_id: str, sede_id: int, producto_id: int, cantidad: int
) -> None:
    """Fila de saldo por sede (`stock_sede`), unica fuente de stock operativo."""
    with sesion(motor) as db:
        db.add(
            StockSede(
                sede_id=sede_id,
                producto_id=producto_id,
                stock_actual=cantidad,
                institucion_id=institucion_id,
            )
        )
        db.commit()


def _asignar_sede_a_usuario(motor, usuario_id: int, sede_id: int | None) -> None:
    """Asigna (o limpia, con `None`) la sede del Bodeguero persistido."""
    from app.models import Usuario

    with sesion(motor) as db:
        usuario = db.get(Usuario, usuario_id)
        assert usuario is not None, f"usuario {usuario_id} inexistente en la fixture"
        usuario.sede_id = sede_id
        db.commit()


@pytest.fixture
def mundo(motor, dos_instituciones):
    """Mundo de la 018: sedes, departamentos y saldos por sede en INST01/INST02.

    Sobre `dos_instituciones` (INST01 propia + INST02 ajena, con un usuario
    persistido por rol) siembra:

    * **Sedes INST01**: `Norte`, `Sur` y `Este` activas (insertadas en ese orden,
      que no es el alfabetico, para que el orden determinista sea observable) y
      `Central Inactiva` desactivada. INST02 aporta `Bodega Ajena`.
    * **Departamentos INST01**: `Operaciones` (de `datos_base`, y el del
      Solicitante) en `Norte`; `Almacen` tambien en `Norte` (dos departamentos de
      la **misma** sede, AC-2); `Logistica` en `Sur`; `Deposito Este` en `Este`;
      `Sin Sede` activo sin sede (no es opcion, D-5); `Archivado` desactivado en
      `Norte`. El departamento de INST02 queda en `Bodega Ajena`.
    * **Productos INST01**: `Cuaderno linedado` (el de `datos_base`; 30 en Norte y
      12 en Sur), `Cinta adhesiva` (solo 3 en Sur), `Regla metalica` (100 en
      Norte, 3 en Sur: critico global, holgado en Norte) y `Goma de borrar` (sin
      ninguna fila de stock). `Toner` vive en una segunda categoria con 5 en
      Norte.
    * **Bodeguero persistido** con sede `Norte`, que es la que usa
      `cliente_de_rol`. INST02 tiene saldo de su producto homonimo en su sede.
    """
    inst = dos_instituciones["inst_propia"]
    ajena = dos_instituciones["inst_ajena"]

    norte = _crear_sede(motor, institucion_id=inst, nombre="Norte")
    sur = _crear_sede(motor, institucion_id=inst, nombre="Sur")
    este = _crear_sede(motor, institucion_id=inst, nombre="Este")
    inactiva = _crear_sede(
        motor, institucion_id=inst, nombre="Central Inactiva", activo=False
    )
    bodega_ajena = _crear_sede(motor, institucion_id=ajena, nombre="Bodega Ajena")

    # El departamento de `datos_base` es el del Solicitante: su sede define su
    # ambito operativo (Feature 011, spec D-5).
    with sesion(motor) as db:
        operaciones = db.get(Departamento, dos_instituciones["departamento_id"])
        operaciones.sede_id = norte
        departamento_ajeno = db.get(
            Departamento, dos_instituciones["departamento_ajeno_id"]
        )
        departamento_ajeno.sede_id = bodega_ajena
        db.commit()

    almacen = _crear_departamento(
        motor, institucion_id=inst, nombre="Almacen", sede_id=norte
    )
    logistica = _crear_departamento(
        motor, institucion_id=inst, nombre="Logistica", sede_id=sur
    )
    deposito_este = _crear_departamento(
        motor, institucion_id=inst, nombre="Deposito Este", sede_id=este
    )
    sin_sede = _crear_departamento(
        motor, institucion_id=inst, nombre="Sin Sede", sede_id=None
    )
    archivado = _crear_departamento(
        motor, institucion_id=inst, nombre="Archivado", sede_id=norte, activo=False
    )

    cinta = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=dos_instituciones["categoria_id"],
        nombre="Cinta adhesiva",
        stock_minimo=10,
    )
    regla = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=dos_instituciones["categoria_id"],
        nombre="Regla metalica",
        stock_minimo=10,
    )
    goma = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=dos_instituciones["categoria_id"],
        nombre="Goma de borrar",
        stock_minimo=10,
    )
    categoria_toner = _crear_categoria(motor, institucion_id=inst, nombre="Toner")
    toner = _crear_producto(
        motor,
        institucion_id=inst,
        categoria_id=categoria_toner,
        nombre="Toner negro",
        stock_minimo=10,
    )

    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=norte,
        producto_id=dos_instituciones["producto_id"],
        cantidad=30,
    )
    _fijar_stock(
        motor,
        institucion_id=inst,
        sede_id=sur,
        producto_id=dos_instituciones["producto_id"],
        cantidad=12,
    )
    _fijar_stock(
        motor, institucion_id=inst, sede_id=sur, producto_id=cinta, cantidad=3
    )
    _fijar_stock(
        motor, institucion_id=inst, sede_id=norte, producto_id=regla, cantidad=100
    )
    _fijar_stock(
        motor, institucion_id=inst, sede_id=sur, producto_id=regla, cantidad=3
    )
    _fijar_stock(
        motor, institucion_id=inst, sede_id=norte, producto_id=toner, cantidad=5
    )
    _fijar_stock(
        motor,
        institucion_id=ajena,
        sede_id=bodega_ajena,
        producto_id=dos_instituciones["producto_homonimo_ajeno_id"],
        cantidad=4,
    )

    _asignar_sede_a_usuario(
        motor, dos_instituciones["usuarios_inst01"]["Bodeguero"], norte
    )

    return {
        **dos_instituciones,
        "sede_id": norte,
        "sede_norte": norte,
        "sede_sur": sur,
        "sede_este": este,
        "sede_inactiva": inactiva,
        "sede_ajena": bodega_ajena,
        "dep_almacen": almacen,
        "dep_logistica": logistica,
        "dep_este": deposito_este,
        "dep_sin_sede": sin_sede,
        "dep_archivado": archivado,
        "producto_cinta": cinta,
        "producto_regla": regla,
        "producto_goma": goma,
        "producto_toner": toner,
        "categoria_toner": categoria_toner,
    }


# ---------------------------------------------------------------------------
# Helpers de observacion HTTP
# ---------------------------------------------------------------------------


def _ambito(cliente_http):
    """`GET /inventario/ambito` debe responder 200 (si no, falla con su texto)."""
    respuesta = cliente_http.get(RUTA_AMBITO)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _existencias(cliente_http, **params) -> list[dict]:
    respuesta = cliente_http.get(RUTA_EXISTENCIAS, params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _ids(filas: list[dict]) -> set[int]:
    return {fila["producto_id"] for fila in filas}


# ===========================================================================
# AC-4: lectura minima de ambito
# ===========================================================================


def test_ambito_administrador_devuelve_solo_opciones_activas_de_su_institucion(
    motor, mundo
):
    """AC-4/D-6: sedes activas y departamentos activos con sede de la institucion.

    Se excluyen la sede desactivada, el departamento desactivado, el
    departamento sin sede y todo el arbol de INST02.
    """
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        cuerpo = _ambito(cliente_http)

    sedes = {fila["sede_id"] for fila in cuerpo["sedes"]}
    assert sedes == {
        mundo["sede_norte"],
        mundo["sede_sur"],
        mundo["sede_este"],
    }, sorted(sedes)

    departamentos = {fila["departamento_id"] for fila in cuerpo["departamentos"]}
    assert departamentos == {
        mundo["departamento_id"],
        mundo["dep_almacen"],
        mundo["dep_logistica"],
        mundo["dep_este"],
    }, sorted(departamentos)


def test_ambito_administrador_no_expone_campos_ni_recursos_ajenos(motor, mundo):
    """AC-4/D-6: la respuesta contiene **solo** las opciones pactadas.

    Ni usuarios, ni tickets, ni productos/stock, ni agregados, ni campos de mas:
    un cliente que consuma este contrato no puede inferir organizacion o saldo
    fuera de las opciones de filtro.
    """
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        cuerpo = _ambito(cliente_http)

    assert set(cuerpo) == CLAVES_AMBITO, sorted(cuerpo)
    for fila in cuerpo["sedes"]:
        assert set(fila) == CAMPOS_SEDE, sorted(fila)
    for fila in cuerpo["departamentos"]:
        assert set(fila) == CAMPOS_DEPARTAMENTO, sorted(fila)
        # El `sede_id` del departamento es la asociacion que la UI necesita para
        # acotar departamentos al elegir sede (D-6), no un saldo.
        assert fila["sede_id"] in {
            mundo["sede_norte"],
            mundo["sede_sur"],
            mundo["sede_este"],
        }


def test_ambito_orden_determinista(motor, mundo):
    """AC-4/plan §1.2: sedes por `(nombre, sede_id)`, departamentos por `(nombre_dep, id)`."""
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        cuerpo = _ambito(cliente_http)

    assert [fila["sede_nombre"] for fila in cuerpo["sedes"]] == [
        "Este",
        "Norte",
        "Sur",
    ], "las sedes se ordenan por nombre, no por orden de insercion"
    assert [fila["departamento_nombre"] for fila in cuerpo["departamentos"]] == [
        "Almacen",
        "Deposito Este",
        "Logistica",
        "Operaciones",
    ], "los departamentos se ordenan por nombre"


def test_ambito_bodeguero_recibe_solo_su_sede_y_sus_departamentos(motor, mundo):
    """AC-4/D-6: el Bodeguero no recibe niguna otra sede ni deps de otra sede."""
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente_de_rol(motor, mundo, "Bodeguero") as cliente_http:
        cuerpo = _ambito(cliente_http)

    assert [fila["sede_id"] for fila in cuerpo["sedes"]] == [
        mundo["sede_norte"]
    ], "el Bodeguero solo ve su sede asignada"
    assert {fila["departamento_id"] for fila in cuerpo["departamentos"]} == {
        mundo["departamento_id"],
        mundo["dep_almacen"],
    }, "solo los departamentos activos de su sede"
    assert all(
        fila["sede_id"] == mundo["sede_norte"]
        for fila in cuerpo["departamentos"]
    )


def test_ambito_bodeguero_sin_sede_responde_409(motor, mundo):
    """AC-4/D-6: sin sede asignada no hay ambito alternativo ni por defecto."""
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente(
        motor,
        "Bodeguero",
        departamento_id=mundo["departamento_id"],
    ) as cliente_http:
        respuesta = cliente_http.get(RUTA_AMBITO)

    assert respuesta.status_code == 409, respuesta.text
    detalle = respuesta.json()["detail"].lower()
    assert "sede" in detalle and "asignada" in detalle, respuesta.json()


def test_ambito_sin_sesion_responde_401(motor, mundo):
    """AC-8: la lectura exige sesion autenticada."""
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente(motor, SIN_AUTENTICAR) as cliente_http:
        respuesta = cliente_http.get(RUTA_AMBITO)
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("rol", ["Solicitante", "Superadmin"])
def test_ambito_de_rol_no_autorizado_responde_403(motor, mundo, rol):
    """AC-8: solo Administrador y Bodeguero; el resto recibe 403 de matriz."""
    _exigir_ruta_018(RUTA_AMBITO)
    with cliente_de_rol(motor, mundo, rol) as cliente_http:
        respuesta = cliente_http.get(RUTA_AMBITO)
    assert respuesta.status_code == 403, respuesta.text


@pytest.mark.parametrize("rol", ["Administrador", "Bodeguero"])
def test_ambito_con_capacidad_inventario_apagada_responde_403(motor, mundo, rol):
    """AC-8/plan §1.1.4: el gating de `inventario` es adicional a la matriz."""
    _exigir_ruta_018(RUTA_AMBITO)
    sembrar_contexto_capacidades(motor, mundo, frozenset({"inventario"}))

    with cliente_de_rol(motor, mundo, rol, correo=CORREO_GATING) as cliente_http:
        respuesta = cliente_http.get(RUTA_AMBITO)

    assert respuesta.status_code == 403, respuesta.text


# ===========================================================================
# AC-1/AC-6: agregado permitido por rol y productos sin saldo
# ===========================================================================


def test_existencias_sin_filtro_mantienen_agregado_y_productos_sin_saldo(
    motor, mundo
):
    """AC-1/AC-6: sin filtros organizacionales el total suma las sedes y el
    producto sin fila de stock sigue visible en cero."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        filas = _existencias(cliente_http)

    cuaderno = producto_de_existencias(filas, mundo["producto_id"])
    assert cuaderno["stock_total"] == 42, "30 de Norte + 12 de Sur"
    assert {fila["sede_id"] for fila in cuaderno["sedes"]} == {
        mundo["sede_norte"],
        mundo["sede_sur"],
    }

    goma = producto_de_existencias(filas, mundo["producto_goma"])
    assert goma["stock_total"] == 0
    assert goma["sedes"] == []
    assert goma["es_critico"] is True, "0 <= stock_minimo, semantica vigente"


def test_existencias_con_sede_acotan_saldo_sedes_y_criticidad(motor, mundo):
    """AC-1/D-7: con `sede_id` valido, total, sedes y criticidad son de esa sede."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        filas = _existencias(cliente_http, sede_id=mundo["sede_norte"])

    cuaderno = producto_de_existencias(filas, mundo["producto_id"])
    assert cuaderno["stock_total"] == 30
    assert [fila["sede_id"] for fila in cuaderno["sedes"]] == [
        mundo["sede_norte"]
    ]

    # Critico en el agregado (3 en Sur) pero holgado en Norte (100): la franja
    # debe describir la sede consultada.
    regla = producto_de_existencias(filas, mundo["producto_regla"])
    assert regla["stock_total"] == 100
    assert regla["es_critico"] is False, "100 > 10 en la sede filtrada"

    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        agregado = _existencias(cliente_http)
    assert producto_de_existencias(agregado, mundo["producto_regla"])[
        "es_critico"
    ] is True, "sin filtro, la sede Sur (3) marca el producto como critico"


def test_existencias_sede_inexistente_responde_200_vacio(motor, mundo):
    """AC-3/D-7: `sede_id` ausente del esquema del actor es 200 con lista vacia."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        respuesta = cliente_http.get(RUTA_EXISTENCIAS, params={"sede_id": 999_999})

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


def test_existencias_sede_de_otra_institucion_responde_200_vacio(motor, mundo):
    """AC-3: un id de sede de otro tenant no se distingue de uno inexistente.

    Esto **no** contradice el 404 de `GET /inventario/stock?sede_id=…` de la
    Feature 011: alli se consulta un recurso, aqui se filtra una lista.
    """
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        respuesta = cliente_http.get(
            RUTA_EXISTENCIAS, params={"sede_id": mundo["sede_ajena"]}
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


# ===========================================================================
# AC-3/AC-4: ambito de `sede_id` por rol
# ===========================================================================


def test_existencias_bodeguero_filtra_su_sede_y_otra_sede_da_vacio(motor, mundo):
    """AC-3/D-7: su propia sede filtra; cualquier otra es 200/[] por interseccion."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Bodeguero") as cliente_http:
        propia = _existencias(cliente_http, sede_id=mundo["sede_norte"])
        otra = _existencias(cliente_http, sede_id=mundo["sede_sur"])

    assert _ids(propia) == {mundo["producto_id"], mundo["producto_regla"], mundo["producto_toner"]}
    assert otra == []


@pytest.mark.parametrize("rol", ["Bodeguero", "Solicitante"])
def test_existencias_sin_filtro_de_rol_operativo_ya_esta_acotada(motor, mundo, rol):
    """AC-3: el recorte de sede del rol operativo se conserva sin `sede_id`."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, rol) as cliente_http:
        filas = _existencias(cliente_http)

    sedes = {sede["sede_id"] for fila in filas for sede in fila["sedes"]}
    assert sedes == {mundo["sede_norte"]}, "solo la sede de su alcance"


def test_existencias_solicitante_su_sede_filtra_y_otra_sede_da_vacio(motor, mundo):
    """AC-3/D-7: el Solicitante conserva su lectura y la interseccion por sede."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Solicitante") as cliente_http:
        propia = _existencias(cliente_http, sede_id=mundo["sede_norte"])
        otra = _existencias(cliente_http, sede_id=mundo["sede_sur"])

    assert mundo["producto_id"] in _ids(propia)
    assert otra == []


# ===========================================================================
# AC-2/AC-3: combinacion con `departamento_id`
# ===========================================================================


def test_departamentos_de_la_misma_sede_devuelven_el_mismo_saldo(motor, mundo):
    """AC-2/D-2: el departamento solo localiza la sede; el saldo es compartido."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        operaciones = _existencias(
            cliente_http, departamento_id=mundo["departamento_id"]
        )
        almacen = _existencias(cliente_http, departamento_id=mundo["dep_almacen"])

    assert operaciones == almacen, "dos departamentos de la misma sede, mismo saldo"
    cuaderno = producto_de_existencias(operaciones, mundo["producto_id"])
    assert cuaderno["stock_total"] == 30, "el saldo es el de la sede, no del depto"


def test_existencias_sede_y_departamento_coherentes_acotan_igual(motor, mundo):
    """AC-3: si ambos filtros son coherentes, se aplican juntos sin cambiar la lista."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        solo_sede = _existencias(cliente_http, sede_id=mundo["sede_norte"])
        ambos = _existencias(
            cliente_http,
            sede_id=mundo["sede_norte"],
            departamento_id=mundo["dep_almacen"],
        )

    assert _ids(ambos) == _ids(solo_sede)


def test_existencias_sede_y_departamento_incoherentes_responde_200_vacio(
    motor, mundo
):
    """AC-3/D-7: un par incoherente responde lista vacia (la UI no lo envia)."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        respuesta = cliente_http.get(
            RUTA_EXISTENCIAS,
            params={
                "sede_id": mundo["sede_sur"],
                "departamento_id": mundo["dep_almacen"],  # Almacen esta en Norte
            },
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


@pytest.mark.parametrize("caso", ["sin_sede", "inexistente", "otra_sede_sin_stock"])
def test_existencias_departamento_no_resoluble_responde_200_vacio(
    motor, mundo, caso
):
    """AC-4/D-7: departamento sin sede, inexistente o de una sede sin saldo -> []."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    if caso == "sin_sede":
        departamento_id = mundo["dep_sin_sede"]
    elif caso == "inexistente":
        departamento_id = 999_999
    else:
        departamento_id = mundo["dep_este"]  # sede Este, sin filas de stock

    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        respuesta = cliente_http.get(
            RUTA_EXISTENCIAS, params={"departamento_id": departamento_id}
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == []


def test_existencias_departamento_de_otra_institucion_responde_403(motor, mundo):
    """AC-4: 403 solo en el arnes SQLite, donde la fila ajena es visible.

    En PostgreSQL cada tenant vive en su esquema: un `departamento_id` ajeno no
    existe en el esquema del actor y el resultado correcto es 200/[] (plan §1.4).
    Por eso esta prueba no se replica en la suite gated.
    """
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        respuesta = cliente_http.get(
            RUTA_EXISTENCIAS,
            params={"departamento_id": mundo["departamento_ajeno_id"]},
        )

    assert respuesta.status_code == 403, respuesta.text


# ===========================================================================
# AC-6: productos sin saldo ocultos al filtrar
# ===========================================================================


def test_existencias_con_filtro_organizacional_oculta_productos_sin_saldo(
    motor, mundo
):
    """AC-6/D-7: sin filtro aparece en cero; con sede o departamento desaparece."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        sin_filtro = _existencias(cliente_http)
        por_sede = _existencias(cliente_http, sede_id=mundo["sede_norte"])
        por_departamento = _existencias(
            cliente_http, departamento_id=mundo["dep_almacen"]
        )

    assert mundo["producto_goma"] in _ids(sin_filtro)
    assert mundo["producto_goma"] not in _ids(por_sede)
    assert mundo["producto_goma"] not in _ids(por_departamento)


# ===========================================================================
# AC-7/AC-3: los filtros existentes siguen funcionando junto a `sede_id`
# ===========================================================================


def test_existencias_filtros_existentes_combinan_con_sede_id(motor, mundo):
    """AC-7: texto, categoria y criticidad se aplican sobre el conjunto de la sede."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente_de_rol(motor, mundo, "Administrador") as cliente_http:
        por_texto = _existencias(
            cliente_http, q="Cuaderno", sede_id=mundo["sede_norte"]
        )
        por_categoria = _existencias(
            cliente_http, categoria_id=mundo["categoria_toner"], sede_id=mundo["sede_norte"]
        )
        criticos = _existencias(
            cliente_http, solo_criticos=True, sede_id=mundo["sede_norte"]
        )

    assert _ids(por_texto) == {mundo["producto_id"]}
    assert _ids(por_categoria) == {mundo["producto_toner"]}
    # En Norte: Cuaderno 30, Regla 100 y Toner 5 (minimo 10) -> solo el Toner.
    assert _ids(criticos) == {mundo["producto_toner"]}


def test_existencias_bodeguero_sin_sede_responde_409(motor, mundo):
    """AC-4: el rol de sede operativa sin asignacion no cae a otra sede."""
    _exigir_ruta_018(RUTA_EXISTENCIAS)
    with cliente(
        motor, "Bodeguero", departamento_id=mundo["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.get(RUTA_EXISTENCIAS)

    assert respuesta.status_code == 409, respuesta.text
    assert "sede" in respuesta.json()["detail"].lower()


# ===========================================================================
# AC-8: matriz central aditiva (60 -> 61)
# ===========================================================================


def test_matriz_declara_la_operacion_de_ambito_para_administrador_y_bodeguero():
    """AC-8/D-6: exactamente una operacion nueva, con los dos roles de la spec."""
    for clave, roles in OPERACIONES_018.items():
        _exigir_operacion_018(*clave)
        assert set(permisos.MATRIZ_PERMISOS[clave]) == roles, clave


def test_matriz_conserva_las_operaciones_previas_intactas():
    """AC-8: la 018 solo agrega; ninguna operacion previa cambia de roles.

    Se compara contra las transcripciones historicas independientes de las
    Features 012, 013 y 014 (nunca contra `MATRIZ_PERMISOS` como fuente).
    """
    for clave in OPERACIONES_018:
        _exigir_operacion_018(*clave)
    for clave, roles in MATRIZ_012.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion {clave} desaparecio de la matriz"
        esperado = set(roles) - ({"Superadmin"} if clave in RETIRADAS_017 else set())
        assert set(actual) == esperado, clave
    for clave, roles in OPERACIONES_013.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion de la 013 {clave} desaparecio"
        assert set(actual) == roles, clave
    for clave, roles in OPERACIONES_014.items():
        actual = permisos.MATRIZ_PERMISOS.get(clave)
        assert actual is not None, f"la operacion de la 014 {clave} desaparecio"
        assert set(actual) == roles, clave


def test_matriz_tiene_exactamente_61_operaciones_tras_018():
    """AC-8: 60 previas + la unica operacion nueva de la 018."""
    total = len(permisos.MATRIZ_PERMISOS)
    previas = set(permisos.MATRIZ_PERMISOS) - set(OPERACIONES_018)
    assert total == TOTAL_OPERACIONES_018, (
        "la matriz debe tener 61 operaciones (60 previas + la de ambito); "
        f"tiene {total}"
    )
    assert len(previas) == 60, (
        "la operacion nueva no puede sustituir a ninguna previa; "
        f"quedan {len(previas)} operaciones anteriores"
    )


def test_capacidad_inventario_asociada_a_la_operacion_de_ambito():
    """AC-8: la lectura nueva se gatea con la capacidad `inventario` existente."""
    for clave, esperada in CAPACIDADES_018.items():
        _exigir_capacidad_018(*clave)
        assert capacidades.capacidad_de_operacion(*clave) == esperada, clave


# ===========================================================================
# AC-8/AC-9: contrato OpenAPI
# ===========================================================================


def test_openapi_publica_ambito_y_el_parametro_sede_id(cliente):
    """AC-8/AC-9: el contrato publica la ruta nueva y `sede_id` en existencias."""
    contrato = cliente.get("/openapi.json").json()

    ambito = contrato["paths"].get(RUTA_AMBITO, {}).get("get")
    if ambito is None:
        pytest.fail(
            f"capacidad ausente (T4): GET {RUTA_AMBITO} no esta publicada en "
            "/openapi.json; la Feature 018 la cablea en T4."
        )
    assert ambito.get("parameters", []) == [], (
        "la lectura de ambito no recibe parametros ni cuerpo"
    )

    existencias = contrato["paths"][RUTA_EXISTENCIAS]["get"]
    parametros = {
        parametro["name"]: parametro
        for parametro in existencias.get("parameters", [])
        if parametro.get("in") == "query"
    }
    if "sede_id" not in parametros:
        pytest.fail(
            "capacidad ausente (T4): GET /api/v1/inventario/existencias no declara "
            "el parametro de query `sede_id`; la Feature 018 lo agrega en T4."
        )
    assert parametros["sede_id"]["required"] is False, (
        "`sede_id` es un filtro opcional"
    )


def test_openapi_documenta_respuestas_de_ambito_y_existencias(cliente):
    """AC-8: ambito documenta 200/401/403/409; existencias conserva 200/401/403."""
    contrato = cliente.get("/openapi.json").json()

    ambito = contrato["paths"].get(RUTA_AMBITO, {}).get("get")
    if ambito is None:
        pytest.fail(
            f"capacidad ausente (T4): GET {RUTA_AMBITO} no esta publicada en "
            "/openapi.json; la Feature 018 la cablea en T4."
        )
    respuestas_ambito = set(ambito.get("responses", {}))
    assert {"200", "401", "403", "409"} <= respuestas_ambito, sorted(
        respuestas_ambito
    )

    respuestas_existencias = set(
        contrato["paths"][RUTA_EXISTENCIAS]["get"].get("responses", {})
    )
    assert {"200", "401", "403"} <= respuestas_existencias, sorted(
        respuestas_existencias
    )
    assert "409" in respuestas_existencias or "409" in contrato["paths"][
        RUTA_EXISTENCIAS
    ]["get"].get("description", ""), (
        "el 409 del rol operativo sin sede debe quedar documentado"
    )


def test_openapi_publica_61_operaciones_tras_018(cliente):
    """AC-8/AC-9: el contrato v1 publica la misma cardinalidad que la matriz."""
    contrato = cliente.get("/openapi.json").json()
    total = sum(
        1
        for ruta, operaciones in contrato["paths"].items()
        if ruta.startswith(_PREFIJO_CONTRATO)
        for metodo in operaciones
        if metodo in _METODOS_OPENAPI
    )
    assert total == TOTAL_OPERACIONES_018, (
        f"/openapi.json debe publicar 61 operaciones v1; publica {total}"
    )
