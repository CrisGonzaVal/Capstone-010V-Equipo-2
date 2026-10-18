import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { forkJoin } from 'rxjs';

import { CapacidadRespuesta, InstitucionControl } from '../../shared/interfaces';
import { ControlNavComponent } from './control-nav.component';
import { mensajeDeErrorControl } from './control-errores';
import { ControlService } from './services/control.service';

/** Etiquetas legibles del conjunto cerrado de seis capacidades (D-6/AC-5). */
const ETIQUETAS_CAPACIDAD: Record<string, string> = {
  catalogo: 'Catálogo',
  inventario: 'Inventario',
  tickets: 'Tickets',
  kanban: 'Kanban',
  dashboard: 'Dashboard',
  gestion_organizacional: 'Gestión organizacional',
};

/**
 * Capacidades funcionales por institución (Feature 012, D-6/AC-5).
 *
 * Vista por institución con las seis capacidades del conjunto cerrado y su estado
 * persistido en control. Habilitar/deshabilitar usa `PUT` por función y refleja la
 * respuesta del servidor: una capacidad deshabilitada no se muestra como
 * disponible para el tenant. Es disponibilidad de producto, **no** un permiso de
 * rol: la matriz y el gating backend siguen siendo la autoridad.
 */
@Component({
  selector: 'app-control-capacidades',
  standalone: true,
  imports: [ControlNavComponent],
  templateUrl: './capacidades.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CapacidadesComponent implements OnInit {
  private readonly controlService = inject(ControlService);
  private readonly ruta = inject(ActivatedRoute);

  readonly institucionId = this.ruta.snapshot.paramMap.get('institucionId') ?? '';

  readonly cargando = signal(true);
  readonly institucion = signal<InstitucionControl | null>(null);
  readonly capacidades = signal<CapacidadRespuesta[]>([]);
  readonly mensajeError = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);

  /** Capacidad con una actualización en vuelo (por `funcion`). */
  readonly guardandoFuncion = signal<string | null>(null);

  ngOnInit(): void {
    this.cargar();
  }

  reintentar(): void {
    this.cargar();
  }

  etiqueta(funcion: string): string {
    return ETIQUETAS_CAPACIDAD[funcion] ?? funcion;
  }

  cambiar(capacidad: CapacidadRespuesta): void {
    if (this.guardandoFuncion() !== null) {
      return;
    }
    const habilitada = !capacidad.habilitada;
    this.guardandoFuncion.set(capacidad.funcion);
    this.mensajeError.set(null);
    this.mensajeExito.set(null);

    this.controlService
      .actualizarCapacidad(this.institucionId, capacidad.funcion, habilitada)
      .subscribe({
        next: (actualizada) => {
          this.guardandoFuncion.set(null);
          this.capacidades.update((lista) =>
            lista.map((item) =>
              item.funcion === actualizada.funcion ? actualizada : item,
            ),
          );
          this.mensajeExito.set(
            `Capacidad «${this.etiqueta(actualizada.funcion)}» ${
              actualizada.habilitada ? 'habilitada' : 'deshabilitada'
            }.`,
          );
        },
        error: (error: HttpErrorResponse) => {
          this.guardandoFuncion.set(null);
          this.mensajeError.set(mensajeDeErrorControl(error));
        },
      });
  }

  private cargar(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    forkJoin({
      institucion: this.controlService.obtenerInstitucion(this.institucionId),
      capacidades: this.controlService.listarCapacidades(this.institucionId),
    }).subscribe({
      next: ({ institucion, capacidades }) => {
        this.institucion.set(institucion);
        this.capacidades.set(capacidades);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.institucion.set(null);
        this.capacidades.set([]);
        this.cargando.set(false);
        this.mensajeError.set(mensajeDeErrorControl(error));
      },
    });
  }
}
