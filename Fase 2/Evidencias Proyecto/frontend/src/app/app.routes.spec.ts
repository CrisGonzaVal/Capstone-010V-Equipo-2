import { routes } from './app.routes';
import { AutenticacionGuard } from './core/guards/auth.guard';
import { ROLES_ADMINISTRATIVOS, ROLES_TICKETS, ROLES_TODOS } from './core/auth/roles';

/**
 * La configuración de rutas es parte del contrato de AC-1/AC-3/AC-4: las rutas
 * de negocio exigen sesión y rol (AC-2/AC-3), y la app no publica registro.
 */
describe('app.routes', () => {
  function ruta(path: string) {
    return routes.find((r) => r.path === path);
  }

  /** Los roles declarados por la ruta para su guard de rol (contrato legible). */
  function rolesDe(path: string): readonly string[] | undefined {
    return ruta(path)?.data?.['roles'];
  }

  it('protege las rutas de negocio con el guard de autenticación', () => {
    for (const path of ['dashboard', 'inventario', 'tickets', 'administracion']) {
      expect(ruta(path)?.canActivate).toContain(AutenticacionGuard);
    }
  });

  it('combina sesión y rol en las cuatro áreas de negocio', () => {
    for (const path of ['dashboard', 'inventario', 'tickets', 'administracion']) {
      const guardas = ruta(path)?.canActivate ?? [];
      // Sesión primero (redirige a login), y luego un guard de rol que deniega
      // sin cerrar sesión.
      expect(guardas[0]).toBe(AutenticacionGuard);
      expect(typeof guardas[1]).toBe('function');
      expect(guardas[1]).not.toBe(AutenticacionGuard);
    }
  });

  it('permite dashboard e inventario a los cuatro roles (AC-5)', () => {
    for (const path of ['dashboard', 'inventario']) {
      expect(rolesDe(path)).withContext(path).toEqual(ROLES_TODOS);
    }
  });

  it('excluye solo al Superadmin de /tickets y conserva a los roles de negocio (Feature 012, AC-3)', () => {
    expect(rolesDe('tickets')).toEqual(ROLES_TICKETS);
    expect(rolesDe('tickets')).not.toContain('Superadmin');
    for (const rol of ['Administrador', 'Bodeguero', 'Solicitante']) {
      expect(rolesDe('tickets')).withContext(rol).toContain(rol);
    }
  });

  it('restringe administración a Superadmin y Administrador (AC-3, AC-5)', () => {
    expect(rolesDe('administracion')).toEqual(ROLES_ADMINISTRATIVOS);
    expect(rolesDe('administracion')).not.toContain('Bodeguero');
    expect(rolesDe('administracion')).not.toContain('Solicitante');
  });

  it('conserva la redirección de la raíz a dashboard (AC-5)', () => {
    const raiz = ruta('');
    expect(raiz?.redirectTo).toBe('dashboard');
    expect(raiz?.pathMatch).toBe('full');
  });

  it('expone /login sin guard', () => {
    expect(ruta('login')).toBeTruthy();
    expect(ruta('login')?.canActivate).toBeUndefined();
    expect(ruta('login')?.data?.['roles']).toBeUndefined();
  });

  it('expone el estado de acceso denegado sin exigir rol', () => {
    const accesoDenegado = ruta('acceso-denegado');
    expect(accesoDenegado).toBeTruthy();
    expect(accesoDenegado?.canActivate).toBeUndefined();
  });

  it('no expone ninguna ruta de registro', () => {
    const prohibidas = ['registro', 'registrar', 'signup', 'sign-up', 'register'];
    expect(routes.some((r) => prohibidas.includes(r.path ?? ''))).toBe(false);
  });
});
