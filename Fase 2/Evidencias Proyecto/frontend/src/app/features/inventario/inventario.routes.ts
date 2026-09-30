import { Routes } from '@angular/router';

export const inventarioRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./inventario.component').then((m) => m.InventarioComponent),
    title: 'Inventario | CompuStock',
  },
];