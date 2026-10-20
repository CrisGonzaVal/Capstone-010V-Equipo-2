import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { routes } from '../../app.routes';
import { IdentidadAutenticada } from '../../shared/interfaces';
import { AutenticacionService } from '../services/auth.service';
import { RUTA_ACCESO_DENEGADO } from './role.guard';

/**
 * Superficies de negocio retiradas al Superadmin (Feature 017, AC-15).
 *
 * A diferencia del `RolGuard` aislado, aquí se recorre el enrutador completo:
 * `/dashboard`, `/inventario`, `/tickets` y `/administracion` declaran roles de
 * negocio, así que el Superadmin es redirigido a `/acceso-denegado` incluso por
 * ruta directa y los componentes lazy nunca se cargan. Los roles de negocio
 * conservan sus permisos en `role.guard.spec.ts` y `app.routes.spec.ts` sin
 * montar componentes que consultan la API.
 */
describe('superficies retiradas al Superadmin (Feature 017, AC-15)', () => {
  function identidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 1,
      sub: 'user_clerk_1',
      nombre: 'Camila',
      apellido: 'Fernández',
      correo: 'camila.fernandez@losalpes.cl',
      rol,
      institucion: null,
    };
  }

  function configurar(rol: string): void {
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        {
          provide: AutenticacionService,
          useValue: {
            inicializar: () => Promise.resolve(),
            estaAutenticado: () => true,
            esperarIdentidad: () => Promise.resolve(identidad(rol)),
          },
        },
      ],
    });
  }

  for (const ruta of ['/dashboard', '/inventario', '/tickets', '/administracion']) {
    it(`redirige al Superadmin a /acceso-denegado en ${ruta}`, async () => {
      configurar('Superadmin');
      const router = TestBed.inject(Router);
      const harness = await RouterTestingHarness.create();

      await harness.navigateByUrl(ruta);

      expect(router.url).toBe(RUTA_ACCESO_DENEGADO);
      expect(harness.routeNativeElement?.textContent ?? '').toContain(
        'Acceso denegado',
      );
    });
  }

  it('no usa /acceso-denegado para la superficie de control del Superadmin', async () => {
    configurar('Superadmin');
    const router = TestBed.inject(Router);
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/control');

    // El login del portal es público: el Superadmin no es expulsado de /control.
    expect(router.url).toBe('/control');
  });
});
