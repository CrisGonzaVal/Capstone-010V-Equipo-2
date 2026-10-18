import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { InstitucionControl } from '../../shared/interfaces';
import { InstitucionesComponent } from './instituciones.component';

/**
 * Feature 012 (T9): gestión institucional del portal `/control` (AC-1/AC-2).
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y peticiones reales
 * del `ControlService` bajo `HttpTestingController`. Se verifica el listado con
 * estado activo/inactivo, la edición de atributos canónicos (PUT sin estado), la
 * desactivación/reactivación con confirmación (PATCH { activo }), la navegación a
 * capacidades y los estados de carga/error/éxito.
 */
describe('InstitucionesComponent', () => {
  const RUTA_LISTA = `${URL_API}/control/instituciones/`;

  function activa(sobrescribir: Partial<InstitucionControl> = {}): InstitucionControl {
    return {
      institucion_id: 'INSTA',
      nombre: 'Instituto Alfa',
      rut: '76.111.222-3',
      direccion: 'Av. Siempre Viva 742',
      activo: true,
      nombre_esquema: 'tenant_insta_ab12cd34',
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<InstitucionesComponent>;
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InstitucionesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    fixture = TestBed.createComponent(InstitucionesComponent);
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

  function montar(instituciones: InstitucionControl[] = [activa()]): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_LISTA).flush(instituciones);
    fixture.detectChanges();
  }

  it('AC-1: lista las instituciones una sola vez al inicializar', () => {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_LISTA);
    expect(peticion.request.method).toBe('GET');
    peticion.flush([activa()]);
    fixture.detectChanges();
    httpMock.expectNone(RUTA_LISTA);
  });

  it('AC-1: renderiza la lista con nombre, id, estado y atributos canónicos', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('Instituto Alfa');
    expect(visible).toContain('INSTA');
    expect(visible).toContain('Activa');
    expect(visible).toContain('76.111.222-3');
    expect(visible).toContain('Av. Siempre Viva 742');
  });

  it('AC-2: una institución inactiva se muestra como tal y ofrece Reactivar', () => {
    montar([activa({ activo: false })]);
    expect(texto()).toContain('Inactiva');
    expect(boton('reactivar')).withContext('acción reactivar').toBeTruthy();
    expect(boton('desactivar')).withContext('sin acción desactivar').toBeFalsy();
  });

  it('AC-1: edita los atributos canónicos con PUT sin enviar estado ni esquema', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formulario.patchValue({
      nombre: 'Instituto Alfa Renombrado',
      rut: '',
      direccion: 'Calle Nueva 100',
    });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/control/instituciones/INSTA`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({
      nombre: 'Instituto Alfa Renombrado',
      rut: null,
      direccion: 'Calle Nueva 100',
    });

    peticion.flush(
      activa({ nombre: 'Instituto Alfa Renombrado', direccion: 'Calle Nueva 100' }),
    );
    fixture.detectChanges();

    expect(texto()).toContain('Instituto Alfa Renombrado');
    expect(texto().toLowerCase()).toContain('actualizada');
  });

  it('AC-2: desactivar exige confirmación y persiste el estado con PATCH', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    // Todavía no hay mutación: solo la confirmación.
    expect(texto()).toContain('¿Desactivar esta institución?');

    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(
      `${URL_API}/control/instituciones/INSTA/estado`,
    );
    expect(peticion.request.method).toBe('PATCH');
    expect(peticion.request.body).toEqual({ activo: false });

    peticion.flush({ institucion_id: 'INSTA', activo: false });
    fixture.detectChanges();

    expect(texto()).toContain('Inactiva');
    expect(texto().toLowerCase()).toContain('desactivada');
  });

  it('AC-2: reactivar persiste el estado con PATCH { activo: true }', () => {
    montar([activa({ activo: false })]);
    boton('reactivar')?.click();
    fixture.detectChanges();

    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(
      `${URL_API}/control/instituciones/INSTA/estado`,
    );
    expect(peticion.request.body).toEqual({ activo: true });

    peticion.flush({ institucion_id: 'INSTA', activo: true });
    fixture.detectChanges();

    expect(texto()).toContain('Activa');
    expect(texto().toLowerCase()).toContain('reactivada');
  });

  it('AC-2: cancelar la confirmación no dispara ninguna mutación', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    boton('cancelar')?.click();
    fixture.detectChanges();

    httpMock.expectNone(`${URL_API}/control/instituciones/INSTA/estado`);
  });

  it('AC-5: navega a la vista de capacidades de la institución', () => {
    const navegar = spyOn(router, 'navigate').and.resolveTo(true);
    montar();

    boton('capacidades')?.click();

    expect(navegar).toHaveBeenCalledWith([
      '/control/instituciones',
      'INSTA',
      'capacidades',
    ]);
  });

  it('AC-1: informa el error del listado y permite reintentar', () => {
    fixture.detectChanges();
    httpMock
      .expectOne(RUTA_LISTA)
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).withContext('alerta de error').toBeTruthy();

    boton('reintentar')?.click();
    fixture.detectChanges();
    httpMock.expectOne(RUTA_LISTA).flush([activa()]);
    fixture.detectChanges();

    expect(texto()).toContain('Instituto Alfa');
  });

  it('AC-2: un fallo en la mutación muestra el mensaje y conserva la lista', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    boton('confirmar')?.click();
    fixture.detectChanges();

    httpMock
      .expectOne(`${URL_API}/control/instituciones/INSTA/estado`)
      .flush({ detail: 'No se puede desactivar' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('No se puede desactivar');
    expect(texto()).toContain('Instituto Alfa');
  });
});
