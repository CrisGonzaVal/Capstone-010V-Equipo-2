import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
  UrlTree,
  provideRouter,
} from '@angular/router';
import { TestBed } from '@angular/core/testing';

import { IdentidadAutenticada } from '../../shared/interfaces';
import { AutenticacionService } from '../services/auth.service';
import { RUTA_ACCESO_DENEGADO } from './role.guard';
import { ControlSuperadminGuard } from './control-superadmin.guard';

/**
 * El `ControlSuperadminGuard` (Feature 010, AC-7/AC-9/AC-15) es la costura de
 * navegación del portal `/control`: solo el rol exacto `Superadmin` activa la
 * ruta de alta; cualquier otro rol —o una identidad no resuelta— se redirige a
 * `/acceso-denegado` sin cerrar sesión. No es frontera de seguridad: el backend
 * vuelve a validar token y matriz en cada petición.
 */
describe('ControlSuperadminGuard', () => {
  let router: Router;
  let esperarIdentidad: jasmine.Spy;
  let cerrarSesion: jasmine.Spy;

  function crearIdentidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 1,
      sub: 'user_clerk_1',
      nombre: 'Sofía',
      apellido: 'Cárdenas',
      correo: 'sofia.cardenas@compustock.cl',
      rol,
      institucion: null,
    };
  }

  beforeEach(() => {
    esperarIdentidad = jasmine
      .createSpy('esperarIdentidad')
      .and.callFake(() => Promise.resolve(null));
    cerrarSesion = jasmine.createSpy('cerrarSesion').and.resolveTo(undefined);

    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: AutenticacionService, useValue: { esperarIdentidad, cerrarSesion } },
      ],
    });

    router = TestBed.inject(Router);
  });

  function conIdentidad(identidad: IdentidadAutenticada | null): void {
    esperarIdentidad.and.callFake(() => Promise.resolve(identidad));
  }

  function evaluar(): Promise<boolean | UrlTree> {
    return TestBed.runInInjectionContext(() =>
      ControlSuperadminGuard({} as ActivatedRouteSnapshot, {
        url: '/control/alta',
      } as RouterStateSnapshot),
    ) as Promise<boolean | UrlTree>;
  }

  it('activa la ruta cuando el rol es exactamente Superadmin', async () => {
    conIdentidad(crearIdentidad('Superadmin'));

    await expectAsync(evaluar()).toBeResolvedTo(true);
  });

  it('deniega al Administrador llevándolo a /acceso-denegado', async () => {
    conIdentidad(crearIdentidad('Administrador'));

    const resultado = (await evaluar()) as UrlTree;
    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('deniega a Bodeguero y Solicitante', async () => {
    for (const rol of ['Bodeguero', 'Solicitante']) {
      conIdentidad(crearIdentidad(rol));

      const resultado = (await evaluar()) as UrlTree;
      expect(router.serializeUrl(resultado)).withContext(rol).toBe(RUTA_ACCESO_DENEGADO);
    }
  });

  it('compara el rol exacto: `superadmin` no concede', async () => {
    conIdentidad(crearIdentidad('superadmin'));

    const resultado = (await evaluar()) as UrlTree;
    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('deniega cuando no hay identidad vinculada', async () => {
    conIdentidad(null);

    const resultado = (await evaluar()) as UrlTree;
    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('ante denegación no cierra la sesión', async () => {
    conIdentidad(crearIdentidad('Bodeguero'));

    const resultado = (await evaluar()) as UrlTree;
    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
    expect(cerrarSesion).not.toHaveBeenCalled();
  });
});
