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
import { ROLES_TICKETS } from '../auth/roles';
import { RUTA_ACCESO_DENEGADO, RolGuard } from './role.guard';

/**
 * El `RolGuard` es la costura de navegación de 007: compara el rol local exacto
 * de la identidad autenticada contra los roles permitidos por la ruta. Nunca
 * redirige a `/login` (eso es del `AutenticacionGuard`) ni cierra la sesión:
 * una identidad sin permiso ve el estado dedicado de acceso denegado.
 */
describe('RolGuard', () => {
  let router: Router;
  let esperarIdentidad: jasmine.Spy;
  let cerrarSesion: jasmine.Spy;

  function crearIdentidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 1,
      sub: 'user_clerk_1',
      nombre: 'Camila',
      apellido: 'Fernández',
      correo: 'camila.fernandez@losalpes.cl',
      rol,
      institucion: { institucion_id: 'inst-los-alpes', nombre: 'Los Alpes' },
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

  /** Resuelve `esperarIdentidad` con la identidad dada (o `null`). */
  function conIdentidad(identidad: IdentidadAutenticada | null): void {
    esperarIdentidad.and.callFake(() => Promise.resolve(identidad));
  }

  function evaluar(rolesPermitidos: string[]): Promise<boolean | UrlTree> {
    return TestBed.runInInjectionContext(() =>
      RolGuard(rolesPermitidos)({} as ActivatedRouteSnapshot, {
        url: '/administracion',
      } as RouterStateSnapshot),
    ) as Promise<boolean | UrlTree>;
  }

  it('espera a que la identidad se resuelva antes de decidir', async () => {
    let resolver!: (identidad: IdentidadAutenticada | null) => void;
    esperarIdentidad.and.callFake(
      () =>
        new Promise<IdentidadAutenticada | null>((res) => {
          resolver = res;
        }),
    );

    let resultado: boolean | UrlTree | undefined;
    const pendiente = evaluar(['Administrador']).then((r) => {
      resultado = r;
    });

    // La identidad aún no llega: el guard no ha decidido.
    await Promise.resolve();
    expect(esperarIdentidad).toHaveBeenCalled();
    expect(resultado).toBeUndefined();

    resolver(crearIdentidad('Administrador'));
    await pendiente;
    expect(resultado).toBe(true);
  });

  it('activa la ruta cuando el rol local está entre los permitidos', async () => {
    conIdentidad(crearIdentidad('Administrador'));

    await expectAsync(evaluar(['Administrador', 'Superadmin'])).toBeResolvedTo(true);
  });

  it('no activa la ruta cuando el rol es distinto al permitido', async () => {
    conIdentidad(crearIdentidad('Solicitante'));

    const resultado = (await evaluar(['Administrador'])) as UrlTree;

    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('compara el rol exacto: `Admin` no es un alias de `Administrador`', async () => {
    conIdentidad(crearIdentidad('Admin'));

    const resultado = (await evaluar(['Administrador'])) as UrlTree;

    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('deniega un rol ausente/desconocido', async () => {
    conIdentidad(crearIdentidad('Desconocido'));

    const resultado = (await evaluar(['Administrador'])) as UrlTree;

    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('deniega cuando no hay identidad vinculada (sesión ausente o vínculo fallido)', async () => {
    conIdentidad(null);

    const resultado = (await evaluar(['Administrador'])) as UrlTree;

    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('deniega sin lista de roles permitidos', async () => {
    conIdentidad(crearIdentidad('Superadmin'));

    const resultado = (await evaluar([])) as UrlTree;

    expect(router.serializeUrl(resultado)).toBe(RUTA_ACCESO_DENEGADO);
  });

  it('ante denegación no redirige a login ni cierra la sesión', async () => {
    conIdentidad(crearIdentidad('Bodeguero'));

    const resultado = (await evaluar(['Administrador'])) as UrlTree;

    const url = router.serializeUrl(resultado);
    expect(url).toBe(RUTA_ACCESO_DENEGADO);
    expect(url).not.toContain('/login');
    expect(cerrarSesion).not.toHaveBeenCalled();
  });

  /**
   * Feature 012, AC-3: el guard que protege `/tickets` (con `ROLES_TICKETS`)
   * deniega al Superadmin sin tocar su sesión, y mantiene el acceso de los roles
   * de negocio. Es una decisión de navegación; la matriz del backend no cambia.
   */
  it('con ROLES_TICKETS deniega al Superadmin y conserva a los roles de negocio', async () => {
    conIdentidad(crearIdentidad('Superadmin'));
    const denegado = (await evaluar([...ROLES_TICKETS])) as UrlTree;
    expect(router.serializeUrl(denegado)).toBe(RUTA_ACCESO_DENEGADO);

    for (const rol of ['Administrador', 'Bodeguero', 'Solicitante']) {
      conIdentidad(crearIdentidad(rol));
      await expectAsync(evaluar([...ROLES_TICKETS]))
        .withContext(rol)
        .toBeResolvedTo(true);
    }
  });
});
