import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { URL_API } from '../../../shared/config/url-api';
import { DashboardAnalitico } from '../../../shared/interfaces';

/**
 * HTTP del dashboard analítico consolidado (Feature 009).
 *
 * Una sola lectura (`GET /dashboard/`) que ya reúne los KPI, el log de alertas y
 * la actividad reciente autorizada. No se envían `institucion_id`,
 * departamento ni cabeceras de ámbito: el ámbito lo resuelve el servidor a
 * partir de la identidad autenticada (D-3). Tampoco se consulta
 * `/inventario/movimientos`: la actividad de la respuesta consolidada respeta
 * los límites de rol (el Solicitante la recibe no disponible).
 */
@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly http = inject(HttpClient);

  obtenerDashboard(): Observable<DashboardAnalitico> {
    return this.http.get<DashboardAnalitico>(`${URL_API}/dashboard/`);
  }
}
