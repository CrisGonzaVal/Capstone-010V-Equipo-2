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
    DepartamentoCrear,
    DepartamentoEdicion,
    DepartamentoEstado,
    DepartamentoEstadoRespuesta,
    DepartamentoRespuesta,
    EncargadoCrear,
    EncargadoRespuesta,
    SedeCrear,
    SedeEdicion,
    SedeEstado,
    SedeEstadoRespuesta,
    SedeRespuesta,
)
from app.services import organizacion_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/organizacion", tags=["Organizacion"])

#: Rutas contractuales de la matriz central (plan §1, spec §4.12).
RUTA_SEDES = "/api/v1/organizacion/sedes"
RUTA_SEDE = "/api/v1/organizacion/sedes/{sede_id}"
RUTA_SEDE_ESTADO = "/api/v1/organizacion/sedes/{sede_id}/estado"
RUTA_DEPARTAMENTOS = "/api/v1/organizacion/departamentos"
RUTA_DEPARTAMENTO = "/api/v1/organizacion/departamentos/{departamento_id}"
RUTA_DEPARTAMENTO_ESTADO = (
    "/api/v1/organizacion/departamentos/{departamento_id}/estado"
)
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", RUTA_SEDES))
    ],
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", RUTA_SEDE_DEPARTAMENTO))
    ],
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", RUTA_SEDE_USUARIO))
    ],
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", RUTA_ENCARGADOS))
    ],
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", RUTA_ENCARGADOS))
    ],
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
    dependencies=[
        Depends(dependencies.requiere_capacidad("DELETE", RUTA_ENCARGADO))
    ],
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


# ---------------------------------------------------------------------------
# CRUD organizacional de sedes (Feature 012, T7, AC-6/AC-11/AC-13)
# ---------------------------------------------------------------------------


@router.post(
    "/sedes",
    response_model=SedeRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una sede de la institucion",
    description=(
        "Crea una sede en la institucion del Administrador (AC-6). El cliente solo "
        "aporta nombre y direccion; la institucion la resuelve el servidor. Una "
        "sede homonima en la institucion responde **409** sin crear fila, de modo "
        "que 'Sede Central' no se duplica. Un cuerpo invalido responde **422**."
    ),
    responses=_respuestas(conflicto=True, payload=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", RUTA_SEDES))
    ],
)
def crear_sede(
    datos: SedeCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_SEDES)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> SedeRespuesta:
    return organizacion_service.crear_sede(db, datos, identidad)


@router.put(
    "/sedes/{sede_id}",
    response_model=SedeRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar una sede de la institucion",
    description=(
        "Modifica el nombre y la direccion de una sede del tenant (AC-6). Una sede "
        "inexistente o **ajena** responde **404** sin mutacion; un cuerpo invalido, "
        "**422**."
    ),
    responses=_respuestas(payload=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", RUTA_SEDE))
    ],
)
def editar_sede(
    sede_id: int,
    datos: SedeEdicion,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_SEDE)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> SedeRespuesta:
    return organizacion_service.editar_sede(db, sede_id, datos, identidad)


@router.patch(
    "/sedes/{sede_id}/estado",
    response_model=SedeEstadoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar una sede",
    description=(
        "Persiste el estado logico `activo` de la sede (idempotente, AC-11). "
        "Desactivar no borra la fila ni su historial; reactivar es el mismo "
        "endpoint con `true`. Si la desactivacion dejaria departamentos activos o "
        "Bodegueros asignados a la sede responde **409** con el motivo concreto; "
        "una sede inexistente o ajena responde **404**."
    ),
    responses=_respuestas(conflicto=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("PATCH", RUTA_SEDE_ESTADO))
    ],
)
def cambiar_estado_sede(
    sede_id: int,
    datos: SedeEstado,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_SEDE_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> SedeEstadoRespuesta:
    sede = organizacion_service.cambiar_estado_sede(db, sede_id, datos.activo, identidad)
    return SedeEstadoRespuesta(sede_id=sede.sede_id, activo=sede.activo)


# ---------------------------------------------------------------------------
# CRUD organizacional de departamentos (Feature 012, T7, AC-7/AC-11/AC-13)
# ---------------------------------------------------------------------------


@router.get(
    "/departamentos",
    response_model=List[DepartamentoRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar los departamentos de la institucion del actor",
    description=(
        "Devuelve los departamentos de la institucion resuelta desde la sesion, "
        "con su sede asignada o su ausencia y su estado logico (AC-7). Un "
        "departamento de otro tenant no aparece en la lista."
    ),
    responses=_respuestas(),
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", RUTA_DEPARTAMENTOS))
    ],
)
def listar_departamentos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_DEPARTAMENTOS)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> List[DepartamentoRespuesta]:
    return organizacion_service.listar_departamentos(db, identidad)


@router.post(
    "/departamentos",
    response_model=DepartamentoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un departamento de la institucion",
    description=(
        "Crea un departamento en la institucion del Administrador (AC-7). La sede "
        "no es obligatoria en el alta (la precondicion de sede es operativa, regla "
        "011); se asigna despues con `PUT .../{departamento_id}/sede`. Un cuerpo "
        "invalido responde **422**."
    ),
    responses=_respuestas(payload=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", RUTA_DEPARTAMENTOS))
    ],
)
def crear_departamento(
    datos: DepartamentoCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_DEPARTAMENTOS)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> DepartamentoRespuesta:
    return organizacion_service.crear_departamento(db, datos, identidad)


@router.put(
    "/departamentos/{departamento_id}",
    response_model=DepartamentoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar un departamento de la institucion",
    description=(
        "Modifica nombre y descripcion de un departamento del tenant (AC-7). Un "
        "departamento inexistente o **ajeno** responde **404** sin mutacion; un "
        "cuerpo invalido, **422**."
    ),
    responses=_respuestas(payload=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("PUT", RUTA_DEPARTAMENTO))
    ],
)
def editar_departamento(
    departamento_id: int,
    datos: DepartamentoEdicion,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_DEPARTAMENTO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> DepartamentoRespuesta:
    return organizacion_service.editar_departamento(
        db, departamento_id, datos, identidad
    )


@router.patch(
    "/departamentos/{departamento_id}/estado",
    response_model=DepartamentoEstadoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar un departamento",
    description=(
        "Persiste el estado logico `activo` del departamento (idempotente, AC-11). "
        "Desactivar no borra la fila ni su historial; reactivar es el mismo "
        "endpoint con `true`. Si la desactivacion dejaria usuarios activos "
        "vinculados responde **409** con el motivo concreto; un departamento "
        "inexistente o ajeno, **404**."
    ),
    responses=_respuestas(conflicto=True),
    dependencies=[
        Depends(dependencies.requiere_capacidad("PATCH", RUTA_DEPARTAMENTO_ESTADO))
    ],
)
def cambiar_estado_departamento(
    departamento_id: int,
    datos: DepartamentoEstado,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_DEPARTAMENTO_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> DepartamentoEstadoRespuesta:
    departamento = organizacion_service.cambiar_estado_departamento(
        db, departamento_id, datos.activo, identidad
    )
    return DepartamentoEstadoRespuesta(
        departamento_id=departamento.departamento_id, activo=departamento.activo
    )
