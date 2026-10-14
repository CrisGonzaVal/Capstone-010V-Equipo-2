"""DTOs de identidad autenticada (Features 006 y 008)."""

from pydantic import BaseModel


class InstitucionEfectivaRespuesta(BaseModel):
    """Institucion efectiva del usuario autenticado (Feature 008, AC-17).

    Identificada por `institucion_id` (misma clave que la entidad `Institucion` y
    que expone `/usuarios/instituciones`) y su `nombre` legible. Es un subconjunto
    de coherencia de esa respuesta, no una entidad completa: el campo es
    **informativo** (contexto de UI) y nunca autoriza.
    """

    institucion_id: str
    nombre: str


class IdentidadAutenticadaRespuesta(BaseModel):
    """Identidad resuelta del usuario local vinculado por Clerk (AC-8).

    `usuario_id`, `nombre`, `apellido`, `correo` y `rol` proceden del registro
    local resuelto por el correo primario verificado; `rol` es el valor legible
    de `rol.nombre_rol`. El `sub` es el identificador validado de Clerk y no se
    persiste en la base local. El contrato no expone `rol_id`.

    `institucion` (Feature 008, AC-17) es la institucion efectiva derivada en el
    servidor para Administrador, Bodeguero y Solicitante; es `null` para
    Superadmin, que conserva su caracter global. El campo es **informativo**:
    informa contexto de UI, no sustituye la autorizacion del servidor y no acepta
    entrada del cliente.
    """

    usuario_id: int
    sub: str
    nombre: str
    apellido: str
    correo: str
    rol: str
    institucion: InstitucionEfectivaRespuesta | None
