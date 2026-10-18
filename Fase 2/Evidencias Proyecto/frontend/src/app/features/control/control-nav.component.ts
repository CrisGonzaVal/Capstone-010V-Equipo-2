import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

interface EnlaceControl {
  readonly ruta: string;
  readonly etiqueta: string;
}

/**
 * Navegación interna del portal `/control` (Feature 012, T9).
 *
 * Barra de secciones del portal SaaS del Superadmin: dashboard global, gestión de
 * instituciones y alta. Es solo navegación; la autorización real la resuelve el
 * backend ante cada petición y el `ControlSuperadminGuard` ante cada ruta. No
 * monta el layout operativo de tenant ni ofrece selector de esquema.
 */
@Component({
  selector: 'app-control-nav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './control-nav.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ControlNavComponent {
  readonly enlaces: readonly EnlaceControl[] = [
    { ruta: '/control/dashboard', etiqueta: 'Dashboard SaaS' },
    { ruta: '/control/instituciones', etiqueta: 'Instituciones' },
    { ruta: '/control/alta', etiqueta: 'Alta de institución' },
  ];
}
