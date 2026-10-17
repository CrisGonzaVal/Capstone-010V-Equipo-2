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
#: Roles que operan inventario/movimientos y el flujo de tickets (lectura global
#: de movimientos). Tras el ajuste de la Feature 008 su uso es solo de lectura;
#: las escrituras institucionales usan los conjuntos `_ESCRITURA_*` de abajo.
_INVENTARIO_Y_TICKETS: frozenset[str] = frozenset(
    {_SUPERADMIN, _ADMINISTRADOR, _BODEGUERO}
)

# --- Ajuste puntual de la Feature 008 (D-3/AC-10) ---------------------------
# Superadmin conserva su lectura global pero deja de escribir datos de una
# institucion concreta: escritura de catalogo (producto/categoria),
# stock/movimientos y tickets. Esa escritura corresponde al Administrador de la
# institucion (y al Bodeguero en las operaciones operativas). Es un ajuste
# acotado a estas entradas; el resto de la matriz 007 no se modifica.
#: Escritura de catalogo institucional (alta de producto). Solo el Administrador.
_ESCRITURA_CATALOGO: frozenset[str] = frozenset({_ADMINISTRADOR})
#: Escritura de stock/movimientos y operaciones de ticket (despacho, estado).
_ESCRITURA_STOCK: frozenset[str] = frozenset({_ADMINISTRADOR, _BODEGUERO})
#: Alta de ticket: los roles operativos de la institucion (incluye Solicitante).
_ESCRITURA_TICKETS: frozenset[str] = frozenset(
    {_ADMINISTRADOR, _BODEGUERO, _SOLICITANTE}
)

# --- Ajuste puntual de la Feature 011 (spec D-4/D-5, AC-5) ------------------
# Las asignaciones organizacionales (sede de departamento, sede de Bodeguero y
# gestion de encargados) son administracion institucional: solo el Administrador.
# Superadmin no escribe datos de negocio en tenants; los roles operativos no
# gestionan la organizacion. Tambien la consulta de sedes queda reservada al
# Administrador en esta feature (la lectura operativa de existencias llega en T8).
_ORGANIZACION: frozenset[str] = frozenset({_ADMINISTRADOR})

#: Matriz explicita operacion -> roles permitidos (D-3, AC-9).
#:
#: La clave es (metodo HTTP en mayusculas, ruta completa tal como la publica el
#: contrato, con los parametros de path en su forma `{param}`). Los 22 endpoints
#: de negocio quedan cubiertos (las 18 operaciones de 007, los dos `GET` por
#: objeto de catalogo que exige la Feature 008, el `GET` consolidado del
#: dashboard de la Feature 009 y el `POST` de aprovisionamiento de la Feature
#: 010); una operacion ausente de esta matriz no concede permiso a ningun rol.
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
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): _TODOS,
    ("GET", "/api/v1/inventario/productos"): _TODOS,
    ("GET", "/api/v1/inventario/productos/{producto_id}"): _TODOS,
    # 008 D-3: escritura de catalogo solo institucional (Superadmin no escribe).
    ("POST", "/api/v1/inventario/productos"): _ESCRITURA_CATALOGO,
    ("GET", "/api/v1/inventario/existencias"): _TODOS,
    ("GET", "/api/v1/inventario/stock"): _TODOS,
    ("GET", "/api/v1/inventario/movimientos"): _INVENTARIO_Y_TICKETS,
    # 008 D-3: movimientos de stock sin Superadmin (escritura institucional).
    ("POST", "/api/v1/inventario/movimientos"): _ESCRITURA_STOCK,
    # Tickets: alta y consulta para los cuatro; estado y despacho sin Solicitante.
    ("GET", "/api/v1/tickets/catalogos"): _TODOS,
    ("GET", "/api/v1/tickets/"): _TODOS,
    # 008 D-3: alta de ticket sin Superadmin (escritura institucional).
    ("POST", "/api/v1/tickets/"): _ESCRITURA_TICKETS,
    # 008 D-3: despacho y cambio de estado sin Superadmin.
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _ESCRITURA_STOCK,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _ESCRITURA_STOCK,
    # Feature 009 (D-3/AC-13/AC-14): el dashboard consolidado es una lectura para
    # los cuatro roles. La actividad de movimientos dentro de su respuesta se
    # gobierna en el servicio (Solicitante sin actividad); esta operacion NO
    # amplia el permiso de `GET /inventario/movimientos`, que sigue reservado a
    # `_INVENTARIO_Y_TICKETS` (Solicitante excluido).
    ("GET", "/api/v1/dashboard/"): _TODOS,
    # Feature 010 (D-7/AC-7…AC-9/AC-17): aprovisionamiento de instituciones.
    # Es la unica incorporacion de la 010: solo Superadmin.
    ("POST", "/api/v1/control/instituciones/"): frozenset({_SUPERADMIN}),
    # Feature 011 (D-4/D-5, AC-5): gestion organizacional minima. Las seis
    # operaciones las autoriza solo el Administrador institucional; no hay permiso
    # implicito para el resto de roles ni escritura de Superadmin en tenants.
    ("GET", "/api/v1/organizacion/sedes"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}/sede"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/usuarios/{usuario_id}/sede"): _ORGANIZACION,
    (
        "GET",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): _ORGANIZACION,
    (
        "POST",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): _ORGANIZACION,
    (
        "DELETE",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}",
    ): _ORGANIZACION,
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
