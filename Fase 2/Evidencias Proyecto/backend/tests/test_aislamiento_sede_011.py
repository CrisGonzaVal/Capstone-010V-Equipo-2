"""M3 (Feature 011): aislamiento cross-schema de sede entre tenants (gated).

Cierra la evidencia que la suite SQLite no puede acreditar: SQLite tiene un unico
contexto logico y no reproduce namespaces, asi que la frontera real entre el
esquema de dos instituciones solo se observa contra PostgreSQL 16.

Se monta `control` + dos esquemas tenant en una base efimera y se verifica, por
la **interfaz HTTP real** (la resolucion de `get_db_negocio` se ejecuta de verdad
contra el mapa de control):

  * AC-1: una sede creada en Tenant A no aparece en `GET /organizacion/sedes`
    de Tenant B.
  * AC-3: usar el `sede_id` de A desde una identidad de B responde **404** sin
    mutacion, tanto al asignar una sede a un departamento como al consultar el
    saldo por sede (`GET /inventario/stock`).

COMO ACTIVARLA
    docker compose -f docker-compose.yml up -d db
    $env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"
    cd backend; python -m pytest tests/test_aislamiento_sede_011.py

    Sin `POSTGRES_TEST_URL` la prueba se **salta**. La URL apunta a una base de
    mantenimiento donde el modulo crea y DESTRUYE bases/esquemas temporales
    propios; nunca toca `apt_erp`.
"""

from __future__ import annotations

import importlib
import os

import pytest

try:  # `psycopg2` es dependencia declarada; el guard evita un error de coleccion.
    import psycopg2  # noqa: F401

    _PSYCOPG2_DISPONIBLE = True
except ImportError:  # pragma: no cover - entorno sin la dependencia
    _PSYCOPG2_DISPONIBLE = False

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base, ESQUEMA_CONTROL

# La infraestructura temporal y el cliente HTTP real ya viven en el modulo gated
# de la 010; se reutilizan para no duplicarlos.
from tests.test_integracion_multitenant_010 import (
    _base_temporal,
    _cliente_http,
    _esquema,
    _sembrar_control,
    _sembrar_tenant,
    _url_sqlalchemy,
)

_POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL")

pytestmark = pytest.mark.skipif(
    not _POSTGRES_TEST_URL or not _PSYCOPG2_DISPONIBLE,
    reason=(
        "Requiere PostgreSQL 16 real: exporta POSTGRES_TEST_URL="
        "postgresql://postgres:postgres@localhost:5433/postgres y levanta el "
        "contenedor `db` (docker compose up -d db)."
    ),
)

_CORREO_A = "u.inst-a@t.cl"
_CORREO_B = "t.b@inst-b.cl"


def _identidad(modelos, correo: str, departamento_id: int, sub: str):
    """Identidad Administrador con su rol y departamento del tenant."""
    from app.services.auth_service import IdentidadAutenticada

    usuario = modelos.Usuario(
        usuario_id=1,
        nombre="Admin",
        apellido="Tenant",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
    )
    usuario.rol = modelos.Rol(nombre_rol="Administrador")
    return IdentidadAutenticada(usuario=usuario, sub=sub)


