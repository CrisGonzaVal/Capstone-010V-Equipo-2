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
        return _extraer_correo_primario_verificado(datos)
    except ErrorAutenticacion:
        raise
    except Exception as exc:  # respuesta con forma inesperada
        raise ErrorAutenticacion("respuesta de Clerk inesperada") from exc


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
