import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';

import { AutenticacionService } from '../../core/services/auth.service';
import { URL_API } from '../../shared/config/url-api';
import {
  Categoria,
  GestionCatalogo,
  HistorialTransicionCategoria,
  IdentidadAutenticada,
  ProductoExistencia,
  SedeExistencia,
} from '../../shared/interfaces';
import { InventarioComponent } from './inventario.component';

const RUTA_EXISTENCIAS = `${URL_API}/inventario/existencias`;
const RUTA_CATEGORIAS = `${URL_API}/inventario/categorias`;
const RUTA_GESTION = `${URL_API}/inventario/gestion`;

function rutaEstadoProducto(productoId: number): string {
  return `${URL_API}/inventario/productos/${productoId}/estado`;
}

function rutaEstadoCategoria(categoriaId: number): string {
  return `${URL_API}/inventario/categorias/${categoriaId}/estado`;
}

function rutaHistorialProducto(productoId: number): string {
  return `${URL_API}/inventario/productos/${productoId}/historial`;
}

function rutaHistorialCategoria(categoriaId: number): string {
  return `${URL_API}/inventario/categorias/${categoriaId}/historial`;
}

function crearCategoria(sobrescribir: Partial<Categoria> = {}): Categoria {
  return {
    categoria_id: 1,
    nombre_cat: 'Papeleria',
    descripcion_cat: 'Insumos de papeleria',
    activo: true,
    ...sobrescribir,
  };
}

function crearSede(sobrescribir: Partial<SedeExistencia> = {}): SedeExistencia {
  return {
    sede_id: 1,
    sede_nombre: 'Sede Central',
    stock_actual: 50,
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
      crearSede({ sede_id: 2, sede_nombre: 'Sede Central', stock_actual: 120 }),
      crearSede({ sede_id: 3, sede_nombre: 'Sede Norte', stock_actual: 30 }),
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
      crearSede({ sede_id: 4, sede_nombre: 'Sede Norte', stock_actual: 3 }),
    ],
  }),
];

/**
 * Listado administrativo (Feature 014, AC-15): ambos estados.
 *
 * `Grapadora retirada` es un producto **inactivo que no está en el listado
 * operativo** (`INSUMOS`). Sirve para probar que la sección consume `/gestion`
 * y no la lista filtrada: si la sección se alimentara de la vista operativa,
 * ese producto no aparecería.
 */
const GESTION: GestionCatalogo = {
  categorias: [
    {
      categoria_id: 1,
      nombre_cat: 'Papeleria',
      descripcion_cat: 'Insumos de papeleria',
      activo: true,
    },
    {
      categoria_id: 2,
      nombre_cat: 'Toner',
      descripcion_cat: 'Consumibles',
      activo: false,
    },
  ],
  productos: [
    {
      producto_id: 1,
      nombre: 'Cuaderno linedado',
      descripcion: 'Cuaderno de 100 hojas',
      unidad_medida: 'UNIDAD',
      stock_minimo: 10,
      categoria_id: 1,
      categoria_nombre: 'Papeleria',
      categoria_activa: true,
      activo: true,
    },
    {
      producto_id: 9,
      nombre: 'Grapadora retirada',
      descripcion: null,
      unidad_medida: 'UNIDAD',
      stock_minimo: 0,
      categoria_id: 2,
      categoria_nombre: 'Toner',
      categoria_activa: false,
      activo: false,
    },
  ],
};

/** Variante con la categoría `Toner` reactivada, para la recarga tras un 200. */
const GESTION_TONER_ACTIVA: GestionCatalogo = {
  ...GESTION,
  categorias: GESTION.categorias.map((categoria) =>
    categoria.categoria_id === 2 ? { ...categoria, activo: true } : categoria,
  ),
};

