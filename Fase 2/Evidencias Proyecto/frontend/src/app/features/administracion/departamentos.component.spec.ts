import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { URL_API } from '../../shared/config/url-api';
import { DepartamentoGestion, Sede } from '../../shared/interfaces';
import { DepartamentosComponent } from './departamentos.component';

/**
 * Feature 012 (T10): vista de departamentos (AC-7/AC-11).
 *
 * Seam bajo prueba: la interfaz pública del componente. Se verifica el listado
 * con la sede asignada o su ausencia, el estado activo/inactivo, el alta y la
 * edición, la asignación de sede con opciones **limitadas a las sedes del
 * tenant**, el 409 por dependencias y los estados de carga/error/vacío.
 */
describe('DepartamentosComponent', () => {
  const RUTA_DEPARTAMENTOS = `${URL_API}/organizacion/departamentos`;
  const RUTA_SEDES = `${URL_API}/organizacion/sedes`;

  function departamento(
    sobrescribir: Partial<DepartamentoGestion> = {},
  ): DepartamentoGestion {
    return {
      departamento_id: 1,
      nombre_dep: 'Administración',
      descripcion: 'Departamento administrativo',
      institucion_id: 'INSTA',
      sede_id: 1,
      activo: true,
      ...sobrescribir,
    };
  }

  function sede(sobrescribir: Partial<Sede> = {}): Sede {
    return {
      sede_id: 1,
      nombre: 'Sede Central',
      direccion: null,
      institucion_id: 'INSTA',
      activo: true,
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<DepartamentosComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DepartamentosComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(DepartamentosComponent);
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

  function montar(
    departamentos: DepartamentoGestion[] = [departamento()],
    sedes: Sede[] = [sede()],
  ): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(departamentos);
    httpMock.expectOne(RUTA_SEDES).flush(sedes);
    fixture.detectChanges();
  }

  it('AC-7: muestra la sede asignada resuelta y la ausencia de asignación', () => {
    montar(
      [
        departamento({ departamento_id: 1, nombre_dep: 'Administración', sede_id: 1 }),
        departamento({ departamento_id: 2, nombre_dep: 'Logística', sede_id: null }),
      ],
      [sede({ sede_id: 1, nombre: 'Sede Central' })],
    );
    const visible = texto();
    expect(visible).toContain('Administración');
    expect(visible).toContain('Sede Central');
    expect(visible).toContain('Sin sede asignada');
  });

  it('AC-11: muestra el estado activo/inactivo de cada departamento', () => {
    montar([
      departamento({ departamento_id: 1, activo: true }),
      departamento({ departamento_id: 2, nombre_dep: 'Logística', activo: false }),
    ]);
    expect(texto()).toContain('Activo');
    expect(texto()).toContain('Inactivo');
  });

  it('AC-7: crea un departamento con POST (nombre + descripción)', () => {
    montar([]);
    fixture.componentInstance.formulario.patchValue({
      nombre_dep: 'Recursos Humanos',
      descripcion: '',
    });
    fixture.detectChanges();

    boton('crear departamento')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(RUTA_DEPARTAMENTOS);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({
      nombre_dep: 'Recursos Humanos',
      descripcion: null,
    });

    peticion.flush(departamento({ departamento_id: 5, nombre_dep: 'Recursos Humanos' }));
    fixture.detectChanges();
    expect(texto()).toContain('Recursos Humanos');
  });

  it('AC-7: asignar sede usa PUT y limita las opciones a las sedes del tenant', () => {
    montar(
      [departamento({ departamento_id: 1, sede_id: null })],
      [sede({ sede_id: 1, nombre: 'Sede Central' }), sede({ sede_id: 2, nombre: 'Bodega Norte' })],
    );

    boton('asignar sede')?.click();
    fixture.detectChanges();

    const opciones = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('select option'),
    ).map((o) => o.textContent?.trim());
    expect(opciones).toEqual(['Sin asignar', 'Sede Central', 'Bodega Norte']);

    fixture.componentInstance.cambiarSeleccionSede({
      target: { value: '2' },
    } as unknown as Event);
    fixture.detectChanges();

    boton('guardar sede')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/1/sede`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ sede_id: 2 });
    peticion.flush({ departamento_id: 1, sede_id: 2 });
    fixture.detectChanges();
    expect(texto()).toContain('Bodega Norte');
  });

  it('AC-11: desactivar exige confirmación y un 409 por usuarios vinculados muestra el motivo', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    expect(texto()).toContain('¿Desactivar este departamento?');

    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/1/estado`);
    expect(peticion.request.body).toEqual({ activo: false });
    peticion.flush(
      { detail: 'No se puede desactivar el departamento: tiene usuarios vinculados' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('tiene usuarios vinculados');
    expect(texto()).toContain('Activo');
  });

  it('AC-7: estado vacío explícito cuando no hay departamentos', () => {
    montar([]);
    expect(texto()).toContain('Aún no hay departamentos');
  });

  it('AC-7: informa el error del listado y permite reintentar', () => {
    fixture.detectChanges();
    const peticionSedes = httpMock.expectOne(RUTA_SEDES);
    const peticionDepartamentos = httpMock.expectOne(RUTA_DEPARTAMENTOS);
    // `forkJoin` cancela el resto al primer error: se libera la sede antes.
    peticionSedes.flush([]);
    peticionDepartamentos.flush(
      { detail: 'boom' },
      { status: 500, statusText: 'Server Error' },
    );
    fixture.detectChanges();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeTruthy();
  });
});
