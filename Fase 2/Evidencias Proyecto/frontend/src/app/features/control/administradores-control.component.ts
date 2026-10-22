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
import { ActivatedRoute, RouterLink } from '@angular/router';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { EnlaceInvitacionComponent } from '../../shared/components/enlace-invitacion.component';
import { MotivoSelectorComponent } from '../../shared/components/motivo-selector.component';
import {
  construirMotivo,
  esMotivoCompleto,
  etiquetaEstadoInvitacion,
} from '../../shared/config/motivos-mutacion';
import { AdministradorListadoControl } from '../../shared/interfaces';
import { nuevaClaveIdempotencia } from '../../shared/utils/idempotencia';
import { ControlNavComponent } from './control-nav.component';
import { mensajeDeErrorControl } from './control-errores';
import { ControlService } from './services/control.service';

/**
 * Gobierno de Administradores de una institución (Feature 017, D-10/AC-8).
 *
 * Listado mínimo de Administradores (`usuario_id`, nombre, apellido, correo,
 * vínculo local y estado de invitación persistido), alta con invitación, edición
 * y baja/reactivación motivadas y reenvío con URL de un solo uso. El cliente solo
 * envía el `institucion_id` de la ruta: **nunca** esquema ni tenant; el servidor
 * los deriva desde control. La URL vive en memoria del componente y el listado
 * jamás la contiene.
 *
 * Limitación conocida (reportada): el contrato D-10 no expone un catálogo de
 * departamentos/roles del tenant para el Superadmin, así que el alta y la
 * edición piden los identificadores numéricos (`rol_id`, `departamento_id`) que
 * valida el backend. No se inventan endpoints ni se consulta Clerk.
 */