const HISTORIAL_CATEGORIA: HistorialTransicionCategoria[] = [
  {
    historial_categoria_id: 2,
    categoria_id: 2,
    usuario_id: 9,
    fecha_transicion: '2026-10-20T10:15:00',
    activo_origen: true,
    activo_destino: false,
    motivo: 'Tóner descontinuado por el proveedor',
    usuario_nombre: 'Ana',
    usuario_apellido: 'Pérez',
  },
  {
    historial_categoria_id: 1,
    categoria_id: 2,
    usuario_id: 8,
    fecha_transicion: '2026-10-19T08:00:00',
    activo_origen: false,
    activo_destino: true,
    motivo: 'Reapertura del catálogo de consumibles',
    usuario_nombre: 'Bruno',
    usuario_apellido: 'Soto',
  },
];

function crearIdentidad(rol: string): IdentidadAutenticada {
  return {
    usuario_id: 9,
    sub: 'user_inventario',
    nombre: 'Ana',
    apellido: 'Pérez',
    correo: 'ana.perez@losalpes.cl',
    rol,
    institucion: { institucion_id: 'inst-los-alpes', nombre: 'Los Alpes' },
  };
}

describe('InventarioComponent', () => {
  let fixture: ComponentFixture<InventarioComponent>;
  let componente: InventarioComponent;
  let httpMock: HttpTestingController;

  /** Identidad local (`/auth/me`) que la vista lee para decidir la sección. */
  let identidad: WritableSignal<IdentidadAutenticada | null>;

  beforeEach(async () => {
    // Por defecto, un rol operativo: las pruebas heredadas de la vista
    // operativa no deben disparar el listado de gestión.
    identidad = signal<IdentidadAutenticada | null>(crearIdentidad('Bodeguero'));

    await TestBed.configureTestingModule({
      imports: [InventarioComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AutenticacionService, useValue: { identidad } },
      ],
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
    // La celda de sedes une el nombre de la sede y su saldo.
    expect(texto).toContain('Sede Central');
    expect(texto).toContain('Sede Norte');

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

  /**
   * AC-19: la vista de una institución presenta exactamente el catálogo y el
   * stock que el servidor devolvió para su ámbito. El servidor ya aísla (T6);
   * el cliente no agrega ni recombina datos de otra institución, y tampoco
   * elige el ámbito: no lo envía.
   */
  describe('aislamiento institucional en la vista (AC-19)', () => {
    /** Homónimo de INST-A: mismo nombre que en INST-B, con id y stock propios. */
    const INSUMOS_A: ProductoExistencia[] = [
      crearInsumo({
        producto_id: 101,
        nombre: 'Resma Carta 75g',
        stock_total: 120,
        stock_minimo: 20,
        sedes: [crearSede({ sede_id: 55, stock_actual: 120 })],
      }),
    ];

    const CATEGORIAS_A: Categoria[] = [crearCategoria()];

    it('presenta solo el catálogo y el stock del ámbito recibido', () => {
      fixture.detectChanges();
      cargar(CATEGORIAS_A, INSUMOS_A);

      expect(componente.insumos()).toEqual(INSUMOS_A);
      expect(componente.categorias()).toEqual(CATEGORIAS_A);

      const texto = textoDeLaTabla();
      expect(texto).toContain('Resma Carta 75g');
      // El stock es el de INST-A (120), no una suma ni un valor de INST-B.
      expect(texto).toContain('120');
      // Solo las filas que el servidor devolvió: nada de homónimos de INST-B.
      expect(filas().length).toBe(1);
      expect(componente.totalCatalogo()).toBe(1);
    });

    it('no envía institución ni parámetros de ámbito: el filtro es del servidor', () => {
      fixture.detectChanges();
      const peticiones = {
        insumos: httpMock.expectOne(RUTA_EXISTENCIAS),
        categorias: httpMock.expectOne(RUTA_CATEGORIAS),
      };
      peticiones.insumos.flush(INSUMOS_A);
      peticiones.categorias.flush(CATEGORIAS_A);
      fixture.detectChanges();

      for (const peticion of [peticiones.insumos, peticiones.categorias]) {
        expect(peticion.request.method).toBe('GET');
        expect(peticion.request.params.has('institucion_id')).toBe(false);
        expect(peticion.request.body).toBeNull();
        expect(peticion.request.headers.get('X-Institucion-Id')).toBeNull();
      }
    });
  });

  // ---------------------------------------------------------------------------
  // Ciclo de vida del catálogo (Feature 014, AC-11/AC-12/AC-15)
  // ---------------------------------------------------------------------------

  function seccionGestion(): HTMLElement | null {
    return fixture.nativeElement.querySelector(
      'section[aria-label="Ciclo de vida del catálogo"]',
    );
  }

  function panelExistencias(): HTMLElement | null {
    return fixture.nativeElement.querySelector('#panel-existencias');
  }

  function panelGestion(): HTMLElement | null {
    return fixture.nativeElement.querySelector('#panel-gestion');
  }

  function pestanas(): HTMLButtonElement[] {
    const raiz = fixture.nativeElement as HTMLElement;
    return Array.from(raiz.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  }

  function pestana(etiqueta: string): HTMLButtonElement {
    const encontrada = pestanas().find((candidata) => (candidata.textContent ?? '').trim() === etiqueta);
    expect(encontrada).withContext(`pestaña "${etiqueta}"`).toBeTruthy();
    return encontrada!;
  }

  /** Pulsa la pestaña de gestión (solo existe para Administrador). */
  function abrirGestion(): void {
    pestana('Gestión del catálogo').click();
    fixture.detectChanges();
  }

  /** Vuelve a la pestaña operativa. */
  function abrirExistencias(): void {
    pestana('Existencias').click();
    fixture.detectChanges();
  }

  function textoSeccion(): string {
    return (seccionGestion()?.textContent ?? '').replace(/\s+/g, ' ');
  }

  function botonesDeLaSeccion(): HTMLButtonElement[] {
    const seccion = seccionGestion();
    return seccion === null
      ? []
      : Array.from(seccion.querySelectorAll<HTMLButtonElement>('button'));
  }

  function boton(texto: string): HTMLButtonElement {
    const encontrado = botonesDeLaSeccion().find(
      (candidato) =>
        (candidato.textContent ?? '').replace(/\s+/g, ' ').trim() === texto,
    );
    expect(encontrado).withContext(`botón "${texto}"`).toBeTruthy();
    return encontrado!;
  }

  function botonConAria(fragmento: string): HTMLButtonElement {
    const encontrado = botonesDeLaSeccion().find((candidato) =>
      (candidato.getAttribute('aria-label') ?? '').includes(fragmento),
    );
    expect(encontrado).withContext(`botón con aria "${fragmento}"`).toBeTruthy();
    return encontrado!;
  }

  /** Responde las tres peticiones de una transición aceptada (recargas). */
  function responderRecargas(datos: GestionCatalogo = GESTION): void {
    httpMock.expectOne(RUTA_GESTION).flush(datos);
    httpMock.expectOne(RUTA_EXISTENCIAS).flush(INSUMOS);
    httpMock.expectOne(RUTA_CATEGORIAS).flush(CATEGORIAS);
    fixture.detectChanges();
  }

  /** Arranca como Administrador y responde catálogo operativo + gestión. */
  function montarAdmin(datos: GestionCatalogo = GESTION) {
    identidad.set(crearIdentidad('Administrador'));
    fixture.detectChanges();

    const peticiones = {
      insumos: httpMock.expectOne(RUTA_EXISTENCIAS),
      categorias: httpMock.expectOne(RUTA_CATEGORIAS),
      gestion: httpMock.expectOne(RUTA_GESTION),
    };
    peticiones.insumos.flush(INSUMOS);
    peticiones.categorias.flush(CATEGORIAS);
    peticiones.gestion.flush(datos);
    fixture.detectChanges();
    return peticiones;
  }

  describe('sección de gestión por rol (AC-11)', () => {
    for (const rol of ['Bodeguero', 'Solicitante'] as const) {
      it(`no renderiza la sección ni el conmutador para ${rol} y conserva la vista operativa`, () => {
        identidad.set(crearIdentidad(rol));
        fixture.detectChanges();
        cargar(CATEGORIAS, INSUMOS);

        expect(seccionGestion()).toBeNull();
        expect(panelGestion()).toBeNull();
        // Sin conmutador: no hay pestaña vacía ni bloqueada, solo la vista operativa.
        expect(pestanas().length).toBe(0);
        expect(fixture.nativeElement.querySelector('[role="tablist"]')).toBeNull();
        expect(fixture.nativeElement.textContent).not.toContain(
          'Ciclo de vida del catálogo',
        );
        expect(fixture.nativeElement.textContent).not.toContain('Gestión del catálogo');
        // La pestaña operativa es la única y está renderizada.
        expect(panelExistencias()).toBeTruthy();
        expect(componente.pestanaActiva()).toBe('existencias');
        // Ninguna acción de mutación en toda la vista.
        const raiz = fixture.nativeElement as HTMLElement;
        const textos = Array.from(raiz.querySelectorAll<HTMLButtonElement>('button')).map(
          (b) => (b.textContent ?? '').trim(),
        );
        expect(textos).not.toContain('Dar de baja');
        expect(textos).not.toContain('Reactivar');
        // La vista operativa sigue igual.
        expect(filas().length).toBe(3);
        expect(componente.gestion()).toBeNull();
      });
    }
  });

  describe('pestañas de inventario (enmienda de AC-11)', () => {
    it('abre «Existencias» por defecto y no renderiza la pestaña de gestión', () => {
      montarAdmin();

      expect(componente.pestanaActiva()).toBe('existencias');
      expect(panelExistencias()).toBeTruthy();
      expect(panelGestion()).toBeNull();
      expect(seccionGestion()).toBeNull();
      // La tabla operativa y sus filtros viven en la pestaña por defecto.
      expect(filas().length).toBe(3);
      expect(fixture.nativeElement.querySelector('input[aria-label="Buscar insumos"]')).toBeTruthy();
    });

    it('el Administrador ve el conmutador con las dos pestañas y su selección', () => {
      montarAdmin();

      expect(fixture.nativeElement.querySelector('[role="tablist"]')).toBeTruthy();
      expect(pestanas().map((p) => (p.textContent ?? '').trim())).toEqual([
        'Existencias',
        'Gestión del catálogo',
      ]);
      expect(pestana('Existencias').getAttribute('aria-selected')).toBe('true');
      expect(pestana('Gestión del catálogo').getAttribute('aria-selected')).toBe('false');
      // Un solo tab stop: `tabindex` móvil en la pestaña activa.
      expect(pestana('Existencias').getAttribute('tabindex')).toBe('0');
      expect(pestana('Gestión del catálogo').getAttribute('tabindex')).toBe('-1');
    });

    it('cambia a la pestaña de gestión y vuelve a Existencias', () => {
      montarAdmin();

      abrirGestion();

      expect(componente.pestanaActiva()).toBe('gestion');
      expect(panelGestion()).toBeTruthy();
      expect(seccionGestion()).toBeTruthy();
      expect(panelExistencias()).toBeNull();
      expect(filas().length).toBe(0);
      expect(pestana('Gestión del catálogo').getAttribute('aria-selected')).toBe('true');
      expect(pestana('Existencias').getAttribute('aria-selected')).toBe('false');

      abrirExistencias();

      expect(panelExistencias()).toBeTruthy();
      expect(panelGestion()).toBeNull();
      expect(filas().length).toBe(3);
    });

    it('navega entre pestañas con las flechas del teclado', () => {
      montarAdmin();

      const tablist = fixture.nativeElement.querySelector('[role="tablist"]') as HTMLElement;
      tablist.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      fixture.detectChanges();
      expect(componente.pestanaActiva()).toBe('gestion');
      expect(panelGestion()).toBeTruthy();

      tablist.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
      fixture.detectChanges();
      expect(componente.pestanaActiva()).toBe('existencias');
    });
  });

  describe('sección de gestión del Administrador (AC-11/AC-15)', () => {
    it('consume el listado de gestión y muestra activos e inactivos', () => {
      montarAdmin();
      abrirGestion();

      expect(componente.gestion()).toEqual(GESTION);
      const seccion = seccionGestion();
      expect(seccion).toBeTruthy();

      const texto = textoSeccion();
      expect(texto).toContain('Ciclo de vida del catálogo');
      // Categorías y productos, con su estado visible por texto, no solo color.
      expect(texto).toContain('Papeleria');
      expect(texto).toContain('Activa');
      expect(texto).toContain('Toner');
      expect(texto).toContain('Inactiva');
      expect(texto).toContain('Cuaderno linedado');
      expect(texto).toContain('Grapadora retirada');
      expect(texto).toContain('Inactivo');
      expect(texto).toContain('(categoría inactiva)');
      // La franja resume ambos estados del listado administrativo.
      expect(componente.totalActivosGestion()).toBe(2);
      expect(componente.totalInactivosGestion()).toBe(2);
    });

    it('se alimenta solo de /gestion: el inactivo ausente del catálogo operativo aparece ahí y no en la tabla', () => {
      montarAdmin();

      abrirGestion();
      // `Grapadora retirada` solo existe en el listado administrativo.
      expect(textoSeccion()).toContain('Grapadora retirada');

      // La tabla operativa conserva exactamente sus 3 filas filtradas y el
      // inactivo no está en ella.
      abrirExistencias();
      expect(textoDeLaTabla()).not.toContain('Grapadora retirada');
      expect(filas().length).toBe(3);
    });

    it('200 idempotente muestra el estado actual sin error', () => {
      montarAdmin();
      abrirGestion();

      // `Toner` ya está inactiva: reactivarla sin cambio efectivo es 200.
      botonConAria('la categoría Toner').click();
      fixture.detectChanges();
      expect(textoSeccion()).toContain('Reactivar «Toner»');

      componente.motivo.set('Reactivación aprobada por coordinación');
      fixture.detectChanges();
      boton('Confirmar').click();

      const peticion = httpMock.expectOne(rutaEstadoCategoria(2));
      expect(peticion.request.method).toBe('PATCH');
      expect(peticion.request.body).toEqual({
        activo: true,
        motivo: 'Reactivación aprobada por coordinación',
      });
      peticion.flush({
        categoria_id: 2,
        nombre_cat: 'Toner',
        descripcion_cat: 'Consumibles',
        activo: true,
      });
      fixture.detectChanges();

      const seccion = seccionGestion()!;
      expect(seccion.querySelector('[role="alert"]')).toBeNull();
      const estado = seccion.querySelector('[role="status"]');
      expect(estado?.textContent).toContain('«Toner» ahora está activo');
      // El formulario se cierra y el estado recargado refleja el destino.
      expect(seccion.querySelector('textarea#motivo-transicion')).toBeNull();

      responderRecargas(GESTION_TONER_ACTIVA);
      expect(componente.gestion()).toEqual(GESTION_TONER_ACTIVA);
    });

    it('422 del motivo se muestra con el mensaje del servidor', () => {
      montarAdmin();
      abrirGestion();

      botonConAria('la categoría Papeleria').click();
      componente.motivo.set('Motivo válido en cliente');
      fixture.detectChanges();
      boton('Confirmar').click();

      httpMock.expectOne(rutaEstadoCategoria(1)).flush(
        { detail: 'El motivo es obligatorio para cambiar el estado.' },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
      fixture.detectChanges();

      const alerta = seccionGestion()!.querySelector('[role="alert"]');
      expect(alerta?.textContent).toContain('El motivo es obligatorio');
      // Sin recargas: el fallo no toca el listado.
      httpMock.expectNone(RUTA_GESTION);
    });

    it('409 de precondición se muestra con el mensaje del servidor', () => {
      montarAdmin();
      abrirGestion();

      botonConAria('la categoría Papeleria').click();
      componente.motivo.set('Se retira la categoría');
      fixture.detectChanges();
      boton('Confirmar').click();

      httpMock.expectOne(rutaEstadoCategoria(1)).flush(
        { detail: 'La categoría tiene productos activos.' },
        { status: 409, statusText: 'Conflict' },
      );
      fixture.detectChanges();

      const alerta = seccionGestion()!.querySelector('[role="alert"]');
      expect(alerta?.textContent).toContain('La categoría tiene productos activos.');
      expect(seccionGestion()!.querySelector('textarea#motivo-transicion')).toBeTruthy();
    });

    it('exige motivo no vacío y de hasta 500 caracteres antes de enviar', () => {
      montarAdmin();
      abrirGestion();

      botonConAria('el producto Cuaderno linedado').click();
      fixture.detectChanges();

      // Vacío.
      boton('Confirmar').click();
      fixture.detectChanges();
      expect(seccionGestion()!.textContent).toContain('El motivo es obligatorio');
      httpMock.expectNone(rutaEstadoProducto(1));

      // Solo espacios.
      componente.motivo.set('   ');
      fixture.detectChanges();
      boton('Confirmar').click();
      fixture.detectChanges();
      expect(seccionGestion()!.textContent).toContain('El motivo es obligatorio');
      httpMock.expectNone(rutaEstadoProducto(1));

      // Más de 500.
      componente.motivo.set('x'.repeat(501));
      fixture.detectChanges();
      boton('Confirmar').click();
      fixture.detectChanges();
      expect(seccionGestion()!.textContent).toContain('500 caracteres');
      httpMock.expectNone(rutaEstadoProducto(1));
    });

    it('envía la transición de producto con motivo y recarga ambos listados', () => {
      montarAdmin();
      abrirGestion();

      botonConAria('el producto Cuaderno linedado').click();
      fixture.detectChanges();
      expect(textoSeccion()).toContain('Dar de baja «Cuaderno linedado»');

      componente.motivo.set('Producto descontinuado');
      fixture.detectChanges();
      boton('Confirmar').click();

      const peticion = httpMock.expectOne(rutaEstadoProducto(1));
      expect(peticion.request.method).toBe('PATCH');
      expect(peticion.request.body).toEqual({
        activo: false,
        motivo: 'Producto descontinuado',
      });
      peticion.flush({
        producto_id: 1,
        nombre: 'Cuaderno linedado',
        descripcion: 'Cuaderno de 100 hojas',
        unidad_medida: 'UNIDAD',
        stock_minimo: 10,
        categoria_id: 1,
        activo: false,
        categoria: null,
      });
      fixture.detectChanges();

      const estado = seccionGestion()!.querySelector('[role="status"]');
      expect(estado?.textContent).toContain('«Cuaderno linedado» ahora está inactivo');

      responderRecargas();
    });

    it('carga y presenta el historial del recurso', () => {
      montarAdmin();
      abrirGestion();

      botonConAria('el historial de la categoría Toner').click();
      fixture.detectChanges();

      const peticion = httpMock.expectOne(rutaHistorialCategoria(2));
      expect(peticion.request.method).toBe('GET');
      peticion.flush(HISTORIAL_CATEGORIA);
      fixture.detectChanges();

      const historial = fixture.nativeElement.querySelector(
        'section[aria-label="Historial del recurso"]',
      ) as HTMLElement;
      expect(historial).toBeTruthy();
      const texto = (historial.textContent ?? '').replace(/\s+/g, ' ');
      expect(texto).toContain('Historial de «Toner»');
      expect(texto).toContain('Activo → Inactivo');
      expect(texto).toContain('Ana Pérez');
      expect(texto).toContain('Tóner descontinuado por el proveedor');
      expect(texto).toContain('20/10/2026');

      // Se cierra sin dejar peticiones pendientes.
      boton('Cerrar historial').click();
      fixture.detectChanges();
      expect(
        fixture.nativeElement.querySelector(
          'section[aria-label="Historial del recurso"]',
        ),
      ).toBeNull();
    });
  });
});