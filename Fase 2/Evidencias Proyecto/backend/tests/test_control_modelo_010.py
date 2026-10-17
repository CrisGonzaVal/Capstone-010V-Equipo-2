"""T3 (Feature 010): modelo logico de control, mapa correo->esquema y version.

Seam bajo prueba: el **modelo logico** (`app.models.control`) y los servicios que
lo operan (`app.services.control_service`, `app.services.tenant_service`), sobre
el motor SQLite en memoria de la suite ordinaria (contexto logico unico). Esta
tarea fija primero el contrato rojo de:

  * la **estructura administrativa de control** y el **bootstrap idempotente**
    (AC-6): institucion administrativa, departamento administrativo, usuario y
    rol Superadmin; una segunda ejecucion no duplica ni altera;
  * el **mapa `correo -> esquema`** (AC-6/AC-12): unicidad de `correo` (un correo
    no puede apuntar a dos esquemas); `nombre_esquema` no es unico en la base
    (dos usuarios de la misma institucion lo comparten) y su invariante se
    garantiza por derivacion en servidor (ver `test_nombre_...`);
  * `version_esquema` (AC-12/AC-13): comparacion de **igualdad exacta** con la
    version objetivo `011.1`; ausente/diferente/ilegible deniega en cerrado;
  * el **nombre determinista de esquema** (AC-7/AC-13): reproducible, con prefijo
    reservado, sin colisiones silenciosas y rechazando identificadores vacios.

Lo que SQLite **no** puede demostrar —el espejo de institucion en el esquema
tenant, la replica de catalogos por esquema, las seis FK locales a `institucion`
y la ausencia de FK cross-schema, y el namespace real de `version_esquema`— queda
en `test_control_postgres_010.py`, marcado gated con `POSTGRES_TEST_URL` (misma
condicion y estilo que los tests PostgreSQL de la Feature 008). SQLite no acredita
aislamiento de esquemas (D-10, AC-16).

Fase ROJA de TDD: T4/T5/T8 crean estas capacidades. Cada prueba falla por
**capacidad ausente** con mensaje legible (`pytest.fail`) —nunca por importacion
rota ni sintaxis— porque `app.models.control` y el servicio de control aun no
existen.
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core import config
from app.models import Departamento, Institucion, Rol, Usuario

# ---------------------------------------------------------------------------
# Version objetivo (constante de despliegue compartida, plan §1)
# ---------------------------------------------------------------------------

#: Token de version objetivo (Feature 011: sube con el modelo organizacional).
VERSION_OBJETIVO = "011.1"

#: Prefijo reservado del nombre de esquema tenant (plan §"Nombre determinista").
PREFIJO_TENANT = "tenant_"


# ---------------------------------------------------------------------------
# Sondas de capacidad: fallan por ausencia, nunca por import roto
# ---------------------------------------------------------------------------


def _modulo(nombre: str, motivo: str):
    try:
        return importlib.import_module(nombre)
    except ImportError:
        pytest.fail(f"capacidad ausente (T4/T5/T8): falta el modulo {nombre} ({motivo}).")


def _simbolo(nombre_modulo: str, nombre: str, motivo: str):
    modulo = _modulo(nombre_modulo, motivo)
    valor = getattr(modulo, nombre, None)
    if valor is None:
        pytest.fail(
            f"capacidad ausente (T4/T5/T8): {nombre_modulo}.{nombre} no existe ({motivo})."
        )
    return valor


def _clase_control(nombre: str, motivo: str):
    return _simbolo("app.models.control", nombre, motivo)


def _bootstrap():
    return _simbolo(
        "app.services.control_service",
        "ejecutar_bootstrap_control",
        "bootstrap idempotente de control (T8, AC-6)",
    )


def _es_version_objetivo():
    return _simbolo(
        "app.services.control_service",
        "es_version_objetivo",
        "predicado de igualdad exacta de version (T5, AC-12)",
    )


def _nombre_esquema():
    return _simbolo(
        "app.services.tenant_service",
        "nombre_esquema_para_institucion",
        "nombre determinista de esquema (T4, AC-7/AC-13)",
    )


@pytest.fixture
def sesion(motor):
    db = sessionmaker(bind=motor)()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Version objetivo: constante exacta
# ---------------------------------------------------------------------------


def test_version_objetivo_es_la_constante_de_despliegue():
    """Plan §1/stack §5: la version objetivo es `011.1` (Feature 011)."""
    version = getattr(config, "VERSION_ESQUEMA_OBJETIVO", None)
    assert version == VERSION_OBJETIVO, (
        "capacidad ausente (T4/T5): app.core.config debe exponer "
        f"VERSION_ESQUEMA_OBJETIVO = '{VERSION_OBJETIVO}'."
    )


# ---------------------------------------------------------------------------
# Declaracion del mapa y de la version en el modelo logico
# ---------------------------------------------------------------------------


def _columnas_unicas(tabla) -> set[str]:
    unicas: set[str] = set()
    for constraint in tabla.constraints:
        if isinstance(constraint, UniqueConstraint):
            unicas |= {columna.name for columna in constraint.columns}
    for columna in tabla.columns:
        if columna.unique:
            unicas.add(columna.name)
    return unicas


def test_mapa_declara_correo_como_clave_unica():
    """Stack §4: `correo` identifica una identidad local; `nombre_esquema` no es unico.

    El mapa tiene una fila por usuario y todos los usuarios de una institucion
    comparten su `nombre_esquema`, asi que este no puede llevar unicidad de base.
    """
    mapa = _clase_control("MapaUsuarioEsquema", "mapa correo->esquema (T4, AC-6/AC-12)")
    tabla = mapa.__table__

    columnas = set(tabla.columns.keys())
    assert {"correo", "institucion_id", "nombre_esquema", "activo"} <= columnas, columnas

    claves_primarias = {columna.name for columna in tabla.primary_key.columns}
    unicas = _columnas_unicas(tabla)
    assert "correo" in claves_primarias or "correo" in unicas, (
        "`correo` debe ser clave unica del mapa (una identidad no apunta a 2 esquemas)"
    )
    assert "nombre_esquema" not in unicas, (
        "`nombre_esquema` no debe ser unico: el mapa tiene una fila por usuario y "
        "los usuarios de una institucion comparten su esquema"
    )


def test_version_esquema_declara_una_fila_vigente():
    """Stack §5: `version_esquema` tiene una fila (`version_id` PK) con la version."""
    version = _clase_control("VersionEsquema", "version por tenant (T4, AC-12)")
    tabla = version.__table__

    assert {"version_id", "version", "actualizada_en"} <= set(tabla.columns.keys())
    claves_primarias = {columna.name for columna in tabla.primary_key.columns}
    assert "version_id" in claves_primarias, claves_primarias
    assert not tabla.columns["version"].nullable, "`version` no puede ser nula"


# ---------------------------------------------------------------------------
# Bootstrap de control: estructura administrativa e idempotencia (AC-6)
# ---------------------------------------------------------------------------


def _conteos_control(db) -> dict:
    return {
        "institucion": len(db.execute(select(Institucion)).scalars().all()),
        "departamento": len(db.execute(select(Departamento)).scalars().all()),
        "usuario": len(db.execute(select(Usuario)).scalars().all()),
        "rol": len(db.execute(select(Rol)).scalars().all()),
    }


def _superadmins(db) -> list[Usuario]:
    return (
        db.execute(select(Usuario).join(Rol).where(Rol.nombre_rol == "Superadmin"))
        .scalars()
        .all()
    )


def test_bootstrap_control_crea_estructura_administrativa(sesion):
    """AC-6: tras el bootstrap existe institucion/departamento/usuario/rol Superadmin."""
    _bootstrap()(sesion)

    roles_superadmin = (
        sesion.execute(select(Rol).where(Rol.nombre_rol == "Superadmin")).scalars().all()
    )
    assert len(roles_superadmin) == 1, "debe existir exactamente un rol Superadmin"

    usuarios = _superadmins(sesion)
    assert len(usuarios) == 1, "debe existir exactamente un usuario Superadmin"
    administrador = usuarios[0]

    departamento = sesion.get(Departamento, administrador.departamento_id)
    assert departamento is not None, "el usuario Superadmin necesita departamento (NOT NULL)"
    assert departamento.institucion_id, "el departamento necesita institucion (NOT NULL)"

    institucion = sesion.get(Institucion, departamento.institucion_id)
    assert institucion is not None, "debe existir la institucion administrativa de control"


def test_bootstrap_control_es_idempotente(sesion):
    """AC-6: una segunda ejecucion no duplica ni altera los registros existentes.

    Distingue el bootstrap idempotente de la mera existencia de tablas: los
    conteos y los identificadores deben ser **iguales** entre ejecuciones.
    """
    bootstrap = _bootstrap()

    bootstrap(sesion)
    conteos_1 = _conteos_control(sesion)
    ids_1 = sorted(u.usuario_id for u in _superadmins(sesion))
    assert ids_1, "la primera ejecucion debe crear el usuario Superadmin"

    bootstrap(sesion)
    conteos_2 = _conteos_control(sesion)
    ids_2 = sorted(u.usuario_id for u in _superadmins(sesion))

    assert conteos_2 == conteos_1, (conteos_1, conteos_2)
    assert ids_2 == ids_1, "el bootstrap repetido no debe recrear el usuario administrativo"


# ---------------------------------------------------------------------------
# Unicidad del mapa correo->esquema
# ---------------------------------------------------------------------------


def _dos_instituciones(db) -> None:
    db.add_all(
        [
            Institucion(institucion_id="INST01", nombre="Institucion Uno"),
            Institucion(institucion_id="INST02", nombre="Institucion Dos"),
        ]
    )
    db.commit()


def test_mapa_rechaza_correo_repetido_en_otro_esquema(sesion):
    """AC-6/AC-12: un correo no puede apuntar a dos esquemas distintos."""
    mapa = _clase_control("MapaUsuarioEsquema", "mapa correo->esquema (T4)")
    _dos_instituciones(sesion)

    sesion.add(
        mapa(
            correo="ana@compustock.cl",
            institucion_id="INST01",
            nombre_esquema="tenant_inst01_deadbeef",
            activo=True,
        )
    )
    sesion.commit()

    sesion.add(
        mapa(
            correo="ana@compustock.cl",
            institucion_id="INST02",
            nombre_esquema="tenant_inst02_cafebabe",
            activo=True,
        )
    )
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.execute(select(mapa)).scalars().all().__len__() == 1


def test_mapa_permite_varios_usuarios_de_la_misma_institucion(sesion):
    """AC-10: el mapa admite todos los usuarios de una institucion (mismo esquema).

    `nombre_esquema` no es unico en la base porque el mapa tiene una fila por
    usuario. Dos usuarios de la misma institucion comparten su esquema; esto es
    lo que permite que el mapa cubra a **todos** los usuarios migrados. La
    invariante "dos instituciones no comparten esquema" se garantiza por
    derivacion en servidor (nombre determinista del ID), no por unicidad de base.
    """
    mapa = _clase_control("MapaUsuarioEsquema", "mapa correo->esquema (T4)")
    nombre_esquema = _nombre_esquema()
    _dos_instituciones(sesion)

    esquema_compartido = nombre_esquema("INST01")
    sesion.add_all(
        [
            mapa(
                correo="ana@compustock.cl",
                institucion_id="INST01",
                nombre_esquema=esquema_compartido,
                activo=True,
            ),
            mapa(
                correo="luis@compustock.cl",
                institucion_id="INST01",
                nombre_esquema=esquema_compartido,
                activo=True,
            ),
        ]
    )
    sesion.commit()

    filas = sesion.execute(select(mapa)).scalars().all()
    assert len(filas) == 2, "dos usuarios de la misma institucion deben mapearse"
    assert {fila.nombre_esquema for fila in filas} == {esquema_compartido}

    # La invariante se sostiene por derivacion: otra institucion -> otro esquema.
    assert nombre_esquema("INST02") != esquema_compartido


# ---------------------------------------------------------------------------
# Version: comparacion de igualdad exacta (AC-12/AC-13)
# ---------------------------------------------------------------------------


def test_version_solo_acepta_igualdad_exacta():
    """AC-12: ausente, vacia, futura, incompleta o con espacios deniega en cerrado."""
    es_version_objetivo = _es_version_objetivo()

    assert es_version_objetivo(VERSION_OBJETIVO) is True
    for invalida in (
        None,
        "",
        "011",
        "011.1.0",
        "011.10",
        "011.2",
        "010.1",
        "v011.1",
        "011.1 ",
        " 011.1",
    ):
        assert es_version_objetivo(invalida) is False, invalida


# ---------------------------------------------------------------------------
# Nombre determinista de esquema (AC-7/AC-13)
# ---------------------------------------------------------------------------


def test_nombre_esquema_es_determinista_y_sin_colisiones():
    """AC-7/AC-13: mismo ID -> mismo nombre; IDs distintos -> nombres distintos."""
    nombre_esquema = _nombre_esquema()

    assert nombre_esquema("INST01") == nombre_esquema("INST01")
    assert nombre_esquema("INST01") != nombre_esquema("INST02")
    assert nombre_esquema("INST01").startswith(PREFIJO_TENANT)

    generados = {nombre_esquema(f"INST{i:05d}") for i in range(300)}
    assert len(generados) == 300, "el nombre generado no debe colisionar entre IDs"


def test_nombre_esquema_rechaza_identificadores_vacios():
    """Plan §"Nombre determinista": IDs vacios se rechazan sin truncar el hash."""
    nombre_esquema = _nombre_esquema()

    for vacio in ("", "   ", None):
        with pytest.raises((ValueError, TypeError)):
            nombre_esquema(vacio)
