"""T6 (Feature 019): aislamiento tenant del detalle de producto (gated PG16).

Cierra la evidencia que la suite SQLite no puede acreditar (spec AC-2/AC-13 y
plan §1.3 «PostgreSQL 16 gated»). En SQLite existe un unico contexto logico y
un producto ajeno convive en la misma tabla; en PostgreSQL cada tenant vive en
su propio esquema, de modo que el mismo `producto_id` **es un recurso distinto**
segun el esquema del actor. Esta prueba fija esa semantica sobre PostgreSQL 16
real:

  * **AC-2**: el Administrador de A y el de B piden el **mismo** `producto_id`
    (secuencias por esquema, ambas arrancan en 1) y reciben **su** producto: el
    nombre es homonimo a proposito, pero descripcion, unidad, minimo, total y
    desglose de sedes son los del tenant que consulta. La respuesta de A no
    contiene ninguna sede de B ni al reves.
  * **AC-2**: el Bodeguero de A ve solo su sede asignada, aunque el producto
    tenga saldo en otras sedes de A; ninguna sede del tenant B aparece.
  * **AC-2/AC-13**: un identificador que **solo existe en B** responde **404**
    para A -indistinguible de uno inexistente- y **200** para B, lo que demuestra
    que el 404 no es un falso positivo por ausencia de datos.
  * **AC-2**: la sede inactiva de A forma parte del desglose y suma al total,
    mientras que las sedes de B (incluidas sus homonimas «Sede Central») no.

COMO ACTIVARLA
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_detalle_producto_postgres_019.py

    Sin `POSTGRES_TEST_URL` la prueba se **salta** con una razon clara y la
    suite ordinaria no cambia. La URL apunta a una base de mantenimiento donde
    el modulo crea y DESTRUYE una base temporal propia con guardia fail-closed;
    nunca toca `apt_erp`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app.api import dependencies
from app.core import security
from app.core.config import VERSION_ESQUEMA_OBJETIVO
from app.db.database import (
    Base,
    ESQUEMA_CONTROL,
    crear_sesion_control,
    crear_sesion_esquema,
)
from app.main import app
from app.models import (
    BaseControl,
    Categoria,
    Departamento,
    MapaUsuarioEsquema,
    Producto,
    Rol,
    Sede,
    StockSede,
    Usuario,
    VersionEsquema,
)
from app.schemas.control_schema import InstitucionAltaControlCrear
from app.services import control_service, tenant_service
from app.services.auth_service import IdentidadAutenticada

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

#: Lectura de detalle de producto por alcance (Feature 019, §8).
_RUTA_DETALLE = "/api/v1/inventario/existencias/{producto_id}"

_INSTITUCION_A = "INST-019A"
_INSTITUCION_B = "INST-019B"
_CORREO_ADMIN_A = "admin.a@019.cl"
_CORREO_ADMIN_B = "admin.b@019.cl"
_CORREO_BODEGUERO_A = "bodega.a@019.cl"

_NOMBRE_SEDE_INICIAL = control_service.NOMBRE_SEDE_CENTRAL

#: Nombre **homonimo** en ambos esquemas: el discriminador no es el nombre, sino
#: el esquema que el mapa de control resuelve para el correo del actor.
_NOMBRE_PRODUCTO_COMPARTIDO = "Resma Compartida 019"


def _url_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


# ---------------------------------------------------------------------------
# Base temporal (nunca `apt_erp`) y utilidades de siembra
# ---------------------------------------------------------------------------


@contextmanager
def _base_temporal():
    """Crea una base PostgreSQL efimera y la destruye al salir (fail-closed)."""
    dsn = (_POSTGRES_TEST_URL or "").replace("postgresql+psycopg2://", "postgresql://")
    # Guardia fail-closed: la base de mantenimiento no puede ser la base QA.
    assert "/apt_erp" not in dsn, "POSTGRES_TEST_URL apunta a `apt_erp`"
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    nombre = f"compustock_019t6_{uuid4().hex[:12]}"
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{nombre}"')
    partes = urlsplit(dsn)
    url = urlunsplit((partes.scheme, partes.netloc, "/" + nombre, "", ""))
    try:
        yield url
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (nombre,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{nombre}"')
        admin.close()


def _datos(institucion_id: str, nombre: str, correo: str) -> InstitucionAltaControlCrear:
    return InstitucionAltaControlCrear(
        institucion_id=institucion_id,
        nombre=nombre,
        correo_administrador=correo,
        nombre_administrador="Ada",
        apellido_administrador="Administradora",
        departamento_nombre_administrativo=f"Administracion {institucion_id}",
    )


def _sesion_tenant(engine, institucion_id: str) -> Session:
    return crear_sesion_esquema(
        tenant_service.nombre_esquema_para_institucion(institucion_id),
        motor=engine,
    )


def _crear_sede(
    sesion: Session,
    institucion_id: str,
    nombre: str,
    *,
    activo: bool = True,
) -> int:
    """Sede del tenant; el id lo asigna la secuencia **de ese esquema**."""
    sede = Sede(nombre=nombre, institucion_id=institucion_id, activo=activo)
    sesion.add(sede)
    sesion.flush()
    return sede.sede_id


def _crear_departamento(
    sesion: Session, institucion_id: str, nombre: str, sede_id: int | None
) -> int:
    departamento = Departamento(
        nombre_dep=nombre,
        descripcion=f"Departamento de prueba {nombre}",
        institucion_id=institucion_id,
        sede_id=sede_id,
    )
    sesion.add(departamento)
    sesion.flush()
    return departamento.departamento_id


def _crear_categoria(sesion: Session, institucion_id: str, nombre: str) -> int:
    categoria = Categoria(
        nombre_cat=nombre,
        descripcion_cat=f"Categoria de prueba {nombre}",
        institucion_id=institucion_id,
    )
    sesion.add(categoria)
    sesion.flush()
    return categoria.categoria_id


def _crear_producto_con_saldo(
    sesion: Session,
    institucion_id: str,
    *,
    categoria_id: int,
    nombre: str,
    descripcion: str,
    unidad_medida: str,
    stock_minimo: int,
    saldos: dict[int, int] | None = None,
) -> int:
    """Producto del tenant con una fila de `stock_sede` por sede indicada."""
    producto = Producto(
        nombre=nombre,
        descripcion=descripcion,
        unidad_medida=unidad_medida,
        stock_minimo=stock_minimo,
        categoria_id=categoria_id,
        institucion_id=institucion_id,
    )
    sesion.add(producto)
    sesion.flush()
    for sede_id, cantidad in (saldos or {}).items():
        sesion.add(
            StockSede(
                stock_actual=cantidad,
                sede_id=sede_id,
                producto_id=producto.producto_id,
                institucion_id=institucion_id,
            )
        )
    sesion.flush()
    return producto.producto_id


def _crear_bodeguero(
    sesion: Session,
    *,
    correo: str,
    departamento_id: int,
    sede_id: int,
) -> int:
    rol = sesion.execute(
        select(Rol).where(Rol.nombre_rol == "Bodeguero")
    ).scalar_one()
    usuario = Usuario(
        nombre="Bode",
        apellido="Guero",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=rol.rol_id,
        sede_id=sede_id,
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario.usuario_id


def _registrar_mapa(engine, institucion_id: str, correo: str) -> None:
    """Vincula el correo del Bodeguero a su tenant en el mapa de control (D-3)."""
    sesion = crear_sesion_control(engine)
    try:
        sesion.add(
            MapaUsuarioEsquema(
                correo=security.normalizar_correo(correo),
                institucion_id=institucion_id,
                nombre_esquema=tenant_service.nombre_esquema_para_institucion(
                    institucion_id
                ),
                activo=True,
                estado_invitacion="aceptada",
            )
        )
        sesion.commit()
    finally:
        sesion.close()


def _sembrar_tenant_a(engine) -> dict[str, int]:
    """Tenant A: producto compartido con saldo en 3 sedes (una inactiva).

    La primera entidad de catalogo que se crea es el producto compartido, de
    modo que su `producto_id` es el **mismo numero** que el del tenant B: la
    secuencia de `producto` es propia de cada esquema y ambas arrancan en 1.
    """
    sesion = _sesion_tenant(engine, _INSTITUCION_A)
    try:
        sede_inicial = sesion.execute(
            select(Sede.sede_id).where(Sede.nombre == _NOMBRE_SEDE_INICIAL)
        ).scalar_one()
        sede_norte = _crear_sede(sesion, _INSTITUCION_A, "Alfa Norte")
        # Sede desactivada: el detalle **no** filtra por `Sede.activo` (D-3/D-5).
        sede_inactiva = _crear_sede(
            sesion, _INSTITUCION_A, "Alfa Bodega Inactiva", activo=False
        )
        departamento = _crear_departamento(
            sesion, _INSTITUCION_A, "Alfa Almacen", sede_norte
        )
        categoria = _crear_categoria(sesion, _INSTITUCION_A, "Papeleria Alfa 019")
        compartido = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_A,
            categoria_id=categoria,
            nombre=_NOMBRE_PRODUCTO_COMPARTIDO,
            descripcion="Catalogo de Alfa 019",
            unidad_medida="UNIDAD",
            stock_minimo=2,
            saldos={sede_inicial: 3, sede_norte: 4, sede_inactiva: 5},
        )
        # Segundo producto de A: ocupa el id 2 de **este** esquema.
        solo_alfa = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_A,
            categoria_id=categoria,
            nombre="Solo Alfa 019",
            descripcion="Existe unicamente en Alfa",
            unidad_medida="UNIDAD",
            stock_minimo=1,
        )
        bodeguero = _crear_bodeguero(
            sesion,
            correo=_CORREO_BODEGUERO_A,
            departamento_id=departamento,
            sede_id=sede_norte,
        )
        sesion.commit()
        ids = {
            "sede_inicial": sede_inicial,
            "sede_norte": sede_norte,
            "sede_inactiva": sede_inactiva,
            "departamento": departamento,
            "categoria": categoria,
            "compartido": compartido,
            "solo_alfa": solo_alfa,
            "bodeguero": bodeguero,
        }
    finally:
        sesion.close()
    _registrar_mapa(engine, _INSTITUCION_A, _CORREO_BODEGUERO_A)
    return ids


def _sembrar_tenant_b(engine) -> dict[str, int]:
    """Tenant B: producto homonimo con otro catalogo, otra unidad y otro saldo.

    B crea **tres** productos: el compartido (id 1, igual que A), uno propio
    (id 2) y uno mas (id 3) que **no existe** en el esquema de A. Ese id es el
    que prueba que un recurso de B se oculta con 404 a A.
    """
    sesion = _sesion_tenant(engine, _INSTITUCION_B)
    try:
        sede_inicial = sesion.execute(
            select(Sede.sede_id).where(Sede.nombre == _NOMBRE_SEDE_INICIAL)
        ).scalar_one()
        sede_centro = _crear_sede(sesion, _INSTITUCION_B, "Beta Centro")
        sede_sur = _crear_sede(sesion, _INSTITUCION_B, "Beta Sur")
        categoria = _crear_categoria(sesion, _INSTITUCION_B, "Papeleria Beta 019")
        compartido = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_B,
            categoria_id=categoria,
            nombre=_NOMBRE_PRODUCTO_COMPARTIDO,
            descripcion="Catalogo de Beta 019",
            unidad_medida="CAJA",
            stock_minimo=10,
            saldos={sede_inicial: 50, sede_centro: 60, sede_sur: 70},
        )
        solo_beta = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_B,
            categoria_id=categoria,
            nombre="Solo Beta 019",
            descripcion="Existe unicamente en Beta",
            unidad_medida="CAJA",
            stock_minimo=1,
        )
        solo_beta_dos = _crear_producto_con_saldo(
            sesion,
            _INSTITUCION_B,
            categoria_id=categoria,
            nombre="Solo Beta Dos 019",
            descripcion="Existe unicamente en Beta (id 3 de este esquema)",
            unidad_medida="CAJA",
            stock_minimo=1,
            saldos={sede_sur: 2},
        )
        sesion.commit()
        return {
            "sede_inicial": sede_inicial,
            "sede_centro": sede_centro,
            "sede_sur": sede_sur,
            "categoria": categoria,
            "compartido": compartido,
            "solo_beta": solo_beta,
            "solo_beta_dos": solo_beta_dos,
        }
    finally:
        sesion.close()


def _identidad(
    correo: str,
    rol: str,
    *,
    departamento_id: int,
    sede_id: int | None = None,
) -> IdentidadAutenticada:
    """Identidad sintetica con el rol y la sede que lee el servicio (`getattr`)."""
    usuario = Usuario(
        usuario_id=1,
        nombre="Frontera",
        apellido="Gated",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
        sede_id=sede_id,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub=f"sub-{correo}")


@contextmanager
def _cliente(mundo, identidad: IdentidadAutenticada):
    """`TestClient` del `app` real con `get_db` atado a la base temporal.

    `get_db` cede la sesion de **control**; `get_db_negocio` resuelve el esquema
    del correo contra el mapa real de control y abre el tenant, igual que en
    produccion. Asi la frontera entre esquemas se ejecuta de verdad.
    """
    Fabrica = sessionmaker(bind=mundo["motor_control"])

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    app.dependency_overrides[dependencies.get_current_user] = lambda: identidad
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _detalle(cliente, producto_id: int):
    return cliente.get(_RUTA_DETALLE.format(producto_id=producto_id))


@pytest.fixture
def mundo_019():
    """`control` + dos tenants reales en esquemas separados, provisionados de verdad."""
    with _base_temporal() as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            # Guarda explicita: la base desechable nunca es `apt_erp`.
            assert engine.url.database.startswith("compustock_019t6_"), (
                engine.url.database
            )

            with engine.begin() as conexion:
                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            # El canonico de control (con `activo`/`funcion_institucion`) primero.
            BaseControl.metadata.create_all(bind=motor_control)
            Base.metadata.create_all(bind=motor_control)

            control = crear_sesion_control(engine)
            try:
                # El gating lee la version desde control: se siembra la objetivo.
                control.add(VersionEsquema(version=VERSION_ESQUEMA_OBJETIVO))
                control.flush()
                control_service.aprovisionar_institucion(
                    control,
                    _datos(_INSTITUCION_A, "Instituto Alfa 019", _CORREO_ADMIN_A),
                    lambda _correo: True,
                )
                control_service.aprovisionar_institucion(
                    control,
                    _datos(_INSTITUCION_B, "Instituto Beta 019", _CORREO_ADMIN_B),
                    lambda _correo: True,
                )
            finally:
                control.close()

            ids_a = _sembrar_tenant_a(engine)
            ids_b = _sembrar_tenant_b(engine)

            # Guardia del escenario: el id compartido es **el mismo numero** en
            # ambos esquemas y el tercer producto es exclusivo de B.
            assert ids_a["compartido"] == ids_b["compartido"], (
                ids_a["compartido"],
                ids_b["compartido"],
            )
            assert ids_b["solo_beta_dos"] not in (
                ids_a["compartido"],
                ids_a["solo_alfa"],
            ), "el id exclusivo de B no debe existir en A"

            yield {
                "engine": engine,
                "motor_control": motor_control,
                "ids_a": ids_a,
                "ids_b": ids_b,
                # Los departamentos administrativos iniciales son la id 1 en
                # ambos esquemas: la institucion se resuelve por esa fila.
                "identidad_admin_a": _identidad(
                    _CORREO_ADMIN_A, "Administrador", departamento_id=1
                ),
                "identidad_admin_b": _identidad(
                    _CORREO_ADMIN_B, "Administrador", departamento_id=1
                ),
                "identidad_bodeguero_a": _identidad(
                    _CORREO_BODEGUERO_A,
                    "Bodeguero",
                    departamento_id=ids_a["departamento"],
                    sede_id=ids_a["sede_norte"],
                ),
            }
        finally:
            engine.dispose()


# ===========================================================================
# AC-2/AC-13: el mismo `producto_id` es un recurso distinto por esquema
# ===========================================================================


def test_detalle_de_producto_no_mezcla_tenants_ajenos(mundo_019):
    """AC-2/AC-13: A y B piden el mismo id y cada uno recibe **su** producto.

    Homonomia deliberada: el nombre del producto, el nombre de la categoria y
    el `producto_id` son identicos en ambos esquemas. El discriminador real es
    el esquema que `get_db_negocio` resuelve para el correo del actor, asi que
    la prueba seria si -y solo si- los datos que vuelven son los sembrados en
    cada tenant: descripcion, unidad, minimo, total y desglose de sedes.
    """
    ids_a = mundo_019["ids_a"]
    ids_b = mundo_019["ids_b"]
    producto_id = ids_a["compartido"]

    with _cliente(mundo_019, mundo_019["identidad_admin_a"]) as cliente_a:
        detalle_a = _detalle(cliente_a, producto_id)
        solo_en_b = _detalle(cliente_a, ids_b["solo_beta_dos"])
        inexistente = _detalle(cliente_a, 999_999)

    with _cliente(mundo_019, mundo_019["identidad_admin_b"]) as cliente_b:
        detalle_b = _detalle(cliente_b, producto_id)
        propio_de_b = _detalle(cliente_b, ids_b["solo_beta_dos"])

    # --- Administrador de A: solo el catalogo y el saldo de A ----------------
    assert detalle_a.status_code == 200, detalle_a.text
    cuerpo_a = detalle_a.json()
    assert cuerpo_a["producto_id"] == producto_id
    assert cuerpo_a["nombre"] == _NOMBRE_PRODUCTO_COMPARTIDO, "homonimo por diseno"
    assert cuerpo_a["institucion_id"] == _INSTITUCION_A
    assert cuerpo_a["descripcion"] == "Catalogo de Alfa 019"
    assert cuerpo_a["unidad_medida"] == "UNIDAD"
    assert cuerpo_a["stock_minimo"] == 2
    assert cuerpo_a["categoria_nombre"] == "Papeleria Alfa 019"
    # Tres sedes de A, **incluida la inactiva** (D-3/D-5), orden `(nombre, id)`.
    assert [(s["sede_nombre"], s["stock_actual"]) for s in cuerpo_a["sedes"]] == [
        ("Alfa Bodega Inactiva", 5),
        ("Alfa Norte", 4),
        ("Sede Central", 3),
    ]
    assert cuerpo_a["stock_total"] == 12, "3 + 4 + 5, solo saldo de Alfa"
    # Ningun dato de B: ni institucion, ni catalogo, ni sedes propias de B.
    assert _INSTITUCION_B not in detalle_a.text
    nombres_sedes_a = {s["sede_nombre"] for s in cuerpo_a["sedes"]}
    assert not {"Beta Centro", "Beta Sur"} & nombres_sedes_a
    assert "Catalogo de Beta 019" not in detalle_a.text
    assert "CAJA" not in detalle_a.text

    # --- Administrador de B: el mismo id resuelve a **otro** producto --------
    assert detalle_b.status_code == 200, detalle_b.text
    cuerpo_b = detalle_b.json()
    assert cuerpo_b["producto_id"] == producto_id, "misma secuencia por esquema"
    assert cuerpo_b["nombre"] == _NOMBRE_PRODUCTO_COMPARTIDO, "homonimo por diseno"
    assert cuerpo_b["institucion_id"] == _INSTITUCION_B
    assert cuerpo_b["descripcion"] == "Catalogo de Beta 019"
    assert cuerpo_b["unidad_medida"] == "CAJA"
    assert cuerpo_b["stock_minimo"] == 10
    assert [s["sede_nombre"] for s in cuerpo_b["sedes"]] == [
        "Beta Centro",
        "Beta Sur",
        "Sede Central",
    ]
    assert cuerpo_b["stock_total"] == 180, "50 + 60 + 70, solo saldo de Beta"
    assert _INSTITUCION_A not in detalle_b.text
    assert "Alfa Norte" not in detalle_b.text
    assert not {"Alfa Bodega Inactiva", "Alfa Norte"} & {
        s["sede_nombre"] for s in cuerpo_b["sedes"]
    }
    # Ambos esquemas tienen la «Sede Central» con el id 1; el saldo difiere y
    # prueba que cada uno leyo su propia fila.
    central_a = next(
        s for s in cuerpo_a["sedes"] if s["sede_nombre"] == _NOMBRE_SEDE_INICIAL
    )
    central_b = next(
        s for s in cuerpo_b["sedes"] if s["sede_nombre"] == _NOMBRE_SEDE_INICIAL
    )
    assert central_a["sede_id"] == central_b["sede_id"] == ids_a["sede_inicial"]
    assert central_a["stock_actual"] == 3
    assert central_b["stock_actual"] == 50

    # --- Un id que solo existe en B: 404 para A, 200 para B ------------------
    assert solo_en_b.status_code == 404, solo_en_b.text
    assert solo_en_b.json()["detail"] == inexistente.json()["detail"], (
        "el 404 de un recurso de otro tenant es indistinguible del inexistente"
    )
    assert propio_de_b.status_code == 200, propio_de_b.text
    assert propio_de_b.json()["nombre"] == "Solo Beta Dos 019"
    assert propio_de_b.json()["institucion_id"] == _INSTITUCION_B

    # --- Bodeguero de A: solo su sede, aunque el producto tenga mas saldo ----
    with _cliente(mundo_019, mundo_019["identidad_bodeguero_a"]) as cliente_bodega:
        detalle_bodeguero = _detalle(cliente_bodega, producto_id)

    assert detalle_bodeguero.status_code == 200, detalle_bodeguero.text
    cuerpo_bodeguero = detalle_bodeguero.json()
    assert cuerpo_bodeguero["institucion_id"] == _INSTITUCION_A
    assert [(s["sede_id"], s["stock_actual"]) for s in cuerpo_bodeguero["sedes"]] == [
        (ids_a["sede_norte"], 4)
    ]
    assert cuerpo_bodeguero["stock_total"] == 4, "solo la sede asignada"
    # La sede inactiva de A y las sedes de B quedan fuera del alcance operativo.
    assert ids_a["sede_inactiva"] not in {
        s["sede_id"] for s in cuerpo_bodeguero["sedes"]
    }
    assert _INSTITUCION_B not in detalle_bodeguero.text
    assert not {"Beta Centro", "Beta Sur"} & {
        s["sede_nombre"] for s in cuerpo_bodeguero["sedes"]
    }
