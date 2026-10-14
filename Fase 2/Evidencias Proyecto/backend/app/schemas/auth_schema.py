"""DTOs de identidad autenticada (Feature 006)."""

from pydantic import BaseModel


class IdentidadAutenticadaRespuesta(BaseModel):
    """Identidad resuelta del usuario local vinculado por Clerk (AC-8).

    `usuario_id`, `nombre`, `apellido`, `correo` y `rol` proceden del registro
    local resuelto por el correo primario verificado; `rol` es el valor legible
    de `rol.nombre_rol`. El `sub` es el identificador validado de Clerk y no se
    persiste en la base local. El contrato no expone `rol_id`.
    """

    usuario_id: int
    sub: str
    nombre: str
    apellido: str
    correo: str
    rol: str
