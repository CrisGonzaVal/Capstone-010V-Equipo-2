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

#: Los cuatro roles de la semilla (identidad autenticada, p. ej. `/auth/me`).
_TODOS: frozenset[str] = frozenset(
    {_SUPERADMIN, _ADMINISTRADOR, _BODEGUERO, _SOLICITANTE}
)
#: Roles administrativos (usuarios, departamentos y catalogo maestro).
_ADMINISTRATIVOS: frozenset[str] = frozenset({_SUPERADMIN, _ADMINISTRADOR})
#: Lectura de negocio de los tres roles institucionales (Feature 017, D-9/AC-15):
#: Superadmin deja de leer dashboard, tickets, catalogo, existencias y stock.
_LECTURA_NEGOCIO: frozenset[str] = frozenset(
    {_ADMINISTRADOR, _BODEGUERO, _SOLICITANTE}
)
#: Lectura del historial de movimientos: operativa de la institucion (sin
#: Solicitante y, desde la Feature 017, sin Superadmin).
_MOVIMIENTOS: frozenset[str] = frozenset({_ADMINISTRADOR, _BODEGUERO})

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

# --- Feature 014 (spec D-8/D-9, AC-2/AC-12/AC-15) ---------------------------
# Ciclo de vida del catalogo: transiciones, historiales y listado de gestion. Las
# cinco operaciones son exclusivas del Administrador Institucional; Superadmin no
# opera catalogo de un tenant desde la 008 y los roles operativos no gestionan el
# ciclo de vida. El gating de capacidad `catalogo` se aplica aparte.
_CICLO_VIDA_CATALOGO: frozenset[str] = frozenset({_ADMINISTRADOR})


