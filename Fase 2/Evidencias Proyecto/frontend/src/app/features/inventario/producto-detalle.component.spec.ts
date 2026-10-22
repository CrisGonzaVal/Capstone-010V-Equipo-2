import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { URL_API } from '../../shared/config/url-api';
import { SedeExistencia } from '../../shared/interfaces';
import { ProductoDetalleComponent } from './producto-detalle.component';

/**
 * Pruebas en rojo de la vista de detalle de producto (Feature 019, T7).
 *
 * Fijan el contrato observable que T9 debe cumplir: carga, datos presentables
 * de §8 sin identificadores, estados de error accesibles y diferenciados,
 * reintento sin bucle, vacío válido distinto del 404, lectura sin controles de
 * escritura y retorno a la pestaña de origen (`?tab=gestion`).
 *
 * `ProductoDetalleComponent` es todavía un stub sin plantilla (ver el archivo):
 * por eso todas estas pruebas fallan por comportamiento ausente, no por
 * compilación. Se asertan **textos y roles del DOM**, no miembros del
 * componente, para que la fase roja no dependa de una API interna que T9 puede
 * diseñar libremente. Los textos pactados aquí son el contrato de presentación:
 * la carga anuncia «Cargando», el vacío contiene «Sin existencias» y el enlace
 * de vuelta dice «Volver al inventario».
 */
