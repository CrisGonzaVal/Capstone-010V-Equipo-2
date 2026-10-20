import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';

import { copiarAlPortapapeles } from '../utils/portapapeles';

/**
 * Enlace de invitación de un solo uso (Feature 017, D-4/AC-5).
 *
 * Solo se monta cuando la respuesta inmediata de alta/reenvío trajo
 * `url_invitacion`; al navegar o recargar deja de existir porque el enlace nunca
 * se persiste ni se publica en listados. Ofrece copia explícita y el texto
 * visible del enlace para copiarlo manualmente si el portapapeles falla.
 */
@Component({
  selector: 'app-enlace-invitacion',
  standalone: true,
  templateUrl: './enlace-invitacion.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EnlaceInvitacionComponent {
  readonly url = input.required<string>();
  readonly titulo = input('Enlace de invitación');

  readonly copiado = signal(false);
  readonly errorCopia = signal(false);

  async copiar(): Promise<void> {
    this.copiado.set(false);
    this.errorCopia.set(false);
    const exito = await copiarAlPortapapeles(this.url());
    this.copiado.set(exito);
    this.errorCopia.set(!exito);
  }
}