@pytest.fixture
def mundo_dos_tenants():
    """`control` + dos tenants: A con dos sedes, B con su "Sede Central".

    La segunda sede de A tiene id 2, que **no existe** en el esquema de B (su
    unica sede es la "Sede Central" con id 1). Asi el `sede_id` de A es
    genuinamente ajeno para B y no una colision de secuencia.
    """
    modelos = importlib.import_module("app.models")
    with _base_temporal(_POSTGRES_TEST_URL) as url:
        engine = create_engine(_url_sqlalchemy(url), future=True)
        try:
            with engine.begin() as conexion:
                from sqlalchemy.schema import CreateSchema

                conexion.execute(CreateSchema(ESQUEMA_CONTROL))
            motor_control = engine.execution_options(
                schema_translate_map={None: ESQUEMA_CONTROL}
            )
            Base.metadata.create_all(bind=motor_control)

            with _esquema(engine, "tenant_a") as (esq_a, motor_a):
                with _esquema(engine, "tenant_b") as (esq_b, motor_b):
                    ids_a = _sembrar_tenant(motor_a, "INST-A", "Instituto Alfa", stock=9)
                    ids_b = _sembrar_tenant(motor_b, "INST-B", "Instituto Beta", stock=3)

                    with Session(bind=motor_a) as sesion_a:
                        sede_extra = modelos.Sede(
                            nombre="Sede Alfa 2", institucion_id="INST-A"
                        )
                        sesion_a.add(sede_extra)
                        sesion_a.commit()
                        sede_ajena_id = sede_extra.sede_id

                    _sembrar_control(motor_control, esq_a, "INST-A", esq_b, "INST-B")

                    sesion_control = Session(bind=motor_control)
                    try:
                        yield {
                            "control": sesion_control,
                            "motor_control": motor_control,
                            "esq_a": esq_a,
                            "esq_b": esq_b,
                            "motor_a": motor_a,
                            "motor_b": motor_b,
                            "ids_a": ids_a,
                            "ids_b": ids_b,
                            "sede_ajena_id": sede_ajena_id,
                            "identidad_a": _identidad(
                                modelos, _CORREO_A, ids_a["departamento_id"], "sub-a"
                            ),
                            "identidad_b": _identidad(
                                modelos, _CORREO_B, ids_b["departamento_id"], "sub-b"
                            ),
                        }
                    finally:
                        sesion_control.close()
        finally:
            engine.dispose()


def test_sede_de_a_no_aparece_en_b_y_su_id_responde_404_sin_mutar(mundo_dos_tenants):
    """AC-1/AC-3: la sede de A es invisible e inutilizable desde B."""
    from app.api import dependencies

    mundo = mundo_dos_tenants
    sede_ajena = mundo["sede_ajena_id"]

    # Tenant A ve sus dos sedes (la suya y la extra).
    with _cliente_http(
        mundo, {dependencies.get_current_user: lambda: mundo["identidad_a"]}
    ) as cliente_a:
        sedes_a = cliente_a.get("/api/v1/organizacion/sedes")
    assert sedes_a.status_code == 200, sedes_a.text
    assert sede_ajena in {s["sede_id"] for s in sedes_a.json()}

    # Tenant B no ve la sede de A.
    with _cliente_http(
        mundo, {dependencies.get_current_user: lambda: mundo["identidad_b"]}
    ) as cliente_b:
        sedes_b = cliente_b.get("/api/v1/organizacion/sedes")
        assert sedes_b.status_code == 200, sedes_b.text
        assert sede_ajena not in {s["sede_id"] for s in sedes_b.json()}

        # Asignar la sede de A a un departamento de B responde 404.
        asignar = cliente_b.put(
            f"/api/v1/organizacion/departamentos/{mundo['ids_b']['departamento_id']}/sede",
            json={"sede_id": sede_ajena},
        )
        # Consultar el saldo de la sede de A desde B responde 404.
        consultar = cliente_b.get(
            "/api/v1/inventario/stock", params={"sede_id": sede_ajena}
        )

    assert asignar.status_code == 404, asignar.text
    assert consultar.status_code == 404, consultar.text

    # Sin mutacion: el departamento de B sigue sin sede y A conserva sus dos sedes.
    modelos = importlib.import_module("app.models")
    with Session(bind=mundo["motor_b"]) as sesion_b:
        departamento_b = sesion_b.get(
            modelos.Departamento, mundo["ids_b"]["departamento_id"]
        )
        assert departamento_b.sede_id is None, "B no debe quedar mutado"
    with Session(bind=mundo["motor_a"]) as sesion_a:
        total_sedes_a = sesion_a.query(modelos.Sede).count()
    assert total_sedes_a == 2, "A no debe quedar mutado"
