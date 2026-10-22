"""Feature 017, T2: contrato de la frontera Clerk de invitaciones (AC-1, AC-2, AC-3, AC-6, AC-7).

Seam bajo prueba: las funciones publicas de `app.core.security` que T4
implementara y que los servicios de T6 orquestaran. Todo el trafico HTTP se
resuelve con un `httpx.BaseTransport` simulado que **registra** cada solicitud:
ninguna prueba toca la red ni usa credenciales reales.

Contrato que estas pruebas fijan (documentado aqui porque T4 lo implementa):

  * `security.normalizar_correo(correo) -> str`: recorta espacios al inicio/final
    y convierte a minusculas. Es la unica regla de normalizacion del proyecto.
  * `security.buscar_identidad_o_invitacion(correo, secret_key, transport)`
    -> objeto con los atributos `identidad_existente: bool`,
    `invitacion_pendiente: bool` e `invitacion_id: str | None`.
  * `security.crear_invitacion(correo, secret_key, transport, *, ignore_existing=False)`
    -> objeto con los atributos `invitacion_id: str`, `url: str` y
    `expira_en` (valor no nulo; el tipo concreto lo decide T4).
  * `security.revocar_invitacion(invitacion_id, secret_key, transport) -> None`.
  * Errores de dominio: `security.ErrorClerkNoDisponible` para red/429/5xx o
    payload ilegible (la capa HTTP responde **503**) y
    `security.ErrorInvitacionConflicto` para "ya invitado" (la capa HTTP
    responde **409** sin inventar URL).

Las pruebas fallan hoy solo porque esas funciones/clases aun no existen (T4);
fallan con un mensaje explicito de contrato pendiente, no por un fixture roto.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from app.core import security

#: Secreto ficticio: nunca se usa una credencial real.
SECRETO = "sk_test_falso_017"

#: Forma canonica de la politica de correo (`trim + lowercase`).
CORREO_NORMALIZADO = "juanperez@ejemplo.cl"

#: Forma "sucia" que debe normalizarse antes de cualquier consulta o persistencia.
CORREO_SUCIO = "  JuanPerez@Ejemplo.CL "


# ---------------------------------------------------------------------------
# Contrato publico esperado (T4)
# ---------------------------------------------------------------------------


def _frontera(nombre: str) -> Callable:
    """Devuelve la funcion de frontera o falla con un mensaje de contrato pendiente."""
    funcion = getattr(security, nombre, None)
    if not callable(funcion):
        pytest.fail(
            "Contrato pendiente (T4): `app.core.security` debe exponer "
            f"`{nombre}` para la frontera Clerk de invitaciones (Feature 017)."
        )
    return funcion


def _error_de_dominio(nombre: str) -> type[Exception]:
    """Devuelve la clase de error de dominio o falla indicando el contrato pendiente."""
    clase = getattr(security, nombre, None)
    if not isinstance(clase, type) or not issubclass(clase, Exception):
        pytest.fail(
            "Contrato pendiente (T4): `app.core.security` debe exponer la excepcion "
            f"`{nombre}` (Feature 017)."
        )
    return clase


# ---------------------------------------------------------------------------
# Transporte simulado que registra las solicitudes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolicitudRegistrada:
    """Solicitud HTTP observada por el transporte fake."""

    metodo: str
    ruta: str
    url: str
    cuerpo: str
    autorizacion: str | None


class TransporteClerkFalso(httpx.BaseTransport):
    """Transporte `httpx.BaseTransport` programable y observador.

    `respondedor` recibe la `httpx.Request` y devuelve la `httpx.Response`
    simulada; si lanza una excepcion de `httpx`, reproduce un fallo de red.
    """

    def __init__(
        self, respondedor: Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self._respondedor = respondedor
        self.solicitudes: list[SolicitudRegistrada] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.solicitudes.append(
            SolicitudRegistrada(
                metodo=request.method,
                ruta=request.url.path,
                url=str(request.url),
                cuerpo=request.content.decode("utf-8"),
                autorizacion=request.headers.get("authorization"),
            )
        )
        return self._respondedor(request)


def _transporte(
    respondedor: Callable[[httpx.Request], httpx.Response],
) -> TransporteClerkFalso:
    return TransporteClerkFalso(respondedor)


def _respuesta_usuarios(correos: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json=[
            {
                "id": f"user_{indice}",
                "email_addresses": [
                    {
                        "id": f"em_{indice}",
                        "email_address": correo,
                        "verification": {"status": "verified"},
                    }
                ],
            }
            for indice, correo in enumerate(correos)
        ],
    )


def _respuesta_invitaciones(invitaciones: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": invitaciones, "total_count": len(invitaciones)})


def _invitacion_pendiente(
    invitacion_id: str = "inv_pendiente",
    correo: str = CORREO_NORMALIZADO,
) -> dict:
    return {
        "id": invitacion_id,
        "email_address": correo,
        "status": "pending",
        "url": "https://accounts.ejemplo.cl/invite/pendiente",
        "expires_at": 1893456000000,
    }


def _correo_en_url(solicitud: SolicitudRegistrada) -> str:
    """Extrae el correo normalizado de la query, sin depender del nombre del parametro."""
    from urllib.parse import unquote

    return unquote(solicitud.url)


# ---------------------------------------------------------------------------
# Politica de normalizacion (D-1, AC-1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (CORREO_SUCIO, CORREO_NORMALIZADO),
        ("JUANPEREZ@EJEMPLO.CL", CORREO_NORMALIZADO),
        ("juanperez@ejemplo.cl", CORREO_NORMALIZADO),
        ("\tjuanperez@ejemplo.cl\n", CORREO_NORMALIZADO),
    ],
)
def test_normalizar_correo_aplica_trim_y_minusculas(entrada: str, esperado: str):
    """La unica regla de correo es `trim + lowercase`, idempotente."""
    normalizar = _frontera("normalizar_correo")
    assert normalizar(entrada) == esperado
    assert normalizar(normalizar(entrada)) == esperado


def test_correo_primario_verificado_se_normaliza_antes_de_entregarlo():
    """El correo que devuelve Clerk se normaliza antes del vinculo local (D-1)."""
    def responder(_peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "user_ana",
                "primary_email_address_id": "em_ana",
                "email_addresses": [
                    {
                        "id": "em_ana",
                        "email_address": "  Ana.Perez@Ejemplo.CL ",
                        "verification": {"status": "verified"},
                    }
                ],
            },
        )

    transporte = _transporte(responder)
    correo = security.obtener_correo_primario_verificado(
        "user_ana", SECRETO, transporte
    )
    assert correo == "ana.perez@ejemplo.cl"


# ---------------------------------------------------------------------------
# Busqueda de identidad / invitacion (D-1, AC-2)
# ---------------------------------------------------------------------------


def test_busqueda_encuentra_identidad_existente_sin_invitacion():
    """Identidad existente: `identidad_existente=True` y sin invitacion pendiente."""
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios([CORREO_NORMALIZADO])
        return _respuesta_invitaciones([])

    transporte = _transporte(responder)
    buscar = _frontera("buscar_identidad_o_invitacion")
    resultado = buscar(CORREO_SUCIO, SECRETO, transporte)

    assert resultado.identidad_existente is True
    assert resultado.invitacion_pendiente is False
    assert resultado.invitacion_id is None

    consulta = transporte.solicitudes[0]
    assert consulta.metodo == "GET"
    assert consulta.ruta == "/v1/users"
    assert CORREO_NORMALIZADO in _correo_en_url(consulta)
    assert consulta.autorizacion == f"Bearer {SECRETO}"


def test_busqueda_compara_correos_case_insensitive():
    """Una respuesta de Clerk con mayusculas sigue contando como la misma identidad."""
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios(["JuanPerez@Ejemplo.CL"])
        return _respuesta_invitaciones([])

    transporte = _transporte(responder)
    resultado = _frontera("buscar_identidad_o_invitacion")(
        CORREO_NORMALIZADO, SECRETO, transporte
    )
    assert resultado.identidad_existente is True


def test_busqueda_detecta_invitacion_pendiente_sin_identidad():
    """Invitacion pendiente sin identidad: se reutiliza, no se crea otra (D-1)."""
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios([])
        return _respuesta_invitaciones([_invitacion_pendiente()])

    transporte = _transporte(responder)
    resultado = _frontera("buscar_identidad_o_invitacion")(
        CORREO_SUCIO, SECRETO, transporte
    )

    assert resultado.identidad_existente is False
    assert resultado.invitacion_pendiente is True
    assert resultado.invitacion_id == "inv_pendiente"
    assert any(s.ruta == "/v1/invitations" for s in transporte.solicitudes)
    assert CORREO_NORMALIZADO in _correo_en_url(transporte.solicitudes[0])


def test_busqueda_detecta_invitacion_pendiente_en_lista_desnuda():
    """La API real de Clerk lista invitaciones como lista JSON desnuda (sin `data`).

    La busqueda debe aceptar ambas formas del listado para no romper el alta con
    correos sin identidad (AC-1/AC-2): antes devolvia 503 "respuesta de Clerk
    inesperada" con la respuesta real de `GET /v1/invitations`.
    """
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios([])
        return httpx.Response(200, json=[_invitacion_pendiente()])

    transporte = _transporte(responder)
    resultado = _frontera("buscar_identidad_o_invitacion")(
        CORREO_SUCIO, SECRETO, transporte
    )

    assert resultado.identidad_existente is False
    assert resultado.invitacion_pendiente is True
    assert resultado.invitacion_id == "inv_pendiente"


def test_busqueda_acepta_lista_desnuda_vacia_de_invitaciones():
    """Sin invitaciones, la lista desnuda vacia equivale a "no hay pendiente"."""
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios([])
        return httpx.Response(200, json=[])

    transporte = _transporte(responder)
    resultado = _frontera("buscar_identidad_o_invitacion")(
        CORREO_NORMALIZADO, SECRETO, transporte
    )

    assert resultado.identidad_existente is False
    assert resultado.invitacion_pendiente is False
    assert resultado.invitacion_id is None


def test_busqueda_sin_identidad_ni_invitacion_habilita_el_alta_con_invitacion():
    """Ni identidad ni invitacion: corresponde crear invitacion nueva (D-1)."""
    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/users":
            return _respuesta_usuarios([])
        return _respuesta_invitaciones([])

    transporte = _transporte(responder)
    resultado = _frontera("buscar_identidad_o_invitacion")(
        CORREO_NORMALIZADO, SECRETO, transporte
    )

    assert resultado.identidad_existente is False
    assert resultado.invitacion_pendiente is False
    assert resultado.invitacion_id is None


# ---------------------------------------------------------------------------
# Creacion de invitacion (D-1, D-4, AC-1/AC-6)
# ---------------------------------------------------------------------------


def _respondedor_creacion(estado: int = 200, cuerpo: dict | None = None):
    def responder(_peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(
            estado,
            json=cuerpo
            if cuerpo is not None
            else _invitacion_pendiente("inv_nueva", CORREO_NORMALIZADO),
        )

    return responder


def test_crear_invitacion_devuelve_id_url_y_expiracion():
    """El exito expone identificador, URL y expiracion (solo en esta respuesta)."""
    transporte = _transporte(_respondedor_creacion())
    invitacion = _frontera("crear_invitacion")(
        CORREO_SUCIO, SECRETO, transporte
    )

    assert invitacion.invitacion_id == "inv_nueva"
    assert invitacion.url == "https://accounts.ejemplo.cl/invite/pendiente"
    assert invitacion.expira_en is not None

    solicitud = transporte.solicitudes[0]
    assert solicitud.metodo == "POST"
    assert solicitud.ruta == "/v1/invitations"
    assert solicitud.autorizacion == f"Bearer {SECRETO}"
    import json as _json

    cuerpo = _json.loads(solicitud.cuerpo)
    assert cuerpo["email_address"] == CORREO_NORMALIZADO
    assert cuerpo["ignore_existing"] is False


def test_crear_invitacion_respeta_ignore_existing_explicito():
    """`ignore_existing` se envia explicitamente segun el flujo de alta/reenvio."""
    transporte = _transporte(_respondedor_creacion())
    _frontera("crear_invitacion")(
        CORREO_NORMALIZADO, SECRETO, transporte, ignore_existing=True
    )

    import json as _json

    cuerpo = _json.loads(transporte.solicitudes[0].cuerpo)
    assert cuerpo["ignore_existing"] is True


@pytest.mark.parametrize(
    "respuesta_conflicto",
    [
        httpx.Response(409, json={"errors": [{"code": "already_invited"}]}),
        httpx.Response(400, json={"errors": [{"code": "already_invited"}]}),
    ],
)
def test_crear_invitacion_ya_invitado_es_conflicto_de_dominio(respuesta_conflicto):
    """'Ya invitado' es un conflicto recuperable: ni URL inventada ni exito (D-4)."""
    conflicto = _error_de_dominio("ErrorInvitacionConflicto")

    transporte = _transporte(lambda _peticion: respuesta_conflicto)
    with pytest.raises(conflicto):
        _frontera("crear_invitacion")(CORREO_NORMALIZADO, SECRETO, transporte)


# ---------------------------------------------------------------------------
# Errores externos normalizados (AC-1/AC-3/AC-6: 503 sin filtrar detalles)
# ---------------------------------------------------------------------------


def _fallo_de_red(_peticion: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("sin red")


def _payload_ilegible(_peticion: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"<html>no es json</html>")


@pytest.mark.parametrize(
    "respondedor",
    [
        lambda _peticion: httpx.Response(429, json={"errors": [{"code": "rate_limit"}]}),
        lambda _peticion: httpx.Response(500, json={"errors": [{"code": "internal"}]}),
        _payload_ilegible,
        _fallo_de_red,
    ],
    ids=["429", "5xx", "payload_invalido", "red"],
)
def test_busqueda_normaliza_fallos_externos_a_error_no_disponible(respondedor):
    """Red/429/5xx/payload invalido son `ErrorClerkNoDisponible` (HTTP 503)."""
    no_disponible = _error_de_dominio("ErrorClerkNoDisponible")

    transporte = _transporte(respondedor)
    with pytest.raises(no_disponible):
        _frontera("buscar_identidad_o_invitacion")(
            CORREO_NORMALIZADO, SECRETO, transporte
        )


@pytest.mark.parametrize(
    "respondedor",
    [
        lambda _peticion: httpx.Response(429, json={"errors": [{"code": "rate_limit"}]}),
        lambda _peticion: httpx.Response(503, json={"errors": [{"code": "unavailable"}]}),
        _payload_ilegible,
        _fallo_de_red,
    ],
    ids=["429", "5xx", "payload_invalido", "red"],
)
def test_creacion_normaliza_fallos_externos_a_error_no_disponible(respondedor):
    """Crear invitacion tambien normaliza fallos externos a `ErrorClerkNoDisponible`."""
    no_disponible = _error_de_dominio("ErrorClerkNoDisponible")

    transporte = _transporte(respondedor)
    with pytest.raises(no_disponible):
        _frontera("crear_invitacion")(CORREO_NORMALIZADO, SECRETO, transporte)


# ---------------------------------------------------------------------------
# Revocacion y compensacion (D-2, D-4, AC-3/AC-6)
# ---------------------------------------------------------------------------


def test_revocar_invitacion_por_id():
    """La revocacion exitosa usa `POST /v1/invitations/{id}/revoke`."""
    transporte = _transporte(
        lambda _peticion: httpx.Response(200, json={"id": "inv_nueva", "status": "revoked"})
    )
    resultado = _frontera("revocar_invitacion")("inv_nueva", SECRETO, transporte)

    assert resultado is None
    solicitud = transporte.solicitudes[0]
    assert solicitud.metodo == "POST"
    assert solicitud.ruta == "/v1/invitations/inv_nueva/revoke"
    assert solicitud.autorizacion == f"Bearer {SECRETO}"


def test_revocacion_compensa_la_invitacion_creada_si_falla_el_commit_local():
    """El ID devuelto al crear es el que la compensacion revoca (D-2).

    La orquestacion (crear -> commit tenant -> revocar si falla) pertenece a T6;
    aqui se fija que ambas operaciones de frontera encajan por identificador.
    """
    respuestas = iter(
        [
            httpx.Response(200, json=_invitacion_pendiente("inv_compensable")),
            httpx.Response(200, json={"id": "inv_compensable", "status": "revoked"}),
        ]
    )
    transporte = _transporte(lambda _peticion: next(respuestas))

    crear = _frontera("crear_invitacion")
    revocar = _frontera("revocar_invitacion")
    invitacion = crear(CORREO_NORMALIZADO, SECRETO, transporte)

    # Fallo local simulado: la compensacion revoca exactamente esa invitacion.
    revocar(invitacion.invitacion_id, SECRETO, transporte)

    assert [s.ruta for s in transporte.solicitudes] == [
        "/v1/invitations",
        "/v1/invitations/inv_compensable/revoke",
    ]


# ---------------------------------------------------------------------------
# La URL no se persiste ni se publica fuera de la respuesta inmediata
# ---------------------------------------------------------------------------


def test_el_mapa_de_control_no_persiste_la_url_de_invitacion():
    """Ninguna columna del mapa `correo -> esquema` puede almacenar la URL (D-6)."""
    from app.models.control import MapaUsuarioEsquema

    columnas = set(MapaUsuarioEsquema.__table__.columns.keys())
    assert not any("url" in columna or "link" in columna for columna in columnas)


def test_la_respuesta_de_usuario_no_expone_la_url_de_invitacion():
    """El DTO de usuario/listado no publica la URL: solo viaja en alta/reenvio."""
    from app.schemas.usuario_schema import UsuarioRespuesta

    campos = set(UsuarioRespuesta.model_fields)
    assert not any("url" in campo or "link" in campo for campo in campos)
