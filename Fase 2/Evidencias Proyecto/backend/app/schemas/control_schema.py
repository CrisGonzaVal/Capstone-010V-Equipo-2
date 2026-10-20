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

from enum import Enum

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
    #: URL de la invitacion del primer Administrador, solo en la respuesta del
    #: alta cuando hubo que invitar (Feature 017, D-1/D-4). Nunca se persiste.
    url_invitacion: str | None = None


# ---------------------------------------------------------------------------
# Gestion administrativa de instituciones (Feature 012, T6)
# ---------------------------------------------------------------------------


class InstitucionControlRespuesta(BaseModel):
    """Lectura administrativa del registro institucional canonico (control).

    Publica el estado de ciclo de vida persistido (`activo`) y `nombre_esquema`
    derivado en servidor (informativo). El resto de atributos canonicos
    (`rut`, `direccion`) permanece solo en control (D-1).
    """

    institucion_id: str
    nombre: str
    rut: str | None = None
    direccion: str | None = None
    activo: bool
    nombre_esquema: str | None = None


class InstitucionEdicion(BaseModel):
    """Entrada de la modificacion del registro canonico (plan §1, D-1).

    Solo admite los atributos canonicos (`nombre`, `rut`, `direccion`). Nunca
    recibe `activo`, esquema ni version: el cliente no aporta esos valores
    (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=150)
    rut: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=200)


class InstitucionEstado(BaseModel):
    """Entrada de la activacion/desactivacion logica (D-2, plan §1)."""

    model_config = ConfigDict(extra="forbid")

    activo: bool


class InstitucionEstadoRespuesta(BaseModel):
    """Resultado del cambio de estado institucional: el estado persistido."""

    institucion_id: str
    activo: bool


class CapacidadFuncional(str, Enum):
    """Los seis identificadores cerrados de capacidad funcional (D-6/AC-5).

    Se usa como tipo del parametro de path `{funcion}` para que una funcion
    fuera del conjunto cerrado produzca **422** de validacion (plan §1).
    """

    CATALOGO = "catalogo"
    INVENTARIO = "inventario"
    TICKETS = "tickets"
    KANBAN = "kanban"
    DASHBOARD = "dashboard"
    GESTION_ORGANIZACIONAL = "gestion_organizacional"


class CapacidadRespuesta(BaseModel):
    """Estado persistido de una capacidad funcional de una institucion (AC-5)."""

    funcion: str
    habilitada: bool


class CapacidadActualizar(BaseModel):
    """Entrada del cambio de una capacidad funcional (`extra="forbid"`)."""

    model_config = ConfigDict(extra="forbid")

    habilitada: bool


#: Clases de la taxonomia unica de tenant (Feature 017, D-8). Toda institucion
#: cae exactamente en una: la UI y la API no inventan estados intermedios.
CLASE_OPERATIVO = "operativo"
CLASE_NO_ENRUTABLE = "no enrutable"
CLASE_NO_DISPONIBLE = "no disponible"

#: Detalles tecnicos acotados que acompanan la clase (nunca datos personales ni
#: de negocio). `None` en la clase operativa.
DETALLE_INSTITUCION_INACTIVA = "institucion_inactiva"
DETALLE_TENANT_NO_RESOLUBLE = "tenant_no_resoluble"
DETALLE_TENANT_NO_DISPONIBLE = "tenant_no_disponible"
DETALLE_VERSION_AUSENTE = "version_ausente_o_ilegible"
DETALLE_VERSION_INCOMPATIBLE = "version_incompatible"


class InstitucionMetricasRespuesta(BaseModel):
    """Metrica tecnica de una institucion en el dashboard SaaS (D-8/AC-13/AC-14).

    `estado_tecnico` es la clase unica (`operativo`, `no enrutable`,
    `no disponible`). Los conteos del tenant solo se publican en la clase
    operativa; en las otras dos quedan en `None` (**nunca** en cero).
    `usuarios_por_rol` incluye solo roles no privilegiados con asociacion local
    activa; los Administradores tienen sus dos metricas separadas. No expone
    datos personales, de tickets, catalogo, stock ni motivos.
    """

    institucion_id: str
    nombre: str
    activo: bool
    estado_tecnico: str
    detalle_tecnico: str | None = None
    version_objetivo: str
    version_persistida: str | None = None
    sedes: int | None = None
    departamentos: int | None = None
    administradores_activos: int | None = None
    administradores_inactivos: int | None = None
    usuarios_por_rol: dict[str, int] | None = None


class DashboardSaaSRespuesta(BaseModel):
    """Panorama tecnico global del Superadmin (D-8/AC-13).

    `conteos_conocidos` y `conteos_no_disponibles` cuentan instituciones, de modo
    que su suma es `total_instituciones`. Los totales por rol y de
    Administradores agregan **solo** tenants operativos; no duplican el detalle
    por institucion. `total_instituciones_activas` conserva el contrato previo de
    la Feature 012 como dato informativo del ciclo de vida.
    """

    total_instituciones: int
    total_instituciones_activas: int
    total_administradores_activos: int
    total_administradores_inactivos: int
    usuarios_por_rol: dict[str, int]
    conteos_conocidos: int
    conteos_no_disponibles: int
    instituciones: list[InstitucionMetricasRespuesta]


# ---------------------------------------------------------------------------
# Gobierno de Administradores por institucion (Feature 017, D-10/AC-5)
# ---------------------------------------------------------------------------


class AdministradorListadoControlRespuesta(BaseModel):
    """Listado minimo de Administradores de una institucion (Feature 017, AC-5).

    Expone exactamente los cinco campos acordados por la spec, con
    `estado_invitacion` ya proyectado por el servidor (`no disponible` para un
    registro legado o desconocido). **No** contiene URL ni consulta Clerk.
    """

    usuario_id: int
    nombre: str
    apellido: str
    correo: str
    activo: bool
    estado_invitacion: str

