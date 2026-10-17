"""DTOs del aprovisionamiento de instituciones (Feature 010, T7).

Contrato del alta minima de una institucion y su primer Administrador
(`POST /api/v1/control/instituciones/`, plan §1, D-7). El **cliente nunca**
aporta el nombre de esquema, la version, el rol ni el estado: el servidor los
deriva y valida (D-7, AC-7…AC-9). Por eso `InstitucionAltaControlCrear` los
prohibe explicitamente (`extra="forbid"`) ademas de no declararlos.

Pydantic v2 con `ConfigDict` (nunca `class Config`). Los read models de salida
no usan `from_attributes`: los arma el servicio a mano.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Estados del tenant en la respuesta del alta. Un alta solo termina `operativa`
#: cuando dejo estructura, espejo, catalogos, usuario, mapa y version objetivo.
ESTADO_OPERATIVA = "operativa"


class InstitucionAltaControlCrear(BaseModel):
    """Entrada del alta de institucion (plan §1).

    Campos obligatorios: identificador canonico, nombre de la institucion y los
    datos del primer Administrador (correo verificado en Clerk, nombre, apellido
    y nombre del departamento administrativo). `rut` y `direccion` son
    opcionales. No se recibe nombre de esquema, version, rol ni estado.
    """

    model_config = ConfigDict(extra="forbid")

    institucion_id: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=150)
    rut: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=200)
    correo_administrador: str = Field(min_length=3, max_length=150)
    nombre_administrador: str = Field(min_length=1, max_length=100)
    apellido_administrador: str = Field(min_length=1, max_length=100)
    departamento_nombre_administrativo: str = Field(min_length=1, max_length=100)


class InstitucionAltaControlRespuesta(BaseModel):
    """Respuesta del alta (plan §1): el tenant quedo registrado y operativo.

    `nombre_esquema` es el nombre determinista derivado en servidor y
    `version_esquema` la version objetivo con la que quedo marcado el tenant.
    """

    institucion_id: str
    nombre: str
    correo_administrador: str
    nombre_esquema: str
    version_esquema: str
    estado: str
    mensaje: str
