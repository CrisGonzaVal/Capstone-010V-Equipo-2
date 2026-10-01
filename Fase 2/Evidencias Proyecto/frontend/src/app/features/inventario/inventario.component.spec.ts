import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { URL_API } from '../../shared/config/url-api';
import { Categoria, ProductoExistencia, SedeExistencia } from '../../shared/interfaces';
import { InventarioComponent } from './inventario.component';

const RUTA_EXISTENCIAS = `${URL_API}/inventario/existencias`;
const RUTA_CATEGORIAS = `${URL_API}/inventario/categorias`;

function crearCategoria(sobrescribir: Partial<Categoria> = {}): Categoria {
  return {
    categoria_id: 1,
    nombre_cat: 'Papeleria',
    descripcion_cat: 'Insumos de papeleria',
    ...sobrescribir,
  };
}

function crearSede(sobrescribir: Partial<SedeExistencia> = {}): SedeExistencia {
  return {
    inventario_id: 1,
    departamento_id: 1,
    departamento_nombre: 'Operaciones',
    stock_actual: 50,
    ubicacion: 'Bodega central',
    ...sobrescribir,
  };
}

function crearInsumo(sobrescribir: Partial<ProductoExistencia> = {}): ProductoExistencia {
  return {
    producto_id: 1,
    nombre: 'Cuaderno linedado',
    descripcion: 'Cuaderno de 100 hojas',
    unidad_medida: 'UNIDAD',
    stock_minimo: 10,
    categoria_id: 1,
    categoria_nombre: 'Papeleria',
    stock_total: 50,
    es_critico: false,
    sedes: [crearSede()],
    ...sobrescribir,
  };
}

const CATEGORIAS: Categoria[] = [
  crearCategoria(),
  crearCategoria({ categoria_id: 2, nombre_cat: 'Toner', descripcion_cat: 'Consumibles' }),
];

const INSUMOS: ProductoExistencia[] = [
  crearInsumo(),
  crearInsumo({
    producto_id: 2,
    nombre: 'Resma Carta 75g',
    descripcion: 'Resma de 500 hojas',
    unidad_medida: 'RESMA',
    stock_minimo: 20,
    stock_total: 150,
    sedes: [
      crearSede({ inventario_id: 2, stock_actual: 120 }),
      crearSede({
        inventario_id: 3,
        departamento_id: 2,
        departamento_nombre: 'Bodega',
        stock_actual: 30,
        ubicacion: 'Bodega central - A2',
      }),
    ],
  }),
  crearInsumo({
    producto_id: 3,
    nombre: 'Toner HP 26A',
    descripcion: null,
    stock_minimo: 10,
    categoria_id: 2,
    categoria_nombre: 'Toner',
    stock_total: 3,
    es_critico: true,
    sedes: [
      crearSede({
        inventario_id: 4,
        departamento_id: 2,
        departamento_nombre: 'Bodega',
        stock_actual: 3,
        ubicacion: 'Bodega central - B1',
      }),
    ],
  }),
];

