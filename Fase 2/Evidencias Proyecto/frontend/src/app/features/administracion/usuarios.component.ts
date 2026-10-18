import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { puedeAsignarRol } from '../../core/auth/roles';
import { AutenticacionService } from '../../core/services/auth.service';
import {
  DepartamentoGestion,
  Rol,
  Sede,
  Usuario,
} from '../../shared/interfaces';
import { mensajeDeErrorAdministracion } from './administracion-errores';
import { AdministracionService } from './services/administracion.service';

const _BODEGUERO = 'Bodeguero';

/**
 * Vista de usuarios locales de la institución (Feature 012, AC-8/AC-9/AC-11).
 *
 * Lista los usuarios del tenant con su rol, departamento y sede aplicable
 * (Bodeguero), y permite editar (nombre, apellido, rol y departamento —nunca el
 * correo), desactivar/reactivar el vínculo local (el 409 por ser encargado se
 * muestra con el motivo) y asignar la sede de un Bodeguero escogiendo solo entre
 * las sedes del tenant.
 *
 * El estado activo/inactivo y la sede del Bodeguero llegan del listado
 * `GET /usuarios/` (que los publica desde la Feature 012) y se mantienen
 * localmente tras cada mutación: la vista muestra el estado real —activo o
 * inactivo— y la sede asignada o su ausencia explícita.
 */
