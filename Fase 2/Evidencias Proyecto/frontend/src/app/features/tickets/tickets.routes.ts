import { Routes } from '@angular/router';

export const ticketsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./tickets.component').then((m) => m.TicketsComponent),
    title: 'Tickets y Kanban | CompuStock',
  },
];