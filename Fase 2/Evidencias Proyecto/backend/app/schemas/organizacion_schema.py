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
    """Sede de la institucion del actor (spec D-1).

    Incluye el estado logico `activo` (Feature 012, AC-6/AC-11): la UI muestra
    activo/inactivo por sede; la desactivacion no borra la fila ni su historial.
    """

    model_config = ConfigDict(from_attributes=True)

    sede_id: int
    nombre: str
    direccion: str | None = None
    institucion_id: str
    activo: bool = True


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


# ---------------------------------------------------------------------------
# CRUD organizacional de sedes (Feature 012, T7, diseno-tecnico.md §1.2)
# ---------------------------------------------------------------------------


class SedeCrear(BaseModel):
    """Alta de sede: el cliente solo aporta nombre y direccion (no institucion)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)


class SedeEdicion(BaseModel):
    """Edicion de sede: nombre y direccion; la institucion la resuelve el servidor."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)


class SedeEstado(BaseModel):
    """Entrada de la desactivacion/reactivacion logica de una sede (AC-11)."""

    model_config = ConfigDict(extra="forbid")

    activo: bool


class SedeEstadoRespuesta(BaseModel):
    """Estado persistido de una sede tras la desactivacion/reactivacion."""

    sede_id: int
    activo: bool


# ---------------------------------------------------------------------------
# CRUD organizacional de departamentos (Feature 012, T7, diseno-tecnico.md §1.2)
# ---------------------------------------------------------------------------


class DepartamentoRespuesta(BaseModel):
    """Departamento de la institucion del actor, con su sede y estado (AC-7/AC-11)."""

    model_config = ConfigDict(from_attributes=True)

    departamento_id: int
    nombre_dep: str
    descripcion: str | None = None
    institucion_id: str
    sede_id: int | None = None
    activo: bool = True


class DepartamentoCrear(BaseModel):
    """Alta de departamento: sin sede obligatoria (la sede es precondicion operativa)."""

    model_config = ConfigDict(extra="forbid")

    nombre_dep: str = Field(min_length=1, max_length=100)
    descripcion: str | None = Field(default=None, max_length=200)


class DepartamentoEdicion(BaseModel):
    """Edicion de departamento: nombre y descripcion; la institucion la pone el servidor."""

    model_config = ConfigDict(extra="forbid")

    nombre_dep: str = Field(min_length=1, max_length=100)
    descripcion: str | None = Field(default=None, max_length=200)


class DepartamentoEstado(BaseModel):
    """Entrada de la desactivacion/reactivacion logica de un departamento (AC-11)."""

    model_config = ConfigDict(extra="forbid")

    activo: bool


class DepartamentoEstadoRespuesta(BaseModel):
    """Estado persistido de un departamento tras la desactivacion/reactivacion."""

    departamento_id: int
    activo: bool
