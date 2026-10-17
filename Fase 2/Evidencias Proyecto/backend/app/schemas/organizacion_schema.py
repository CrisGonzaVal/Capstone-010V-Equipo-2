"""DTOs de la gestion organizacional minima (Feature 011, T7).

Contrato de la superficie de API de asignaciones (plan §1 "Servicios, API y
autorizacion"):

  * `SedeRespuesta` — sede visible dentro del tenant resuelto.
  * `AsignacionSedeDepartamentoRespuesta` / `AsignacionSedeUsuarioRespuesta` —
    resultado de fijar la sede de un departamento o de un Bodeguero.
  * `EncargadoCrear` — alta de la asociacion departamento/encargado; el cliente
    solo aporta `usuario_id` (el departamento viene en la ruta y la institucion
    la resuelve el servidor). `extra="forbid"` impide colar campos de ambito.
  * `EncargadoRespuesta` — fila del listado de encargados compatibles vigentes.

Pydantic v2 con `ConfigDict` (nunca `class Config`). Los read models se arman a
mano desde el servicio, salvo los que se construyen desde el ORM.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SedeRespuesta(BaseModel):
    """Sede de la institucion del actor (spec D-1)."""

    model_config = ConfigDict(from_attributes=True)

    sede_id: int
    nombre: str
    direccion: str | None = None
    institucion_id: str


class AsignacionSedeCrear(BaseModel):
    """Entrada de asignacion de sede: solo el id de la sede del tenant.

    El departamento o el usuario vienen en la ruta y la institucion la resuelve
    el servidor. `extra="forbid"` impide colar `institucion_id` o cualquier otro
    campo de ambito desde el cliente (spec §4.1).
    """

    model_config = ConfigDict(extra="forbid")

    sede_id: int = Field(ge=1)


class AsignacionSedeDepartamentoRespuesta(BaseModel):
    """Sede fijada para un departamento (spec D-5)."""

    departamento_id: int
    sede_id: int


class AsignacionSedeUsuarioRespuesta(BaseModel):
    """Sede fijada para un Bodeguero (spec D-5/D-7)."""

    usuario_id: int
    sede_id: int


class EncargadoCrear(BaseModel):
    """Alta de encargado: solo el usuario; el departamento va en la ruta."""

    model_config = ConfigDict(extra="forbid")

    usuario_id: int = Field(ge=1)


class EncargadoRespuesta(BaseModel):
    """Encargado vigente y compatible de un departamento (spec D-4)."""

    usuario_id: int
    departamento_id: int
    nombre: str
    apellido: str
    correo: str