@Component({
  selector: 'app-control-administradores',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    ControlNavComponent,
    MotivoSelectorComponent,
    EnlaceInvitacionComponent,
  ],
  templateUrl: './administradores-control.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministradoresControlComponent implements OnInit {
  private readonly controlService = inject(ControlService);
  private readonly ruta = inject(ActivatedRoute);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);

  readonly institucionId = this.ruta.snapshot.paramMap.get('institucionId') ?? '';

  readonly cargando = signal(true);
  readonly administradores = signal<AdministradorListadoControl[]>([]);
  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  readonly errorAccion = signal<string | null>(null);
  readonly guardando = signal(false);

  readonly creando = signal(false);
  readonly editando = signal<AdministradorListadoControl | null>(null);
  readonly confirmando = signal<AdministradorListadoControl | null>(null);

  /** URL de invitación recibida en la última alta/reenvío (solo memoria). */
  readonly enlaceInvitacion = signal<{ url: string; nombre: string } | null>(null);

  /**
   * Alta de Administrador. El rol debe ser `Administrador` en el tenant y el
   * departamento pertenecer a la institución; ambos los valida el servidor. No
   * se ofrece catálogo porque D-10 no publica uno para el Superadmin.
   */
  readonly formularioAlta = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    apellido: ['', [Validators.required, Validators.maxLength(100)]],
    correo: ['', [Validators.required, Validators.email, Validators.maxLength(150)]],
    rol_id: [0, [Validators.required, Validators.min(1)]],
    departamento_id: [0, [Validators.required, Validators.min(1)]],
  });

  readonly formularioEdicion = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    apellido: ['', [Validators.required, Validators.maxLength(100)]],
    rol_id: [0, [Validators.required, Validators.min(1)]],
    departamento_id: [0, [Validators.required, Validators.min(1)]],
  });

  readonly motivoEdicion = this.constructorFormulario.group({
    codigo: [''],
    texto: [''],
  });

  readonly motivoEstado = this.constructorFormulario.group({
    codigo: [''],
    texto: [''],
  });

  /** Valores reactivos de los motivos (signals, no getters). */
  private readonly valorMotivoEdicion = toSignal(this.motivoEdicion.valueChanges, {
    initialValue: { codigo: '', texto: '' },
  });
  private readonly valorMotivoEstado = toSignal(this.motivoEstado.valueChanges, {
    initialValue: { codigo: '', texto: '' },
  });

  readonly motivoEdicionCompleto = computed(() => {
    const motivo = this.valorMotivoEdicion();
    return esMotivoCompleto(motivo.codigo ?? '', motivo.texto ?? '');
  });

  readonly motivoEstadoCompleto = computed(() => {
    const motivo = this.valorMotivoEstado();
    return esMotivoCompleto(motivo.codigo ?? '', motivo.texto ?? '');
  });

  private idempotenciaEdicion: string | null = null;
  private idempotenciaEstado: string | null = null;

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  estadoInvitacion(administrador: AdministradorListadoControl): string {
    return etiquetaEstadoInvitacion(administrador.estado_invitacion);
  }

  /** El reenvío aplica solo a invitaciones no aceptadas y con mapa conocido (D-4). */
  puedeReenviar(administrador: AdministradorListadoControl): boolean {
    return ['pendiente', 'revocada', 'expirada'].includes(
      administrador.estado_invitacion,
    );
  }

  abrirCreacion(): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.editando.set(null);
    this.confirmando.set(null);
    this.formularioAlta.reset({
      nombre: '',
      apellido: '',
      correo: '',
      rol_id: 0,
      departamento_id: 0,
    });
    this.creando.set(true);
  }

  cancelarCreacion(): void {
    this.creando.set(false);
  }

  guardarCreacion(): void {
    if (this.guardando()) {
      return;
    }
    if (this.formularioAlta.invalid) {
      this.formularioAlta.markAllAsTouched();
      return;
    }
    const valores = this.formularioAlta.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.enlaceInvitacion.set(null);

    this.controlService
      .crearAdministrador(this.institucionId, {
        nombre: valores.nombre.trim(),
        apellido: valores.apellido.trim(),
        correo: valores.correo.trim(),
        rol_id: valores.rol_id,
        departamento_id: valores.departamento_id,
      })
      .subscribe({
        next: (creado) => {
          this.guardando.set(false);
          this.creando.set(false);
          if (creado.url_invitacion) {
            this.enlaceInvitacion.set({
              url: creado.url_invitacion,
              nombre: `${creado.nombre} ${creado.apellido}`,
            });
          }
          this.mensajeExito.set(
            creado.url_invitacion
              ? `Administrador «${creado.nombre} ${creado.apellido}» creado con invitación pendiente. Copia el enlace ahora.`
              : `Administrador «${creado.nombre} ${creado.apellido}» creado con invitación ${etiquetaEstadoInvitacion(creado.estado_invitacion)}.`,
          );
          this.cargar(false);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  iniciarEdicion(administrador: AdministradorListadoControl): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.creando.set(false);
    this.confirmando.set(null);
    this.formularioEdicion.reset({
      nombre: administrador.nombre,
      apellido: administrador.apellido,
      rol_id: 0,
      departamento_id: 0,
    });
    this.motivoEdicion.reset({ codigo: '', texto: '' });
    this.idempotenciaEdicion = nuevaClaveIdempotencia();
    this.editando.set(administrador);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
    this.idempotenciaEdicion = null;
  }

  guardarEdicion(): void {
    const administrador = this.editando();
    if (!administrador || this.guardando()) {
      return;
    }
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }
    if (!this.motivoEdicionCompleto()) {
      this.motivoEdicion.markAllAsTouched();
      return;
    }
    const valores = this.formularioEdicion.getRawValue();
    const motivo = this.motivoEdicion.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.controlService
      .editarAdministrador(this.institucionId, administrador.usuario_id, {
        nombre: valores.nombre.trim(),
        apellido: valores.apellido.trim(),
        rol_id: valores.rol_id,
        departamento_id: valores.departamento_id,
        motivo: construirMotivo(motivo.codigo, motivo.texto),
        idempotencia: this.idempotenciaEdicion,
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.idempotenciaEdicion = null;
          this.reemplazar({
            ...administrador,
            nombre: actualizado.nombre,
            apellido: actualizado.apellido,
            activo: actualizado.activo ?? administrador.activo,
            estado_invitacion:
              actualizado.estado_invitacion ?? administrador.estado_invitacion,
          });
          this.mensajeExito.set(
            `Administrador «${actualizado.nombre} ${actualizado.apellido}» actualizado.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  solicitarCambioEstado(administrador: AdministradorListadoControl): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);
    this.creando.set(false);
    this.editando.set(null);
    this.motivoEstado.reset({ codigo: '', texto: '' });
    this.idempotenciaEstado = nuevaClaveIdempotencia();
    this.confirmando.set(administrador);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
    this.idempotenciaEstado = null;
  }

  confirmarCambioEstado(): void {
    const administrador = this.confirmando();
    if (!administrador || this.guardando()) {
      return;
    }
    if (!this.motivoEstadoCompleto()) {
      this.motivoEstado.markAllAsTouched();
      return;
    }
    const motivo = this.motivoEstado.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.controlService
      .cambiarEstadoAdministrador(this.institucionId, administrador.usuario_id, {
        activo: !administrador.activo,
        motivo: construirMotivo(motivo.codigo, motivo.texto),
        idempotencia: this.idempotenciaEstado,
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.confirmando.set(null);
          this.idempotenciaEstado = null;
          this.motivoEstado.reset({ codigo: '', texto: '' });
          this.reemplazar({
            ...administrador,
            activo: actualizado.activo ?? !administrador.activo,
            estado_invitacion:
              actualizado.estado_invitacion ?? administrador.estado_invitacion,
          });
          this.mensajeExito.set(
            actualizado.activo === false
              ? `Administrador «${administrador.nombre} ${administrador.apellido}» desactivado.`
              : `Administrador «${administrador.nombre} ${administrador.apellido}» reactivado.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  /** Reenvía la invitación; la URL nueva solo se muestra en esta respuesta. */
  reenviar(administrador: AdministradorListadoControl): void {
    if (this.guardando()) {
      return;
    }
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.enlaceInvitacion.set(null);

    this.controlService
      .reenviarInvitacionAdministrador(this.institucionId, administrador.usuario_id)
      .subscribe({
        next: (respuesta) => {
          this.guardando.set(false);
          if (respuesta.url_invitacion) {
            this.enlaceInvitacion.set({
              url: respuesta.url_invitacion,
              nombre: `${respuesta.nombre} ${respuesta.apellido}`,
            });
          }
          this.reemplazar({
            ...administrador,
            estado_invitacion: respuesta.estado_invitacion ?? 'pendiente',
            activo: respuesta.activo ?? administrador.activo,
          });
          this.mensajeExito.set(
            `Invitación de «${administrador.nombre} ${administrador.apellido}» reenviada. Copia el enlace ahora.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  private cargar(mostrarCarga = true): void {
    if (mostrarCarga) {
      this.cargando.set(true);
    }
    this.mensajeError.set(null);

    this.controlService.listarAdministradores(this.institucionId).subscribe({
      next: (administradores) => {
        this.administradores.set(administradores);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.administradores.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorControl(error));
      },
    });
  }

  private reemplazar(actualizado: AdministradorListadoControl): void {
    this.administradores.update((lista) =>
      lista.map((item) =>
        item.usuario_id === actualizado.usuario_id ? actualizado : item,
      ),
    );
  }
}
