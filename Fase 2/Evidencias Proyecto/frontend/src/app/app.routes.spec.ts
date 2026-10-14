import { routes } from './app.routes';
import { AutenticacionGuard } from './core/guards/auth.guard';

/**
 * La configuración de rutas es parte del contrato de AC-1/AC-3/AC-4: las rutas
 * de negocio exigen sesión y la app no publica registro.
 */
describe('app.routes', () => {
  function ruta(path: string) {
    return routes.find((r) => r.path === path);
  }

  it('protege las rutas de negocio con el guard de autenticación', () => {
    for (const path of ['dashboard', 'inventario', 'tickets', 'administracion']) {
      expect(ruta(path)?.canActivate).toContain(AutenticacionGuard);
    }
  });

  it('expone /login sin guard', () => {
    expect(ruta('login')).toBeTruthy();
    expect(ruta('login')?.canActivate).toBeUndefined();
  });

  it('no expone ninguna ruta de registro', () => {
    const prohibidas = ['registro', 'registrar', 'signup', 'sign-up', 'register'];
    expect(routes.some((r) => prohibidas.includes(r.path ?? ''))).toBe(false);
  });
});
