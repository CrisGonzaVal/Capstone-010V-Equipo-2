import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { URL_API } from '../../../shared/config/url-api';
import {
  CapacidadRespuesta,
  DashboardSaaS,
  InstitucionControl,
  InstitucionEstadoRespuesta,
} from '../../../shared/interfaces';
import { ControlService } from './control.service';

/**
 * Feature 012 (T9): contrato HTTP del `ControlService` de gestión SaaS.
 *
 * Seam bajo prueba: la interfaz pública del servicio contra
 * `HttpTestingController`. Se verifica método, ruta contractual y cuerpo de cada
 * una de las siete operaciones de control, sin parámetros ni cabeceras de ámbito
 * (el ámbito lo resuelve el servidor). El `Bearer` de Clerk lo añade el
 * interceptor existente, con su propia suite.
 */
describe('ControlService (gestión SaaS)', () => {
  const raiz = `${URL_API}/control`;

  const INSTITUCION: InstitucionControl = {
    institucion_id: 'INSTA',
    nombre: 'Instituto Alfa',
    rut: '76.111.222-3',
    direccion: 'Av. Siempre Viva 742',
    activo: true,
    nombre_esquema: 'tenant_insta_ab12cd34',
  };

  let servicio: ControlService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    servicio = TestBed.inject(ControlService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('lista instituciones con GET /control/instituciones/', () => {
    const recibidos: InstitucionControl[][] = [];
    servicio.listarInstituciones().subscribe((r) => recibidos.push(r));

    const peticion = httpMock.expectOne(`${raiz}/instituciones/`);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.keys()).toEqual([]);

    peticion.flush([INSTITUCION]);
    expect(recibidos[0]).toEqual([INSTITUCION]);
  });

  it('obtiene una institución con GET /control/instituciones/{id}', () => {
    servicio.obtenerInstitucion('INSTA').subscribe();

    const peticion = httpMock.expectOne(`${raiz}/instituciones/INSTA`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush(INSTITUCION);
  });

  it('edita una institución con PUT y solo los atributos canónicos', () => {
    servicio
      .editarInstitucion('INSTA', { nombre: 'Alfa 2', rut: null, direccion: 'Calle 1' })
      .subscribe();

    const peticion = httpMock.expectOne(`${raiz}/instituciones/INSTA`);
    expect(peticion.request.method).toBe('PUT');
    expect(Object.keys(peticion.request.body as object).sort()).toEqual(
      ['nombre', 'rut', 'direccion'].sort(),
    );
    expect(peticion.request.body).toEqual({
      nombre: 'Alfa 2',
      rut: null,
      direccion: 'Calle 1',
    });
    peticion.flush({ ...INSTITUCION, nombre: 'Alfa 2' });
  });

  it('cambia el estado con PATCH .../estado y cuerpo { activo }', () => {
    const recibidos: InstitucionEstadoRespuesta[] = [];
    servicio.cambiarEstadoInstitucion('INSTA', false).subscribe((r) => recibidos.push(r));

    const peticion = httpMock.expectOne(`${raiz}/instituciones/INSTA/estado`);
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });

    peticion.flush({ institucion_id: 'INSTA', activo: false });
    expect(recibidos[0]).toEqual({ institucion_id: 'INSTA', activo: false });
  });

  it('consulta el dashboard SaaS con GET /control/dashboard', () => {
    const respuesta: DashboardSaaS = {
      total_instituciones_activas: 1,
      instituciones: [
        {
          institucion_id: 'INSTA',
          nombre: 'Instituto Alfa',
          activo: true,
          sedes: 2,
          usuarios_por_rol: { Administrador: 1, Solicitante: 3 },
        },
        {
          institucion_id: 'INSTB',
          nombre: 'Instituto Beta',
          activo: false,
          sedes: null,
          usuarios_por_rol: null,
        },
      ],
    };

    const recibidos: DashboardSaaS[] = [];
    servicio.obtenerDashboardSaaS().subscribe((r) => recibidos.push(r));

    const peticion = httpMock.expectOne(`${raiz}/dashboard`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush(respuesta);

    expect(recibidos[0]).toEqual(respuesta);
    expect(recibidos[0].instituciones[1].sedes).toBeNull();
  });

  it('lista las seis capacidades con GET .../capacidades', () => {
    servicio.listarCapacidades('INSTA').subscribe();

    const peticion = httpMock.expectOne(`${raiz}/instituciones/INSTA/capacidades`);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([]);
  });

  it('actualiza una capacidad con PUT .../capacidades/{funcion} y cuerpo { habilitada }', () => {
    const recibidos: CapacidadRespuesta[] = [];
    servicio
      .actualizarCapacidad('INSTA', 'kanban', false)
      .subscribe((r) => recibidos.push(r));

    const peticion = httpMock.expectOne(
      `${raiz}/instituciones/INSTA/capacidades/kanban`,
    );
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ habilitada: false });

    peticion.flush({ funcion: 'kanban', habilitada: false });
    expect(recibidos[0]).toEqual({ funcion: 'kanban', habilitada: false });
  });
});
