import { Route, Routes } from '@angular/router';

import { ROLES_ADMINISTRATIVOS, ROLES_TODOS } from './core/auth/roles';
import { AutenticacionGuard } from './core/guards/auth.guard';
import { RolGuard } from './core/guards/role.guard';

/**
 * Enrutador raiz. Cada feature se carga con `loadChildren`, de modo que su
 * bundle se descarga solo cuando se navega a ella (AC-10).
 *
 * Las rutas de negocio exigen sesión de Clerk (`AutenticacionGuard`) y, tras
 * ella, el rol permitido (`RolGuard`, Feature 007): sin sesión se va a `/login`
 * con retorno; con sesión pero sin rol se muestra el estado dedicado de acceso
 * denegado, sin cerrar sesión. `/login` queda fuera del guard para poder iniciar
 * sesión. La app no publica ruta de registro: la instancia de Clerk es solo
 * Email y el autoregsitro está cerrado.
 */

/**
 * Declara una sección de negocio con sesión + rol. Los roles viven en la misma
 * variable que alimenta al `RolGuard` y a `data.roles`, para que la matriz no
 * se pueda desincronizar entre lo que se exige y lo que se documenta.
 */
function seccionProtegida(
  roles: readonly string[],
): Pick<Route, 'canActivate' | 'data'> {
  return {
    canActivate: [AutenticacionGuard, RolGuard(roles)],
    data: { roles },
  };
}

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent),
    title: 'Iniciar sesión | CompuStock',
  },
  {
    path: 'dashboard',
    ...seccionProtegida(ROLES_TODOS),
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.dashboardRoutes),
  },
  {
    path: 'inventario',
    ...seccionProtegida(ROLES_TODOS),
    loadChildren: () =>
      import('./features/inventario/inventario.routes').then((m) => m.inventarioRoutes),
  },
  {
    path: 'tickets',
    ...seccionProtegida(ROLES_TODOS),
    loadChildren: () =>
      import('./features/tickets/tickets.routes').then((m) => m.ticketsRoutes),
  },
  {
    path: 'administracion',
    ...seccionProtegida(ROLES_ADMINISTRATIVOS),
    loadChildren: () =>
      import('./features/administracion/administracion.routes').then(
        (m) => m.administracionRoutes,
      ),
  },
  {
    path: 'acceso-denegado',
    loadComponent: () =>
      import('./features/acceso-denegado/acceso-denegado.component').then(
        (m) => m.AccesoDenegadoComponent,
      ),
    title: 'Acceso denegado | CompuStock',
  },
  { path: '**', redirectTo: 'dashboard' },
];
