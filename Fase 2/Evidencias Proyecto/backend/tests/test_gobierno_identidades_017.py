"""Feature 017, T3: modelo/DTO y persistencia de control (AC-1..AC-7, AC-10, AC-11, AC-18).

Seam bajo prueba: el **modelo logico** de control (`app.models.control`) sobre el
contexto logico unico de SQLite y los **DTOs Pydantic v2** que publican el estado
persistido de invitacion y el motivo de una mutacion administrativa.

Estas pruebas fijan, antes de implementar:

  * `MapaUsuarioEsquema` declara `estado_invitacion`, `invitacion_id`,
    `invitacion_expira_en` e `invitacion_aceptada_en` (stack.md, Feature 017).
    Un registro legado sin estado se proyecta como `no disponible`, nunca como
    `aceptada`.
  * `RegistroMotivoConstancia` existe, es **solo de control** (no viaja en la
    metadata tenant) y posee clave idempotente unica, actor, objetivo,
    institucion, accion, motivo, instante, `invitacion_id` y resultado de la
    compensacion; **ningun campo de URL**.
  * `UsuarioRespuesta` publica `estado_invitacion` y no filtra URL/enlace.
  * `MotivoMutacion` valida el catalogo cerrado de D-5 y el texto de `otro`.

Lo que SQLite no puede acreditar (columnas/CHECK reales en `control`,
ausencia de la tabla auxiliar en cada tenant y guardia fail-closed de la
instalacion limpia) vive en `test_instalacion_limpia_postgres.py`, gated con
`POSTGRES_TEST_URL`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Institucion,
    MapaUsuarioEsquema,
    RegistroMotivoConstancia,
)
from app.schemas.usuario_schema import (
    ESTADO_INVITACION_NO_DISPONIBLE,
    MotivoMutacion,
    UsuarioRespuesta,
    proyectar_estado_invitacion,
)

#: Columnas nuevas del mapa persistido de invitacion (stack.md, Feature 017).
COLUMNAS_INVITACION = {
    "estado_invitacion",
    "invitacion_id",
    "invitacion_expira_en",
    "invitacion_aceptada_en",
}

#: Columnas minimas de la estructura auxiliar de motivos/constancias (D-6).
COLUMNAS_REGISTRO = {
    "registro_id",
    "tipo_registro",
    "actor_correo",
    "usuario_objetivo_id",
    "correo_objetivo",
    "institucion_id",
    "accion",
    "codigo_motivo",
    "texto_motivo",
    "fecha_registro",
    "clave_idempotente",
    "invitacion_id",
    "resultado_revocacion",
}


@pytest.fixture
def sesion(motor):
    db = sessionmaker(bind=motor)()
    try:
        yield db
    finally:
        db.close()


def _institucion(db, institucion_id: str = "INST17") -> None:
    db.add(Institucion(institucion_id=institucion_id, nombre="Institucion 017"))
    db.commit()


# ---------------------------------------------------------------------------
# Modelo del mapa: columnas de invitacion y proyeccion del legado
# ---------------------------------------------------------------------------


def test_mapa_declara_la_proyeccion_persistida_de_invitacion():
    """Stack.md: las cuatro columnas nuevas viven en el mapa de control."""
    tabla = MapaUsuarioEsquema.__table__

    assert COLUMNAS_INVITACION <= set(tabla.columns.keys())
    for nombre in COLUMNAS_INVITACION:
        assert tabla.columns[nombre].nullable, (
            f"`{nombre}` debe admitir NULL: los registros legados no tienen "
            "estado persistido y no pueden nacer como aceptados"
        )


def test_mapa_legado_sin_estado_se_proyecta_como_no_disponible(sesion):
    """D-3: ausencia/estado desconocido -> `no disponible`, nunca `aceptada`."""
    _institucion(sesion)
    sesion.add(
        MapaUsuarioEsquema(
            correo="legado@compustock.cl",
            institucion_id="INST17",
            nombre_esquema="tenant_inst17_deadbeef",
            activo=True,
        )
    )
    sesion.commit()

    mapa = sesion.get(MapaUsuarioEsquema, "legado@compustock.cl")
    assert mapa is not None
    assert mapa.estado_invitacion is None
    assert mapa.invitacion_id is None
    assert proyectar_estado_invitacion(mapa.estado_invitacion) == (
        ESTADO_INVITACION_NO_DISPONIBLE
    )


def test_proyeccion_conserva_los_cuatro_estados_y_descarta_desconocidos():
    """D-3: solo los cuatro estados canonicos se publican tal cual."""
    for estado in ("pendiente", "aceptada", "revocada", "expirada"):
        assert proyectar_estado_invitacion(estado) == estado
    for desconocido in (None, "", "aceptado", "PENDIENTE", "otro"):
        assert proyectar_estado_invitacion(desconocido) == (
            ESTADO_INVITACION_NO_DISPONIBLE
        )


# ---------------------------------------------------------------------------
# Estructura auxiliar de motivos/constancias
# ---------------------------------------------------------------------------


def test_registro_declara_campos_de_evidencia_y_clave_idempotente():
    """D-6/AC-11: evidencia recuperable con idempotencia y sin URL."""
    tabla = RegistroMotivoConstancia.__table__

    assert COLUMNAS_REGISTRO <= set(tabla.columns.keys())
    assert not tabla.columns["clave_idempotente"].nullable
    assert tabla.columns["clave_idempotente"].unique, (
        "la clave idempotente debe ser unica para que el reintento no duplique"
    )
    assert not tabla.columns["actor_correo"].nullable
    assert not tabla.columns["institucion_id"].nullable
    assert not tabla.columns["accion"].nullable
    assert not tabla.columns["fecha_registro"].nullable
    assert tabla.columns["invitacion_id"].nullable
    assert tabla.columns["resultado_revocacion"].nullable

    # Nunca se persiste el enlace de invitacion (D-2/D-6).
    assert not any(
        "url" in nombre or "enlace" in nombre or "link" in nombre
        for nombre in tabla.columns.keys()
    ), tabla.columns.keys()


def test_registro_es_solo_de_control_y_no_viaja_a_la_metadata_tenant():
    """AC-18: la auxiliar no se replica a los esquemas tenant."""
    from app.services.control_service import tablas_metadata_tenant

    nombres = {tabla.name for tabla in tablas_metadata_tenant()}
    assert "registro_motivo_constancia" not in nombres
    assert "mapa_usuario_esquema" not in nombres
    # Feature 014: el tenant replica 19 tablas de negocio (las 17 previas mas los
    # dos historiales de transicion del catalogo, entidades 16.ª y 17.ª).
    assert len(nombres) == 19, sorted(nombres)


def test_registro_persiste_una_constancia_de_compensacion(sesion):
    """AC-3/AC-7: `invitacion_id` localizable y nunca URL."""
    _institucion(sesion)
    sesion.add(
        RegistroMotivoConstancia(
            tipo_registro="constancia_compensacion",
            actor_correo="admin@compustock.cl",
            usuario_objetivo_id=None,
            correo_objetivo="nuevo@ejemplo.cl",
            institucion_id="INST17",
            accion="compensacion_invitacion_fallida",
            clave_idempotente="comp-017-01",
            invitacion_id="inv_017_01",
            resultado_revocacion="revocacion_fallida: 503",
        )
    )
    sesion.commit()

    fila = sesion.query(RegistroMotivoConstancia).one()
    assert fila.invitacion_id == "inv_017_01"
    assert fila.correo_objetivo == "nuevo@ejemplo.cl"
    assert fila.codigo_motivo is None
    assert not hasattr(fila, "url")


def test_registro_rechaza_clave_idempotente_repetida(sesion):
    """AC-11: el reintento reutiliza la clave; no crea una segunda fila."""
    _institucion(sesion)
    base = dict(
        tipo_registro="justificacion",
        actor_correo="admin@compustock.cl",
        institucion_id="INST17",
        accion="edicion_usuario",
        codigo_motivo="correccion_datos",
        texto_motivo="Correccion de apellido",
        clave_idempotente="mut-017-01",
    )
    sesion.add(RegistroMotivoConstancia(**base))
    sesion.commit()

    sesion.add(RegistroMotivoConstancia(**base))
    with pytest.raises(IntegrityError):
        sesion.commit()
    sesion.rollback()

    assert sesion.query(RegistroMotivoConstancia).count() == 1


def test_listado_minimo_de_administradores_expone_estado_sin_url():
    """AC-5: el listado de control publica solo los campos acordados."""
    from app.schemas.control_schema import AdministradorListadoControlRespuesta

    campos = set(AdministradorListadoControlRespuesta.model_fields)
    assert campos == {
        "usuario_id",
        "nombre",
        "apellido",
        "correo",
        "activo",
        "estado_invitacion",
    }
    assert not any("url" in campo or "link" in campo for campo in campos)


# ---------------------------------------------------------------------------
# DTOs: estado de invitacion y motivo
# ---------------------------------------------------------------------------


class _UsuarioPlano:
    """Objeto con los atributos del modelo `Usuario` para probar el DTO."""

    usuario_id = 1
    nombre = "Ana"
    apellido = "Perez"
    correo = "ana@compustock.cl"
    departamento_id = 1
    rol_id = 2
    sede_id = None
    activo = True


def test_usuario_respuesta_publica_estado_no_disponible_por_defecto():
    """El listado publica el estado persistido o `no disponible`; nunca URL."""
    respuesta = UsuarioRespuesta.model_validate(_UsuarioPlano())
    cuerpo = respuesta.model_dump(mode="json")

    assert cuerpo["estado_invitacion"] == ESTADO_INVITACION_NO_DISPONIBLE
    assert not any("url" in campo or "link" in campo for campo in cuerpo)
    assert not any("invitacion_id" in campo for campo in cuerpo)


def test_motivo_mutacion_acepta_catalogo_cerrado_y_texto_opcional():
    """D-5: codigos cerrados; el texto es opcional salvo para `otro`."""
    for codigo in (
        "cambio_funciones",
        "reasignacion_organizacional",
        "correccion_datos",
        "termino_vinculo",
        "seguridad_acceso",
    ):
        assert MotivoMutacion(codigo=codigo).texto is None

    valido = MotivoMutacion(codigo="otro", texto="Detalle explicativo")
    assert valido.codigo == "otro"


def test_motivo_mutacion_rechaza_codigo_invalido_y_otro_sin_texto():
    """AC-10: entrada invalida es 422 antes de cualquier mutacion."""
    with pytest.raises(ValidationError):
        MotivoMutacion(codigo="motivo_inventado")
    with pytest.raises(ValidationError):
        MotivoMutacion(codigo="otro", texto="   ")
    with pytest.raises(ValidationError):
        MotivoMutacion(codigo="otro")
    with pytest.raises(ValidationError):
        MotivoMutacion(codigo="cambio_funciones", texto="x" * 501)
