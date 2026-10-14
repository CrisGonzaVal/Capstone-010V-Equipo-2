import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, provideRouter } from '@angular/router';
import { TestBed } from '@angular/core/testing';

import { AutenticacionService } from '../services/auth.service';
import { AutenticacionGuard } from './auth.guard';

describe('AutenticacionGuard', () => {
  const inicializar = jasmine.createSpy('inicializar');
  let autenticado: boolean;
  let router: Router;

  beforeEach(() => {
    inicializar.calls.reset();
    inicializar.and.resolveTo(undefined);
    autenticado = false;

    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        {
          provide: AutenticacionService,
          useValue: { inicializar, estaAutenticado: () => autenticado },
        },
      ],
    });

    router = TestBed.inject(Router);
  });

  function evaluar(url: string) {
    return TestBed.runInInjectionContext(() =>
      AutenticacionGuard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot),
    );
  }

  it('sin sesión redirige a /login conservando la ruta solicitada', async () => {
    const resultado = await evaluar('/tickets');

    expect(router.serializeUrl(resultado as never)).toBe('/login?retorno=%2Ftickets');
  });

  it('espera a que Clerk termine de cargar antes de decidir', async () => {
    await evaluar('/inventario');

    expect(inicializar).toHaveBeenCalled();
  });

  it('con sesión reconocida deja pasar', async () => {
    autenticado = true;

    const resultado = await evaluar('/dashboard');

    expect(resultado).toBe(true);
  });
});
