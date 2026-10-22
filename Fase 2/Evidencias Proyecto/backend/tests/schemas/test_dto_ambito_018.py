"""T3 (Feature 018): DTOs de la lectura de ambito — contrato exacto de campos.

Estas pruebas validan los modelos Pydantic **de forma aislada**, sin pasar por la
ruta: la Feature 018 aun no publica `GET /api/v1/inventario/ambito` (eso es T4),
asi que el contrato de campos se fija aqui para que T4 solo tenga que armar el
mapping.

Contrato (spec §7 "Campos minimos" y plan §1.1/§1.2):

  * `SedeFiltroRespuesta` -> `sede_id`, `sede_nombre`.
  * `DepartamentoFiltroRespuesta` -> `departamento_id`, `departamento_nombre`,
    `sede_id` (asociacion obligatoria que acota los departamentos a la sede
    elegida).
  * `AmbitoInventarioRespuesta` -> `sedes` y `departamentos`.

No hay campos de institucion, usuario, ticket, producto ni stock/agregados, y los
mappings agregados no declaran `from_attributes` porque los arma el servicio a
mano (plan §1.1.1).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.inventario_schema import (
    AmbitoInventarioRespuesta,
    DepartamentoFiltroRespuesta,
    SedeFiltroRespuesta,
)

CAMPOS_SEDE = {"sede_id", "sede_nombre"}
CAMPOS_DEPARTAMENTO = {"departamento_id", "departamento_nombre", "sede_id"}
CLAVES_AMBITO = {"sedes", "departamentos"}

#: Prefijos/sufijos que el contrato prohibe: ni institucion, ni identidades, ni
#: tickets, ni productos, ni saldos agregados.
PREFIJOS_PROHIBIDOS = (
    "usuario",
    "ticket",
    "producto",
    "stock",
    "sede_rol",
    "role",
    "rol",
    "institucion",
    "correo",
    "email",
    "cantidad",
    "total",
    "critico",
)


def _campos(modelo) -> set[str]:
    return set(modelo.model_fields)


# ===========================================================================
# AC-4: filas de sede y departamento
# ===========================================================================


def test_dto_sede_expone_exactamente_id_y_nombre():
    """AC-4: la fila de sede solo entrega lo que el selector necesita."""
    assert _campos(SedeFiltroRespuesta) == CAMPOS_SEDE, sorted(
        _campos(SedeFiltroRespuesta)
    )


def test_dto_departamento_expone_exactamente_id_nombre_y_sede():
    """AC-4/D-6: `sede_id` es la asociacion obligatoria, no un saldo."""
    assert _campos(DepartamentoFiltroRespuesta) == CAMPOS_DEPARTAMENTO, sorted(
        _campos(DepartamentoFiltroRespuesta)
    )


def test_dto_departamento_exige_la_sede_asociada():
    """AC-4/D-6: un departamento sin sede no es una opcion valida del ambito."""
    with pytest.raises(ValidationError):
        DepartamentoFiltroRespuesta(
            departamento_id=1, departamento_nombre="Sin Sede"
        )


def test_dto_ambito_expone_exactamente_sedes_y_departamentos():
    """AC-4: el cuerpo no lleva ninguna otra coleccion ni agregado."""
    assert _campos(AmbitoInventarioRespuesta) == CLAVES_AMBITO, sorted(
        _campos(AmbitoInventarioRespuesta)
    )


# ===========================================================================
# AC-4: serializacion del agregado armado a mano por el servicio
# ===========================================================================


def test_dto_ambito_serializa_las_filas_del_mapping_del_servicio():
    """AC-4/plan §1.1.1: el servicio arma mappings y el DTO los publica tal cual."""
    ambito = AmbitoInventarioRespuesta(
        sedes=[
            {"sede_id": 1, "sede_nombre": "Norte"},
            {"sede_id": 2, "sede_nombre": "Sur"},
        ],
        departamentos=[
            {
                "departamento_id": 10,
                "departamento_nombre": "Almacen",
                "sede_id": 1,
            }
        ],
    )

    assert ambito.model_dump() == {
        "sedes": [
            {"sede_id": 1, "sede_nombre": "Norte"},
            {"sede_id": 2, "sede_nombre": "Sur"},
        ],
        "departamentos": [
            {
                "departamento_id": 10,
                "departamento_nombre": "Almacen",
                "sede_id": 1,
            }
        ],
    }


def test_dto_ambito_admite_listas_vacias():
    """AC-4/D-5: la sede inactiva del Bodeguero deja ambas colecciones vacias."""
    ambito = AmbitoInventarioRespuesta(sedes=[], departamentos=[])

    assert ambito.model_dump() == {"sedes": [], "departamentos": []}


# ===========================================================================
# AC-8/AC-9: nada fuera del contrato pactado
# ===========================================================================


@pytest.mark.parametrize(
    "modelo", [SedeFiltroRespuesta, DepartamentoFiltroRespuesta, AmbitoInventarioRespuesta]
)
def test_dto_no_expone_campos_de_otras_entidades_ni_de_saldo(modelo):
    """AC-4/AC-8: ni usuarios, ni tickets, ni productos/stock, ni agregados."""
    for campo in _campos(modelo):
        assert not campo.startswith(PREFIJOS_PROHIBIDOS), (
            f"{modelo.__name__} expone `{campo}`, fuera del contrato pactado"
        )


@pytest.mark.parametrize(
    "modelo", [SedeFiltroRespuesta, DepartamentoFiltroRespuesta, AmbitoInventarioRespuesta]
)
def test_dto_no_declara_from_attributes(modelo):
    """plan §1.1.1: los mappings agregados los arma el servicio, no el ORM."""
    assert modelo.model_config.get("from_attributes") is not True, (
        f"{modelo.__name__} no debe declarar from_attributes"
    )


def test_dto_ambito_ignora_campos_extra_del_mapping():
    """Contrato aditivo: un mapping con columnas de mas no rompe la respuesta.

    La politica es la predeterminada de Pydantic v2 (`extra="ignore"`): el DTO
    publica exclusivamente los campos pactados, aunque el servicio proyecte alguna
    columna adicional al armar el mapping.
    """
    ambito = AmbitoInventarioRespuesta.model_validate(
        {
            "sedes": [
                {"sede_id": 1, "sede_nombre": "Norte", "activo": True}
            ],
            "departamentos": [
                {
                    "departamento_id": 10,
                    "departamento_nombre": "Almacen",
                    "sede_id": 1,
                    "descripcion": "no se publica",
                }
            ],
        }
    )

    assert ambito.model_dump() == {
        "sedes": [{"sede_id": 1, "sede_nombre": "Norte"}],
        "departamentos": [
            {"departamento_id": 10, "departamento_nombre": "Almacen", "sede_id": 1}
        ],
    }
