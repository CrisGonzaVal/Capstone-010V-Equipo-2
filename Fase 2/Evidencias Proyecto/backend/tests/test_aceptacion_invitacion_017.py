"""Feature 017, T5: aceptacion idempotente de invitacion en el primer login.

Seam bajo prueba: `app.services.auth_service` sobre SQLite en memoria. Fija la
decision D-3 y los criterios AC-4/AC-16:

  * un login verificado con asociacion activa y estado `pendiente` persiste
    `aceptada` una sola vez (`invitacion_aceptada_en` fijado);
  * repetir el login no reescribe ni falla (idempotente);
  * un estado terminal (`aceptada`, `revocada`, `expirada`) no vuelve a
    `pendiente` ni se reescribe;
  * una asociacion inactiva nunca se reactiva ni se marca aceptada;
  * sin mapa de control o sin correo primario verificado no se marca nada;
  * la busqueda se hace con el correo normalizado (T4), no con el literal que
    devuelve Clerk;
  * dos logins consecutivos dejan un unico estado final aceptado sin error.

La carrera real de dos transacciones concurrentes se acredita en el modulo
gated `test_aceptacion_invitacion_postgres_017.py`; aqui se verifica la
idempotencia observable en el contexto logico unico de SQLite (AC-16).
"""

from __future__ import annotations

import httpx
import pytest

from app.core import security
from app.models import MapaUsuarioEsquema
from app.services import auth_service

CORREO = "ana.prueba@compustock.cl"
ESQUEMA_FICTICIO = "tenant_inst01_cafebabe"


@pytest.fixture
def sesion(motor):
    from sqlalchemy.orm import sessionmaker

    sesion_db = sessionmaker(bind=motor)()
    try:
        yield sesion_db
    finally:
        sesion_db.close()


def _agregar_mapa(
    sesion,
    correo: str = CORREO,
    *,
    estado: str | None = "pendiente",
    activo: bool = True,
) -> MapaUsuarioEsquema:
    mapa = MapaUsuarioEsquema(
        correo=correo,
        institucion_id="INST01",
        nombre_esquema=ESQUEMA_FICTICIO,
        activo=activo,
        estado_invitacion=estado,
    )
    sesion.add(mapa)
    sesion.commit()
    return mapa


def _payload_clerk(correo: str, *, verificado: bool = True) -> dict:
    return {
        "id": "user_017",
        "primary_email_address_id": "idn_primario",
        "email_addresses": [
            {
                "id": "idn_primario",
                "email_address": correo,
                "verification": {
                    "status": "verified" if verificado else "unverified"
                },
            }
        ],
    }


def _transporte(correo: str, *, verificado: bool = True) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda _peticion: httpx.Response(200, json=_payload_clerk(correo, verificado=verificado))
    )


def _login(monkeypatch, sesion, transporte: httpx.BaseTransport):
    """Ejecuta `resolver_identidad` con la validacion JWT sustituida, sin red."""
    monkeypatch.setattr(
        security, "validar_token", lambda _token, _issuer, _fuente: {"sub": "user_017"}
    )
    return auth_service.resolver_identidad(
        token="token-de-prueba",
        issuer="https://clerk.test",
        fuente_jwks=lambda _issuer: {"keys": []},
        secret_key="sk_test_falso",
        transport=transporte,
        db=sesion,
    )


def _mapa_refrescado(sesion, correo: str = CORREO) -> MapaUsuarioEsquema | None:
    sesion.expire_all()
    return sesion.get(MapaUsuarioEsquema, correo)


# ---------------------------------------------------------------------------
# Transicion condicional e idempotencia (D-3, AC-4)
# ---------------------------------------------------------------------------


def test_primer_login_pendiente_pasa_a_aceptada(datos_base, sesion, monkeypatch):
    mapa = _agregar_mapa(sesion)

    identidad = _login(monkeypatch, sesion, _transporte(CORREO))

    assert identidad.usuario.correo == CORREO
    actualizado = _mapa_refrescado(sesion)
    assert actualizado.estado_invitacion == "aceptada"
    assert actualizado.invitacion_aceptada_en is not None
    assert mapa.activo is True


def test_mismo_login_repetido_es_idempotente(datos_base, sesion, monkeypatch):
    _agregar_mapa(sesion)
    _login(monkeypatch, sesion, _transporte(CORREO))
    primero = _mapa_refrescado(sesion).invitacion_aceptada_en

    _login(monkeypatch, sesion, _transporte(CORREO))
    segundo = _mapa_refrescado(sesion).invitacion_aceptada_en

    assert segundo == primero


@pytest.mark.parametrize("estado", ["aceptada", "revocada", "expirada"])
def test_estado_terminal_no_cambia_por_login(estado, datos_base, sesion, monkeypatch):
    _agregar_mapa(sesion, estado=estado)

    _login(monkeypatch, sesion, _transporte(CORREO))

    actualizado = _mapa_refrescado(sesion)
    assert actualizado.estado_invitacion == estado
    assert actualizado.invitacion_aceptada_en is None


def test_mapa_inactivo_no_se_reactiva_ni_acepta(datos_base, sesion, monkeypatch):
    _agregar_mapa(sesion, activo=False)

    identidad = _login(monkeypatch, sesion, _transporte(CORREO))

    assert identidad.usuario.correo == CORREO
    actualizado = _mapa_refrescado(sesion)
    assert actualizado.activo is False
    assert actualizado.estado_invitacion == "pendiente"
    assert actualizado.invitacion_aceptada_en is None


def test_sin_mapa_no_marca_nada(datos_base, sesion, monkeypatch):
    identidad = _login(monkeypatch, sesion, _transporte(CORREO))

    assert identidad.usuario.correo == CORREO
    assert _mapa_refrescado(sesion) is None


def test_correo_no_verificado_no_marca_nada(datos_base, sesion, monkeypatch):
    _agregar_mapa(sesion)

    with pytest.raises(security.ErrorAutenticacion):
        _login(monkeypatch, sesion, _transporte(CORREO, verificado=False))

    actualizado = _mapa_refrescado(sesion)
    assert actualizado.estado_invitacion == "pendiente"
    assert actualizado.invitacion_aceptada_en is None


def test_marca_solo_con_el_correo_normalizado(datos_base, sesion, monkeypatch):
    """Clerk devuelve el correo con espacios/mayusculas; el mapa usa el canonico."""
    _agregar_mapa(sesion, correo=CORREO)

    _login(monkeypatch, sesion, _transporte("  Ana.Prueba@CompuStock.CL "))

    actualizado = _mapa_refrescado(sesion)
    assert actualizado.estado_invitacion == "aceptada"
    assert actualizado.invitacion_aceptada_en is not None


def test_dos_logins_consecutivos_dejan_una_sola_aceptacion(datos_base, sesion, monkeypatch):
    _agregar_mapa(sesion)

    _login(monkeypatch, sesion, _transporte(CORREO))
    primero = _mapa_refrescado(sesion).invitacion_aceptada_en
    _login(monkeypatch, sesion, _transporte(CORREO))

    sesion.expire_all()
    filas = sesion.query(MapaUsuarioEsquema).all()
    assert len(filas) == 1
    assert filas[0].estado_invitacion == "aceptada"
    assert filas[0].invitacion_aceptada_en == primero
