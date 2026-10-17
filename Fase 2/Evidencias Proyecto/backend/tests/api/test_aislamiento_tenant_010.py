"""Cierre de AC-3 (Feature 010): inyeccion adversarial de tenant por los cuatro canales.

T14 dejo registrado que el AC-3 no tenia una prueba que **intentara** envenenar la
resolucion de tenant; solo la evidencia de que no existe canal (la API de
resolucion no lo acepta) y de que el DTO lo prohibe. Este modulo cierra ese hueco
con pruebas que **envian Tenant B** por los cuatro canales que nombra el AC y
comprueban que la resolucion no se contamina:

  * **query**: parametros que la ruta no declara (`nombre_esquema`, `tenant`,
    `institucion_id`, `schema`) se ignoran; la respuesta es identica a la linea
    base y solo contiene datos de Tenant A.
  * **cabecera**: `X-Tenant`, `X-Schema`, `X-Institucion`, `X-Nombre-Esquema` se
    ignoran por igual.
  * **cuerpo**: un DTO de negocio sin `institucion_id` (`ProductoCrear`) ignora el
    campo enviado y ancla la fila a la institucion de la identidad (A); el DTO de
    control, con `extra="forbid"`, **rechaza** los campos de tenant con `422`.
  * **claim/token**: un JWT valido con claims adversariales (`institucion_id`,
    `nombre_esquema`, `tenant`) no cambia la identidad resuelta: esta sale del
    correo primario verificado que entrega Clerk, no del token.

Seam bajo prueba: la **interfaz HTTP real** (`TestClient` sobre `app.main.app`) y,
para el canal de claim, la frontera Clerk real con JWKS/transporte mock (nunca
red). SQLite en memoria usa un contexto logico unico (AC-16): alli no hay
namespaces que seleccionar, por lo que la garantia observable es que la
institucion del resultado sigue siendo la de la identidad A y que el canal no
altera nada. La prueba de aislamiento con dos esquemas reales vive en la suite
gated de PostgreSQL (`tests/test_integracion_multitenant_010.py`).
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
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import config
from app.core.config import settings
from app.main import app
from app.models import MapaUsuarioEsquema, Producto, Rol, Usuario, VersionEsquema
from app.services.auth_service import IdentidadAutenticada

#: Rutas de negocio usadas como vehiculo (endpoint existente) y de control.
RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"
RUTA_PRODUCTOS = "/api/v1/inventario/productos"
RUTA_ALTA_CONTROL = "/api/v1/control/instituciones/"

#: Esquemas de dos tenants distintos. El de Tenant B nunca debe aparecer en el
#: resultado de una identidad de Tenant A.
ESQUEMA_A = "tenant_inst01_deadbeef"
ESQUEMA_B = "tenant_inst02_cafebabe"

#: Correos de las dos identidades: A (rol limitado de INST01) y B (INST02).
CORREO_A = "ana.prueba@compustock.cl"
CORREO_B = "administrador.inst02@compustock.cl"

#: Parametros/cabeceras adversariales que se intentan inyectar (Tenant B).
PARAMS_ADVERSARIOS = {
    "nombre_esquema": ESQUEMA_B,
    "tenant": "INST02",
    "institucion_id": "INST02",
    "schema": ESQUEMA_B,
}
CABECERAS_ADVERSARIAS = {
    "X-Tenant": "INST02",
    "X-Schema": ESQUEMA_B,
    "X-Institucion": "INST02",
    "X-Nombre-Esquema": ESQUEMA_B,
}


# ---------------------------------------------------------------------------
# Fixtures: mapa de dos tenants y cliente HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def mundo(dos_instituciones, motor):
    """Dos instituciones con mapa `correo -> esquema` activo y version objetivo.

    Reutiliza `dos_instituciones` (INST01 propia / INST02 ajena, con catalogo y
    stock homonimos) y agrega lo que exige la resolucion de tenant: una fila
    activa del mapa para cada correo y la unica fila de version objetivo.
    """
    sesion = sessionmaker(bind=motor)()
    try:
        sesion.add_all(
            [
                MapaUsuarioEsquema(
                    correo=CORREO_A,
                    institucion_id=dos_instituciones["inst_propia"],
                    nombre_esquema=ESQUEMA_A,
                    activo=True,
                ),
                MapaUsuarioEsquema(
                    correo=CORREO_B,
                    institucion_id=dos_instituciones["inst_ajena"],
                    nombre_esquema=ESQUEMA_B,
                    activo=True,
                ),
            ]
        )
        sesion.add(VersionEsquema(version=config.VERSION_ESQUEMA_OBJETIVO))
        sesion.commit()
    finally:
        sesion.close()
    return dos_instituciones


def _identidad(correo: str, departamento_id: int, rol: str) -> IdentidadAutenticada:
    """Identidad autenticada de prueba, con el rol ya cargado (autorizacion)."""
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="AC3",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-aislamiento-010")


@contextmanager
def _cliente(motor, overrides: dict | None = None):
    """`TestClient` del `app` real con `get_db` en SQLite y overrides opcionales."""
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if overrides:
        app.dependency_overrides.update(overrides)
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


@contextmanager
def _cliente_como(motor, identidad: IdentidadAutenticada):
    """Cliente HTTP cuya identidad autenticada se fija a la de Tenant A."""
    with _cliente(motor, {dependencies.get_current_user: lambda: identidad}) as cliente:
        yield cliente


def _productos_por_nombre(motor, nombre: str, institucion_id: str) -> int:
    """Cuenta productos con ese nombre e institucion (para medir escrituras)."""
    sesion = sessionmaker(bind=motor)()
    try:
        return len(
            sesion.execute(
                select(Producto).where(
                    Producto.nombre == nombre,
                    Producto.institucion_id == institucion_id,
                )
            )
            .scalars()
            .all()
        )
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# AC-3 / canal 1: query
# ---------------------------------------------------------------------------


def test_query_adversarial_no_contamina_la_resolucion(motor, mundo):
    """Enviar Tenant B por query no altera el resultado de la identidad de A.

    La ruta no declara un parametro de tenant; los parametros sobrantes se
    ignoran y la respuesta es identica a la linea base. Mientras, la resolucion
    de control del correo A sigue devolviendo su propio esquema.
    """
    identidad = _identidad(CORREO_A, mundo["departamento_id"], "Administrador")
    with _cliente_como(motor, identidad) as cliente:
        base = cliente.get(RUTA_EXISTENCIAS)
        envenenado = cliente.get(RUTA_EXISTENCIAS, params=PARAMS_ADVERSARIOS)

    assert base.status_code == 200, base.text
    assert envenenado.status_code == 200, envenenado.text
    assert envenenado.json() == base.json(), "los parametros de tenant no deben alterar la respuesta"
    assert {fila["institucion_id"] for fila in base.json()} == {"INST01"}

    # La resolucion tampoco admite el canal: deriva del correo, no del query.
    from app.services import tenant_service

    sesion = sessionmaker(bind=motor)()
    try:
        resolucion = tenant_service.resolver_contexto_solicitud(sesion, CORREO_A)
    finally:
        sesion.close()
    assert resolucion.nombre_esquema == ESQUEMA_A


# ---------------------------------------------------------------------------
# AC-3 / canal 2: cabecera
# ---------------------------------------------------------------------------


def test_cabeceras_adversarias_no_contaminan_la_resolucion(motor, mundo):
    """Enviar Tenant B por cabeceras HTTP no altera el resultado de A."""
    identidad = _identidad(CORREO_A, mundo["departamento_id"], "Administrador")
    with _cliente_como(motor, identidad) as cliente:
        base = cliente.get(RUTA_EXISTENCIAS)
        envenenado = cliente.get(RUTA_EXISTENCIAS, headers=CABECERAS_ADVERSARIAS)

    assert base.status_code == 200, base.text
    assert envenenado.status_code == 200, envenenado.text
    assert envenenado.json() == base.json(), "las cabeceras de tenant no deben alterar la respuesta"
    assert {fila["institucion_id"] for fila in base.json()} == {"INST01"}


# ---------------------------------------------------------------------------
# AC-3 / canal 3: cuerpo
# ---------------------------------------------------------------------------


def test_cuerpo_de_negocio_no_puede_fijar_otra_institucion(motor, mundo):
    """Un campo `institucion_id` en el cuerpo se ignora: la fila es de A, no de B.

    `ProductoCrear` no declara `institucion_id` ni los campos de tenant; Pydantic
    los descarta y el servicio ancla la institucion a la identidad. Se comprueba
    que **no** se escribio ninguna fila en Tenant B.
    """
    identidad = _identidad(CORREO_A, mundo["departamento_id"], "Administrador")
    with _cliente_como(motor, identidad) as cliente:
        respuesta = cliente.post(
            RUTA_PRODUCTOS,
            json={
                "nombre": "Insumo Envenenado",
                "categoria_id": mundo["categoria_id"],
                **PARAMS_ADVERSARIOS,
            },
        )

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["institucion_id"] == "INST01", (
        "el producto debe pertenecer a la institucion de la identidad, no a la enviada"
    )
    assert _productos_por_nombre(motor, "Insumo Envenenado", "INST02") == 0, (
        "no debe escribirse nada en Tenant B"
    )
    assert _productos_por_nombre(motor, "Insumo Envenenado", "INST01") == 1


def test_dto_de_control_rechaza_campos_de_tenant(motor, mundo):
    """El DTO de control (`extra="forbid"`) rechaza los campos de tenant con 422.

    Es un rechazo limpio: ningun campo enviado por el cliente (esquema, version,
    rol o estado) se acepta y no queda ninguna institucion creada.
    """
    identidad = _identidad(CORREO_A, mundo["departamento_id"], "Superadmin")
    cuerpo = {
        "institucion_id": "INST09",
        "nombre": "Institucion Envenenada",
        "correo_administrador": "admin.envenenado@compustock.cl",
        "nombre_administrador": "Ada",
        "apellido_administrador": "Admin",
        "departamento_nombre_administrativo": "Administracion",
        **PARAMS_ADVERSARIOS,
        "version_esquema": "010.0",
        "rol": "Superadmin",
        "estado": "operativa",
    }
    with _cliente_como(motor, identidad) as cliente:
        respuesta = cliente.post(RUTA_ALTA_CONTROL, json=cuerpo)

    assert respuesta.status_code == 422, respuesta.text
    from app.models import Institucion

    sesion = sessionmaker(bind=motor)()
    try:
        assert sesion.get(Institucion, "INST09") is None
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# AC-3 / canal 4: claim no confiable del token
# ---------------------------------------------------------------------------


@dataclass
class ParClaves:
    privada: object
    publica: object
    kid: str
    jwks: dict


def _generar_par(kid: str) -> ParClaves:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publica = privada.public_key()
    jwk = json.loads(RSAAlgorithm.to_jwk(publica))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return ParClaves(privada=privada, publica=publica, kid=kid, jwks={"keys": [jwk]})


def _cuerpo_clerk(correo: str) -> dict:
    return {
        "id": "user_ac3",
        "primary_email_address_id": "idn_primario",
        "email_addresses": [
            {
                "id": "idn_primario",
                "email_address": correo,
                "verification": {"status": "verified"},
            }
        ],
    }


class FuenteJWKSSimulada:
    """Fuente JWKS inyectable para validar el JWT sin salir a la red."""

    def __init__(self, jwks: dict) -> None:
        self.jwks = jwks

    def __call__(self, _issuer: str) -> dict:
        return self.jwks


def test_claim_adversario_del_token_no_cambia_la_resolucion(motor, mundo, monkeypatch):
    """Un claim de tenant en el token no cambia la identidad ni el esquema de A.

    Se firma un JWT real cuyos claims declaran Tenant B (`institucion_id`,
    `nombre_esquema`, `tenant`), pero Clerk entrega el correo primario verificado
    de A. La identidad resuelta y su institucion efectiva son las de A: el token
    no selecciona el tenant. Se usa el mismo camino real de `get_current_user`
    (validacion de firma + consulta a Clerk mock), nunca un override de identidad.
    """
    par = _generar_par("kid-ac3")
    emisor = f"https://clerk.test/{uuid4().hex}"
    monkeypatch.setattr(settings, "CLERK_ISSUER", emisor)
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_valor_falso")

    def _transporte(_peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_cuerpo_clerk(CORREO_A))

    ahora = int(time.time())
    token = jwt.encode(
        {
            "sub": "user_ac3",
            "iss": emisor,
            "iat": ahora,
            "nbf": ahora - 5,
            "exp": ahora + 3600,
            "azp": "http://localhost:4200",
            # Claims adversariales: declaran Tenant B, que debe ignorarse.
            "institucion_id": "INST02",
            "nombre_esquema": ESQUEMA_B,
            "tenant": "INST02",
            "schema": ESQUEMA_B,
        },
        par.privada,
        algorithm="RS256",
        headers={"kid": par.kid},
    )

    overrides = {
        dependencies.obtener_fuente_jwks: lambda: FuenteJWKSSimulada(par.jwks),
        dependencies.obtener_transporte_clerk: lambda: httpx.MockTransport(_transporte),
    }
    with _cliente(motor, overrides) as cliente:
        respuesta = cliente.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["correo"] == CORREO_A, "la identidad sale del correo verificado"
    assert cuerpo["institucion"] == {
        "institucion_id": "INST01",
        "nombre": "Instituto de Prueba",
    }, "el claim de tenant no debe cambiar la institucion efectiva"

    # La resolucion de tenant del correo verificado sigue siendo la de A.
    from app.services import tenant_service

    sesion = sessionmaker(bind=motor)()
    try:
        resolucion = tenant_service.resolver_contexto_solicitud(sesion, CORREO_A)
    finally:
        sesion.close()
    assert resolucion.nombre_esquema == ESQUEMA_A
