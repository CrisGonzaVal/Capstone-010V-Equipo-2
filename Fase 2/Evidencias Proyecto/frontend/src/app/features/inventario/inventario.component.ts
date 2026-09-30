import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';

import { Inventario } from '../../shared/interfaces';
import { InventarioService } from './services/inventario.service';

@Component({
  selector: 'app-inventario',
  standalone: true,
  templateUrl: './inventario.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventarioComponent implements OnInit {
  private readonly inventarioService = inject(InventarioService);

  readonly listaStock = signal<Inventario[]>([]);
  readonly cargando = signal(true);
  readonly mensajeError = signal<string | null>(null);

  ngOnInit(): void {
    this.cargarStock();
  }

  /** Umbral contra el que se pinta de rojo el stock. */
  esStockCritico(registro: Inventario): boolean {
    return registro.stock_actual <= (registro.producto?.stock_minimo ?? 0);
  }

  private cargarStock(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    this.inventarioService.obtenerStock().subscribe({
      next: (stock) => {
        this.listaStock.set(stock);
        this.cargando.set(false);
      },
      error: (fallo) => {
        this.listaStock.set([]);
        this.cargando.set(false);
        this.mensajeError.set(
          `No se pudo contactar el backend (${fallo.status ?? 'sin respuesta'}). ` +
            'Revisa que el servicio en el puerto 8000 este levantado.',
        );
      },
    });
  }
}