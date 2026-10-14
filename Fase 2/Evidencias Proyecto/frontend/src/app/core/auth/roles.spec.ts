import {
  ROLES_ADMINISTRATIVOS,
  ROLES_OPERATIVOS_TICKETS,
  ROLES_TODOS,
  puedeAdministrar,
  puedeOperarTickets,
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

  it('puedeAdministrar concede solo a los roles administrativos', () => {
    expect(puedeAdministrar('Superadmin')).toBe(true);
    expect(puedeAdministrar('Administrador')).toBe(true);
    expect(puedeAdministrar('Bodeguero')).toBe(false);
    expect(puedeAdministrar('Solicitante')).toBe(false);
    expect(puedeAdministrar('Admin')).toBe(false);
    expect(puedeAdministrar(null)).toBe(false);
  });
});
