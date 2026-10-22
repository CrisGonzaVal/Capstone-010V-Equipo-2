"""Feature 017, T5: aceptacion idempotente del primer login en PostgreSQL 16 - gated.

Complemento gated de `test_aceptacion_invitacion_017.py`. Solo PostgreSQL tiene
transacciones reales sobre `control.mapa_usuario_esquema`, asi que aqui se
acreditan los escenarios de AC-4/AC-16 que SQLite no puede reproducir:

  * dos primeros logins **concurrentes** con la misma asociacion `pendiente` y
    activa finalizan ambos autenticados (HTTP 200) sin error por carrera, y el
    estado persistido queda `aceptada` una sola vez (una fila, un timestamp);
  * una asociacion local inactiva conserva `activo = False` y su estado
    `pendiente` (la aceptacion nunca reactiva el mapa) y el login responde 401
    porque la identidad no resuelve a tenant.

COMO ACTIVARLAS
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_aceptacion_invitacion_postgres_017.py

Sin `POSTGRES_TEST_URL` los tests se **saltan**. La URL apunta a una base de
mantenimiento donde el test crea y DESTRUYE bases temporales propias; nunca toca
`apt_erp`. No se anade ninguna dependencia nueva.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from app.api import dependencies
from app.core.config import settings
from app.db.database import crear_sesion_control
from app.main import app
from app.models import MapaUsuarioEsquema

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMA_SQL = RAIZ / "database" / "01_esquema.sql"
SEMILLA_SQL = RAIZ / "database" / "02_datos_semilla.sql"

RUTA_ME = "/api/v1/auth/me"


# ---------------------------------------------------------------------------
# Base temporal y utilidades
# ---------------------------------------------------------------------------


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


@contextmanager
def _base_temporal():
    """Crea una base desechable, instala 01+02 y devuelve su URL SQLAlchemy."""
    dsn = (_POSTGRES_TEST_URL or "").replace("postgresql+psycopg2://", "postgresql://")
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_017login_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    componentes = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        conexion = psycopg2.connect(componentes)
        try:
            with conexion.cursor() as cur:
                cur.execute(ESQUEMA_SQL.read_text(encoding="utf-8"))
                cur.execute(SEMILLA_SQL.read_text(encoding="utf-8"))
            conexion.commit()
        finally:
            conexion.close()
        yield _url_sqlalchemy(componentes)
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _mapa_de_tenant(engine) -> tuple[str, str]:
    """Correo y esquema de una asociacion tenant sembrada (nunca Superadmin)."""
    sesion = crear_sesion_control(engine)
    try:
        fila = sesion.execute(
            select(MapaUsuarioEsquema.correo, MapaUsuarioEsquema.nombre_esquema)
            .where(MapaUsuarioEsquema.nombre_esquema != "control")
            .order_by(MapaUsuarioEsquema.correo)
        ).first()
        assert fila is not None, "la semilla no contiene asociaciones tenant"
        return fila[0], fila[1]
    finally:
        sesion.close()


def _preparar_mapa(engine, correo: str, *, activo: bool = True) -> None:
    sesion = crear_sesion_control(engine)
    try:
        mapa = sesion.get(MapaUsuarioEsquema, correo)
        assert mapa is not None
        mapa.estado_invitacion = "pendiente"
        mapa.invitacion_aceptada_en = None
        mapa.activo = activo
        sesion.commit()
    finally:
        sesion.close()


def _leer_mapa(engine, correo: str) -> tuple[str | None, bool, object]:
    sesion = crear_sesion_control(engine)
    try:
        mapa = sesion.get(MapaUsuarioEsquema, correo)
        assert mapa is not None
        return mapa.estado_invitacion, mapa.activo, mapa.invitacion_aceptada_en
    finally:
        sesion.close()


# ---------------------------------------------------------------------------
# Token real (clave RSA efimera) y frontera Clerk simulada
# ---------------------------------------------------------------------------


def _jwt_utilidades() -> tuple[object, dict, str]:
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publica = privada.public_key()
    jwk = json.loads(RSAAlgorithm.to_jwk(publica))
    jwk.update({"kid": "kid-017-login", "use": "sig", "alg": "RS256"})
    return privada, {"keys": [jwk]}, jwk["kid"]


def _firmar(privada, emisor: str, kid: str) -> str:
    ahora = int(time.time())
    return jwt.encode(
        {
            "sub": "user_017_login",
            "iss": emisor,
            "iat": ahora,
            "nbf": ahora - 5,
            "exp": ahora + 3600,
            "azp": "http://localhost:4200",
        },
        privada,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _payload_correo(correo: str) -> dict:
    return {
        "id": "user_017_login",
        "primary_email_address_id": "idn_primario",
        "email_addresses": [
            {
                "id": "idn_primario",
                "email_address": correo,
                "verification": {"status": "verified"},
            }
        ],
    }


@contextmanager
def _cliente(
    engine,
    *,
    emisor: str,
    jwks: dict,
    correo: str,
    barrera: threading.Barrier | None = None,
):
    """TestClient real con JWKS/transporte Clerk inyectados; sin red externa."""
    def _db_de_prueba():
        sesion = crear_sesion_control(engine)
        try:
            yield sesion
        finally:
            sesion.close()

    def _manejador(_peticion: httpx.Request) -> httpx.Response:
        if barrera is not None:
            # Sincroniza ambos primeros logins justo antes de la escritura
            # condicional: es la ventana de carrera que AC-16 exige cubrir.
            barrera.wait(timeout=15)
        return httpx.Response(200, json=_payload_correo(correo))

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.obtener_fuente_jwks] = lambda: (
        lambda _issuer: jwks
    )
    app.dependency_overrides[dependencies.obtener_transporte_clerk] = lambda: (
        httpx.MockTransport(_manejador)
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC-4 / AC-16: dos primeros logins concurrentes
# ---------------------------------------------------------------------------


def test_dos_primeros_logins_concurrentes_dejan_un_unico_aceptada(monkeypatch):
    with _base_temporal() as url:
        engine = create_engine(url)
        try:
            correo, _esquema = _mapa_de_tenant(engine)
            _preparar_mapa(engine, correo)

            privada, jwks, kid = _jwt_utilidades()
            emisor = f"https://clerk.test/{uuid4().hex}"
            monkeypatch.setattr(settings, "CLERK_ISSUER", emisor)
            monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_falso")
            token = _firmar(privada, emisor, kid)

            barrera = threading.Barrier(2)
            respuestas: list[int] = []
            errores: list[BaseException] = []

            with _cliente(
                engine, emisor=emisor, jwks=jwks, correo=correo, barrera=barrera
            ) as cliente:
                def _login() -> None:
                    try:
                        respuesta = cliente.get(
                            RUTA_ME, headers={"Authorization": f"Bearer {token}"}
                        )
                        respuestas.append(respuesta.status_code)
                    except BaseException as exc:  # noqa: BLE001 - se reporta abajo
                        errores.append(exc)

                hilos = [threading.Thread(target=_login) for _ in range(2)]
                for hilo in hilos:
                    hilo.start()
                for hilo in hilos:
                    hilo.join(timeout=60)

            assert not errores, errores
            assert sorted(respuestas) == [200, 200], respuestas

            estado, activo, aceptada_en = _leer_mapa(engine, correo)
            assert estado == "aceptada"
            assert activo is True
            assert aceptada_en is not None
        finally:
            engine.dispose()


def test_mapa_inactivo_conserva_inactividad_y_pendiente(monkeypatch):
    with _base_temporal() as url:
        engine = create_engine(url)
        try:
            correo, _esquema = _mapa_de_tenant(engine)
            _preparar_mapa(engine, correo, activo=False)

            privada, jwks, kid = _jwt_utilidades()
            emisor = f"https://clerk.test/{uuid4().hex}"
            monkeypatch.setattr(settings, "CLERK_ISSUER", emisor)
            monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_falso")
            token = _firmar(privada, emisor, kid)

            with _cliente(engine, emisor=emisor, jwks=jwks, correo=correo) as cliente:
                respuesta = cliente.get(
                    RUTA_ME, headers={"Authorization": f"Bearer {token}"}
                )

            assert respuesta.status_code == 401, respuesta.text
            estado, activo, aceptada_en = _leer_mapa(engine, correo)
            assert estado == "pendiente"
            assert activo is False
            assert aceptada_en is None
        finally:
            engine.dispose()
