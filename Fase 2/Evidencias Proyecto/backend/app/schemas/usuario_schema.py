from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioBase(BaseModel):
    nombre: str
    apellido: str
    correo: EmailStr
    departamento_id: int
    rol_id: int


class UsuarioCrear(UsuarioBase):
    """Alta de usuario: Clerk es la unica autoridad; sin credencial local (D-7)."""


class UsuarioRespuesta(UsuarioBase):
    model_config = ConfigDict(from_attributes=True)

    usuario_id: int
    #: Sede asignada al Bodeguero (Feature 011/012); `None` cuando no tiene sede.
    #: El listado la publica siempre (asignacion vigente o su ausencia).
    sede_id: int | None = None
    #: Estado local del vinculo usuario-esquema (`mapa_usuario_esquema.activo`,
    #: Feature 012 D-3). El listado lo publica siempre; el alta/edicion pueden
    #: dejarlo en `None` cuando la operacion no consulta el mapa de control.
    activo: bool | None = None


# ---------------------------------------------------------------------------
# Edicion y estado logico de usuario local (Feature 012, T7)
# ---------------------------------------------------------------------------


class UsuarioEdicion(BaseModel):
    """Edicion de usuario local (D-3): atributos de rol y ambito, nunca el correo.

    El correo es la clave de identidad local (no se edita aqui: cambiarlo seria
    alterar la vinculacion con Clerk). La institucion la resuelve el servidor.
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=100)
    apellido: str = Field(min_length=1, max_length=100)
    departamento_id: int = Field(ge=1)
    rol_id: int = Field(ge=1)


class UsuarioEstado(BaseModel):
    """Entrada de la activacion/desactivacion local de un usuario (AC-8/AC-11).

    El estado se persiste en `mapa_usuario_esquema.activo` (D-3): desactivar
    impide que el correo resuelva al tenant, sin borrar la identidad de Clerk.
    """

    model_config = ConfigDict(extra="forbid")

    activo: bool


class UsuarioEstadoRespuesta(BaseModel):
    """Estado local persistido de la vinculacion usuario/correo."""

    usuario_id: int
    activo: bool
