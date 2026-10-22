import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { URL_API } from '../../../shared/config/url-api';
import {
  AdministradorListadoControl,
  CapacidadRespuesta,
  DashboardSaaS,
  InstitucionAltaControlCrear,
  InstitucionAltaControlRespuesta,
  InstitucionControl,
  InstitucionEdicion,
  InstitucionEstadoRespuesta,
  Usuario,
  UsuarioCrear,
  UsuarioEdicionConMotivo,
  UsuarioEstadoConMotivo,
  UsuarioInvitacionRespuesta,
} from '../../../shared/interfaces';

/**
 * HTTP del portal de control (Features 010 y 012).
 *
 * Aprovisionamiento mínimo (010) más la gestión administrativa SaaS (012):
 * listado/detalle/edición de instituciones, activación/desactivación lógica,
 * dashboard global y las seis capacidades funcionales por institución. El cliente
 * solo envía los DTOs de entrada; el esquema, la versión y el estado de
 * institución los deriva el servidor. El Bearer de Clerk lo presenta el
 * interceptor existente. Ningún método decide ámbito ni autorización.
 */
@Injectable({ providedIn: 'root' })
export class ControlService {
  private readonly http = inject(HttpClient);

  private readonly raiz = `${URL_API}/control`;

  aprovisionarInstitucion(
    datos: InstitucionAltaControlCrear,
  ): Observable<InstitucionAltaControlRespuesta> {
    return this.http.post<InstitucionAltaControlRespuesta>(
      `${this.raiz}/instituciones/`,
      datos,
    );
  }

  /** `GET /control/instituciones/` — registro canónico con su estado (AC-1). */
  listarInstituciones(): Observable<InstitucionControl[]> {
    return this.http.get<InstitucionControl[]>(`${this.raiz}/instituciones/`);
  }

  /** `GET /control/instituciones/{id}` — una institución canónica (AC-1). */
  obtenerInstitucion(institucionId: string): Observable<InstitucionControl> {
    return this.http.get<InstitucionControl>(
      `${this.raiz}/instituciones/${institucionId}`,
    );
  }

  /**
   * `PUT /control/instituciones/{id}` — modifica los atributos canónicos; el
   * servidor sincroniza con el espejo tenant solo `institucion_id` + `nombre`
   * (D-1/AC-1). No se envía estado, esquema ni versión.
   */
  editarInstitucion(
    institucionId: string,
    datos: InstitucionEdicion,
  ): Observable<InstitucionControl> {
    return this.http.put<InstitucionControl>(
      `${this.raiz}/instituciones/${institucionId}`,
      datos,
    );
  }

  /** `PATCH /control/instituciones/{id}/estado` — activa o desactiva (AC-2). */
  cambiarEstadoInstitucion(
    institucionId: string,
    activo: boolean,
  ): Observable<InstitucionEstadoRespuesta> {
    return this.http.patch<InstitucionEstadoRespuesta>(
      `${this.raiz}/instituciones/${institucionId}/estado`,
      { activo },
    );
  }

  /** `GET /control/dashboard` — panorama SaaS con atribución por institución (AC-4). */
  obtenerDashboardSaaS(): Observable<DashboardSaaS> {
    return this.http.get<DashboardSaaS>(`${this.raiz}/dashboard`);
  }

  /** `GET /control/instituciones/{id}/capacidades` — las seis capacidades (AC-5). */
  listarCapacidades(institucionId: string): Observable<CapacidadRespuesta[]> {
    return this.http.get<CapacidadRespuesta[]>(
      `${this.raiz}/instituciones/${institucionId}/capacidades`,
    );
  }

  /**
   * `PUT /control/instituciones/{id}/capacidades/{funcion}` — habilita o
   * deshabilita una capacidad (D-6/AC-5). Una función fuera del conjunto cerrado
   * la rechaza el servidor (422).
   */
  actualizarCapacidad(
    institucionId: string,
    funcion: string,
    habilitada: boolean,
  ): Observable<CapacidadRespuesta> {
    return this.http.put<CapacidadRespuesta>(
      `${this.raiz}/instituciones/${institucionId}/capacidades/${funcion}`,
      { habilitada },
    );
  }

  // --- Gobierno de Administradores por institución (Feature 017, D-10) ---

  /**
   * `GET /control/instituciones/{id}/usuarios/` — listado mínimo de
   * Administradores (AC-5). Solo estado persistido; nunca URL ni Clerk.
   */
  listarAdministradores(
    institucionId: string,
  ): Observable<AdministradorListadoControl[]> {
    return this.http.get<AdministradorListadoControl[]>(
      `${this.raiz}/instituciones/${institucionId}/usuarios/`,
    );
  }

  /**
   * `POST /control/instituciones/{id}/usuarios/` — alta de Administrador
   * (D-10). El cliente manda solo el DTO de usuario y el ID institucional de la
   * ruta; el esquema lo deriva el servidor. La URL llega solo en esta respuesta.
   */
  crearAdministrador(
    institucionId: string,
    datos: UsuarioCrear,
  ): Observable<UsuarioInvitacionRespuesta> {
    return this.http.post<UsuarioInvitacionRespuesta>(
      `${this.raiz}/instituciones/${institucionId}/usuarios/`,
      datos,
    );
  }

  /** `PUT .../usuarios/{usuarioId}` — edición motivada (D-7/D-10). */
  editarAdministrador(
    institucionId: string,
    usuarioId: number,
    datos: UsuarioEdicionConMotivo,
  ): Observable<Usuario> {
    return this.http.put<Usuario>(
      `${this.raiz}/instituciones/${institucionId}/usuarios/${usuarioId}`,
      datos,
    );
  }

  /** `PATCH .../usuarios/{usuarioId}/estado` — baja/reactivación motivada (D-7/D-10). */
  cambiarEstadoAdministrador(
    institucionId: string,
    usuarioId: number,
    datos: UsuarioEstadoConMotivo,
  ): Observable<Usuario> {
    return this.http.patch<Usuario>(
      `${this.raiz}/instituciones/${institucionId}/usuarios/${usuarioId}/estado`,
      datos,
    );
  }

  /**
   * `POST .../usuarios/{usuarioId}/invitacion/reenvio` — crea una invitación
   * nueva y entrega la URL solo en esta respuesta (D-4/D-10). Una invitación
   * aceptada o un conflicto de Clerk responde 409 sin cambiar el ID persistido.
   */
  reenviarInvitacionAdministrador(
    institucionId: string,
    usuarioId: number,
  ): Observable<UsuarioInvitacionRespuesta> {
    return this.http.post<UsuarioInvitacionRespuesta>(
      `${this.raiz}/instituciones/${institucionId}/usuarios/${usuarioId}/invitacion/reenvio`,
      {},
    );
  }
}
