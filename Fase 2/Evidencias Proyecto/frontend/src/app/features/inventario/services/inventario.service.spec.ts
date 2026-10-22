import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { Observable } from 'rxjs';

import { URL_API } from '../../../shared/config/url-api';
import { AmbitoInventario, ProductoDetalle } from '../../../shared/interfaces';
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

// ---------------------------------------------------------------------------
// Feature 019 (T7): detalle de producto por alcance
// ---------------------------------------------------------------------------

/**
 * Contrato de `GET /inventario/existencias/{producto_id}` (§8 de la spec 019).
 *
 * T7 lo declaró localmente porque en la fase roja la interface compartida no
 * existía. T8 publica `ProductoDetalle` en `shared/interfaces/index.ts`, así que
 * este alias ata la prueba al contrato compartido: si el tipo pierde o cambia un
 * campo, el fixture deja de compilar.
 */
type ProductoDetalleContrato = ProductoDetalle;

const DETALLE_PRODUCTO: ProductoDetalleContrato = {
  producto_id: 7,
  nombre: 'Cuaderno linedado',
  descripcion: 'Cuaderno de 100 hojas',
  unidad_medida: 'UNIDAD',
  stock_minimo: 10,
  categoria_id: 1,
  categoria_nombre: 'Papelería',
  categoria_activa: true,
  activo: true,
  institucion_id: 'inst-los-alpes',
  stock_total: 17,
  es_critico: false,
  sedes: [
    { sede_id: 1, sede_nombre: 'Sede Central', stock_actual: 12 },
    { sede_id: 3, sede_nombre: 'Sede Norte', stock_actual: 5 },
  ],
};

/** Orden alfabético de los 13 campos del contrato (§8). */
const CAMPOS_DEL_CONTRATO = [
  'activo',
  'categoria_activa',
  'categoria_id',
  'categoria_nombre',
  'descripcion',
  'es_critico',
  'institucion_id',
  'nombre',
  'producto_id',
  'sedes',
  'stock_minimo',
  'stock_total',
  'unidad_medida',
];

describe('InventarioService — detalle de producto por alcance (Feature 019)', () => {
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
   * T8 publica el método: se invoca directamente sobre el tipo del servicio, así
   * que un cambio de firma rompe la compilación de la suite en vez de colarse en
   * tiempo de ejecución.
   */
  function invocarDetalle(productoId: number): Observable<ProductoDetalle> {
    return servicio.obtenerDetalleProducto(productoId);
  }

  /**
   * AC-1/AC-13: el detalle es una lectura propia, `GET` sobre la ruta del
   * producto, sin query ni cuerpo, y devuelve los 13 campos exactos de §8.
   */
  it('obtenerDetalleProducto hace GET /inventario/existencias/{id} sin parámetros y devuelve el contrato de §8', () => {
    const recibidas: ProductoDetalleContrato[] = [];
    invocarDetalle(7).subscribe((detalle) => recibidas.push(detalle));

    const peticion = httpMock.expectOne(`${URL_API}/inventario/existencias/7`);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.keys()).toEqual([]);
    expect(peticion.request.body).toBeNull();
    peticion.flush(DETALLE_PRODUCTO);

    expect(recibidas).toEqual([DETALLE_PRODUCTO]);
    // Ni un campo de más ni de menos: el cliente no recorta el contrato.
    expect(Object.keys(recibidas[0]).sort()).toEqual(CAMPOS_DEL_CONTRATO);
  });

  /**
   * AC-9/D-3: el identificador viaja en la ruta y el cliente **no** elige el
   * ámbito. El detalle ignora los filtros de sede/departamento de la lista: el
   * servidor aplica el alcance completo del rol.
   */
  it('lleva el id en la ruta y no envía producto_id, sede_id ni departamento_id (AC-9/D-3)', () => {
    invocarDetalle(42).subscribe();

    const peticion = httpMock.expectOne(`${URL_API}/inventario/existencias/42`);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.has('producto_id')).toBe(false);
    expect(peticion.request.params.has('sede_id')).toBe(false);
    expect(peticion.request.params.has('departamento_id')).toBe(false);
    expect(peticion.request.params.keys()).toEqual([]);
    peticion.flush(DETALLE_PRODUCTO);
  });
});
