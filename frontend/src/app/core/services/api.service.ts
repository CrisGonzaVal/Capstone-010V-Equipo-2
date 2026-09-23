import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  // Usa 'backend' cuando se ejecute en Docker, o '127.0.0.1:8000' en desarrollo local
  private baseUrl = 'http://localhost:8000/api/v1';

  constructor(private http: HttpClient) {}

  // --- INVENTARIO ---
  getProductos(): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/inventario/productos`);
  }

  getStock(departamentoId?: number): Observable<any[]> {
    const url = departamentoId ? `${this.baseUrl}/inventario/stock?departamento_id=${departamentoId}` : `${this.baseUrl}/inventario/stock`;
    return this.http.get<any[]>(url);
  }

  registrarMovimiento(data: { tipo_movimiento: string; cantidad: number; observacion: string; inventario_id: number }): Observable<any> {
    return this.http.post(`${this.baseUrl}/inventario/movimientos`, data);
  }

  // --- TICKETS ---
  getTickets(): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/tickets/`);
  }

  crearTicket(ticket: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/tickets/`, ticket);
  }

  actualizarEstadoTicket(ticketId: number, estadoId: number): Observable<any> {
    return this.http.patch(`${this.baseUrl}/tickets/${ticketId}/estado`, { estado_id: estadoId });
  }

  // --- USUARIOS ---
  getUsuarios(): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/usuarios/`);
  }
}
