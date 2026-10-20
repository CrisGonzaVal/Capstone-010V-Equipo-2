import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { InstitucionControl } from '../../shared/interfaces';
import { ControlNavComponent } from './control-nav.component';
import { mensajeDeErrorControl } from './control-errores';
import { ControlService } from './services/control.service';

/**
 * Gestión institucional del portal `/control` (Feature 012, AC-1/AC-2).
 *
 * Lista el registro canónico de control, permite editar los atributos canónicos
 * (`nombre`, `rut`, `direccion`) y desactivar/reactivar la institución de forma
 * lógica y reversible, siempre con confirmación explícita. El alta sigue siendo
 * el flujo de la Feature 010 (enlace «Alta de institución»). El estado
 * (`activo`) lo deriva el servidor: la vista nunca lo envía en la edición. No
 * monta el layout operativo de tenant ni escribe datos de negocio.
 */
@Component({
  selector: 'app-control-instituciones',
  standalone: true,
  imports: [ControlNavComponent, ReactiveFormsModule],
  templateUrl: './instituciones.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InstitucionesComponent implements OnInit {
  private readonly controlService = inject(ControlService);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);
  private readonly router = inject(Router);

  readonly cargando = signal(true);
  readonly instituciones = signal<InstitucionControl[]>([]);
  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);

  /** Institución en edición (o `null`). */
  readonly editando = signal<InstitucionControl | null>(null);

  /** Institución pendiente de confirmar un cambio de estado (o `null`). */
  readonly confirmando = signal<InstitucionControl | null>(null);

  /** Hay una mutación en vuelo (edición o cambio de estado). */
  readonly guardando = signal(false);

  /** Error de la última mutación, sin descartar la lista cargada. */
  readonly errorAccion = signal<string | null>(null);

  readonly formulario = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(150)]],
    rut: ['', [Validators.maxLength(20)]],
    direccion: ['', [Validators.maxLength(200)]],
  });

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  iniciarEdicion(institucion: InstitucionControl): void {
    this.mensajeExito.set(null);
    this.errorAccion.set(null);
    this.confirmando.set(null);
    this.formulario.reset({
      nombre: institucion.nombre,
      rut: institucion.rut ?? '',
      direccion: institucion.direccion ?? '',
    });
    this.editando.set(institucion);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
  }

  guardarEdicion(): void {
    const institucion = this.editando();
    if (!institucion) {
      return;
    }
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const valores = this.formulario.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.controlService
      .editarInstitucion(institucion.institucion_id, {
        nombre: valores.nombre.trim(),
        rut: valores.rut.trim() || null,
        direccion: valores.direccion.trim() || null,
      })
      .subscribe({
        next: (actualizada) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.reemplazar(actualizada);
          this.mensajeExito.set(`Institución «${actualizada.nombre}» actualizada.`);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  solicitarCambioEstado(institucion: InstitucionControl): void {
    this.mensajeExito.set(null);
    this.errorAccion.set(null);
    this.editando.set(null);
    this.confirmando.set(institucion);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
  }

  confirmarCambioEstado(): void {
    const institucion = this.confirmando();
    if (!institucion) {
      return;
    }
    const nuevoEstado = !institucion.activo;
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.controlService
      .cambiarEstadoInstitucion(institucion.institucion_id, nuevoEstado)
      .subscribe({
        next: (resultado) => {
          this.guardando.set(false);
          this.confirmando.set(null);
          this.instituciones.update((lista) =>
            lista.map((item) =>
              item.institucion_id === resultado.institucion_id
                ? { ...item, activo: resultado.activo }
                : item,
            ),
          );
          this.mensajeExito.set(
            resultado.activo
              ? `Institución «${institucion.nombre}» reactivada.`
              : `Institución «${institucion.nombre}» desactivada.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorControl(error));
        },
      });
  }

  /** Navega a la vista de capacidades funcionales de la institución (AC-5). */
  verCapacidades(institucion: InstitucionControl): void {
    void this.router.navigate([
      '/control/instituciones',
      institucion.institucion_id,
      'capacidades',
    ]);
  }

  /** Navega a la gestión de Administradores de la institución (Feature 017, D-10). */
  verAdministradores(institucion: InstitucionControl): void {
    void this.router.navigate([
      '/control/instituciones',
      institucion.institucion_id,
      'administradores',
    ]);
  }

  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    this.controlService.listarInstituciones().subscribe({
      next: (instituciones) => {
        this.instituciones.set(instituciones);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.instituciones.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorControl(error));
      },
    });
  }

  private reemplazar(actualizada: InstitucionControl): void {
    this.instituciones.update((lista) =>
      lista.map((item) =>
        item.institucion_id === actualizada.institucion_id ? actualizada : item,
      ),
    );
  }
}
