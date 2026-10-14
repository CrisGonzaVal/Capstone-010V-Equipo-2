"""T2 (Feature 006): pruebas rojas de autenticacion Clerk y vinculo local.

Seam bajo prueba: la **interfaz HTTP** (`TestClient`), igual que el resto de la
suite. Ninguna asercion consulta la base directamente ni importa servicios
internos de negocio.

Estas pruebas son de TDD: describen el comportamiento *observable* que T3-T6
deben implementar. Hoy fallan porque la funcionalidad aun no existe (endpoint
`/auth/me` ausente, router de negocio sin proteger, `securityScheme` no
publicado), no por errores de importacion ni de fixture.

Nunca se usan credenciales reales: el par de claves RSA y el JWKS se generan en
el propio test, y el transporte hacia `api.clerk.com` es un `httpx.MockTransport`.
El JWKS simulado verifica una firma real con la clave fixture (auto-chequeo en
la fixture `par_de_claves`).

Contrato inyectable que estas pruebas exigen (ver `plan.md` §1 y §3.2):

  * `app.api.dependencies.obtener_fuente_jwks` -> callable
    `fuente(issuer: str) -> dict` que entrega el documento JWKS.
  * `app.api.dependencies.obtener_transporte_clerk` -> `httpx.BaseTransport`
    para el Backend API de Clerk.
  * `app.core.security` valida firma, `iss`, `exp`/`nbf`, allowlist de
    algoritmo y `azp`; cachea el JWKS con TTL y refresca una vez ante `kid`
    desconocido. Expone `TTL_JWKS_SEGUNDOS` para poder probar la caducidad.
  * `app.api.v1.endpoints.auth.router` expone `GET /auth/me`.
  * `app.api.v1.api` aplica la dependencia Bearer al router agregado.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import settings
from app.main import app
from app.models.usuario import Usuario
from app.services.auth_service import IdentidadAutenticada

RUTA_ME = "/api/v1/auth/me"

#: Origenes frontend autorizados por la spec (§3.2 del plan).
AZP_PERMITIDOS = ["http://localhost:4200", "http://localhost:8080"]

#: Rutas de negocio que deben quedar protegidas por el router agregado (AC-10).
RUTAS_NEGOCIO = [
    "/api/v1/usuarios/",
    "/api/v1/usuarios/roles",
    "/api/v1/inventario/categorias",
    "/api/v1/inventario/productos",
    "/api/v1/inventario/stock",
    "/api/v1/inventario/existencias",
    "/api/v1/tickets/",
]


# ---------------------------------------------------------------------------
# Fixtures: par de claves, JWKS simulado y transporte Clerk mock
# ---------------------------------------------------------------------------


@dataclass
class ParClaves:
    privada: object
    publica: object
    kid: str
    jwks: dict


def _jwks_desde_publica(publica: object, kid: str) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(publica))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def _generar_par(kid: str) -> ParClaves:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publica = privada.public_key()
    return ParClaves(privada=privada, publica=publica, kid=kid, jwks=_jwks_desde_publica(publica, kid))


@pytest.fixture
def par_de_claves() -> ParClaves:
    """Par de claves RSA efimero + su JWKS.

    Se auto-verifica una firma contra el JWK generado: si el JWKS simulado no
    fuese valido, esta fixture revienta antes de que el test pueda dar un falso
    negativo. Es la prueba de que el JWKS mock verifica firmas de la clave
    fixture sin usar Clerk real.
    """
    par = _generar_par("kid-principal")
    sonda = jwt.encode({"sub": "sonda"}, par.privada, algorithm="RS256", headers={"kid": par.kid})
    clave_publica = RSAAlgorithm.from_jwk(json.dumps(par.jwks["keys"][0]))
    assert jwt.decode(sonda, clave_publica, algorithms=["RS256"])["sub"] == "sonda"
    return par


@pytest.fixture
def clave_intrusa() -> ParClaves:
    """Otra clave, para firmar tokens con una firma que no corresponde al `kid`."""
    return _generar_par("kid-intruso")


@pytest.fixture
def emisor() -> str:
    """Emisor unico por test: aisla la cache JWKS del resto de la suite."""
    return f"https://clerk.test/{uuid4().hex}"


class FuenteJWKSSimulada:
    """Fuente JWKS inyectable; cuenta descargas y permite simular rotacion."""

    def __init__(self, jwks: dict) -> None:
        self.jwks = jwks
        self.llamadas = 0

    def __call__(self, issuer: str) -> dict:
        self.llamadas += 1
        return self.jwks

    def agregar(self, jwk: dict) -> None:
        self.jwks["keys"].append(jwk)


@pytest.fixture
def fuente_jwks_simulada(par_de_claves: ParClaves) -> FuenteJWKSSimulada:
    return FuenteJWKSSimulada(json.loads(json.dumps(par_de_claves.jwks)))


@pytest.fixture
def respuesta_clerk() -> dict:
    """Estado mutable que el transporte mock usa para responder.

    El test ajusta `cuerpo`, `estado` o `excepcion` antes de cada peticion.
    """
    return {"cuerpo": None, "estado": 200, "excepcion": None}


@pytest.fixture
def transporte_clerk(respuesta_clerk: dict) -> httpx.MockTransport:
    def manejador(_peticion: httpx.Request) -> httpx.Response:
        if respuesta_clerk["excepcion"] is not None:
            raise respuesta_clerk["excepcion"]
        return httpx.Response(respuesta_clerk["estado"], json=respuesta_clerk["cuerpo"])

    return httpx.MockTransport(manejador)


def cuerpo_clerk(
    correo: str,
    *,
    sub: str = "user_ana",
    verificado: bool = True,
    primario: bool = True,
) -> dict:
    identificador = "idn_primario"
    return {
        "id": sub,
        "primary_email_address_id": identificador if primario else None,
        "email_addresses": [
            {
                "id": identificador,
                "email_address": correo,
                "verification": {"status": "verified" if verificado else "unverified"},
            }
        ],
    }


@pytest.fixture
def firmar_token(par_de_claves: ParClaves, emisor: str):
    """Fabrica tokens firmados con la clave fixture, con overrides por caso."""

    def _firmar(
        sub: str = "user_ana",
        *,
        iss: str | None = None,
        azp: str = "http://localhost:4200",
        omitir_azp: bool = False,
        aud: str | None = None,
        omitir_aud: bool = True,
        exp_delta: int = 3600,
        nbf_delta: int = -5,
        algoritmo: str = "RS256",
        clave: object | None = None,
        kid: str | None = None,
    ) -> str:
        ahora = int(time.time())
        claims = {
            "sub": sub,
            "iss": iss if iss is not None else emisor,
            "iat": ahora,
            "nbf": ahora + nbf_delta,
            "exp": ahora + exp_delta,
        }
        if not omitir_azp:
            claims["azp"] = azp
        if not omitir_aud and aud is not None:
            claims["aud"] = aud
        return jwt.encode(
            claims,
            clave if clave is not None else par_de_claves.privada,
            algorithm=algoritmo,
            headers={"kid": kid if kid is not None else par_de_claves.kid},
        )

    return _firmar


# ---------------------------------------------------------------------------
# Cliente HTTP con las costuras de autenticacion inyectadas
# ---------------------------------------------------------------------------


@contextmanager
def _cliente_con_overrides(motor, overrides: dict):
    FabricaSesion = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def obtener_db_de_prueba():
        db = FabricaSesion()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = obtener_db_de_prueba
    app.dependency_overrides.update(overrides)
    try:
        with TestClient(app) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_auth(
    motor,
    monkeypatch,
    emisor: str,
    fuente_jwks_simulada: FuenteJWKSSimulada,
    transporte_clerk: httpx.MockTransport,
):
    """Cliente con JWKS y transporte Clerk inyectados, sin salir a la red.

    Los overrides solo se registran si la costura ya existe: mientras T3/T4 no la
    implementen, los tests fallan por su propia asercion (404/200 esperado vs
    real), no por una fixture rota.
    """
    monkeypatch.setattr(settings, "CLERK_ISSUER", emisor)
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_valor_falso")

    overrides = {}
    if hasattr(dependencies, "obtener_fuente_jwks"):
        overrides[dependencies.obtener_fuente_jwks] = lambda: fuente_jwks_simulada
    if hasattr(dependencies, "obtener_transporte_clerk"):
        overrides[dependencies.obtener_transporte_clerk] = lambda: transporte_clerk

    with _cliente_con_overrides(motor, overrides) as cliente_http:
        yield cliente_http


@pytest.fixture
def cliente(motor):
    """Cliente sin override de identidad: proteccion real (T2/T7).

    `conftest.py` inyecta una identidad legacy en su fixture `cliente` para que
    la suite funcional siga operando bajo el router protegido. Las pruebas de
    este modulo que validan 401/seguridad no deben heredar ese override: este
    fixture de modulo lo sombrea dejando solo `get_db` redirigido, de modo que
    la ausencia de Bearer siga devolviendo 401 de verdad.
    """
    with _cliente_con_overrides(motor, {}) as cliente_http:
        yield cliente_http


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _cuerpo_happy(datos_base: dict, respuesta_clerk: dict) -> None:
    respuesta_clerk["cuerpo"] = cuerpo_clerk(datos_base["correo_usado"])


# ---------------------------------------------------------------------------
# Contrato de costuras inyectables
# ---------------------------------------------------------------------------


def test_costura_inyectable_de_autenticacion_existe():
    """Las costuras JWKS y transporte Clerk deben ser overrideables (AC-13)."""
    faltantes = [
        nombre
        for nombre in ("obtener_fuente_jwks", "obtener_transporte_clerk")
        if not hasattr(dependencies, nombre)
    ]
    if faltantes:
        pytest.fail(
            "Contrato pendiente (T4): app.api.dependencies debe exponer la(s) costura(s) "
            + ", ".join(faltantes)
            + " para inyectar JWKS/transporte sin red en los tests."
        )


# ---------------------------------------------------------------------------
# Validacion JWT: firma, emisor, vigencia, algoritmo, azp, aud (AC-5)
# ---------------------------------------------------------------------------


def test_token_valido_responde_200(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 200, respuesta.text


def test_firma_invalida_responde_401(
    cliente_auth, datos_base, respuesta_clerk, firmar_token, clave_intrusa
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    # El `kid` apunta a la clave legitima, pero la firma la hizo otra clave.
    token = firmar_token(clave=clave_intrusa.privada)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_iss_incorrecto_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(iss="https://otro.clerk.test")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_iss_igual_al_emisor_responde_200(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 200, respuesta.text


def test_token_expirado_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(exp_delta=-3600)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_token_antes_de_nbf_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(nbf_delta=3600)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_algoritmo_no_permitido_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    # HS256 con un secreto falso: fuera de la allowlist (RS256).
    token = firmar_token(algoritmo="HS256", clave="secreto-de-prueba")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_azp_ausente_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(omitir_azp=True)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


def test_azp_no_permitido_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(azp="http://localhost:9999")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("azp", AZP_PERMITIDOS)
def test_azp_permitido_responde_200(cliente_auth, datos_base, respuesta_clerk, firmar_token, azp):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(azp=azp)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 200, respuesta.text


def test_token_sin_aud_no_se_exige_responde_200(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    """El token de sesion de Clerk no define audiencia de API: no se exige `aud`."""
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token(omitir_aud=True)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 200, respuesta.text


# ---------------------------------------------------------------------------
# JWKS: kid, rotacion y cache con TTL (AC-5, AC-13)
# ---------------------------------------------------------------------------


def test_jwks_se_cachea_y_no_refresca_dentro_del_ttl(
    cliente_auth, datos_base, respuesta_clerk, firmar_token, fuente_jwks_simulada
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token()
    assert cliente_auth.get(RUTA_ME, headers=_auth(token)).status_code == 200
    assert cliente_auth.get(RUTA_ME, headers=_auth(token)).status_code == 200
    assert fuente_jwks_simulada.llamadas == 1, "el JWKS debe servirse desde cache"


def test_kid_desconocido_fuerza_refresco_y_valida(
    cliente_auth, datos_base, respuesta_clerk, firmar_token, fuente_jwks_simulada
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    assert cliente_auth.get(RUTA_ME, headers=_auth(firmar_token())).status_code == 200

    clave_rotada = _generar_par("kid-rotado")
    fuente_jwks_simulada.agregar(clave_rotada.jwks["keys"][0])
    token_rotado = firmar_token(kid=clave_rotada.kid, clave=clave_rotada.privada)

    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token_rotado))
    assert respuesta.status_code == 200, respuesta.text
    assert fuente_jwks_simulada.llamadas == 2, "un `kid` nuevo debe forzar un unico refresco"


def test_kid_desconocido_ausente_en_jwks_responde_401(
    cliente_auth, datos_base, respuesta_clerk, firmar_token, fuente_jwks_simulada
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    assert cliente_auth.get(RUTA_ME, headers=_auth(firmar_token())).status_code == 200

    token = firmar_token(kid="kid-fantasma")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(token))
    assert respuesta.status_code == 401, respuesta.text
    assert fuente_jwks_simulada.llamadas == 2, "un `kid` desconocido debe refrescar una sola vez"


def test_jwks_refresca_al_vencer_el_ttl(
    cliente_auth, datos_base, respuesta_clerk, firmar_token, fuente_jwks_simulada, monkeypatch
):
    try:
        from app.core import security as modulo_seguridad
    except ImportError:
        pytest.fail("Contrato pendiente (T3): falta app.core.security para validar JWKS.")
    if not hasattr(modulo_seguridad, "TTL_JWKS_SEGUNDOS"):
        pytest.fail(
            "Contrato pendiente (T3): core.security debe exponer TTL_JWKS_SEGUNDOS "
            "para poder probar la caducidad de la cache JWKS."
        )

    _cuerpo_happy(datos_base, respuesta_clerk)
    token = firmar_token()
    assert cliente_auth.get(RUTA_ME, headers=_auth(token)).status_code == 200

    monkeypatch.setattr(modulo_seguridad, "TTL_JWKS_SEGUNDOS", 0)
    assert cliente_auth.get(RUTA_ME, headers=_auth(token)).status_code == 200
    assert fuente_jwks_simulada.llamadas == 2, "al vencer el TTL debe redescargarse el JWKS"


# ---------------------------------------------------------------------------
# Consulta al Backend API de Clerk: correo primario y verificacion (AC-6)
# ---------------------------------------------------------------------------


def test_correo_primario_verificado_vincula_usuario(
    cliente_auth, datos_base, respuesta_clerk, firmar_token
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["usuario_id"] == datos_base["usuario_id"]


def test_correo_no_verificado_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    respuesta_clerk["cuerpo"] = cuerpo_clerk(datos_base["correo_usado"], verificado=False)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 401, respuesta.text


def test_correo_no_coincidente_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    respuesta_clerk["cuerpo"] = cuerpo_clerk("ajeno@compustock.cl")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 401, respuesta.text


def test_correo_primario_ausente_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    respuesta_clerk["cuerpo"] = cuerpo_clerk(datos_base["correo_usado"], primario=False)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 401, respuesta.text


def test_fallo_del_backend_api_responde_401(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    respuesta_clerk["estado"] = 500
    respuesta_clerk["cuerpo"] = {"error": "interno"}
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 401, respuesta.text


def test_error_de_red_del_backend_api_responde_401(
    cliente_auth, datos_base, respuesta_clerk, firmar_token
):
    respuesta_clerk["excepcion"] = httpx.ConnectError("sin conexion")
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 401, respuesta.text


# ---------------------------------------------------------------------------
# GET /auth/me (AC-8, AC-9)
# ---------------------------------------------------------------------------


def test_auth_me_devuelve_usuario_id_y_sub(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token(sub="user_clerk_validado")))
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["usuario_id"] == datos_base["usuario_id"]
    assert cuerpo["sub"] == "user_clerk_validado"


def test_auth_me_sin_bearer_responde_401(cliente_auth, datos_base):
    respuesta = cliente_auth.get(RUTA_ME)
    assert respuesta.status_code == 401, respuesta.text


def test_auth_me_con_bearer_invalido_responde_401(cliente_auth, datos_base):
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth("no-es-un-jwt"))
    assert respuesta.status_code == 401, respuesta.text


def test_auth_me_devuelve_identidad_local_completa(
    cliente_auth, datos_base, respuesta_clerk, firmar_token
):
    """AC-8: la identidad resuelta incluye los seis campos locales y `sub`."""
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token(sub="user_clerk_validado")))
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["usuario_id"] == datos_base["usuario_id"]
    assert cuerpo["sub"] == "user_clerk_validado"
    assert cuerpo["nombre"] == "Ana"
    assert cuerpo["apellido"] == "Perez"
    assert cuerpo["correo"] == datos_base["correo_usado"]
    # `rol` es el valor legible de la relacion `Rol` del usuario local.
    assert cuerpo["rol"] == datos_base["rol_nombre"]


def test_auth_me_no_expone_rol_id(cliente_auth, datos_base, respuesta_clerk, firmar_token):
    """AC-8: el contrato no incluye `rol_id`; solo el nombre legible del rol."""
    _cuerpo_happy(datos_base, respuesta_clerk)
    respuesta = cliente_auth.get(RUTA_ME, headers=_auth(firmar_token()))
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert "rol_id" not in cuerpo
    assert set(cuerpo) == {"usuario_id", "sub", "nombre", "apellido", "correo", "rol"}


def test_identidad_no_resoluble_responde_401_sin_datos_ni_mutacion(motor, datos_base):
    """AC-9: si el usuario o su rol no se resuelven, 401 sin datos ni mutaciones.

    Se inyecta una identidad valida en forma pero cuyo `usuario_id` no existe en
    la base; el enriquecimiento del endpoint no puede resolverla y responde 401
    sin exponer identidad parcial y sin crear ni modificar filas de usuario.
    """
    usuario_huerfano = Usuario(
        usuario_id=999999,
        nombre="Fantasma",
        apellido="Ausente",
        correo="fantasma@compustock.cl",
        password="no-usada-por-clerk",
        departamento_id=datos_base["departamento_id"],
        rol_id=datos_base["rol_id"],
    )
    identidad = IdentidadAutenticada(usuario=usuario_huerfano, sub="user_huerfano")
    overrides = {dependencies.get_current_user: lambda: identidad}

    with _cliente_con_overrides(motor, overrides) as cliente_http:
        respuesta = cliente_http.get(RUTA_ME)
        assert respuesta.status_code == 401, respuesta.text
        cuerpo = respuesta.json()
        campos_identidad = {"usuario_id", "nombre", "apellido", "correo", "rol"}
        assert not (campos_identidad & set(cuerpo)), cuerpo

        listado = cliente_http.get("/api/v1/usuarios/")
        assert listado.status_code == 200, listado.text
        usuarios = listado.json()
        correos = {usuario["correo"] for usuario in usuarios}
        assert "fantasma@compustock.cl" not in correos, "no debe crearse un usuario nuevo"
        assert len(usuarios) == 1, "la resolucion fallida no debe alterar la tabla usuario"


# ---------------------------------------------------------------------------
# Proteccion de rutas de negocio (AC-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", RUTAS_NEGOCIO)
def test_ruta_de_negocio_sin_bearer_responde_401(cliente, ruta):
    respuesta = cliente.get(ruta)
    assert respuesta.status_code == 401, respuesta.text


def test_ruta_de_negocio_con_bearer_valido_responde_200(
    cliente_auth, datos_base, respuesta_clerk, firmar_token
):
    _cuerpo_happy(datos_base, respuesta_clerk)
    # Guarda de la proteccion: si sin Bearer tambien respondiera 200, este test
    # pasaria en verde aunque no hubiera autenticacion real.
    assert cliente_auth.get("/api/v1/tickets/").status_code == 401
    respuesta = cliente_auth.get("/api/v1/tickets/", headers=_auth(firmar_token()))
    assert respuesta.status_code == 200, respuesta.text


# ---------------------------------------------------------------------------
# OpenAPI: securityScheme y contrato (AC-11)
# ---------------------------------------------------------------------------


#: Metodos que OpenAPI usa como llaves de operacion dentro de un path item.
METODOS_HTTP = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "trace"})


def _esquemas_de_seguridad(esquema: dict) -> dict:
    return esquema.get("components", {}).get("securitySchemes", {})


def _nombres_bearer(esquema: dict) -> set[str]:
    """Nombres de los securityScheme publicados que son HTTP bearer."""
    return {
        nombre
        for nombre, definicion in _esquemas_de_seguridad(esquema).items()
        if definicion.get("type") == "http" and definicion.get("scheme") == "bearer"
    }


def _hay_bearer(esquema: dict) -> bool:
    return bool(_nombres_bearer(esquema))


def _operaciones(esquema: dict):
    """Itera `(ruta, metodo, operacion)` de todas las operaciones del contrato."""
    for ruta, item in esquema["paths"].items():
        for metodo, operacion in item.items():
            if metodo in METODOS_HTTP:
                yield ruta, metodo, operacion


def _exige_bearer(esquema: dict, operacion: dict) -> bool:
    """La operacion exige en `security` uno de los esquemas HTTP bearer publicados."""
    nombres = _nombres_bearer(esquema)
    requisitos = operacion.get("security") or []
    return any(nombre in requisito for requisito in requisitos for nombre in nombres)


def test_openapi_publica_esquema_bearer(cliente):
    esquema = cliente.get("/openapi.json").json()
    assert _hay_bearer(esquema), "el contrato debe publicar un securityScheme HTTP bearer"


def test_openapi_toda_operacion_de_negocio_exige_bearer(cliente):
    """Cada operacion bajo `/api/v1` (negocio, incluida `/auth/me`) exige bearer."""
    esquema = cliente.get("/openapi.json").json()
    assert _hay_bearer(esquema)
    sin_seguridad = [
        f"{metodo.upper()} {ruta}"
        for ruta, metodo, operacion in _operaciones(esquema)
        if ruta.startswith("/api/v1") and not _exige_bearer(esquema, operacion)
    ]
    assert not sin_seguridad, f"operaciones de negocio sin seguridad bearer: {sin_seguridad}"


@pytest.mark.parametrize("ruta", RUTAS_NEGOCIO)
def test_openapi_marca_operaciones_de_negocio_protegidas(cliente, ruta):
    esquema = cliente.get("/openapi.json").json()
    assert _hay_bearer(esquema)
    item = esquema["paths"][ruta]
    operaciones = {metodo: op for metodo, op in item.items() if metodo in METODOS_HTTP}
    assert operaciones, f"la ruta {ruta} no publica operaciones"
    for metodo, operacion in operaciones.items():
        assert _exige_bearer(esquema, operacion), f"{metodo.upper()} {ruta} debe exigir bearer"


def test_openapi_auth_me_exige_bearer(cliente):
    esquema = cliente.get("/openapi.json").json()
    operacion = esquema["paths"][RUTA_ME]["get"]
    assert _exige_bearer(esquema, operacion)


def test_openapi_salud_no_requiere_seguridad_y_publica_bearer(cliente):
    esquema = cliente.get("/openapi.json").json()
    # Se combina con la publicacion del esquema para que este caso no pase en
    # verde mientras el contrato siga incompleto.
    assert _hay_bearer(esquema)
    assert not esquema["paths"]["/health"]["get"].get("security")


@pytest.mark.parametrize("ruta", ["/health", "/docs", "/openapi.json"])
def test_openapi_rutas_tecnicas_no_exigen_bearer(cliente, ruta):
    """Salud y documentacion no aparecen como operaciones protegidas (AC-10/AC-11)."""
    esquema = cliente.get("/openapi.json").json()
    item = esquema["paths"].get(ruta, {})
    for metodo, operacion in item.items():
        if metodo in METODOS_HTTP:
            assert not operacion.get("security"), f"{metodo.upper()} {ruta} no debe exigir seguridad"


def test_salud_documentacion_y_contrato_accesibles_sin_token(cliente):
    """Salud, Swagger UI y el propio contrato responden sin Bearer (AC-10)."""
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_openapi_auth_me_documenta_200_y_401(cliente):
    esquema = cliente.get("/openapi.json").json()
    ruta = esquema["paths"].get(RUTA_ME)
    assert ruta is not None, "debe existir la operacion GET /api/v1/auth/me en el contrato"
    operacion = ruta["get"]
    assert "200" in operacion["responses"]
    assert "401" in operacion["responses"]
    assert operacion.get("security"), "/auth/me debe exigir el esquema bearer"


def test_openapi_auth_me_declara_response_model_explicito(cliente):
    """El 200 referencia el DTO `IdentidadAutenticadaRespuesta` completo (AC-8/AC-11).

    Publica los seis campos de la identidad local y no publica `rol_id`.
    """
    esquema = cliente.get("/openapi.json").json()
    operacion = esquema["paths"][RUTA_ME]["get"]
    referencia = operacion["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    nombre = referencia.rsplit("/", 1)[-1]
    assert nombre == "IdentidadAutenticadaRespuesta"
    dto = esquema["components"]["schemas"][nombre]
    campos = {"usuario_id", "sub", "nombre", "apellido", "correo", "rol"}
    assert campos <= set(dto["properties"])
    assert campos <= set(dto.get("required", []))
    assert "rol_id" not in dto["properties"], "el contrato no debe publicar `rol_id`"


def test_openapi_auth_me_documenta_401_con_descripcion(cliente):
    """El 401 esta documentado y descrito, sin filtrar la causa interna (AC-11)."""
    esquema = cliente.get("/openapi.json").json()
    operacion = esquema["paths"][RUTA_ME]["get"]
    respuesta_401 = operacion["responses"]["401"]
    assert respuesta_401.get("description")
