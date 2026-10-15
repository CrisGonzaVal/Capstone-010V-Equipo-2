import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';

import { DashboardAnalitico } from '../../shared/interfaces';
import { DashboardService } from './services/dashboard.service';

/**
 * Dashboard analítico consolidado (Feature 009).
 *
 * Una sola lectura (`GET /dashboard/`) alimenta los cuatro KPI, el log de
 * alertas y la actividad reciente. La vista solo presenta: **no** decide ámbito
 * ni autorización. En particular, la sección de actividad se gobierna por el
 * booleano `actividad_disponible` que resuelve el servidor; con `false` (caso del
 * Solicitante) no se pinta y no se hace ninguna lectura del historial de
 * movimientos. Todo valor sale del DTO real, sin cifras de muestra.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './dashboard.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit {
  private readonly dashboardService = inject(DashboardService);

  readonly cargando = signal(true);
  readonly datos = signal<DashboardAnalitico | null>(null);
  readonly mensajeError = signal<string | null>(null);

  /** KPI del DTO, o `null` mientras no hay lectura. */
  readonly kpi = computed(() => this.datos()?.kpi ?? null);

  /** Log de alertas del DTO (lista vacía si no hay lectura). */
  readonly alertas = computed(() => this.datos()?.alertas ?? []);

  /** `true` cuando el servidor autoriza la sección de actividad al rol. */
  readonly actividadDisponible = computed(
    () => this.datos()?.actividad_disponible ?? false,
  );

  /** Movimientos recientes del DTO (vacíos para el Solicitante). */
  readonly actividad = computed(() => this.datos()?.actividad_movimientos ?? []);

  ngOnInit(): void {
    this.cargar();
  }

  /** Reintenta la lectura tras un error visible. */
  reintentar(): void {
    this.cargar();
  }

  /**
   * Una sola carga: el DTO consolidado es la unidad. Ante fallo se descartan los
   * datos previos (nada de cifras ficticias) y se publica un mensaje recuperable.
   */
  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    this.dashboardService.obtenerDashboard().subscribe({
      next: (datos) => {
        this.datos.set(datos);
        this.cargando.set(false);
      },
      error: () => {
        this.datos.set(null);
        this.cargando.set(false);
        this.mensajeError.set(
          'No se pudo cargar el dashboard. Revisa la conexión e inténtalo de nuevo.',
        );
      },
    });
  }
}
