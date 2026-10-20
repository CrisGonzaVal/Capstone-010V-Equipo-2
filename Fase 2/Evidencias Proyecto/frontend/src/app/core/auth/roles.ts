/**
 * Matriz de roles de la Feature 007 (D-1).
 *
 * Los cuatro nombres de rol son identidades **distintas** de la semilla. `Admin`
 * es solo una abreviatura documental de `Administrador`: no existe alias ni
 * normalización runtime. Un rol ausente o desconocido nunca concede permiso.
 *
 * Estas constantes son la única fuente de la navegación (`app.routes.ts`), del
 * layout (`app.component.ts`) y de las capacidades de la vista de tickets. La
 * frontera de seguridad real está en la API (D-2): lo de aquí es navegación y
 * comodidad de interfaz.
 */
export const ROLES_TODOS = [
  'Superadmin',
  'Administrador',
  'Bodeguero',
  'Solicitante',
] as const;

/**
 * Roles con acceso al área de administración (AC-3, AC-5).
 *
 * Desde la Feature 017 (D-9/AC-15, T10) solo el Administrador institucional: el
 * Superadmin perdió `/administracion` porque las rutas tenant `/usuarios/*` y
 * `/organizacion/*` le responden 403. Su gobierno de Administradores vive en
 * `/control/instituciones/:institucionId/administradores`.
 */
export const ROLES_ADMINISTRATIVOS = ['Administrador'] as const;

/**
 * Roles con navegación a las superficies de negocio (Feature 017, D-9/AC-15).
 *
 * Es `ROLES_TODOS` menos `Superadmin`: dashboard, inventario y tickets exponen
 * datos operativos del tenant y la única superficie del Superadmin es
 * `/control/*` más la gestión de Administradores. Es una lista de
 * **navegación/UI**; la frontera de seguridad real sigue en la API (D-2).
 */
export const ROLES_NEGOCIO = [
  'Administrador',
  'Bodeguero',
  'Solicitante',
] as const;

/**
 * Roles con acceso al portal de control (Feature 010, AC-7/AC-15): **solo**
 * Superadmin puede aprovisionar instituciones. A diferencia de la administración
 * institucional, el alta de tenants es una capacidad global, no delegable.
 */
export const ROLES_CONTROL = ['Superadmin'] as const;

/**
 * Roles que operan el Kanban: avanzar/retroceder estado y despachar. El
 * Solicitante consulta y crea tickets, pero no opera (AC-3, AC-6, AC-7).
 *
 * **No** es la lista de acceso a la vista de tickets: el Superadmin opera por
 * API, pero desde la Feature 012 no navega a `/tickets` (ver `ROLES_TICKETS`).
 */
export const ROLES_OPERATIVOS_TICKETS = [
  'Superadmin',
  'Administrador',
  'Bodeguero',
] as const;

/**
 * Roles que acceden a dashboard, inventario y tickets/Kanban por navegación
 * (Feature 012, AC-3; Feature 017, AC-15). Las tres superficies comparten el
 * conjunto de negocio: el Superadmin no activa ninguna. El Administrador, el
 * Bodeguero y el Solicitante conservan el acceso tal como estaba configurado.
 *
 * Son listas de **navegación/UI**: no recortan la matriz de permisos del
 * backend, que sigue siendo la frontera de seguridad real (D-2).
 */
export const ROLES_DASHBOARD = ROLES_NEGOCIO;
export const ROLES_INVENTARIO = ROLES_NEGOCIO;
export const ROLES_TICKETS = ROLES_NEGOCIO;

/**
 * Roles que un Administrador puede asignar en el alta/edición de usuarios
 * (Feature 007, D-6/AC-10). Refleja exactamente la regla del backend
 * (`usuario_service._validar_rol_asignable`): un Administrador solo puede
 * asignar `Bodeguero` o `Solicitante`; `Superadmin` y `Administrador` responden
 * 403 al intentarse.
 *
 * Es una constante de **presentación** para alinear los combos con esa regla,
 * no una autorización: la frontera sigue en la API (D-2).
 */
