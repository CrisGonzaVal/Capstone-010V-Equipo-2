"""Feature 017, T2: politica de normalizacion y no-mutacion del alta (AC-1, AC-2, AC-7).

Seam bajo prueba: la interfaz publica de `app.services.usuario_service` sobre
SQLite en memoria, igual que el resto de la suite de servicios. Se fija el
comportamiento que T6 debe completar (el flujo de invitacion y la recuperacion
del usuario tenant sin mapa); hoy los casos de normalizacion/duplicado/reintento
fallan **solo** porque ese flujo aun no existe, mientras que los guards de "un
fallo de Clerk o de validacion no crea usuario local" ya documentan la regla
vigente y deben permanecer verdes.

Casos:

  * El correo se persiste normalizado (`trim + lowercase`) en el alta (D-1).
  * Dos altas del mismo correo normalizado: una crea, la otra recibe **409**
    (AC-2/AC-7), sin duplicar filas.
  * Un usuario tenant local sin mapa se reconoce como alta incompleta: el
    reintento completa la asociacion y no se responde 400 por duplicado (D-2).
  * Un fallo de la frontera Clerk (**503**) o una validacion de rol/ambito
    fallida no crean usuario local (AC-1).
  * Listado/DTO de usuario no exponen la URL de invitacion (D-6).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.core import security
from app.models import MapaUsuarioEsquema, Rol, Usuario
from app.schemas.usuario_schema import UsuarioCrear, UsuarioRespuesta
from app.services import usuario_service
from app.services.auth_service import IdentidadAutenticada

#: Correo "sucio" y su forma canonica (D-1).
CORREO_SUCIO = "  JuanPerez@Ejemplo.CL "
CORREO_NORMALIZADO = "juanperez@ejemplo.cl"


@pytest.fixture
def sesion(motor) -> Session:
    sesion_db = sessionmaker(bind=motor)()
    try:
        yield sesion_db
    finally:
        sesion_db.close()


def _identidad_administrador(datos_base: dict) -> IdentidadAutenticada:
    """Identidad Administrador con el ambito institucional de `datos_base` (INST01)."""
    usuario = Usuario(
        usuario_id=9999,
        nombre="Sonda",
        apellido="Invitaciones",
        correo="sonda.invitaciones@compustock.cl",
        departamento_id=datos_base["departamento_id"],
        rol_id=datos_base["rol_id"],
    )
    usuario.rol = Rol(nombre_rol="Administrador")
    return IdentidadAutenticada(usuario=usuario, sub="sub-017-invitaciones")


def _datos_alta(datos_base: dict, correo: str) -> UsuarioCrear:
    return UsuarioCrear(
        nombre="Juan",
        apellido="Perez",
        correo=correo,
        departamento_id=datos_base["departamento_id"],
        rol_id=datos_base["rol_bodeguero_id"],
    )


def _usuarios_con_correo(db: Session, correo_normalizado: str) -> list[Usuario]:
    return (
        db.query(Usuario)
        .filter(func.lower(Usuario.correo) == correo_normalizado)
        .all()
    )


# ---------------------------------------------------------------------------
# Normalizacion (D-1, AC-1)
# ---------------------------------------------------------------------------


def test_alta_persiste_el_correo_normalizado(datos_base, sesion):
    """El alta guarda `trim + lowercase`, aunque el formulario envie otra caja."""
    identidad = _identidad_administrador(datos_base)

    usuario_service.crear_usuario(
        sesion,
        _datos_alta(datos_base, CORREO_SUCIO),
        identidad,
        verificar_correo=lambda _correo: True,
    )

    usuarios = _usuarios_con_correo(sesion, CORREO_NORMALIZADO)
    assert len(usuarios) == 1
    assert usuarios[0].correo == CORREO_NORMALIZADO


# ---------------------------------------------------------------------------
# Duplicado normalizado y recuperacion del reintento (AC-2, AC-7)
# ---------------------------------------------------------------------------


def test_dos_altas_del_mismo_correo_normalizado_producen_409(datos_base, sesion):
    """La unicidad del correo normalizado elige una; la segunda recibe 409."""
    identidad = _identidad_administrador(datos_base)
    verificar = lambda _correo: True  # noqa: E731 - identidad existente, sin invitar

    usuario_service.crear_usuario(
        sesion, _datos_alta(datos_base, CORREO_SUCIO), identidad, verificar_correo=verificar
    )

    with pytest.raises(HTTPException) as contexto:
        usuario_service.crear_usuario(
            sesion,
            _datos_alta(datos_base, CORREO_NORMALIZADO),
            identidad,
            verificar_correo=verificar,
        )

    assert contexto.value.status_code == 409
    assert len(_usuarios_con_correo(sesion, CORREO_NORMALIZADO)) == 1


def test_reintento_de_usuario_local_sin_mapa_completa_la_asociacion(datos_base, sesion):
    """Un usuario tenant sin mapa es alta incompleta: el reintento la repara (D-2).

    No se responde 400 por duplicado ni se crea un segundo usuario; el mapa de
    control queda registrado y activo.
    """
    identidad = _identidad_administrador(datos_base)
    correo = "reintento@ejemplo.cl"
    existente = Usuario(
        nombre="Juan",
        apellido="Perez",
        correo=correo,
        departamento_id=datos_base["departamento_id"],
        rol_id=datos_base["rol_bodeguero_id"],
    )
    sesion.add(existente)
    sesion.commit()
    sesion.refresh(existente)
    assert sesion.get(MapaUsuarioEsquema, correo) is None

    recuperado = usuario_service.crear_usuario(
        sesion,
        _datos_alta(datos_base, correo),
        identidad,
        verificar_correo=lambda _correo: True,
    )

    assert recuperado.usuario_id == existente.usuario_id
    assert len(_usuarios_con_correo(sesion, correo)) == 1
    mapa = sesion.get(MapaUsuarioEsquema, correo)
    assert mapa is not None
    assert mapa.activo is True


# ---------------------------------------------------------------------------
# Fallos previos no crean usuario local (AC-1)
# ---------------------------------------------------------------------------


def test_fallo_de_la_frontera_clerk_no_crea_usuario_local(datos_base, sesion):
    """Un error de Clerk responde 503 y no deja fila local."""
    identidad = _identidad_administrador(datos_base)

    def clerk_no_disponible(_correo: str) -> bool:
        raise security.ErrorAutenticacion("fallo simulado de la frontera")

    correo = "sin.clerk@ejemplo.cl"
    with pytest.raises(HTTPException) as contexto:
        usuario_service.crear_usuario(
            sesion,
            _datos_alta(datos_base, correo),
            identidad,
            verificar_correo=clerk_no_disponible,
        )

    assert contexto.value.status_code == 503
    assert _usuarios_con_correo(sesion, correo) == []


def test_validacion_fallida_no_crea_usuario_local(datos_base, sesion):
    """Un rol no asignable por el Administrador responde 403 sin crear fila."""
    identidad = _identidad_administrador(datos_base)
    datos = _datos_alta(datos_base, "rol.invalido@ejemplo.cl")
    datos.rol_id = 999_999

    with pytest.raises(HTTPException) as contexto:
        usuario_service.crear_usuario(
            sesion,
            datos,
            identidad,
            verificar_correo=lambda _correo: True,
        )

    assert contexto.value.status_code == 403
    assert _usuarios_con_correo(sesion, "rol.invalido@ejemplo.cl") == []


# ---------------------------------------------------------------------------
# La URL no viaja en el listado ni en el DTO de usuario (D-6)
# ---------------------------------------------------------------------------


def test_listado_de_usuarios_no_expone_la_url_de_invitacion(datos_base, sesion):
    """La serializacion del listado no contiene URL ni enlace de invitacion."""
    identidad = _identidad_administrador(datos_base)
    usuarios = usuario_service.listar_usuarios(sesion, identidad)
    serializados = [
        UsuarioRespuesta.model_validate(usuario).model_dump(mode="json")
        for usuario in usuarios
    ]

    for usuario in serializados:
        assert not any("url" in campo or "link" in campo for campo in usuario)
