import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-inventario',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="flex justify-between items-center">
        <div>
          <h2 class="text-2xl font-bold text-slate-800">Gestión de Inventario</h2>
          <p class="text-sm text-slate-500">Control de stock y movimientos en tiempo real (Conectado a FastAPI & PostgreSQL)</p>
        </div>
        <button class="bg-blue-600 hover:bg-blue-700 text-white font-medium px-4 py-2 rounded-lg shadow transition flex items-center space-x-2">
          <span>+ Nuevo Producto</span>
        </button>
      </div>

      <!-- Tabla de Inventario -->
      <div class="bg-white rounded-xl shadow-sm border border-slate-100 overflow-hidden">
        <div class="p-4 border-b border-slate-100 flex items-center justify-between">
          <input type="text" placeholder="Buscar insumos..." class="w-full max-w-md px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <span class="text-sm text-slate-500">Total registros: {{ stockList.length }}</span>
        </div>
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider border-b border-slate-100">
              <th class="py-3 px-6">ID</th>
              <th class="py-3 px-6">Producto</th>
              <th class="py-3 px-6">Ubicación</th>
              <th class="py-3 px-6">Stock Actual</th>
              <th class="py-3 px-6">Stock Mínimo</th>
              <th class="py-3 px-6 text-right">Acciones</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 text-sm text-slate-700">
            <tr *ngFor="let item of stockList" class="hover:bg-slate-50">
              <td class="py-4 px-6 font-medium text-slate-900">{{ item.inventario_id }}</td>
              <td class="py-4 px-6">{{ item.producto?.nombre || 'Producto #' + item.producto_id }}</td>
              <td class="py-4 px-6">{{ item.ubicacion || 'Bodega Central' }}</td>
              <td class="py-4 px-6 font-bold" [ngClass]="{'text-emerald-600': item.stock_actual > 10, 'text-rose-600': item.stock_actual <= 10}">
                {{ item.stock_actual }}
              </td>
              <td class="py-4 px-6 text-slate-500">{{ item.producto?.stock_minimo || 5 }}</td>
              <td class="py-4 px-6 text-right space-x-2">
                <button class="text-blue-600 hover:text-blue-800 font-medium">Registrar Movimiento</button>
              </td>
            </tr>
            <tr *ngIf="stockList.length === 0">
              <td colspan="6" class="py-8 text-center text-slate-400">No hay registros de inventario en la base de datos o el backend no está disponible.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `
})
export class InventarioComponent implements OnInit {
  stockList: any[] = [];

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    this.apiService.getStock().subscribe({
      next: (data) => {
        this.stockList = data;
      },
      error: (err) => {
        console.error('Error al cargar inventario:', err);
      }
    });
  }
}
