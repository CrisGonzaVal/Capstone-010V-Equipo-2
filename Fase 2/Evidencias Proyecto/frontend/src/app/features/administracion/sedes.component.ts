import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { Sede } from '../../shared/interfaces';
import { mensajeDeErrorAdministracion } from './administracion-errores';
import { AdministracionService } from './services/administracion.service';

/**
 * Vista de sedes de la institución (Feature 012, AC-6/AC-11).
 *
 * Lista las sedes del tenant con su estado activo/inactivo, permite crear y
 * editar (nombre y dirección) y desactivar/reactivar de forma lógica y reversible.
 * El 409 de nombre duplicado y el 409 de desactivación con dependencias se
 * muestran con el motivo del servidor. No envía institución ni esquema. Consume
 * el contrato de la Feature 011/012 sin reinterpretarlo.
 */
@Component({
  selector: 'app-administracion-sedes',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './sedes.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SedesComponent implements OnInit {
  private readonly administracion = inject(AdministracionService);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);

  readonly cargando = signal(true);
  readonly sedes = signal<Sede[]>([]);
  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  readonly errorAccion = signal<string | null>(null);

  readonly editando = signal<Sede | null>(null);
  readonly confirmando = signal<Sede | null>(null);
  readonly guardando = signal(false);

  readonly formulario = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    direccion: ['', [Validators.maxLength(200)]],
  });

  readonly formularioEdicion = this.constructorFormulario.group({
    nombre: ['', [Validators.required, Validators.maxLength(100)]],
    direccion: ['', [Validators.maxLength(200)]],
  });

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  crear(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }
    const valores = this.formulario.getRawValue();
    this.guardando.set(true);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);

    this.administracion
      .crearSede({
        nombre: valores.nombre.trim(),
        direccion: valores.direccion.trim() || null,
      })
      .subscribe({
        next: (creada) => {
          this.guardando.set(false);
          this.formulario.reset({ nombre: '', direccion: '' });
          this.sedes.update((lista) => [...lista, creada]);
          this.mensajeExito.set(`Sede «${creada.nombre}» creada.`);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  iniciarEdicion(sede: Sede): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.confirmando.set(null);
    this.formularioEdicion.reset({
      nombre: sede.nombre,
      direccion: sede.direccion ?? '',
    });
    this.editando.set(sede);
  }

  cancelarEdicion(): void {
    this.editando.set(null);
  }

  guardarEdicion(): void {
    const sede = this.editando();
    if (!sede) {
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
      .editarSede(sede.sede_id, {
        nombre: valores.nombre.trim(),
        direccion: valores.direccion.trim() || null,
      })
      .subscribe({
        next: (actualizada) => {
          this.guardando.set(false);
          this.editando.set(null);
          this.reemplazar(actualizada);
          this.mensajeExito.set(`Sede «${actualizada.nombre}» actualizada.`);
        },
        error: (error: HttpErrorResponse) => {
          this.guardando.set(false);
          this.errorAccion.set(mensajeDeErrorAdministracion(error));
        },
      });
  }

  solicitarCambioEstado(sede: Sede): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
    this.editando.set(null);
    this.confirmando.set(sede);
  }

  cancelarCambioEstado(): void {
    this.confirmando.set(null);
  }

  confirmarCambioEstado(): void {
    const sede = this.confirmando();
    if (!sede) {
      return;
    }
    const nuevoEstado = !sede.activo;
    this.guardando.set(true);
    this.errorAccion.set(null);

    this.administracion.cambiarEstadoSede(sede.sede_id, nuevoEstado).subscribe({
      next: (resultado) => {
        this.guardando.set(false);
        this.confirmando.set(null);
        this.sedes.update((lista) =>
          lista.map((item) =>
            item.sede_id === resultado.sede_id
              ? { ...item, activo: resultado.activo }
              : item,
          ),
        );
        this.mensajeExito.set(
          resultado.activo
            ? `Sede «${sede.nombre}» reactivada.`
            : `Sede «${sede.nombre}» desactivada.`,
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

    this.administracion.listarSedes().subscribe({
      next: (sedes) => {
        this.sedes.set(sedes);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.sedes.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorAdministracion(error));
      },
    });
  }

  private reemplazar(actualizada: Sede): void {
    this.sedes.update((lista) =>
      lista.map((item) => (item.sede_id === actualizada.sede_id ? actualizada : item)),
    );
  }
}
