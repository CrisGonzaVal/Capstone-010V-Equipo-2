"""Doble de la frontera Clerk de invitaciones para la suite (Feature 017).

Los tests nunca llaman a Clerk real (plan seccion 5). Este modulo centraliza el fake de
las tres costuras inyectables (`consultar_identidad`, `crear_invitacion`,
`revocar_invitacion`) para que cada helper de cliente las instale junto al
verificador de correo historico.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api import dependencies
from app.core import security

URL_FALSA = "https://clerk.test/invitacion"
ID_FALSO = "inv_prueba_017"


def invitacion_falsa(
    *, invitacion_id: str = ID_FALSO, url: str = URL_FALSA
) -> security.InvitacionCreada:
    return security.InvitacionCreada(
        invitacion_id=invitacion_id,
        url=url,
        expira_en=datetime.now(timezone.utc) + timedelta(days=7),
    )


def instalar_frontera_clerk(
    *,
    identidad_existente: bool = True,
    invitacion_pendiente: bool = False,
    invitacion_id: str | None = None,
    crear=None,
    revocar=None,
    consultar=None,
) -> None:
    """Instala overrides de las costuras Clerk en `app.dependency_overrides`.

    `identidad_existente` decide el estado por defecto del consultor; `crear` y
    `revocar` permiten inyectar fallos. Las pruebas que necesitan otro
    comportamiento pueden sobrescribir el override despues.
    """
    def _consultar(correo: str) -> security.EstadoIdentidadClerk:
        if consultar is not None:
            return consultar(correo)
        return security.EstadoIdentidadClerk(
            identidad_existente=identidad_existente,
            invitacion_pendiente=invitacion_pendiente,
            invitacion_id=invitacion_id,
        )

    def _crear(correo: str, *, ignore_existing: bool = False):
        if crear is not None:
            return crear(correo, ignore_existing=ignore_existing)
        return invitacion_falsa()

    def _revocar(invitacion: str) -> None:
        if revocar is not None:
            revocar(invitacion)
        return None

    app = _aplicacion()
    app.dependency_overrides[dependencies.obtener_consultor_identidad_clerk] = (
        lambda: _consultar
    )
    app.dependency_overrides[dependencies.obtener_creador_invitacion_clerk] = (
        lambda: _crear
    )
    app.dependency_overrides[dependencies.obtener_revocador_invitacion_clerk] = (
        lambda: _revocar
    )


def _aplicacion():
    from app.main import app

    return app
