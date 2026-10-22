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
        "Feature 008 (AC-17): incluye `institucion`, la institucion efectiva "
        "derivada en el servidor (`usuario -> departamento -> institucion`) para "
        "Administrador, Bodeguero y Solicitante; para Superadmin es `null`, "
        "porque conserva su caracter global. El campo es **informativo** "
        "(contexto de UI): no autoriza y no acepta entrada del cliente.\n\n"
        "Sin Bearer valido, con firma/emisor/vigencia incorrectos, con fallo o "
        "respuesta inadecuada del Backend API de Clerk, con correo primario no "
        "verificado, sin usuario local coincidente o con identidad/rol no "
        "resoluble responde **401**. Si el ambito institucional de un rol "
        "limitado no se resuelve, responde **403** y nunca degrada a global."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
    },
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/auth/me"))
    ],
)
def leer_identidad_autenticada(
    identidad: dependencies.IdentidadAutenticada = Depends(dependencies.get_current_user),
    db: Session = Depends(dependencies.get_db_negocio),
) -> IdentidadAutenticadaRespuesta:
    # `get_db_negocio` (no `get_db`): la identidad local de un rol limitado vive
    # en el esquema de **su** institucion (Feature 010), no en `control`. La
    # releida del usuario y de su institucion efectiva debe ocurrir en el mismo
    # tenant que resolvio el correo verificado; en control no habria fila y la
    # respuesta seria un 401 espurio. Para Superadmin la sesion sigue siendo la
    # de control. En SQLite (contexto logico unico) ambas sesiones coinciden.
    return auth_service.construir_identidad_autenticada(db, identidad)
