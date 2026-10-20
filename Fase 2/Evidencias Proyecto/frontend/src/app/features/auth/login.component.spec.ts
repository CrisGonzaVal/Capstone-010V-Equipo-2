import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { crearClerkFalso, InstanciaClerkFalsa } from '../../../testing/clerk-falso';
import { CARGADOR_CLERK } from '../../core/services/auth.service';
import { LoginComponent, resolverDestinoRetorno } from './login.component';

describe('LoginComponent', () => {
  let clerk: InstanciaClerkFalsa;
  let router: jasmine.SpyObj<Router>;
  let httpMock: HttpTestingController;

  async function montar(retorno: string | null = null): Promise<ComponentFixture<LoginComponent>> {
    clerk = crearClerkFalso();
    router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);
    router.navigateByUrl.and.resolveTo(true);

    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: CARGADOR_CLERK, useValue: () => Promise.resolve(clerk) },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap(retorno === null ? {} : { retorno }),
            },
          },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture;
  }

  /**
   * Al firmar sesión el servicio real pide `/auth/me`. Aquí no se prueba esa
   * carga (T15 la cubre en su propio spec), así que se responde lo mínimo para
   * no dejar la petición colgada mientras se verifica la navegación.
   */
  function responderIdentidad(): void {
    httpMock.match(() => true).forEach((peticion) => peticion.flush({}));
  }

  /** Responde `/auth/me` con la identidad local de un rol concreto. */
  function responderIdentidadComo(rol: string): void {
    httpMock.match(() => true).forEach((peticion) =>
      peticion.flush({
        usuario_id: 1,
        sub: 'user_prueba',
        nombre: 'Sonda',
        apellido: 'Rol',
        correo: 'sonda@example.com',
        rol,
        institucion: null,
      }),
    );
  }

  it('monta la UI prebuilt de inicio de sesión de Clerk', async () => {
    const fixture = await montar();

    expect(clerk.mountSignIn).toHaveBeenCalledTimes(1);
    const nodo = clerk.mountSignIn.calls.mostRecent().args[0] as HTMLElement;
    expect(nodo.tagName).toBe('DIV');
    expect(fixture.nativeElement.contains(nodo)).toBe(true);
  });

  it('no expone UI de registro', async () => {
    const fixture = await montar();
    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

    expect(texto.toLowerCase()).not.toContain('registr');
    expect((fixture.nativeElement as HTMLElement).querySelector('a[href*="sign-up"]')).toBeNull();
  });

  it('presenta la caja de credenciales de Clerk sin tarjeta exterior propia', async () => {
    const fixture = await montar();
    const raiz = fixture.nativeElement as HTMLElement;

    // La UI de Clerk vive en su propio contenedor, que cuelga del bloque
    // centrado: no debe mediar una tarjeta del sistema envolviéndola.
    const nodo = clerk.mountSignIn.calls.mostRecent().args[0] as HTMLElement;
    const padre = nodo.parentElement as HTMLElement;
    expect(padre.classList.contains('max-w-md')).toBe(true);

    // No queda ninguna tarjeta contenedora propia del sistema (rounded-2xl + shadow-xl).
    expect(raiz.querySelectorAll('.rounded-2xl.shadow-xl').length).toBe(0);
  });

  it('conserva la cabecera de marca sobre el login', async () => {
    const fixture = await montar();
    const raiz = fixture.nativeElement as HTMLElement;

    const titulo = raiz.querySelector('h1');
    expect(titulo?.textContent).toContain('CompuStock ERP');
    expect((raiz.textContent ?? '').toLowerCase()).toContain('inicia sesión');
  });

  it('no navega mientras no hay sesión', async () => {
    await montar('/tickets');

    expect(router.navigateByUrl).not.toHaveBeenCalled();
  });

  it('tras iniciar sesión vuelve a la ruta local solicitada', async () => {
    const fixture = await montar('/tickets');

    clerk.firmarSesion();
    responderIdentidad();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/tickets');
  });

  it('sin ruta de retorno va a /dashboard', async () => {
    const fixture = await montar(null);

    clerk.firmarSesion();
    responderIdentidad();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
  });

  it('un retorno no local no se sigue: va a /dashboard', async () => {
    const fixture = await montar('//malicioso.example');

    clerk.firmarSesion();
    responderIdentidad();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
  });

  it('un Superadmin sin ruta de retorno aterriza en /control (AC-18)', async () => {
    const fixture = await montar(null);

    clerk.firmarSesion();
    responderIdentidadComo('Superadmin');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/control');
    expect(router.navigateByUrl).not.toHaveBeenCalledWith('/dashboard');
  });

  it('un retorno local válido sigue prevaleciendo para Superadmin', async () => {
    const fixture = await montar('/control/instituciones');

    clerk.firmarSesion();
    responderIdentidadComo('Superadmin');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/control/instituciones');
    expect(router.navigateByUrl).not.toHaveBeenCalledWith('/control');
  });

  it('los roles de negocio sin retorno siguen yendo a /dashboard', async () => {
    const fixture = await montar(null);

    clerk.firmarSesion();
    responderIdentidadComo('Administrador');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(router.navigateByUrl).toHaveBeenCalledWith('/dashboard');
  });

  it('desmonta la UI de Clerk al destruirse', async () => {
    const fixture = await montar();

    fixture.destroy();

    expect(clerk.unmountSignIn).toHaveBeenCalledTimes(1);
  });

  describe('resolverDestinoRetorno', () => {
    it('acepta rutas locales', () => {
      expect(resolverDestinoRetorno('/tickets')).toBe('/tickets');
      expect(resolverDestinoRetorno('/inventario?x=1')).toBe('/inventario?x=1');
    });

    it('rechaza vacío, externo y la propia ruta de login', () => {
      expect(resolverDestinoRetorno(null)).toBe('/dashboard');
      expect(resolverDestinoRetorno('')).toBe('/dashboard');
      expect(resolverDestinoRetorno('https://evil.example')).toBe('/dashboard');
      expect(resolverDestinoRetorno('//evil.example')).toBe('/dashboard');
      expect(resolverDestinoRetorno('/login')).toBe('/dashboard');
    });

    it('sin retorno, el Superadmin va a /control y el resto a /dashboard', () => {
      expect(resolverDestinoRetorno(null, 'Superadmin')).toBe('/control');
      expect(resolverDestinoRetorno('', 'Superadmin')).toBe('/control');
      expect(resolverDestinoRetorno(null, 'Administrador')).toBe('/dashboard');
      expect(resolverDestinoRetorno(null, 'Bodeguero')).toBe('/dashboard');
      expect(resolverDestinoRetorno(null, 'Solicitante')).toBe('/dashboard');
      expect(resolverDestinoRetorno(null, null)).toBe('/dashboard');
    });

    it('una ruta local válida prevalece sobre el fallback de rol', () => {
      expect(resolverDestinoRetorno('/control/instituciones', 'Superadmin')).toBe(
        '/control/instituciones',
      );
      expect(resolverDestinoRetorno('/tickets', 'Administrador')).toBe('/tickets');
    });
  });
});