export const ROLES_ASIGNABLES_ADMINISTRADOR = ['Bodeguero', 'Solicitante'] as const;

/**
 * Roles que anulan tickets (Feature 013, AC-17: `POST /tickets/{id}/anulacion`).
 * En la vista de detalle, el Solicitante además debe ser el dueño del ticket.
 */
export const ROLES_ANULACION_TICKETS = ['Administrador', 'Solicitante'] as const;

/**
 * Roles que rechazan tickets (Feature 013, AC-17: `POST /tickets/{id}/rechazo`).
 * El Bodeguero opera tickets de su institución; no se exige condición de dueño.
 */
export const ROLES_RECHAZO_TICKETS = ['Administrador', 'Bodeguero'] as const;

/**
 * Roles que editan tickets (Feature 013, AC-17: `PUT /tickets/{id}`). En la
 * vista de detalle, el Solicitante además debe ser el dueño del ticket.
 */
export const ROLES_EDICION_TICKETS = ['Administrador', 'Solicitante'] as const;

function contiene(roles: readonly string[], rol: string | null): boolean {
  return rol !== null && roles.includes(rol);
}

/**
 * `true` si `rolCreador` puede asignar `rolDestino` en el alta/edición.
 *
 * Réplica de la regla de dominio del backend (`_validar_rol_asignable`,
 * D-6/AC-10): Superadmin puede asignar cualquiera de los cuatro; Administrador
 * solo `Bodeguero`/`Solicitante`; cualquier otro rol creador, ninguno.
 */
export function puedeAsignarRol(
  rolCreador: string | null,
  rolDestino: string,
): boolean {
  if (rolCreador === 'Superadmin') {
    return true;
  }
  if (rolCreador === 'Administrador') {
    return (ROLES_ASIGNABLES_ADMINISTRADOR as readonly string[]).includes(
      rolDestino,
    );
  }
  return false;
}

/** `true` si el rol puede operar tickets (Kanban/estado/despacho). */
export function puedeOperarTickets(rol: string | null): boolean {
  return contiene(ROLES_OPERATIVOS_TICKETS, rol);
}

/** `true` si el rol puede navegar al dashboard consolidado (017, AC-15). */
export function puedeVerDashboard(rol: string | null): boolean {
  return contiene(ROLES_DASHBOARD, rol);
}

/** `true` si el rol puede navegar al inventario (017, AC-15). */
export function puedeVerInventario(rol: string | null): boolean {
  return contiene(ROLES_INVENTARIO, rol);
}

/** `true` si el rol puede navegar a la vista de tickets/Kanban (AC-3). */
export function puedeVerTickets(rol: string | null): boolean {
  return contiene(ROLES_TICKETS, rol);
}

/**
 * `true` si el rol puede anular tickets (Feature 013, AC-17/AC-24).
 *
 * Espejo de la matriz: Administrador y Solicitante; en la vista de detalle el
 * Solicitante además debe ser el dueño (la vista lo exige junto a esto).
 * Presentación pura: la autorización real la decide la API (D-2).
 */
export function puedeAnularTicket(rol: string | null): boolean {
  return contiene(ROLES_ANULACION_TICKETS, rol);
}

/**
 * `true` si el rol puede rechazar tickets (Feature 013, AC-17/AC-24).
 *
 * Espejo de la matriz: Administrador y Bodeguero, sin condición de dueño.
 */
export function puedeRechazarTicket(rol: string | null): boolean {
  return contiene(ROLES_RECHAZO_TICKETS, rol);
}

/**
 * `true` si el rol puede editar tickets (Feature 013, AC-17/AC-24).
 *
 * Espejo de la matriz: Administrador y Solicitante; en la vista de detalle el
 * Solicitante además debe ser el dueño.
 */
export function puedeEditarTicket(rol: string | null): boolean {
  return contiene(ROLES_EDICION_TICKETS, rol);
}

/** `true` si el rol puede acceder al área administrativa. */
export function puedeAdministrar(rol: string | null): boolean {
  return contiene(ROLES_ADMINISTRATIVOS, rol);
}
