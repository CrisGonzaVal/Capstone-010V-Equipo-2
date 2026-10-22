import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  effect,
  inject,
  input,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import {
  LONGITUD_MAXIMA_TEXTO_MOTIVO,
  MOTIVOS_MUTACION,
} from '../config/motivos-mutacion';

/**
 * Selector accesible del motivo obligatorio de las mutaciones del conjunto
 * cerrado D-7 (Feature 017, D-5/AC-10).
 *
 * Recibe los dos `FormControl` del motivo en lugar de un `FormGroup` para poder
 * anidarse dentro de los formularios existentes sin interferir con su directiva
 * de grupo. No decide autorización ni muta nada: valida en cliente lo mismo que
 * el backend rechazaría con **422** (código del catálogo, `otro` con texto y
 * ≤500 caracteres).
 */
@Component({
  selector: 'app-motivo-selector',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './motivo-selector.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MotivoSelectorComponent {
  readonly codigo = input.required<FormControl<string>>();
  readonly texto = input.required<FormControl<string>>();
  readonly idPrefijo = input.required<string>();

  readonly opciones = MOTIVOS_MUTACION;
  readonly maxTexto = LONGITUD_MAXIMA_TEXTO_MOTIVO;

  private readonly detector = inject(ChangeDetectorRef);

  constructor() {
    // Los controles no son signals: al cambiar su valor desde el formulario
    // padre se marca la vista para volver a evaluar los mensajes de validación.
    effect((onCleanup) => {
      const codigo = this.codigo();
      const texto = this.texto();
      const suscripciones = [
        codigo.valueChanges.subscribe(() => this.detector.markForCheck()),
        texto.valueChanges.subscribe(() => this.detector.markForCheck()),
      ];
      onCleanup(() => suscripciones.forEach((s) => s.unsubscribe()));
    });
  }

  get esOtro(): boolean {
    return this.codigo().value === 'otro';
  }

  get faltaCodigo(): boolean {
    return this.codigo().value === '';
  }

  get textoVacio(): boolean {
    return this.esOtro && this.texto().value.trim() === '';
  }

  get textoExcedido(): boolean {
    return this.texto().value.length > this.maxTexto;
  }
}
