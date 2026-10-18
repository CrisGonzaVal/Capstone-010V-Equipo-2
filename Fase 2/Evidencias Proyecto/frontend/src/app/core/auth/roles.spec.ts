import {
  ROLES_ADMINISTRATIVOS,
  ROLES_ASIGNABLES_ADMINISTRADOR,
  ROLES_OPERATIVOS_TICKETS,
  ROLES_TICKETS,
  ROLES_TODOS,
  puedeAdministrar,
  puedeAsignarRol,
  puedeOperarTickets,
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

  it('los roles con acceso a administración son Superadmin y Administrador', () => {
    expect(ROLES_ADMINISTRATIVOS).toEqual(['Superadmin', 'Administrador']);
    expect(ROLES_ADMINISTRATIVOS as readonly string[]).not.toContain('Bodeguero');
    expect(ROLES_ADMINISTRATIVOS as readonly string[]).not.toContain('Solicitante');
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

  it('puedeAdministrar concede solo a los roles administrativos', () => {
    expect(puedeAdministrar('Superadmin')).toBe(true);
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
});