#: Matriz explicita operacion -> roles permitidos (D-3, AC-9).
#:
#: La clave es (metodo HTTP en mayusculas, ruta completa tal como la publica el
#: contrato, con los parametros de path en su forma `{param}`). Una operacion
#: ausente de esta matriz no concede permiso a ningun rol.
#:
#: Feature 017 (D-9/AC-15): se retira **solo** Superadmin de las lecturas de
#: negocio enumeradas (`dashboard`, tickets y su detalle/historial, movimientos,
#: categorias, productos, existencias y stock). T10 agrega a esa retirada
#: `GET /tickets/catalogos`, que expone catalogo y stock del tenant. No se retira
#: ni se agrega ninguna fila: los roles institucionales conservan exactamente sus
#: permisos previos.
MATRIZ_PERMISOS: dict[tuple[str, str], frozenset[str]] = {
    # Autenticacion: identidad autenticada, cualquier rol.
    ("GET", "/api/v1/auth/me"): _TODOS,
    # Administracion de usuarios y catalogos de apoyo.
    ("GET", "/api/v1/usuarios/"): _ORGANIZACION,
    ("POST", "/api/v1/usuarios/"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/roles"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/departamentos"): _ORGANIZACION,
    ("GET", "/api/v1/usuarios/instituciones"): _ORGANIZACION,
    # Inventario: lectura de los roles institucionales; escritura administrativa
    # o de bodega. Feature 017: Superadmin ya no lee catalogo, existencias ni stock.
    ("GET", "/api/v1/inventario/categorias"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/productos"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/productos/{producto_id}"): _LECTURA_NEGOCIO,
    # 008 D-3: escritura de catalogo solo institucional (Superadmin no escribe).
    ("POST", "/api/v1/inventario/productos"): _ESCRITURA_CATALOGO,
    ("GET", "/api/v1/inventario/existencias"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/inventario/stock"): _LECTURA_NEGOCIO,
    # 017 D-9: historial de movimientos sin Superadmin; sigue sin Solicitante.
    ("GET", "/api/v1/inventario/movimientos"): _MOVIMIENTOS,
    # 008 D-3: movimientos de stock sin Superadmin (escritura institucional).
    ("POST", "/api/v1/inventario/movimientos"): _ESCRITURA_STOCK,
    # Tickets: alta para los roles institucionales; estado y despacho sin
    # Solicitante. Feature 017: Superadmin no lee tickets ni su detalle/historial.
    # T10 (D-9/AC-15): el catalogo del modal tambien es lectura de negocio
    # (productos, stock y solicitantes del tenant), no una superficie de control.
    ("GET", "/api/v1/tickets/catalogos"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/tickets/"): _LECTURA_NEGOCIO,
    # 008 D-3: alta de ticket sin Superadmin (escritura institucional).
    ("POST", "/api/v1/tickets/"): _ESCRITURA_TICKETS,
    # 008 D-3: despacho y cambio de estado sin Superadmin.
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): _ESCRITURA_STOCK,
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): _ESCRITURA_STOCK,
    # Feature 009 (D-3/AC-13/AC-14) y Feature 017 (D-9/AC-15): el dashboard
    # consolidado es lectura de los roles institucionales; Superadmin lo pierde.
    # La actividad de movimientos dentro de su respuesta se gobierna en el
    # servicio (Solicitante sin actividad).
    ("GET", "/api/v1/dashboard/"): _LECTURA_NEGOCIO,
    # Feature 010 (D-7/AC-7…AC-9/AC-17): aprovisionamiento de instituciones.
    # Es la unica incorporacion de la 010: solo Superadmin.
    ("POST", "/api/v1/control/instituciones/"): frozenset({_SUPERADMIN}),
    # Feature 012 (D-1/D-2/D-5/D-6, AC-1…AC-5/AC-13): gestion administrativa del
    # control SaaS (registro institucional, estado, dashboard y capacidades). Son
    # operaciones nuevas **aditivas** y exclusivas del Superadmin; no modifican
    # ninguna de las entradas previas.
    ("GET", "/api/v1/control/instituciones/"): frozenset({_SUPERADMIN}),
    ("GET", "/api/v1/control/instituciones/{institucion_id}"): frozenset({_SUPERADMIN}),
    ("PUT", "/api/v1/control/instituciones/{institucion_id}"): frozenset({_SUPERADMIN}),
    ("PATCH", "/api/v1/control/instituciones/{institucion_id}/estado"): frozenset(
        {_SUPERADMIN}
    ),
    ("GET", "/api/v1/control/dashboard"): frozenset({_SUPERADMIN}),
    (
        "GET",
        "/api/v1/control/instituciones/{institucion_id}/capacidades",
    ): frozenset({_SUPERADMIN}),
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}",
    ): frozenset({_SUPERADMIN}),
    # Feature 012 (T7, D-3/D-4/AC-6…AC-13): CRUD organizacional del Administrador
    # institucional (sedes, departamentos y usuarios locales). Operaciones nuevas
    # **aditivas** que no modifican ninguna entrada previa; el Administrador sigue
    # siendo el unico autorizado sobre `/organizacion/*` y comparte con Superadmin
    # las operaciones de `/usuarios/`.
    ("POST", "/api/v1/organizacion/sedes"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/sedes/{sede_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/organizacion/sedes/{sede_id}/estado"): _ORGANIZACION,
    ("GET", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("POST", "/api/v1/organizacion/departamentos"): _ORGANIZACION,
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}"): _ORGANIZACION,
    (
        "PATCH",
        "/api/v1/organizacion/departamentos/{departamento_id}/estado",
    ): _ORGANIZACION,
    ("PUT", "/api/v1/usuarios/{usuario_id}"): _ORGANIZACION,
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): _ORGANIZACION,
    # Feature 017 (D-4/D-10/AC-9): reenvio ordinario del Administrador a sus
    # Bodegueros/Solicitantes. Exclusivo del Administrador tenant; Superadmin
    # recibe 403 en toda ruta ordinaria de `/usuarios/`.
    (
        "POST",
        "/api/v1/usuarios/{usuario_id}/invitacion/reenvio",
    ): _ORGANIZACION,
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
    # Feature 013 (AC-17, plan §2): ciclo de vida del ticket. Son las cinco
    # operaciones nuevas **aditivas** de la 013 (matriz 44 -> 49): ninguna
    # entrada previa se modifica ni se retira. Los roles son exactamente los
    # del AC-17: anulacion y edicion las opera el dueño del ticket (Solicitante)
    # junto con el Administrador institucional; el rechazo es operativo de
    # bodega (Bodeguero) mas el Administrador; detalle e historial son lectura
    # de los roles institucionales. Superadmin queda fuera de toda escritura
    # (D-8) y, desde la Feature 017 (D-9/AC-15), tambien de la lectura.
    ("POST", "/api/v1/tickets/{ticket_id}/anulacion"): frozenset(
        {_ADMINISTRADOR, _SOLICITANTE}
    ),
    ("POST", "/api/v1/tickets/{ticket_id}/rechazo"): frozenset(
        {_ADMINISTRADOR, _BODEGUERO}
    ),
    ("PUT", "/api/v1/tickets/{ticket_id}"): frozenset(
        {_ADMINISTRADOR, _SOLICITANTE}
    ),
    ("GET", "/api/v1/tickets/{ticket_id}"): _LECTURA_NEGOCIO,
    ("GET", "/api/v1/tickets/{ticket_id}/historial"): _LECTURA_NEGOCIO,
    # Feature 017 (D-10/AC-8/AC-9): gobierno de Administradores por institucion.
    # Cinco operaciones nuevas **exclusivas de Superadmin**. Las rutas ordinarias
    # de `/usuarios/` dejan de conceder Superadmin (solo Administrador tenant).
    (
        "GET",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): frozenset({_SUPERADMIN}),
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/",
    ): frozenset({_SUPERADMIN}),
    (
        "PUT",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}",
    ): frozenset({_SUPERADMIN}),
    (
        "PATCH",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado",
    ): frozenset({_SUPERADMIN}),
    (
        "POST",
        "/api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/invitacion/reenvio",
    ): frozenset({_SUPERADMIN}),
    # Feature 014 (spec D-8/D-9, AC-2/AC-12/AC-15): ciclo de vida del catalogo.
    # Las cinco operaciones son nuevas y **aditivas** (matriz 55 -> 60): ninguna
    # entrada previa se modifica ni se retira. Transiciones, historiales y listado
    # de gestion quedan reservados al Administrador Institucional de su tenant;
    # Bodeguero, Solicitante y Superadmin reciben 403. El gating de la capacidad
    # `catalogo` (Feature 012) se evalua despues de esta matriz y antes del recurso.
    (
        "PATCH",
        "/api/v1/inventario/productos/{producto_id}/estado",
    ): _CICLO_VIDA_CATALOGO,
    (
        "PATCH",
        "/api/v1/inventario/categorias/{categoria_id}/estado",
    ): _CICLO_VIDA_CATALOGO,
    (
        "GET",
        "/api/v1/inventario/productos/{producto_id}/historial",
    ): _CICLO_VIDA_CATALOGO,
    (
        "GET",
        "/api/v1/inventario/categorias/{categoria_id}/historial",
    ): _CICLO_VIDA_CATALOGO,
    ("GET", "/api/v1/inventario/gestion"): _CICLO_VIDA_CATALOGO,
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
