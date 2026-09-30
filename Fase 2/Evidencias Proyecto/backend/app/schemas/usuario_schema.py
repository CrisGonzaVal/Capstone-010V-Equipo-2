from pydantic import BaseModel, ConfigDict, EmailStr


class UsuarioBase(BaseModel):
    nombre: str
    apellido: str
    correo: EmailStr
    departamento_id: int
    rol_id: int


class UsuarioCrear(UsuarioBase):
    password: str


class UsuarioRespuesta(UsuarioBase):
    model_config = ConfigDict(from_attributes=True)

    usuario_id: int
