import { Routes } from '@angular/router';

import { ControlSuperadminGuard } from '../../core/guards/control-superadmin.guard';

/**
 * Segmento lazy-loaded del portal `/control` (Features 010 y 012).
 *
 * Vistas: el login público con la UI prebuilt de Clerk (`''`, sin guard, para
 * poder iniciar sesión); el alta de institución (`'alta'`); y la gestión
 * administrativa SaaS del Superadmin (Feature 012): dashboard global
 * (`'dashboard'`), gestión institucional (`'instituciones'`) y capacidades
 * funcionales por institución (`'instituciones/:institucionId/capacidades'`).
 * Todas las rutas de gestión exigen el rol exacto `Superadmin` mediante
 * `ControlSuperadminGuard`. No monta el layout operativo de tenant ni permite
 * escoger esquema. La gestión administrativa institucional (sedes, departamentos,
 * usuarios y encargados) vive en `/administracion` (Feature 012, T10).
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
  {
    path: 'dashboard',
    canActivate: [ControlSuperadminGuard],
    loadComponent: () =>
      import('./dashboard-saas.component').then((m) => m.DashboardSaasComponent),
    title: 'Dashboard SaaS | CompuStock',
  },
  {
    path: 'instituciones',
    canActivate: [ControlSuperadminGuard],
    loadComponent: () =>
      import('./instituciones.component').then((m) => m.InstitucionesComponent),
    title: 'Instituciones | CompuStock',
  },
  {
    path: 'instituciones/:institucionId/capacidades',
    canActivate: [ControlSuperadminGuard],
    loadComponent: () =>
      import('./capacidades.component').then((m) => m.CapacidadesComponent),
    title: 'Capacidades institucionales | CompuStock',
  },
];
