"""T7 (Feature 017): dashboard tecnico SaaS y taxonomia unica de tenant.

Seam bajo prueba: `control_service.dashboard_saas` y el contrato
`GET /api/v1/control/dashboard`. Fase TDD: fija la semantica de D-8/AC-13/AC-14
antes de implementarla.

Casos cubiertos:

* `operativo` (activa + enrutable + version exacta) expone conteos tecnicos.
* `no enrutable` (inactiva o sin metadatos/routing) **no abre** el tenant y sus
  conteos quedan como no disponibles; la inactiva se lista y cuenta en el total.
* `no disponible` (tenant que no responde, version ausente/ilegible o
  incompatible) publica conteos no disponibles, **nunca cero**.
* Solo las asociaciones locales activas cuentan por rol; los Administradores
  inactivos se reportan en su metrica separada.
* Los agregados distinguen cantidades conocidas y no disponibles.
* El DTO no contiene datos personales, de negocio ni motivos.

SQLite simula el contexto logico unico; las costuras de sesion/version por tenant
se sustituyen para representar las tres clases. La verificacion real de
namespaces vive en `test_dashboard_tecnico_postgres_017.py`.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.main import app
from app.models import (
    Departamento,
    InstitucionControl,
    MapaUsuarioEsquema,
    Rol,
    Sede,
    Usuario,
)
from app.schemas.control_schema import (
    CLASE_NO_DISPONIBLE,
    CLASE_NO_ENRUTABLE,
    CLASE_OPERATIVO,
    DashboardSaaSRespuesta,
    InstitucionMetricasRespuesta,
)
from app.services import control_service, tenant_service
from app.services.auth_service import IdentidadAutenticada

_OPERATIVO = "INST-OP"
_INACTIVA = "INST-INACTIVA"
_SIN_RAIZ = "INST-SIN-RAIZ"
_NODISP = "INST-NODISP"
_NORESPONDE = "INST-NORESPONDE"

_ROLES = ("Administrador", "Bodeguero", "Solicitante")


# ---------------------------------------------------------------------------
# Sembrado del contexto logico
# ---------------------------------------------------------------------------


def _institucion(db, institucion_id: str, *, activo: bool = True) -> None:
    db.add(
        InstitucionControl(
            institucion_id=institucion_id,
            nombre=f"Institucion {institucion_id}",
            direccion="Sede de prueba",
            activo=activo,
        )
    )
    db.flush()


def _mapa(
    db,
    institucion_id: str,
    correo: str,
    *,
    activo: bool = True,
) -> None:
    db.add(
        MapaUsuarioEsquema(
            correo=correo,
            institucion_id=institucion_id,
            nombre_esquema=tenant_service.nombre_esquema_para_institucion(
                institucion_id
            ),
            activo=activo,
            estado_invitacion="aceptada",
        )
    )


def _usuario(
    db,
    institucion_id: str,
    correo: str,
    rol_id: int,
    departamento_id: int,
) -> Usuario:
    usuario = Usuario(
        nombre="Nombre",
        apellido="Apellido",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=rol_id,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _sembrar_mundo(db) -> dict[str, int]:
    """Cuatro instituciones que representan las tres clases de D-8."""
    _institucion(db, _OPERATIVO)
    _institucion(db, _INACTIVA, activo=False)
    _institucion(db, _SIN_RAIZ)
    _institucion(db, _NODISP)
    _institucion(db, _NORESPONDE)

    # `_SIN_RAIZ` queda sin mapa: resolucion de metadatos/routing falla.
    _mapa(db, _INACTIVA, "admin.inactiva@017.cl", activo=True)
    _mapa(db, _OPERATIVO, "admin.op@017.cl", activo=True)
    _mapa(db, _NODISP, "admin.nodisp@017.cl", activo=True)
    _mapa(db, _NORESPONDE, "admin.noresponde@017.cl", activo=True)

    roles: dict[str, int] = {}
    for nombre in _ROLES:
        rol = Rol(nombre_rol=nombre, descripcion=f"Rol {nombre}")
        db.add(rol)
        db.flush()
        roles[nombre] = rol.rol_id

    # Tenant operativo: 2 sedes, 2 departamentos y asociaciones activas/inactivas.
    departamento_uno = Departamento(
        nombre_dep="Operaciones",
        descripcion="Departamento uno",
        institucion_id=_OPERATIVO,
    )
    departamento_dos = Departamento(
        nombre_dep="Compras",
        descripcion="Departamento dos",
        institucion_id=_OPERATIVO,
    )
    db.add_all([departamento_uno, departamento_dos])
    db.flush()
    db.add_all(
        [
            Sede(nombre="Sede Central", institucion_id=_OPERATIVO),
            Sede(nombre="Sede Norte", institucion_id=_OPERATIVO),
        ]
    )

    _usuario(
        db,
        _OPERATIVO,
        "admin.op@017.cl",
        roles["Administrador"],
        departamento_uno.departamento_id,
    )
    # Administrador inactivo: se reporta separado y no cuenta como activo.
    _usuario(
        db,
        _OPERATIVO,
        "admin.inactivo@017.cl",
        roles["Administrador"],
        departamento_dos.departamento_id,
    )
    _mapa(db, _OPERATIVO, "admin.inactivo@017.cl", activo=False)
    _usuario(
        db,
        _OPERATIVO,
        "bodeguero.activo@017.cl",
        roles["Bodeguero"],
        departamento_uno.departamento_id,
    )
    _mapa(db, _OPERATIVO, "bodeguero.activo@017.cl", activo=True)
    # Bodeguero inactivo: no aparece en conteos por rol.
    _usuario(
        db,
        _OPERATIVO,
        "bodeguero.inactivo@017.cl",
        roles["Bodeguero"],
        departamento_uno.departamento_id,
    )
    _mapa(db, _OPERATIVO, "bodeguero.inactivo@017.cl", activo=False)
    _usuario(
        db,
        _OPERATIVO,
        "solicitante.activo@017.cl",
        roles["Solicitante"],
        departamento_dos.departamento_id,
    )
    _mapa(db, _OPERATIVO, "solicitante.activo@017.cl", activo=True)
    # Usuario sin asociacion local: tampoco cuenta.
    _usuario(
        db,
        _OPERATIVO,
        "sin.mapa@017.cl",
        roles["Solicitante"],
        departamento_dos.departamento_id,
    )

    db.commit()
    return roles


def _instalar_version_por_tenant(monkeypatch, versiones: dict[str, str | None]) -> None:
    monkeypatch.setattr(
        control_service,
        "_version_persistida_tenant",
        lambda _sesion, institucion_id: versiones.get(
            institucion_id, VERSION_ESQUEMA_OBJETIVO
        ),
    )


@pytest.fixture
def mundo(motor):
    db = sessionmaker(bind=motor)()
    try:
        roles = _sembrar_mundo(db)
        yield db, roles
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Taxonomia y conteos
# ---------------------------------------------------------------------------


def test_taxonomia_operativo_no_enrutable_y_no_disponible(mundo, monkeypatch):
    db, _roles = mundo
    _instalar_version_por_tenant(
        monkeypatch,
        {
            _OPERATIVO: VERSION_ESQUEMA_OBJETIVO,
            _NODISP: "000.0-incompatible",
            _NORESPONDE: None,
        },
    )

    resumen = control_service.dashboard_saas(db)

    assert resumen.total_instituciones == 5
    assert resumen.total_instituciones_activas == 4
    por_id = {fila.institucion_id: fila for fila in resumen.instituciones}
    assert set(por_id) == {_OPERATIVO, _INACTIVA, _SIN_RAIZ, _NODISP, _NORESPONDE}

    assert por_id[_OPERATIVO].estado_tecnico == CLASE_OPERATIVO
    assert por_id[_OPERATIVO].version_persistida == VERSION_ESQUEMA_OBJETIVO
    assert por_id[_OPERATIVO].version_objetivo == VERSION_ESQUEMA_OBJETIVO
    assert por_id[_OPERATIVO].sedes == 2
    assert por_id[_OPERATIVO].departamentos == 2

    # Inactiva: se lista y cuenta en el total, sin conteos de su tenant.
    inactiva = por_id[_INACTIVA]
    assert inactiva.activo is False
    assert inactiva.estado_tecnico == CLASE_NO_ENRUTABLE
    assert inactiva.sedes is None
    assert inactiva.departamentos is None
    assert inactiva.usuarios_por_rol is None

    # Activa sin mapa: no enrutable, sin abrir tenant.
    sin_raiz = por_id[_SIN_RAIZ]
    assert sin_raiz.activo is True
    assert sin_raiz.estado_tecnico == CLASE_NO_ENRUTABLE
    assert sin_raiz.sedes is None

    # Version incompatible / ausente: no disponible, nunca cero.
    assert por_id[_NODISP].estado_tecnico == CLASE_NO_DISPONIBLE
    assert por_id[_NODISP].version_persistida == "000.0-incompatible"
    assert por_id[_NODISP].sedes is None
    assert por_id[_NODISP].departamentos is None
    assert por_id[_NODISP].usuarios_por_rol is None
    assert por_id[_NORESPONDE].estado_tecnico == CLASE_NO_DISPONIBLE
    assert por_id[_NORESPONDE].version_persistida is None
    assert por_id[_NORESPONDE].sedes is None

    # Agregados: solo el operativo aporta cifras conocidas.
    assert resumen.conteos_conocidos == 1
    assert resumen.conteos_no_disponibles == 4
    assert resumen.total_administradores_activos == 1
    assert resumen.total_administradores_inactivos == 1
    assert resumen.usuarios_por_rol == {"Bodeguero": 1, "Solicitante": 1}


def test_conteos_por_rol_solo_asociaciones_activas_y_administradores_separados(
    mundo, monkeypatch
):
    db, _roles = mundo
    _instalar_version_por_tenant(
        monkeypatch, {_OPERATIVO: VERSION_ESQUEMA_OBJETIVO}
    )

    resumen = control_service.dashboard_saas(db)
    operativo = next(
        fila for fila in resumen.instituciones if fila.institucion_id == _OPERATIVO
    )

    assert operativo.administradores_activos == 1
    assert operativo.administradores_inactivos == 1
    # El rol Administrador no se duplica en `usuarios_por_rol`; el usuario sin
    # mapa y el Bodeguero inactivo no cuentan.
    assert operativo.usuarios_por_rol == {"Bodeguero": 1, "Solicitante": 1}


def test_no_enrutable_no_abre_el_tenant(mundo, monkeypatch):
    db, _roles = mundo
    _instalar_version_por_tenant(
        monkeypatch, {_OPERATIVO: VERSION_ESQUEMA_OBJETIVO}
    )
    abiertos: list[str] = []

    @contextmanager
    def _abrir(_db, nombre_esquema):
        abiertos.append(nombre_esquema)
        yield _db

    monkeypatch.setattr(control_service, "_abrir_sesion_dashboard", _abrir)

    control_service.dashboard_saas(db)

    esquemas_abiertos = set(abiertos)
    assert tenant_service.nombre_esquema_para_institucion(_INACTIVA) not in (
        esquemas_abiertos
    )
    assert tenant_service.nombre_esquema_para_institucion(_SIN_RAIZ) not in (
        esquemas_abiertos
    )
    assert tenant_service.nombre_esquema_para_institucion(_OPERATIVO) in (
        esquemas_abiertos
    )


def test_tenant_que_no_responde_es_no_disponible_nunca_cero(mundo, monkeypatch):
    db, _roles = mundo
    _instalar_version_por_tenant(
        monkeypatch, {_OPERATIVO: VERSION_ESQUEMA_OBJETIVO}
    )

    @contextmanager
    def _abrir(_db, nombre_esquema):
        if nombre_esquema == tenant_service.nombre_esquema_para_institucion(
            _NORESPONDE
        ):
            raise RuntimeError("tenant no responde")
        yield _db

    monkeypatch.setattr(control_service, "_abrir_sesion_dashboard", _abrir)

    resumen = control_service.dashboard_saas(db)
    caido = next(
        fila for fila in resumen.instituciones if fila.institucion_id == _NORESPONDE
    )
    assert caido.estado_tecnico == CLASE_NO_DISPONIBLE
    assert caido.sedes is None
    assert caido.departamentos is None
    assert caido.usuarios_por_rol is None
    assert caido.administradores_activos is None
    assert caido.administradores_inactivos is None


def test_dto_tecnico_no_expone_datos_personales_ni_de_negocio():
    claves_institucion = set(InstitucionMetricasRespuesta.model_fields)
    claves_dashboard = set(DashboardSaaSRespuesta.model_fields)

    prohibidas = {
        "correo",
        "nombre_usuario",
        "apellido",
        "tickets",
        "ticket",
        "productos",
        "producto",
        "existencias",
        "stock",
        "movimientos",
        "motivo",
        "motivos",
        "catalogo",
        "inventario",
    }
    assert not (claves_institucion & prohibidas), claves_institucion & prohibidas
    assert not (claves_dashboard & prohibidas), claves_dashboard & prohibidas

    assert {
        "institucion_id",
        "nombre",
        "activo",
        "estado_tecnico",
        "version_objetivo",
        "version_persistida",
        "sedes",
        "departamentos",
        "administradores_activos",
        "administradores_inactivos",
        "usuarios_por_rol",
    } <= claves_institucion
    assert {
        "total_instituciones",
        "total_administradores_activos",
        "total_administradores_inactivos",
        "usuarios_por_rol",
        "conteos_conocidos",
        "conteos_no_disponibles",
        "instituciones",
    } <= claves_dashboard


# ---------------------------------------------------------------------------
# Contrato HTTP
# ---------------------------------------------------------------------------


def _identidad_superadmin() -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Super",
        apellido="Admin",
        correo="superadmin@017.cl",
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol="Superadmin")
    return IdentidadAutenticada(usuario=usuario, sub="sub-017-dashboard")


@contextmanager
def _cliente(motor, identidad=None):
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if identidad is not None:
        app.dependency_overrides[dependencies.get_current_user] = lambda: identidad
    try:
        with TestClient(app) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


def test_http_dashboard_publica_taxonomia_y_agregados(motor, mundo, monkeypatch):
    _instalar_version_por_tenant(
        monkeypatch,
        {
            _OPERATIVO: VERSION_ESQUEMA_OBJETIVO,
            _NODISP: "000.0-incompatible",
            _NORESPONDE: None,
        },
    )
    with _cliente(motor, _identidad_superadmin()) as cliente_http:
        respuesta = cliente_http.get("/api/v1/control/dashboard")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["total_instituciones"] == 5
    assert cuerpo["conteos_conocidos"] == 1
    assert cuerpo["conteos_no_disponibles"] == 4
    assert cuerpo["usuarios_por_rol"] == {"Bodeguero": 1, "Solicitante": 1}
    clases = {fila["institucion_id"]: fila["estado_tecnico"] for fila in cuerpo["instituciones"]}
    assert clases[_OPERATIVO] == CLASE_OPERATIVO
    assert clases[_INACTIVA] == CLASE_NO_ENRUTABLE
    assert clases[_NODISP] == CLASE_NO_DISPONIBLE
    assert "correo" not in cuerpo["instituciones"][0]
