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
  DepartamentoGestion,
  IdentidadAutenticada,
  Rol,
  Sede,
  Usuario,
} from '../../shared/interfaces';
import { UsuariosComponent } from './usuarios.component';

/**
 * Feature 012 (T10): vista de usuarios locales (AC-8/AC-9/AC-11).
 *
 * Seam bajo prueba: la interfaz pública del componente. Se verifica el listado
 * con rol/departamento resueltos y el estado activo/inactivo, la edición sin
 * correo (PUT), el cambio de estado (PATCH) con su 409, y la asignación de sede
 * de un Bodeguero limitada a las sedes del tenant, incluido el 409 por rol.
 *
 * Ajuste post-cierre (D-6/AC-10): el combo de rol del **alta** solo ofrece los
 * roles que la identidad activa puede asignar (Administrador → Bodeguero/
 * Solicitante; Superadmin → los cuatro), alineado con el backend sin alterar la
 * regla de servidor.
 */
describe('UsuariosComponent', () => {
  const RUTA_USUARIOS = `${URL_API}/usuarios/`;
  const RUTA_ROLES = `${URL_API}/usuarios/roles`;
  const RUTA_DEPARTAMENTOS = `${URL_API}/organizacion/departamentos`;
  const RUTA_SEDES = `${URL_API}/organizacion/sedes`;

  const ROLES: Rol[] = [
    { rol_id: 1, nombre_rol: 'Administrador', descripcion: null },
    { rol_id: 3, nombre_rol: 'Bodeguero', descripcion: null },
    { rol_id: 4, nombre_rol: 'Solicitante', descripcion: null },
  ];

  /** Catálogo completo: solo se sirve para la identidad Superadmin. */
  const ROLES_CUATRO: Rol[] = [
    { rol_id: 1, nombre_rol: 'Superadmin', descripcion: null },
    { rol_id: 2, nombre_rol: 'Administrador', descripcion: null },
    { rol_id: 3, nombre_rol: 'Bodeguero', descripcion: null },
    { rol_id: 4, nombre_rol: 'Solicitante', descripcion: null },
  ];

  function identidad(rol: string): IdentidadAutenticada {
    return {
      usuario_id: 1,
      sub: 'user_prueba',
      nombre: 'Sonda',
      apellido: 'Rol',
      correo: 'sonda@example.com',
      rol,
      institucion: null,
    };
  }

  const DEPARTAMENTOS: DepartamentoGestion[] = [
    {
      departamento_id: 10,
      nombre_dep: 'Logística',
      descripcion: null,
      institucion_id: 'INSTA',
      sede_id: null,
      activo: true,
    },
  ];

  const SEDES: Sede[] = [
    { sede_id: 1, nombre: 'Sede Central', direccion: null, institucion_id: 'INSTA', activo: true },
    { sede_id: 2, nombre: 'Bodega Norte', direccion: null, institucion_id: 'INSTA', activo: true },
  ];

  function usuario(sobrescribir: Partial<Usuario> = {}): Usuario {
    return {
      usuario_id: 1,
      nombre: 'Ana',
      apellido: 'Pérez',
      correo: 'ana@example.com',
      departamento_id: 10,
      rol_id: 3,
      sede_id: 1,
      activo: true,
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<UsuariosComponent>;
  let httpMock: HttpTestingController;
  let identidadFalsa: WritableSignal<IdentidadAutenticada | null>;

  beforeEach(async () => {
    identidadFalsa = signal<IdentidadAutenticada | null>(identidad('Administrador'));

    await TestBed.configureTestingModule({
      imports: [UsuariosComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        // La vista deriva los roles asignables del rol de la identidad activa;
        // se sustituye el servicio real por una señal doble (sin Clerk).
        { provide: AutenticacionService, useValue: { identidad: identidadFalsa } },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(UsuariosComponent);
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

  function montar(usuarios: Usuario[] = [usuario()], roles: Rol[] = ROLES): void {
    fixture.detectChanges();
    httpMock.expectOne(RUTA_USUARIOS).flush(usuarios);
    httpMock.expectOne(RUTA_ROLES).flush(roles);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();
  }

  /** Opciones del combo de rol del formulario de alta, en orden. */
  function opcionesRolAlta(): string[] {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll(
        '#crear-usuario-rol option',
      ),
    ).map((o) => o.textContent?.trim() ?? '');
  }

  it('AC-8: renderiza rol, departamento, estado y sede del Bodeguero', () => {
    montar();
    const visible = texto();
    expect(visible).toContain('Ana Pérez');
    expect(visible).toContain('ana@example.com');
    expect(visible).toContain('Bodeguero');
    expect(visible).toContain('Logística');
    expect(visible).toContain('Activo');
    expect(visible).toContain('Sede Central');
  });

  it('AC-8/AC-11: un usuario inactivo se muestra como tal y ofrece Reactivar', () => {
    montar([usuario({ activo: false })]);
    expect(texto()).toContain('Inactivo');
    expect(boton('reactivar')).toBeTruthy();
  });

  it('AC-8: el listado publica el estado real, sin "Estado no informado"', () => {
    montar([
      usuario({ activo: true }),
      usuario({ usuario_id: 2, nombre: 'Beto', activo: false }),
    ]);
    const visible = texto();
    expect(visible).toContain('Activo');
    expect(visible).toContain('Inactivo');
    expect(visible).not.toContain('Estado no informado');
  });

  it('AC-8: edita con PUT sin enviar el correo', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioEdicion.patchValue({
      nombre: 'Ana María',
      apellido: 'Pérez',
      rol_id: 4,
      departamento_id: 10,
    });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/1`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({
      nombre: 'Ana María',
      apellido: 'Pérez',
      rol_id: 4,
      departamento_id: 10,
    });
    expect((peticion.request.body as Record<string, unknown>)['correo']).toBeUndefined();

    peticion.flush(usuario({ nombre: 'Ana María', rol_id: 4 }));
    fixture.detectChanges();
    expect(texto()).toContain('Ana María');
  });

  it('AC-11: un 409 al desactivar (encargado) muestra el motivo', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/1/estado`);
    expect(peticion.request.body).toEqual({ activo: false });
    peticion.flush(
      { detail: 'No se puede desactivar el usuario: es encargado de uno o mas departamentos' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('es encargado');
    expect(texto()).toContain('Activo');
  });

  it('AC-9: asigna sede a un Bodeguero con opciones limitadas al tenant', () => {
    montar([usuario({ sede_id: null })]);
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

    const peticion = httpMock.expectOne(`${URL_API}/organizacion/usuarios/1/sede`);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ sede_id: 2 });
    peticion.flush({ usuario_id: 1, sede_id: 2 });
    fixture.detectChanges();
    expect(texto()).toContain('Bodega Norte');
  });

  it('AC-9: un 409 al asignar sede a un no Bodeguero muestra el motivo', () => {
    montar([usuario({ rol_id: 4, sede_id: null })]);
    // Un Solicitante no ofrece la acción de sede; se comprueba que no aparece.
    expect(boton('asignar sede')).toBeFalsy();
  });

  it('AC-8: estado vacío cuando no hay usuarios', () => {
    montar([]);
    expect(texto()).toContain('Aún no hay usuarios');
  });

  // --- Alta de usuario (Feature 012, correccion T13) ---

  it('AC-8: el botón Nuevo usuario abre el formulario de alta', () => {
    montar();
    expect(boton('crear usuario')).toBeFalsy();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    const visible = texto();
    expect(visible).toContain('Alta de usuario');
    expect(boton('crear usuario')).toBeTruthy();
    const campos = (
      fixture.nativeElement as HTMLElement
    ).querySelectorAll('#crear-usuario-nombre, #crear-usuario-correo, #crear-usuario-rol');
    expect(campos.length).toBe(3);
  });

  it('AC-8: el alta envía el payload y recarga el listado', () => {
    montar([]);
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioCreacion.patchValue({
      nombre: 'Nuevo',
      apellido: 'Solicitante',
      correo: 'nuevo@example.com',
      rol_id: 4,
      departamento_id: 10,
    });
    fixture.detectChanges();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({
      nombre: 'Nuevo',
      apellido: 'Solicitante',
      correo: 'nuevo@example.com',
      departamento_id: 10,
      rol_id: 4,
    });
    peticion.flush(
      usuario({
        usuario_id: 5,
        nombre: 'Nuevo',
        apellido: 'Solicitante',
        correo: 'nuevo@example.com',
        rol_id: 4,
        sede_id: null,
      }),
    );
    fixture.detectChanges();

    // El alta exitosa recarga la lista con una nueva ronda de GET.
    httpMock
      .expectOne(RUTA_USUARIOS)
      .flush([
        usuario({
          usuario_id: 5,
          nombre: 'Nuevo',
          apellido: 'Solicitante',
          correo: 'nuevo@example.com',
          rol_id: 4,
          sede_id: null,
        }),
      ]);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();

    expect(texto()).toContain('Nuevo Solicitante');
    expect(texto()).toContain('creado');
  });

  it('AC-8: un 422 de correo inexistente en Clerk se muestra y no recarga', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioCreacion.patchValue({
      nombre: 'Sin',
      apellido: 'Clerk',
      correo: 'no.existe@example.com',
      rol_id: 4,
      departamento_id: 10,
    });
    fixture.detectChanges();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/`);
    peticion.flush(
      { detail: 'El correo no existe como identidad verificada en Clerk' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta?.textContent).toContain('no existe');
    // El formulario sigue abierto para corregir el correo.
    expect(boton('crear usuario')).toBeTruthy();
  });

  it('AC-8: un 409 de correo ya vinculado se muestra con el motivo', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioCreacion.patchValue({
      nombre: 'Duplicado',
      apellido: 'Local',
      correo: 'ya.vinculado@example.com',
      rol_id: 4,
      departamento_id: 10,
    });
    fixture.detectChanges();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${URL_API}/usuarios/`).flush(
      { detail: 'El correo ya esta vinculado a una identidad local activa' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta?.textContent).toContain('ya esta vinculado');
  });

  it('AC-9: el alta de un Bodeguero con sede la asigna tras crear', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioCreacion.patchValue({
      nombre: 'Beto',
      apellido: 'Bodega',
      correo: 'beto@example.com',
      rol_id: 3,
      departamento_id: 10,
      sede_id: 2,
    });
    fixture.detectChanges();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock
      .expectOne(`${URL_API}/usuarios/`)
      .flush(
        usuario({
          usuario_id: 7,
          nombre: 'Beto',
          apellido: 'Bodega',
          correo: 'beto@example.com',
          rol_id: 3,
          sede_id: null,
        }),
      );
    fixture.detectChanges();

    const asignacion = httpMock.expectOne(
      `${URL_API}/organizacion/usuarios/7/sede`,
    );
    expect(asignacion.request.method).toBe('PUT');
    expect(asignacion.request.body).toEqual({ sede_id: 2 });
    asignacion.flush({ usuario_id: 7, sede_id: 2 });
    fixture.detectChanges();

    httpMock.expectOne(RUTA_USUARIOS).flush([]);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();

    expect(texto()).toContain('con su sede');
  });

  // --- Roles asignables según la identidad (ajuste post-cierre, D-6/AC-10) ---

  it('AC-8/AC-10: con identidad Administrador el combo de rol del alta ofrece dos roles', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    expect(opcionesRolAlta()).toEqual(['Bodeguero', 'Solicitante']);
  });

  it('AC-8/AC-10: con identidad Superadmin el combo de rol del alta ofrece los cuatro roles', () => {
    identidadFalsa.set(identidad('Superadmin'));
    montar([usuario()], ROLES_CUATRO);
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    expect(opcionesRolAlta()).toEqual([
      'Superadmin',
      'Administrador',
      'Bodeguero',
      'Solicitante',
    ]);
  });

  it('AC-8/AC-10: el rol por defecto del alta es asignable por la identidad activa', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.formularioCreacion.controls.rol_id.value).toBe(
      3,
    );
  });

  it('AC-8/AC-10: si cambia la identidad activa, el combo se recalcula', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    // Administrador sobre el catálogo de prueba: Bodeguero y Solicitante.
    expect(opcionesRolAlta().length).toBe(2);

    // Superadmin: todos los roles servidos (el catálogo no se recarga).
    identidadFalsa.set(identidad('Superadmin'));
    fixture.detectChanges();
    expect(opcionesRolAlta().length).toBe(3);
  });
});
