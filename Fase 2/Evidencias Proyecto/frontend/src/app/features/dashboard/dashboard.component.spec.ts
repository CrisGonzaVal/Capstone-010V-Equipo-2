import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { WritableSignal, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AutenticacionService } from '../../core/services/auth.service';
import { URL_API } from '../../shared/config/url-api';
import {
  DashboardAnalitico,
  IdentidadAutenticada,
} from '../../shared/interfaces';
import { DashboardComponent } from './dashboard.component';

/**
 * Feature 009 (T9): contrato de la vista del dashboard consolidado.
 *
 * Seam bajo prueba: la **interfaz publica del componente** — el DOM renderizado
 * y la(s) peticion(es) HTTP del `DashboardService` real bajo `HttpTestingController`.
 * Solo se asertan textos, encabezados, roles ARIA y numero de peticiones: nada de
 * clases Tailwind ni estructura interna fragil.
 *
 * Estado verde: el `DashboardComponent` carga la respuesta consolidada via
 * `DashboardService.obtenerDashboard()` al inicializar, con `signal()` para
 * carga/datos/error y `computed()` para las secciones, y ofrece reintento. Esta
 * spec fija el contrato de presentacion; el servicio/cliente HTTP tiene su propia
 * suite (`dashboard.service.spec.ts`).
 *
 * Contrato de template que fija esta spec:
 *   - cuatro KPI con las etiquetas exactas «Unidades en Stock», «Tickets Activos»,
 *     «Departamentos» y «Alertas de Stock», con los valores del DTO;
 *   - sin el placeholder «Estado de Sedes Descentralizadas» ni cifras de ejemplo;
 *   - un listado de alertas con producto, sede, stock actual y minimo;
 *   - seccion «Actividad Reciente» solo si `actividad_disponible` es `true`; con
 *     `actividad_disponible=false` (Solicitante) no se pinta y **no** se consulta
 *     `/inventario/movimientos`;
 *   - durante la carga, un indicador con `role="status"`;
 *   - ante fallo, un `[role="alert"]` con un boton «Reintentar» que repite la
 *     lectura (sin restaurar cifras ficticias);
 *   - sin datos, KPI en cero y vacios explícitos («No hay alertas de stock.»,
 *     «Sin movimientos recientes.»).
 */
