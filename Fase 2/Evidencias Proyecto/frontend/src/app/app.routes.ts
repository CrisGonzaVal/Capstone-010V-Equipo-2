import { Routes } from '@angular/router';

import { AutenticacionGuard } from './core/guards/auth.guard';

/**
 * Enrutador raiz. Cada feature se carga con `loadChildren`, de modo que su
 * bundle se descarga solo cuando se navega a ella (AC-10).
 *
 * Las rutas de negocio exigen sesión de Clerk (`AutenticacionGuard`); `/login`
 * queda fuera del guard para poder iniciar sesión. La app no publica ruta de
 * registro: la instancia de Clerk es solo Email y el autoregsitro está cerrado.
 */
export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent),
    title: 'Iniciar sesión | CompuStock',
  },
  {
    path: 'dashboard',
    canActivate: [AutenticacionGuard],
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.dashboardRoutes),
  },
  {
    path: 'inventario',
    canActivate: [AutenticacionGuard],
    loadChildren: () =>
      import('./features/inventario/inventario.routes').then((m) => m.inventarioRoutes),
  },
  {
    path: 'tickets',
    canActivate: [AutenticacionGuard],
    loadChildren: () =>
      import('./features/tickets/tickets.routes').then((m) => m.ticketsRoutes),
  },
  {
    path: 'administracion',
    canActivate: [AutenticacionGuard],
    loadChildren: () =>
      import('./features/administracion/administracion.routes').then(
        (m) => m.administracionRoutes,
      ),
  },
  { path: '**', redirectTo: 'dashboard' },
];
