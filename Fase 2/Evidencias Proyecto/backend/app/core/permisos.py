"""Politica central de autorizacion por rol (Feature 007).

Define los cuatro literales de rol local de la semilla y la matriz explicita de
permisos por operacion (metodo + ruta) conforme a D-3/AC-9. La dependencia HTTP
de autorizacion (`app.api.dependencies.requiere_roles` / `requiere_operacion`)
consume esta matriz; los endpoints de negocio la declaran en T2.

`Admin` es **solo** una abreviatura documental de `Administrador`: no se
reconoce ni se normaliza en runtime. Un rol ausente, vacio o desconocido no
concede permiso. No existe permiso implicito: una operacion no declarada no
tiene roles permitidos.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class RolConocido(str, Enum):
    """Los cuatro roles locales de la semilla, sin alias.

    Los valores son los literales exactos de `rol.nombre_rol`; se usan tal cual
    en la comparacion de autorizacion.
    """

    SUPERADMIN = "Superadmin"
    ADMINISTRADOR = "Administrador"
    BODEGUERO = "Bodeguero"
    SOLICITANTE = "Solicitante"


#: Literales exactos reconocidos. Un valor fuera de este conjunto no concede.
ROLES_CONOCIDOS: frozenset[str] = frozenset(rol.value for rol in RolConocido)

_SUPERADMIN = RolConocido.SUPERADMIN.value
_ADMINISTRADOR = RolConocido.ADMINISTRADOR.value
_BODEGUERO = RolConocido.BODEGUERO.value
_SOLICITANTE = RolConocido.SOLICITANTE.value

#: Los cuatro roles de la semilla (acceso de negocio general).
_TODOS: frozenset[str] = frozenset(
    {_SUPERADMIN, _ADMINISTRADOR, _BODEGUERO, _SOLICITANTE}
)
#: Roles administrativos (usuarios, departamentos y catalogo maestro).
_ADMINISTRATIVOS: frozenset[str] = frozenset({_SUPERADMIN, _ADMINISTRADOR})
#: Roles que operan inventario/movimientos y el flujo de tickets.
_INVENTARIO_Y_TICKETS: frozenset[str] = frozenset(
    {_SUPERADMIN, _ADMINISTRADOR, _BODEGUERO}
)

#: Matriz explicita operacion -> roles permitidos (D-3, AC-9).
#:
#: La clave es (metodo HTTP en mayusculas, ruta completa tal como la publica el
#: contrato, con los parametros de path en su forma `{param}`). Los 18 endpoints
#: de negocio quedan cubiertos; una operacion ausente de esta matriz no concede
#: permiso a ningun rol.
MATRIZ_PERMISOS: dict[tuple[str, str], frozenset[str]] = {
    # Autenticacion: identidad autenticada, cualquier rol.
    ("GET", "/api/v1/auth/me"): _TODOS,
    # Administracion de usuarios y catalogos de apoyo.
    ("GET", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("POST", "/api/v1/usuarios/"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/roles"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/departamentos"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/usuarios/instituciones"): _ADMINISTRATIVOS,
    # Inventario: lectura para los cuatro roles; escritura administrativa o de bodega.
    ("GET", "/api/v1/inventario/categorias"): _TODOS,
    ("GET", "/api/v1/inventario/productos"): _TODOS,
    ("POST", "/api/v1/inventario/productos"): _ADMINISTRATIVOS,
    ("GET", "/api/v1/inventario/existencias"): _TODOS,
    ("GET", "/api/v1/inventario/stock"): _TODOS,
    ("GET", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    ("POST", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    # Tickets: alta y consulta para los cuatro; estado y despacho sin Solicitante.
    ("GET", "/api/v1/tickets/catalogos"): _TODOS,
    ("GET", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/"): _TODOS,
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _INVENTARIO_Y_TICKETS,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _INVENTARIO_Y_TICKETS,
}


def roles_de_operacion(metodo: str, ruta: str) -> frozenset[str]:
    """Roles permitidos para una operacion de la matriz.

    Levanta `KeyError` si la operacion no esta declarada: no hay permiso
    implicito ni coincidencia parcial de rutas.
    """
    return MATRIZ_PERMISOS[(metodo.upper(), ruta)]


def nombre_rol_de(identidad: Any) -> str | None:
    """Nombre del rol local de la identidad, o `None` si es ausente/no resoluble.

    No lanza: un usuario sin rol cargado o una identidad incompleta se traduce a
    `None`, que nunca concede permiso.
    """
    usuario = getattr(identidad, "usuario", None)
    rol = getattr(usuario, "rol", None)
    if rol is None:
        return None
    return getattr(rol, "nombre_rol", None)


def rol_autorizado(
    rol: str | None, roles_permitidos: frozenset[str] | set[str]
) -> bool:
    """`True` solo si `rol` es un literal conocido y esta entre los permitidos.

    Un `None`, un valor vacio, un rol desconocido (p. ej. `Admin`) o un rol
    conocido no listado devuelven `False`.
    """
    return rol in ROLES_CONOCIDOS and rol in roles_permitidos
