"""T11 (Feature 010): cableado del contexto tenant en la suite ordinaria SQLite.

Complemento no gated. SQLite corre sobre un **contexto logico unico** (AC-16): no
hay namespaces que seleccionar, de modo que el cableado del contexto tenant debe
ser **transparente** y no cambiar el contrato observado. Estas pruebas de
comportamiento fijan esa transparencia, mientras que la agregacion multi-esquema
real y el fallo completo ante un tenant caido se acreditan en PostgreSQL
(`tests/test_integracion_multitenant_010.py`).

Casos:

  * `crear_sesion_control` devuelve una sesion usable sobre el contexto unico;
  * `tenants_registrados` deriva los tenants activos del mapa y excluye el
    esquema reservado `control` (deduplicando por institucion+esquema);
  * `agregar_lista_global` ejecuta la lectura **una sola vez** sobre el contexto
    unico (no itera tenants);
  * `get_db_negocio` devuelve la misma sesion recibida en SQLite: el cableado no
    introduce un segundo contexto ni rompe la suite funcional.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.db.database import ESQUEMA_CONTROL, crear_sesion_control
from app.models import Institucion, MapaUsuarioEsquema, Rol, Usuario
from app.services import global_service, tenant_service
from app.services.auth_service import IdentidadAutenticada


def _identidad(rol: str, correo: str = "sonda.t11@compustock.cl") -> IdentidadAutenticada:
    usuario = Usuario(
        usuario_id=1,
        nombre="Sonda",
        apellido="T11",
        correo=correo,
        departamento_id=1,
        rol_id=1,
    )
    usuario.rol = Rol(nombre_rol=rol)
    return IdentidadAutenticada(usuario=usuario, sub="sub-t11")


def _sembrar_mapa(motor) -> None:
    db = sessionmaker(bind=motor)()
    try:
        db.add(Institucion(institucion_id="INST-A", nombre="Instituto Alfa"))
        db.add(Institucion(institucion_id="INST-B", nombre="Instituto Beta"))
        db.add(Institucion(institucion_id="CTRL-SAAS", nombre="CompuStock SaaS"))
        db.flush()
        db.add_all(
            [
                MapaUsuarioEsquema(
                    correo="a1@inst-a.cl",
                    institucion_id="INST-A",
                    nombre_esquema="tenant_a",
                    activo=True,
                ),
                MapaUsuarioEsquema(
                    correo="a2@inst-a.cl",
                    institucion_id="INST-A",
                    nombre_esquema="tenant_a",
                    activo=True,
                ),
                MapaUsuarioEsquema(
                    correo="b1@inst-b.cl",
                    institucion_id="INST-B",
                    nombre_esquema="tenant_b",
                    activo=True,
                ),
                MapaUsuarioEsquema(
                    correo="inactivo@inst-a.cl",
                    institucion_id="INST-A",
                    nombre_esquema="tenant_a",
                    activo=False,
                ),
                MapaUsuarioEsquema(
                    correo="super@compustock.cl",
                    institucion_id="CTRL-SAAS",
                    nombre_esquema=ESQUEMA_CONTROL,
                    activo=True,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_crear_sesion_control_usa_el_contexto_unico(motor):
    """SQLite no simula esquemas: la sesion de control ve el contexto unico."""
    db = sessionmaker(bind=motor)()
    try:
        db.add(Institucion(institucion_id="INST-A", nombre="Instituto Alfa"))
        db.commit()
    finally:
        db.close()

    sesion = crear_sesion_control(motor)
    try:
        nombres = [
            fila[0]
            for fila in sesion.execute(select(Institucion.nombre)).all()
        ]
    finally:
        sesion.close()
    assert nombres == ["Instituto Alfa"]


def test_tenants_registrados_deriva_del_mapa_y_excluye_control(motor):
    _sembrar_mapa(motor)

    db = sessionmaker(bind=motor)()
    try:
        tenants = global_service.tenants_registrados(db)
    finally:
        db.close()

    assert {t.institucion_id for t in tenants} == {"INST-A", "INST-B"}
    assert {t.nombre_esquema for t in tenants} == {"tenant_a", "tenant_b"}
    assert ESQUEMA_CONTROL not in {t.nombre_esquema for t in tenants}


def test_agregar_lista_global_sqlite_lee_una_sola_vez(motor):
    """En el contexto unico la lectura no se repite por tenant."""
    _sembrar_mapa(motor)

    db = sessionmaker(bind=motor)()
    try:
        llamadas = {"n": 0}

        def _lectura(_sesion):
            llamadas["n"] += 1
            return ["fila"]

        resultado = global_service.agregar_lista_global(
            db, _identidad("Superadmin"), _lectura
        )
    finally:
        db.close()

    assert llamadas["n"] == 1, "SQLite no itera tenants"
    assert resultado == ["fila"]


def test_get_db_negocio_sqlite_devuelve_la_misma_sesion(motor):
    db = sessionmaker(bind=motor)()
    try:
        generador = dependencies.get_db_negocio(db, _identidad("Administrador"))
        sesion = next(generador)
        try:
            assert sesion is db, "SQLite conserva el contexto logico unico"
        finally:
            generador.close()
    finally:
        db.close()


def test_esquema_para_correo_expone_el_mapa_sin_lanzar(motor):
    _sembrar_mapa(motor)

    db = sessionmaker(bind=motor)()
    try:
        assert tenant_service.esquema_para_correo(db, "a1@inst-a.cl") == "tenant_a"
        assert tenant_service.esquema_para_correo(db, "nadie@nada.cl") is None
    finally:
        db.close()
