"""Feature 007 (T6): la contrasena local deja de existir en el modelo y el contrato.

Clerk es la unica autoridad de autenticacion (D-7). El modelo funcional
(`Usuario`) y el contrato de creacion (`UsuarioCrear`) no deben declarar ni
requerir `password`, y ninguna respuesta de usuario debe publicarlo. Estas
asercciones son intencionales sobre la **ausencia** del campo (permitidas por
el `Hecho cuando:` de T6): fijan que el retiro no se revierta por accidente.
"""

from app.models import Usuario
from app.schemas.usuario_schema import UsuarioCrear, UsuarioRespuesta


def test_modelo_usuario_no_declara_la_columna_password():
    assert "password" not in Usuario.__table__.columns
    assert not hasattr(Usuario, "password")


def test_contrato_de_creacion_no_requiere_ni_acepta_password():
    assert "password" not in UsuarioCrear.model_fields
    # Un payload que intentara adjuntar una credencial local no forma parte del
    # contrato: el campo no se declara.
    datos = UsuarioCrear(
        nombre="Sin",
        apellido="Credencial",
        correo="sin.credencial@compustock.cl",
        departamento_id=1,
        rol_id=1,
    )
    assert not hasattr(datos, "password")
    assert "password" not in datos.model_dump()


def test_respuesta_de_usuario_no_publica_password():
    assert "password" not in UsuarioRespuesta.model_fields
