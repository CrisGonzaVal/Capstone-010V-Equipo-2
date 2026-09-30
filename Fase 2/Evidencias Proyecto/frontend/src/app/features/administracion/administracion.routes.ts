import { Routes } from '@angular/router';

export const administracionRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./administracion.component').then((m) => m.AdministracionComponent),
    title: 'Administracion | CompuStock',
  },
];