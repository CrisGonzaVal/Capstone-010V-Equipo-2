import { Routes } from '@angular/router';

export const ticketsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./tickets.component').then((m) => m.TicketsComponent),
    title: 'Tickets | CompuStock',
  },
  {
    // Detalle del ticket (Feature 013, D-13/AC-24): todas las mutaciones del
    // ciclo de vida viven aquí, no en el tablero (D-14).
    path: ':ticketId',
    loadComponent: () =>
      import('./ticket-detalle.component').then((m) => m.TicketDetalleComponent),
    title: 'Detalle del ticket | CompuStock',
  },
];
