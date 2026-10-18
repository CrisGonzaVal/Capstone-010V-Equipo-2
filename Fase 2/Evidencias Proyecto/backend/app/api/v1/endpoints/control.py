"""Endpoint del alta de institucion en el portal de control (Feature 010, T7).

Router delgado: autoriza por la matriz central (solo Superadmin) e inyecta la
costura de verificacion Clerk, la sesion de control (`Depends(get_db)`) y delega
toda la logica de aprovisionamiento en `app.services.control_service`. No
contiene consultas ni reglas de negocio (AGENTS §6).

El esquema, la version, el rol y el estado los deriva el **servidor**; el cliente
solo envia el DTO de entrada (D-7, AC-7…AC-9).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.control_schema import (
    CapacidadActualizar,
    CapacidadFuncional,
    CapacidadRespuesta,
    DashboardSaaSRespuesta,
    InstitucionAltaControlCrear,
    InstitucionAltaControlRespuesta,
    InstitucionControlRespuesta,
    InstitucionEdicion,
    InstitucionEstado,
    InstitucionEstadoRespuesta,
)
from app.services import control_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/control", tags=["Control"])

#: Ruta contractual del alta de institucion (plan §1); clave de la matriz.
RUTA_ALTA = "/api/v1/control/instituciones/"

#: Rutas contractuales de la gestion administrativa de control (diseno §1).
RUTA_LISTA = "/api/v1/control/instituciones/"
RUTA_DETALLE = "/api/v1/control/instituciones/{institucion_id}"
RUTA_ESTADO = "/api/v1/control/instituciones/{institucion_id}/estado"
RUTA_DASHBOARD = "/api/v1/control/dashboard"
RUTA_CAPACIDADES = "/api/v1/control/instituciones/{institucion_id}/capacidades"
RUTA_CAPACIDAD = (
    "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}"
)

#: Respuestas de error del alta ademas de las de autorizacion (401/403).
_RESPUESTAS_ALTA = {
    **dependencies.respuestas_de_autorizacion(),
    status.HTTP_409_CONFLICT: {
        "description": (
            "Institucion, correo o nombre de esquema ya registrado, o fallo de "
            "una etapa del alta: no se aplica ningun cambio parcial."
        )
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": (
            "El correo del Administrador no existe en Clerk o el cuerpo es "
            "invalido (el cliente no aporta esquema, version, rol ni estado)."
        )
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": (
            "No fue posible verificar el correo contra Clerk: la frontera externa "
            "esta indisponible y no se crea ningun recurso."
        )
    },
}


@router.post(
    "/instituciones/",
    response_model=InstitucionAltaControlRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Aprovisionar una institucion y su primer Administrador",
    description=(
        "Da de alta una institucion y su primer Administrador (D-7). Solo lo "
        "autoriza **Superadmin** mediante la matriz central (AC-7…AC-9). El "
        "correo del Administrador debe existir previamente en Clerk; si no "
        "existe responde **422** y si Clerk no puede verificar responde **503**, "
        "sin dejar tenant operativo.\n\n"
        "En exito (**201**) el servidor deriva el nombre de esquema "
        "determinista y crea en control la institucion, el mapa "
        "`correo -> esquema`, el usuario Administrador inicial y la version "
        "objetivo. El cliente **no** envia nombre de esquema, version, rol ni "
        "estado. Un duplicado o colision responde **409** sin mutar el estado, y "
        "un fallo de cualquier etapa compensa (rollback): ningun tenant queda "
        "parcial y un reintento no duplica ni sobrescribe datos previos."
    ),
    responses=_RESPUESTAS_ALTA,
)
def alta_institucion(
    datos: InstitucionAltaControlCrear,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", RUTA_ALTA)
    ),
    verificar_correo: Callable[[str], bool] = Depends(
        dependencies.obtener_verificador_correo_clerk
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionAltaControlRespuesta:
    try:
        return control_service.aprovisionar_institucion(db, datos, verificar_correo)
    except control_service.ErrorCorreoInexistente as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except control_service.ErrorConflictoAprovisionamiento as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except control_service.ErrorClerkNoDisponible as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Gestion administrativa de instituciones (Feature 012, T6)
# ---------------------------------------------------------------------------


def _respuestas_admin(
    *, oculto: bool = False, conflicto: bool = False, payload: bool = False
) -> dict[int, dict[str, str]]:
    """Respuestas documentadas: autorizacion + 404/409/422 segun la operacion."""
    respuestas = dict(dependencies.respuestas_de_autorizacion())
    if oculto:
        respuestas.update(dependencies.respuesta_recurso_oculto())
    if conflicto:
        respuestas.update(dependencies.respuesta_conflicto())
    if payload:
        respuestas[status.HTTP_422_UNPROCESSABLE_CONTENT] = {
            "description": (
                "Cuerpo o funcion invalidos (el cliente no aporta esquema, "
                "version ni estado); no se aplica ningun cambio."
            )
        }
    return respuestas


@router.get(
    "/instituciones/",
    response_model=list[InstitucionControlRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar las instituciones registradas",
    description=(
        "Devuelve el registro institucional canonico de control con su estado "
        "(`activo`) y el `nombre_esquema` derivado. Solo **Superadmin** (AC-1)."
    ),
    responses=_respuestas_admin(),
)
def listar_instituciones(
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_LISTA)
    ),
    db: Session = Depends(dependencies.get_db),
) -> list[InstitucionControlRespuesta]:
    return control_service.listar_instituciones(db)


@router.get(
    "/instituciones/{institucion_id}",
    response_model=InstitucionControlRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar una institucion registrada",
    description=(
        "Devuelve una institucion canonica de control por id. Una institucion "
        "inexistente responde **404**. Solo **Superadmin** (AC-1)."
    ),
    responses=_respuestas_admin(oculto=True),
)
def obtener_institucion(
    institucion_id: str,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_DETALLE)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionControlRespuesta:
    try:
        return control_service.obtener_institucion(db, institucion_id)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put(
    "/instituciones/{institucion_id}",
    response_model=InstitucionControlRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Modificar una institucion registrada",
    description=(
        "Modifica los atributos canonicos (`nombre`, `rut`, `direccion`) en el "
        "registro fuente de verdad de control y sincroniza con el espejo tenant "
        "**solo** `institucion_id` + `nombre` (D-1/AC-1). El cliente no aporta "
        "estado, esquema ni version. Una institucion inexistente responde **404** "
        "y un cuerpo invalido **422**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def editar_institucion(
    institucion_id: str,
    datos: InstitucionEdicion,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_DETALLE)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionControlRespuesta:
    try:
        return control_service.editar_institucion(db, institucion_id, datos)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch(
    "/instituciones/{institucion_id}/estado",
    response_model=InstitucionEstadoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Activar o desactivar una institucion",
    description=(
        "Persiste el estado de ciclo de vida `control.institucion.activo` de "
        "forma logica y reversible: desactivar no borra la fila, el tenant, los "
        "datos ni el historial; reactivar es el mismo endpoint con `true` "
        "(D-2/AC-2). Una institucion inexistente responde **404** y un cuerpo "
        "invalido **422**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def cambiar_estado_institucion(
    institucion_id: str,
    datos: InstitucionEstado,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PATCH", RUTA_ESTADO)
    ),
    db: Session = Depends(dependencies.get_db),
) -> InstitucionEstadoRespuesta:
    try:
        return control_service.cambiar_estado_institucion(
            db, institucion_id, datos.activo
        )
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/dashboard",
    response_model=DashboardSaaSRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar el dashboard SaaS del Superadmin",
    description=(
        "Panorama global con atribucion por institucion: conteo de activas, "
        "sedes y usuarios por rol por institucion activa (D-5/AC-4). Las "
        "instituciones desactivadas se listan identificadas y sin metricas. Una "
        "institucion activa inaccesible o incompatible falla el agregado "
        "completo (409), nunca parcial; solo **Superadmin**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_conflicto(),
    },
)
def consultar_dashboard(
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_DASHBOARD)
    ),
    db: Session = Depends(dependencies.get_db),
) -> DashboardSaaSRespuesta:
    try:
        return control_service.dashboard_saas(db)
    except control_service.ErrorDashboardSaaS as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/instituciones/{institucion_id}/capacidades",
    response_model=list[CapacidadRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Consultar las capacidades funcionales de una institucion",
    description=(
        "Devuelve las seis capacidades del conjunto cerrado con su estado "
        "persistido en control (D-6/AC-5). Una institucion inexistente responde "
        "**404**; solo **Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True),
)
def listar_capacidades(
    institucion_id: str,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", RUTA_CAPACIDADES)
    ),
    db: Session = Depends(dependencies.get_db),
) -> list[CapacidadRespuesta]:
    try:
        return control_service.listar_capacidades(db, institucion_id)
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put(
    "/instituciones/{institucion_id}/capacidades/{funcion}",
    response_model=CapacidadRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Habilitar o deshabilitar una capacidad funcional",
    description=(
        "Persiste el estado (`habilitada`) de una de las seis capacidades de la "
        "institucion (D-6/AC-5). Una funcion fuera del conjunto cerrado responde "
        "**422** y una institucion inexistente **404**, sin mutacion; solo "
        "**Superadmin**."
    ),
    responses=_respuestas_admin(oculto=True, payload=True),
)
def actualizar_capacidad(
    institucion_id: str,
    funcion: CapacidadFuncional,
    datos: CapacidadActualizar,
    _identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("PUT", RUTA_CAPACIDAD)
    ),
    db: Session = Depends(dependencies.get_db),
) -> CapacidadRespuesta:
    try:
        return control_service.actualizar_capacidad(
            db, institucion_id, funcion.value, datos.habilitada
        )
    except control_service.ErrorInstitucionNoEncontrada as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except control_service.ErrorFuncionInvalida as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
