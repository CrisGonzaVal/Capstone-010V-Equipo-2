import { WritableSignal, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { AppComponent } from './app.component';
import { routes } from './app.routes';
import { AutenticacionService, EstadoIdentidad } from './core/services/auth.service';
import { IdentidadAutenticada, InstitucionEfectiva } from './shared/interfaces';

/**
 * Institución efectiva de la identidad limitada (Feature 008, AC-17). Procede de
 * `GET /auth/me` y la vista solo la presenta como contexto.
 */
const INSTITUCION: InstitucionEfectiva = {
  institucion_id: 'inst-los-alpes',
  nombre: 'Los Alpes',
};

/**
 * Identidad local de prueba (`/auth/me`), equivalente a la usuaria real de la
 * semilla: debe presentarse como "Camila Fernandez",
 * "camila.fernandez@losalpes.cl" y rol legible "Administrador".
 */
const IDENTIDAD_RESUELTA: IdentidadAutenticada = {
  usuario_id: 1,
  sub: 'user_de_prueba',
  nombre: 'Camila',
  apellido: 'Fernandez',
  correo: 'camila.fernandez@losalpes.cl',
  rol: 'Administrador',
  institucion: INSTITUCION,
};

/** Valores ficticios que el layout antiguo mostraba quemados (AC-16 / D-14). */
const DATOS_FICTICIOS = [
  'Super Administrator',
  'admin@compustock.cl',
  'Superadmin',
];

describe('AppComponent', () => {
  let autenticacionFalsa: {
    cerrarSesion: jasmine.Spy;
    estaAutenticado: WritableSignal<boolean>;
    identidad: WritableSignal<IdentidadAutenticada | null>;
    estadoIdentidad: WritableSignal<EstadoIdentidad>;
  };

  beforeEach(async () => {
    autenticacionFalsa = {
      cerrarSesion: jasmine.createSpy('cerrarSesion').and.resolveTo(undefined),
      estaAutenticado: signal(true),
      identidad: signal<IdentidadAutenticada | null>(IDENTIDAD_RESUELTA),
      estadoIdentidad: signal<EstadoIdentidad>('disponible'),
    };

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      // `AppComponent` usa `routerLink`/`router-outlet`, asi que sin el router
      //-provider los enlaces no se pueden resolver y el fixture falla al crear.
      providers: [
        provideRouter(routes),
        // La shell no guarda token local: consume la sesion/identidad de Clerk
        // como señales. En la prueba se sustituyen por señales dobles.
        { provide: AutenticacionService, useValue: autenticacionFalsa },
      ],
    }).compileComponents();
  });

  function crearYRenderizar(): HTMLElement {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('debe exponer el titulo del sistema', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance.titulo).toEqual('CompuStock ERP');
  });

  it('debe renderizar el encabezado principal', () => {
    const compilado = crearYRenderizar();
    expect(compilado.querySelector('h1')?.textContent).toContain('Sistema ERP');
  });

  it('debe alternar el menu lateral', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;

    expect(app.sidebarAbierto()).toBeTrue();
    app.alternarSidebar();
    expect(app.sidebarAbierto()).toBeFalse();
    app.alternarSidebar();
    expect(app.sidebarAbierto()).toBeTrue();
  });

  it('cerrar sesion vuelve al login', async () => {
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate');
    const fixture = TestBed.createComponent(AppComponent);

    fixture.componentInstance.cerrarSesion();
    await fixture.whenStable();

    expect(autenticacionFalsa.cerrarSesion).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  describe('identidad local en el layout (AC-16)', () => {
    it('presenta nombre completo, correo local y rol legible sin datos ficticios', () => {
      const compilado = crearYRenderizar();
      const texto = compilado.textContent ?? '';

      expect(texto).toContain('Camila Fernandez');
      expect(texto).toContain('camila.fernandez@losalpes.cl');
      expect(texto).toContain('Administrador');

      for (const ficticio of DATOS_FICTICIOS) {
        expect(texto).not.toContain(ficticio);
      }
    });

    it('deriva el nombre completo y el rol de la identidad resuelta', () => {
      const fixture = TestBed.createComponent(AppComponent);
      const app = fixture.componentInstance;

      expect(app.nombreCompleto()).toEqual('Camila Fernandez');
      expect(app.correoLocal()).toEqual('camila.fernandez@losalpes.cl');
      expect(app.rolLegible()).toEqual('Administrador');
    });

    it('muestra en el avatar la inicial del nombre normalizada a mayúscula', () => {
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const app = fixture.componentInstance;

      expect(app.inicialNombre()).toEqual('C');

      // El avatar recibe la inicial, no una letra fija.
      const avatar = fixture.nativeElement.querySelector(
        '.w-10.h-10.rounded-full',
      ) as HTMLElement | null;
      expect(avatar?.textContent?.trim()).toEqual('C');
    });

    it('normaliza a mayúscula un nombre en minúscula', () => {
      autenticacionFalsa.identidad.set({
        ...IDENTIDAD_RESUELTA,
        nombre: 'camila',
      });
      const fixture = TestBed.createComponent(AppComponent);

      expect(fixture.componentInstance.inicialNombre()).toEqual('C');
    });

    it('mientras carga la identidad muestra un marcador neutro sin parecer usuario', () => {
      autenticacionFalsa.identidad.set(null);
      autenticacionFalsa.estadoIdentidad.set('cargando');
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

      expect(texto).toContain('Cargando identidad');
      expect(fixture.componentInstance.inicialNombre()).toBeNull();
      expect(fixture.componentInstance.nombreCompleto()).toBeNull();
      expect(fixture.componentInstance.rolLegible()).toBeNull();

      for (const ficticio of DATOS_FICTICIOS) {
        expect(texto).not.toContain(ficticio);
      }
    });

    it('ante error o identidad no disponible muestra un marcador neutro', () => {
      autenticacionFalsa.identidad.set(null);
      autenticacionFalsa.estadoIdentidad.set('no_disponible');
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

      expect(texto).toContain('Identidad no disponible');
      expect(fixture.componentInstance.inicialNombre()).toBeNull();
      expect(fixture.componentInstance.rolLegible()).toBeNull();

      for (const ficticio of DATOS_FICTICIOS) {
        expect(texto).not.toContain(ficticio);
      }
    });

    it('sin sesion no muestra el marco de la app ni identidad ficticia', () => {
      autenticacionFalsa.estaAutenticado.set(false);
      autenticacionFalsa.identidad.set(null);
      autenticacionFalsa.estadoIdentidad.set('no_disponible');
      const compilado = crearYRenderizar();

      expect(compilado.querySelector('aside')).toBeNull();

      for (const ficticio of DATOS_FICTICIOS) {
        expect(compilado.textContent ?? '').not.toContain(ficticio);
      }
    });
  });

  /**
   * AC-3: el Solicitante no recibe el acceso administrativo en la navegación.
   * Es comodidad de interfaz; la ruta sigue protegida por el guard de rol.
   */
  describe('navegación por rol (AC-3)', () => {
    function destinos(compilado: HTMLElement): string[] {
      return Array.from(compilado.querySelectorAll('a')).map(
        (enlace) => enlace.getAttribute('href') ?? '',
      );
    }

    it('oculta el enlace de administración al Solicitante', () => {
      autenticacionFalsa.identidad.set({ ...IDENTIDAD_RESUELTA, rol: 'Solicitante' });
      const compilado = crearYRenderizar();

      expect(destinos(compilado)).not.toContain('/administracion');
      // Las demás secciones permitidas siguen visibles.
      expect(destinos(compilado)).toContain('/dashboard');
      expect(destinos(compilado)).toContain('/inventario');
      expect(destinos(compilado)).toContain('/tickets');
    });

    it('mantiene el enlace de administración solo al Administrador', () => {
      autenticacionFalsa.identidad.set({
        ...IDENTIDAD_RESUELTA,
        rol: 'Administrador',
      });
      expect(destinos(crearYRenderizar())).toContain('/administracion');

      // Feature 017 (AC-15): la API tenant de administración niega al
      // Superadmin, así que su navegación no ofrece una pantalla muerta.
      autenticacionFalsa.identidad.set({
        ...IDENTIDAD_RESUELTA,
        rol: 'Superadmin',
        institucion: null,
      });
      expect(destinos(crearYRenderizar())).not.toContain('/administracion');
    });

    /**
     * Feature 012, AC-3 y Feature 017, AC-15: el Superadmin solo conserva
     * `/control` como superficie. Dashboard, inventario, tickets y
     * administración se retiran de la navegación; las rutas siguen protegidas
     * por el guard de rol.
     */
    it('deja al Superadmin únicamente /control en la navegación', () => {
      autenticacionFalsa.identidad.set({
        ...IDENTIDAD_RESUELTA,
        rol: 'Superadmin',
        institucion: null,
      });
      const compilado = crearYRenderizar();

      for (const retirada of ['/dashboard', '/inventario', '/tickets', '/administracion']) {
        expect(destinos(compilado)).withContext(retirada).not.toContain(retirada);
      }
      expect(destinos(compilado)).toContain('/control');
    });

    it('mantiene el enlace de tickets a los roles de negocio', () => {
      for (const rol of ['Administrador', 'Bodeguero', 'Solicitante']) {
        autenticacionFalsa.identidad.set({ ...IDENTIDAD_RESUELTA, rol });
        const compilado = crearYRenderizar();

        expect(destinos(compilado)).withContext(rol).toContain('/tickets');
      }
    });
  });

  /**
   * AC-17 / AC-19: el contexto institucional mostrado es el de `/auth/me`. Para
   * roles limitados es el nombre de su institución efectiva; para Superadmin,
   * cuyo `institucion` es `null`, es un contexto global explícito. La vista no
   * ofrece ningún selector ni trata el contexto como seguridad.
   */
  describe('contexto institucional (AC-17, AC-19)', () => {
    it('muestra el nombre de la institución efectiva del rol limitado', () => {
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

      expect(fixture.componentInstance.contextoInstitucional()).toEqual('Los Alpes');
      expect(texto).toContain('Los Alpes');
    });

    it('para Superadmin muestra un contexto global explícito, no vacío', () => {
      autenticacionFalsa.identidad.set({
        ...IDENTIDAD_RESUELTA,
        rol: 'Superadmin',
        institucion: null,
      });
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();
      const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';

      expect(fixture.componentInstance.contextoInstitucional()).toEqual(
        'Todas las instituciones',
      );
      expect(texto).toContain('Todas las instituciones');
      // El nombre de una institución concreta no se usa para Superadmin.
      expect(texto).not.toContain('Los Alpes');
    });

    it('un rol limitado sin institución resuelta no muestra un contexto global', () => {
      autenticacionFalsa.identidad.set({ ...IDENTIDAD_RESUELTA, institucion: null });
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();

      // Solo Superadmin declara el contexto global; una institución ausente en
      // un rol limitado es una ausencia, no un ámbito global (AC-17).
      expect(fixture.componentInstance.contextoInstitucional()).toBeNull();
      expect((fixture.nativeElement as HTMLElement).textContent ?? '').not.toContain(
        'Todas las instituciones',
      );
    });

    it('mientras la identidad carga no muestra contexto institucional', () => {
      autenticacionFalsa.identidad.set(null);
      autenticacionFalsa.estadoIdentidad.set('cargando');
      const fixture = TestBed.createComponent(AppComponent);
      fixture.detectChanges();

      expect(fixture.componentInstance.contextoInstitucional()).toBeNull();
      expect((fixture.nativeElement as HTMLElement).textContent ?? '').not.toContain(
        'Los Alpes',
      );
    });

    it('no expone un selector ni una entrada de ámbito institucional', () => {
      const compilado = crearYRenderizar();

      expect(compilado.querySelector('select')).toBeNull();
      expect(compilado.querySelector('input')).toBeNull();
    });
  });
});
