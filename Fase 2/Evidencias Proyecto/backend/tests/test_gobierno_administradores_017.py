"""Feature 017, T6: alta con invitacion, reenvio, motivos y gobierno (AC-1..AC-12).

Seam bajo prueba: la interfaz HTTP real sobre SQLite y las funciones de servicio
para los escenarios que requieren inyectar fallos (compensacion, segunda
confirmacion). La frontera Clerk se sustituye por callables fake; ninguna prueba
sale a la red ni persiste URLs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core import security
from app.main import app
from app.models import (
    Departamento,
    MapaUsuarioEsquema,
    RegistroMotivoConstancia,
    Rol,
    Usuario,
)
from app.schemas.usuario_schema import UsuarioCrear
from app.services import motivo_service, usuario_service
from app.services.auth_service import IdentidadAutenticada

RUTA_USUARIOS = "/api/v1/usuarios/"
RUTA_USUARIO = "/api/v1/usuarios/{usuario_id}"
RUTA_ESTADO = "/api/v1/usuarios/{usuario_id}/estado"
RUTA_CONTROL_USUARIOS = "/api/v1/control/instituciones/{institucion_id}/usuarios/"
RUTA_CONTROL_USUARIO = (
    "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
)
RUTA_CONTROL_ESTADO = (
    "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado"
)
RUTA_CONTROL_REENVIO = (
    "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}"
    "/invitacion/reenvio"
)

MOTIVO = {"codigo": "correccion_datos", "texto": "Correccion administrativa"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(rol: str, departamento_id: int | None) -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=9000,
        nombre="Sonda",
        apellido="T6",
        correo="sonda.t6@compustock.cl",
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-t6")


def _invitacion(invitacion_id="inv_t6", url="https://clerk.test/t6"):
    return security.InvitacionCreada(
        invitacion_id=invitacion_id,
        url=url,
        expira_en=datetime.now(timezone.utc) + timedelta(days=7),
    )


@contextmanager
def _cliente(
    motor,
    rol: str,
    *,
    departamento_id: int | None,
    estado_identidad=None,
    crear=None,
    revocar=None,
):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db
    app.dependency_overrides[dependencies.get_current_user] = lambda: _identity(
        rol, departamento_id
    )
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda _correo: True)
    )
    app.dependency_overrides[dependencies.obtener_consultor_identidad_clerk] = (
        lambda: (estado_identidad or (lambda _c: security.EstadoIdentidadClerk(True, False, None)))
    )
    app.dependency_overrides[dependencies.obtener_creador_invitacion_clerk] = (
        lambda: (crear or (lambda _c, ignore_existing=False: _invitacion()))
    )
    app.dependency_overrides[dependencies.obtener_revocador_invitacion_clerk] = (
        lambda: (revocar or (lambda _i: None))
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


def _sembrar(motor, datos_base):
    """Roles Administrador/Solicitante, un Bodeguero y un mapa pendiente."""
    with sessionmaker(bind=motor)() as db:
        rol_solicitante = Rol(nombre_rol="Solicitante", descripcion="Solicitante")
        db.add(rol_solicitante)
        db.flush()
        bodeguero = Usuario(
            nombre="Bodega",
            apellido="T6",
            correo="bodega.t6@compustock.cl",
            departamento_id=datos_base["departamento_id"],
            rol_id=datos_base["rol_bodeguero_id"],
        )
        db.add(bodeguero)
        db.commit()
        return {
            **datos_base,
            "rol_solicitante_id": rol_solicitante.rol_id,
            "bodeguero_id": bodeguero.usuario_id,
        }


def _datos_alta(datos, correo="nuevo.t6@compustock.cl", rol_id=None) -> UsuarioCrear:
    return UsuarioCrear(
        nombre="Nuevo",
        apellido="T6",
        correo=correo,
        departamento_id=datos["departamento_id"],
        rol_id=rol_id or datos["rol_bodeguero_id"],
    )


# ---------------------------------------------------------------------------
# Alta tenant: normalizacion, identidad, invitacion pendiente (AC-1/AC-2)
# ---------------------------------------------------------------------------


def test_alta_sin_identidad_crea_invitacion_y_estado_pendiente(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        estado_identidad=lambda _c: security.EstadoIdentidadClerk(False, False, None),
    ) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS,
            json=_datos_alta(datos, "  Nuevo.T6@CompuStock.CL ").model_dump(),
        )
    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["correo"] == "nuevo.t6@compustock.cl"
    assert cuerpo["estado_invitacion"] == "pendiente"
    assert cuerpo["url_invitacion"]
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, "nuevo.t6@compustock.cl")
        assert mapa is not None and mapa.estado_invitacion == "pendiente"
        assert mapa.invitacion_id == "inv_t6"


def test_alta_con_identidad_existente_no_invita(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    creadas = []

    def crear(correo, ignore_existing=False):
        creadas.append(correo)
        return _invitacion()

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        estado_identidad=lambda _c: security.EstadoIdentidadClerk(True, False, None),
        crear=crear,
    ) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS, json=_datos_alta(datos, "existe.t6@compustock.cl").model_dump()
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["estado_invitacion"] == "aceptada"
    assert respuesta.json()["url_invitacion"] is None
    assert creadas == []


def test_alta_reutiliza_invitacion_pendiente_sin_crear_otra(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    creadas = []

    def crear(correo, ignore_existing=False):
        creadas.append(correo)
        return _invitacion()

    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos["departamento_id"],
        estado_identidad=lambda _c: security.EstadoIdentidadClerk(
            False, True, "inv_pendiente"
        ),
        crear=crear,
    ) as cliente:
        respuesta = cliente.post(
            RUTA_USUARIOS, json=_datos_alta(datos, "pendiente.t6@compustock.cl").model_dump()
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["estado_invitacion"] == "pendiente"
    assert creadas == []
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, "pendiente.t6@compustock.cl")
        assert mapa.invitacion_id == "inv_pendiente"


# ---------------------------------------------------------------------------
# Compensacion y recuperacion (AC-3/AC-7)
# ---------------------------------------------------------------------------


def _sesion(motor):
    return sessionmaker(bind=motor)()


def test_fallo_tenant_revoca_la_invitacion(motor, datos_base, monkeypatch):
    datos = _sembrar(motor, datos_base)
    db = _sesion(motor)
    revocadas = []

    def boom(_db, _usuario):
        raise RuntimeError("fallo simulado de commit tenant")

    monkeypatch.setattr(usuario_service, "_confirmar_usuario_tenant", boom)
    try:
        with pytest.raises(RuntimeError):
            usuario_service.crear_usuario(
                db,
                _datos_alta(datos, "compensa.t6@compustock.cl"),
                _identity("Administrador", datos["departamento_id"]),
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    False, False, None
                ),
                crear_invitacion_fn=lambda _c, ignore_existing=False: _invitacion(
                    "inv_compensa"
                ),
                revocar_invitacion_fn=lambda i: revocadas.append(i),
            )
        assert revocadas == ["inv_compensa"]
        assert db.query(RegistroMotivoConstancia).count() == 0
        assert db.query(Usuario).filter(
            Usuario.correo == "compensa.t6@compustock.cl"
        ).count() == 0
    finally:
        db.close()


def test_fallo_de_revocacion_persiste_constancia_con_invitacion_id(
    motor, datos_base, monkeypatch
):
    datos = _sembrar(motor, datos_base)
    db = _sesion(motor)

    def boom(_db, _usuario):
        raise RuntimeError("fallo simulado de commit tenant")

    def revocar(_id):
        raise RuntimeError("revocacion caida")

    monkeypatch.setattr(usuario_service, "_confirmar_usuario_tenant", boom)
    try:
        with pytest.raises(RuntimeError):
            usuario_service.crear_usuario(
                db,
                _datos_alta(datos, "huerfana.t6@compustock.cl"),
                _identity("Administrador", datos["departamento_id"]),
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    False, False, None
                ),
                crear_invitacion_fn=lambda _c, ignore_existing=False: _invitacion(
                    "inv_huerfana"
                ),
                revocar_invitacion_fn=revocar,
            )
        constancia = db.execute(select(RegistroMotivoConstancia)).scalar_one()
        assert constancia.invitacion_id == "inv_huerfana"
        assert constancia.accion == "compensacion_invitacion_fallida"
        assert "url" not in constancia.__table__.columns
    finally:
        db.close()


def test_fallo_del_mapa_responde_503_y_el_reintento_completa(
    motor, datos_base, monkeypatch
):
    datos = _sembrar(motor, datos_base)
    db = _sesion(motor)
    original = usuario_service._registrar_vinculacion
    llamadas = {"n": 0, "creadas": 0}

    def falla_una_vez(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("fallo simulado del mapa")
        return original(*args, **kwargs)

    def crear(correo, ignore_existing=False):
        llamadas["creadas"] += 1
        return _invitacion("inv_reintento")

    monkeypatch.setattr(usuario_service, "_registrar_vinculacion", falla_una_vez)
    datos_alta = _datos_alta(datos, "reintento2.t6@compustock.cl")
    try:
        with pytest.raises(HTTPException) as error:
            usuario_service.crear_usuario(
                db,
                datos_alta,
                _identity("Administrador", datos["departamento_id"]),
                consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                    False, False, None
                ),
                crear_invitacion_fn=crear,
            )
        assert error.value.status_code == 503
        assert db.get(MapaUsuarioEsquema, "reintento2.t6@compustock.cl") is None

        monkeypatch.setattr(
            usuario_service, "_registrar_vinculacion", original
        )
        recuperado = usuario_service.crear_usuario(
            db,
            datos_alta,
            _identity("Administrador", datos["departamento_id"]),
            consultar_identidad=lambda _c: security.EstadoIdentidadClerk(
                False, False, None
            ),
            crear_invitacion_fn=crear,
        )
        assert llamadas["creadas"] == 1, "el reintento no vuelve a invitar"
        mapa = db.get(MapaUsuarioEsquema, "reintento2.t6@compustock.cl")
        assert mapa is not None and mapa.activo is True
        assert db.query(Usuario).filter(
            Usuario.correo == "reintento2.t6@compustock.cl"
        ).count() == 1
        assert recuperado.correo == "reintento2.t6@compustock.cl"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reenvio (AC-6)
# ---------------------------------------------------------------------------


def _con_mapa(motor, datos_base, *, estado="pendiente", invitacion_id="inv_vieja"):
    with sessionmaker(bind=motor)() as db:
        db.add(
            MapaUsuarioEsquema(
                correo=datos_base["correo_usado"],
                institucion_id=datos_base["institucion_id"],
                nombre_esquema="tenant_t6",
                activo=True,
                estado_invitacion=estado,
                invitacion_id=invitacion_id,
            )
        )
        db.commit()


def test_reenvio_crea_invitacion_nueva_y_actualiza_el_mapa(motor, datos_base):
    _con_mapa(motor, datos_base)
    revocadas = []
    with _cliente(
        motor,
        "Superadmin",
        departamento_id=None,
        crear=lambda _c, ignore_existing=False: _invitacion("inv_nueva", "https://nueva"),
        revocar=lambda i: revocadas.append(i),
    ) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_REENVIO.format(
                institucion_id=datos_base["institucion_id"],
                usuario_id=datos_base["usuario_id"],
            )
        )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["url_invitacion"] == "https://nueva"
    assert revocadas == ["inv_vieja"]
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, datos_base["correo_usado"])
        assert mapa.invitacion_id == "inv_nueva"
        assert mapa.estado_invitacion == "pendiente"


def test_reenvio_de_invitacion_aceptada_responde_409(motor, datos_base):
    _con_mapa(motor, datos_base, estado="aceptada")
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_REENVIO.format(
                institucion_id=datos_base["institucion_id"],
                usuario_id=datos_base["usuario_id"],
            )
        )
    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(MapaUsuarioEsquema, datos_base["correo_usado"]).invitacion_id == "inv_vieja"


def test_reenvio_con_conflicto_no_cambia_el_id_persistido(motor, datos_base):
    _con_mapa(motor, datos_base)

    def crear(_correo, ignore_existing=False):
        raise security.ErrorInvitacionConflicto("ya invitado")

    with _cliente(
        motor, "Superadmin", departamento_id=None, crear=crear
    ) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_REENVIO.format(
                institucion_id=datos_base["institucion_id"],
                usuario_id=datos_base["usuario_id"],
            )
        )
    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, datos_base["correo_usado"])
        assert mapa.invitacion_id == "inv_vieja"


# ---------------------------------------------------------------------------
# Motivos (AC-10/AC-11) en rutas tenant
# ---------------------------------------------------------------------------


def test_edicion_efectiva_sin_motivo_responde_422_sin_mutar(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.put(
            RUTA_USUARIO.format(usuario_id=datos["bodeguero_id"]),
            json={
                "nombre": "Cambiado",
                "apellido": "T6",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_bodeguero_id"],
            },
        )
    assert respuesta.status_code == 422, respuesta.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(Usuario, datos["bodeguero_id"]).nombre == "Bodega"
        assert db.query(RegistroMotivoConstancia).count() == 0


def test_edicion_efectiva_con_motivo_persiste_justificacion(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.put(
            RUTA_USUARIO.format(usuario_id=datos["bodeguero_id"]),
            json={
                "nombre": "Cambiado",
                "apellido": "T6",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_bodeguero_id"],
                "motivo": MOTIVO,
                "idempotencia": "mut-edicion-1",
            },
        )
    assert respuesta.status_code == 200, respuesta.text
    with sessionmaker(bind=motor)() as db:
        fila = db.get(RegistroMotivoConstancia, 1)
        assert fila.tipo_registro == "justificacion"
        assert fila.codigo_motivo == "correccion_datos"
        assert fila.clave_idempotente == "mut-edicion-1"
        assert fila.usuario_objetivo_id == datos["bodeguero_id"]


def test_estado_repetido_no_exige_ni_genera_motivo(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        baja = cliente.patch(
            RUTA_ESTADO.format(usuario_id=datos["bodeguero_id"]),
            json={"activo": False, "motivo": {"codigo": "termino_vinculo"}},
        )
        repetida = cliente.patch(
            RUTA_ESTADO.format(usuario_id=datos["bodeguero_id"]),
            json={"activo": False},
        )
    assert baja.status_code == 200, baja.text
    assert repetida.status_code == 200, repetida.text
    with sessionmaker(bind=motor)() as db:
        assert db.query(RegistroMotivoConstancia).count() == 1


def test_baja_del_ultimo_administrador_responde_409_sin_mutar(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        respuesta = cliente.patch(
            RUTA_ESTADO.format(usuario_id=datos["usuario_id"]),
            json={"activo": False, "motivo": {"codigo": "termino_vinculo"}},
        )
    assert respuesta.status_code == 409, respuesta.text
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, datos["correo_usado"])
        assert mapa is None or mapa.activo is True
        assert db.query(RegistroMotivoConstancia).count() == 0


def test_fallo_de_la_segunda_confirmacion_responde_503_y_el_reintento_completa(
    motor, datos_base, monkeypatch
):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente:
        body = {
            "nombre": "Cambiado",
            "apellido": "T6",
            "departamento_id": datos["departamento_id"],
            "rol_id": datos["rol_bodeguero_id"],
            "motivo": MOTIVO,
            "idempotencia": "mut-fallo-control",
        }
        original = motivo_service.registrar_justificacion
        monkeypatch.setattr(
            motivo_service,
            "registrar_justificacion",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("control caido")),
        )
        fallo = cliente.put(RUTA_USUARIO.format(usuario_id=datos["bodeguero_id"]), json=body)
        assert fallo.status_code == 503, fallo.text

        monkeypatch.setattr(motivo_service, "registrar_justificacion", original)
        reintento = cliente.put(
            RUTA_USUARIO.format(usuario_id=datos["bodeguero_id"]), json=body
        )
    assert reintento.status_code == 200, reintento.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(Usuario, datos["bodeguero_id"]).nombre == "Cambiado"
        filas = db.query(RegistroMotivoConstancia).all()
        assert len(filas) == 1
        assert filas[0].tipo_registro == "justificacion"
        assert filas[0].clave_idempotente == "mut-fallo-control"


# ---------------------------------------------------------------------------
# Rutas de control (AC-8/AC-9)
# ---------------------------------------------------------------------------


def test_listado_control_solo_administradores_y_sin_clerk(motor, datos_base):
    datos = _sembrar(motor, datos_base)

    def consultar(_correo):
        raise AssertionError("un listado no debe llamar a Clerk")

    with _cliente(
        motor, "Superadmin", departamento_id=None, estado_identidad=consultar
    ) as cliente:
        respuesta = cliente.get(
            RUTA_CONTROL_USUARIOS.format(institucion_id=datos["institucion_id"])
        )
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()
    assert [f["usuario_id"] for f in filas] == [datos["usuario_id"]]
    assert set(filas[0]) == {
        "usuario_id",
        "nombre",
        "apellido",
        "correo",
        "activo",
        "estado_invitacion",
    }
    assert not any("url" in campo for campo in filas[0])


def test_control_institucion_inexistente_responde_404(motor, datos_base):
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_CONTROL_USUARIOS.format(institucion_id="NOEXISTE"))
    assert respuesta.status_code == 404, respuesta.text


def test_control_alta_admin_sin_identidad_invita_y_devuelve_url(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(
        motor,
        "Superadmin",
        departamento_id=None,
        estado_identidad=lambda _c: security.EstadoIdentidadClerk(False, False, None),
    ) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_USUARIOS.format(institucion_id=datos["institucion_id"]),
            json=_datos_alta(
                datos, "admin.nuevo17@compustock.cl", rol_id=datos["rol_id"]
            ).model_dump(),
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["estado_invitacion"] == "pendiente"
    assert respuesta.json()["url_invitacion"]


def test_control_alta_rechaza_rol_no_administrador(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.post(
            RUTA_CONTROL_USUARIOS.format(institucion_id=datos["institucion_id"]),
            json=_datos_alta(
                datos, "no.admin17@compustock.cl", rol_id=datos["rol_bodeguero_id"]
            ).model_dump(),
        )
    assert respuesta.status_code == 403, respuesta.text


def test_control_no_gestiona_usuarios_que_no_son_administradores(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.patch(
            RUTA_CONTROL_ESTADO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["bodeguero_id"],
            ),
            json={"activo": False, "motivo": {"codigo": "termino_vinculo"}},
        )
    assert respuesta.status_code == 404, respuesta.text


def test_control_edicion_y_estado_motivados(motor, datos_base):
    datos = _sembrar(motor, datos_base)
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        edicion = cliente.put(
            RUTA_CONTROL_USUARIO.format(
                institucion_id=datos["institucion_id"],
                usuario_id=datos["usuario_id"],
            ),
            json={
                "nombre": "Admin Editado",
                "apellido": "T6",
                "departamento_id": datos["departamento_id"],
                "rol_id": datos["rol_id"],
                "motivo": MOTIVO,
            },
        )
    assert edicion.status_code == 200, edicion.text
    with sessionmaker(bind=motor)() as db:
        assert db.get(Usuario, datos["usuario_id"]).nombre == "Admin Editado"
        assert db.query(RegistroMotivoConstancia).count() == 1


def test_superadmin_recibe_403_en_usuarios_ordinarios(motor, datos_base):
    with _cliente(motor, "Superadmin", departamento_id=None) as cliente:
        respuesta = cliente.get(RUTA_USUARIOS)
    assert respuesta.status_code == 403, respuesta.text
