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
import { EnlaceInvitacionComponent } from '../../shared/components/enlace-invitacion.component';
import { MotivoSelectorComponent } from '../../shared/components/motivo-selector.component';
import {
  esMotivoCompleto,
  construirMotivo,
  etiquetaEstadoInvitacion,
} from '../../shared/config/motivos-mutacion';
import {
  DepartamentoGestion,
  Rol,
  Sede,
  Usuario,
  UsuarioInvitacionRespuesta,
} from '../../shared/interfaces';
import { nuevaClaveIdempotencia } from '../../shared/utils/idempotencia';
import { mensajeDeErrorAdministracion } from './administracion-errores';
import { AdministracionService } from './services/administracion.service';

const _BODEGUERO = 'Bodeguero';

/**
 * Roles cuyo reenvío de invitación autoriza el Administrador institucional
 * (Feature 017, D-10/AC-9). Espejo de `_ROLES_ASIGNABLES_ADMINISTRADOR` del
 * backend: la frontera real la aplica la API (403 para cualquier otro rol).
 */
const _ROLES_REENVIABLES = ['Bodeguero', 'Solicitante'];

/**
 * Vista de usuarios locales de la institución (Feature 012, AC-8/AC-9/AC-11;
 * ampliada por Feature 017 con invitaciones y motivos).
 *
 * Lista los usuarios del tenant con su rol, departamento y sede aplicable
 * (Bodeguero). Desde la Feature 017 muestra **dos conceptos separados**: el
 * vínculo local activo/inactivo y el estado persistido de invitación
 * (`pendiente`/`aceptada`/`revocada`/`expirada`/`no disponible`). El alta puede
 * devolver una invitación nueva; su URL se muestra solo en la respuesta
 * inmediata (en memoria del componente) y nunca en el listado. Editar y
 * cambiar estado exigen motivo del catálogo D-7 cuando hay cambio efectivo.
 *
 * Desde T12 ofrece el **reenvío ordinario** (`POST /usuarios/{id}/invitacion/
 * reenvio`) a Bodegueros/Solicitantes de la institución, solo con vínculo local
 * activo y sin invitación aceptada, y copia el enlace nuevo sin persistirlo.
 * Reactivar sigue siendo una operación distinta (`PATCH .../estado` con motivo):
 * esta vista no reenvía al reactivar, solo deja disponible el reenvío después
 * (D-4, §5 regla 7).
 */

