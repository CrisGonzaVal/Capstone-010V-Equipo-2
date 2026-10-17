import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { URL_API } from '../../../shared/config/url-api';
import {
  InstitucionAltaControlCrear,
  InstitucionAltaControlRespuesta,
} from '../../../shared/interfaces';

/**
 * HTTP del portal de control (Feature 010, D-7).
 *
 * Única operación del portal mínimo: solicitar el alta de una institución y su
 * primer Administrador. El cliente solo envía el DTO de entrada; el nombre de
 * esquema, la versión, el rol y el estado los deriva el servidor. El Bearer de
 * Clerk lo presenta el interceptor existente. No hay CRUD aquí (Feature 012).
 */
@Injectable({ providedIn: 'root' })
export class ControlService {
  private readonly http = inject(HttpClient);

  aprovisionarInstitucion(
    datos: InstitucionAltaControlCrear,
  ): Observable<InstitucionAltaControlRespuesta> {
    return this.http.post<InstitucionAltaControlRespuesta>(
      `${URL_API}/control/instituciones/`,
      datos,
    );
  }
}
