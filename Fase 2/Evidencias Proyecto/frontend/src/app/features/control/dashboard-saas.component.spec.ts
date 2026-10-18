import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { DashboardSaaS } from '../../shared/interfaces';
import { DashboardSaasComponent } from './dashboard-saas.component';

/**
 * Feature 012 (T9): vista del dashboard SaaS del Superadmin (AC-4).
 *
 * Seam bajo prueba: la interfaz pública del componente — el DOM renderizado y la
 * petición real del `ControlService` bajo `HttpTestingController`. Se verifica el
 * KPI de instituciones activas, la tabla con atribución inequívoca (nombre + id),
 * el estado activo/inactivo y las métricas atribuidas; una institución inactiva
 * se muestra sin métricas. También estados de carga, error recuperable y vacío.
 */
describe('DashboardSaasComponent', () => {
  const RUTA_DASHBOARD = `${URL_API}/control/dashboard`;

  function crearDashboard(sobrescribir: Partial<DashboardSaaS> = {}): DashboardSaaS {
    return {
      total_instituciones_activas: 2,
      instituciones: [
        {
          institucion_id: 'INSTA',
          nombre: 'Instituto Alfa',
          activo: true,
          sedes: 3,
          usuarios_por_rol: { Administrador: 1, Bodeguero: 2, Solicitante: 5 },
        },
        {
          institucion_id: 'INSTB',
          nombre: 'Instituto Alfa',
          activo: true,
          sedes: 1,
          usuarios_por_rol: { Administrador: 1 },
        },
        {
          institucion_id: 'INSTC',
          nombre: 'Instituto Gamma',
          activo: false,
          sedes: null,
          usuarios_por_rol: null,
        },
      ],
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<DashboardSaasComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DashboardSaasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(DashboardSaasComponent);
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function montar(dto: DashboardSaaS = crearDashboard()): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_DASHBOARD).flush(dto);
    fixture.detectChanges();
  }

  it('AC-4: pide el dashboard SaaS una sola vez al inicializar', () => {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_DASHBOARD);
    expect(peticion.request.method).toBe('GET');
    peticion.flush(crearDashboard());
    fixture.detectChanges();
    httpMock.expectNone(RUTA_DASHBOARD);
  });

  it('AC-4: durante la carga identifica el estado pendiente', () => {
    fixture.detectChanges();
    const indicador = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="status"]',
    );
    expect(indicador).withContext('indicador de carga').toBeTruthy();
    httpMock.expectOne(RUTA_DASHBOARD).flush(crearDashboard());
    fixture.detectChanges();
  });

  it('AC-4: muestra el KPI de instituciones activas del DTO', () => {
    montar();
    expect(texto()).toContain('Instituciones activas');
    expect(texto()).toContain('2');
  });

  it('AC-4: lista las instituciones con atribución inequívoca (nombre + id)', () => {
    montar();
    const visible = texto();
    // Dos instituciones homónimas se distinguen por su identificador.
    expect(visible).toContain('INSTA');
    expect(visible).toContain('INSTB');
    expect(visible).toContain('Instituto Gamma');
    expect(visible).toContain('Administrador');
    expect(visible).toContain('Solicitante');
  });

  it('AC-4: una institución inactiva se identifica y no recibe métricas actuales', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('Inactiva');
    expect(visible.toLowerCase()).toContain('sin métricas');
  });

  it('AC-4: ante fallo informa un error recuperable y permite reintentar', () => {
    fixture.detectChanges();
    httpMock
      .expectOne(RUTA_DASHBOARD)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta).withContext('alerta de error').toBeTruthy();

    const boton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((b) => /reintentar/i.test(b.textContent ?? ''));
    expect(boton).withContext('botón de reintento').toBeTruthy();

    boton?.click();
    fixture.detectChanges();
    httpMock.expectOne(RUTA_DASHBOARD).flush(crearDashboard());
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeNull();
  });

  it('AC-4: sin instituciones muestra un vacío explícito', () => {
    montar({ total_instituciones_activas: 0, instituciones: [] });
    expect(texto().toLowerCase()).toContain('no hay instituciones');
  });
});
