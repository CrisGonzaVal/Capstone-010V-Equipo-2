import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { CatalogosTicket, Ticket, TicketCrear } from '../../../shared/interfaces';
import { URL_API } from '../../../shared/config/url-api';

/** HTTP del flujo de tickets. */
@Injectable({ providedIn: 'root' })
export class TicketService {
  private readonly http = inject(HttpClient);

  obtenerCatalogos(): Observable<CatalogosTicket> {
    return this.http.get<CatalogosTicket>(`${URL_API}/tickets/catalogos`);
  }

  obtenerTickets(estadoId?: number): Observable<Ticket[]> {
    let params = new HttpParams();
    if (estadoId !== undefined) {
      params = params.set('estado_id', estadoId);
    }
    return this.http.get<Ticket[]>(`${URL_API}/tickets/`, { params });
  }

  crearTicket(datos: TicketCrear): Observable<Ticket> {
    return this.http.post<Ticket>(`${URL_API}/tickets/`, datos);
  }

  actualizarEstado(ticketId: number, estadoId: number): Observable<Ticket> {
    return this.http.patch<Ticket>(`${URL_API}/tickets/${ticketId}/estado`, {
      estado_id: estadoId,
    });
  }
}