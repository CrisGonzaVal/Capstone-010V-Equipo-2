import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

/**
 * Vista dedicada de acceso denegado (AC-2/AC-15).
 *
 * Es el destino del `RolGuard` cuando la identidad autenticada no tiene el rol
 * permitido. No cierra la sesión ni envía a `/login`: informa del permiso
 * insuficiente y ofrece volver operar en una sección permitida.
 */
@Component({
  selector: 'app-acceso-denegado',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './acceso-denegado.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccesoDenegadoComponent {}
