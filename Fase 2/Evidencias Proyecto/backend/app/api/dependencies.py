"""Dependencias de la capa HTTP (Features 006 y 007).

`get_db` inyecta la `Session`. Las costuras `obtener_fuente_jwks` y
`obtener_transporte_clerk` aíslan la red (JWKS y Backend API de Clerk) para
poder overridearlas en los tests. `get_current_user` resuelve la identidad
vinculada delegando en `auth_service` y normaliza todo fallo a HTTP 401.

La autorizacion por rol (Feature 007) se expone con `requiere_roles`, que
fabrica una dependencia parametrizable que reutiliza `get_current_user`: la
sesion ausente/invalida conserva el 401 y una identidad autenticada sin el rol
requerido recibe 403. La matriz central de permisos vive en
`app.core.permisos`; `requiere_operacion` la ata a la ruta declarada.
"""

from collections.abc import Callable, Generator

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import permisos, security
from app.core.config import settings
from app.core.security import FuenteJWKS
from app.db.database import crear_sesion_control, crear_sesion_esquema
from app.services import auth_service, tenant_service
from app.services.auth_service import IdentidadAutenticada
from app.services.tenant_service import ContextoSolicitud

#: Esquema HTTP Bearer sin error automatico: publica el securityScheme en
#: OpenAPI pero permite un 401 explicito en vez del 403 por defecto cuando
#: faltan credenciales.
esquema_bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Sesion del **esquema de control**, ligada explicitamente a `control`.

    La sesion de control (resolucion de identidad, mapa `correo -> esquema` y
    lecturas globales) se abre con `crear_sesion_control`, que fija el esquema de
    control de forma explicita: resuelve a `control` tanto en una instalacion
    limpia como en una base migrada, donde el `search_path` por defecto de la
    base no apunta a `control` (Feature 010, T11).
    """
    db = crear_sesion_control()
    try:
        yield db
    finally:
        db.close()


def obtener_fuente_jwks() -> FuenteJWKS:
    """Costura inyectable: fuente del documento JWKS (`fuente(issuer) -> dict`)."""
    return security.descargar_jwks


def obtener_transporte_clerk() -> httpx.BaseTransport:
    """Costura inyectable: transporte HTTP hacia el Backend API de Clerk."""
    return httpx.HTTPTransport()


def obtener_verificador_correo_clerk(
    transporte: httpx.BaseTransport = Depends(obtener_transporte_clerk),
) -> Callable[[str], bool]:
    """Costura inyectable del verificador de existencia de correo en Clerk (T7).

    Devuelve un `Callable[[str], bool]`: `True` si el correo existe como
    identidad verificada en Clerk, `False` si no, y `security.ErrorAutenticacion`
    si la frontera externa no se puede consultar. Las pruebas la overridean para
    no invocar Clerk real (plan §3); el alta no crea cuentas ni credenciales.
    """
    def verificar(correo: str) -> bool:
        return security.correo_existe_en_clerk(
            correo, settings.CLERK_SECRET_KEY, transporte
        )

    return verificar


def respuestas_de_autorizacion() -> dict[int, dict[str, str]]:
    """Respuestas documentadas de autorizacion para las operaciones de negocio.

    Feature 007 (D-5): toda operacion de la matriz declara el **401** (sesion
    ausente o invalida) y el **403** (identidad autenticada sin el rol requerido)
    en `/openapi.json` sin alterar el `response_model` de exito ni el contrato de
    la respuesta. Devuelve un diccionario nuevo por llamada para que el decorador
    de cada ruta no comparta una estructura mutable con las demas.
    """
    return {
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Credenciales ausentes o invalidas, o identidad no resoluble."
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Identidad autenticada sin el rol requerido para la operacion."
        },
    }


def respuesta_recurso_oculto() -> dict[int, dict[str, str]]:
    """Documenta el **404** con el que se oculta un recurso inexistente o ajeno.

    Feature 008 (D-4/AC-9/AC-16): un id de otra institucion responde 404 igual que
    uno inexistente, de modo que no revela su existencia. Devuelve un diccionario
    nuevo por llamada, igual que `respuestas_de_autorizacion`.
    """
    return {
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "Recurso inexistente o ajeno al ambito del usuario: se oculta como "
                "inexistente (Feature 008). En una operacion de creacion, ninguna "
                "fila parcial queda persistida."
            )
        }
    }


def respuesta_conflicto() -> dict[int, dict[str, str]]:
    """Documenta el **409** de estado/catalogo/stock o referencia cruzada.

    Feature 008 (AC-12/AC-16): un estado no elegible, stock insuficiente o una
    referencia institucional cruzada responden 409 sin aplicar cambios.
    """
    return {
        status.HTTP_409_CONFLICT: {
            "description": (
                "Conflicto de estado del flujo, catalogo incompleto, stock "
                "insuficiente o referencia institucional cruzada; no se aplica "
                "ningun cambio."
            )
        }
    }


def _no_autorizado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credenciales: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    fuente_jwks: FuenteJWKS = Depends(obtener_fuente_jwks),
    transporte: httpx.BaseTransport = Depends(obtener_transporte_clerk),
    db: Session = Depends(get_db),
) -> IdentidadAutenticada:
    """Devuelve la identidad vinculada (usuario local + `sub` validado de Clerk).

    Ausencia o invalidez de credenciales, fallo de JWKS, de Clerk, correo no
    verificado o falta de coincidencia local se responden como 401 sin filtrar
    la causa interna.
    """
    if credenciales is None:
        raise _no_autorizado()
    try:
        return auth_service.resolver_identidad(
            token=credenciales.credentials,
            issuer=settings.CLERK_ISSUER,
            fuente_jwks=fuente_jwks,
            secret_key=settings.CLERK_SECRET_KEY,
            transport=transporte,
            db=db,
        )
    except security.ErrorAutenticacion as exc:
        raise _no_autorizado() from exc


def get_contexto_solicitud(
    identidad: IdentidadAutenticada = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContextoSolicitud:
    """Resuelve el contexto inmutable de solicitud (Feature 010, T5).

    La identidad ya validada por Clerk aporta el correo; `tenant_service` lo
    traduce a un esquema tenant (o a la identidad global del Superadmin) contra
    el mapa de control. Ninguna entrada del cliente participa. Un correo no
    mapeado, con asociacion inactiva o con tenant no versionado responde **403**
    sin caer a otro esquema ni a global.
    """
    try:
        return tenant_service.resolver_contexto_solicitud(db, identidad.usuario.correo)
    except tenant_service.ErrorTenant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La identidad no tiene un tenant de negocio operativo",
        ) from exc


def get_db_tenant(
    contexto: ContextoSolicitud = Depends(get_contexto_solicitud),
) -> Generator[Session, None, None]:
    """Sesion de negocio acotada al esquema tenant resuelto (Feature 010, T5).

    El esquema procede **solo** del contexto de control. Se abre una sesion por
    ejecucion con `schema_translate_map`; al cerrarla, la conexion vuelve al pool
    sin estado de tenant (sin `search_path`). La identidad global (Superadmin)
    no tiene tenant operativo y recibe **403** en rutas de negocio.
    """
    if contexto.nombre_esquema is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La operacion requiere un tenant de negocio",
        )
    sesion = crear_sesion_esquema(contexto.nombre_esquema)
    try:
        yield sesion
    finally:
        sesion.close()


def get_db_negocio(
    db: Session = Depends(get_db),
    identidad: IdentidadAutenticada = Depends(get_current_user),
) -> Generator[Session, None, None]:
    """Sesion de **negocio** acotada al tenant resuelto (Feature 010, T11).

    Es la costura que cablea el contexto tenant en los flujos de negocio
    existentes (`inventario`, `tickets`, `dashboard`):

    * En **PostgreSQL** resuelve el esquema del correo verificado contra el mapa
      de control (nunca una entrada del cliente) y abre una sesion con
      `schema_translate_map` por ejecucion, de modo que toda operacion de un rol
      limitado se ejecuta **solo** en su tenant. Un correo no mapeado o un tenant
      no versionado deniega en cerrado con **403**; la identidad global
      (Superadmin) conserva la sesion de control para su lectura global.
    * En **SQLite** (suite ordinaria, AC-16) devuelve la sesion recibida: existe un
      contexto logico unico y no hay namespaces que seleccionar.

    Sustituye a `get_db` en los routers de negocio: las operaciones siguen siendo
    las mismas y sus contratos no cambian.
    """
    if db.get_bind().dialect.name != "postgresql":
        yield db
        return
    try:
        contexto = tenant_service.resolver_contexto_solicitud(
            db,
            identidad.usuario.correo,
            abrir_sesion_tenant=lambda esquema: crear_sesion_esquema(
                esquema, motor=db.get_bind()
            ),
        )
    except tenant_service.ErrorTenant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La identidad no tiene un tenant de negocio operativo",
        ) from exc
    if contexto.nombre_esquema is None:
        # Identidad global (Superadmin): no tiene tenant operativo propio; su
        # lectura global se compone por ejecucion sobre los tenants registrados.
        yield db
        return
    sesion = crear_sesion_esquema(contexto.nombre_esquema, motor=db.get_bind())
    try:
        yield sesion
    finally:
        sesion.close()


def _permiso_insuficiente() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permiso insuficiente para la operacion",
    )


def requiere_roles(*roles_permitidos: str) -> Callable[..., IdentidadAutenticada]:
    """Fabrica una dependencia que exige uno de los `roles_permitidos`.

    Depende de `get_current_user`, de modo que la identidad Clerk se resuelve
    una sola vez por solicitud (FastAPI cachea dependencias equivalentes) y el
    endpoint/servicio recibe esa misma identidad sin volver a resolverla. La
    semantica de denegacion es D-5: sesion ausente o invalida conserva el **401**
    de `get_current_user`; una identidad autenticada sin el rol requerido recibe
    **403**. Un rol ausente, vacio o desconocido (p. ej. `Admin`, que no es un
    alias) nunca concede permiso.
    """
    permitidos = frozenset(roles_permitidos)

    def dependencia(
        identidad: IdentidadAutenticada = Depends(get_current_user),
    ) -> IdentidadAutenticada:
        rol = permisos.nombre_rol_de(identidad)
        if not permisos.rol_autorizado(rol, permitidos):
            raise _permiso_insuficiente()
        return identidad

    return dependencia


def requiere_operacion(
    metodo: str, ruta: str
) -> Callable[..., IdentidadAutenticada]:
    """Dependencia de autorizacion para una operacion de la matriz D-3.

    Lee los roles permitidos de `app.core.permisos.MATRIZ_PERMISOS` (la fuente
    central) y delega en `requiere_roles`. Una operacion no declarada en la
    matriz levanta `KeyError` al construir la dependencia: no hay permiso
    implicito.
    """
    return requiere_roles(*permisos.roles_de_operacion(metodo, ruta))
