import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { DashboardSaaS, InstitucionMetricas } from '../../shared/interfaces';
import { DashboardSaasComponent } from './dashboard-saas.component';

/**
 * Feature 017 (T9): dashboard técnico del Superadmin (D-8/AC-13/AC-14).
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y petición real del
 * `ControlService` bajo `HttpTestingController`. Se verifica la taxonomía única
 * (operativo / no enrutable / no disponible), que un conteo no disponible nunca
 * se presenta como cero, los agregados conocidos/no disponibles y los estados de
 * carga, error y vacío.
 */
describe('DashboardSaasComponent', () => {
  const RUTA_DASHBOARD = `${URL_API}/control/dashboard`;

  function operativa(
    sobrescribir: Partial<InstitucionMetricas> = {},
  ): InstitucionMetricas {
    return {
      institucion_id: 'INSTA',
      nombre: 'Instituto Alfa',
      activo: true,
      estado_tecnico: 'operativo',
      detalle_tecnico: null,
      version_objetivo: '013.1',
      version_persistida: '013.1',
      sedes: 3,
      departamentos: 2,
      administradores_activos: 1,
      administradores_inactivos: 1,
      usuarios_por_rol: { Bodeguero: 2, Solicitante: 5 },
      ...sobrescribir,
    };
  }

  function crearDashboard(sobrescribir: Partial<DashboardSaaS> = {}): DashboardSaaS {
    return {
      total_instituciones: 3,
      total_instituciones_activas: 2,
      total_administradores_activos: 1,
      total_administradores_inactivos: 1,
      usuarios_por_rol: { Bodeguero: 2, Solicitante: 5 },
      conteos_conocidos: 1,
      conteos_no_disponibles: 2,
      instituciones: [
        operativa(),
        operativa({
          institucion_id: 'INSTB',
          nombre: 'Instituto Beta',
          activo: true,
          estado_tecnico: 'no disponible',
          detalle_tecnico: 'version_incompatible',
          version_persistida: null,
          sedes: null,
          departamentos: null,
          administradores_activos: null,
          administradores_inactivos: null,
          usuarios_por_rol: null,
        }),
        operativa({
          institucion_id: 'INSTC',
          nombre: 'Instituto Gamma',
          activo: false,
          estado_tecnico: 'no enrutable',
          detalle_tecnico: 'institucion_inactiva',
          version_persistida: null,
          sedes: null,
          departamentos: null,
          administradores_activos: null,
          administradores_inactivos: null,
          usuarios_por_rol: null,
        }),
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

  it('AC-13: pide el dashboard SaaS una sola vez al inicializar', () => {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_DASHBOARD);
    expect(peticion.request.method).toBe('GET');
    peticion.flush(crearDashboard());
    fixture.detectChanges();
    httpMock.expectNone(RUTA_DASHBOARD);
  });

  it('AC-13: durante la carga identifica el estado pendiente', () => {
    fixture.detectChanges();
    const indicador = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="status"]',
    );
    expect(indicador).withContext('indicador de carga').toBeTruthy();
    httpMock.expectOne(RUTA_DASHBOARD).flush(crearDashboard());
    fixture.detectChanges();
  });

  it('AC-13: muestra el total de instituciones y los agregados conocidos/no disponibles', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('Instituciones');
    expect(visible).toContain('Con conteos conocidos');
    expect(visible).toContain('Sin conteos disponibles');
    expect(visible).toContain('Administradores activos');
    expect(visible).toContain('Administradores inactivos');
    expect(fixture.componentInstance.conocidos()).toBe(1);
    expect(fixture.componentInstance.noDisponibles()).toBe(2);
  });

  it('AC-14: distingue las tres clases técnicas y solo la operativa muestra conteos', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('Operativo');
    expect(visible).toContain('No enrutable');
    expect(visible).toContain('No disponible');
    expect(visible).toContain('Institución inactiva');
    expect(visible).toContain('Versión incompatible');

    const filaOperativa = fixture.componentInstance
      .instituciones()
      .find((i) => i.institucion_id === 'INSTA');
    expect(fixture.componentInstance.esOperativa(filaOperativa!)).toBe(true);

    const filaNoDisponible = fixture.componentInstance
      .instituciones()
      .find((i) => i.institucion_id === 'INSTB');
    expect(fixture.componentInstance.esOperativa(filaNoDisponible!)).toBe(false);
  });

  it('AC-14: un conteo no disponible se muestra como «No disponible», nunca como cero', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('No disponible');
    expect(fixture.componentInstance.valor(null)).toBe('No disponible');
    expect(fixture.componentInstance.valor(0)).toBe('0');
  });

  it('AC-13: lista las instituciones con atribución inequívoca (nombre + id)', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('INSTA');
    expect(visible).toContain('INSTB');
    expect(visible).toContain('Instituto Gamma');
    expect(visible).toContain('Bodeguero');
    expect(visible).toContain('Solicitante');
  });

  it('AC-13: no expone datos personales ni de negocio', () => {
    montar();
    const visible = texto().toLowerCase();
    expect(visible).not.toContain('@');
    expect(visible).not.toContain('ticket');
  });

  it('AC-13: ante fallo informa un error recuperable y permite reintentar', () => {
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

  it('AC-13: sin instituciones muestra un vacío explícito', () => {
    montar({
      total_instituciones: 0,
      total_instituciones_activas: 0,
      total_administradores_activos: 0,
      total_administradores_inactivos: 0,
      usuarios_por_rol: {},
      conteos_conocidos: 0,
      conteos_no_disponibles: 0,
      instituciones: [],
    });
    expect(texto().toLowerCase()).toContain('no hay instituciones');
  });
});
