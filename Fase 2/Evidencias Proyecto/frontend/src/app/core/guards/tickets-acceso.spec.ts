import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { routes } from '../../app.routes';
import { IdentidadAutenticada } from '../../shared/interfaces';
import { AutenticacionService } from '../services/auth.service';
import { RUTA_ACCESO_DENEGADO } from './role.guard';

/**
 * Navegación real hacia `/tickets` (Feature 012, AC-3).
 *
 * A diferencia del `RolGuard` aislado, aquí se recorre el enrutador completo:
 * la ruta de negocio está protegida por `ROLES_TICKETS`, así que el Superadmin
 * es redirigido a `/acceso-denegado` y el Kanban (lazy) nunca se carga. Los
 * roles de negocio se validan a nivel de guard en `role.guard.spec.ts` para no
 * montar el componente real, que consulta la API.
 */
describe('acceso a /tickets (Feature 012, AC-3)', () => {
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

  it('redirige al Superadmin a /acceso-denegado y no renderiza el Kanban', async () => {
    configurar('Superadmin');
    const router = TestBed.inject(Router);
    const harness = await RouterTestingHarness.create();

    await harness.navigateByUrl('/tickets');

    expect(router.url).toBe(RUTA_ACCESO_DENEGADO);
    const texto = harness.routeNativeElement?.textContent ?? '';
    expect(texto).toContain('Acceso denegado');
    expect(harness.routeNativeElement?.querySelector('app-tickets')).toBeNull();
  });
});
