"""Feature 017, T11: correcciones backend tras la validacion AC por AC.

Cubre, sobre la interfaz HTTP real y los servicios (SQLite en memoria):

  * AC-2/AC-6: `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio`, reenvio
    ordinario del Administrador a sus Bodegueros/Solicitantes activos, con la
    reactivacion motivada como operacion separada (D-4/D-10);
  * C-C: continuidad administrativa al degradar el rol del unico Administrador
    activo por `PUT /control/.../usuarios/{usuario_id}` (D-7/AC-12);
  * C-E: fallos de sesion/tenant de las cinco operaciones D-10 y del dashboard
    normalizados a **503** documentado;
  * C-F: `_completar_alta_sin_mapa` completa la evidencia persistida del alta y
    no fabrica claves idempotentes (D-2).

Ninguna prueba sale a la red: la frontera Clerk se sustituye por callables fake.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import permisos, security
from app.main import app
from app.models import (
    Departamento,
    Institucion,
    MapaUsuarioEsquema,
    RegistroMotivoConstancia,
    Rol,
    Usuario,
)
from app.schemas.usuario_schema import UsuarioCrear
from app.services import control_service, motivo_service, usuario_service

from .test_gobierno_administradores_017 import (  # noqa: F401 - helpers compartidos
    MOTIVO,
    RUTA_CONTROL_ESTADO,
    RUTA_CONTROL_REENVIO,
    RUTA_CONTROL_USUARIO,
    RUTA_CONTROL_USUARIOS,
    _cliente,
    _datos_alta,
    _identity,
    _invitacion,
    _sembrar,
)

RUTA_REENVIO = "/api/v1/usuarios/{usuario_id}/invitacion/reenvio"
RUTA_ESTADO_TENANT = "/api/v1/usuarios/{usuario_id}/estado"


def _sesion(motor):
    return sessionmaker(bind=motor)()


def _mapa(
    motor,
    correo: str,
    *,
    activo: bool = True,
    estado: str = "pendiente",
    invitacion_id: str = "inv_previa",
    institucion_id: str = "INST01",
):
    with sessionmaker(bind=motor)() as db:
        db.add(
            MapaUsuarioEsquema(
                correo=correo,
                institucion_id=institucion_id,
                nombre_esquema="tenant_t11",
                activo=activo,
                estado_invitacion=estado,
                invitacion_id=invitacion_id,
            )
        )
        db.commit()


def _bodeguero_ajeno(motor, datos) -> int:
    """Bodeguero de otra institucion para el 404 de objetivo ajeno (AC-9)."""
    with sessionmaker(bind=motor)() as db:
        if db.get(Institucion, "INST02") is None:
            db.add(Institucion(institucion_id="INST02", nombre="Institucion ajena"))
            db.flush()
        departamento = Departamento(
            nombre_dep="Bodega ajena",
            descripcion="Departamento de otra institucion",
            institucion_id="INST02",
        )
        db.add(departamento)
        db.flush()
        usuario = Usuario(
            nombre="Ajeno",
            apellido="T11",
            correo="ajeno.t11@compustock.cl",
            departamento_id=departamento.departamento_id,
            rol_id=datos["rol_bodeguero_id"],
        )
        db.add(usuario)
        db.commit()
        return usuario.usuario_id


# ---------------------------------------------------------------------------
# AC-2/AC-6: reenvio ordinario del Administrador
# ---------------------------------------------------------------------------


def test_reenvio_ordinario_rota_la_invitacion_y_entrega_url_una_vez(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, invitacion_id="inv_vieja")
    revocadas = []

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        crear=lambda _c, ignore_existing=False: _invitacion("inv_nueva", "https://nueva"),
        revocar=lambda i: revocadas.append(i),
    ) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )
        listado = cliente.get("/api/v1/usuarios/")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["url_invitacion"] == "https://nueva"
    assert revocadas == ["inv_vieja"]
    assert listado.status_code == 200, listado.text
    assert "url_invitacion" not in listado.text
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, correo)
        assert mapa.invitacion_id == "inv_nueva"
        assert mapa.estado_invitacion == "pendiente"
        assert mapa.activo is True


def test_reenvio_ordinario_solo_lo_autoriza_el_administrador():
    roles = permisos.MATRIZ_PERMISOS[("POST", RUTA_REENVIO)]
    assert set(roles) == {"Administrador"}


@pytest.mark.parametrize("rol", ["Superadmin", "Bodeguero", "Solicitante"])
def test_reenvio_ordinario_deniega_otros_roles_sin_mutar(motor, datos_base, rol):
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, invitacion_id="inv_vieja")

    with _cliente(motor, rol, departamento_id=None) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )

    assert respuesta.status_code == 403, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(MapaUsuarioEsquema, correo).invitacion_id == "inv_vieja"


def test_reenvio_ordinario_rechaza_objetivo_ajeno_con_404(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    ajeno_id = _bodeguero_ajeno(motor, datos)

    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.post(RUTA_REENVIO.format(usuario_id=ajeno_id))

    assert respuesta.status_code == 404, respuesta.text


def test_reenvio_ordinario_rechaza_objetivo_administrador_con_403(motor, datos_base):
    datos = _sembrar(motor, datos_base)

    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["usuario_id"])
        )

    assert respuesta.status_code == 403, respuesta.text


def test_reenvio_ordinario_de_invitacion_aceptada_responde_409(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, estado="aceptada", invitacion_id="inv_aceptada")

    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )

    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(MapaUsuarioEsquema, correo).invitacion_id == "inv_aceptada"


def test_reenvio_ordinario_con_conflicto_clerk_conserva_el_id(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, invitacion_id="inv_vieja")

    def crear(_correo, ignore_existing=False):
        raise security.ErrorInvitacionConflicto("ya invitado")

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        crear=crear,
    ) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )

    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(MapaUsuarioEsquema, correo).invitacion_id == "inv_vieja"


def test_reenvio_ordinario_de_asociacion_inactiva_responde_409_sin_reactivar(
    motor, datos_base
):
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, activo=False, invitacion_id="inv_vieja")
    creadas = []

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        crear=lambda _c, ignore_existing=False: creadas.append(_c) or _invitacion(),
    ) as cliente:
        respuesta = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )

    assert respuesta.status_code == 409, respuesta.text
    assert creadas == []
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, correo)
        assert mapa.activo is False
        assert mapa.invitacion_id == "inv_vieja"


def test_reactivacion_motivada_y_reenvio_son_operaciones_separadas(
    motor, datos_base
):
    """AC-2/AC-6: primero PATCH .../estado con motivo, luego el reenvio."""
    datos = _sembrar(motor, datos_base)
    correo = "bodega.t6@compustock.cl"
    _mapa(motor, correo, activo=False, invitacion_id="inv_vieja")

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        crear=lambda _c, ignore_existing=False: _invitacion("inv_tras", "https://tras"),
    ) as cliente:
        reactivacion = cliente.patch(
            RUTA_ESTADO_TENANT.format(usuario_id=datos["bodeguero_id"]),
            json={
                "activo": True,
                "motivo": {"codigo": "seguridad_acceso", "texto": "Reactivar"},
                "idempotencia": "reactivacion-t11",
            },
        )
        reenvio = cliente.post(
            RUTA_REENVIO.format(usuario_id=datos["bodeguero_id"])
        )

    assert reactivacion.status_code == 200, reactivacion.text
    assert reactivacion.json()["activo"] is True
    assert reenvio.status_code == 200, reenvio.text
    assert reenvio.json()["url_invitacion"] == "https://tras"
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, correo)
        assert mapa.activo is True
        assert mapa.invitacion_id == "inv_tras"
        motivos = db.query(RegistroMotivoConstancia).all()
        assert len(motivos) == 1
        assert motivos[0].accion == "reactivacion_usuario"


def test_control_reenvio_de_asociacion_inactiva_responde_409(motor, datos_base):
    _mapa(motor, datos_base["correo_usado"], activo=False, invitacion_id="inv_vieja")

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_REENVIO.format(
                institucion_id=datos_base["institucion_id"],
                usuario_id=datos_base["usuario_id"],
            )
        )

    assert respuesta.status_code == 409, respuesta.text


def test_openapi_publica_el_reenvio_ordinario_con_su_contrato():
    operacion = (
        app.openapi()["paths"][RUTA_REENVIO]["post"]
    )
    respuestas = operacion["responses"]
    assert "200" in respuestas
    esquema = respuestas["200"]["content"]["application/json"]["schema"]
    assert esquema["$ref"].rsplit("/", 1)[-1] == "UsuarioInvitacionRespuesta"
    assert {"401", "403", "404", "409", "422", "503"} <= set(respuestas)
    assert operacion.get("security")


# ---------------------------------------------------------------------------
# C-C: continuidad administrativa al degradar el rol (D-7/AC-12)
# ---------------------------------------------------------------------------


def test_control_no_degrada_al_ultimo_administrador_activo(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    _mapa(motor, datos_base["correo_usado"], estado="aceptada", activo=True)

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.put(
            RUTA_CONTROL_USUARIO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            json={
                "nombre": datos_base.get("nombre", "Ana"),
                "apellido": "Perez",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_bodeguero_id"],
                "motivo": MOTIVO,
            },
        )

    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        usuario = db.get(Usuario, datos["usuario_id"])
        assert usuario.rol_id == datos["rol_id"]
        assert db.query(RegistroMotivoConstancia).count() == 0


def test_control_permite_degradar_si_queda_otro_administrador_activo(
    motor, datos_base
):
    datos = _sembrar(motor, datos_base)
    _mapa(motor, datos_base["correo_usado"], estado="aceptada", activo=True)
    with sessionmaker(bind=motor)() as db:
        segundo = Usuario(
            nombre="Segundo",
            apellido="Admin",
            correo="segundo.admin.t11@compustock.cl",
            departamento_id=datos["departamento_id"],
            rol_id=datos["rol_id"],
        )
        db.add(segundo)
        db.commit()
    _mapa(motor, "segundo.admin.t11@compustock.cl", estado="aceptada", activo=True)

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.put(
            RUTA_CONTROL_USUARIO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            json={
                "nombre": "Ana",
                "apellido": "Perez",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_bodeguero_id"],
                "motivo": MOTIVO,
            },
        )

    assert respuesta.status_code == 200, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(Usuario, datos["usuario_id"]).rol_id == datos["rol_bodeguero_id"]
        assert db.query(RegistroMotivoConstancia).count() == 1


# ---------------------------------------------------------------------------
# C-E: fallos de sesion/tenant -> 503 documentado
# ---------------------------------------------------------------------------


@contextmanager
def _tenant_no_disponible(*_args, **_kwargs):
    raise RuntimeError("tenant caido")
    yield  # pragma: no cover - nunca se alcanza


def _peticiones_control(datos):
    return [
        ("GET", RUTA_CONTROL_USUARIOS.format(institucion_id=datos["institucion_id"]), None),
        (
            "POST",
            RUTA_CONTROL_USUARIOS.format(institucion_id=datos["institucion_id"]),
            _datos_alta(datos, "caido.t11@compustock.cl", rol_id=datos["rol_id"]).model_dump(),
        ),
        (
            "PUT",
            RUTA_CONTROL_USUARIO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            {
                "nombre": "Ana",
                "apellido": "Perez",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_id"],
                "motivo": MOTIVO,
            },
        ),
        (
            "PATCH",
            RUTA_CONTROL_ESTADO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            {"activo": False, "motivo": {"codigo": "termino_vinculo"}},
        ),
        (
            "POST",
            RUTA_CONTROL_REENVIO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            None,
        ),
    ]


@pytest.mark.parametrize("indice", range(5))
def test_fallo_de_sesion_tenant_en_control_responde_503(
    motor, datos_base, monkeypatch, indice
):
    datos = _sembrar(motor, datos_base)
    monkeypatch.setattr(
        control_service, "_sesion_tenant_derivada", _tenant_no_disponible
    )
    metodo, ruta, cuerpo = _peticiones_control(datos)[indice]

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.request(metodo, ruta, json=cuerpo)

    assert respuesta.status_code == 503, (metodo, ruta, respuesta.text)


def test_fallo_del_control_en_dashboard_responde_503(motor, datos_base, monkeypatch):
    def _caido(_db):
        raise RuntimeError("control caido")

    monkeypatch.setattr(control_service, "_instituciones_canonicas", _caido)

    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get("/api/v1/control/dashboard")

    assert respuesta.status_code == 503, respuesta.text


def test_openapi_documenta_503_en_el_dashboard():
    operacion = app.openapi()["paths"]["/api/v1/control/dashboard"]["get"]
    assert "503" in operacion["responses"]


# ---------------------------------------------------------------------------
# C-F: `_completar_alta_sin_mapa` completa la evidencia persistida (D-2)
# ---------------------------------------------------------------------------


def test_fallo_de_mapa_deja_evidencia_con_clave_e_invitacion(
    motor, datos_base, monkeypatch
):
    datos = _sembrar(motor, datos_base)
    db = _sesion(motor)
    original = usuario_service._registrar_vinculacion

    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado del mapa")

    monkeypatch.setattr(usuario_service, "_registrar_vinculacion", falla)
    datos_alta = _datos_alta(datos, "evidencia.t11@compustock.cl")
    usuario_id = None
    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            usuario_service.crear_usuario(
                db,
                datos_alta,
                _identity("Administrador", datos["departamento_id"]),
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    False, False, None
                ),
                crear_invitacion_fn=lambda _c, ignore_existing=False: _invitacion(
                    "inv_evidencia"
                ),
            )
        assert error.value.status_code == 503
        usuario_id = (
            db.query(Usuario)
            .filter(Usuario.correo == "evidencia.t11@compustock.cl")
            .one()
            .usuario_id
        )
        fila = db.execute(select(RegistroMotivoConstancia)).scalar_one()
        assert fila.clave_idempotente == motivo_service.clave_para_alta(usuario_id)
        assert fila.accion == motivo_service.ACCION_ALTA_INVITACION
        assert fila.invitacion_id == "inv_evidencia"
        assert fila.usuario_objetivo_id == usuario_id

        monkeypatch.setattr(usuario_service, "_registrar_vinculacion", original)
        recuperado = usuario_service.crear_usuario(
            db,
            datos_alta,
            _identity("Administrador", datos["departamento_id"]),
            consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                False, True, "inv_evidencia"
            ),
            crear_invitacion_fn=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("el reintento no debe invitar de nuevo")
            ),
        )
        assert recuperado.usuario_id == usuario_id
        assert db.get(MapaUsuarioEsquema, "evidencia.t11@compustock.cl") is not None
        fila = db.execute(select(RegistroMotivoConstancia)).scalar_one()
        assert fila.tipo_registro == "justificacion"
        assert fila.clave_idempotente == motivo_service.clave_para_alta(usuario_id)
    finally:
        db.close()


def test_reintento_con_invitacion_pendiente_sin_evidencia_responde_503(
    motor, datos_base
):
    datos = _sembrar(motor, datos_base)
    db = _sesion(motor)
    correo = "sin.evidencia.t11@compustock.cl"
    existente = Usuario(
        nombre="Sin",
        apellido="Evidencia",
        correo=correo,
        departamento_id=datos["departamento_id"],
        rol_id=datos["rol_bodeguero_id"],
    )
    db.add(existente)
    db.commit()
    try:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            usuario_service.crear_usuario(
                db,
                _datos_alta(datos, correo),
                _identity("Administrador", datos["departamento_id"]),
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    False, True, "inv_sin_evidencia"
                ),
            )
        assert error.value.status_code == 503
        assert db.get(MapaUsuarioEsquema, correo) is None
        assert db.query(RegistroMotivoConstancia).count() == 0
    finally:
        db.close()
