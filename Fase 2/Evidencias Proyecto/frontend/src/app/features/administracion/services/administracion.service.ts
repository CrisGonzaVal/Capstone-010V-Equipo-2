import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { URL_API } from '../../../shared/config/url-api';
import {
  AsignacionSedeDepartamentoRespuesta,
  AsignacionSedeUsuarioRespuesta,
  DepartamentoCrear,
  DepartamentoEdicion,
  DepartamentoEstadoRespuesta,
  DepartamentoGestion,
  Encargado,
  Rol,
  Sede,
  SedeCrear,
  SedeEdicion,
  SedeEstadoRespuesta,
  Usuario,
  UsuarioCrear,
  UsuarioEdicion,
  UsuarioEstadoRespuesta,
} from '../../../shared/interfaces';

/**
 * HTTP de las vistas administrativas institucionales (Feature 012, T10).
 *
 * Consume 1:1 los contratos organizacionales de la Feature 011 y el CRUD de la
 * Feature 012: sedes, departamentos, usuarios y encargados del tenant del
 * Administrador. El cliente **nunca** envía institución ni esquema: el ámbito lo
 * resuelve el servidor desde la sesión. El Bearer de Clerk lo presenta el
 * interceptor existente. No decide autorización; el backend es la autoridad
 * (los errores 403/404/409 se muestran tal cual llegan).
 */
@Injectable({ providedIn: 'root' })
export class AdministracionService {
  private readonly http = inject(HttpClient);

  private readonly organizacion = `${URL_API}/organizacion`;
  private readonly usuarios = `${URL_API}/usuarios`;

  // --- Sedes ---

  /** `GET /organizacion/sedes` — sedes del tenant, con su estado (AC-6). */
  listarSedes(): Observable<Sede[]> {
    return this.http.get<Sede[]>(`${this.organizacion}/sedes`);
  }

  /** `POST /organizacion/sedes` — alta; nombre duplicado responde 409 (AC-6). */
  crearSede(datos: SedeCrear): Observable<Sede> {
    return this.http.post<Sede>(`${this.organizacion}/sedes`, datos);
  }

  /** `PUT /organizacion/sedes/{id}` — edición; sede ajena responde 404 (AC-6). */
  editarSede(sedeId: number, datos: SedeEdicion): Observable<Sede> {
    return this.http.put<Sede>(`${this.organizacion}/sedes/${sedeId}`, datos);
  }

  /** `PATCH /organizacion/sedes/{id}/estado` — activa/desactiva (AC-11). */
  cambiarEstadoSede(sedeId: number, activo: boolean): Observable<SedeEstadoRespuesta> {
    return this.http.patch<SedeEstadoRespuesta>(
      `${this.organizacion}/sedes/${sedeId}/estado`,
      { activo },
    );
  }

  // --- Departamentos ---

  /** `GET /organizacion/departamentos` — con sede asignada o su ausencia (AC-7). */
  listarDepartamentos(): Observable<DepartamentoGestion[]> {
    return this.http.get<DepartamentoGestion[]>(`${this.organizacion}/departamentos`);
  }

  /** `POST /organizacion/departamentos` — alta sin sede obligatoria (AC-7). */
  crearDepartamento(datos: DepartamentoCrear): Observable<DepartamentoGestion> {
    return this.http.post<DepartamentoGestion>(
      `${this.organizacion}/departamentos`,
      datos,
    );
  }

  /** `PUT /organizacion/departamentos/{id}` — edición; ajeno 404 (AC-7). */
  editarDepartamento(
    departamentoId: number,
    datos: DepartamentoEdicion,
  ): Observable<DepartamentoGestion> {
    return this.http.put<DepartamentoGestion>(
      `${this.organizacion}/departamentos/${departamentoId}`,
      datos,
    );
  }

