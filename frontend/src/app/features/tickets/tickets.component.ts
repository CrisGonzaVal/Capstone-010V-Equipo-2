import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-tickets',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="flex justify-between items-center">
        <div>
          <h2 class="text-2xl font-bold text-slate-800">Sistema de Tickets y Kanban</h2>
          <p class="text-sm text-slate-500">Gestión de solicitudes e insumos entre departamentos</p>
        </div>
        <button class="bg-blue-600 hover:bg-blue-700 text-white font-medium px-4 py-2 rounded-lg shadow transition">
          + Crear Ticket
        </button>
      </div>

      <!-- Tablero Kanban -->
      <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
        <!-- Columna 1: Ingresado -->
        <div class="bg-slate-200/60 p-4 rounded-xl flex flex-col space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-700">INGRESADO</h3>
            <span class="bg-white text-slate-700 text-xs font-bold px-2 py-0.5 rounded-full shadow-sm">2</span>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-rose-600 bg-rose-50 px-2 py-0.5 rounded">ALTA</span>
              <span class="text-xs text-slate-400">#101</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Dpto. Salud</h4>
            <p class="text-xs text-slate-500">Insumos varios: Guantes, Mascarillas, Jeringas</p>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded">BAJA</span>
              <span class="text-xs text-slate-400">#102</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Construcción</h4>
            <p class="text-xs text-slate-500">Materiales: Cemento, Ladrillos</p>
          </div>
        </div>

        <!-- Columna 2: En Preparación -->
        <div class="bg-slate-200/60 p-4 rounded-xl flex flex-col space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-700">EN PREPARACIÓN</h3>
            <span class="bg-white text-slate-700 text-xs font-bold px-2 py-0.5 rounded-full shadow-sm">2</span>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">MEDIA</span>
              <span class="text-xs text-slate-400">#099</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Dpto. Administración</h4>
            <p class="text-xs text-slate-500">Artículos de oficina: Papel, Toner, Carpetas</p>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-rose-600 bg-rose-50 px-2 py-0.5 rounded">ALTA</span>
              <span class="text-xs text-slate-400">#098</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Dpto. IT</h4>
            <p class="text-xs text-slate-500">Componentes: Cable UTP, Monitores</p>
          </div>
        </div>

        <!-- Columna 3: Despachado -->
        <div class="bg-slate-200/60 p-4 rounded-xl flex flex-col space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-700">DESPACHADO</h3>
            <span class="bg-white text-slate-700 text-xs font-bold px-2 py-0.5 rounded-full shadow-sm">1</span>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded">BAJA</span>
              <span class="text-xs text-slate-400">#095</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Dpto. Logística</h4>
            <p class="text-xs text-slate-500">Herramientas: Cajas plásticas, Etiquetas</p>
          </div>
        </div>

        <!-- Columna 4: Entregado -->
        <div class="bg-slate-200/60 p-4 rounded-xl flex flex-col space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-700">ENTREGADO</h3>
            <span class="bg-white text-slate-700 text-xs font-bold px-2 py-0.5 rounded-full shadow-sm">1</span>
          </div>
          <div class="bg-white p-4 rounded-lg shadow-sm border border-slate-200 space-y-2">
            <div class="flex justify-between items-start">
              <span class="text-xs font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">MEDIA</span>
              <span class="text-xs text-slate-400">#090</span>
            </div>
            <h4 class="font-bold text-slate-800 text-sm">Dpto. Ventas</h4>
            <p class="text-xs text-slate-500">Material promocional: Folletos, Banners</p>
          </div>
        </div>
      </div>
    </div>
  `
})
export class TicketsComponent {}
