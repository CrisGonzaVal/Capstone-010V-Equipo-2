import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';

import { URL_API } from '../../shared/config/url-api';
import { AdministradorListadoControl } from '../../shared/interfaces';
import { AdministradoresControlComponent } from './administradores-control.component';

/**
 * Feature 017 (T9): gobierno de Administradores por institución (D-10/AC-8).
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y peticiones reales
 * del `ControlService` bajo `HttpTestingController`. Se verifica el listado
 * mínimo con estado persistido, el alta con URL solo en la respuesta, el reenvío
 * con copia, la edición y baja/reactivación con motivo, el 409 del último
 * Administrador y que el cliente nunca envíe esquema ni institución fuera de la
 * ruta.
 */
describe('AdministradoresControlComponent', () => {
  const INSTITUCION_ID = 'INSTA';
  const RUTA_ADMIN = `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/`;

  function administrador(
    sobrescribir: Partial<AdministradorListadoControl> = {},
  ): AdministradorListadoControl {
    return {
      usuario_id: 7,
      nombre: 'Ada',
      apellido: 'Admin',
      correo: 'ada@example.com',
      activo: true,
      estado_invitacion: 'aceptada',
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<AdministradoresControlComponent>;
  let httpMock: HttpTestingController;
  let portapapeles: string[];

  beforeEach(async () => {
    portapapeles = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: (texto: string) => {
          portapapeles.push(texto);
          return Promise.resolve();
        },
      },
    });

    await TestBed.configureTestingModule({
      imports: [AdministradoresControlComponent],
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
    fixture = TestBed.createComponent(AdministradoresControlComponent);
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

  function montar(lista: AdministradorListadoControl[] = [administrador()]): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_ADMIN).flush(lista);
    fixture.detectChanges();
  }

  it('AC-8: pide el listado mínimo de Administradores de la institución de la ruta', () => {
    fixture.detectChanges();
    const peticion = httpMock.expectOne(RUTA_ADMIN);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.params.keys()).toEqual([]);
    peticion.flush([administrador()]);
    fixture.detectChanges();

    const visible = texto();
    expect(visible).toContain('Ada Admin');
    expect(visible).toContain('ada@example.com');
    expect(visible).toContain('Activo');
    expect(visible).toContain('Invitación: Aceptada');
  });

  it('AC-5: muestra pendiente e «inactivo» como conceptos separados y sin URL', () => {
    montar([
      administrador({ activo: false, estado_invitacion: 'pendiente' }),
    ]);
    const visible = texto();
    expect(visible).toContain('Inactivo');
    expect(visible).toContain('Invitación: Pendiente');
    expect(visible).not.toContain('http');
  });

  it('AC-5: un estado desconocido se presenta como «No disponible»', () => {
    montar([administrador({ estado_invitacion: 'legado' })]);
    expect(texto()).toContain('Invitación: No disponible');
  });

  it('AC-8: no ofrece reenvío cuando la invitación ya fue aceptada', () => {
    montar([administrador({ estado_invitacion: 'aceptada' })]);
    expect(boton('reenviar')).toBeFalsy();
  });

  it('AC-5: no ofrece reenvío cuando el estado persistido no está disponible', () => {
    montar([administrador({ estado_invitacion: 'no disponible' })]);
    expect(boton('reenviar')).toBeFalsy();
  });

  it('AC-6: reenvía una invitación pendiente y muestra la URL solo ahora', async () => {
    montar([administrador({ estado_invitacion: 'pendiente' })]);
    boton('reenviar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(
      `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7/invitacion/reenvio`,
    );
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({});
    peticion.flush({
      usuario_id: 7,
      nombre: 'Ada',
      apellido: 'Admin',
      correo: 'ada@example.com',
      departamento_id: 10,
      rol_id: 2,
      activo: true,
      estado_invitacion: 'pendiente',
      url_invitacion: 'https://clerk.example/inv/nueva',
    });
    fixture.detectChanges();

    expect(texto()).toContain('https://clerk.example/inv/nueva');
    expect(texto()).toContain('Invitación: Pendiente');

    boton('copiar enlace')?.click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(portapapeles).toEqual(['https://clerk.example/inv/nueva']);
    expect(texto()).toContain('Enlace copiado');
  });

  it('AC-6: un 409 de reenvío (ya invitado) se muestra sin enlace', () => {
    montar([administrador({ estado_invitacion: 'pendiente' })]);
    boton('reenviar')?.click();
    fixture.detectChanges();

    httpMock
      .expectOne(
        `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7/invitacion/reenvio`,
      )
      .flush(
        { detail: 'Ya existe una invitacion pendiente en Clerk' },
        { status: 409, statusText: 'Conflict' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('invitacion pendiente');
    expect(texto()).not.toContain('https://');
  });

  it('AC-8: da de alta un Administrador y muestra el enlace inmediato', () => {
    montar([]);
    boton('nuevo administrador')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioAlta.patchValue({
      nombre: 'Nuevo',
      apellido: 'Admin',
      correo: 'nuevo.admin@example.com',
      rol_id: 2,
      departamento_id: 10,
    });
    fixture.detectChanges();

    boton('crear administrador')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(RUTA_ADMIN);
    expect(peticion.request.method).toBe('POST');
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo).toEqual({
      nombre: 'Nuevo',
      apellido: 'Admin',
      correo: 'nuevo.admin@example.com',
      rol_id: 2,
      departamento_id: 10,
    });
    expect(cuerpo['institucion_id']).toBeUndefined();
    expect(cuerpo['esquema']).toBeUndefined();

    peticion.flush({
      usuario_id: 9,
      nombre: 'Nuevo',
      apellido: 'Admin',
      correo: 'nuevo.admin@example.com',
      departamento_id: 10,
      rol_id: 2,
      activo: true,
      estado_invitacion: 'pendiente',
      url_invitacion: 'https://clerk.example/inv/alta',
    });
    fixture.detectChanges();

    expect(texto()).toContain('https://clerk.example/inv/alta');

    httpMock.expectOne(RUTA_ADMIN).flush([administrador()]);
    fixture.detectChanges();
  });

  it('AC-10: la edición exige motivo y lo envía con idempotencia', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioEdicion.patchValue({
      nombre: 'Ada María',
      apellido: 'Admin',
      rol_id: 2,
      departamento_id: 10,
    });
    fixture.componentInstance.motivoEdicion.patchValue({
      codigo: 'correo_datos',
      texto: '',
    });
    fixture.detectChanges();

    // Código inválido: no se envía.
    boton('guardar cambios')?.click();
    fixture.detectChanges();
    httpMock.expectNone(`${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7`);

    fixture.componentInstance.motivoEdicion.patchValue({
      codigo: 'correccion_datos',
      texto: 'Corrección de nombre',
    });
    fixture.detectChanges();
    expect(fixture.componentInstance.motivoEdicionCompleto()).withContext('motivo completo').toBe(true);
    expect(fixture.componentInstance.guardando()).withContext('guardando false').toBe(false);
    expect(boton('guardar cambios')?.disabled).withContext('guardar habilitado').toBe(false);
    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(
      `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7`,
    );
    expect(peticion.request.method).toBe('PUT');
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['motivo']).toEqual({
      codigo: 'correccion_datos',
      texto: 'Corrección de nombre',
    });
    expect(typeof cuerpo['idempotencia']).toBe('string');
    peticion.flush({
      usuario_id: 7,
      nombre: 'Ada María',
      apellido: 'Admin',
      correo: 'ada@example.com',
      departamento_id: 10,
      rol_id: 2,
      activo: true,
      estado_invitacion: 'aceptada',
    });
    fixture.detectChanges();
    expect(texto()).toContain('Ada María');
  });

  it('AC-12: la baja del último Administrador responde 409 con su motivo y no muta', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.motivoEstado.patchValue({
      codigo: 'termino_vinculo',
      texto: '',
    });
    fixture.detectChanges();
    expect(fixture.componentInstance.motivoEstadoCompleto()).withContext('motivo completo').toBe(true);
    expect(fixture.componentInstance.guardando()).withContext('guardando false').toBe(false);
    expect(boton('confirmar')?.disabled).withContext('confirmar habilitado').toBe(false);
    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(
      `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7/estado`,
    );
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['activo']).toBe(false);
    expect(cuerpo['motivo']).toEqual({ codigo: 'termino_vinculo', texto: null });
    peticion.flush(
      {
        detail:
          'No se puede desactivar al ultimo Administrador activo de la institucion',
      },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('ultimo Administrador');
    expect(texto()).toContain('Activo');
  });

  it('AC-10: sin motivo no se envía el cambio de estado', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.confirmarCambioEstado();
    fixture.detectChanges();

    httpMock.expectNone(
      `${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7/estado`,
    );
  });

  it('AC-8: un 503 se informa como recuperable sin cerrar la edición', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.formularioEdicion.patchValue({
      nombre: 'Ada',
      apellido: 'Admin',
      rol_id: 2,
      departamento_id: 10,
    });
    fixture.componentInstance.motivoEdicion.patchValue({
      codigo: 'correccion_datos',
      texto: '',
    });
    fixture.detectChanges();
    boton('guardar cambios')?.click();
    fixture.detectChanges();

    httpMock
      .expectOne(`${URL_API}/control/instituciones/${INSTITUCION_ID}/usuarios/7`)
      .flush(
        { detail: 'La segunda confirmacion local no esta disponible' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('no esta disponible');
    expect(fixture.componentInstance.editando()).not.toBeNull();
  });

  it('AC-8: ante fallo de carga informa y permite reintentar', () => {
    fixture.detectChanges();
    httpMock
      .expectOne(RUTA_ADMIN)
      .flush({ detail: 'No existe' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeTruthy();

    boton('reintentar')?.click();
    fixture.detectChanges();
    httpMock.expectOne(RUTA_ADMIN).flush([administrador()]);
    fixture.detectChanges();
    expect(texto()).toContain('Ada Admin');
  });

  it('AC-8: sin Administradores muestra un vacío explícito', () => {
    montar([]);
    expect(texto()).toContain('no tiene Administradores');
  });
});
