import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { AdministracionNavComponent } from './administracion-nav.component';

/**
 * Layout del área administrativa institucional (Feature 012, T10).
 *
 * Contiene la navegación entre las vistas de sedes, departamentos, usuarios y
 * encargados mediante `AdministracionNavComponent` y el `RouterOutlet`. Es la
 * sección de tenant del Administrador Institucional; el Superadmin administra la
 * plataforma desde `/control`, no desde aquí. Solo presenta: el guard de rol de
 * `app.routes.ts` y la matriz central del backend siguen siendo la autoridad.
 */
@Component({
  selector: 'app-administracion',
  standalone: true,
  imports: [AdministracionNavComponent, RouterOutlet],
  templateUrl: './administracion.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministracionComponent {}
