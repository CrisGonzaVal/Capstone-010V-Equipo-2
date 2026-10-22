import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import {
  DashboardSaaS,
  InstitucionMetricas,
} from '../../shared/interfaces';
import { ControlNavComponent } from './control-nav.component';
import { mensajeDeErrorControl } from './control-errores';
import { ControlService } from './services/control.service';

/** Etiquetas legibles de la taxonomía única de tenant (Feature 017, D-8). */
const ETIQUETAS_TECNICO: Record<string, string> = {
  operativo: 'Operativo',
  'no enrutable': 'No enrutable',
  'no disponible': 'No disponible',
};

const ETIQUETAS_DETALLE: Record<string, string> = {
  institucion_inactiva: 'Institución inactiva',
  tenant_no_resoluble: 'Metadatos/routing no resolubles',
  tenant_no_disponible: 'Tenant no responde',
  version_ausente_o_ilegible: 'Versión ausente o ilegible',
  version_incompatible: 'Versión incompatible',
};

/**
 * Dashboard técnico SaaS del Superadmin (Feature 012, AC-4; taxonomía de la
 * Feature 017, D-8/AC-13/AC-14).
 *
 * Una sola lectura (`GET /control/dashboard`) alimenta los agregados y la tabla
 * por institución. La vista distingue explícitamente **lo conocido** de **lo no
 * disponible**: solo una institución `operativo` presenta conteos; en `no
 * enrutable` y `no disponible` los valores nulos se muestran como «No
 * disponible», nunca como cero. No expone datos personales ni de negocio y solo
 * presenta lo que resuelve el servidor.
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

  readonly totalInstituciones = computed(
    () => this.datos()?.total_instituciones ?? 0,
  );

  readonly totalActivas = computed(
    () => this.datos()?.total_instituciones_activas ?? 0,
  );

  readonly conocidos = computed(() => this.datos()?.conteos_conocidos ?? 0);

  readonly noDisponibles = computed(
    () => this.datos()?.conteos_no_disponibles ?? 0,
  );

  readonly administradoresActivos = computed(
    () => this.datos()?.total_administradores_activos ?? 0,
  );

  readonly administradoresInactivos = computed(
    () => this.datos()?.total_administradores_inactivos ?? 0,
  );

  readonly instituciones = computed(() => this.datos()?.instituciones ?? []);

  readonly usuariosPorRol = computed(
    () => Object.entries(this.datos()?.usuarios_por_rol ?? {}),
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

  etiquetaTecnica(institucion: InstitucionMetricas): string {
    return ETIQUETAS_TECNICO[institucion.estado_tecnico] ?? institucion.estado_tecnico;
  }

  detalleTecnico(institucion: InstitucionMetricas): string | null {
    if (!institucion.detalle_tecnico) {
      return null;
    }
    return ETIQUETAS_DETALLE[institucion.detalle_tecnico] ?? institucion.detalle_tecnico;
  }

  /** `true` si la institución presenta conteos consultados (clase operativa). */
  esOperativa(institucion: InstitucionMetricas): boolean {
    return institucion.estado_tecnico === 'operativo';
  }

  /** Conteo como texto; `null` es «No disponible» y nunca se sustituye por cero. */
  valor(valor: number | null | undefined): string {
    return valor === null || valor === undefined ? 'No disponible' : String(valor);
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
