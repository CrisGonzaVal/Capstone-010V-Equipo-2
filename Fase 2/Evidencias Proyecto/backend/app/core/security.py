"""Frontera externa de autenticacion Clerk (Feature 006).

Encapsula la validacion criptografica del JWT de sesion de Clerk y la consulta
al Backend API de Clerk para obtener el correo primario verificado:

* Descarga el JWKS publicado por `{CLERK_ISSUER}/.well-known/jwks.json`, cachea
  el documento con TTL y refresca una sola vez ante un `kid` desconocido.
* Selecciona la clave por `kid`, restringe los algoritmos a una allowlist
  (RS256), valida firma, `iss` exacto, `exp`/`nbf` con margen de reloj y exige
  `azp` dentro de los origenes frontend autorizados. No exige `aud`.
* Consulta con `CLERK_SECRET_KEY` `GET https://api.clerk.com/v1/users/{sub}`
  usando un `httpx.BaseTransport` inyectable, y lee el correo primario y su
  estado de verificacion.

Clerk es la unica autoridad de autenticacion: este modulo no emite ni acepta
tokens locales. Todo fallo se normaliza a `ErrorAutenticacion` para que la capa
HTTP responda 401 sin filtrar la causa.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

#: TTL de la cache del documento JWKS (segundos). Monkeypatcheable por los tests.
TTL_JWKS_SEGUNDOS = 3600

#: Allowlist de algoritmos de firma aceptados.
ALGORITMOS_PERMITIDOS = ["RS256"]

#: Origenes frontend autorizados como `azp` del token de sesion.
AZP_PERMITIDOS = frozenset({"http://localhost:4200", "http://localhost:8080"})

#: Margen de reloj para `exp`/`nbf`.
MARGEN_RELOJ_SEGUNDOS = 10

#: Base del Backend API de Clerk.
URL_BACKEND_CLERK = "https://api.clerk.com"

#: Tipos de JWKS: callable `fuente(issuer) -> dict` con el documento JWKS.
FuenteJWKS = Callable[[str], dict]

#: Cache por issuer: `{issuer: (instante_descarga, documento_jwks)}`.
_cache_jwks: dict[str, tuple[float, dict]] = {}


class ErrorAutenticacion(Exception):
    """Fallo de autenticacion o vinculo. Se traduce a HTTP 401 sin causa interna."""


def descargar_jwks(issuer: str) -> dict:
    """Fuente JWKS de produccion: descarga el documento publicado por el emisor."""
    url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    try:
        respuesta = httpx.get(url, timeout=5.0)
        respuesta.raise_for_status()
        return respuesta.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ErrorAutenticacion("no fue posible obtener el JWKS") from exc


def _buscar_jwk(documento: dict, kid: str | None) -> dict | None:
    if not kid:
        return None
    for jwk in documento.get("keys", []):
        if jwk.get("kid") == kid:
            return jwk
    return None


def _guardar_en_cache(issuer: str, documento: dict) -> dict:
    """Cachea una copia del documento: refleja el JWKS descargado, no mutaciones posteriores."""
    instantanea = copy.deepcopy(documento)
    _cache_jwks[issuer] = (time.monotonic(), instantanea)
    return instantanea


def _jwks_desde_cache(issuer: str, fuente: FuenteJWKS) -> dict:
    entrada = _cache_jwks.get(issuer)
    ahora = time.monotonic()
    if entrada is None or (ahora - entrada[0]) >= TTL_JWKS_SEGUNDOS:
        return _guardar_en_cache(issuer, fuente(issuer))
    return entrada[1]


def _jwks_refrescado(issuer: str, fuente: FuenteJWKS) -> dict:
    return _guardar_en_cache(issuer, fuente(issuer))


def validar_token(token: str, issuer: str, fuente_jwks: FuenteJWKS) -> dict:
    """Valida el JWT de sesion Clerk y devuelve sus claims ya verificados.

    Ante un `kid` ausente en el documento cacheado refresca **una sola vez**
    para contemplar rotacion de claves; si sigue ausente, rechaza.
    """
    try:
        encabezado = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ErrorAutenticacion("token ilegible") from exc

    if encabezado.get("alg") not in ALGORITMOS_PERMITIDOS:
        raise ErrorAutenticacion("algoritmo no permitido")

    kid = encabezado.get("kid")
    documento = _jwks_desde_cache(issuer, fuente_jwks)
    jwk = _buscar_jwk(documento, kid)
    if jwk is None:
        documento = _jwks_refrescado(issuer, fuente_jwks)
        jwk = _buscar_jwk(documento, kid)
    if jwk is None:
        raise ErrorAutenticacion("kid desconocido")

    try:
        clave = RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = jwt.decode(
            token,
            clave,
            algorithms=ALGORITMOS_PERMITIDOS,
            issuer=issuer,
            leeway=MARGEN_RELOJ_SEGUNDOS,
            options={
                "verify_aud": False,
                "require": ["exp", "nbf", "iss", "sub"],
            },
        )
    except jwt.PyJWTError as exc:
        raise ErrorAutenticacion("token invalido") from exc

    if claims.get("azp") not in AZP_PERMITIDOS:
        raise ErrorAutenticacion("origen no autorizado")
    return claims


def obtener_correo_primario_verificado(
    sub: str, secret_key: str, transport: httpx.BaseTransport
) -> str:
    """Consulta el Backend API de Clerk y devuelve el correo primario verificado."""
    try:
        with httpx.Client(base_url=URL_BACKEND_CLERK, transport=transport) as cliente:
            respuesta = cliente.get(
                f"/v1/users/{sub}",
                headers={"Authorization": f"Bearer {secret_key}"},
            )
    except httpx.HTTPError as exc:
        raise ErrorAutenticacion("fallo de red contra Clerk") from exc

    if respuesta.status_code != 200:
        raise ErrorAutenticacion("Clerk no respondio correctamente")

    try:
        datos = respuesta.json()
    except ValueError as exc:
        raise ErrorAutenticacion("respuesta de Clerk ilegible") from exc

    try:
        return normalizar_correo(_extraer_correo_primario_verificado(datos))
    except ErrorAutenticacion:
        raise
    except Exception as exc:  # respuesta con forma inesperada
        raise ErrorAutenticacion("respuesta de Clerk inesperada") from exc


def correo_existe_en_clerk(
    correo: str, secret_key: str, transport: httpx.BaseTransport
) -> bool:
    """True si Clerk tiene una identidad con ese correo primario verificado.

    Frontera externa del aprovisionamiento (Feature 010, D-7): el alta del primer
    Administrador exige que su correo exista previamente en Clerk antes de crear
    el tenant, para no crear un usuario local imposible de autenticar con la
    autoridad de identidad vigente. No se crean cuentas ni credenciales.

    Un fallo de red o una respuesta no `200` se normalizan a `ErrorAutenticacion`
    (el alta responde **503**); un correo inexistente devuelve `False` (el alta
    responde **422**).
    """
    normalizado = normalizar_correo(correo)
    try:
        with httpx.Client(base_url=URL_BACKEND_CLERK, transport=transport) as cliente:
            respuesta = cliente.get(
                "/v1/users",
                params={"email_address": [normalizado]},
                headers={"Authorization": f"Bearer {secret_key}"},
            )
    except httpx.HTTPError as exc:
        raise ErrorAutenticacion("fallo de red contra Clerk") from exc

    if respuesta.status_code != 200:
        raise ErrorAutenticacion("Clerk no respondio correctamente")

    try:
        datos = respuesta.json()
    except ValueError as exc:
        raise ErrorAutenticacion("respuesta de Clerk ilegible") from exc

    if not isinstance(datos, list):
        raise ErrorAutenticacion("respuesta de Clerk inesperada")

    for usuario in datos:
        for direccion in usuario.get("email_addresses") or []:
            if normalizar_correo(direccion.get("email_address") or "") == normalizado:
                return True
    return False


def _extraer_correo_primario_verificado(datos: dict) -> str:
    identificador_primario = datos.get("primary_email_address_id")
    if not identificador_primario:
        raise ErrorAutenticacion("sin correo primario")

    for direccion in datos.get("email_addresses") or []:
        if direccion.get("id") != identificador_primario:
            continue
        if (direccion.get("verification") or {}).get("status") != "verified":
            raise ErrorAutenticacion("correo primario no verificado")
        correo = direccion.get("email_address")
        if not correo:
            raise ErrorAutenticacion("correo primario vacio")
        return correo

    raise ErrorAutenticacion("correo primario ausente en la respuesta")


# ---------------------------------------------------------------------------
# Frontera Clerk de invitaciones (Feature 017)
# ---------------------------------------------------------------------------

#: Codigos de error de Clerk que significan "ya existe" y son conflicto recuperable.
CODIGOS_CONFLICTO_INVITACION = frozenset(
    {
        "already_invited",
        "already_exists",
        "form_identifier_exists",
        "invitation_already_exists",
    }
)

#: Estados de invitacion que Clerk considera vigentes.
ESTADOS_INVITACION_VIGENTE = frozenset({"pending"})


class ErrorFronteraClerk(Exception):
    """Base de fallos de la frontera Clerk de invitaciones (Feature 017)."""


class ErrorClerkNoDisponible(ErrorFronteraClerk):
    """Red, 429, 5xx o payload ilegible: la capa HTTP responde **503**.

    No transporta detalles internos de Clerk; el servicio decide el codigo de
    respuesta sin filtrar la causa externa.
    """


class ErrorInvitacionConflicto(ErrorFronteraClerk):
    """Clerk informa una invitacion/identidad existente: la capa HTTP responde **409**.

    Es un conflicto recuperable: no se inventa URL ni se sustituye el
    identificador persistido (D-4).
    """


@dataclass(frozen=True)
class EstadoIdentidadClerk:
    """Clasificacion externa de un correo antes de crear una invitacion (D-1)."""

    identidad_existente: bool
    invitacion_pendiente: bool
    invitacion_id: str | None


@dataclass(frozen=True)
class InvitacionCreada:
    """Resultado puntual de alta/reenvio: URL y expiracion solo en esta respuesta."""

    invitacion_id: str
    url: str
    expira_en: datetime


def normalizar_correo(correo: str) -> str:
    """Unica regla de correo del proyecto: recorta extremos y pasa a minusculas."""
    return correo.strip().lower()


def _cabecera_autorizacion(secret_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret_key}"}


def _json_de_respuesta(respuesta: httpx.Response):
    """Decodifica el cuerpo o falla como `ErrorClerkNoDisponible` si es ilegible."""
    try:
        return respuesta.json()
    except ValueError as exc:
        raise ErrorClerkNoDisponible("respuesta de Clerk ilegible") from exc


def _hay_identidad(usuarios: list, correo: str) -> bool:
    """True si alguna direccion del listado coincide con el correo normalizado."""
    for usuario in usuarios:
        if not isinstance(usuario, dict):
            continue
        for direccion in usuario.get("email_addresses") or []:
            if not isinstance(direccion, dict):
                continue
            if normalizar_correo(direccion.get("email_address") or "") == correo:
                return True
    return False


def _invitacion_pendiente_de(datos, correo: str) -> str | None:
    """Devuelve el id de la invitacion pendiente del correo, si existe.

    `GET /v1/invitations` no tiene una forma unica de listado: la instancia dev
    responde la **lista desnuda** de invitaciones, mientras que otras versiones
    de la API envuelven el listado en `{"data": [...]}`. Ambas formas se aceptan
    para no convertir una diferencia de sobre en un 503 que bloquee el alta.
    """
    invitaciones = datos.get("data") if isinstance(datos, dict) else datos
    if not isinstance(invitaciones, list):
        raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")

    for invitacion in invitaciones:
        if not isinstance(invitacion, dict):
            continue
        estado = str(invitacion.get("status") or "").lower()
        if estado not in ESTADOS_INVITACION_VIGENTE:
            continue
        if normalizar_correo(invitacion.get("email_address") or "") != correo:
            continue
        invitacion_id = invitacion.get("id")
        if isinstance(invitacion_id, str) and invitacion_id:
            return invitacion_id
    return None


def _es_conflicto_de_invitacion(respuesta: httpx.Response) -> bool:
    """True si el cuerpo declara un error de "ya existe"/"ya invitado" de Clerk."""
    try:
        datos = respuesta.json()
    except ValueError:
        return False
    if not isinstance(datos, dict):
        return False
    errores = datos.get("errors")
    if not isinstance(errores, list):
        return False
    for error in errores:
        if not isinstance(error, dict):
            continue
        codigo = str(error.get("code") or "").lower()
        if codigo in CODIGOS_CONFLICTO_INVITACION or "already" in codigo:
            return True
    return False


def _instante_expiracion(valor) -> datetime:
    """Convierte la expiracion de Clerk (epoch ms) a `datetime` con zona UTC."""
    if isinstance(valor, bool):
        raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")
    if isinstance(valor, (int, float)):
        segundos = valor / 1000 if valor > 100_000_000_000 else valor
        return datetime.fromtimestamp(segundos, tz=timezone.utc)
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErrorClerkNoDisponible("respuesta de Clerk inesperada") from exc
    raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")


def buscar_identidad_o_invitacion(
    correo: str, secret_key: str, transport: httpx.BaseTransport
) -> EstadoIdentidadClerk:
    """Clasifica el correo en Clerk: identidad, invitacion pendiente o ninguna.

    Orden de consulta: `GET /v1/users` (identidad) y, solo si no existe, `GET
    /v1/invitations` con estado `pending` (D-1). Una identidad existente se
    vincula localmente sin invitacion; una invitacion pendiente se reutiliza sin
    crear otra. Red/429/5xx/payload invalido -> `ErrorClerkNoDisponible` (503)
    sin estado local.
    """
    normalizado = normalizar_correo(correo)
    cabecera = _cabecera_autorizacion(secret_key)

    try:
        with httpx.Client(
            base_url=URL_BACKEND_CLERK, transport=transport, timeout=10.0
        ) as cliente:
            respuesta_usuarios = cliente.get(
                "/v1/users",
                params={"email_address": [normalizado]},
                headers=cabecera,
            )
            if respuesta_usuarios.status_code != 200:
                raise ErrorClerkNoDisponible("Clerk no respondio correctamente")
            usuarios = _json_de_respuesta(respuesta_usuarios)
            if not isinstance(usuarios, list):
                raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")

            if _hay_identidad(usuarios, normalizado):
                return EstadoIdentidadClerk(
                    identidad_existente=True,
                    invitacion_pendiente=False,
                    invitacion_id=None,
                )

            respuesta_invitaciones = cliente.get(
                "/v1/invitations",
                params={"email_address": [normalizado], "status": "pending"},
                headers=cabecera,
            )
            if respuesta_invitaciones.status_code != 200:
                raise ErrorClerkNoDisponible("Clerk no respondio correctamente")
            invitaciones = _json_de_respuesta(respuesta_invitaciones)
    except httpx.HTTPError as exc:
        raise ErrorClerkNoDisponible("fallo de red contra Clerk") from exc

    invitacion_id = _invitacion_pendiente_de(invitaciones, normalizado)
    return EstadoIdentidadClerk(
        identidad_existente=False,
        invitacion_pendiente=invitacion_id is not None,
        invitacion_id=invitacion_id,
    )


def crear_invitacion(
    correo: str,
    secret_key: str,
    transport: httpx.BaseTransport,
    *,
    ignore_existing: bool = False,
) -> InvitacionCreada:
    """Crea una invitacion Clerk y devuelve id, URL y expiracion (solo aqui).

    Nunca crea usuarios (`POST /v1/users`): la identidad la materializa la
    persona invitada al aceptar. `ignore_existing` se envia explicito segun el
    flujo de alta/reenvio y no habilita duplicar identidades. Un "ya invitado"
    de Clerk se traduce a `ErrorInvitacionConflicto` (409) sin URL inventada; un
    fallo externo, a `ErrorClerkNoDisponible` (503).
    """
    normalizado = normalizar_correo(correo)
    try:
        with httpx.Client(
            base_url=URL_BACKEND_CLERK, transport=transport, timeout=10.0
        ) as cliente:
            respuesta = cliente.post(
                "/v1/invitations",
                json={
                    "email_address": normalizado,
                    "ignore_existing": ignore_existing,
                },
                headers=_cabecera_autorizacion(secret_key),
            )
    except httpx.HTTPError as exc:
        raise ErrorClerkNoDisponible("fallo de red contra Clerk") from exc

    if respuesta.status_code not in (200, 201):
        if respuesta.status_code in (400, 409) and _es_conflicto_de_invitacion(
            respuesta
        ):
            raise ErrorInvitacionConflicto(
                "Clerk ya registra una invitacion o identidad para el correo"
            )
        raise ErrorClerkNoDisponible("Clerk no respondio correctamente")

    datos = _json_de_respuesta(respuesta)
    if not isinstance(datos, dict):
        raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")

    invitacion_id = datos.get("id")
    url = datos.get("url")
    if (
        not isinstance(invitacion_id, str)
        or not invitacion_id
        or not isinstance(url, str)
        or not url
    ):
        raise ErrorClerkNoDisponible("respuesta de Clerk inesperada")

    return InvitacionCreada(
        invitacion_id=invitacion_id,
        url=url,
        expira_en=_instante_expiracion(datos.get("expires_at")),
    )


def revocar_invitacion(
    invitacion_id: str, secret_key: str, transport: httpx.BaseTransport
) -> None:
    """Revoca una invitacion por identificador (compensacion o reenvio, D-2/D-4).

    Un fallo externo se normaliza a `ErrorClerkNoDisponible` para que el
    llamador decida si persiste una constancia; no se infiere revocacion
    externa por otra via.
    """
    if not isinstance(invitacion_id, str) or not invitacion_id:
        raise ValueError("invitacion_id requerido para revocar")

    try:
        with httpx.Client(
            base_url=URL_BACKEND_CLERK, transport=transport, timeout=10.0
        ) as cliente:
            respuesta = cliente.post(
                f"/v1/invitations/{invitacion_id}/revoke",
                headers=_cabecera_autorizacion(secret_key),
            )
    except httpx.HTTPError as exc:
        raise ErrorClerkNoDisponible("fallo de red contra Clerk") from exc

    if respuesta.status_code not in (200, 204):
        raise ErrorClerkNoDisponible("Clerk no respondio correctamente")