describe('ProductoDetalleComponent', () => {
  const RUTA_EXISTENCIAS = `${URL_API}/inventario/existencias`;
  const RUTA_DETALLE = `${RUTA_EXISTENCIAS}/7`;

  let fixture: ComponentFixture<ProductoDetalleComponent>;
  let httpMock: HttpTestingController;

  /** Contrato de §8: 13 campos; los dos identificadores no se presentan. */
  interface ProductoDetalleContrato {
    producto_id: number;
    nombre: string;
    descripcion: string | null;
    unidad_medida: string | null;
    stock_minimo: number;
    categoria_id: number;
    categoria_nombre: string;
    categoria_activa: boolean;
    activo: boolean;
    institucion_id: string | null;
    stock_total: number;
    es_critico: boolean;
    sedes: SedeExistencia[];
  }

  /**
   * Respuesta base: producto activo, categoría activa y dos sedes.
   *
   * `stock_total` (17) es la suma de las sedes devueltas (12 + 5) y
   * `es_critico` es falso porque ninguna sede baja del mínimo (10).
   */
  function crearDetalle(
    sobrescribir: Partial<ProductoDetalleContrato> = {},
  ): ProductoDetalleContrato {
    return {
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
      ...sobrescribir,
    };
  }

  /**
   * `ActivatedRoute` mínimo: el id de la ruta y la pestaña de procedencia.
   *
   * Se cubren `paramMap`/`queryParamMap` observables y `snapshot` para que T9
   * pueda leer el origen por cualquiera de las dos vías sin reabrir la prueba.
   */
  function crearRuta(
    productoId: string,
    consulta: Record<string, string> = {},
  ): ActivatedRoute {
    const paramMap = convertToParamMap({ productoId });
    const queryParamMap = convertToParamMap(consulta);
    return {
      paramMap: of(paramMap),
      queryParamMap: of(queryParamMap),
      snapshot: { paramMap, queryParamMap },
    } as unknown as ActivatedRoute;
  }

  /**
   * Monta el componente con el id y la pestaña indicados.
   *
   * `provideRouter([])` es obligatorio porque la vista usa `RouterLink` para el
   * enlace de vuelta (AC-9).
   */
  async function montar(
    productoId = '7',
    consulta: Record<string, string> = {},
  ): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [ProductoDetalleComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: crearRuta(productoId, consulta) },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ProductoDetalleComponent);
    fixture.detectChanges();
  }

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  function raiz(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function texto(): string {
    return (raiz().textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  function alertas(): string[] {
    return Array.from(raiz().querySelectorAll('[role="alert"]')).map((nodo) =>
      (nodo.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
  }

  function botones(): string[] {
    return Array.from(raiz().querySelectorAll('button')).map((boton) =>
      (boton.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
  }

  function boton(etiqueta: string): HTMLButtonElement | null {
    return (
      Array.from(raiz().querySelectorAll<HTMLButtonElement>('button')).find(
        (candidato) => (candidato.textContent ?? '').replace(/\s+/g, ' ').trim() === etiqueta,
      ) ?? null
    );
  }

  /** Enlace «← Volver al inventario» (AC-9/§6.6). */
  function enlaceVolver(): HTMLAnchorElement | null {
    return (
      Array.from(raiz().querySelectorAll<HTMLAnchorElement>('a')).find((enlace) =>
        (enlace.textContent ?? '').includes('Volver al inventario'),
      ) ?? null
    );
  }

  const PETICION_DE_DETALLE = (peticion: { url: string }): boolean =>
    peticion.url.startsWith(RUTA_EXISTENCIAS);

  // ---------------------------------------------------------------------------
  // Carga y datos presentables (AC-1)
  // ---------------------------------------------------------------------------

  it('anuncia la carga y después presenta el producto y el desglose por sede (AC-1)', async () => {
    await montar();

    expect(texto())
      .withContext('la vista debe anunciar la carga mientras la petición está en vuelo')
      .toContain('Cargando');

    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    const contenido = texto();
    expect(contenido).toContain('Cuaderno linedado');
    expect(contenido).toContain('Cuaderno de 100 hojas');
    expect(contenido).toContain('UNIDAD');
    expect(contenido).toContain('Papelería');
    // Mínimo, total (12 + 5) y criticidad: el producto no está crítico.
    expect(contenido).toContain('10');
    expect(contenido).toContain('17');
    expect(contenido).toContain('Disponible');
    // Desglose por sede con nombre y saldo (orden del contrato).
    expect(contenido).toContain('Sede Central');
    expect(contenido).toContain('12');
    expect(contenido).toContain('Sede Norte');
    expect(contenido).toContain('5');
    expect(alertas()).toEqual([]);
  });

  it('no presenta producto_id ni institucion_id aunque formen parte del contrato (AC-1/§8)', async () => {
    await montar('4242');
    httpMock
      .expectOne(`${RUTA_EXISTENCIAS}/4242`)
      .flush(crearDetalle({ producto_id: 4242, institucion_id: 'inst-secreta-019' }));
    fixture.detectChanges();

    const contenido = texto();
    expect(contenido).toContain('Cuaderno linedado');
    expect(contenido).not.toContain('4242');
    expect(contenido).not.toContain('inst-secreta-019');
  });

  it('marca la criticidad cuando alguna sede visible baja del mínimo (AC-1/AC-7)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).flush(
      crearDetalle({
        stock_total: 3,
        es_critico: true,
        sedes: [{ sede_id: 4, sede_nombre: 'Sede Norte', stock_actual: 3 }],
      }),
    );
    fixture.detectChanges();

    expect(texto()).toContain('Crítico');
    expect(texto()).toContain('Sede Norte');
  });

  // ---------------------------------------------------------------------------
  // Parámetro inválido: sin petición y error controlado (AC-10/§6.5)
  // ---------------------------------------------------------------------------

  // Cero, negativo y no entero: ninguno identifica un producto válido.
  for (const invalido of ['0', '-3', '1abc']) {
    it(`con productoId "${invalido}" no emite petición y muestra un error controlado (AC-10/§6.5)`, async () => {
      await montar(invalido);

      httpMock.expectNone(PETICION_DE_DETALLE);

      const mensajes = alertas().join(' ');
      expect(mensajes)
        .withContext('el identificador inválido debe explicarse en un role="alert"')
        .toContain('no es válido');
      expect(texto()).not.toContain('Cargando');
    });
  }

  // ---------------------------------------------------------------------------
  // Estados de error accesibles y reintento (AC-10)
  // ---------------------------------------------------------------------------

  it('presenta el 403 de capacidad como alerta y ofrece reintento sin bucle (AC-10)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).flush(
      { detail: 'La capacidad inventario esta deshabilitada para la institucion' },
      { status: 403, statusText: 'Forbidden' },
    );
    fixture.detectChanges();

    expect(alertas().join(' ')).toContain('capacidad inventario');
    // Sin bucle: ningún reintento automático tras el fallo.
    httpMock.expectNone(PETICION_DE_DETALLE);

    const reintentar = boton('Reintentar');
    expect(reintentar)
      .withContext('el 403 es recuperable según §6.4 y debe ofrecer reintento')
      .not.toBeNull();
    reintentar!.click();

    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    expect(texto()).toContain('Cuaderno linedado');
    expect(alertas()).toEqual([]);
  });

  it('presenta el 404 como alerta y lo distingue del vacío válido (AC-6/AC-10)', async () => {
    await montar();
    httpMock
      .expectOne(RUTA_DETALLE)
      .flush({ detail: 'Producto no encontrado' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(alertas().join(' ')).toContain('no encontrado');
    expect(texto()).not.toContain('Sin existencias');
  });

  it('presenta el 409 de sede no resoluble como alerta y permite reintentar (AC-10)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).flush(
      { detail: 'Tu usuario no tiene una sede asignada' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    expect(alertas().join(' ')).toContain('sede');
    expect(boton('Reintentar')).not.toBeNull();

    boton('Reintentar')!.click();
    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    expect(texto()).toContain('Cuaderno linedado');
  });

  it('presenta el fallo de red (status 0) como alerta y reintenta (AC-10)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect(alertas().join(' ')).toContain('servidor');
    httpMock.expectNone(PETICION_DE_DETALLE);

    boton('Reintentar')!.click();
    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    expect(texto()).toContain('Cuaderno linedado');
    expect(alertas()).toEqual([]);
  });

  it('presenta un error de servidor (500 sin cuerpo) como alerta sin bucle (AC-10)', async () => {
    await montar();
    httpMock
      .expectOne(RUTA_DETALLE)
      .flush('', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(alertas().length).toBeGreaterThan(0);
    httpMock.expectNone(PETICION_DE_DETALLE);
  });

  it('mapea el 422 de identificador a un mensaje de valor no válido, distinto del 404 (AC-10)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).flush(
      { detail: [{ loc: ['path', 'producto_id'], msg: 'Input should be a valid integer' }] },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    fixture.detectChanges();

    const mensajes = alertas().join(' ');
    expect(mensajes).toContain('no es válido');
    expect(mensajes).not.toContain('no encontrado');
  });

  // ---------------------------------------------------------------------------
  // Vacío válido y datos inactivos (AC-3/AC-6/AC-10)
  // ---------------------------------------------------------------------------

  it('un 200 con sedes vacías renderiza un vacío legible, distinto de error y de 404 (AC-6/D-7)', async () => {
    await montar();
    httpMock
      .expectOne(RUTA_DETALLE)
      .flush(crearDetalle({ sedes: [], stock_total: 0, es_critico: true }));
    fixture.detectChanges();

    const contenido = texto();
    expect(alertas()).toEqual([]);
    expect(contenido).toContain('Sin existencias');
    expect(contenido).toContain('Cuaderno linedado');
    // El total cero y la criticidad del contrato siguen presentes.
    expect(contenido).toContain('0');
    expect(contenido).toContain('Crítico');
    // Es un resultado válido: no hay reintento ni mensaje de error.
    expect(boton('Reintentar')).toBeNull();
    expect(contenido).not.toContain('no encontrado');
  });

  it('indica el producto y la categoría inactivos sin controles de escritura (AC-3/AC-10)', async () => {
    await montar();
    httpMock
      .expectOne(RUTA_DETALLE)
      .flush(crearDetalle({ activo: false, categoria_activa: false }));
    fixture.detectChanges();

    const contenido = texto().toLowerCase();
    expect(contenido).toContain('inactivo');
    expect(contenido).toContain('categor');

    // Solo lectura: la vista no publica ninguna acción de modificación.
    expect(botones()).toEqual([]);
    expect(raiz().querySelectorAll('input, select, textarea').length).toBe(0);
  });

  // ---------------------------------------------------------------------------
  // Retorno contextual a la pestaña de origen (AC-8/AC-9/§6.6)
  // ---------------------------------------------------------------------------

  it('vuelve a /inventario (Existencias) cuando no hay pestaña de origen (AC-9)', async () => {
    await montar();
    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    const volver = enlaceVolver();
    expect(volver)
      .withContext('falta el enlace «← Volver al inventario»')
      .not.toBeNull();
    expect(volver!.getAttribute('href')).toBe('/inventario');
  });

  it('vuelve a /inventario?tab=gestion cuando el detalle se abrió desde Gestión (AC-8/AC-9)', async () => {
    await montar('7', { tab: 'gestion' });
    httpMock.expectOne(RUTA_DETALLE).flush(crearDetalle());
    fixture.detectChanges();

    const volver = enlaceVolver();
    expect(volver)
      .withContext('falta el enlace «← Volver al inventario»')
      .not.toBeNull();
    expect(volver!.getAttribute('href')).toBe('/inventario?tab=gestion');
  });
});