@Component({
  selector: 'app-administracion-usuarios',
  standalone: true,
  imports: [ReactiveFormsModule, MotivoSelectorComponent, EnlaceInvitacionComponent],
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

  /**
   * Enlace de invitación recibido en la respuesta inmediata del alta
   * (Feature 017, D-4). Vive solo en memoria: al navegar o recargar desaparece.
   */
  readonly enlaceInvitacion = signal<{ url: string; nombre: string } | null>(null);

  /** `true` mientras hay un reenvío de invitación en vuelo (anti doble envío). */
  readonly reenviando = signal(false);

  /**
   * Usuario recién reactivado (Feature 017, §5 regla 7). Sirve para recordar en
   * la tarjeta que la reactivación **no** reenvía la invitación y que el envío
   * de un enlace nuevo es una acción separada.
   */
  readonly sugerenciaReenvio = signal<number | null>(null);

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
   */
  readonly rolesAsignables = computed(() =>
    this.roles().filter((rol) => puedeAsignarRol(this.rolActual(), rol.nombre_rol)),
  );

  /**
   * Roles del combo de **edición** (Feature 007, D-6/AC-10; Feature 017, AC-9).
   *
   * Ofrece los mismos roles asignables que el alta —un Administrador nunca ve
   * `Superadmin` ni puede promover a `Administrador`— y conserva el rol actual
   * del usuario editado aunque no sea asignable, para que el combo muestre el
   * valor persistido al editar a otro Administrador. `Superadmin` se excluye
   * siempre: es una identidad de control, no un rol de tenant, y esta vista solo
   * gestiona usuarios institucionales (Feature 017, AC-9/D-10).
   */
  readonly rolesEdicion = computed(() => {
    const usuario = this.editando();
    return this.roles().filter(
      (rol) =>
        rol.nombre_rol !== 'Superadmin' &&
        (puedeAsignarRol(this.rolActual(), rol.nombre_rol) ||
          rol.rol_id === usuario?.rol_id),
    );
  });

  readonly formularioEdicion = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    apellido: ['', [Validators.required, Validators.maxLength(100)]],
    rol_id: [0, [Validators.required, Validators.min(1)]],
    departamento_id: [0, [Validators.required, Validators.min(1)]],
  });

  /** Motivo de la edición (Feature 017, D-5/D-7). */
  readonly motivoEdicion = this.constructorFormulario.group({
    codigo: [''],
    texto: [''],
  });

  /** Motivo de la baja/reactivación (Feature 017, D-5/D-7). */
  readonly motivoEstado = this.constructorFormulario.group({
    codigo: [''],
    texto: [''],
  });

  /** Valores reactivos de los formularios con motivo (signals, no getters). */
  private readonly valorEdicion = toSignal(this.formularioEdicion.valueChanges, {
    initialValue: this.formularioEdicion.getRawValue(),
  });
  private readonly valorMotivoEdicion = toSignal(this.motivoEdicion.valueChanges, {
    initialValue: { codigo: '', texto: '' },
  });
  private readonly valorMotivoEstado = toSignal(this.motivoEstado.valueChanges, {
    initialValue: { codigo: '', texto: '' },
  });

  /** `true` si el formulario de edición cambió algún atributo efectivo. */
  readonly hayCambiosEdicion = computed(() => {
    const usuario = this.editando();
    if (!usuario) {
      return false;
    }
    const valores = this.valorEdicion();
    return (
      (valores.nombre ?? '').trim() !== usuario.nombre ||
      (valores.apellido ?? '').trim() !== usuario.apellido ||
      valores.rol_id !== usuario.rol_id ||
      valores.departamento_id !== usuario.departamento_id
    );
  });

  /** `true` si el motivo de la edición puede enviarse tal como está. */
  readonly motivoEdicionCompleto = computed(() => {
    const motivo = this.valorMotivoEdicion();
    return esMotivoCompleto(motivo.codigo ?? '', motivo.texto ?? '');
  });

  /** `true` si el motivo del cambio de estado puede enviarse tal como está. */
  readonly motivoEstadoCompleto = computed(() => {
    const motivo = this.valorMotivoEstado();
    return esMotivoCompleto(motivo.codigo ?? '', motivo.texto ?? '');
  });

  /**
   * Alta de usuario local (AC-8): nombre, apellido y correo, rol y departamento
   * del tenant. Desde la Feature 017 el backend invita (o reutiliza una
   * invitación/identidad) y su resultado se muestra al usuario.
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

  /** Clave de idempotencia de la mutación en curso (se reutiliza en reintentos). */
  private idempotenciaEdicion: string | null = null;
  private idempotenciaEstado: string | null = null;

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

  /** Etiqueta legible del estado persistido de invitación (AC-5). */
  estadoInvitacion(usuario: Usuario): string {
    return etiquetaEstadoInvitacion(usuario.estado_invitacion);
  }

  /** `true` si el estado persistido es `aceptada` (no se reenvía). */
  invitacionAceptada(usuario: Usuario): boolean {
    return usuario.estado_invitacion === 'aceptada';
  }

  /** `true` si el rol del usuario admite reenvío por el Administrador (AC-9). */
  esReenviable(usuario: Usuario): boolean {
    const rol = this.nombreRol(usuario.rol_id);
    return rol !== null && _ROLES_REENVIABLES.includes(rol);
  }

  /**
   * `true` si se ofrece «Reenviar invitación» (Feature 017, D-4/D-10/AC-6).
   *
   * Exige vínculo local activo (el reenvío nunca reactiva), rol
   * Bodeguero/Solicitante y una invitación no aceptada. Una invitación
   * aceptada no se reenvía; `revocada`/`expirada`/`pendiente`/`no disponible`
   * sí admiten una nueva.
   */
  puedeReenviar(usuario: Usuario): boolean {
    return (
      usuario.activo === true &&
      this.esReenviable(usuario) &&
      !this.invitacionAceptada(usuario)
    );
  }

  /**
   * `true` si el reenvío está bloqueado solo por el vínculo inactivo: la vista
   * indica que primero hay que reactivar con motivo (operaciones separadas).
   */
  requiereReactivarParaReenviar(usuario: Usuario): boolean {
    return (
      usuario.activo !== true &&
      this.esReenviable(usuario) &&
      !this.invitacionAceptada(usuario)
    );
  }

  iniciarEdicion(usuario: Usuario): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.sugerenciaReenvio.set(null);
    this.confirmando.set(null);
    this.asignandoSede.set(null);
    this.formularioEdicion.reset({
      nombre: usuario.nombre,
      apellido: usuario.apellido,
      rol_id: usuario.rol_id,
      departamento_id: usuario.departamento_id,
    });
    this.motivoEdicion.reset({ codigo: '', texto: '' });
    this.idempotenciaEdicion = nuevaClaveIdempotencia();
    this.editando.set(usuario);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
    this.idempotenciaEdicion = null;
  }

  /** Abre el formulario de alta con valores por defecto del tenant (AC-8). */
  abrirCreacion(): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.sugerenciaReenvio.set(null);
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
    this.enlaceInvitacion.set(null);
  }

  /** Envía el alta; al volver muestra el estado de invitación y su enlace si vino. */
  guardarCreacion(): void {
    if (this.guardando()) {
      return;
    }
    if (this.formularioCreacion.invalid) {
      this.formularioCreacion.markAllAsTouched();
      return;
    }
    const valores = this.formularioCreacion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.enlaceInvitacion.set(null);

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
          this.creando.set(false);
          if (creado.url_invitacion) {
            this.enlaceInvitacion.set({
              url: creado.url_invitacion,
              nombre: `${creado.nombre} ${creado.apellido}`,
            });
          }
          const sedeElegida = valores.sede_id;
          if (this.creacionEsBodeguero() && sedeElegida !== null) {
            this.asignarSedeTrasAlta(creado, sedeElegida);
            return;
          }
          this.guardando.set(false);
          this.mensajeExito.set(this.mensajeDeAlta(creado));
          this.cargar();
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  /** Asigna la sede elegida en el alta; el error no revierte la creación. */
  private asignarSedeTrasAlta(
    creado: UsuarioInvitacionRespuesta,
    sedeId: number,
  ): void {
    this.administracion.asignarSedeUsuario(creado.usuario_id, sedeId).subscribe({
      next: () => {
        this.guardando.set(false);
        this.mensajeExito.set(
          `${this.mensajeDeAlta(creado)} Sede asignada.`,
        );
        this.cargar();
      },
      error: (error: HttpErrorResponse) => {
        this.guardando.set(false);
        this.errorAccion.set(
          `El usuario se creó, pero no se pudo asignar su sede. ${mensajeDeErrorAdministracion(error)}`,
        );
        this.cargar();
      },
    });
  }

  /** Mensaje del alta según el estado persistido y si trajo enlace inmediato. */
  private mensajeDeAlta(creado: UsuarioInvitacionRespuesta): string {
    const nombre = `«${creado.nombre} ${creado.apellido}»`;
    if (creado.url_invitacion) {
      return `Usuario ${nombre} creado con invitación pendiente. Copia el enlace ahora: no volverá a mostrarse.`;
    }
    if (creado.estado_invitacion === 'aceptada') {
      return `Usuario ${nombre} creado y vinculado a una identidad existente (invitación aceptada).`;
    }
    return `Usuario ${nombre} creado. Estado de invitación: ${etiquetaEstadoInvitacion(creado.estado_invitacion)}.`;
  }

  guardarEdicion(): void {
    const usuario = this.editando();
    if (!usuario || this.guardando()) {
      return;
    }
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }
    const valores = this.formularioEdicion.getRawValue();
    const cambia = this.hayCambiosEdicion();
    if (cambia && !this.motivoEdicionCompleto()) {
      this.motivoEdicion.markAllAsTouched();
      return;
    }
    const motivo = this.motivoEdicion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .editarUsuario(usuario.usuario_id, {
        nombre: valores.nombre.trim(),
        apellido: valores.apellido.trim(),
        rol_id: valores.rol_id,
        departamento_id: valores.departamento_id,
        ...(cambia
          ? {
              motivo: construirMotivo(motivo.codigo, motivo.texto),
              idempotencia: this.idempotenciaEdicion,
            }
          : {}),
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.idempotenciaEdicion = null;
          this.reemplazar({
            ...usuario,
            ...actualizado,
            sede_id: usuario.sede_id,
            activo: usuario.activo,
            estado_invitacion: usuario.estado_invitacion,
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
    this.enlaceInvitacion.set(null);
    this.sugerenciaReenvio.set(null);
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
    if (!usuario || sedeId === null || this.guardando()) {
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
    this.enlaceInvitacion.set(null);
    this.sugerenciaReenvio.set(null);
    this.editando.set(null);
    this.asignandoSede.set(null);
    this.motivoEstado.reset({ codigo: '', texto: '' });
    this.idempotenciaEstado = nuevaClaveIdempotencia();
    this.confirmando.set(usuario);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
    this.idempotenciaEstado = null;
  }

  confirmarCambioEstado(): void {
    const usuario = this.confirmando();
    if (!usuario || this.guardando()) {
      return;
    }
    if (!this.motivoEstadoCompleto()) {
      this.motivoEstado.markAllAsTouched();
      return;
    }
    const motivo = this.motivoEstado.getRawValue();
    const nuevoEstado = !(usuario.activo ?? true);
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion
      .cambiarEstadoUsuario(usuario.usuario_id, {
        activo: nuevoEstado,
        motivo: construirMotivo(motivo.codigo, motivo.texto),
        idempotencia: this.idempotenciaEstado,
      })
      .subscribe({
        next: (resultado) => {
          this.guardando.set(false);
          this.confirmando.set(null);
          this.idempotenciaEstado = null;
          this.motivoEstado.reset({ codigo: '', texto: '' });
          this.usuarios.update((lista) =>
            lista.map((item) =>
              item.usuario_id === resultado.usuario_id
                ? { ...item, activo: resultado.activo }
                : item,
            ),
          );
          if (resultado.activo) {
            // Reactivar no reenvía la invitación: son operaciones separadas
            // (Feature 017, D-4; §5 regla 7). Se deja el reenvío disponible.
            this.sugerenciaReenvio.set(resultado.usuario_id);
            this.mensajeExito.set(
              `Usuario «${usuario.nombre} ${usuario.apellido}» reactivado. La reactivación no reenvía la invitación: usa «Reenviar invitación» si necesitas un enlace nuevo.`,
            );
            return;
          }
          this.sugerenciaReenvio.set(null);
          this.mensajeExito.set(
            `Usuario «${usuario.nombre} ${usuario.apellido}» desactivado.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  /**
   * Reenvía la invitación de un Bodeguero/Solicitante (Feature 017, T12).
   *
   * La URL nueva solo vive en esta respuesta: se monta en `enlaceInvitacion`
   * (en memoria) y desaparece al cambiar de acción o navegar. Un 409 (aceptada,
   * vínculo inactivo, conflicto de Clerk) o un 503 de la frontera se muestran
   * con el mensaje de la administración; no se inventa enlace.
   */
  reenviarInvitacion(usuario: Usuario): void {
    if (this.reenviando()) {
      return;
    }
    this.reenviando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.sugerenciaReenvio.set(null);

    this.administracion.reenviarInvitacionUsuario(usuario.usuario_id).subscribe({
      next: (respuesta) => {
        this.reenviando.set(false);
        if (respuesta.url_invitacion) {
          this.enlaceInvitacion.set({
            url: respuesta.url_invitacion,
            nombre: `${respuesta.nombre} ${respuesta.apellido}`,
          });
        }
        this.reemplazar({
          ...usuario,
          activo: respuesta.activo ?? usuario.activo,
          estado_invitacion: respuesta.estado_invitacion ?? 'pendiente',
        });
        this.mensajeExito.set(
          `Invitación de «${usuario.nombre} ${usuario.apellido}» reenviada. Copia el enlace ahora: no volverá a mostrarse.`,
        );
      },
      error: (error: HttpErrorResponse) => {
        this.reenviando.set(false);
        this.errorAccion.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private cargar(): void {    this.cargando.set(true);
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
