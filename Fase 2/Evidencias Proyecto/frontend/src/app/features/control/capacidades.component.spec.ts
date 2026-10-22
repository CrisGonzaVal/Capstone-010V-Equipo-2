import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { CapacidadRespuesta, InstitucionControl } from '../../shared/interfaces';
import { CapacidadesComponent } from './capacidades.component';

/**
 * Feature 012 (T9): capacidades funcionales por institución (AC-5).
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y peticiones reales
 * del `ControlService` bajo `HttpTestingController`. Se verifica la carga de las
 * seis capacidades del conjunto cerrado con su estado persistido, el cambio de
 * estado por `PUT .../capacidades/{funcion}` con la respuesta del servidor, y los
 * estados de carga/error. El ámbito lo fija la ruta (`institucionId`), no el
 * cliente.
 */
describe('CapacidadesComponent', () => {
  const INSTITUCION_ID = 'INSTA';
  const RUTA_INSTITUCION = `${URL_API}/control/instituciones/${INSTITUCION_ID}`;
  const RUTA_CAPACIDADES = `${URL_API}/control/instituciones/${INSTITUCION_ID}/capacidades`;

  const INSTITUCION: InstitucionControl = {
    institucion_id: INSTITUCION_ID,
    nombre: 'Instituto Alfa',
    rut: '76.111.222-3',
    direccion: 'Av. Siempre Viva 742',
    activo: true,
    nombre_esquema: 'tenant_insta_ab12cd34',
  };

  const SEIS_CAPACIDADES: CapacidadRespuesta[] = [
    { funcion: 'catalogo', habilitada: true },
    { funcion: 'inventario', habilitada: true },
    { funcion: 'tickets', habilitada: true },
    { funcion: 'kanban', habilitada: false },
    { funcion: 'dashboard', habilitada: true },
    { funcion: 'gestion_organizacional', habilitada: false },
  ];

  let fixture: ComponentFixture<CapacidadesComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CapacidadesComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: convertToParamMap({ institucionId: INSTITUCION_ID }) },
          },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CapacidadesComponent);
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function boton(etiqueta: string): HTMLButtonElement | undefined {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((b) => new RegExp(etiqueta, 'i').test(b.textContent ?? ''));
  }

  /** Resuelve la carga inicial (institución + capacidades) y estabiliza. */
  function montar(
    institucion: InstitucionControl = INSTITUCION,
    capacidades: CapacidadRespuesta[] = SEIS_CAPACIDADES,
  ): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_INSTITUCION).flush(institucion);
    httpMock.expectOne(RUTA_CAPACIDADES).flush(capacidades);
    fixture.detectChanges();
  }

  it('AC-5: durante la carga identifica el estado pendiente', () => {
    fixture.detectChanges();
    const indicador = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="status"]',
    );
    expect(indicador).withContext('indicador de carga').toBeTruthy();

    httpMock.expectOne(RUTA_INSTITUCION).flush(INSTITUCION);
    httpMock.expectOne(RUTA_CAPACIDADES).flush(SEIS_CAPACIDADES);
    fixture.detectChanges();
  });

  it('AC-5: carga y presenta las seis capacidades con su estado persistido', () => {
    montar();

    const visible = texto();
    expect(visible).toContain('Instituto Alfa');
    expect(visible).toContain('INSTA');

    const etiquetas = [
      'Catálogo',
      'Inventario',
      'Tickets',
      'Tablero',
      'Dashboard',
      'Gestión organizacional',
    ];
    for (const etiqueta of etiquetas) {
      expect(visible).withContext(etiqueta).toContain(etiqueta);
    }

    // Estado mixto: cuatro habilitadas (dos en deshabilitado: kanban y gestión).
    expect(visible).toContain('Habilitada');
    expect(visible).toContain('Deshabilitada');
  });

  it('AC-5: deshabilita una capacidad con PUT y refleja la respuesta del servidor', () => {
    montar();
    // El primer botón «Deshabilitar» corresponde a la primera capacidad habilitada.
    boton('deshabilitar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_CAPACIDADES}/catalogo`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ habilitada: false });

    peticion.flush({ funcion: 'catalogo', habilitada: false });
    fixture.detectChanges();

    expect(texto().toLowerCase()).toContain('deshabilitada');
    expect(fixture.componentInstance.capacidades()).toEqual([
      { funcion: 'catalogo', habilitada: false },
      { funcion: 'inventario', habilitada: true },
      { funcion: 'tickets', habilitada: true },
      { funcion: 'kanban', habilitada: false },
      { funcion: 'dashboard', habilitada: true },
      { funcion: 'gestion_organizacional', habilitada: false },
    ]);
  });

  it('AC-5: habilita una capacidad deshabilitada con PUT { habilitada: true }', () => {
    montar();
    // Aísla la capacidad `kanban` (deshabilitada) desde el servicio.
    fixture.componentInstance.cambiar({ funcion: 'kanban', habilitada: false });
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_CAPACIDADES}/kanban`);
    expect(peticion.request.body).toEqual({ habilitada: true });
    peticion.flush({ funcion: 'kanban', habilitada: true });
    fixture.detectChanges();

    expect(
      fixture.componentInstance
        .capacidades()
        .find((c) => c.funcion === 'kanban')?.habilitada,
    ).toBe(true);
    expect(texto().toLowerCase()).toContain('habilitada');
  });

  it('AC-5: ante fallo de carga informa un error y permite reintentar', () => {
    fixture.detectChanges();
    // Se resuelve primero la lectura de capacidades (éxito) y luego el fallo de la
    // institución: `forkJoin` falla completo al primer error, sin agregado parcial.
    httpMock.expectOne(RUTA_CAPACIDADES).flush([]);
    httpMock
      .expectOne(RUTA_INSTITUCION)
      .flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).withContext('alerta de error').toBeTruthy();

    boton('reintentar')?.click();
    fixture.detectChanges();
    httpMock.expectOne(RUTA_INSTITUCION).flush(INSTITUCION);
    httpMock.expectOne(RUTA_CAPACIDADES).flush(SEIS_CAPACIDADES);
    fixture.detectChanges();

    expect(texto()).toContain('Catálogo');
  });

  it('AC-5: un fallo al cambiar una capacidad muestra el error sin mutar el estado local', () => {
    montar();
    fixture.componentInstance.cambiar({ funcion: 'tickets', habilitada: true });
    fixture.detectChanges();

    httpMock
      .expectOne(`${RUTA_CAPACIDADES}/tickets`)
      .flush({ detail: 'No autorizado' }, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('No autorizado');
    expect(
      fixture.componentInstance
        .capacidades()
        .find((c) => c.funcion === 'tickets')?.habilitada,
    ).toBe(true);
  });
});
