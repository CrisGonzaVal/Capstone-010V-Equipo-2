"""T7 (Feature 012): CRUD organizacional por API — pruebas de comportamiento.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), sobre el
padron multiinstitucion compartido (`dos_instituciones`). Cubre la superficie
nueva del Administrador institucional (diseno-tecnico.md §1.2):

  * `POST   /api/v1/organizacion/sedes`
  * `PUT    /api/v1/organizacion/sedes/{sede_id}`
  * `PATCH  /api/v1/organizacion/sedes/{sede_id}/estado`
  * `GET    /api/v1/organizacion/departamentos`
  * `POST   /api/v1/organizacion/departamentos`
  * `PUT    /api/v1/organizacion/departamentos/{departamento_id}`
  * `PATCH  /api/v1/organizacion/departamentos/{departamento_id}/estado`
  * `PUT    /api/v1/usuarios/{usuario_id}`
  * `PATCH  /api/v1/usuarios/{usuario_id}/estado`

Trazabilidad AC (spec 012 §6): AC-6 (sedes + estado), AC-7 (departamentos),
AC-8 (usuarios locales vinculados a Clerk), AC-11 (desactivacion idempotente o
409 con motivo), AC-12 (aislamiento por tenant → 404) y AC-13 (contrato/matriz).

La matriz de roles se transcribe a mano (nunca se lee de `MATRIZ_PERMISOS`) para
que la prueba no sea tautologica.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.main import app
from app.models import (
    Departamento,
    DepartamentoEncargado,
    MapaUsuarioEsquema,
    Rol,
    Sede,
    Usuario,
)

from ._soporte_sede_011 import SIN_AUTENTICAR, exigir_operacion, exigir_ruta, identidad

# ---------------------------------------------------------------------------
# Contrato de rutas y roles (transcrito a mano desde el diseno tecnico §1.2)
# ---------------------------------------------------------------------------

RUTA_SEDES = "/api/v1/organizacion/sedes"
RUTA_SEDE = "/api/v1/organizacion/sedes/{sede_id}"
RUTA_SEDE_ESTADO = "/api/v1/organizacion/sedes/{sede_id}/estado"
RUTA_DEPARTAMENTOS = "/api/v1/organizacion/departamentos"
RUTA_DEPARTAMENTO = "/api/v1/organizacion/departamentos/{departamento_id}"
RUTA_DEPARTAMENTO_ESTADO = "/api/v1/organizacion/departamentos/{departamento_id}/estado"
RUTA_USUARIO = "/api/v1/usuarios/{usuario_id}"
RUTA_USUARIO_ESTADO = "/api/v1/usuarios/{usuario_id}/estado"

_ORGANIZACION = {"Administrador"}
_ADMINISTRATIVOS = {"Superadmin", "Administrador"}

OPERACIONES_012: tuple[tuple[str, str, set[str]], ...] = (
    ("POST", RUTA_SEDES, _ORGANIZACION),
    ("PUT", RUTA_SEDE, _ORGANIZACION),
    ("PATCH", RUTA_SEDE_ESTADO, _ORGANIZACION),
    ("GET", RUTA_DEPARTAMENTOS, _ORGANIZACION),
    ("POST", RUTA_DEPARTAMENTOS, _ORGANIZACION),
    ("PUT", RUTA_DEPARTAMENTO, _ORGANIZACION),
    ("PATCH", RUTA_DEPARTAMENTO_ESTADO, _ORGANIZACION),
    ("PUT", RUTA_USUARIO, _ADMINISTRATIVOS),
    ("PATCH", RUTA_USUARIO_ESTADO, _ADMINISTRATIVOS),
)

#: Roles que NO pueden administrar la organizacion institucional.
_ROLES_DENEGADOS_ORG = ("Bodeguero", "Solicitante", "Superadmin")
#: Roles que NO pueden editar/estado de usuarios locales.
_ROLES_DENEGADOS_USUARIO = ("Bodeguero", "Solicitante")

_CORREO = "sonda.crud012@compustock.cl"


# ---------------------------------------------------------------------------
# Cliente HTTP con la costura Clerk overrideada
# ---------------------------------------------------------------------------


@contextmanager
def _cliente(
    motor,
    rol=SIN_AUTENTICAR,
    *,
    departamento_id: int | None = None,
    usuario_id: int = 9999,
    correo: str = _CORREO,
    correo_en_clerk: bool = True,
):
    """`TestClient` del `app` real; la costura Clerk devuelve `correo_en_clerk`."""
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.obtener_verificador_correo_clerk] = (
        lambda: (lambda _correo: correo_en_clerk)
    )
    if rol is not SIN_AUTENTICAR:
        app.dependency_overrides[dependencies.get_current_user] = lambda: identidad(
            rol, departamento_id, usuario_id, None, correo
        )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers de sembrado y observacion
# ---------------------------------------------------------------------------


def _crear_departamento(motor, institucion_id: str, nombre: str) -> int:
    with sessionmaker(bind=motor)() as db:
        departamento = Departamento(
            nombre_dep=nombre,
            descripcion=f"Departamento {nombre}",
            institucion_id=institucion_id,
        )
        db.add(departamento)
        db.commit()
        db.refresh(departamento)
        return departamento.departamento_id


def _crear_usuario(motor, *, departamento_id, rol_nombre, correo) -> int:
    with sessionmaker(bind=motor)() as db:
        rol = (
            db.execute(select(Rol).where(Rol.nombre_rol == rol_nombre))
            .scalars()
            .first()
        )
        if rol is None:
            pytest.fail(f"la fixture no sembro el rol {rol_nombre}")
        usuario = Usuario(
            nombre="Sonda",
            apellido="Crud012",
            correo=correo,
            departamento_id=departamento_id,
            rol_id=rol.rol_id,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        return usuario.usuario_id


def _activo_de_sede(motor, sede_id: int) -> bool | None:
    with sessionmaker(bind=motor)() as db:
        sede = db.get(Sede, sede_id)
        return None if sede is None else sede.activo


def _activo_de_departamento(motor, departamento_id: int) -> bool | None:
    with sessionmaker(bind=motor)() as db:
        departamento = db.get(Departamento, departamento_id)
        return None if departamento is None else departamento.activo


def _mapa_activo(motor, correo: str) -> bool | None:
    with sessionmaker(bind=motor)() as db:
        mapa = db.get(MapaUsuarioEsquema, correo)
        return None if mapa is None else mapa.activo


def _contar(motor, entidad) -> int:
    with sessionmaker(bind=motor)() as db:
        return db.execute(select(func.count()).select_from(entidad)).scalar_one()


# ---------------------------------------------------------------------------
# AC-13: contrato y matriz
# ---------------------------------------------------------------------------


def test_matriz_declara_las_operaciones_organizacionales_012():
    for metodo, ruta, roles in OPERACIONES_012:
        exigir_operacion(metodo, ruta)
        from app.core import permisos

        assert set(permisos.MATRIZ_PERMISOS[(metodo, ruta)]) == roles, (metodo, ruta)
    # No se retira ni relaja ninguna operacion previa de la 011.
    from app.core import permisos

    assert permisos.MATRIZ_PERMISOS[("GET", "/api/v1/organizacion/sedes")] == {
        "Administrador"
    }


def test_openapi_publica_las_rutas_organizacionales_012():
    for metodo, ruta, _roles in OPERACIONES_012:
        exigir_ruta(ruta, metodo)


@pytest.mark.parametrize("rol", _ROLES_DENEGADOS_ORG)
def test_organizacion_denegada_a_roles_no_autorizados(motor, dos_instituciones, rol):
    with _cliente(
        motor, rol, departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(RUTA_SEDES, json={"nombre": "Sede X"})
    assert respuesta.status_code == 403, (rol, respuesta.text)


@pytest.mark.parametrize("rol", _ROLES_DENEGADOS_USUARIO)
def test_editar_usuario_denegado_a_no_administrativos(motor, dos_instituciones, rol):
    usuario_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]
    with _cliente(
        motor, rol, departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_USUARIO.format(usuario_id=usuario_id),
            json={
                "nombre": "X",
                "apellido": "Y",
                "departamento_id": dos_instituciones["departamento_id"],
                "rol_id": 1,
            },
        )
    assert respuesta.status_code == 403, (rol, respuesta.text)


def test_crud_organizacional_sin_sesion_responde_401(motor, dos_instituciones):
    with _cliente(motor) as cliente_http:
        respuesta = cliente_http.post(RUTA_SEDES, json={"nombre": "Sede X"})
    assert respuesta.status_code == 401, respuesta.text


# ---------------------------------------------------------------------------
# AC-6: sedes (creacion, edicion, estado)
# ---------------------------------------------------------------------------


def test_listar_sedes_expone_estado_activo(motor, dos_instituciones):
    crear = dos_instituciones["inst_propia"]
    _crear_sede_por_api(motor, dos_instituciones, "Sede Listada")
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        listado = cliente_http.get(RUTA_SEDES)
    assert listado.status_code == 200, listado.text
    filas = listado.json()
    assert filas, "debe haber al menos la sede creada"
    for fila in filas:
        assert fila["institucion_id"] == crear
        assert fila["activo"] is True


def test_crear_sede_responde_201_y_persiste(motor, dos_instituciones):
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_SEDES, json={"nombre": "Sede Nueva", "direccion": "Calle 1"}
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["nombre"] == "Sede Nueva"
    assert respuesta.json()["institucion_id"] == dos_instituciones["inst_propia"]


def test_crear_sede_duplicada_responde_409_sin_crear(motor, dos_instituciones):
    payload = {"nombre": "Sede Central"}
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        primera = cliente_http.post(RUTA_SEDES, json=payload)
        antes = _contar(motor, Sede)
        repetida = cliente_http.post(RUTA_SEDES, json=payload)
        despues = _contar(motor, Sede)
    assert primera.status_code == 201, primera.text
    assert repetida.status_code == 409, repetida.text
    assert despues == antes, "una sede homonima no debe duplicarse"


def test_editar_sede_actualiza_y_sede_ajena_responde_404(motor, dos_instituciones):
    propia = _crear_sede_por_api(motor, dos_instituciones, "Sede Editable")
    ajena = _crear_sede_ajena(motor, dos_instituciones)
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        propia_resp = cliente_http.put(
            RUTA_SEDE.format(sede_id=propia), json={"nombre": "Sede Renombrada"}
        )
        ajena_resp = cliente_http.put(
            RUTA_SEDE.format(sede_id=ajena), json={"nombre": "Intruso"}
        )
    assert propia_resp.status_code == 200, propia_resp.text
    assert propia_resp.json()["nombre"] == "Sede Renombrada"
    assert ajena_resp.status_code == 404, ajena_resp.text


def test_desactivar_sede_sin_dependencias_es_idempotente_y_reactivable(
    motor, dos_instituciones
):
    sede_id = _crear_sede_por_api(motor, dos_instituciones, "Sede Libre")
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        baja = cliente_http.patch(
            RUTA_SEDE_ESTADO.format(sede_id=sede_id), json={"activo": False}
        )
        repetida = cliente_http.patch(
            RUTA_SEDE_ESTADO.format(sede_id=sede_id), json={"activo": False}
        )
        alta = cliente_http.patch(
            RUTA_SEDE_ESTADO.format(sede_id=sede_id), json={"activo": True}
        )
    assert baja.status_code == 200 and baja.json()["activo"] is False, baja.text
    assert repetida.status_code == 200 and repetida.json()["activo"] is False
    assert alta.status_code == 200 and alta.json()["activo"] is True
    assert _activo_de_sede(motor, sede_id) is True


def test_desactivar_sede_con_dependencias_responde_409(motor, dos_instituciones):
    sede_id = _crear_sede_por_api(motor, dos_instituciones, "Sede Ocupada")
    # Un departamento activo queda asignado a la sede: desactivarla es inseguro.
    with sessionmaker(bind=motor)() as db:
        departamento = db.get(Departamento, dos_instituciones["departamento_id"])
        departamento.sede_id = sede_id
        db.commit()
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.patch(
            RUTA_SEDE_ESTADO.format(sede_id=sede_id), json={"activo": False}
        )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"], "el 409 debe explicar el motivo"
    assert _activo_de_sede(motor, sede_id) is True, "no debe cambiar el estado"


# ---------------------------------------------------------------------------
# AC-7: departamentos (listado, creacion, edicion, estado)
# ---------------------------------------------------------------------------


def test_listar_departamentos_solo_del_tenant(motor, dos_instituciones):
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.get(RUTA_DEPARTAMENTOS)
    assert respuesta.status_code == 200, respuesta.text
    ids = {fila["departamento_id"] for fila in respuesta.json()}
    assert dos_instituciones["departamento_id"] in ids
    assert dos_instituciones["departamento_ajeno_id"] not in ids
    for fila in respuesta.json():
        assert fila["institucion_id"] == dos_instituciones["inst_propia"]
        assert "activo" in fila and "sede_id" in fila


def test_crear_y_editar_departamento(motor, dos_instituciones):
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        creado = cliente_http.post(
            RUTA_DEPARTAMENTOS, json={"nombre_dep": "Logistica"}
        )
        assert creado.status_code == 201, creado.text
        departamento_id = creado.json()["departamento_id"]
        editado = cliente_http.put(
            RUTA_DEPARTAMENTO.format(departamento_id=departamento_id),
            json={"nombre_dep": "Logistica y Despacho"},
        )
    assert editado.status_code == 200, editado.text
    assert editado.json()["nombre_dep"] == "Logistica y Despacho"


def test_editar_departamento_ajeno_responde_404(motor, dos_instituciones):
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_DEPARTAMENTO.format(
                departamento_id=dos_instituciones["departamento_ajeno_id"]
            ),
            json={"nombre_dep": "Intruso"},
        )
    assert respuesta.status_code == 404, respuesta.text


def test_desactivar_departamento_sin_usuarios_es_idempotente(motor, dos_instituciones):
    departamento_id = _crear_departamento(
        motor, dos_instituciones["inst_propia"], "Departamento Vacio"
    )
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        baja = cliente_http.patch(
            RUTA_DEPARTAMENTO_ESTADO.format(departamento_id=departamento_id),
            json={"activo": False},
        )
        repetida = cliente_http.patch(
            RUTA_DEPARTAMENTO_ESTADO.format(departamento_id=departamento_id),
            json={"activo": False},
        )
    assert baja.status_code == 200 and baja.json()["activo"] is False, baja.text
    assert repetida.status_code == 200 and repetida.json()["activo"] is False
    assert _activo_de_departamento(motor, departamento_id) is False


def test_desactivar_departamento_con_usuarios_responde_409(motor, dos_instituciones):
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.patch(
            RUTA_DEPARTAMENTO_ESTADO.format(
                departamento_id=dos_instituciones["departamento_id"]
            ),
            json={"activo": False},
        )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]
    assert _activo_de_departamento(motor, dos_instituciones["departamento_id"]) is True


# ---------------------------------------------------------------------------
# AC-8/AC-12: usuarios locales (edicion y estado en el mapa)
# ---------------------------------------------------------------------------


def test_editar_usuario_actualiza_atributos(motor, dos_instituciones):
    usuario_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_USUARIO.format(usuario_id=usuario_id),
            json={
                "nombre": "Bodega Editada",
                "apellido": "Inst01",
                "departamento_id": dos_instituciones["departamento_id"],
                "rol_id": dos_instituciones["rol_bodeguero_id"],
            },
        )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["nombre"] == "Bodega Editada"


def test_editar_usuario_ajeno_responde_404(motor, dos_instituciones):
    ajeno = dos_instituciones["usuarios_inst02"]["Bodeguero"]
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_USUARIO.format(usuario_id=ajeno),
            json={
                "nombre": "Intruso",
                "apellido": "Ajeno",
                "departamento_id": dos_instituciones["departamento_id"],
                "rol_id": dos_instituciones["rol_bodeguero_id"],
            },
        )
    assert respuesta.status_code == 404, respuesta.text


def test_estado_usuario_persiste_en_mapa_y_es_idempotente(motor, dos_instituciones):
    usuario_id = dos_instituciones["usuarios_inst01"]["Solicitante"]
    correo = "solicitante.inst01@compustock.cl"
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        baja = cliente_http.patch(
            RUTA_USUARIO_ESTADO.format(usuario_id=usuario_id), json={"activo": False}
        )
        repetida = cliente_http.patch(
            RUTA_USUARIO_ESTADO.format(usuario_id=usuario_id), json={"activo": False}
        )
        alta = cliente_http.patch(
            RUTA_USUARIO_ESTADO.format(usuario_id=usuario_id), json={"activo": True}
        )
    assert baja.status_code == 200 and baja.json()["activo"] is False, baja.text
    assert repetida.status_code == 200 and repetida.json()["activo"] is False
    assert alta.status_code == 200 and alta.json()["activo"] is True
    assert _mapa_activo(motor, correo) is True


def test_desactivar_usuario_encargado_responde_409(motor, dos_instituciones):
    usuario_id = dos_instituciones["usuarios_inst01"]["Solicitante"]
    with sessionmaker(bind=motor)() as db:
        db.add(
            DepartamentoEncargado(
                departamento_id=dos_instituciones["departamento_id"],
                usuario_id=usuario_id,
            )
        )
        db.commit()
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.patch(
            RUTA_USUARIO_ESTADO.format(usuario_id=usuario_id), json={"activo": False}
        )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# AC-8/D-3: alta local valida Clerk (sin crear identidades)
# ---------------------------------------------------------------------------


def test_alta_usuario_con_correo_inexistente_en_clerk_responde_422(motor, datos_base):
    correo = "no.existe.en.clerk@compustock.cl"
    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos_base["departamento_id"],
        correo_en_clerk=False,
    ) as cliente_http:
        respuesta = cliente_http.post(
            "/api/v1/usuarios/",
            json={
                "nombre": "Sin",
                "apellido": "Clerk",
                "correo": correo,
                "departamento_id": datos_base["departamento_id"],
                "rol_id": datos_base["rol_bodeguero_id"],
            },
        )
    assert respuesta.status_code == 422, respuesta.text
    assert _mapa_activo(motor, correo) is None
    with sessionmaker(bind=motor)() as db:
        assert (
            db.query(Usuario).filter(Usuario.correo == correo).first() is None
        ), "no debe quedar un usuario local no autenticable"


def test_alta_usuario_con_correo_existente_en_clerk_responde_201(motor, datos_base):
    correo = "existe.en.clerk@compustock.cl"
    with _cliente(
        motor,
        "Administrador",
        departamento_id=datos_base["departamento_id"],
        correo_en_clerk=True,
    ) as cliente_http:
        respuesta = cliente_http.post(
            "/api/v1/usuarios/",
            json={
                "nombre": "Con",
                "apellido": "Clerk",
                "correo": correo,
                "departamento_id": datos_base["departamento_id"],
                "rol_id": datos_base["rol_bodeguero_id"],
            },
        )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["correo"] == correo
    # Correccion T13: el alta registra la vinculacion local activa (D-3), de modo
    # que el correo resuelve a su tenant; sin ella el usuario no seria autenticable.
    assert _mapa_activo(motor, correo) is True


# ---------------------------------------------------------------------------
# AC-8/AC-9 (T12): el listado publica estado local y sede
# ---------------------------------------------------------------------------


def _fijar_mapa(motor, correo: str, institucion_id: str, activo: bool) -> None:
    with sessionmaker(bind=motor)() as db:
        db.merge(
            MapaUsuarioEsquema(
                correo=correo,
                institucion_id=institucion_id,
                nombre_esquema="tenant_sonda",
                activo=activo,
            )
        )
        db.commit()


def test_listado_usuarios_publica_estado_y_sede(motor, dos_instituciones):
    """El listado ya no deja la vista en "Estado no informado" (T12)."""
    usuario_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        listado = cliente_http.get("/api/v1/usuarios/")
    assert listado.status_code == 200, listado.text
    filas = {fila["usuario_id"]: fila for fila in listado.json()}
    assert usuario_id in filas
    fila = filas[usuario_id]
    assert "activo" in fila and fila["activo"] is True
    assert "sede_id" in fila and fila["sede_id"] is None


def test_listado_usuarios_refleja_el_mapa_inactivo(motor, dos_instituciones):
    usuario_id = dos_instituciones["usuarios_inst01"]["Solicitante"]
    _fijar_mapa(
        motor,
        "solicitante.inst01@compustock.cl",
        dos_instituciones["institucion_id"],
        activo=False,
    )
    with _cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        listado = cliente_http.get("/api/v1/usuarios/")
    assert listado.status_code == 200, listado.text
    filas = {fila["usuario_id"]: fila for fila in listado.json()}
    assert filas[usuario_id]["activo"] is False
    # Sin fila en el mapa la ausencia no es desactivacion explicita (D-6).
    assert filas[dos_instituciones["usuarios_inst01"]["Bodeguero"]]["activo"] is True


# ---------------------------------------------------------------------------
# Helpers internos de sembrado por API
# ---------------------------------------------------------------------------


def _crear_sede_por_api(motor, datos, nombre: str) -> int:
    with _cliente(
        motor, "Administrador", departamento_id=datos["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.post(RUTA_SEDES, json={"nombre": nombre})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["sede_id"]


def _crear_sede_ajena(motor, datos) -> int:
    with sessionmaker(bind=motor)() as db:
        sede = Sede(nombre="Sede Ajena", institucion_id=datos["inst_ajena"])
        db.add(sede)
        db.commit()
        db.refresh(sede)
        return sede.sede_id
