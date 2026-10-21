"""T6 (Feature 014): contrato de los DTO del ciclo de vida del catalogo.

Seam bajo prueba: los modelos Pydantic v2 del catalogo (entrada de transicion,
recursos con su estado, filas del listado de gestion y filas de los dos
historiales). Es el contrato que T7 consume en el servicio y T9 publica como
`response_model` en `/openapi.json`; fijarlo aqui evita que la implementacion
lo deforme al cablear las rutas.

Dos reglas del plan §2.3 se comprueban de forma explicita:

* el payload de transicion admite **solo** el estado destino y un `motivo`
  opcional, y **no** valida contenido ni longitud en Pydantic: la validacion
  (no vacio, no solo espacios, <=500) es del servicio, para respetar el orden
  404 -> 200 idempotente -> 422 -> 409 de AC-3/AC-8 (si el schema rechazara el
  cuerpo, el 422 se adelantaria al 404 y a la idempotencia);
* los read models de historial exponen los siete campos del contrato fijado por
  T2, sin publicar ninguna operacion de escritura.

Fase ROJA de TDD: los modulos de schema aun no declaran estos DTO (los agrega
T6). Las pruebas fallan por esa ausencia, nunca por logica ajena.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.producto import (
    HistorialTransicionCategoria,
    HistorialTransicionProducto,
)
from app.schemas.inventario_schema import (
    GestionCatalogoRespuesta,
    HistorialTransicionCategoriaRespuesta,
    HistorialTransicionProductoRespuesta,
)
from app.schemas.producto_schema import (
    CategoriaGestionRespuesta,
    CategoriaRespuesta,
    ProductoGestionRespuesta,
    ProductoRespuesta,
    TransicionCatalogo,
)

#: Campos del contrato de historial de producto fijado por T2 (`stack.md` §2).
CAMPOS_HISTORIAL_PRODUCTO = {
    "historial_producto_id",
    "producto_id",
    "usuario_id",
    "fecha_transicion",
    "activo_origen",
    "activo_destino",
    "motivo",
}

#: Campos del contrato de historial de categoria (tabla hermana).
CAMPOS_HISTORIAL_CATEGORIA = {
    "historial_categoria_id",
    "categoria_id",
    "usuario_id",
    "fecha_transicion",
    "activo_origen",
    "activo_destino",
    "motivo",
}

#: Campos de presentacion resueltos por el servicio (patron de la 013): el actor
#: se muestra legible sin que la vista cruce `/usuarios/`.
CAMPOS_ACTOR = {"usuario_nombre", "usuario_apellido"}


# ---------------------------------------------------------------------------
# AC-3/AC-7/AC-8: payload de transicion sin validacion adelantada del motivo
# ---------------------------------------------------------------------------


def test_transicion_acepta_solo_el_estado_destino_y_deja_el_motivo_nulo():
    """AC-8: repetir el estado destino no exige motivo en el schema."""
    transicion = TransicionCatalogo.model_validate({"activo": False})
    assert transicion.activo is False
    assert transicion.motivo is None


@pytest.mark.parametrize(
    "motivo",
    [None, "", "   ", "x" * 501],
    ids=["nulo", "vacio", "solo_espacios", "501_caracteres"],
)
def test_transicion_no_adelanta_la_validacion_del_motivo(motivo):
    """AC-3/AC-7: el motivo invalido debe llegar al servicio para ordenar 404/422.

    Un `min_length`/`max_length`/validador en Pydantic convertiria estos cuerpos
    en 422 antes del handler, adelantandose al 404 de ambito y a la idempotencia
    de AC-8.
    """
    transicion = TransicionCatalogo.model_validate({"activo": False, "motivo": motivo})
    assert transicion.motivo == motivo


def test_transicion_conserva_literal_un_motivo_de_500_caracteres():
    """AC-7: el limite valido es 500 inclusive y el texto no se transforma."""
    motivo = "m" * 500
    transicion = TransicionCatalogo.model_validate({"activo": True, "motivo": motivo})
    assert transicion.motivo == motivo


@pytest.mark.parametrize(
    "payload",
    [{}, {"motivo": "Solo motivo"}, {"activo": None}],
    ids=["sin_activo", "sin_activo_con_motivo", "activo_nulo"],
)
def test_transicion_exige_el_estado_destino(payload):
    """AC-7: sin `activo` no hay transicion que interpretar (422 de forma)."""
    with pytest.raises(ValidationError):
        TransicionCatalogo.model_validate(payload)


# ---------------------------------------------------------------------------
# AC-13/AC-15: los recursos exponen su estado
# ---------------------------------------------------------------------------


def test_producto_respuesta_expone_el_estado():
    """AC-13: el alta y la transicion devuelven el producto con su estado."""
    producto = ProductoRespuesta.model_validate(
        {
            "producto_id": 7,
            "nombre": "Resma",
            "unidad_medida": "UNIDAD",
            "stock_minimo": 1,
            "categoria_id": 3,
            "institucion_id": "INST01",
            "activo": False,
        }
    )
    assert producto.activo is False


def test_categoria_respuesta_expone_el_estado():
    """AC-15: la categoria expone su estado igual que la sede y el departamento."""
    categoria = CategoriaRespuesta.model_validate(
        {
            "categoria_id": 3,
            "nombre_cat": "Papeleria",
            "institucion_id": "INST01",
            "activo": True,
        }
    )
    assert categoria.activo is True


# ---------------------------------------------------------------------------
# AC-15: items del listado de gestion
# ---------------------------------------------------------------------------


def test_gestion_agrupa_productos_y_categorias():
    """AC-15: el listado de gestion publica exactamente las dos colecciones."""
    gestion = GestionCatalogoRespuesta(productos=[], categorias=[])
    assert set(gestion.model_dump()) == {"productos", "categorias"}


def test_producto_de_gestion_incluye_su_estado_y_el_de_su_categoria():
    """AC-15: la fila de gestion permite decidir acciones sin cruzar la operativa."""
    fila = ProductoGestionRespuesta(
        producto_id=7,
        nombre="Resma",
        categoria_id=3,
        categoria_nombre="Papeleria",
        categoria_activa=False,
        stock_minimo=1,
        activo=False,
    )
    assert fila.activo is False
    assert fila.categoria_activa is False


def test_categoria_de_gestion_incluye_su_estado():
    """AC-15: la fila de gestion de categoria expone `activo`."""
    fila = CategoriaGestionRespuesta(
        categoria_id=3, nombre_cat="Papeleria", activo=False
    )
    assert fila.activo is False


# ---------------------------------------------------------------------------
# AC-7/AC-12: read models de historial
# ---------------------------------------------------------------------------


def test_historial_de_producto_expone_el_contrato_sin_campos_inventados():
    assert set(HistorialTransicionProductoRespuesta.model_fields) == (
        CAMPOS_HISTORIAL_PRODUCTO | CAMPOS_ACTOR
    )


def test_historial_de_categoria_expone_el_contrato_sin_campos_inventados():
    assert set(HistorialTransicionCategoriaRespuesta.model_fields) == (
        CAMPOS_HISTORIAL_CATEGORIA | CAMPOS_ACTOR
    )


def test_historial_de_producto_se_construye_desde_la_entidad():
    """El read model es una proyeccion de la entidad: `from_attributes`."""
    entidad = HistorialTransicionProducto(
        producto_id=5,
        usuario_id=9,
        activo_origen=True,
        activo_destino=False,
        motivo="Retiro del catalogo",
    )
    entidad.historial_producto_id = 11
    entidad.fecha_transicion = datetime(2026, 10, 20, 9, 30, 0)

    dto = HistorialTransicionProductoRespuesta.model_validate(entidad)

    assert dto.historial_producto_id == 11
    assert dto.producto_id == 5
    assert dto.usuario_id == 9
    assert dto.activo_origen is True
    assert dto.activo_destino is False
    assert dto.motivo == "Retiro del catalogo"


def test_historial_de_categoria_se_construye_desde_la_entidad():
    entidad = HistorialTransicionCategoria(
        categoria_id=4,
        usuario_id=9,
        activo_origen=False,
        activo_destino=True,
        motivo="Reactivacion de la categoria",
    )
    entidad.historial_categoria_id = 12
    entidad.fecha_transicion = datetime(2026, 10, 20, 10, 0, 0)

    dto = HistorialTransicionCategoriaRespuesta.model_validate(entidad)

    assert dto.historial_categoria_id == 12
    assert dto.categoria_id == 4
    assert dto.activo_destino is True
    assert dto.motivo == "Reactivacion de la categoria"