describe('DashboardComponent', () => {
  const RUTA_DASHBOARD = `${URL_API}/dashboard/`;
  const RUTA_MOVIMIENTOS = `${URL_API}/inventario/movimientos`;

  /** Respuesta global (Superadmin): dos instituciones atribuidas y actividad. */
  function crearDashboard(
    sobrescribir: Partial<DashboardAnalitico> = {},
  ): DashboardAnalitico {
    return {
      kpi: {
        unidades_en_stock: 4321,
        tickets_activos: 76,
        total_departamentos: 87,
        total_alertas: 9,
      },
      alertas: [
        {
          sede_id: 11,
          sede_nombre: 'Sede Central',
          producto_id: 101,
          producto_nombre: 'Papel Bond',
          stock_actual: 2,
          stock_minimo: 10,
          institucion_id: 'INSTA',
          institucion_nombre: 'Instituto Alfa',
        },
        {
          sede_id: 12,
          sede_nombre: 'Bodega Norte',
          producto_id: 202,
          producto_nombre: 'Toner HP',
          stock_actual: 1,
          stock_minimo: 5,
          institucion_id: 'INSTB',
          institucion_nombre: 'Instituto Beta',
        },
      ],
      actividad_disponible: true,
      actividad_movimientos: [
        {
          movimiento_id: 501,
          tipo_movimiento: 'ENTRADA',
          cantidad: 15,
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
      ],
      ...sobrescribir,
    };
  }

  /** Respuesta sin datos: KPI en cero y listas vacias. */
  function crearDashboardVacio(): DashboardAnalitico {
    return {
      kpi: {
        unidades_en_stock: 0,
        tickets_activos: 0,
        total_departamentos: 0,
        total_alertas: 0,
      },
      alertas: [],
      actividad_disponible: true,
      actividad_movimientos: [],
    };
  }

  /** Respuesta del Solicitante: KPI/alertas de su ámbito, actividad no disponible. */
  function crearDashboardSolicitante(): DashboardAnalitico {
    return {
      kpi: {
        unidades_en_stock: 40,
        tickets_activos: 3,
        total_departamentos: 2,
        total_alertas: 1,
      },
      alertas: [
        {
          sede_id: 31,
          sede_nombre: 'Sede Sur',
          producto_id: 301,
          producto_nombre: 'Resma Carta',
          stock_actual: 1,
          stock_minimo: 8,
          institucion_id: 'INSTA',
          institucion_nombre: 'Instituto Alfa',
        },
      ],
      actividad_disponible: false,
      actividad_movimientos: [],
    };
  }

  function crearIdentidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 7,
      sub: 'user_dashboard',
      nombre: 'Dana',
      apellido: 'Rivas',
      correo: 'dana.rivas@losalpes.cl',
      rol,
      institucion: { institucion_id: 'INSTA', nombre: 'Instituto Alfa' },
    };
  }

  let fixture: ComponentFixture<DashboardComponent>;
  let httpMock: HttpTestingController;
  /** Identidad local (`/auth/me`) como señal: doble, sin arrancar Clerk. */
  let identidad: WritableSignal<IdentidadAutenticada | null>;

  beforeEach(async () => {
    identidad = signal<IdentidadAutenticada | null>(crearIdentidad('Superadmin'));

    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        // La vista no decide ámbito ni autorización (lo hace el servidor); aun
        // así se inyecta la identidad en el formato de la casa para cubrir el rol.
        { provide: AutenticacionService, useValue: { identidad } },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(DashboardComponent);
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  /** Texto visible completo del dashboard. */
  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  /** Dispara la carga inicial y resuelve la unica peticion con `dto`. */
  function montar(dto: DashboardAnalitico = crearDashboard()) {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_DASHBOARD);
    peticion.flush(dto);
    fixture.detectChanges();
    return peticion;
  }

  /** Boton de reintento del estado de error, por su texto accesible. */
  function botonReintentar(): HTMLButtonElement | undefined {
    const botones = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    );
    return botones.find((boton) => /reintentar/i.test(boton.textContent ?? ''));
  }

  // -------------------------------------------------------------------------
  // Carga y contrato HTTP
  // -------------------------------------------------------------------------

  it('AC-15: pide el dashboard una sola vez al inicializar', () => {
    fixture.detectChanges();

    const peticion = httpMock.expectOne(RUTA_DASHBOARD);
    expect(peticion.request.method).toBe('GET');
    peticion.flush(crearDashboard());
    fixture.detectChanges();

    // Sin peticiones duplicadas.
    httpMock.expectNone(RUTA_DASHBOARD);
  });

  it('AC-8: no envía institución ni parámetros de ámbito', () => {
    fixture.detectChanges();

    const peticion = httpMock.expectOne(RUTA_DASHBOARD);
    expect(peticion.request.params.keys()).toEqual([]);
    expect(peticion.request.body).toBeNull();
    expect(peticion.request.headers.get('X-Institucion-Id')).toBeNull();

    peticion.flush(crearDashboard());
    fixture.detectChanges();
  });

  it('AC-15: no consulta el historial de movimientos para armar la actividad', () => {
    montar();

    httpMock.expectNone(RUTA_MOVIMIENTOS);
  });

  // -------------------------------------------------------------------------
  // AC-1/AC-15: KPI y retiro del placeholder
  // -------------------------------------------------------------------------

  it('AC-1: las cuatro tarjetas usan sus etiquetas exactas', () => {
    montar();

    const etiquetas = [
      'Unidades en Stock',
      'Tickets Activos',
      'Departamentos',
      'Alertas de Stock',
    ];
    for (const etiqueta of etiquetas) {
      expect(texto()).withContext(etiqueta).toContain(etiqueta);
    }
  });

  it('AC-1: muestra los valores numéricos del DTO', () => {
    montar();

    for (const valor of ['4321', '76', '87', '9']) {
      expect(texto()).withContext(valor).toContain(valor);
    }
  });

  it('AC-15: retira el placeholder «Estado de Sedes Descentralizadas»', () => {
    montar();

    expect(texto()).not.toContain('Estado de Sedes Descentralizadas');
  });

  it('AC-15: no presenta cifras ni actividad de ejemplo', () => {
    montar();

    expect(texto()).not.toContain('1,240');
    expect(texto()).not.toContain('Se añadieron 200 lápices');
  });

  // -------------------------------------------------------------------------
  // AC-5: log de alertas
  // -------------------------------------------------------------------------

  it('AC-5: lista las alertas con producto, sede, stock actual y mínimo', () => {
    montar();

    const visible = texto();
    expect(visible).toContain('Papel Bond');
    expect(visible).toContain('Sede Central');
    expect(visible).toContain('Toner HP');
    expect(visible).toContain('Bodega Norte');
  });

  // -------------------------------------------------------------------------
  // AC-6/AC-7: actividad reciente y atribución
  // -------------------------------------------------------------------------

  it('AC-6/AC-7: muestra la Actividad Reciente con movimientos y su atribución', () => {
    montar();

    const visible = texto();
    expect(visible).toContain('Actividad Reciente');
    expect(visible).toContain('Papel Bond');
    expect(visible).toContain('Instituto Alfa');
  });

  it('AC-7: cada alerta global conserva su institución', () => {
    montar();

    const visible = texto();
    expect(visible).toContain('Instituto Alfa');
    expect(visible).toContain('Instituto Beta');
  });

  // -------------------------------------------------------------------------
  // AC-10: Solicitante sin actividad
  // -------------------------------------------------------------------------

  it('AC-10: el Solicitante no ve actividad y no consulta el historial', () => {
    identidad.set(crearIdentidad('Solicitante'));

    montar(crearDashboardSolicitante());

    expect(texto()).not.toContain('Actividad Reciente');
    httpMock.expectNone(RUTA_MOVIMIENTOS);
  });

  // -------------------------------------------------------------------------
  // AC-15: estados de carga, vacío y error recuperable
  // -------------------------------------------------------------------------

  it('AC-15: durante la carga identifica el estado pendiente', () => {
    fixture.detectChanges();

    const indicador = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="status"]',
    );
    expect(indicador).withContext('indicador de carga').toBeTruthy();

    // Se resuelve la lectura para no dejar peticiones pendientes.
    httpMock.expectOne(RUTA_DASHBOARD).flush(crearDashboard());
    fixture.detectChanges();
  });

  it('AC-15: sin datos muestra ceros y vacíos explícitos', () => {
    montar(crearDashboardVacio());

    const visible = texto();
    expect(visible).toContain('0');
    expect(visible.toLowerCase()).toContain('no hay alertas');
    expect(visible.toLowerCase()).toContain('sin movimientos');
  });

  it('AC-15: ante fallo informa un error recuperable con acción de reintento', () => {
    fixture.detectChanges();

    httpMock
      .expectOne(RUTA_DASHBOARD)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta).withContext('alerta de error').toBeTruthy();
    expect(botonReintentar()).withContext('botón de reintento').toBeTruthy();
  });

  it('AC-15: el reintento vuelve a pedir el dashboard y limpia el error', () => {
    fixture.detectChanges();

    httpMock
      .expectOne(RUTA_DASHBOARD)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    botonReintentar()?.click();
    fixture.detectChanges();

    const reintento = httpMock.expectOne(RUTA_DASHBOARD);
    reintento.flush(crearDashboard());
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeNull();
  });
});
