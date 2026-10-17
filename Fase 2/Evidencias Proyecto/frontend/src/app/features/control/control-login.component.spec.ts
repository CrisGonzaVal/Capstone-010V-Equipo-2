import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { crearClerkFalso, InstanciaClerkFalsa } from '../../../testing/clerk-falso';
import { CARGADOR_CLERK } from '../../core/services/auth.service';
import { ControlLoginComponent } from './control-login.component';

/**
 * Login del portal `/control` (Feature 010, AC-7/AC-15): reutiliza la UI
 * prebuilt de Clerk ya embebida (`mountSignIn`) y la sesión que administra
 * `AutenticacionService`. No introduce un segundo mecanismo de sesión ni un
 * formulario propio. Tras reconocerse la sesión navega al alta de control.
 */
describe('ControlLoginComponent', () => {
  let clerk: InstanciaClerkFalsa;
  let router: jasmine.SpyObj<Router>;
  let httpMock: HttpTestingController;

  async function montar(
    opciones: { sesionActiva?: boolean } = {},
  ): Promise<ComponentFixture<ControlLoginComponent>> {
    clerk = crearClerkFalso();
    router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);
    router.navigateByUrl.and.resolveTo(true);

    await TestBed.configureTestingModule({
      imports: [ControlLoginComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: CARGADOR_CLERK, useValue: () => Promise.resolve(clerk) },
        { provide: Router, useValue: router },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    // Sesión preexistente: se firma antes de crear el componente para que el
    // `AutenticacionService` la reconozca durante su arranque, que es el caso
    // real (entrar a `/control` con sesión de Clerk ya activa).
    if (opciones.sesionActiva) {
      clerk.firmarSesion();
    }
    const fixture = TestBed.createComponent(ControlLoginComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture;
  }

  /** Responde `/auth/me` para no dejar la petición colgada al firmar sesión. */
  function responderIdentidad(): void {
    httpMock.match(() => true).forEach((peticion) => peticion.flush({}));
  }

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  it('monta la UI prebuilt de Clerk, sin formulario ni login local', async () => {
    const fixture = await montar();

    expect(clerk.mountSignIn).toHaveBeenCalledTimes(1);
    const nodo = clerk.mountSignIn.calls.mostRecent().args[0] as HTMLElement;
    expect(nodo.tagName).toBe('DIV');
    expect(fixture.nativeElement.contains(nodo)).toBe(true);

    const raiz = fixture.nativeElement as HTMLElement;
    expect(raiz.querySelector('form')).toBeNull();
    expect(raiz.querySelector('input')).toBeNull();
  });

  it('no expone UI de registro', async () => {
    const fixture = await montar();
    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

    expect(texto.toLowerCase()).not.toContain('registr');
  });

  it('no navega mientras no hay sesión', async () => {
    await montar();

    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('tras iniciar sesión navega al alta de control', async () => {
    const fixture = await montar();

    clerk.firmarSesion();
    responderIdentidad();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/control/alta');
  });

  it('fija el destino del SignIn prebuilt al alta de control, no a `/`', async () => {
    await montar();

    const props = clerk.mountSignIn.calls.mostRecent().args[1] as
      | { forceRedirectUrl?: string }
      | undefined;

    // Sin esto, Clerk redirige por su cuenta a `/` al reconocer la sesión.
    expect(props?.forceRedirectUrl).toBe('/control/alta');
  });

  it('con una sesión ya activa aterriza en el alta y nunca en /dashboard', async () => {
    const fixture = await montar({ sesionActiva: true });

    responderIdentidad();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/control/alta');
    const destinos = router.navigateByUrl.calls.allArgs().flat();
    expect(destinos).not.toContain('/dashboard');
    expect(destinos).not.toContain('/');
  });

  it('desmonta la UI de Clerk al destruirse', async () => {
    const fixture = await montar();

    fixture.destroy();

    expect(clerk.unmountSignIn).toHaveBeenCalledTimes(1);
  });
});
