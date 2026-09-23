import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <!-- Tarjetas de Resumen -->
      <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-500">Productos en Stock</p>
            <h3 class="text-3xl font-bold text-slate-800 mt-1">1,240</h3>
          </div>
          <div class="bg-blue-50 text-blue-600 p-3 rounded-lg text-2xl">📦</div>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-500">Tickets Activos</p>
            <h3 class="text-3xl font-bold text-amber-600 mt-1">14</h3>
          </div>
          <div class="bg-amber-50 text-amber-600 p-3 rounded-lg text-2xl">🎫</div>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-500">Departamentos</p>
            <h3 class="text-3xl font-bold text-emerald-600 mt-1">6</h3>
          </div>
          <div class="bg-emerald-50 text-emerald-600 p-3 rounded-lg text-2xl">🏢</div>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 flex items-center justify-between">
          <div>
            <p class="text-sm font-medium text-slate-500">Alertas de Stock</p>
            <h3 class="text-3xl font-bold text-rose-600 mt-1">2</h3>
          </div>
          <div class="bg-rose-50 text-rose-600 p-3 rounded-lg text-2xl">⚠️</div>
        </div>
      </div>

      <!-- Sección de Estado del Sistema y Mapa / Resumen -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 bg-white p-6 rounded-xl shadow-sm border border-slate-100">
          <h3 class="text-lg font-bold text-slate-800 mb-4">Estado de Sedes Descentralizadas</h3>
          <div class="bg-slate-100 h-64 rounded-lg flex items-center justify-center text-slate-500 border border-dashed border-slate-300">
            [ Mapa de Sedes / Métricas Geográficas en Tiempo Real ]
          </div>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100">
          <h3 class="text-lg font-bold text-slate-800 mb-4">Actividad Reciente</h3>
          <div class="space-y-4">
            <div class="flex items-start space-x-3 text-sm">
              <span class="bg-blue-100 text-blue-800 p-1 rounded">📦</span>
              <div>
                <p class="font-medium text-slate-800">Entrada de Insumos</p>
                <p class="text-slate-500 text-xs">Se añadieron 200 lápices pasta azul.</p>
              </div>
            </div>
            <div class="flex items-start space-x-3 text-sm">
              <span class="bg-emerald-100 text-emerald-800 p-1 rounded">🎫</span>
              <div>
                <p class="font-medium text-slate-800">Nuevo Ticket Creado</p>
                <p class="text-slate-500 text-xs">Dpto. Salud solicitó insumos médicos.</p>
              </div>
            </div>
            <div class="flex items-start space-x-3 text-sm">
              <span class="bg-rose-100 text-rose-800 p-1 rounded">⚠️</span>
              <div>
                <p class="font-medium text-slate-800">Stock Crítico</p>
                <p class="text-slate-500 text-xs">Resmas de papel bajo el mínimo.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class DashboardComponent {}
