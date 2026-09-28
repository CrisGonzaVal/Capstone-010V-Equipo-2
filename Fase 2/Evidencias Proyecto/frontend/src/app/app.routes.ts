import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { 
    path: 'dashboard', 
    loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent) 
  },
  { 
    path: 'inventario', 
    loadComponent: () => import('./features/inventario/inventario.component').then(m => m.InventarioComponent) 
  },
  { 
    path: 'tickets', 
    loadComponent: () => import('./features/tickets/tickets.component').then(m => m.TicketsComponent) 
  },
  { 
    path: 'administracion', 
    loadComponent: () => import('./features/administracion/administracion.component').then(m => m.AdministracionComponent) 
  },
  { path: '**', redirectTo: 'dashboard' }
];
