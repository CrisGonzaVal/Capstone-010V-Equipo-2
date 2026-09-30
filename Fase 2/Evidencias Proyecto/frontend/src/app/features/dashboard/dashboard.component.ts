import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Resumen de la operacion.
 *
 * **Las cifras son de muestra.** El backend no expone un endpoint de metricas
 * agregadas, asi que cablear el dashboard al `/inventario/stock` mas el conteo
 * de tickets exigiria N peticiones y una regla de agregacion que no esta
 * definida. Llega con el panel de metricas (Feature 004/005).
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  templateUrl: './dashboard.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {}