import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AutenticacionService } from '../services/auth.service';
import { tokenInterceptor } from './token.interceptor';

/**
 * El interceptor no guarda token propio: pide el vigente a Clerk y solo entonces
 * lo adjunta como `Authorization: Bearer`. Sin sesión, la petición pasa intacta.
 */
describe('tokenInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  const obtenerToken = jasmine.createSpy('obtenerToken');

  beforeEach(() => {
    obtenerToken.calls.reset();
    obtenerToken.and.resolveTo(null);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([tokenInterceptor])),
        provideHttpClientTesting(),
        { provide: AutenticacionService, useValue: { obtenerToken } },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  /** Espera a que la cadena asíncrona del interceptor emita la petición. */
  const esperarPeticion = () => new Promise((resolve) => setTimeout(resolve));

  it('adjunta el token de Clerk como Bearer', async () => {
    obtenerToken.and.resolveTo('jwt-de-clerk');

    http.get('/api/v1/auth/me').subscribe();
    await esperarPeticion();
    const peticion = httpMock.expectOne('/api/v1/auth/me');

    expect(peticion.request.headers.get('Authorization')).toBe('Bearer jwt-de-clerk');
    peticion.flush({});
  });

  it('no adjunta Authorization cuando no hay sesión', async () => {
    obtenerToken.and.resolveTo(null);

    http.get('/api/v1/auth/me').subscribe();
    await esperarPeticion();
    const peticion = httpMock.expectOne('/api/v1/auth/me');

    expect(peticion.request.headers.has('Authorization')).toBe(false);
    peticion.flush({});
  });

  it('pide el token a Clerk y no a localStorage', async () => {
    const leer = spyOn(Storage.prototype, 'getItem').and.callThrough();
    obtenerToken.and.resolveTo('jwt-de-clerk');

    http.get('/api/v1/auth/me').subscribe();
    await esperarPeticion();
    httpMock.expectOne('/api/v1/auth/me').flush({});

    expect(obtenerToken).toHaveBeenCalled();
    expect(leer).not.toHaveBeenCalled();
  });
});
