"""Endpoints de asignaciones organizacionales (Feature 011, T7).

Router delgado: la autorizacion viene de la matriz central via
`dependencies.requiere_operacion` (solo Administrador institucional) y la sesion
de negocio se resuelve con `get_db_negocio` (tenant de Feature 010). Toda la
logica de dominio vive en `app.services.organizacion_service` (AGENTS §6).

Superficie minima de la spec/plan, sin CRUD de sedes (Feature 012):

  * `GET    /api/v1/organizacion/sedes`
  * `PUT    /api/v1/organizacion/departamentos/{departamento_id}/sede`
  * `PUT    /api/v1/organizacion/usuarios/{usuario_id}/sede`
  * `GET    /api/v1/organizacion/departamentos/{departamento_id}/encargados`
  * `POST   /api/v1/organizacion/departamentos/{departamento_id}/encargados`
  * `DELETE /api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}`
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.organizacion_schema import (
    AsignacionSedeCrear,
    AsignacionSedeDepartamentoRespuesta,
    AsignacionSedeUsuarioRespuesta,
    EncargadoCrear,
    EncargadoRespuesta,
    SedeRespuesta,
)
from app.services import organizacion_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/organizacion", tags=["Organizacion"])

#: Rutas contractuales de la matriz central (plan §1, spec §4.12).
RUTA_SEDES = "/api/v1/organizacion/sedes"
RUTA_SEDE_DEPARTAMENTO = "/api/v1/organizacion/departamentos/{departamento_id}/sede"
RUTA_SEDE_USUARIO = "/api/v1/organizacion/usuarios/{usuario_id}/sede"
RUTA_ENCARGADOS = "/api/v1/organizacion/departamentos/{departamento_id}/encargados"
RUTA_ENCARGADO = (
    "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}"
)


def _respuestas(*, conflicto: bool = False, payload: bool = False) -> dict:
    """Respuestas documentadas: autorizacion + 404 y, si aplica, 409/422."""
    respuestas = {
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    }
    if conflicto:
        respuestas.update(dependencies.respuesta_conflicto())
    if payload:
        respuestas[status.HTTP_422_UNPROCESSABLE_CONTENT] = {
            "description": (
                "Cuerpo invalido o con campos no permitidos; no se aplica ningun "
                "cambio."
            )
        }
    return respuestas


def _encargado_respuesta(usuario) -> EncargadoRespuesta:
    """Read model de un encargado a partir del `Usuario` resuelto por el servicio."""
    return EncargadoRespuesta(
        usuario_id=usuario.usuario_id,
        departamento_id=usuario.departamento_id,
        nombre=usuario.nombre,
        apellido=usuario.apellido,
        correo=usuario.correo,
    )


@router.get(
    "/sedes",
    response_model=List[SedeRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar las sedes de la institucion del actor",
    description=(
        "Devuelve las sedes de la institucion resuelta desde la sesion (nunca "
        "desde la peticion). Una sede de otro tenant no aparece en la lista "
        "(AC-1/AC-8). Las sedes se administran en la Feature 012: aqui solo se "
        "consultan."
    ),
    responses=_respuestas(),
)
def listar_sedes(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_SEDES)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> List[SedeRespuesta]:
    return organizacion_service.listar_sedes(db, identidad)


@router.put(
    "/departamentos/{departamento_id}/sede",
    response_model=AsignacionSedeDepartamentoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Asignar la sede de un departamento",
    description=(
        "Fija `departamento.sede_id` dentro de la institucion del Administrador "
        "institucional (spec D-5). Un departamento (o una sede) inexistente o de "
        "otro tenant responde **404** sin mutacion (AC-3); un payload invalido "
        "responde **422**. La sede es la unica bodega de la que se despachan los "
        "tickets del departamento."
    ),
    responses=_respuestas(payload=True),
)
def asignar_sede_a_departamento(
    departamento_id: int,
    datos: AsignacionSedeCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_SEDE_DEPARTAMENTO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> AsignacionSedeDepartamentoRespuesta:
    departamento = organizacion_service.asignar_sede_a_departamento(
        db, departamento_id, datos.sede_id, identidad
    )
    return AsignacionSedeDepartamentoRespuesta(
        departamento_id=departamento.departamento_id, sede_id=departamento.sede_id
    )


@router.put(
    "/usuarios/{usuario_id}/sede",
    response_model=AsignacionSedeUsuarioRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Asignar la sede de un Bodeguero",
    description=(
        "Fija `usuario.sede_id` para un Bodeguero de la institucion (spec "
        "D-5/D-7). Un usuario o una sede inexistente/ajena responde **404** "
        "(ocultacion, AC-7); un usuario cuyo rol no es Bodeguero responde "
        "**409** sin mutacion. El Bodeguero solo opera la sede asignada."
    ),
    responses=_respuestas(conflicto=True, payload=True),
)
def asignar_sede_a_usuario(
    usuario_id: int,
    datos: AsignacionSedeCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_SEDE_USUARIO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> AsignacionSedeUsuarioRespuesta:
    usuario = organizacion_service.asignar_sede_a_usuario(
        db, usuario_id, datos.sede_id, identidad
    )
    return AsignacionSedeUsuarioRespuesta(
        usuario_id=usuario.usuario_id, sede_id=usuario.sede_id
    )


@router.get(
    "/departamentos/{departamento_id}/encargados",
    response_model=List[EncargadoRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar los encargados de un departamento",
    description=(
        "Devuelve solo asociaciones **vigentes y compatibles** (usuario "
        "existente, rol Solicitante y pertenencia al departamento); una "
        "asociacion obsoleta no se muestra ni concede capacidad (spec D-4). Un "
        "departamento inexistente o ajeno responde **404** (AC-1/AC-5)."
    ),
    responses=_respuestas(),
)
def listar_encargados(
    departamento_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_ENCARGADOS)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> List[EncargadoRespuesta]:
    return [
        _encargado_respuesta(usuario)
        for usuario in organizacion_service.listar_encargados(
            db, departamento_id, identidad
        )
    ]


@router.post(
    "/departamentos/{departamento_id}/encargados",
    response_model=EncargadoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Asociar un encargado a un departamento",
    description=(
        "Asocia un usuario **Solicitante del mismo departamento** como encargado "
        "(spec D-4, AC-4). Un departamento o usuario inexistente/ajeno responde "
        "**404**; un rol distinto de Solicitante, un usuario de otro "
        "departamento o una asociacion duplicada responde **409** sin mutacion. "
        "Ser encargado no cambia el rol ni amplia permisos."
    ),
    responses=_respuestas(conflicto=True, payload=True),
)
def asociar_encargado(
    departamento_id: int,
    datos: EncargadoCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_ENCARGADOS)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> EncargadoRespuesta:
    usuario = organizacion_service.asociar_encargado(
        db, departamento_id, datos.usuario_id, identidad
    )
    return _encargado_respuesta(usuario)


@router.delete(
    "/departamentos/{departamento_id}/encargados/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirar un encargado de un departamento",
    description=(
        "Retira solo la pareja departamento/usuario indicada; las demas "
        "asociaciones no se tocan (AC-5). Una asociacion inexistente o un "
        "departamento ajeno responde **404** sin efecto."
    ),
    responses=_respuestas(),
)
def retirar_encargado(
    departamento_id: int,
    usuario_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("DELETE", RUTA_ENCARGADO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> None:
    organizacion_service.retirar_encargado(
        db, departamento_id, usuario_id, identidad
    )
