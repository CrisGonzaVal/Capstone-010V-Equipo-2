import { Routes } from '@angular/router';

import { ControlSuperadminGuard } from '../../core/guards/control-superadmin.guard';

/**
 * Segmento lazy-loaded del portal `/control` (Feature 010, plan §"Portal Angular").
 *
 * Dos vistas mínimas: el login público con la UI prebuilt de Clerk (`''`, sin
 * guard, para poder iniciar sesión) y el alta protegida por
 * `ControlSuperadminGuard` (`'alta'`), que solo deja pasar al rol exacto
 * `Superadmin`. No publica CRUD de instituciones, usuarios ni permisos
 * (Feature 012).
 */
export const controlRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./control-login.component').then((m) => m.ControlLoginComponent),
    title: 'Portal de control | CompuStock',
  },
  {
    path: 'alta',
    canActivate: [ControlSuperadminGuard],
    loadComponent: () =>
      import('./alta-institucion.component').then((m) => m.AltaInstitucionComponent),
    title: 'Alta de institución | CompuStock',
  },
];
