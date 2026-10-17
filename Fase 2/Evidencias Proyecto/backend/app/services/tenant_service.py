"""Resolucion del tenant por correo primario verificado (Feature 010, T5).

Este modulo implementa la **resolucion previa a la sesion de negocio**. El
esquema efectivo de una peticion de negocio es funcion **exclusiva** del correo
primario verificado que Clerk entrego al backend y que control tradujo a un
esquema: ninguna entrada del cliente (parametro, cuerpo, cabecera o claim no
confiable) ni el reuso de una conexion del pool participan de la resolucion.

Piezas publicas:

* `nombre_esquema_para_institucion`: nombre determinista del esquema tenant a
  partir del ID canonico de institucion (plan §"Nombre determinista").
* `resolver_tenant_por_correo`: traduce el correo a `(institucion_id,
  nombre_esquema)` exigiendo una fila **activa** en el mapa de control y la
  version objetivo del tenant.
* `resolver_contexto_solicitud`: arma el contexto inmutable de solicitud; la
  identidad global (Superadmin) se resuelve en control **sin** tenant operativo.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.models.control import MapaUsuarioEsquema
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.services import control_service

#: Prefijo reservado de todos los esquemas tenant (plan §"Nombre determinista").
PREFIJO_TENANT = "tenant_"

#: Limite de identificadores de PostgreSQL (63 bytes). El nombre generado nunca
#: lo alcanza, de modo que no hay truncado silencioso del sufijo del hash.
LONGITUD_MAXIMA_ESQUEMA = 63

#: Longitud del sufijo hexadecimal estable derivado del SHA-256 del ID.
LONGITUD_SUFIJO = 8


class ErrorTenant(Exception):
    """Fallo de resolucion de tenant: la solicitud se deniega en cerrado.

    Un correo no mapeado, una asociacion inactiva o un tenant sin la version
    objetivo levantan esta excepcion; la capa HTTP la normaliza a su respuesta
    de denegacion. Nunca hay caida a otro tenant ni a un esquema predeterminado.
    """


@dataclass(frozen=True)
class ResolucionTenant:
    """Esquema tenant resuelto para un correo: resultado inmutable de control."""

    correo: str
    institucion_id: str
    nombre_esquema: str


@dataclass(frozen=True)
class ContextoSolicitud:
    """Contexto inmutable de solicitud, resuelto antes de la sesion de negocio.

    `nombre_esquema` es `None` para la identidad global (Superadmin), que no
    tiene tenant operativo; un rol limitado recibe siempre un esquema concreto.
    """

    correo: str
    institucion_id: str | None
    nombre_esquema: str | None
    version: str


def _slug(cadena: str) -> str:
    """Translitera a ASCII minusculo y reduce lo no alfanumerico a `_`."""
    descompuesto = unicodedata.normalize("NFKD", cadena)
    ascii_plano = descompuesto.encode("ascii", "ignore").decode("ascii").lower()
    limpio = "".join(caracter if caracter.isalnum() else "_" for caracter in ascii_plano)
    return limpio.strip("_")


def nombre_esquema_para_institucion(institucion_id: str | None) -> str:
    """Nombre determinista del esquema tenant para un ID canonico de institucion.

    Reproduce la regla del plan: prefijo reservado `tenant_` + slug ASCII del ID
    + sufijo hexadecimal estable del SHA-256 del ID normalizado. Mismo ID ->
    mismo nombre; IDs distintos -> nombres distintos (el sufijo evita colisiones
    por transliteracion/recorte). Un ID vacio o no textual se rechaza; nunca se
    trunca el sufijo del hash.
    """
    if not isinstance(institucion_id, str):
        raise TypeError("el identificador de institucion debe ser una cadena")
    normalizado = institucion_id.strip()
    if not normalizado:
        raise ValueError("el identificador de institucion no puede estar vacio")

    slug = _slug(normalizado)
    sufijo = hashlib.sha256(normalizado.encode("utf-8")).hexdigest()[:LONGITUD_SUFIJO]
    presupuesto_slug = LONGITUD_MAXIMA_ESQUEMA - len(PREFIJO_TENANT) - LONGITUD_SUFIJO - 1
    return f"{PREFIJO_TENANT}{slug[:presupuesto_slug]}_{sufijo}"


def _es_identidad_global(db: Session, correo: str) -> bool:
    """True si el correo corresponde a la identidad Superadmin de control.

    El rol Superadmin vive en control (stack §7) y se resuelve alli; nunca se
    enruta como usuario tenant. En el contexto logico unico de SQLite conviven
    control y tenant, por lo que la consulta mira el rol persistido del correo.
    """
    nombres_rol = (
        db.execute(
            select(Rol.nombre_rol)
            .join(Usuario, Usuario.rol_id == Rol.rol_id)
            .where(Usuario.correo == correo)
        )
        .scalars()
        .all()
    )
    return "Superadmin" in nombres_rol


def _resolver_mapa(db: Session, correo: str) -> MapaUsuarioEsquema:
    """Fila **activa** del mapa de control para el correo, o `ErrorTenant`."""
    mapa = db.execute(
        select(MapaUsuarioEsquema).where(
            MapaUsuarioEsquema.correo == correo,
            MapaUsuarioEsquema.activo.is_(True),
        )
    ).scalar_one_or_none()
    if mapa is None:
        raise ErrorTenant("correo sin asignacion activa de tenant")
    return mapa


def esquema_para_correo(db: Session, correo: str) -> str | None:
    """Nombre del esquema activo del correo, o `None` si no esta mapeado.

    Version no lanzante de `_resolver_mapa`: la usa la resolucion de identidad
    para abrir la sesion del tenant donde vive un usuario de negocio. Un correo
    sin asociacion activa devuelve `None` (no concede tenant ni fallback).
    """
    try:
        return _resolver_mapa(db, correo).nombre_esquema
    except ErrorTenant:
        return None


def resolver_tenant_por_correo(
    db: Session,
    correo: str,
    *,
    sesion_version: Session | None = None,
) -> ResolucionTenant:
    """Traduce el correo a su esquema tenant, validando estado y version.

    `db` es la sesion de **control** (mapa `correo -> esquema`). La version vive
    en el esquema del tenant, por lo que `sesion_version` puede ser una sesion
    ligada a ese esquema; por defecto se reutiliza `db` (contexto logico unico
    de la suite SQLite). Si no hay asociacion activa o el tenant no esta en la
    version objetivo, levanta `ErrorTenant` sin fallback.
    """
    mapa = _resolver_mapa(db, correo)
    if not control_service.tenant_en_version_objetivo(sesion_version or db):
        raise ErrorTenant("el tenant no esta en la version objetivo")
    return ResolucionTenant(
        correo=correo,
        institucion_id=mapa.institucion_id,
        nombre_esquema=mapa.nombre_esquema,
    )


def resolver_contexto_solicitud(
    db: Session,
    correo: str,
    *,
    abrir_sesion_tenant: Callable[[str], Session] | None = None,
) -> ContextoSolicitud:
    """Arma el contexto inmutable de solicitud para el correo verificado.

    Casos:

    * Identidad global (Superadmin): se resuelve en control, sin tenant operativo
      (`nombre_esquema=None`).
    * Rol limitado: se resuelve el esquema tenant y se exige la version objetivo.
      `abrir_sesion_tenant` permite abrir la sesion ligada al esquema del tenant
      (con `schema_translate_map` por ejecucion); si es `None`, la version se lee
      de `db` (contexto logico unico de SQLite).
    """
    if _es_identidad_global(db, correo):
        return ContextoSolicitud(
            correo=correo,
            institucion_id=None,
            nombre_esquema=None,
            version=VERSION_ESQUEMA_OBJETIVO,
        )

    mapa = _resolver_mapa(db, correo)
    if abrir_sesion_tenant is None:
        sesion_version = db
        cerrar = False
    else:
        sesion_version = abrir_sesion_tenant(mapa.nombre_esquema)
        cerrar = True
    try:
        if not control_service.tenant_en_version_objetivo(sesion_version):
            raise ErrorTenant("el tenant no esta en la version objetivo")
    finally:
        if cerrar:
            sesion_version.close()
    return ContextoSolicitud(
        correo=correo,
        institucion_id=mapa.institucion_id,
        nombre_esquema=mapa.nombre_esquema,
        version=VERSION_ESQUEMA_OBJETIVO,
    )
