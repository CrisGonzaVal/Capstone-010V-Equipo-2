import { ControlSuperadminGuard } from '../../core/guards/control-superadmin.guard';
import { controlRoutes } from './control.routes';

/**
 * Contrato de navegación del portal `/control` (Feature 010, AC-15): un
 * segmento lazy con dos vistas mínimas — login público con Clerk prebuilt y
 * alta protegida solo para Superadmin. No expone ninguna vista de CRUD (eso es
 * la Feature 012).
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

  it('no publica rutas de CRUD de instituciones/usuarios/permisos', () => {
    const prohibidas = ['crear', 'editar', 'usuarios', 'permisos', 'instituciones'];
    expect(controlRoutes.some((r) => prohibidas.includes(r.path ?? ''))).toBe(false);
  });
});
