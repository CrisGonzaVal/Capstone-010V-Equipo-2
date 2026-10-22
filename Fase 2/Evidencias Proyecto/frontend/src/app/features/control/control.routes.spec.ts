import { ControlSuperadminGuard } from '../../core/guards/control-superadmin.guard';
import { controlRoutes } from './control.routes';

/**
 * Contrato de navegación del portal `/control` (Features 010 y 012).
 *
 * El portal es un segmento lazy con el login público con Clerk prebuilt (`''`,
 * sin guard), el alta de institución y la gestión administrativa SaaS del
 * Superadmin (`dashboard`, `instituciones`, capacidades por institución y
 * Administradores por institución de la Feature 017), todas protegidas por el
 * guard exacto de Superadmin. No monta el layout operativo de tenant ni ofrece
 * selector de esquema.
 */
describe('controlRoutes', () => {
  function ruta(path: string) {
    return controlRoutes.find((r) => r.path === path);
  }

  it('expone el login de control sin guard', () => {
    const login = ruta('');
    expect(login).toBeTruthy();
    expect(login?.canActivate).toBeUndefined();
  });

  it('protege el alta con el guard exacto de Superadmin', () => {
    const alta = ruta('alta');
    expect(alta).toBeTruthy();
    expect(alta?.canActivate).toContain(ControlSuperadminGuard);
  });

  it('publica las vistas de gestión SaaS protegidas por el guard de Superadmin', () => {
    const protegidas = [
      'dashboard',
      'instituciones',
      'instituciones/:institucionId/capacidades',
      // Feature 017, AC-15: la gestión de Administradores vive en /control,
      // no en /administracion, y es la vía del Superadmin para ese gobierno.
      'instituciones/:institucionId/administradores',
    ];
    for (const path of protegidas) {
      const definicion = ruta(path);
      expect(definicion).withContext(path).toBeTruthy();
      expect(definicion?.canActivate).withContext(path).toContain(
        ControlSuperadminGuard,
      );
    }
  });

  it('carga cada vista de gestión de forma perezosa, sin módulos', () => {
    for (const path of [
      'dashboard',
      'instituciones',
      'instituciones/:institucionId/capacidades',
      'instituciones/:institucionId/administradores',
    ]) {
      const definicion = ruta(path);
      expect(typeof definicion?.loadComponent).withContext(path).toBe('function');
      expect(definicion?.loadChildren).withContext(path).toBeUndefined();
    }
  });
});
