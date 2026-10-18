import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import { DashboardSaaS, InstitucionMetricas } from '../../shared/interfaces';
import { ControlNavComponent } from './control-nav.component';
import { mensajeDeErrorControl } from './control-errores';
import { ControlService } from './services/control.service';

/**
 * Dashboard SaaS del Superadmin (Feature 012, AC-4).
 *
 * Una sola lectura (`GET /control/dashboard`) alimenta el KPI de instituciones
 * activas y la tabla de instituciones con atribución inequívoca. Las
 * instituciones desactivadas aparecen identificadas (`activo=false`) y sin
 * métricas actuales (`sedes`/`usuarios_por_rol` en `null`): no se les atribuyen
 * cifras. La vista solo presenta; el agregado completo (o su fallo explícito) lo
 * resuelve el servidor.
 */
@Component({
  selector: 'app-control-dashboard-saas',
  standalone: true,
  imports: [ControlNavComponent],
  templateUrl: './dashboard-saas.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardSaasComponent implements OnInit {
  private readonly controlService = inject(ControlService);

  readonly cargando = signal(true);
  readonly datos = signal<DashboardSaaS | null>(null);
  readonly mensajeError = signal<string | null>(null);

  readonly totalActivas = computed(
    () => this.datos()?.total_instituciones_activas ?? 0,
  );

  readonly instituciones = computed(
    () => this.datos()?.instituciones ?? [],
  );

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  /** Etiquetas legibles de los roles hallados en las métricas del DTO. */
  rolesDe(institucion: InstitucionMetricas): Array<[string, number]> {
    return Object.entries(institucion.usuarios_por_rol ?? {});
  }

  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    this.controlService.obtenerDashboardSaaS().subscribe({
      next: (datos) => {
        this.datos.set(datos);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.datos.set(null);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorControl(error));
      },
    });
  }
}
