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

/** Roles con acceso al área de administración (AC-3, AC-5). */
export const ROLES_ADMINISTRATIVOS = ['Superadmin', 'Administrador'] as const;

/**
 * Roles que operan el Kanban: avanzar/retroceder estado y despachar. El
 * Solicitante consulta y crea tickets, pero no opera (AC-3, AC-6, AC-7).
 */
export const ROLES_OPERATIVOS_TICKETS = [
  'Superadmin',
  'Administrador',
  'Bodeguero',
] as const;

function contiene(roles: readonly string[], rol: string | null): boolean {
  return rol !== null && roles.includes(rol);
}

/** `true` si el rol puede operar tickets (Kanban/estado/despacho). */
export function puedeOperarTickets(rol: string | null): boolean {
  return contiene(ROLES_OPERATIVOS_TICKETS, rol);
}

/** `true` si el rol puede acceder al área administrativa. */
export function puedeAdministrar(rol: string | null): boolean {
  return contiene(ROLES_ADMINISTRATIVOS, rol);
}
