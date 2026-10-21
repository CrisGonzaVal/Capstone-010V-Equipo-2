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
  UsuarioInvitacionRespuesta,
} from '../../shared/interfaces';
import { UsuariosComponent } from './usuarios.component';

/**
 * Feature 012 (T10) y Feature 017 (T9): vista de usuarios locales.
 *
 * Seam bajo prueba: la interfaz pública del componente — DOM y peticiones reales
 * del `AdministracionService` bajo `HttpTestingController`. Se verifica el
 * listado con el estado de invitación persistido separado del vínculo local, el
 * alta con invitación y copia del enlace solo en la respuesta inmediata, los
 * motivos obligatorios de edición y estado, los errores 409/422/503 y —desde
 * T12— el reenvío ordinario (`POST /usuarios/{id}/invitacion/reenvio`) con su
 * restricción por rol/estado y la secuencia reactivar (con motivo) → reenviar.
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
      estado_invitacion: 'aceptada',
      ...sobrescribir,
    };
  }

  function invitacion(
    sobrescribir: Partial<UsuarioInvitacionRespuesta> = {},
  ): UsuarioInvitacionRespuesta {
    return {
      ...usuario(),
      url_invitacion: null,
      ...sobrescribir,
    };
  }

  let fixture: ComponentFixture<UsuariosComponent>;
  let httpMock: HttpTestingController;
  let identidadFalsa: WritableSignal<IdentidadAutenticada | null>;
  let portapapeles: string[];

  beforeEach(async () => {
    identidadFalsa = signal<IdentidadAutenticada | null>(identidad('Administrador'));
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
      imports: [UsuariosComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
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

  function opcionesRolAlta(): string[] {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll(
        '#crear-usuario-rol option',
      ),
    ).map((o) => o.textContent?.trim() ?? '');
  }

  function opcionesRolEdicion(): string[] {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll(
        '#editar-usuario-rol option',
      ),
    ).map((o) => o.textContent?.trim() ?? '');
  }

  function rellenarAlta(sobrescribir: Record<string, unknown> = {}): void {
    fixture.componentInstance.formularioCreacion.patchValue({
      nombre: 'Nuevo',
      apellido: 'Solicitante',
      correo: 'nuevo@example.com',
      rol_id: 4,
      departamento_id: 10,
      ...sobrescribir,
    });
    fixture.detectChanges();
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

  it('AC-5: muestra el estado de invitación persistido separado del vínculo local', () => {
    montar([
      usuario({ usuario_id: 1, activo: false, estado_invitacion: 'pendiente' }),
      usuario({ usuario_id: 2, nombre: 'Beto', activo: true, estado_invitacion: 'aceptada' }),
    ]);
    const visible = texto();
    expect(visible).toContain('Inactivo');
    expect(visible).toContain('Activo');
    expect(visible).toContain('Invitación: Pendiente');
    expect(visible).toContain('Invitación: Aceptada');
  });

  it('AC-5: un estado de invitación desconocido se presenta como «No disponible»', () => {
    montar([usuario({ estado_invitacion: undefined })]);
    expect(texto()).toContain('Invitación: No disponible');
    expect(texto()).not.toContain('Invitación: Aceptada');
  });

  it('AC-5: el listado nunca muestra una URL de invitación', () => {
    montar([usuario({ estado_invitacion: 'pendiente' })]);
    expect(texto()).not.toContain('http');
    expect(texto().toLowerCase()).not.toContain('copiar enlace');
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

  it('AC-10: edita con PUT y motivo del catálogo, sin enviar el correo', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    fixture.componentInstance.formularioEdicion.patchValue({
      nombre: 'Ana María',
      apellido: 'Pérez',
      rol_id: 4,
      departamento_id: 10,
    });
    fixture.componentInstance.motivoEdicion.patchValue({
      codigo: 'cambio_funciones',
      texto: 'Nuevo rol',
    });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/1`);
    expect(peticion.request.method).toBe('PUT');
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['nombre']).toBe('Ana María');
    expect(cuerpo['apellido']).toBe('Pérez');
    expect(cuerpo['rol_id']).toBe(4);
    expect(cuerpo['departamento_id']).toBe(10);
    expect(cuerpo['correo']).toBeUndefined();
    expect(cuerpo['motivo']).toEqual({ codigo: 'cambio_funciones', texto: 'Nuevo rol' });
    expect(typeof cuerpo['idempotencia']).toBe('string');

    peticion.flush(usuario({ nombre: 'Ana María', rol_id: 4 }));
    fixture.detectChanges();
    expect(texto()).toContain('Ana María');
  });

  it('AC-10: una edición sin cambios no exige motivo', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/1`);
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['motivo']).toBeUndefined();
    expect(cuerpo['idempotencia']).toBeUndefined();
    peticion.flush(usuario());
    fixture.detectChanges();
  });

  it('AC-10: «otro» sin texto no envía la edición', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.formularioEdicion.patchValue({ nombre: 'Cambio' });
    fixture.componentInstance.motivoEdicion.patchValue({ codigo: 'otro', texto: '   ' });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    httpMock.expectNone(`${URL_API}/usuarios/1`);
    expect(texto()).toContain('exige un texto explicativo');
  });

  it('AC-10: un texto de motivo mayor a 500 caracteres no envía la edición', () => {
    montar();
    boton('editar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.formularioEdicion.patchValue({ nombre: 'Cambio' });
    fixture.componentInstance.motivoEdicion.patchValue({
      codigo: 'otro',
      texto: 'a'.repeat(501),
    });
    fixture.detectChanges();

    boton('guardar cambios')?.click();
    fixture.detectChanges();

    httpMock.expectNone(`${URL_API}/usuarios/1`);
  });

  it('AC-11: un 409 al desactivar (encargado) muestra el motivo', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.motivoEstado.patchValue({
      codigo: 'termino_vinculo',
      texto: '',
    });
    fixture.detectChanges();
    expect(fixture.componentInstance.motivoEstadoCompleto()).withContext('motivo completo').toBe(true);
    expect(boton('confirmar')?.disabled).withContext('confirmar habilitado').toBe(false);
    boton('confirmar')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/1/estado`);
    const cuerpo = peticion.request.body as Record<string, unknown>;
    expect(cuerpo['activo']).toBe(false);
    expect(cuerpo['motivo']).toEqual({ codigo: 'termino_vinculo', texto: null });
    expect(typeof cuerpo['idempotencia']).toBe('string');
    peticion.flush(
      { detail: 'No se puede desactivar el usuario: es encargado de uno o mas departamentos' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('es encargado');
    expect(texto()).toContain('Activo');
  });

  it('AC-10: sin motivo válido el cambio de estado no se envía', () => {
    montar();
    boton('desactivar')?.click();
    fixture.detectChanges();
    fixture.componentInstance.confirmarCambioEstado();
    fixture.detectChanges();

    httpMock.expectNone(`${URL_API}/usuarios/1/estado`);
    expect(texto()).toContain('Selecciona un motivo');
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

  it('AC-9: un Solicitante no ofrece la acción de asignar sede', () => {
    montar([usuario({ rol_id: 4, sede_id: null })]);
    expect(boton('asignar sede')).toBeFalsy();
  });

  // --- Reenvío ordinario de invitación (Feature 017, T12) ---

  describe('reenvío ordinario de invitación (T12)', () => {
    function tarjetas(): HTMLElement[] {
      return Array.from(
        (fixture.nativeElement as HTMLElement).querySelectorAll('li'),
      );
    }

    function botonEn(indice: number, etiqueta: string): HTMLButtonElement | undefined {
      return Array.from(tarjetas()[indice].querySelectorAll('button')).find((b) =>
        new RegExp(etiqueta, 'i').test(b.textContent ?? ''),
      );
    }

    function textoDe(indice: number): string {
      return tarjetas()[indice].textContent ?? '';
    }

    it('AC-6/AC-9: solo se ofrece a Bodeguero/Solicitante activos con invitación no aceptada', () => {
      montar([
        usuario({ usuario_id: 1, estado_invitacion: 'pendiente' }),
        usuario({ usuario_id: 2, estado_invitacion: 'aceptada' }),
        usuario({ usuario_id: 3, estado_invitacion: 'expirada', activo: false }),
        usuario({ usuario_id: 4, rol_id: 1, estado_invitacion: 'pendiente' }),
        usuario({ usuario_id: 5, rol_id: 4, estado_invitacion: 'revocada' }),
      ]);

      expect(botonEn(0, 'reenviar')).toBeTruthy();
      expect(botonEn(1, 'reenviar')).toBeFalsy();
      expect(botonEn(2, 'reenviar')).toBeFalsy();
      expect(botonEn(3, 'reenviar')).toBeFalsy();
      expect(botonEn(4, 'reenviar')).toBeTruthy();
    });

    it('AC-6: un vínculo inactivo no ofrece reenvío y pide reactivarlo primero', () => {
      montar([usuario({ usuario_id: 3, estado_invitacion: 'expirada', activo: false })]);

      expect(botonEn(0, 'reenviar')).toBeFalsy();
      expect(textoDe(0)).toContain('Reactívalo primero');
    });

    it('AC-6: reenvía con POST sin cuerpo y muestra la URL solo en esa respuesta', async () => {
      montar([usuario({ usuario_id: 7, estado_invitacion: 'expirada' })]);

      botonEn(0, 'reenviar')?.click();
      fixture.detectChanges();

      const peticion = httpMock.expectOne(`${URL_API}/usuarios/7/invitacion/reenvio`);
      expect(peticion.request.method).toBe('POST');
      expect(peticion.request.body).toBeNull();
      peticion.flush(
        invitacion({
          usuario_id: 7,
          estado_invitacion: 'pendiente',
          url_invitacion: 'https://clerk.example/inv/nueva',
        }),
      );
      fixture.detectChanges();

      expect(textoDe(0)).toContain('Invitación: Pendiente');
      expect(texto()).toContain('https://clerk.example/inv/nueva');
      expect(texto()).toContain('reenviada');

      boton('copiar enlace')?.click();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(portapapeles).toEqual(['https://clerk.example/inv/nueva']);
      expect(texto()).toContain('Enlace copiado');
    });

    it('AC-6: no envía el reenvío dos veces mientras está en vuelo', () => {
      montar([usuario({ usuario_id: 7, estado_invitacion: 'pendiente' })]);

      const objetivo = usuario({ usuario_id: 7, estado_invitacion: 'pendiente' });
      fixture.componentInstance.reenviarInvitacion(objetivo);
      fixture.componentInstance.reenviarInvitacion(objetivo);
      fixture.detectChanges();

      const peticiones = httpMock.match(
        `${URL_API}/usuarios/7/invitacion/reenvio`,
      );
      expect(peticiones.length).toBe(1);
      peticiones[0].flush(
        invitacion({ usuario_id: 7, estado_invitacion: 'pendiente', url_invitacion: null }),
      );
      fixture.detectChanges();
    });

    it('AC-6: un 409 (aceptada/conflicto) se muestra sin enlace', () => {
      montar([usuario({ usuario_id: 8, estado_invitacion: 'pendiente' })]);

      botonEn(0, 'reenviar')?.click();
      fixture.detectChanges();

      httpMock
        .expectOne(`${URL_API}/usuarios/8/invitacion/reenvio`)
        .flush(
          { detail: 'La invitacion ya fue aceptada; no se reenvia' },
          { status: 409, statusText: 'Conflict' },
        );
      fixture.detectChanges();

      expect(texto()).toContain('ya fue aceptada');
      expect(texto()).not.toContain('Copiar enlace');
      expect(botonEn(0, 'reenviar')).toBeTruthy();
    });

    it('AC-6: un 503 de la frontera Clerk se informa y es reintentable', () => {
      montar([usuario({ usuario_id: 8, estado_invitacion: 'pendiente' })]);

      botonEn(0, 'reenviar')?.click();
      fixture.detectChanges();

      httpMock
        .expectOne(`${URL_API}/usuarios/8/invitacion/reenvio`)
        .flush('', { status: 503, statusText: 'Service Unavailable' });
      fixture.detectChanges();

      expect(texto()).toContain('no está disponible');
      expect(botonEn(0, 'reenviar')).toBeTruthy();
    });

    it('AC-2: reactivar no reenvía; después el reenvío es una operación separada', () => {
      montar([usuario({ usuario_id: 9, estado_invitacion: 'pendiente', activo: false })]);

      expect(botonEn(0, 'reenviar')).toBeFalsy();

      botonEn(0, 'reactivar')?.click();
      fixture.detectChanges();
      fixture.componentInstance.motivoEstado.patchValue({
        codigo: 'reasignacion_organizacional',
        texto: '',
      });
      fixture.detectChanges();

      boton('confirmar')?.click();
      fixture.detectChanges();

      const cambio = httpMock.expectOne(`${URL_API}/usuarios/9/estado`);
      expect(cambio.request.method).toBe('PATCH');
      expect(cambio.request.body.activo).toBe(true);
      expect(cambio.request.body.motivo).toEqual({
        codigo: 'reasignacion_organizacional',
        texto: null,
      });
      cambio.flush({ usuario_id: 9, activo: true });
      fixture.detectChanges();

      // La reactivación no llama a Clerk ni crea invitaciones.
      httpMock.expectNone(`${URL_API}/usuarios/9/invitacion/reenvio`);
      expect(textoDe(0)).toContain('La reactivación no reenvía la invitación');

      expect(botonEn(0, 'reenviar')).toBeTruthy();
      botonEn(0, 'reenviar')?.click();
      fixture.detectChanges();

      const reenvio = httpMock.expectOne(`${URL_API}/usuarios/9/invitacion/reenvio`);
      expect(reenvio.request.method).toBe('POST');
      reenvio.flush(
        invitacion({
          usuario_id: 9,
          estado_invitacion: 'pendiente',
          url_invitacion: 'https://clerk.example/inv/reactivado',
        }),
      );
      fixture.detectChanges();

      expect(texto()).toContain('https://clerk.example/inv/reactivado');
    });
  });

  it('AC-8: estado vacío cuando no hay usuarios', () => {
    montar([]);
    expect(texto()).toContain('Aún no hay usuarios');
  });

  // --- Alta de usuario con invitación (Feature 017, T9) ---

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

  it('AC-1: el alta con invitación muestra el estado pendiente y el enlace copiable', async () => {
    montar([]);
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/`);
    expect(peticion.request.method).toBe('POST');
    peticion.flush(
      invitacion({
        usuario_id: 5,
        nombre: 'Nuevo',
        apellido: 'Solicitante',
        correo: 'nuevo@example.com',
        rol_id: 4,
        sede_id: null,
        estado_invitacion: 'pendiente',
        url_invitacion: 'https://clerk.example/inv/abc',
      }),
    );
    fixture.detectChanges();

    expect(texto()).toContain('invitación pendiente');
    expect(texto()).toContain('https://clerk.example/inv/abc');
    expect(texto()).toContain('Copiar enlace');

    boton('copiar enlace')?.click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(portapapeles).toEqual(['https://clerk.example/inv/abc']);
    expect(texto()).toContain('Enlace copiado');

    httpMock.expectOne(RUTA_USUARIOS).flush([]);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();
  });

  it('AC-2: si Clerk ya tenía identidad, el alta informa «aceptada» y no trae enlace', () => {
    montar([]);
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${URL_API}/usuarios/`).flush(
      invitacion({
        usuario_id: 5,
        nombre: 'Nuevo',
        apellido: 'Solicitante',
        estado_invitacion: 'aceptada',
        url_invitacion: null,
      }),
    );
    fixture.detectChanges();

    expect(texto()).toContain('invitación aceptada');
    expect(texto()).not.toContain('Copiar enlace');

    httpMock.expectOne(RUTA_USUARIOS).flush([]);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();
  });

  it('AC-10: un 422 de motivo/rol se muestra y no cierra el alta', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta({ correo: 'invalido@example.com' });

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${URL_API}/usuarios/`).flush(
      {
        detail: [
          {
            type: 'value_error',
            loc: ['body', 'motivo'],
            msg: 'Value error, el motivo `otro` exige texto',
          },
        ],
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta?.textContent).toContain('motivo');
    expect(boton('crear usuario')).toBeTruthy();
  });

  it('AC-1: un 409 de correo ya vinculado se muestra con el motivo', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta({ correo: 'ya.vinculado@example.com' });

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

  it('AC-2: un 503 de la frontera Clerk es recuperable y no cierra el alta', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta();

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${URL_API}/usuarios/`).flush(
      { detail: 'La frontera Clerk no esta disponible' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    fixture.detectChanges();

    const alerta = (fixture.nativeElement as HTMLElement).querySelector(
      '[role="alert"]',
    );
    expect(alerta?.textContent).toContain('no esta disponible');
    expect(boton('crear usuario')).toBeTruthy();
  });

  it('AC-1: el alta no se envía dos veces mientras está en vuelo', () => {
    montar([]);
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta();

    expect(fixture.componentInstance.formularioCreacion.valid).withContext('formulario válido').toBe(true);
    fixture.componentInstance.guardarCreacion();
    fixture.componentInstance.guardarCreacion();
    fixture.detectChanges();

    const peticion = httpMock.expectOne(`${URL_API}/usuarios/`);
    httpMock.expectNone(`${URL_API}/usuarios/`);
    peticion.flush(
      invitacion({ usuario_id: 5, estado_invitacion: 'pendiente', url_invitacion: null }),
    );
    fixture.detectChanges();
    httpMock.expectOne(RUTA_USUARIOS).flush([]);
    httpMock.expectOne(RUTA_ROLES).flush(ROLES);
    httpMock.expectOne(RUTA_DEPARTAMENTOS).flush(DEPARTAMENTOS);
    httpMock.expectOne(RUTA_SEDES).flush(SEDES);
    fixture.detectChanges();
  });

  it('AC-9: el alta de un Bodeguero con sede la asigna tras crear', () => {
    montar();
    boton('nuevo usuario')?.click();
    fixture.detectChanges();
    rellenarAlta({
      nombre: 'Beto',
      apellido: 'Bodega',
      correo: 'beto@example.com',
      rol_id: 3,
      sede_id: 2,
    });

    boton('crear usuario')?.click();
    fixture.detectChanges();

    httpMock.expectOne(`${URL_API}/usuarios/`).flush(
      invitacion({
        usuario_id: 7,
        nombre: 'Beto',
        apellido: 'Bodega',
        correo: 'beto@example.com',
        rol_id: 3,
        sede_id: null,
        estado_invitacion: 'pendiente',
        url_invitacion: 'https://clerk.example/inv/beto',
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

    expect(texto()).toContain('Sede asignada');
    expect(texto()).toContain('https://clerk.example/inv/beto');
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
    expect(opcionesRolAlta().length).toBe(2);

    identidadFalsa.set(identidad('Superadmin'));
    fixture.detectChanges();
    expect(opcionesRolAlta().length).toBe(3);
  });

  it('AC-8/AC-10: el combo de rol de la edición no ofrece Superadmin a un Administrador', () => {
    montar([usuario()], ROLES_CUATRO);
    boton('editar')?.click();
    fixture.detectChanges();

    expect(opcionesRolEdicion()).toEqual(['Bodeguero', 'Solicitante']);
  });

  it('AC-8/AC-10: al editar un Administrador se conserva visible su rol actual, sin Superadmin', () => {
    montar([usuario({ rol_id: 2, nombre: 'Camila' })], ROLES_CUATRO);
    boton('editar')?.click();
    fixture.detectChanges();

    expect(opcionesRolEdicion()).toEqual([
      'Administrador',
      'Bodeguero',
      'Solicitante',
    ]);
    expect(
      fixture.componentInstance.formularioEdicion.controls.rol_id.value,
    ).toBe(2);
  });

  it('AC-8/AC-10: la edición institucional nunca ofrece Superadmin, ni con identidad Superadmin', () => {
    identidadFalsa.set(identidad('Superadmin'));
    montar([usuario()], ROLES_CUATRO);
    boton('editar')?.click();
    fixture.detectChanges();

    expect(opcionesRolEdicion()).toEqual([
      'Administrador',
      'Bodeguero',
      'Solicitante',
    ]);
  });
});