@Component({
  selector: 'app-administracion-usuarios',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './usuarios.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UsuariosComponent implements OnInit {
  private readonly administracion = inject(AdministracionService);
  private readonly autenticacion = inject(AutenticacionService);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);

  readonly cargando = signal(true);
  readonly usuarios = signal<Usuario[]>([]);
  readonly roles = signal<Rol[]>([]);
  readonly departamentos = signal<DepartamentoGestion[]>([]);
  readonly sedes = signal<Sede[]>([]);

  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  readonly errorAccion = signal<string | null>(null);

  readonly editando = signal<Usuario | null>(null);
  readonly confirmando = signal<Usuario | null>(null);
  readonly asignandoSede = signal<Usuario | null>(null);
  readonly sedeSeleccion = signal<number | null>(null);
  readonly guardando = signal(false);

  /** `true` mientras el formulario de alta de usuario está abierto (AC-8). */
  readonly creando = signal(false);

  /** Rol del usuario resuelto por `rol_id` contra el catálogo de roles. */
  readonly rolesPorId = computed(
    () => new Map(this.roles().map((rol) => [rol.rol_id, rol.nombre_rol])),
  );

  /**
   * Rol de la identidad activa (`/auth/me`). Reactivo a la sesión: si cambia el
   * usuario autenticado, el formulario de alta recalcula sus opciones.
   */
  readonly rolActual = computed(() => this.autenticacion.identidad()?.rol ?? null);

  /**
   * Roles que la identidad activa puede asignar en el **alta** (D-6/AC-10): el
   * Administrador solo `Bodeguero`/`Solicitante`; el Superadmin, los cuatro.
   *
   * Es una alineación de interfaz con la regla del backend
   * (`_validar_rol_asignable`): el catálogo de roles compartido sigue llegando
   * completo (se usa para mostrar el rol de cada usuario), pero el combo de alta
   * solo ofrece lo asignable. La autoridad real permanece en la API, que sigue
   * respondiendo 403 a un rol no asignable.
   */
  readonly rolesAsignables = computed(() =>
    this.roles().filter((rol) => puedeAsignarRol(this.rolActual(), rol.nombre_rol)),
  );

  readonly formularioEdicion = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    apellido: ['', [Validators.required, Validators.maxLength(100)]],
    rol_id: [0, [Validators.required, Validators.min(1)]],
    departamento_id: [0, [Validators.required, Validators.min(1)]],
  });

  /**
   * Alta de usuario local (AC-8): nombre, apellido y correo (identidad Clerk ya
   * existente), rol y departamento del tenant. La sede solo aplica a un Bodeguero
   * y se ofrece entre las sedes del tenant; se asigna tras crear la fila local.
   */
  readonly formularioCreacion = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    apellido: ['', [Validators.required, Validators.maxLength(100)]],
    correo: ['', [Validators.required, Validators.email, Validators.maxLength(150)]],
    rol_id: [0, [Validators.required, Validators.min(1)]],
    departamento_id: [0, [Validators.required, Validators.min(1)]],
    sede_id: [null as number | null],
  });

  /** Rol elegido en el formulario de alta; reactivo a los cambios del control. */
  private readonly rolCreacion = toSignal(
    this.formularioCreacion.controls.rol_id.valueChanges,
    { initialValue: 0 },
  );

  /** `true` si el rol elegido para el alta es Bodeguero (habilita la sede). */
  readonly creacionEsBodeguero = computed(
    () => this.nombreRol(this.rolCreacion()) === _BODEGUERO,
  );

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  nombreRol(rolId: number): string | null {
    return this.rolesPorId().get(rolId) ?? null;
  }

  nombreDepartamento(departamentoId: number): string | null {
    return (
      this.departamentos().find((d) => d.departamento_id === departamentoId)
        ?.nombre_dep ?? null
    );
  }

  nombreSede(sedeId: number | null | undefined): string | null {
    if (sedeId === null || sedeId === undefined) {
      return null;
    }
    return this.sedes().find((sede) => sede.sede_id === sedeId)?.nombre ?? null;
  }

  esBodeguero(usuario: Usuario): boolean {
    return this.nombreRol(usuario.rol_id) === _BODEGUERO;
  }

  iniciarEdicion(usuario: Usuario): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.confirmando.set(null);
    this.asignandoSede.set(null);
    this.formularioEdicion.reset({
      nombre: usuario.nombre,
      apellido: usuario.apellido,
      rol_id: usuario.rol_id,
      departamento_id: usuario.departamento_id,
    });
    this.editando.set(usuario);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
  }

  /** Abre el formulario de alta con valores por defecto del tenant (AC-8). */
  abrirCreacion(): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.confirmando.set(null);
    this.asignandoSede.set(null);
    this.formularioCreacion.reset({
      nombre: '',
      apellido: '',
      correo: '',
      rol_id: this.rolesAsignables()[0]?.rol_id ?? 0,
      departamento_id: this.departamentos()[0]?.departamento_id ?? 0,
      sede_id: null,
    });
    this.creando.set(true);
  }

  cancelarCreacion(): void {
    this.creando.set(false);
  }

  /** Envía el alta; tras el éxito recarga el listado (AC-8). */
  guardarCreacion(): void {
    if (this.formularioCreacion.invalid) {
      this.formularioCreacion.markAllAsTouched();
      return;
    }
    const valores = this.formularioCreacion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .crearUsuario({
        nombre: valores.nombre.trim(),
        apellido: valores.apellido.trim(),
        correo: valores.correo.trim(),
        departamento_id: valores.departamento_id,
        rol_id: valores.rol_id,
      })
      .subscribe({
        next: (creado) => {
          const sedeElegida = valores.sede_id;
          if (this.creacionEsBodeguero() && sedeElegida !== null) {
            this.asignarSedeTrasAlta(creado, sedeElegida);
            return;
          }
          this.guardando.set(false);
          this.creando.set(false);
          this.mensajeExito.set(
            `Usuario «${creado.nombre} ${creado.apellido}» creado.`,
          );
          this.cargar();
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  /** Asigna la sede elegida en el alta; el error no revierte la creación. */
  private asignarSedeTrasAlta(creado: Usuario, sedeId: number): void {
    this.administracion.asignarSedeUsuario(creado.usuario_id, sedeId).subscribe({
      next: () => {
        this.guardando.set(false);
        this.creando.set(false);
        this.mensajeExito.set(
          `Usuario «${creado.nombre} ${creado.apellido}» creado con su sede.`,
        );
        this.cargar();
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.creando.set(false);
        this.errorAccion.set(
          `El usuario se creó, pero no se pudo asignar su sede. ${mensajeDeErrorAdministracion(error)}`,
        );
        this.cargar();
      },
    });
  }

  guardarEdicion(): void {
    const usuario = this.editando();
    if (!usuario) {
      return;
    }
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }
    const valores = this.formularioEdicion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .editarUsuario(usuario.usuario_id, {
        nombre: valores.nombre.trim(),
        apellido: valores.apellido.trim(),
        rol_id: valores.rol_id,
        departamento_id: valores.departamento_id,
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.reemplazar({
            ...usuario,
            ...actualizado,
            sede_id: usuario.sede_id,
            activo: usuario.activo,
          });
          this.mensajeExito.set(
            `Usuario «${actualizado.nombre} ${actualizado.apellido}» actualizado.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  iniciarAsignacionSede(usuario: Usuario): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.confirmando.set(null);
    this.sedeSeleccion.set(usuario.sede_id ?? null);
    this.asignandoSede.set(usuario);
  }

  cancelarAsignacionSede(): void {
    this.asignandoSede.set(null);
    this.sedeSeleccion.set(null);
  }

  cambiarSeleccionSede(evento: Event): void {
    const valor = (evento.target as HTMLSelectElement).value;
    this.sedeSeleccion.set(valor === '' ? null : Number(valor));
  }

  guardarSede(): void {
    const usuario = this.asignandoSede();
    const sedeId = this.sedeSeleccion();
    if (!usuario || sedeId === null) {
      return;
    }
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion.asignarSedeUsuario(usuario.usuario_id, sedeId).subscribe({
      next: (resultado) => {
        this.guardando.set(false);
        this.asignandoSede.set(null);
        this.sedeSeleccion.set(null);
        this.reemplazar({ ...usuario, sede_id: resultado.sede_id });
        this.mensajeExito.set(
          `Sede «${this.nombreSede(resultado.sede_id) ?? resultado.sede_id}» asignada a «${usuario.nombre} ${usuario.apellido}».`,
        );
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  solicitarCambioEstado(usuario: Usuario): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.asignandoSede.set(null);
    this.confirmando.set(usuario);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
  }

  confirmarCambioEstado(): void {
    const usuario = this.confirmando();
    if (!usuario) {
      return;
    }
    const nuevoEstado = !(usuario.activo ?? true);
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion.cambiarEstadoUsuario(usuario.usuario_id, nuevoEstado).subscribe({
      next: (resultado) => {
        this.guardando.set(false);
        this.confirmando.set(null);
        this.usuarios.update((lista) =>
          lista.map((item) =>
            item.usuario_id === resultado.usuario_id
              ? { ...item, activo: resultado.activo }
              : item,
          ),
        );
        this.mensajeExito.set(
          resultado.activo
            ? `Usuario «${usuario.nombre} ${usuario.apellido}» reactivado.`
            : `Usuario «${usuario.nombre} ${usuario.apellido}» desactivado.`,
        );
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    forkJoin({
      usuarios: this.administracion.listarUsuarios(),
      roles: this.administracion.listarRoles(),
      departamentos: this.administracion.listarDepartamentos(),
      sedes: this.administracion.listarSedes(),
    }).subscribe({
      next: ({ usuarios, roles, departamentos, sedes }) => {
        this.usuarios.set(usuarios);
        this.roles.set(roles);
        this.departamentos.set(departamentos);
        this.sedes.set(sedes);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.usuarios.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private reemplazar(actualizado: Usuario): void {
    this.usuarios.update((lista) =>
      lista.map((item) =>
        item.usuario_id === actualizado.usuario_id ? actualizado : item,
      ),
    );
  }
}
