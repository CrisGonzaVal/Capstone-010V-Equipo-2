import { Routes } from '@angular/router';

/**
 * Enrutador raiz. Cada feature se carga con `loadChildren`, de modo que su
 * bundle se descarga solo cuando se navega a ella (AC-10).
 *
 * `canActivate` no se aplica a proposito: los guards existen
 * (`core/guards/`) pero la autenticacion sigue decorativa y no hay login, asi
 * que activarlos dejaria la app inaccesible. Ver la nota en `auth.guard.ts`.
 */
export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'dashboard',
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.dashboardRoutes),
  },
  {
    path: 'inventario',
    loadChildren: () =>
      import('./features/inventario/inventario.routes').then((m) => m.inventarioRoutes),
  },
  {
    path: 'tickets',
    loadChildren: () =>
      import('./features/tickets/tickets.routes').then((m) => m.ticketsRoutes),
  },
  {
    path: 'administracion',
    loadChildren: () =>
      import('./features/administracion/administracion.routes').then(
        (m) => m.administracionRoutes,
      ),
  },
  { path: '**', redirectTo: 'dashboard' },
];