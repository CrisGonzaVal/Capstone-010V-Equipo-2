"""Asociacion central capacidad funcional <-> operacion de negocio (Feature 012).

La Feature 012 introduce las **capacidades funcionales por institucion** (D-6): un
conjunto cerrado de seis identificadores que representan la disponibilidad global
de una funcion del producto para una institucion. No son permisos de usuario ni
capacidades de rol: son una bandera de disponibilidad persistida en `control`
(`funcion_institucion`) que se aplica como **gating adicional** a la matriz
central de permisos (`app.core.permisos`), nunca como sustituto ni modificacion.

Este modulo es la **unica fuente** de la asociacion operacion -> capacidad. Los
routers no duplican la lista: declaran la dependencia
`app.api.dependencies.requiere_capacidad(metodo, ruta)`, que consulta aqui.
`GET /api/v1/auth/me` y todas las rutas `/control/*` (Superadmin SaaS) **no**
quedan gated: `capacidad_de_operacion` devuelve `None` para ellos (plan §2).

El conjunto de identificadores validos es `CAPACIDADES`, reexportado desde el
modelo canonico de control para no mantener dos listas.
"""

from __future__ import annotations

from app.models.control_canonico import CAPACIDADES

#: Asociacion explicita (metodo HTTP, ruta completa con `{param}`) -> capacidad.
#: Es la fuente de verdad del gating: una operacion ausente no se gatea.
MAPA_OPERACION_CAPACIDAD: dict[tuple[str, str], str] = {
    # --- catalogo: consulta/gestion del catalogo institucional ---
    ("GET", "/api/v1/inventario/categorias"): "catalogo",
    ("GET", "/api/v1/inventario/categorias/{categoria_id}"): "catalogo",
    ("GET", "/api/v1/inventario/productos"): "catalogo",
    ("GET", "/api/v1/inventario/productos/{producto_id}"): "catalogo",
    ("POST", "/api/v1/inventario/productos"): "catalogo",
    # Feature 014 (plan §2.6): el ciclo de vida completo del catalogo —transiciones,
    # historiales y listado de gestion— pertenece a la capacidad `catalogo`. Son
    # cinco asociaciones nuevas; el conjunto cerrado de la 012 no se amplia.
    ("PATCH", "/api/v1/inventario/productos/{producto_id}/estado"): "catalogo",
    ("PATCH", "/api/v1/inventario/categorias/{categoria_id}/estado"): "catalogo",
    ("GET", "/api/v1/inventario/productos/{producto_id}/historial"): "catalogo",
    ("GET", "/api/v1/inventario/categorias/{categoria_id}/historial"): "catalogo",
    ("GET", "/api/v1/inventario/gestion"): "catalogo",
    # --- inventario: existencias y movimientos ---
    ("GET", "/api/v1/inventario/existencias"): "inventario",
    ("GET", "/api/v1/inventario/stock"): "inventario",
    ("GET", "/api/v1/inventario/movimientos"): "inventario",
    ("POST", "/api/v1/inventario/movimientos"): "inventario",
    # Feature 018 (spec D-6/AC-8): la lectura de ambito son las opciones de
    # filtro de existencias, la misma capacidad `inventario` que ya existe. El
    # conjunto cerrado de capacidades de la 012 no se amplia.
    ("GET", "/api/v1/inventario/ambito"): "inventario",
    # --- tickets: creacion y gestion del flujo ---
    ("GET", "/api/v1/tickets/catalogos"): "tickets",
    ("GET", "/api/v1/tickets/"): "tickets",
    ("POST", "/api/v1/tickets/"): "tickets",
    # --- kanban: tablero operativo de estado/despacho ---
    ("POST", "/api/v1/tickets/{ticket_id}/despacho"): "kanban",
    ("PATCH", "/api/v1/tickets/{ticket_id}/estado"): "kanban",
    # --- ciclo de vida 013 (plan §2): anulacion y rechazo son mutaciones del
    # ciclo de vida, la misma familia que despacho/estado -> `kanban`; edicion,
    # detalle e historial son gestion/consulta del ticket -> `tickets`. Sin
    # capacidad nueva: el conjunto cerrado de la 012 queda intacto. ---
    ("POST", "/api/v1/tickets/{ticket_id}/anulacion"): "kanban",
    ("POST", "/api/v1/tickets/{ticket_id}/rechazo"): "kanban",
    ("PUT", "/api/v1/tickets/{ticket_id}"): "tickets",
    ("GET", "/api/v1/tickets/{ticket_id}"): "tickets",
    ("GET", "/api/v1/tickets/{ticket_id}/historial"): "tickets",
    # --- dashboard: dashboard analitico del tenant ---
    ("GET", "/api/v1/dashboard/"): "dashboard",
    # --- gestion_organizacional: sedes, departamentos, usuarios y encargados ---
    ("GET", "/api/v1/organizacion/sedes"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}/sede"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/usuarios/{usuario_id}/sede"): "gestion_organizacional",
    (
        "GET",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): "gestion_organizacional",
    (
        "POST",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados",
    ): "gestion_organizacional",
    (
        "DELETE",
        "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}",
    ): "gestion_organizacional",
    ("POST", "/api/v1/organizacion/sedes"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/sedes/{sede_id}"): "gestion_organizacional",
    ("PATCH", "/api/v1/organizacion/sedes/{sede_id}/estado"): "gestion_organizacional",
    ("GET", "/api/v1/organizacion/departamentos"): "gestion_organizacional",
    ("POST", "/api/v1/organizacion/departamentos"): "gestion_organizacional",
    ("PUT", "/api/v1/organizacion/departamentos/{departamento_id}"): "gestion_organizacional",
    (
        "PATCH",
        "/api/v1/organizacion/departamentos/{departamento_id}/estado",
    ): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/"): "gestion_organizacional",
    ("POST", "/api/v1/usuarios/"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/roles"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/departamentos"): "gestion_organizacional",
    ("GET", "/api/v1/usuarios/instituciones"): "gestion_organizacional",
    ("PUT", "/api/v1/usuarios/{usuario_id}"): "gestion_organizacional",
    ("PATCH", "/api/v1/usuarios/{usuario_id}/estado"): "gestion_organizacional",
    # Feature 017 (D-4/D-10): el reenvio ordinario de invitacion es una operacion
    # de gestion de usuarios del tenant, la misma capacidad que sus altas.
    (
        "POST",
        "/api/v1/usuarios/{usuario_id}/invitacion/reenvio",
    ): "gestion_organizacional",
}



def capacidad_de_operacion(metodo: str, ruta: str) -> str | None:
    """Capacidad funcional asociada a `(metodo, ruta)`, o `None` si no se gatea.

    La comparacion es exacta sobre el metodo en mayusculas y la ruta del contrato
    (con los parametros de path en su forma `{param}`). Una operacion no asociada
    (p. ej. `GET /api/v1/auth/me` o `/control/*`) devuelve `None`: no se aplica
    gating de capacidad.
    """
    return MAPA_OPERACION_CAPACIDAD.get((metodo.upper(), ruta))
