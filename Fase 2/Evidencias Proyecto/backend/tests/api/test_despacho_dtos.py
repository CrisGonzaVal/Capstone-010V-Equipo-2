"""Feature 005 (T1): contrato de los DTO de despacho e historial.

En T1 aun no existe la ruta HTTP de despacho ni la de historial, asi que el
seam observable es el propio modelo Pydantic: se valida aqui que el payload
exige un `usuario_id` entero y que el read model del historial expone todos
los campos de `spec.md` §5.

El DTO del historial se declara como read model de consulta (sin
`from_attributes`) porque lo arma `inventario_service` a partir de un mapping
que cruza cuatro tablas (plan §3.4); eso tambien se comprueba.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.inventario_schema import MovimientoInventarioRespuesta
from app.schemas.ticket_schema import TicketDespacho

#: Campos exigidos por el contrato de `GET /inventario/movimientos` (§5).
CAMPOS_HISTORIAL = {
    "movimiento_id",
    "tipo_movimiento",
    "cantidad",
    "fecha_movimiento",
    "observacion",
    # Referencia legada (movimientos historicos) y nueva (Feature 011: por sede).
    "inventario_id",
    "stock_sede_id",
    "producto_id",
    "producto_nombre",
    # Atribucion departamental (legados) y de sede (nuevos, Feature 011).
    "departamento_id",
    "departamento_nombre",
    "sede_id",
    "sede_nombre",
    "ubicacion",
    # Feature 008 (AC-8): atribucion institucional del movimiento.
    "institucion_id",
}


def test_ticket_despacho_acepta_usuario_id_entero():
    payload = TicketDespacho.model_validate({"usuario_id": 6})
    assert payload.usuario_id == 6
    assert isinstance(payload.usuario_id, int)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"usuario_id": None},
        {"usuario_id": "no-es-entero"},
    ],
)
def test_ticket_despacho_rechaza_usuario_id_ausente_o_no_entero(payload):
    with pytest.raises(ValidationError):
        TicketDespacho.model_validate(payload)


def test_movimiento_inventario_respuesta_expone_todos_los_campos_del_contrato():
    assert set(MovimientoInventarioRespuesta.model_fields) == CAMPOS_HISTORIAL


def test_movimiento_inventario_respuesta_es_read_model_de_consulta():
    # No es una entidad ORM: el service lo arma desde un mapping de columnas.
    assert MovimientoInventarioRespuesta.model_config.get("from_attributes") is not True


def test_movimiento_inventario_respuesta_instancia_todos_los_campos():
    movimiento = MovimientoInventarioRespuesta(
        movimiento_id=1,
        tipo_movimiento="SALIDA",
        cantidad=3,
        fecha_movimiento=datetime(2026, 1, 1, 12, 0, 0),
        observacion="Despacho ticket_id=1; detalle_id=2; producto_id=5",
        inventario_id=4,
        producto_id=5,
        producto_nombre="Resma de papel",
        departamento_id=2,
        departamento_nombre="Bodega",
        ubicacion="Estante A",
    )
    assert movimiento.producto_nombre == "Resma de papel"
    assert movimiento.departamento_nombre == "Bodega"
    assert movimiento.cantidad == 3
