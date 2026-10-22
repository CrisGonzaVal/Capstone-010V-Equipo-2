import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { URL_API } from '../../shared/config/url-api';
import { Sede } from '../../shared/interfaces';
import { SedesComponent } from './sedes.component';

/**
 * Feature 012 (T10): vista de sedes de la institución (AC-6/AC-11).
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y peticiones reales
 * del `AdministracionService` bajo `HttpTestingController`. Se verifica el
 * listado con estado activo/inactivo, el alta y edición, la desactivación con
 * confirmación (PATCH `{ activo }`), los conflictos 409 con su motivo y los
 * estados de carga/error/vacío. El componente nunca envía institución ni esquema.
 */
describe('SedesComponent', () => {
  const RUTA_SEDES = `${URL_API}/organizacion/sedes`;

  function sede(sobrescribir: Partial<Sede> = {}): Sede {
    return {
      sede_id: 1,
      nombre: 'Sede Central',
      direccion: 'Av. Siempre Viva 742',
      institucion_id: 'INSTA',
      activo: true,
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<SedesComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SedesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SedesComponent);
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

  function montar(sedes: Sede[] = [sede()]): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_SEDES).flush(sedes);
    fixture.detectChanges();
  }

  it('AC-6: lista las sedes una sola vez al inicializar', () => {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_SEDES);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([sede()]);
    fixture.detectChanges();
    httpMock.expectNone(RUTA_SEDES);
  });

  it('AC-6/AC-11: renderiza la lista con nombre, dirección y estado activo/inactivo', () => {
    montar([
      sede({ sede_id: 1, nombre: 'Sede Central', activo: true }),
      sede({ sede_id: 2, nombre: 'Bodega Norte', direccion: null, activo: false }),
    ]);
    const visible = texto();
    expect(visible).toContain('Sede Central');
    expect(visible).toContain('Activa');
    expect(visible).toContain('Bodega Norte');
    expect(visible).toContain('Inactiva');
  });

  it('AC-6: crea una sede con POST y el cuerpo mínimo (nombre + dirección)', () => {
    montar([]);
    fixture.componentInstance.formulario.patchValue({
      nombre: 'Bodega Sur',
      direccion: 'Calle 10',
    });
    fixture.detectChanges();

    boton('crear sede')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(RUTA_SEDES);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ nombre: 'Bodega Sur', direccion: 'Calle 10' });

    peticion.flush(sede({ sede_id: 3, nombre: 'Bodega Sur' }));
    fixture.detectChanges();

    expect(texto()).toContain('Bodega Sur');
    expect(texto().toLowerCase()).toContain('creada');
  });

  it('AC-6: un nombre duplicado (409) muestra el motivo del servidor y no crea fila', () => {
    montar([]);
    fixture.componentInstance.formulario.patchValue({ nombre: 'Sede Central', direccion: '' });
    fixture.detectChanges();

    boton('crear sede')?.click();
    fixture.detectChanges();

    httpMock
      .expectOne(RUTA_SEDES)
      .flush(
        { detail: 'Ya existe una sede con ese nombre en la institucion' },
        { status: 409, statusText: 'Conflict' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('Ya existe una sede con ese nombre');
    expect(texto()).toContain('Aún no hay sedes');
  });

  it('AC-6: edita una sede con PUT y el cuerpo nombre + dirección', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioEdicion.patchValue({
      nombre: 'Sede Central Renombrada',
      direccion: '',
    });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_SEDES}/1`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({
      nombre: 'Sede Central Renombrada',
      direccion: null,
    });

    peticion.flush(sede({ nombre: 'Sede Central Renombrada', direccion: null }));
    fixture.detectChanges();
    expect(texto()).toContain('Sede Central Renombrada');
    expect(texto().toLowerCase()).toContain('actualizada');
  });

  it('AC-11: desactivar exige confirmación y persiste el estado con PATCH', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    expect(texto()).toContain('¿Desactivar esta sede?');

    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_SEDES}/1/estado`);
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });

    peticion.flush({ sede_id: 1, activo: false });
    fixture.detectChanges();
    expect(texto()).toContain('Inactiva');
    expect(texto().toLowerCase()).toContain('desactivada');
  });

  it('AC-11: un 409 por dependencias muestra el motivo y conserva el estado activo', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    boton('confirmar')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${RUTA_SEDES}/1/estado`).flush(
      { detail: 'No se puede desactivar la sede: hay departamentos activos asignados a ella' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('hay departamentos activos');
    expect(texto()).toContain('Activa');
  });

  it('AC-11: reactivar una sede inactiva envía PATCH { activo: true }', () => {
    montar([sede({ activo: false })]);
    boton('reactivar')?.click();
    fixture.detectChanges();
    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_SEDES}/1/estado`);
    expect(peticion.request.body).toEqual({ activo: true });
    peticion.flush({ sede_id: 1, activo: true });
    fixture.detectChanges();
    expect(texto()).toContain('Activa');
  });

  it('AC-6: estado vacío explícito cuando no hay sedes', () => {
    montar([]);
    expect(texto()).toContain('Aún no hay sedes');
  });

  it('AC-6: informa el error del listado y permite reintentar', () => {
    fixture.detectChanges();
    httpMock
      .expectOne(RUTA_SEDES)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeTruthy();

    boton('reintentar')?.click();
    fixture.detectChanges();
    httpMock.expectOne(RUTA_SEDES).flush([sede()]);
    fixture.detectChanges();
    expect(texto()).toContain('Sede Central');
  });
});
