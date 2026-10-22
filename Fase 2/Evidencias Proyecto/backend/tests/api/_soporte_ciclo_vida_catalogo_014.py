"""Soporte compartido de las pruebas rojas de la Feature 014 (ciclo de vida del catalogo).

Los modulos `test_ciclo_vida_*_014.py` comparten cinco necesidades:

1. **Contrato de rutas y operaciones.** La 014 agrega cinco operaciones
   (transicion de producto, transicion de categoria, historial de producto,
   historial de categoria y listado de gestion). Este modulo las fija como
   constantes para que todos los modulos hablen del mismo contrato. La spec
   delega los paths concretos al plan; T2 los fija como contrato observable
   (patron de la 011/013).
2. **Fase roja explicita.** `exigir_ruta`/`exigir_operacion` fallan con
   `pytest.fail` mientras la 014 no cablee la API/matriz (T6/T9), de modo que
   una prueba que espera `403`/`404` nunca pase por el motivo equivocado (ruta
   u operacion ausentes). Los helpers de estado fallan con `pytest.fail` si la
   columna `activo` o las tablas de historial aun no existen (T4).
3. **Construccion del mundo**: catalogo de estados, sede del departamento,
   stock por sede, productos/categorias adicionales y marcado directo de
   estados para preparar escenarios (producto inactivo, categoria inactiva).
4. **Observacion**: estado por ORM (con guarda de capacidad), historial por
   HTTP, listado de gestion por HTTP y conteos de referencias.
5. **Gating de capacidades**: contexto de control coherente para que el correo
   de la sonda resuelva a INST01 con todas las capacidades menos las apagadas.

El seam bajo prueba en toda la 014 es la interfaz HTTP (`TestClient`), como en
el resto de la suite; este soporte no prueba nada por si solo.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core import capacidades, permisos
from app.main import app
from app.models import (
    CAPACIDADES,
    Categoria,
    FuncionInstitucion,
    InstitucionControl,
    MapaUsuarioEsquema,
    Producto,
    StockSede,
    VersionEsquema,
)

from ._soporte_ciclo_vida_013 import sembrar_mundo_013
from ._soporte_sede_011 import (
    SIN_AUTENTICAR,
    cliente as cliente_con_rol,
    contar_en,
    identidad,
    modelo,
    sesion,
)

# ---------------------------------------------------------------------------
# Contrato de rutas y operaciones (spec D-9/§7, plan §2)
# ---------------------------------------------------------------------------

#: Transicion del estado vigente de un producto existente (`{"activo": bool,
#: "motivo": str}`). El estado destino viaja explicito en el cuerpo.
RUTA_PRODUCTO_ESTADO = "/api/v1/inventario/productos/{producto_id}/estado"
#: Transicion del estado vigente de una categoria existente.
RUTA_CATEGORIA_ESTADO = "/api/v1/inventario/categorias/{categoria_id}/estado"
#: Historial inmutable de transiciones de un producto (solo `GET`).
RUTA_PRODUCTO_HISTORIAL = "/api/v1/inventario/productos/{producto_id}/historial"
#: Historial inmutable de transiciones de una categoria (solo `GET`).
RUTA_CATEGORIA_HISTORIAL = "/api/v1/inventario/categorias/{categoria_id}/historial"
#: Listado administrativo conjunto de productos y categorias, con su estado.
RUTA_GESTION = "/api/v1/inventario/gestion"

#: Las cinco operaciones nuevas con los roles exactos del AC-2/AC-12/AC-15
#: (transcritos de la spec, nunca leidos de `MATRIZ_PERMISOS` para evitar la
#: prueba tautologica): solo el Administrador Institucional.
OPERACIONES_014: dict[tuple[str, str], set[str]] = {
    ("PATCH", RUTA_PRODUCTO_ESTADO): {"Administrador"},
    ("PATCH", RUTA_CATEGORIA_ESTADO): {"Administrador"},
    ("GET", RUTA_PRODUCTO_HISTORIAL): {"Administrador"},
    ("GET", RUTA_CATEGORIA_HISTORIAL): {"Administrador"},
    ("GET", RUTA_GESTION): {"Administrador"},
}

#: Toda operacion nueva de la 014 queda gated bajo la capacidad `catalogo`
#: (plan §2.6); no se amplia el conjunto cerrado de la 012.
CAPACIDADES_014: dict[tuple[str, str], str] = {
    clave: "catalogo" for clave in OPERACIONES_014
}

#: Campos que cada fila del historial de producto debe exponer por API
#: (`stack.md` §2: historial de transicion de producto, AC-7/AC-12). El plan
#: fija origen/destino booleanos, actor, instante y motivo; los nombres son
#: parte del contrato que fija T2.
CAMPOS_HISTORIAL_PRODUCTO: frozenset[str] = frozenset(
    {
        "historial_producto_id",
        "producto_id",
        "usuario_id",
        "fecha_transicion",
        "activo_origen",
        "activo_destino",
        "motivo",
    }
)

#: Campos de cada fila del historial de categoria (tabla hermana).
CAMPOS_HISTORIAL_CATEGORIA: frozenset[str] = frozenset(
    {
        "historial_categoria_id",
        "categoria_id",
        "usuario_id",
        "fecha_transicion",
        "activo_origen",
        "activo_destino",
        "motivo",
    }
)

#: Claves del listado de gestion (plan §2.7): productos y categorias del
#: tenant, ambos estados, con `activo` incluido en cada recurso.
CLAVES_GESTION: frozenset[str] = frozenset({"productos", "categorias"})

#: 404 identico para recurso inexistente y ajeno (AC-2/AC-12).
DETALLE_PRODUCTO_NO_ENCONTRADO = "Producto no encontrado"
DETALLE_CATEGORIA_NO_ENCONTRADA = "Categoria no encontrada"

#: Sentinela para distinguir "motivo ausente" de "motivo null" en el payload.
AUSENTE = object()

_CORREO_GATING = "gating014.inst01@compustock.cl"


# ---------------------------------------------------------------------------
# Guardas de la fase roja (patron de `_soporte_sede_011.py`/`_soporte_ciclo_vida_013.py`)
# ---------------------------------------------------------------------------


def exigir_ruta(ruta: str, metodo: str) -> None:
    """Falla si la operacion aun no esta publicada en el contrato OpenAPI (T9)."""
    operaciones = app.openapi().get("paths", {}).get(ruta, {})
    if metodo.lower() not in operaciones:
        pytest.fail(
            f"capacidad ausente (T9): {metodo.upper()} {ruta} no esta publicada "
            "en /openapi.json; la Feature 014 la cablea en T9."
        )


def exigir_operacion(metodo: str, ruta: str) -> None:
    """Falla si la operacion aun no esta declarada en la matriz central (T6)."""
    if (metodo.upper(), ruta) not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            f"capacidad ausente (T6): MATRIZ_PERMISOS no declara "
            f"{(metodo.upper(), ruta)}; la Feature 014 la agrega en T6."
        )


def exigir_capacidad_asociada(metodo: str, ruta: str) -> None:
    """Falla si la operacion aun no esta asociada a una capacidad (T6)."""
    if capacidades.capacidad_de_operacion(metodo, ruta) is None:
        pytest.fail(
            f"capacidad ausente (T6): MAPA_OPERACION_CAPACIDAD no asocia "
            f"{(metodo.upper(), ruta)} a ninguna capacidad; la Feature 014 lo "
            "hace en T6."
        )


def exigir_columna(entidad: Any, columna: str, entidad_nombre: str) -> None:
    """Falla si falta una columna del modelo (capacidad ausente de T4)."""
    if columna not in set(entidad.__table__.columns.keys()):
        pytest.fail(
            f"capacidad ausente (T4): `{entidad_nombre}.{columna}` no existe "
            "todavia; la Feature 014 lo agrega en T4."
        )


# ---------------------------------------------------------------------------
# Identidad y cliente HTTP por rol
# ---------------------------------------------------------------------------


def cliente_de_rol(
    motor,
    datos: dict[str, Any],
    rol: Any = SIN_AUTENTICAR,
    *,
    ajeno: bool = False,
    correo: str | None = None,
    usuario_id: int | None = None,
):
    """`TestClient` del `app` real con la identidad del rol pedido.

    `ajeno=True` usa el usuario del mismo rol en INST02 (para el 404 oculto de
    AC-2). El Bodeguero recibe su `sede_id` para que el ambito operativo de la
    011 resuelva. `rol=SIN_AUTENTICAR` conserva el 401 real de la sesion ausente.
    """
    if rol is SIN_AUTENTICAR:
        return cliente_con_rol(motor, SIN_AUTENTICAR)
    if ajeno:
        departamento_id = datos["departamento_ajeno_id"]
        identificador = datos["usuarios_inst02"][rol]
    else:
        departamento_id = datos["departamento_id"]
        if rol == "Administrador":
            identificador = datos["usuario_id"]
        else:
            identificador = datos["usuarios_inst01"][rol]
    if usuario_id is not None:
        identificador = usuario_id
    opciones: dict[str, Any] = {"departamento_id": departamento_id,
                                "usuario_id": identificador}
    if rol == "Bodeguero":
        opciones["sede_id"] = datos.get("sede_id")
    if correo is not None:
        opciones["correo"] = correo
    return cliente_con_rol(motor, rol, **opciones)


# ---------------------------------------------------------------------------
# Construccion del mundo
# ---------------------------------------------------------------------------


def sembrar_mundo_014(motor, datos: dict[str, Any]) -> dict[str, Any]:
    """Catalogo de estados, sede y stock base sobre un padron existente.

    Reutiliza `sembrar_mundo_013` (estados del flujo + sede del departamento con
    50 unidades del producto base) porque la 014 solo necesita ese mundo como
    punto de partida: el catalogo de estados no cambia y la sede es donde se mide
    el saldo operativo de la precondicion de baja (D-6).
    """
    return sembrar_mundo_013(motor, datos)


def crear_categoria(
    motor,
    datos: dict[str, Any],
    *,
    nombre: str = "Categoria 014",
    institucion_id: str | None = None,
) -> int:
    """Crea una categoria del tenant y devuelve su id."""
    institucion = institucion_id or datos["institucion_id"]
    with sesion(motor) as db:
        fila = Categoria(
            nombre_cat=nombre,
            descripcion_cat=f"Categoria de prueba {nombre}",
            institucion_id=institucion,
        )
        fila.activo = True  # Feature 014: una categoria nueva de fixture nace activa.
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.categoria_id


def crear_producto(
    motor,
    datos: dict[str, Any],
    *,
    nombre: str = "Producto 014",
    categoria_id: int | None = None,
    stock_minimo: int = 0,
    stock_sede: int | None = None,
    institucion_id: str | None = None,
) -> int:
    """Crea un producto del tenant y, opcionalmente, su fila de stock por sede.

    `stock_sede=None` deja el producto **sin fila** en `stock_sede` (saldo cero
    por ausencia, D-6); `stock_sede=0` crea la fila en cero. Devuelve el id.
    """
    institucion = institucion_id or datos["institucion_id"]
    with sesion(motor) as db:
        fila = Producto(
            nombre=nombre,
            descripcion=f"Producto de prueba {nombre}",
            unidad_medida="UNIDAD",
            stock_minimo=stock_minimo,
            categoria_id=categoria_id or datos["categoria_id"],
            institucion_id=institucion,
        )
        fila.activo = True  # Feature 014: un producto nuevo de fixture nace activo.
        db.add(fila)
        db.flush()
        if stock_sede is not None:
            db.add(
                StockSede(
                    sede_id=datos["sede_id"],
                    producto_id=fila.producto_id,
                    stock_actual=stock_sede,
                    institucion_id=institucion,
                )
            )
        db.commit()
        db.refresh(fila)
        return fila.producto_id


def fijar_stock_sede(
    motor,
    datos: dict[str, Any],
    producto_id: int,
    cantidad: int,
    *,
    sede_id: int | None = None,
) -> None:
    """Fija el saldo operativo de un producto en una sede (crea la fila si falta)."""
    sede = sede_id if sede_id is not None else datos["sede_id"]
    with sesion(motor) as db:
        fila = db.execute(
            select(StockSede).where(
                StockSede.sede_id == sede,
                StockSede.producto_id == producto_id,
            )
        ).scalar_one_or_none()
        if fila is None:
            fila = StockSede(
                sede_id=sede,
                producto_id=producto_id,
                stock_actual=cantidad,
                institucion_id=datos["institucion_id"],
            )
            db.add(fila)
        else:
            fila.stock_actual = cantidad
        db.commit()


def marcar_producto(motor, producto_id: int, activo: bool) -> None:
    """Marca directamente el estado de un producto (preparacion del escenario).

    La transicion **real** se ejerce por HTTP; esto solo deja el mundo en el
    estado que el escenario necesita (p. ej. un producto ya inactivo para probar
    la idempotencia). Falla con `pytest.fail` mientras T4 no cree `activo`.
    """
    exigir_columna(Producto, "activo", "producto")
    with sesion(motor) as db:
        producto = db.get(Producto, producto_id)
        assert producto is not None, f"producto {producto_id} inexistente"
        producto.activo = activo
        db.commit()


def marcar_categoria(motor, categoria_id: int, activo: bool) -> None:
    """Marca directamente el estado de una categoria (preparacion del escenario)."""
    exigir_columna(Categoria, "activo", "categoria")
    with sesion(motor) as db:
        categoria = db.get(Categoria, categoria_id)
        assert categoria is not None, f"categoria {categoria_id} inexistente"
        categoria.activo = activo
        db.commit()


def activo_de_producto(motor, producto_id: int) -> bool:
    """Estado vigente de un producto, observado por ORM."""
    exigir_columna(Producto, "activo", "producto")
    with sesion(motor) as db:
        return db.get(Producto, producto_id).activo


def activo_de_categoria(motor, categoria_id: int) -> bool:
    """Estado vigente de una categoria, observado por ORM."""
    exigir_columna(Categoria, "activo", "categoria")
    with sesion(motor) as db:
        return db.get(Categoria, categoria_id).activo


def contar(motor, entidad: Any, **filtros) -> int:
    """Cuenta filas de una entidad por ORM (referencias que no deben alterarse)."""
    return contar_en(motor, entidad, **filtros)


# ---------------------------------------------------------------------------
# HTTP: transiciones, historial y gestion
# ---------------------------------------------------------------------------


def payload_transicion(*, activo: bool, motivo: Any = AUSENTE) -> dict:
    """Cuerpo de una transicion: estado destino y motivo opcional/omitible."""
    cuerpo: dict[str, Any] = {"activo": activo}
    if motivo is not AUSENTE:
        cuerpo["motivo"] = motivo
    return cuerpo


def transicionar_producto(
    cliente,
    producto_id: int,
    *,
    activo: bool,
    motivo: Any = AUSENTE,
):
    """`PATCH /inventario/productos/{id}/estado` como lo haria un cliente real."""
    return cliente.patch(
        RUTA_PRODUCTO_ESTADO.format(producto_id=producto_id),
        json=payload_transicion(activo=activo, motivo=motivo),
    )


def transicionar_categoria(
    cliente,
    categoria_id: int,
    *,
    activo: bool,
    motivo: Any = AUSENTE,
):
    """`PATCH /inventario/categorias/{id}/estado`."""
    return cliente.patch(
        RUTA_CATEGORIA_ESTADO.format(categoria_id=categoria_id),
        json=payload_transicion(activo=activo, motivo=motivo),
    )


def historial_producto(cliente, producto_id: int) -> list[dict]:
    """`GET /inventario/productos/{id}/historial` (lista, posiblemente vacia)."""
    respuesta = cliente.get(
        RUTA_PRODUCTO_HISTORIAL.format(producto_id=producto_id)
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def historial_categoria(cliente, categoria_id: int) -> list[dict]:
    """`GET /inventario/categorias/{id}/historial`."""
    respuesta = cliente.get(
        RUTA_CATEGORIA_HISTORIAL.format(categoria_id=categoria_id)
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def listado_gestion(cliente) -> dict[str, list[dict]]:
    """`GET /inventario/gestion` (productos y categorias con su estado)."""
    respuesta = cliente.get(RUTA_GESTION)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# ---------------------------------------------------------------------------
# Gating de capacidades (mismo patron que `test_gating_capacidades_endpoints_012.py`)
# ---------------------------------------------------------------------------


def sembrar_contexto_capacidades(
    motor,
    datos: dict[str, Any],
    capacidades_apagadas: frozenset[str] = frozenset(),
    *,
    correo: str = _CORREO_GATING,
) -> None:
    """Control coherente para que `correo` resuelva a INST01 con las capacidades dadas."""
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
        if db.get(MapaUsuarioEsquema, correo) is None:
            db.add(
                MapaUsuarioEsquema(
                    correo=correo,
                    institucion_id=institucion_id,
                    nombre_esquema="tenant_inst01",
                    activo=True,
                )
            )
            db.flush()
        if db.execute(select(VersionEsquema)).scalars().first() is None:
            from app.core.config import VERSION_ESQUEMA_OBJETIVO

            db.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
        for funcion in CAPACIDADES:
            db.add(
                FuncionInstitucion(
                    institucion_id=institucion_id,
                    funcion=funcion,
                    habilitada=funcion not in capacidades_apagadas,
                )
            )
        db.commit()


CORREO_GATING = _CORREO_GATING


def conteo_por_estado(motor, entidad: Any, campo: str, valor: Any) -> int:
    """Cuenta filas por un filtro de columna (helper de aserciones de referencia)."""
    with sesion(motor) as db:
        return db.execute(
            select(func.count()).select_from(entidad).where(
                getattr(entidad, campo) == valor
            )
        ).scalar_one()


__all__ = [
    "AUSENTE",
    "CAMPOS_HISTORIAL_CATEGORIA",
    "CAMPOS_HISTORIAL_PRODUCTO",
    "CAPACIDADES_014",
    "CLAVES_GESTION",
    "CORREO_GATING",
    "DETALLE_CATEGORIA_NO_ENCONTRADA",
    "DETALLE_PRODUCTO_NO_ENCONTRADO",
    "OPERACIONES_014",
    "RUTA_CATEGORIA_ESTADO",
    "RUTA_CATEGORIA_HISTORIAL",
    "RUTA_GESTION",
    "RUTA_PRODUCTO_ESTADO",
    "RUTA_PRODUCTO_HISTORIAL",
    "SIN_AUTENTICAR",
    "activo_de_categoria",
    "activo_de_producto",
    "cliente_de_rol",
    "conteo_por_estado",
    "contar",
    "crear_categoria",
    "crear_producto",
    "exigir_capacidad_asociada",
    "exigir_columna",
    "exigir_operacion",
    "exigir_ruta",
    "fijar_stock_sede",
    "historial_categoria",
    "historial_producto",
    "identidad",
    "listado_gestion",
    "marcar_categoria",
    "marcar_producto",
    "modelo",
    "payload_transicion",
    "sembrar_contexto_capacidades",
    "sembrar_mundo_014",
    "sesion",
    "transicionar_categoria",
    "transicionar_producto",
]
