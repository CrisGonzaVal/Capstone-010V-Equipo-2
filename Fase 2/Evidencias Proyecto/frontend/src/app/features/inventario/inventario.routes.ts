import { Routes } from '@angular/router';

export const inventarioRoutes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./inventario.component').then((m) => m.InventarioComponent),
    title: 'Inventario | CompuStock',
  },
  {
    // Detalle de producto (Feature 019, D-8/§8): espejo de `:ticketId` en
    // `tickets.routes.ts`. La sección `/inventario` ya está protegida por
    // `AutenticacionGuard` + `RolGuard` con `ROLES_INVENTARIO` en
    // `app.routes.ts`; los guards no se duplican aquí.
    path: ':productoId',
    loadComponent: () =>
      import('./producto-detalle.component').then((m) => m.ProductoDetalleComponent),
    title: 'Detalle del producto | CompuStock',
  },
];
