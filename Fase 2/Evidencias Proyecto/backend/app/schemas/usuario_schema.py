from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.models.control import ESTADOS_INVITACION

#: Valor publicado cuando no existe estado persistido o es desconocido (D-3).
#: Nunca se presenta un legado como `aceptada`.
ESTADO_INVITACION_NO_DISPONIBLE = "no disponible"


def proyectar_estado_invitacion(estado: str | None) -> str:
    """Proyecta el estado persistido para listados y respuestas (D-3).

    Solo los cuatro estados canonicos se publican tal cual; ausencia o valores
    desconocidos se presentan como `no disponible`.
    """
    if estado in ESTADOS_INVITACION:
        return estado
    return ESTADO_INVITACION_NO_DISPONIBLE


#: Catalogo cerrado de codigos de motivo (D-5). No es configurable.
MOTIVOS_MUTACION: tuple[str, ...] = (
    "cambio_funciones",
    "reasignacion_organizacional",
    "correccion_datos",
    "termino_vinculo",
    "seguridad_acceso",
    "otro",
)

#: Longitud maxima del texto explicativo del motivo (D-5).
LONGITUD_MAXIMA_TEXTO_MOTIVO = 500


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
    #: Proyeccion persistida del ciclo de invitacion (Feature 017, D-3). Se arma
    #: desde el mapa de control; un registro legado/sin estado se publica como
    #: `no disponible`, nunca como `aceptada`. Nunca incluye la URL.
    estado_invitacion: str = ESTADO_INVITACION_NO_DISPONIBLE


class MotivoMutacion(BaseModel):
    """Motivo obligatorio de las mutaciones del conjunto cerrado D-7 (D-5).

    El catalogo es cerrado y el texto explicativo admite hasta 500 caracteres;
    para `otro` el texto es obligatorio y no puede ser solo espacios. La
    validacion ocurre antes de cualquier mutacion (AC-10).
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str
    texto: str | None = Field(
        default=None, max_length=LONGITUD_MAXIMA_TEXTO_MOTIVO
    )

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, valor: str) -> str:
        if valor not in MOTIVOS_MUTACION:
            raise ValueError(
                "codigo de motivo invalido; use uno del catalogo cerrado"
            )
        return valor

    @model_validator(mode="after")
    def validar_texto_de_otro(self) -> "MotivoMutacion":
        if self.codigo == "otro" and not (self.texto or "").strip():
            raise ValueError("el motivo `otro` exige texto explicativo no vacio")
        return self


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


# ---------------------------------------------------------------------------
# Invitacion y motivos (Feature 017, D-1/D-4/D-5/D-10)
# ---------------------------------------------------------------------------


class UsuarioInvitacionRespuesta(UsuarioRespuesta):
    """Respuesta de alta/reenvio: URL de invitacion solo en esta respuesta (D-4).

    La URL no se persiste ni se publica en listados; el DTO la expone unicamente
    porque el alta o el reenvio acaban de recibirla de Clerk. Un alta sobre una
    identidad ya existente no genera invitacion y deja `url_invitacion=None`.
    """

    url_invitacion: str | None = None


class UsuarioEdicionConMotivo(UsuarioEdicion):
    """Edicion de usuario con motivo e idempotencia opcionales (D-5/D-7).

    El motivo es obligatorio solo cuando la edicion cambia efectivamente algun
    atributo; una edicion sin cambios es idempotente y no exige ni registra
    justificacion. `idempotencia` permite completar el motivo en un reintento sin
    repetir el cambio de negocio.
    """

    motivo: MotivoMutacion | None = None
    idempotencia: str | None = Field(default=None, min_length=1, max_length=100)


class UsuarioEstadoConMotivo(UsuarioEstado):
    """Baja/reactivacion de usuario con motivo e idempotencia (D-5/D-7).

    Una baja o reactivacion repetida sin cambio de estado no exige ni genera
    motivo; cuando el estado si cambia, el motivo del catalogo D-5 es
    obligatorio antes de mutar.
    """

    motivo: MotivoMutacion | None = None
    idempotencia: str | None = Field(default=None, min_length=1, max_length=100)
