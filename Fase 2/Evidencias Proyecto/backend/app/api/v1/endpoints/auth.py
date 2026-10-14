"""Endpoint de identidad autenticada (Feature 006).

Router delgado: consume la dependencia de identidad, delega el enriquecimiento
de perfil/rol en `app.services.auth_service` y devuelve el DTO. No contiene
consultas ni logica de negocio.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.auth_schema import IdentidadAutenticadaRespuesta
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Autenticacion"])


@router.get(
    "/me",
    response_model=IdentidadAutenticadaRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar la identidad autenticada",
    description=(
        "Devuelve la identidad ya resuelta a partir del Bearer de sesion de "
        "Clerk: `usuario_id`, `nombre`, `apellido`, `correo` y `rol` del "
        "registro local vinculado por el correo primario verificado, mas el "
        "`sub` validado de Clerk. El `sub` no se persiste en la base local y el "
        "contrato no expone `rol_id`.\n\n"
        "Sin Bearer valido, con firma/emisor/vigencia incorrectos, con fallo o "
        "respuesta inadecuada del Backend API de Clerk, con correo primario no "
        "verificado, sin usuario local coincidente o con identidad/rol no "
        "resoluble responde **401**."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Credenciales ausentes o invalidas, o identidad no resoluble."
        }
    },
)
def leer_identidad_autenticada(
    identidad: dependencies.IdentidadAutenticada = Depends(dependencies.get_current_user),
    db: Session = Depends(dependencies.get_db),
) -> IdentidadAutenticadaRespuesta:
    return auth_service.construir_identidad_autenticada(db, identidad)
