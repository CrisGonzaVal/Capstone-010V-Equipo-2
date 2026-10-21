import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { URL_API } from '../../../shared/config/url-api';
import { AmbitoInventario } from '../../../shared/interfaces';
import { InventarioService } from './inventario.service';

const AMBITO: AmbitoInventario = {
  sedes: [
    { sede_id: 1, sede_nombre: 'Sede Central' },
    { sede_id: 3, sede_nombre: 'Sede Norte' },
  ],
  departamentos: [
    { departamento_id: 10, departamento_nombre: 'Operaciones', sede_id: 1 },
    { departamento_id: 12, departamento_nombre: 'Logística', sede_id: 3 },
  ],
};

/**
 * Feature 018 (T6/T7): contrato HTTP de la lectura de ámbito y de los filtros
 * organizacionales de existencias.
 *
 * T6 dejó estas pruebas en rojo con acceso dinámico porque la superficie no
 * existía; T7 las convierte en llamadas directas sobre los tipos y métodos
 * publicados.
 */
describe('InventarioService — ámbito y filtros (Feature 018)', () => {
  const RUTA_AMBITO = `${URL_API}/inventario/ambito`;
  const RUTA_EXISTENCIAS = `${URL_API}/inventario/existencias`;

  /**
   * `expectOne(string)` compara la URL completa **con** query, así que no sirve
   * para probar parámetros opcionales: se selecciona por ruta y los `params` se
   * afirman aparte.
   */
  function peticionExistencias(): TestRequest {
    return httpMock.expectOne(
      (peticion) => peticion.url === RUTA_EXISTENCIAS,
    );
  }

  let servicio: InventarioService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    servicio = TestBed.inject(InventarioService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  /**
   * AC-3/AC-4/AC-8: la lectura de ámbito es una operación propia, sin query ni
   * cuerpo, y devuelve el DTO con sedes y departamentos.
   */
  it('obtenerAmbitoInventario pide GET /inventario/ambito sin parámetros y devuelve el DTO', () => {
    const recibidas: AmbitoInventario[] = [];
    servicio.obtenerAmbitoInventario().subscribe((datos) => recibidas.push(datos));

    const peticion = httpMock.expectOne(RUTA_AMBITO);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.keys()).toEqual([]);
    expect(peticion.request.body).toBeNull();
    peticion.flush(AMBITO);

    expect(recibidas).toEqual([AMBITO]);
  });

  /** AC-3: `sede_id` viaja como query cuando se informa. */
  it('obtenerExistencias envía sede_id como query cuando se informa (AC-3)', () => {
    servicio.obtenerExistencias({ sede_id: 3 }).subscribe();

    const peticion = peticionExistencias();
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.get('sede_id')).toBe('3');
    peticion.flush([]);
  });

  /**
   * AC-2/AC-5: el filtro departamental también se envía al servidor, combinable
   * con `sede_id`; el cliente solo acota el texto, la categoría y los críticos.
   */
  it('obtenerExistencias envía departamento_id como query cuando se informa (AC-2)', () => {
    servicio.obtenerExistencias({ sede_id: 1, departamento_id: 10 }).subscribe();

    const peticion = peticionExistencias();
    expect(peticion.request.params.get('sede_id')).toBe('1');
    expect(peticion.request.params.get('departamento_id')).toBe('10');
    peticion.flush([]);
  });

  /** AC-3: sin valor no se agrega el parámetro (ni `null` ni omitido). */
  it('obtenerExistencias no envía sede_id cuando es null ni cuando falta (AC-3)', () => {
    servicio.obtenerExistencias({ sede_id: null }).subscribe();
    const conNulo = peticionExistencias();
    expect(conNulo.request.params.has('sede_id')).toBe(false);
    expect(conNulo.request.params.keys()).toEqual([]);
    conNulo.flush([]);

    servicio.obtenerExistencias().subscribe();
    const sinFiltros = peticionExistencias();
    expect(sinFiltros.request.params.keys()).toEqual([]);
    sinFiltros.flush([]);
  });

  /**
   * AC-8/D-5: las opciones de inventario no dependen de las lecturas
   * administrativas de `/organizacion/*` (el Bodeguero recibiría 403).
   */
  it('el inventario no consulta endpoints administrativos (AC-8/D-5)', () => {
    servicio.obtenerAmbitoInventario().subscribe();
    httpMock.expectOne(RUTA_AMBITO).flush(AMBITO);

    servicio.obtenerExistencias({ sede_id: 1 }).subscribe();
    peticionExistencias().flush([]);

    httpMock.expectNone((peticion) => peticion.url.includes('/organizacion/'));
  });
});
