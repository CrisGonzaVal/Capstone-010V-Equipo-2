import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';

import {
  AdministracionNavComponent,
  resolverEnlaceActivo,
  urlActivaDelRouter,
} from './administracion-nav.component';

/**
 * Layout del área administrativa institucional (Feature 012, T10; panel de
 * pestañas en la enmienda T-17).
 *
 * Contiene la navegación entre las vistas de sedes, departamentos, usuarios y
 * encargados mediante `AdministracionNavComponent` y el `RouterOutlet`, envuelto
 * en el `tabpanel` que lo asocia con la pestaña activa. La sección activa se
 * deriva de la **misma** resolución de `Router.url` que usa la barra, para que
 * `aria-labelledby` nunca apunte a una pestaña distinta de la seleccionada. Es
 * la sección de tenant del Administrador Institucional; el Superadmin administra
 * la plataforma desde `/control`, no desde aquí. Solo presenta: el guard de rol
 * de `app.routes.ts` y la matriz central del backend siguen siendo la autoridad.
 */
@Component({
  selector: 'app-administracion',
  standalone: true,
  imports: [AdministracionNavComponent, RouterOutlet],
  templateUrl: './administracion.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdministracionComponent {
  private readonly router = inject(Router);

  private readonly urlActiva = urlActivaDelRouter(this.router);

  /** Segmento de la sección vigente; compone el `aria-labelledby` del panel. */
  readonly seccionActiva = computed(() => resolverEnlaceActivo(this.urlActiva()).seccion);
}
