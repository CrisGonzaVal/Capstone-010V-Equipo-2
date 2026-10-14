import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { crearClerkFalso, InstanciaClerkFalsa } from '../../../testing/clerk-falso';
import { URL_API } from '../../shared/config/url-api';
import { IdentidadAutenticada } from '../../shared/interfaces';
import { tokenInterceptor } from '../interceptors/token.interceptor';
import { AutenticacionService, CARGADOR_CLERK, derivarDominioFrontendApi } from './auth.service';

/**
 * La sesión la administra Clerk, no `localStorage` ni un token local. Estos
 * tests fijan el contrato del servicio contra un doble del SDK: carga, estado
 * reactivo, token, logout y **ausencia de almacenamiento local**.
 *
 * Desde T15 el servicio también es dueño de la identidad local: pide una sola
 * vez `/auth/me` por sesión, separa el estado de identidad del de sesión,
 * limpia ante logout/cambio/error y nunca usa el perfil de Clerk como sustituto.
 */
describe('AutenticacionService', () => {
  const urlAuthMe = `${URL_API}/auth/me`;

  const IDENTIDAD: IdentidadAutenticada = {
    usuario_id: 6,
    sub: 'user_clerk_1',
    nombre: 'Camila',
    apellido: 'Fernández',
    correo: 'camila.fernandez@losalpes.cl',
    rol: 'Administrador',
    institucion: { institucion_id: 'inst-los-alpes', nombre: 'Los Alpes' },
  };

  let clerk: InstanciaClerkFalsa;
  let servicio: AutenticacionService;
  let httpMock: HttpTestingController;

  /** Espera a que la cadena asíncrona (interceptor) emita la petición. */
  const esperarPeticion = () => new Promise((resolver) => setTimeout(resolver));

  beforeEach(() => {
    clerk = crearClerkFalso();

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([tokenInterceptor])),
        provideHttpClientTesting(),
        { provide: CARGADOR_CLERK, useValue: () => Promise.resolve(clerk) },
      ],
    });

    servicio = TestBed.inject(AutenticacionService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('carga Clerk una sola vez y expone la sesión como señal reactiva', async () => {
    await servicio.inicializar();

    expect(clerk.load).toHaveBeenCalledTimes(1);

    // Sin sesión todavía: no autenticado.
    expect(servicio.estaAutenticado()).toBe(false);
    expect(servicio.usuario()).toBeNull();

    // El SDK emite un inicio de sesión y el estado reacciona.
    clerk.firmarSesion({ id: 'user_1' });
    await esperarPeticion();
    httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
    await esperarPeticion();

    expect(servicio.estaAutenticado()).toBe(true);
    expect(servicio.usuario()?.id).toBe('user_1');

    // El logout del SDK deja de reconocer la sesión (y limpia la identidad).
    clerk.emitir({ session: null, user: null });

    expect(servicio.estaAutenticado()).toBe(false);
    expect(servicio.usuario()).toBeNull();
    expect(servicio.identidad()).toBeNull();
  });

  it('es idempotente en la inicialización', async () => {
    await servicio.inicializar();
    await servicio.inicializar();

    expect(clerk.load).toHaveBeenCalledTimes(1);
  });

  it('obtiene el token vigente de la sesión de Clerk', async () => {
    await servicio.inicializar();
    clerk.firmarSesion({ id: 'user_1' }, 'jwt-de-clerk');
    await esperarPeticion();
    httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
    await esperarPeticion();

    await expectAsync(servicio.obtenerToken()).toBeResolvedTo('jwt-de-clerk');
  });

  it('no entrega token cuando no hay sesión', async () => {
    await servicio.inicializar();

    await expectAsync(servicio.obtenerToken()).toBeResolvedTo(null);
  });

  it('cerrarSesion delega en signOut del SDK y limpia el estado', async () => {
    await servicio.inicializar();
    clerk.firmarSesion();
    await esperarPeticion();
    httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
    await esperarPeticion();
    expect(servicio.estaAutenticado()).toBe(true);

    await servicio.cerrarSesion();

    expect(clerk.signOut).toHaveBeenCalled();
    expect(servicio.estaAutenticado()).toBe(false);
  });

  it('monta y desmonta la UI prebuilt de inicio de sesión', async () => {
    await servicio.inicializar();
    const contenedor = document.createElement('div');

    servicio.montarInicioSesion(contenedor);
    servicio.desmontarInicioSesion(contenedor);

    expect(clerk.mountSignIn).toHaveBeenCalledWith(contenedor);
    expect(clerk.unmountSignIn).toHaveBeenCalledWith(contenedor);
  });

  it('no lee ni escribe localStorage', async () => {
    const obtener = spyOn(Storage.prototype, 'getItem').and.callThrough();
    const guardar = spyOn(Storage.prototype, 'setItem').and.callThrough();
    const borrar = spyOn(Storage.prototype, 'removeItem').and.callThrough();

    await servicio.inicializar();
    clerk.firmarSesion();
    await esperarPeticion();
    httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
    await esperarPeticion();
    await servicio.obtenerToken();
    await servicio.cerrarSesion();

    expect(obtener).not.toHaveBeenCalled();
    expect(guardar).not.toHaveBeenCalled();
    expect(borrar).not.toHaveBeenCalled();
  });

  it('no expone una API de almacenamiento local de token (sin fallback HS256)', () => {
    const api = servicio as unknown as Record<string, unknown>;

    expect(api['guardarToken']).toBeUndefined();
    expect(api['token']).toBeUndefined();
  });

  describe('identidad local (/auth/me)', () => {
    it('al no haber sesión, la identidad es nula y no disponible', async () => {
      await servicio.inicializar();

      expect(servicio.identidad()).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('no_disponible');
      httpMock.expectNone(urlAuthMe);
    });

    it('pide /auth/me una sola vez al iniciar sesión y publica el DTO', async () => {
      await servicio.inicializar();

      clerk.firmarSesion();
      expect(servicio.estadoIdentidad()).toBe('cargando');
      await esperarPeticion();

      const peticion = httpMock.expectOne(urlAuthMe);
      // La petición va autenticada: el interceptor adjunta el Bearer de Clerk.
      expect(peticion.request.headers.get('Authorization')).toBe('Bearer token-de-prueba');
      peticion.flush(IDENTIDAD);
      await esperarPeticion();

      expect(servicio.identidad()).toEqual(IDENTIDAD);
      expect(servicio.estadoIdentidad()).toBe('disponible');

      // Idempotencia: inicializar de nuevo no repite la petición.
      await servicio.inicializar();
      httpMock.expectNone(urlAuthMe);
    });

    it('conserva la institución efectiva nula de Superadmin sin inventarla (AC-17/AC-19)', async () => {
      await servicio.inicializar();
      clerk.firmarSesion();
      await esperarPeticion();

      const superadmin: IdentidadAutenticada = {
        ...IDENTIDAD,
        rol: 'Superadmin',
        institucion: null,
      };
      httpMock.expectOne(urlAuthMe).flush(superadmin);
      await esperarPeticion();

      // El DTO viaja tal cual: ni el servicio ni la vista derivan una institución
      // que el servidor declaró ausente.
      expect(servicio.identidad()).toEqual(superadmin);
      expect(servicio.identidad()?.institucion).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('disponible');
    });

    it('no repite la petición cuando Clerk reemite la misma sesión (navegación)', async () => {
      await servicio.inicializar();

      const sesionEstable = { getToken: () => Promise.resolve('token-de-prueba') };
      const usuarioEstable = { id: 'user_1' };
      clerk.emitir({ session: sesionEstable, user: usuarioEstable });
      await esperarPeticion();
      httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
      await esperarPeticion();

      // Clerk reemite el mismo estado (actualización de usuario / navegación).
      clerk.emitir({ session: sesionEstable, user: usuarioEstable });
      await esperarPeticion();

      httpMock.expectNone(urlAuthMe);
      expect(servicio.identidad()).toEqual(IDENTIDAD);
    });

    it('limpia la identidad de inmediato al cerrar sesión', async () => {
      await servicio.inicializar();
      clerk.firmarSesion();
      await esperarPeticion();
      httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
      await esperarPeticion();
      expect(servicio.identidad()).toEqual(IDENTIDAD);

      await servicio.cerrarSesion();

      expect(servicio.identidad()).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('no_disponible');
    });

    it('limpia y recarga al cambiar de sesión, sin reutilizar identidad previa', async () => {
      await servicio.inicializar();
      clerk.firmarSesion({ id: 'user_1' });
      await esperarPeticion();
      httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);
      await esperarPeticion();

      clerk.firmarSesion({ id: 'user_2' });

      // Limpieza inmediata y nueva carga antes de recibir la respuesta.
      expect(servicio.identidad()).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('cargando');

      await esperarPeticion();
      const segunda: IdentidadAutenticada = { ...IDENTIDAD, usuario_id: 9, sub: 'user_2' };
      httpMock.expectOne(urlAuthMe).flush(segunda);
      await esperarPeticion();

      expect(servicio.identidad()).toEqual(segunda);
      expect(servicio.estadoIdentidad()).toBe('disponible');
    });

    it('una respuesta tardía tras el logout no restaura la identidad anterior', async () => {
      await servicio.inicializar();
      clerk.firmarSesion();
      await esperarPeticion();
      const peticionTardia = httpMock.expectOne(urlAuthMe);

      await servicio.cerrarSesion();
      expect(servicio.identidad()).toBeNull();

      // La respuesta llega después del logout: debe descartarse.
      peticionTardia.flush(IDENTIDAD);
      await esperarPeticion();

      expect(servicio.identidad()).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('no_disponible');
    });

    it('ante error/401 deja identidad nula y estado no disponible sin usar el perfil Clerk', async () => {
      await servicio.inicializar();
      clerk.firmarSesion({
        id: 'user_1',
        fullName: 'Perfil de Clerk',
        primaryEmailAddress: { emailAddress: 'clerk@ejemplo.cl' },
      });
      await esperarPeticion();

      httpMock
        .expectOne(urlAuthMe)
        .flush({ detail: 'No autenticado' }, { status: 401, statusText: 'Unauthorized' });
      await esperarPeticion();

      // La sesión Clerk sigue reconocida por el SDK, pero la identidad es nula:
      // el estado de sesión y el de identidad son independientes.
      expect(servicio.estaAutenticado()).toBe(true);
      expect(servicio.identidad()).toBeNull();
      expect(servicio.estadoIdentidad()).toBe('no_disponible');
    });

    it('esperarIdentidad resuelve con la identidad vinculada sin repetir /auth/me', async () => {
      await servicio.inicializar();
      clerk.firmarSesion();
      await esperarPeticion();

      // Mientras la identidad carga, la espera no resuelve todavía.
      const espera = servicio.esperarIdentidad();
      await esperarPeticion();
      httpMock.expectOne(urlAuthMe).flush(IDENTIDAD);

      await expectAsync(espera).toBeResolvedTo(IDENTIDAD);
      // La espera reutiliza la carga en curso: no dispara una segunda petición.
      httpMock.expectNone(urlAuthMe);
    });

    it('esperarIdentidad devuelve null cuando no hay sesión', async () => {
      await servicio.inicializar();

      await expectAsync(servicio.esperarIdentidad()).toBeResolvedTo(null);
      httpMock.expectNone(urlAuthMe);
    });

    it('esperarIdentidad devuelve null si la identidad no está disponible', async () => {
      await servicio.inicializar();
      clerk.firmarSesion();
      await esperarPeticion();

      const espera = servicio.esperarIdentidad();
      httpMock
        .expectOne(urlAuthMe)
        .flush({ detail: 'No autenticado' }, { status: 401, statusText: 'Unauthorized' });

      await expectAsync(espera).toBeResolvedTo(null);
    });
  });
});

/**
 * `@clerk/clerk-js` v6 no incluye la UI prebuilt: el bundle `@clerk/ui` se carga
 * desde el CDN del Frontend API. Ubicarlo exige derivar ese dominio desde la
 * publishable key; aquí se fija esa derivación sin salir a la red.
 */
describe('derivarDominioFrontendApi', () => {
  it('deriva el dominio del Frontend API desde la publishable key', () => {
    expect(
      derivarDominioFrontendApi(
        'pk_test_cmVsZXZhbnQtdGVybWl0ZS04MDg5LmNsZXJrLmFjY291bnRzLmRldiQ',
      ),
    ).toBe('relevant-termite-8089.clerk.accounts.dev');
  });
});
