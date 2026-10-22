import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { URL_API } from '../../../shared/config/url-api';
import { DashboardAnalitico } from '../../../shared/interfaces';
import { DashboardService } from './dashboard.service';

/**
 * Feature 009 (T8): contrato HTTP del `DashboardService`.
 *
 * La vista no decide ámbito ni autorización: el servicio hace **una sola**
 * petición `GET /api/v1/dashboard/` sin parámetros, sin cabeceras de ámbito y
 * sin cuerpo (D-3), y transmite la respuesta consolidada íntegra, con atribución
 * institucional por fila y `actividad_disponible`. No reutiliza ni invoca el
 * historial de movimientos.
 */
describe('DashboardService', () => {
  const urlDashboard = `${URL_API}/dashboard/`;

  /** Respuesta consolidada de ejemplo, con dos instituciones atribuidas. */
  const RESPUESTA: DashboardAnalitico = {
    kpi: {
      unidades_en_stock: 33,
      tickets_activos: 5,
      total_departamentos: 5,
      total_alertas: 4,
    },
    alertas: [
      {
        sede_id: 11,
        sede_nombre: 'Sede Central',
        producto_id: 101,
        producto_nombre: 'Papel Bond',
        stock_actual: 9,
        stock_minimo: 10,
        institucion_id: 'INSTA',
        institucion_nombre: 'Instituto Alfa',
      },
      {
        sede_id: 12,
        sede_nombre: 'Sede Norte',
        producto_id: 202,
        producto_nombre: 'Papel Bond',
        stock_actual: 3,
        stock_minimo: 10,
        institucion_id: 'INSTB',
        institucion_nombre: 'Instituto Beta',
      },
    ],
    actividad_disponible: true,
    actividad_movimientos: [
      {
        movimiento_id: 501,
        tipo_movimiento: 'ENTRADA',
        cantidad: 5,
        fecha_movimiento: '2026-04-01T08:00:00',
        producto_id: 101,
        producto_nombre: 'Papel Bond',
        sede_id: 11,
        sede_nombre: 'Sede Central',
        departamento_id: null,
        departamento_nombre: null,
        ubicacion: null,
        institucion_id: 'INSTA',
        institucion_nombre: 'Instituto Alfa',
      },
      {
        movimiento_id: 502,
        tipo_movimiento: 'SALIDA',
        cantidad: 2,
        fecha_movimiento: '2026-04-01T07:30:00',
        producto_id: 202,
        producto_nombre: 'Papel Bond',
        sede_id: null,
        sede_nombre: null,
        departamento_id: 22,
        departamento_nombre: 'Operaciones',
        ubicacion: 'Operaciones (INSTB)',
        institucion_id: 'INSTB',
        institucion_nombre: 'Instituto Beta',
      },
    ],
  };

  let servicio: DashboardService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    servicio = TestBed.inject(DashboardService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('hace una sola petición GET a /dashboard/ sin params, sin cabeceras de ámbito ni cuerpo', () => {
    const recibidos: DashboardAnalitico[] = [];
    servicio.obtenerDashboard().subscribe((respuesta) => recibidos.push(respuesta));

    const peticion = httpMock.expectOne((req) => req.url === urlDashboard);

    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.keys()).toEqual([]);
    expect(peticion.request.body).toBeNull();

    const cabeceras = peticion.request.headers
      .keys()
      .map((nombre) => nombre.toLowerCase());
    expect(cabeceras.some((nombre) => nombre.includes('institucion'))).toBe(false);

    peticion.flush(RESPUESTA);

    expect(recibidos).toEqual([RESPUESTA]);
    // Cero peticiones extra de la operación.
    httpMock.expectNone(urlDashboard);
  });

  it('transmite íntegra la respuesta consolidada con atribución por fila y actividad_disponible', () => {
    const recibidos: DashboardAnalitico[] = [];
    servicio.obtenerDashboard().subscribe((respuesta) => recibidos.push(respuesta));

    httpMock.expectOne(urlDashboard).flush(RESPUESTA);

    expect(recibidos).toEqual([RESPUESTA]);
    expect(recibidos[0].kpi.total_alertas).toBe(4);
    expect(recibidos[0].alertas.map((a) => a.sede_id)).toEqual([11, 12]);
    expect(recibidos[0].alertas[0].sede_nombre).toBe('Sede Central');
    expect(recibidos[0].alertas[0].institucion_nombre).toBe('Instituto Alfa');
    expect(recibidos[0].actividad_disponible).toBe(true);
    // Movimiento nuevo: sede poblada y bloque de departamento nulo.
    expect(recibidos[0].actividad_movimientos[0].sede_nombre).toBe('Sede Central');
    expect(recibidos[0].actividad_movimientos[0].departamento_nombre).toBeNull();
    // Movimiento legado: departamento/ubicacion poblados y sede nula.
    expect(recibidos[0].actividad_movimientos[1].institucion_nombre).toBe(
      'Instituto Beta',
    );
    expect(recibidos[0].actividad_movimientos[1].sede_nombre).toBeNull();
    expect(recibidos[0].actividad_movimientos[1].ubicacion).toBe(
      'Operaciones (INSTB)',
    );
  });

  it('no consulta el historial de movimientos ni ningún otro endpoint', () => {
    servicio.obtenerDashboard().subscribe();

    httpMock.expectOne(urlDashboard).flush(RESPUESTA);

    httpMock.expectNone(`${URL_API}/inventario/movimientos`);
    httpMock.expectNone(`${URL_API}/inventario/stock`);
    httpMock.expectNone(`${URL_API}/tickets/`);
  });

  it('acepta la actividad no disponible del Solicitante (lista vacía) sin alterarla', () => {
    const deSolicitante: DashboardAnalitico = {
      ...RESPUESTA,
      actividad_disponible: false,
      actividad_movimientos: [],
    };

    const recibidos: DashboardAnalitico[] = [];
    servicio.obtenerDashboard().subscribe((respuesta) => recibidos.push(respuesta));

    httpMock.expectOne(urlDashboard).flush(deSolicitante);

    expect(recibidos).toEqual([deSolicitante]);
    expect(recibidos[0].actividad_disponible).toBe(false);
    expect(recibidos[0].actividad_movimientos).toEqual([]);
  });
});
