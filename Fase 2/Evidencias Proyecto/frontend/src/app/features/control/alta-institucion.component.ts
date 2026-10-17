import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import {
  InstitucionAltaControlCrear,
  InstitucionAltaControlRespuesta,
} from '../../shared/interfaces';
import { ControlService } from './services/control.service';

/**
 * Alta mínima de institución del portal `/control` (Feature 010, AC-7…AC-9/AC-15).
 *
 * Ligada al DTO `InstitucionAltaControlCrear`: el cliente solo envía los campos
 * de entrada; el nombre de esquema, la versión, el rol y el estado los deriva el
 * servidor. La vista distingue tres estados con señales —carga (`enviando`),
 * error real (`error`) y éxito (`exito`)— y **no finge éxito**: solo informa un
 * resultado operativo cuando la API responde 201. No ofrece CRUD (Feature 012).
 */
@Component({
  selector: 'app-alta-institucion',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './alta-institucion.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AltaInstitucionComponent {
  private readonly controlService = inject(ControlService);
  private readonly constructorFormulario = inject(NonNullableFormBuilder);

  readonly formulario = this.constructorFormulario.group({
    institucion_id: ['', [Validators.required, Validators.maxLength(20)]],
    nombre: ['', [Validators.required, Validators.maxLength(150)]],
    rut: ['', [Validators.maxLength(20)]],
    direccion: ['', [Validators.maxLength(200)]],
    correo_administrador: ['', [Validators.required, Validators.email]],
    nombre_administrador: ['', [Validators.required, Validators.maxLength(100)]],
    apellido_administrador: ['', [Validators.required, Validators.maxLength(100)]],
    departamento_nombre_administrativo: [
      '',
      [Validators.required, Validators.maxLength(100)],
    ],
  });

  /** Alta en vuelo. */
  readonly enviando = signal(false);

  /** Mensaje de error real devuelto por la API (duplicado, Clerk, frontera...). */
  readonly error = signal<string | null>(null);

  /** Resultado operativo del servidor, solo tras un 201. */
  readonly exito = signal<InstitucionAltaControlRespuesta | null>(null);

  aprovisionar(): void {
    this.error.set(null);

    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.exito.set(null);
    this.enviando.set(true);

    this.controlService.aprovisionarInstitucion(this.construirDatos()).subscribe({
      next: (respuesta) => {
        this.enviando.set(false);
        this.exito.set(respuesta);
        this.formulario.reset();
      },
      error: (error: HttpErrorResponse) => {
        this.enviando.set(false);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  /** Arma el DTO con los campos en `snake_case` que espera el backend. */
  private construirDatos(): InstitucionAltaControlCrear {
    const valores = this.formulario.getRawValue();
    return {
      institucion_id: valores.institucion_id.trim(),
      nombre: valores.nombre.trim(),
      rut: valores.rut.trim() || null,
      direccion: valores.direccion.trim() || null,
      correo_administrador: valores.correo_administrador.trim(),
      nombre_administrador: valores.nombre_administrador.trim(),
      apellido_administrador: valores.apellido_administrador.trim(),
      departamento_nombre_administrativo:
        valores.departamento_nombre_administrativo.trim(),
    };
  }

  /**
   * Mensaje legible del fallo real. Prefiere el `detail` textual del backend
   * (409 duplicado, 422 correo inexistente, 503 frontera caída) y, si no es
   * texto (p. ej. error de validación de Pydantic), recurre a un mensaje por
   * código de estado.
   */
  private mensajeDeError(error: HttpErrorResponse): string {
    const detalle = error.error?.detail;
    if (typeof detalle === 'string' && detalle.trim() !== '') {
      return detalle;
    }
    switch (error.status) {
      case 409:
        return 'La institución o el correo ya están registrados.';
      case 422:
        return 'El correo del Administrador no existe en Clerk o los datos no son válidos.';
      case 503:
        return 'No fue posible verificar el correo contra Clerk: el servicio no está disponible.';
      case 401:
      case 403:
        return 'Tu sesión no tiene permiso para aprovisionar instituciones.';
      case 0:
        return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
      default:
        return `No se pudo completar el alta (HTTP ${error.status}).`;
    }
  }
}
