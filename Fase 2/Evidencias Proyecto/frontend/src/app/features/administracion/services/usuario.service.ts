import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Departamento, Institucion, Rol, Usuario } from '../../../shared/interfaces';
import { URL_API } from '../../inventario/services/inventario.service';

/**
 * HTTP de la administracion multi-tenant: usuarios, roles, departamentos e
 * instituciones. `stack.md` agrupa estos cuatro recursos en la feature
 * `administracion`.
 */
@Injectable({ providedIn: 'root' })
export class UsuarioService {
  private readonly http = inject(HttpClient);

  obtenerUsuarios(): Observable<Usuario[]> {
    return this.http.get<Usuario[]>(`${URL_API}/usuarios/`);
  }

  obtenerRoles(): Observable<Rol[]> {
    return this.http.get<Rol[]>(`${URL_API}/usuarios/roles`);
  }

  obtenerDepartamentos(): Observable<Departamento[]> {
    return this.http.get<Departamento[]>(`${URL_API}/usuarios/departamentos`);
  }

  obtenerInstituciones(): Observable<Institucion[]> {
    return this.http.get<Institucion[]>(`${URL_API}/usuarios/instituciones`);
  }
}