import {
  ROLES_ADMINISTRATIVOS,
  ROLES_ANULACION_TICKETS,
  ROLES_ASIGNABLES_ADMINISTRADOR,
  ROLES_DASHBOARD,
  ROLES_EDICION_TICKETS,
  ROLES_GESTION_CATALOGO,
  ROLES_INVENTARIO,
  ROLES_NEGOCIO,
  ROLES_OPERATIVOS_TICKETS,
  ROLES_RECHAZO_TICKETS,
  ROLES_TICKETS,
  ROLES_TODOS,
  puedeAdministrar,
  puedeAnularTicket,
  puedeAsignarRol,
  puedeEditarTicket,
  puedeGestionarCatalogo,
  puedeOperarTickets,
  puedeRechazarTicket,
  puedeVerDashboard,
  puedeVerFiltrosInventario,
  puedeVerInventario,
  puedeVerTickets,
} from './roles';

/**
 * La matriz de roles de 007 (D-1) es explícita: cuatro literales distintos, sin
 * alias `Admin` y sin normalización runtime. Estas constantes son la única
 * fuente de la navegación y de las capacidades de la vista de tickets.
 */
describe('roles', () => {
  it('expone los cuatro literales exactos y ningún alias `Admin`', () => {
    expect(ROLES_TODOS).toEqual([
      'Superadmin',
      'Administrador',
      'Bodeguero',
      'Solicitante',
    ]);
    expect(ROLES_TODOS as readonly string[]).not.toContain('Admin');
  });

  /**
   * Feature 017 (D-9/AC-15, T10): el Superadmin perdió toda la superficie de
   * negocio, incluida `/administracion` (la API tenant `/usuarios/*` y
   * `/organizacion/*` le responde 403). La gestión de Administradores vive en
   * `/control/instituciones/:id/administradores`.
   */
  it('los roles con acceso a administración se reducen al Administrador', () => {
    expect(ROLES_ADMINISTRATIVOS).toEqual(['Administrador']);
    expect(ROLES_ADMINISTRATIVOS as readonly string[]).not.toContain('Superadmin');
    expect(ROLES_ADMINISTRATIVOS as readonly string[]).not.toContain('Bodeguero');
    expect(ROLES_ADMINISTRATIVOS as readonly string[]).not.toContain('Solicitante');
  });

  it('la superficie de dashboard e inventario excluye al Superadmin (Feature 017, AC-15)', () => {
    for (const roles of [ROLES_DASHBOARD, ROLES_INVENTARIO, ROLES_NEGOCIO]) {
      expect(roles as readonly string[]).not.toContain('Superadmin');
      for (const rol of ['Administrador', 'Bodeguero', 'Solicitante']) {
        expect(roles as readonly string[]).withContext(rol).toContain(rol);
      }
    }
  });

  it('solo el Solicitante queda fuera de la operación de tickets (AC-3)', () => {
    expect(ROLES_OPERATIVOS_TICKETS).toEqual([
      'Superadmin',
      'Administrador',
      'Bodeguero',
    ]);
    expect(ROLES_OPERATIVOS_TICKETS as readonly string[]).not.toContain('Solicitante');
  });

  it('puedeOperarTickets concede solo a los roles operativos', () => {
    expect(puedeOperarTickets('Bodeguero')).toBe(true);
    expect(puedeOperarTickets('Administrador')).toBe(true);
    expect(puedeOperarTickets('Superadmin')).toBe(true);
    expect(puedeOperarTickets('Solicitante')).toBe(false);
  });

  it('puedeOperarTickets no concede a un rol inexistente, alias o ausente', () => {
    expect(puedeOperarTickets('Admin')).toBe(false);
    expect(puedeOperarTickets('Desconocido')).toBe(false);
    expect(puedeOperarTickets(null)).toBe(false);
  });

  it('los roles con acceso a /tickets excluyen solo al Superadmin (Feature 012, AC-3)', () => {
    expect(ROLES_TICKETS).toEqual(['Administrador', 'Bodeguero', 'Solicitante']);
    expect(ROLES_TICKETS as readonly string[]).not.toContain('Superadmin');
    // La exclusión es de navegación: la matriz operativa del backend no cambia.
    expect(ROLES_OPERATIVOS_TICKETS as readonly string[]).toContain('Superadmin');
  });

  it('puedeVerTickets concede a los roles de negocio y nunca al Superadmin', () => {
    expect(puedeVerTickets('Administrador')).toBe(true);
    expect(puedeVerTickets('Bodeguero')).toBe(true);
    expect(puedeVerTickets('Solicitante')).toBe(true);
    expect(puedeVerTickets('Superadmin')).toBe(false);
    expect(puedeVerTickets('Admin')).toBe(false);
    expect(puedeVerTickets(null)).toBe(false);
  });

  it('puedeVerDashboard y puedeVerInventario conceden solo a los roles de negocio', () => {
    for (const rol of ['Administrador', 'Bodeguero', 'Solicitante']) {
      expect(puedeVerDashboard(rol)).withContext(rol).toBe(true);
      expect(puedeVerInventario(rol)).withContext(rol).toBe(true);
    }
    for (const rol of ['Superadmin', 'Admin', null]) {
      expect(puedeVerDashboard(rol)).withContext(String(rol)).toBe(false);
      expect(puedeVerInventario(rol)).withContext(String(rol)).toBe(false);
    }
  });

  it('puedeAdministrar concede solo al Administrador (Feature 017, AC-15)', () => {
    expect(puedeAdministrar('Superadmin')).toBe(false);
    expect(puedeAdministrar('Administrador')).toBe(true);
    expect(puedeAdministrar('Bodeguero')).toBe(false);
    expect(puedeAdministrar('Solicitante')).toBe(false);
    expect(puedeAdministrar('Admin')).toBe(false);
    expect(puedeAdministrar(null)).toBe(false);
  });

  it('los roles asignables por un Administrador son Bodeguero y Solicitante (D-6/AC-10)', () => {
    expect(ROLES_ASIGNABLES_ADMINISTRADOR).toEqual(['Bodeguero', 'Solicitante']);
    expect(ROLES_ASIGNABLES_ADMINISTRADOR as readonly string[]).not.toContain(
      'Superadmin',
    );
    expect(ROLES_ASIGNABLES_ADMINISTRADOR as readonly string[]).not.toContain(
      'Administrador',
    );
  });

  it('puedeAsignarRol replica la regla del backend por rol creador (D-6/AC-10)', () => {
    // Superadmin asigna los cuatro.
    expect(puedeAsignarRol('Superadmin', 'Superadmin')).toBe(true);
    expect(puedeAsignarRol('Superadmin', 'Administrador')).toBe(true);
    expect(puedeAsignarRol('Superadmin', 'Bodeguero')).toBe(true);
    expect(puedeAsignarRol('Superadmin', 'Solicitante')).toBe(true);
    // Administrador solo Bodeguero/Solicitante.
    expect(puedeAsignarRol('Administrador', 'Bodeguero')).toBe(true);
    expect(puedeAsignarRol('Administrador', 'Solicitante')).toBe(true);
    expect(puedeAsignarRol('Administrador', 'Superadmin')).toBe(false);
    expect(puedeAsignarRol('Administrador', 'Administrador')).toBe(false);
  });

  it('puedeAsignarRol no concede a un creador no administrativo, ausente o alias', () => {
    expect(puedeAsignarRol('Bodeguero', 'Bodeguero')).toBe(false);
    expect(puedeAsignarRol('Solicitante', 'Solicitante')).toBe(false);
    expect(puedeAsignarRol(null, 'Bodeguero')).toBe(false);
    expect(puedeAsignarRol('Admin', 'Bodeguero')).toBe(false);
  });

  // --- Ciclo de vida del ticket (Feature 013, AC-17/AC-24) ---

  it('los conjuntos de roles del ciclo de vida son los exactos del AC-17', () => {
    expect(ROLES_ANULACION_TICKETS).toEqual(['Administrador', 'Solicitante']);
    expect(ROLES_RECHAZO_TICKETS).toEqual(['Administrador', 'Bodeguero']);
    expect(ROLES_EDICION_TICKETS).toEqual(['Administrador', 'Solicitante']);
    // El Superadmin no opera ninguna escritura de ticket (403 por matriz).
    expect(ROLES_ANULACION_TICKETS as readonly string[]).not.toContain('Superadmin');
    expect(ROLES_RECHAZO_TICKETS as readonly string[]).not.toContain('Superadmin');
    expect(ROLES_EDICION_TICKETS as readonly string[]).not.toContain('Superadmin');
  });

  it('puedeAnularTicket concede solo a Administrador y Solicitante dueños', () => {
    expect(puedeAnularTicket('Administrador')).toBe(true);
    expect(puedeAnularTicket('Solicitante')).toBe(true);
    expect(puedeAnularTicket('Bodeguero')).toBe(false);
    expect(puedeAnularTicket('Superadmin')).toBe(false);
    expect(puedeAnularTicket('Admin')).toBe(false);
    expect(puedeAnularTicket(null)).toBe(false);
  });

  it('puedeRechazarTicket concede solo a Administrador y Bodeguero', () => {
    expect(puedeRechazarTicket('Administrador')).toBe(true);
    expect(puedeRechazarTicket('Bodeguero')).toBe(true);
    expect(puedeRechazarTicket('Solicitante')).toBe(false);
    expect(puedeRechazarTicket('Superadmin')).toBe(false);
    expect(puedeRechazarTicket('Admin')).toBe(false);
    expect(puedeRechazarTicket(null)).toBe(false);
  });

  it('puedeEditarTicket concede solo a Administrador y Solicitante', () => {
    expect(puedeEditarTicket('Administrador')).toBe(true);
    expect(puedeEditarTicket('Solicitante')).toBe(true);
    expect(puedeEditarTicket('Bodeguero')).toBe(false);
    expect(puedeEditarTicket('Superadmin')).toBe(false);
    expect(puedeEditarTicket('Admin')).toBe(false);
    expect(puedeEditarTicket(null)).toBe(false);
  });

  // --- Ciclo de vida del catálogo (Feature 014, AC-11/AC-15) ---

  it('la gestión del catálogo es exclusiva del Administrador', () => {
    expect(ROLES_GESTION_CATALOGO).toEqual(['Administrador']);
    expect(puedeGestionarCatalogo('Administrador')).toBe(true);
    for (const rol of ['Superadmin', 'Bodeguero', 'Solicitante', 'Admin', null]) {
      expect(puedeGestionarCatalogo(rol))
        .withContext(String(rol))
        .toBe(false);
    }
  });

  // --- Filtros de inventario por sede y departamento (Feature 018, T6/T7) ---

  /**
   * AC-5/AC-8: los filtros organizacionales son visibles solo para
   * Administrador y Bodeguero. Es presentación: la API sigue autorizando.
   */
  it('puedeVerFiltrosInventario concede solo a Administrador y Bodeguero (AC-5/AC-8)', () => {
    expect(puedeVerFiltrosInventario('Administrador')).toBe(true);
    expect(puedeVerFiltrosInventario('Bodeguero')).toBe(true);
    expect(puedeVerFiltrosInventario('Solicitante')).toBe(false);
    expect(puedeVerFiltrosInventario('Superadmin')).toBe(false);
  });

  it('puedeVerFiltrosInventario no concede a alias, desconocido ni ausente (AC-5)', () => {
    for (const rol of ['Admin', 'Desconocido', null]) {
      expect(puedeVerFiltrosInventario(rol)).withContext(String(rol)).toBe(false);
    }
  });

  /**
   * AC-7: el Solicitante conserva la vista de inventario tal como está; lo que
   * no recibe son los filtros organizacionales (que exigen lectura de ámbito).
   */
  it('el Solicitante conserva la vista de inventario pero no sus filtros (AC-7)', () => {
    expect(puedeVerInventario('Solicitante')).toBe(true);
    expect(puedeVerFiltrosInventario('Solicitante')).toBe(false);
  });

  /** AC-8: el Superadmin sigue sin acceso a inventario ni a sus filtros. */
  it('el Superadmin sigue denegado en inventario y en sus filtros (AC-8)', () => {
    expect(puedeVerInventario('Superadmin')).toBe(false);
    expect(puedeVerFiltrosInventario('Superadmin')).toBe(false);
  });
});