  /** `PATCH /organizacion/departamentos/{id}/estado` — activa/desactiva (AC-11). */
  cambiarEstadoDepartamento(
    departamentoId: number,
    activo: boolean,
  ): Observable<DepartamentoEstadoRespuesta> {
    return this.http.patch<DepartamentoEstadoRespuesta>(
      `${this.organizacion}/departamentos/${departamentoId}/estado`,
      { activo },
    );
  }

  /**
   * `PUT /organizacion/departamentos/{id}/sede` — asigna la sede del tenant
   * (AC-7). Solo se ofrecen sedes devueltas por el servidor para el tenant.
   */
  asignarSedeDepartamento(
    departamentoId: number,
    sedeId: number,
  ): Observable<AsignacionSedeDepartamentoRespuesta> {
    return this.http.put<AsignacionSedeDepartamentoRespuesta>(
      `${this.organizacion}/departamentos/${departamentoId}/sede`,
      { sede_id: sedeId },
    );
  }

  // --- Encargados ---

  /** `GET /organizacion/departamentos/{id}/encargados` — asociaciones vigentes (AC-10). */
  listarEncargados(departamentoId: number): Observable<Encargado[]> {
    return this.http.get<Encargado[]>(
      `${this.organizacion}/departamentos/${departamentoId}/encargados`,
    );
  }

  /** `POST /organizacion/departamentos/{id}/encargados` — asocia (AC-10). */
  asociarEncargado(departamentoId: number, usuarioId: number): Observable<Encargado> {
    return this.http.post<Encargado>(
      `${this.organizacion}/departamentos/${departamentoId}/encargados`,
      { usuario_id: usuarioId },
    );
  }

  /** `DELETE /organizacion/departamentos/{id}/encargados/{usuarioId}` — retira (AC-10). */
  retirarEncargado(departamentoId: number, usuarioId: number): Observable<void> {
    return this.http.delete<void>(
      `${this.organizacion}/departamentos/${departamentoId}/encargados/${usuarioId}`,
    );
  }

  // --- Usuarios ---

  /** `GET /usuarios/` — usuarios del tenant (AC-8). */
  listarUsuarios(): Observable<Usuario[]> {
    return this.http.get<Usuario[]>(`${this.usuarios}/`);
  }

  /**
   * `POST /usuarios/` — alta de usuario local (AC-8). El correo debe existir ya en
   * Clerk: si no, responde 422 sin crear fila; si la frontera externa no responde,
   * 503; un correo ya vinculado de forma activa, 409.
   */
  crearUsuario(datos: UsuarioCrear): Observable<Usuario> {
    return this.http.post<Usuario>(`${this.usuarios}/`, datos);
  }

  /** `GET /usuarios/roles` — catálogo de roles para los formularios (AC-8). */
  listarRoles(): Observable<Rol[]> {
    return this.http.get<Rol[]>(`${this.usuarios}/roles`);
  }

  /** `PUT /usuarios/{id}` — edita rol/ámbito; nunca el correo (AC-8). */
  editarUsuario(usuarioId: number, datos: UsuarioEdicion): Observable<Usuario> {
    return this.http.put<Usuario>(`${this.usuarios}/${usuarioId}`, datos);
  }

  /** `PATCH /usuarios/{id}/estado` — activa/desactiva el vínculo local (AC-8/AC-11). */
  cambiarEstadoUsuario(
    usuarioId: number,
    activo: boolean,
  ): Observable<UsuarioEstadoRespuesta> {
    return this.http.patch<UsuarioEstadoRespuesta>(
      `${this.usuarios}/${usuarioId}/estado`,
      { activo },
    );
  }

  /**
   * `PUT /organizacion/usuarios/{id}/sede` — asigna la sede de un Bodeguero
   * (AC-9). Un usuario que no es Bodeguero responde 409 sin mutación.
   */
  asignarSedeUsuario(
    usuarioId: number,
    sedeId: number,
  ): Observable<AsignacionSedeUsuarioRespuesta> {
    return this.http.put<AsignacionSedeUsuarioRespuesta>(
      `${this.organizacion}/usuarios/${usuarioId}/sede`,
      { sede_id: sedeId },
    );
  }
}
