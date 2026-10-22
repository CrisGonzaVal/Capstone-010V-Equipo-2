"""Lecturas globales del Superadmin (Feature 010, T11).

D-9: las lecturas globales autorizadas del Superadmin recorren los tenants
registrados en control y atribuyen cada fila a su institucion, sin fusionar
homonimos. La agregacion se ejecuta en una **unica transaccion de lectura**
PostgreSQL `REPEATABLE READ`: todas las consultas de la respuesta comparten un
mismo instante consistente. Si un tenant requerido no es accesible o no esta en
la version objetivo, la lectura falla **completa**: nunca se entrega un agregado
parcial (spec D-9/AC-12/AC-14).

Piezas publicas:

* `tenants_registrados`: los tenants activos del mapa de control, excluyendo el
  esquema reservado `control` (que no es el tenant de ninguna institucion).
* `lectura_global`: contexto que cede, por cada tenant, una sesion sobre la
  **misma** conexion `REPEATABLE READ`.
* `agregar_lista_global`: concatena una lectura acotada por tenant para una
  identidad global.
* `leer_global_unico`: busca un unico recurso por id a lo largo de los tenants
  para una identidad global.

En SQLite (contexto logico unico, AC-16) no hay namespaces que recorrer: todas
las funciones operan sobre la misma sesion y preservan el comportamiento previo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import ESQUEMA_CONTROL
from app.models.control import MapaUsuarioEsquema, VersionEsquema
from app.services import ambito_service


class ErrorLecturaGlobal(Exception):
    """Un tenant requerido no puede incluirse: el agregado global falla completo.

    Se levanta cuando un tenant registrado no esta en la version objetivo o no
    puede abrirse su lectura. La transaccion global revierte y la capa HTTP la
    normaliza a un error recuperable, sin exponer un resultado parcial.
    """


@dataclass(frozen=True)
class Tenant:
    """Tenant registrado en control: institucion canonica y su esquema."""

    institucion_id: str
    nombre_esquema: str


def tenants_registrados(db_control: Session) -> list[Tenant]:
    """Tenants activos del mapa de control, sin el esquema reservado `control`.

    El mapa tiene una fila por usuario local; dos usuarios de la misma institucion
    comparten `nombre_esquema`, de modo que se deduplica por `(institucion_id,
    nombre_esquema)`. La identidad Superadmin se mapea al esquema `control`
    (stack §4/§7) y **no** es un tenant de negocio, por lo que se excluye.
    """
    filas = db_control.execute(
        select(
            MapaUsuarioEsquema.institucion_id,
            MapaUsuarioEsquema.nombre_esquema,
        )
        .where(
            MapaUsuarioEsquema.activo.is_(True),
            MapaUsuarioEsquema.nombre_esquema != ESQUEMA_CONTROL,
        )
        .distinct()
        .order_by(
            MapaUsuarioEsquema.institucion_id,
            MapaUsuarioEsquema.nombre_esquema,
        )
    ).all()
    return [Tenant(institucion_id=fila[0], nombre_esquema=fila[1]) for fila in filas]


class _LectorLogico:
    """Contexto logico unico (SQLite/AC-16): una sola sesion, sin namespaces."""

    def __init__(self, db: Session) -> None:
        self._db = db

    @contextmanager
    def sesion(self, _tenant: Tenant) -> Iterator[Session]:
        yield self._db


class _LectorPostgres:
    """Sesiones por tenant sobre UNA conexion `REPEATABLE READ` compartida.

    Todas las sesiones se apoyan en la misma conexion (misma transaccion), por lo
    que representan un unico instante. Antes de usarse, la version del tenant se
    valida contra la version objetivo: un tenant ausente/incompatible levanta
    `ErrorLecturaGlobal` y revierte la transaccion global.
    """

    def __init__(self, conexion) -> None:
        self._conexion = conexion

    @contextmanager
    def sesion(self, tenant: Tenant) -> Iterator[Session]:
        conexion = self._conexion.execution_options(
            schema_translate_map={None: tenant.nombre_esquema}
        )
        sesion = Session(bind=conexion, join_transaction_mode="create_savepoint")
        try:
            versiones = sesion.execute(select(VersionEsquema.version)).scalars().all()
            if len(versiones) != 1 or versiones[0] != VERSION_ESQUEMA_OBJETIVO:
                raise ErrorLecturaGlobal(
                    "el tenant no esta en la version objetivo"
                )
            yield sesion
        finally:
            sesion.close()


@contextmanager
def lectura_global(db_control: Session) -> Iterator[object]:
    """Cede el lector de tenants para una lectura global de instante unico.

    En PostgreSQL abre **una** conexion `REPEATABLE READ` y la mantiene durante
    todo el bloque; cada `sesion(tenant)` liga su esquema a esa conexion. Si
    cualquier lectura falla, el bloque revierte y no se entrega nada parcial.
    """
    motor = db_control.get_bind()
    if motor.dialect.name != "postgresql":
        yield _LectorLogico(db_control)
        return
    motor_rr = motor.execution_options(isolation_level="REPEATABLE READ")
    with motor_rr.connect() as conexion:
        with conexion.begin():
            yield _LectorPostgres(conexion)


def _es_global_postgres(db: Session, identidad) -> bool:
    return (
        ambito_service.es_alcance_global(identidad)
        and db.get_bind().dialect.name == "postgresql"
    )


def agregar_lista_global(
    db: Session, identidad, funcion: Callable[[Session], list]
) -> list:
    """Ejecuta `funcion(sesion)` por tenant y concatena, para una identidad global.

    Un rol limitado recibe el resultado de su propia sesion (ya acotada a su
    tenant en PostgreSQL). El Superadmin global en PostgreSQL obtiene la
    concatenacion de las lecturas de cada tenant registrado, todas dentro de una
    unica transaccion de lectura. Sin tenants registrados (instalacion limpia) o
    en SQLite, opera sobre la sesion recibida.
    """
    if not _es_global_postgres(db, identidad):
        return funcion(db)
    tenants = tenants_registrados(db)
    if not tenants:
        return funcion(db)
    resultado: list = []
    with lectura_global(db) as lector:
        for tenant in tenants:
            with lector.sesion(tenant) as sesion:
                resultado.extend(funcion(sesion))
    return resultado


def leer_global_unico(
    db: Session,
    identidad,
    funcion: Callable[[Session], object],
    *,
    no_encontrado: str,
) -> object:
    """Busca un unico recurso por id a lo largo de los tenants, identidad global.

    En PostgreSQL, el Superadmin recorre los tenants registrados dentro de una
    misma transaccion de lectura y devuelve el primer recurso resoluble; si
    ninguno lo resuelve (404), responde **404** con `no_encontrado`. Un rol
    limitado y SQLite conservan el camino de una sola sesion.
    """
    if not _es_global_postgres(db, identidad):
        return funcion(db)
    tenants = tenants_registrados(db)
    if not tenants:
        return funcion(db)
    with lectura_global(db) as lector:
        for tenant in tenants:
            with lector.sesion(tenant) as sesion:
                try:
                    return funcion(sesion)
                except HTTPException as exc:
                    if exc.status_code == status.HTTP_404_NOT_FOUND:
                        continue
                    raise
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=no_encontrado)
