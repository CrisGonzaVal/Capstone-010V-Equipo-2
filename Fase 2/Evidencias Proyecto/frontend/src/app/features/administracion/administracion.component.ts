import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-administracion',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div>
        <h2 class="text-2xl font-bold text-slate-800">Administración y Roles</h2>
        <p class="text-sm text-slate-500">Gestión multi-tenant de instituciones, usuarios y permisos</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <!-- Rol 1 -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-800 text-lg">Super Administrador</h3>
            <span class="bg-emerald-100 text-emerald-800 text-xs px-2.5 py-1 rounded-full font-semibold">Activo</span>
          </div>
          <p class="text-sm text-slate-500">Acceso total al sistema multi-tenant y creación de instituciones.</p>
          <div class="pt-4 border-t border-slate-100 flex justify-between items-center text-sm">
            <span class="text-slate-600">Crear Instancias (Instituciones)</span>
            <input type="checkbox" checked class="toggle accent-blue-600 h-4 w-4">
          </div>
        </div>

        <!-- Rol 2 -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-800 text-lg">Administrador de Institución</h3>
            <span class="bg-emerald-100 text-emerald-800 text-xs px-2.5 py-1 rounded-full font-semibold">Activo</span>
          </div>
          <p class="text-sm text-slate-500">Gestión de usuarios y asignación de roles dentro de la sede.</p>
          <div class="space-y-2 pt-2 border-t border-slate-100 text-sm">
            <div class="flex justify-between items-center">
              <span class="text-slate-600">Gestionar Usuarios</span>
              <input type="checkbox" checked class="accent-blue-600 h-4 w-4">
            </div>
            <div class="flex justify-between items-center">
              <span class="text-slate-600">Asignar Roles</span>
              <input type="checkbox" checked class="accent-blue-600 h-4 w-4">
            </div>
          </div>
        </div>

        <!-- Rol 3 -->
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-100 space-y-4">
          <div class="flex justify-between items-center">
            <h3 class="font-bold text-slate-800 text-lg">Bodeguero / Solicitante</h3>
            <span class="bg-emerald-100 text-emerald-800 text-xs px-2.5 py-1 rounded-full font-semibold">Activo</span>
          </div>
          <p class="text-sm text-slate-500">Control de inventario, despacho y creación de tickets de insumos.</p>
          <div class="space-y-2 pt-2 border-t border-slate-100 text-sm">
            <div class="flex justify-between items-center">
              <span class="text-slate-600">Acceso Catálogo CRUD</span>
              <input type="checkbox" checked class="accent-blue-600 h-4 w-4">
            </div>
            <div class="flex justify-between items-center">
              <span class="text-slate-600">Módulo de Tickets</span>
              <input type="checkbox" checked class="accent-blue-600 h-4 w-4">
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class AdministracionComponent {}
