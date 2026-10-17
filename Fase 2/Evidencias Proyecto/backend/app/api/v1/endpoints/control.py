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
    InstitucionAltaControlCrear,
    InstitucionAltaControlRespuesta,
)
from app.services import control_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/control", tags=["Control"])

#: Ruta contractual del alta de institucion (plan §1); clave de la matriz.
RUTA_ALTA = "/api/v1/control/instituciones/"

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