describe('InventarioComponent', () => {
  let fixture: ComponentFixture<InventarioComponent>;
  let componente: InventarioComponent;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InventarioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(InventarioComponent);
    componente = fixture.componentInstance;
  });

  afterEach(() => {
    // `ignoreCancelled`: cuando una de las dos peticiones de `forkJoin` falla, la
    // otra queda cancelada y ya no se puede responder con `flush`.
    httpMock.verify({ ignoreCancelled: true });
  });

  /** Dispara `ngOnInit` y resuelve las dos peticiones del catalogo. */
  function cargar(categorias: Categoria[], insumos: ProductoExistencia[]) {
    const peticiones = {
      insumos: httpMock.expectOne(RUTA_EXISTENCIAS),
      categorias: httpMock.expectOne(RUTA_CATEGORIAS),
    };
    peticiones.insumos.flush(insumos);
    peticiones.categorias.flush(categorias);
    fixture.detectChanges();
    return peticiones;
  }

  /** Monta el componente y lo deja con el catalogo sembrado. */
  function montar() {
    fixture.detectChanges();
    return cargar(CATEGORIAS, INSUMOS);
  }

  function filas(): HTMLElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('tbody tr'));
  }

  function textoDeLaTabla(): string {
    return fixture.nativeElement.querySelector('tbody')?.textContent ?? '';
  }

  function panelDeCategorias(): string {
    const nav = fixture.nativeElement.querySelector('nav[aria-label]');
    return nav?.textContent ?? '';
  }

  it('debe pedir el catalogo y las categorias', () => {
    const peticiones = montar();

    // Las dos peticiones salieron, y solo esas dos.
    expect(peticiones.insumos.request.method).toBe('GET');
    expect(peticiones.categorias.request.method).toBe('GET');
    expect(componente.insumos()).toEqual(INSUMOS);
    expect(componente.categorias()).toEqual(CATEGORIAS);
  });

  it('debe renderizar los insumos con su categoria y su sede', () => {
    montar();

    expect(filas().length).toBe(3);

    const texto = textoDeLaTabla();
    expect(texto).toContain('Resma Carta 75g');
    expect(texto).toContain('Papeleria');
    // La celda de sedes une departamento, ubicacion y cantidad.
    expect(texto).toContain('Operaciones · Bodega central');
    expect(texto).toContain('Bodega · Bodega central - A2');

    // El estado se distingue por texto, no solo por color.
    expect(texto).toContain('Disponible');
    expect(texto).toContain('Crítico');
  });

  it('debe filtrar por texto', () => {
    montar();

    componente.consulta.set('resma');
    fixture.detectChanges();

    expect(filas().length).toBe(1);
    expect(textoDeLaTabla()).toContain('Resma Carta 75g');
    expect(textoDeLaTabla()).not.toContain('Cuaderno linedado');
  });

  it('debe filtrar por categoria sin inutilizar el panel', () => {
    montar();

    componente.seleccionarCategoria(2);
    fixture.detectChanges();

    expect(filas().length).toBe(1);
    expect(textoDeLaTabla()).toContain('Toner HP 26A');

    // Los conteos del panel son los de antes del filtro de categoria: si no,
    // "Papeleria" marcaria 0 y el panel dejaria de poder navegar.
    expect(panelDeCategorias()).toContain('2 insumos');
    expect(panelDeCategorias()).toContain('1 insumos');
  });

  it('debe filtrar solo los insumos criticos', () => {
    montar();

    componente.alternarSoloCriticos();
    fixture.detectChanges();

    expect(filas().length).toBe(1);
    expect(textoDeLaTabla()).toContain('Toner HP 26A');
    expect(textoDeLaTabla()).not.toContain('Disponible');
  });

  it('debe limpiar los filtros', () => {
    montar();

    componente.consulta.set('resma');
    componente.seleccionarCategoria(1);
    componente.alternarSoloCriticos();
    fixture.detectChanges();
    expect(filas().length).toBe(0);

    componente.limpiarFiltros();
    fixture.detectChanges();

    expect(componente.consulta()).toBe('');
    expect(componente.categoriaSeleccionada()).toBeNull();
    expect(componente.soloCriticos()).toBe(false);
    expect(filas().length).toBe(3);
  });

  it('debe mostrar un error si el backend no responde', () => {
    fixture.detectChanges();

    // La otra peticion queda cancelada sola: `forkJoin` se desuscribe al fallar.
    httpMock.expectOne(RUTA_EXISTENCIAS).flush('error', { status: 500, statusText: 'Error' });
    fixture.detectChanges();

    const alerta = fixture.nativeElement.querySelector('[role="alert"]');
    expect(alerta).toBeTruthy();
    expect(alerta.textContent).toContain('500');
    expect(alerta.textContent).toContain('8000');
    expect(componente.cargando()).toBe(false);
  });

  it('debe distinguir el estado vacio del estado con filtros', () => {
    fixture.detectChanges();
    cargar([], []);

    let mensaje = fixture.nativeElement.textContent;
    expect(mensaje).toContain('El catálogo no tiene insumos cargados.');

    // Con filtros activos el mensaje es otro: no hay resultados, no un catalogo vacio.
    componente.consulta.set('resma');
    fixture.detectChanges();

    mensaje = fixture.nativeElement.textContent;
    expect(mensaje).toContain('Ningún insumo coincide con los filtros aplicados.');
    expect(mensaje).not.toContain('El catálogo no tiene insumos cargados.');
  });
});