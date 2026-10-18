import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { URL_API } from '../../shared/config/url-api';
import { DepartamentoGestion, Encargado, Rol, Usuario } from '../../shared/interfaces';
import { EncargadosComponent } from './encargados.component';

/**
 * Feature 012 (T10): vista de encargados por departamento (AC-10).
 *
 * Seam bajo prueba: la interfaz pública del componente. Se verifica el listado de
 * encargados existentes, el estado vacío, la asociación y el retiro, y que los
 * candidatos se limiten a Solicitantes del mismo departamento aún no asociados.
 */
describe('EncargadosComponent', () => {
  const RUTA_DEPARTAMENTOS = `${URL_API}/organizacion/departamentos`;
  const RUTA_USUARIOS = `${URL_API}/usuarios/`;
  const RUTA_ROLES = `${URL_API}/usuarios/roles`;

  const DEPARTAMENTOS: DepartamentoGestion[] = [
    {
      departamento_id: 10,
      nombre_dep: 'Logística',
      descripcion: null,
      institucion_id: 'INSTA',
      sede_id: null,
      activo: true,
    },
    {
      departamento_id: 20,
      nombre_dep: 'Ventas',
      descripcion: null,
      institucion_id: 'INSTA',
      sede_id: null,
      activo: true,
    },
  ];

  const ROLES: Rol[] = [
    { rol_id: 3, nombre_rol: 'Bodeguero', descripcion: null },
    { rol_id: 4, nombre_rol: 'Solicitante', descripcion: null },
  ];

  const USUARIOS: Usuario[] = [
    { usuario_id: 1, nombre: 'Ana', apellido: 'Pérez', correo: 'ana@e.com', departamento_id: 10, rol_id: 4 },
    { usuario_id: 2, nombre: 'Luis', apellido: 'Soto', correo: 'luis@e.com', departamento_id: 20, rol_id: 4 },
    { usuario_id: 3, nombre: 'Marta', apellido: 'Ruiz', correo: 'marta@e.com', departamento_id: 10, rol_id: 3 },
    { usuario_id: 4, nombre: 'Sofía', apellido: 'Díaz', correo: 'sofia@e.com', departamento_id: 10, rol_id: 4 },
  ];

  const ENCARGADO: Encargado = {
    usuario_id: 4,
    departamento_id: 10,
    nombre: 'Sofía',
    apellido: 'Díaz',
    correo: 'sofia@e.com',
  };

  let fixture: ComponentFixture<EncargadosComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EncargadosComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(EncargadosComponent);
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

  function montar(encargados: Encargado[] = [ENCARGADO]): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_USUARIOS).flush(USUARIOS);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    fixture.detectChanges();
    // Se selecciona automáticamente el primer departamento y se cargan sus encargados.
    httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/10/encargados`).flush(encargados);
    fixture.detectChanges();
  }

  it('AC-10: lista los encargados existentes del departamento seleccionado', () => {
    montar();
    expect(texto()).toContain('Sofía Díaz');
    expect(texto()).toContain('sofia@e.com');
  });

  it('AC-10: estado vacío cuando el departamento no tiene encargados', () => {
    montar([]);
    expect(texto()).toContain('no tiene encargados asociados');
  });

  it('AC-10: los candidatos se limitan a Solicitantes del mismo departamento no asociados', () => {
    montar();
    const opciones = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('#candidato-encargado option'),
    ).map((o) => o.textContent?.trim());
    // Solo Ana (dep 10, Solicitante, no encargada). Luis es de otro departamento,
    // Marta no es Solicitante y Sofía ya es encargada.
    expect(opciones).toEqual(['Selecciona un solicitante', 'Ana Pérez']);
  });

  it('AC-10: asocia un encargado con POST { usuario_id }', () => {
    montar([]);
    fixture.componentInstance.seleccionarCandidato({
      target: { value: '1' },
    } as unknown as Event);
    fixture.detectChanges();

    boton('asociar encargado')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/10/encargados`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ usuario_id: 1 });
    peticion.flush({
      usuario_id: 1,
      departamento_id: 10,
      nombre: 'Ana',
      apellido: 'Pérez',
      correo: 'ana@e.com',
    });
    fixture.detectChanges();
    expect(texto()).toContain('Ana Pérez');
  });

  it('AC-10: retira un encargado con DELETE', () => {
    montar();
    boton('retirar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/10/encargados/4`);
    expect(peticion.request.method).toBe('DELETE');
    peticion.flush(null);
    fixture.detectChanges();

    expect(texto()).toContain('no tiene encargados asociados');
  });

  it('AC-10: un 409 al asociar un encargado incompatible muestra el motivo', () => {
    montar([]);
    fixture.componentInstance.seleccionarCandidato({
      target: { value: '1' },
    } as unknown as Event);
    fixture.detectChanges();

    boton('asociar encargado')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${RUTA_DEPARTAMENTOS}/10/encargados`).flush(
      { detail: 'El usuario ya es encargado de este departamento' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('ya es encargado');
  });
});
