import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { tokenInterceptor } from '../../core/interceptors/token.interceptor';
import { AutenticacionService } from '../../core/services/auth.service';
import { URL_API } from '../../shared/config/url-api';
import { InstitucionAltaControlRespuesta } from '../../shared/interfaces';
import { AltaInstitucionComponent } from './alta-institucion.component';

/**
 * Alta de institución del portal `/control` (Feature 010, AC-7…AC-9/AC-15).
 *
 * Seam bajo prueba: la **interfaz pública del componente** — el formulario, el
 * `POST` real bajo `HttpTestingController` y el DOM. El cliente solo envía el
 * DTO `InstitucionAltaControlCrear` (nunca esquema, versión, rol ni estado) y
 * presenta estados de carga, error real y éxito, sin fingir éxito.
 *
 * El `tokenInterceptor` real es asíncrono (espera el token de Clerk), así que el
 * `POST` se materializa tras un microtask: cada acción de envío espera
 * `whenStable()` antes de interrogar al `HttpTestingController`.
 */
describe('AltaInstitucionComponent', () => {
  const RUTA_ALTA = `${URL_API}/control/instituciones/`;

  /** Cuerpo mínimo y válido del DTO, en `snake_case`. */
  const DATOS_VALIDOS = {
    institucion_id: 'inst-nueva',
    nombre: 'Institución Nueva',
    rut: '76.111.222-3',
    direccion: 'Av. Siempre Viva 742',
    correo_administrador: 'admin@nueva.cl',
    nombre_administrador: 'Ana',
    apellido_administrador: 'Pérez',
    departamento_nombre_administrativo: 'Administración',
  };

  function respuesta(
    sobrescribir: Partial<InstitucionAltaControlRespuesta> = {},
  ): InstitucionAltaControlRespuesta {
    return {
      institucion_id: 'inst-nueva',
      nombre: 'Institución Nueva',
      correo_administrador: 'admin@nueva.cl',
      nombre_esquema: 'tenant_inst_nueva_ab12cd34',
      version_esquema: '010.1',
      estado: 'operativa',
      mensaje: 'Institución aprovisionada correctamente.',
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<AltaInstitucionComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AltaInstitucionComponent],
      providers: [
        provideHttpClient(withInterceptors([tokenInterceptor])),
        provideHttpClientTesting(),
        // El interceptor existente es la única fuente del Bearer de Clerk.
        {
          provide: AutenticacionService,
          useValue: { obtenerToken: () => Promise.resolve('token-control') },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AltaInstitucionComponent);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify({ ignoreCancelled: true });
  });

  function texto(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function botonEnviar(): HTMLButtonElement {
    const boton = (fixture.nativeElement as HTMLElement).querySelector(
      'button[type="submit"]',
    );
    return boton as HTMLButtonElement;
  }

  function completarFormulario(datos: typeof DATOS_VALIDOS = DATOS_VALIDOS): void {
    fixture.componentInstance.formulario.patchValue(datos);
    fixture.detectChanges();
  }

  /** Envía el formulario y espera a que el interceptor asíncrono emita la petición. */
  async function enviar(): Promise<void> {
    botonEnviar().click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  // -------------------------------------------------------------------------
  // Contrato del DTO
  // -------------------------------------------------------------------------

  it('AC-9: envía solo el DTO del alta, sin esquema, versión, rol ni estado', async () => {
    completarFormulario();
    await enviar();

    const peticion = httpMock.expectOne(RUTA_ALTA);
    expect(peticion.request.method).toBe('POST');
    expect(Object.keys(peticion.request.body as object).sort()).toEqual(
      [
        'institucion_id',
        'nombre',
        'rut',
        'direccion',
        'correo_administrador',
        'nombre_administrador',
        'apellido_administrador',
        'departamento_nombre_administrativo',
      ].sort(),
    );
    expect(peticion.request.body.institucion_id).toBe('inst-nueva');

    peticion.flush(respuesta());
  });

  it('AC-7: presenta el Bearer de Clerk a través del interceptor existente', async () => {
    completarFormulario();
    await enviar();

    const peticion = httpMock.expectOne(RUTA_ALTA);
    expect(peticion.request.headers.get('Authorization')).toBe('Bearer token-control');

    peticion.flush(respuesta());
  });

  it('AC-15: no envía la petición si el formulario es inválido', async () => {
    await enviar();

    httpMock.expectNone(RUTA_ALTA);
  });

  // -------------------------------------------------------------------------
  // Estado de carga
  // -------------------------------------------------------------------------

  it('AC-15: durante el alta muestra el estado de carga', async () => {
    completarFormulario();
    await enviar();

    const indicador = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="status"]',
    );
    expect(indicador).withContext('indicador de carga').toBeTruthy();
    expect(botonEnviar().disabled).toBe(true);

    httpMock.expectOne(RUTA_ALTA).flush(respuesta());
    fixture.detectChanges();
  });

  // -------------------------------------------------------------------------
  // Éxito
  // -------------------------------------------------------------------------

  it('AC-7: en 201 informa el resultado operativo del servidor', async () => {
    completarFormulario();
    await enviar();

    httpMock.expectOne(RUTA_ALTA).flush(respuesta());
    fixture.detectChanges();

    const visible = texto();
    expect(visible).toContain('tenant_inst_nueva_ab12cd34');
    expect(visible).toContain('010.1');
    expect(visible).toContain('operativa');
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]'),
    ).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Errores reales, sin fingir éxito
  // -------------------------------------------------------------------------

  it('AC-8: un 409 muestra el mensaje real y no declara éxito', async () => {
    completarFormulario();
    await enviar();

    httpMock
      .expectOne(RUTA_ALTA)
      .flush({ detail: 'La institución ya existe' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('La institución ya existe');
    expect(fixture.componentInstance.exito()).toBeNull();
    expect(texto()).not.toContain('operativa');
  });

  it('AC-8: un 422 por correo inexistente en Clerk muestra el error real', async () => {
    completarFormulario();
    await enviar();

    httpMock
      .expectOne(RUTA_ALTA)
      .flush(
        { detail: 'El correo no existe en Clerk' },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('El correo no existe en Clerk');
    expect(fixture.componentInstance.exito()).toBeNull();
  });

  it('AC-8: un 503 por frontera Clerk caída muestra el error real', async () => {
    completarFormulario();
    await enviar();

    httpMock
      .expectOne(RUTA_ALTA)
      .flush(
        { detail: 'No fue posible verificar el correo contra Clerk' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('No fue posible verificar el correo contra Clerk');
    expect(fixture.componentInstance.exito()).toBeNull();
  });

  it('AC-8: un 422 de validación sin `detail` de texto informa un error legible', async () => {
    completarFormulario();
    await enviar();

    httpMock
      .expectOne(RUTA_ALTA)
      .flush(
        { detail: [{ loc: ['body', 'correo_administrador'], msg: 'correo inválido' }] },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta).withContext('alerta de error').toBeTruthy();
    expect(fixture.componentInstance.exito()).toBeNull();
  });
});
