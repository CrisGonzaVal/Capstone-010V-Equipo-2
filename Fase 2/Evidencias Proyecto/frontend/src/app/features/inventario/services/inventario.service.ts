import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  Categoria,
  Inventario,
  MovimientoCrear,
  Producto,
  ProductoCrear,
  ProductoExistencia,
  RespuestaMovimiento,
} from '../../../shared/interfaces';
import { URL_API } from '../../../shared/config/url-api';

/**
 * HTTP del catalogo y del stock.
 *
 * Reemplaza a `core/services/api.service.ts`, que mezclaba catalogo, stock y
 * tickets en un unico serviciogod. Ver la desviacion registrada en
 * `docs/spec/features/001-reestructuracion-modular/tasks.md`.
 */
@Injectable({ providedIn: 'root' })
export class InventarioService {
  private readonly http = inject(HttpClient);

  obtenerCategorias(): Observable<Categoria[]> {
    return this.http.get<Categoria[]>(`${URL_API}/inventario/categorias`);
  }

  obtenerProductos(): Observable<Producto[]> {
    return this.http.get<Producto[]>(`${URL_API}/inventario/productos`);
  }

  crearProducto(datos: ProductoCrear): Observable<Producto> {
    return this.http.post<Producto>(`${URL_API}/inventario/productos`, datos);
  }

  obtenerStock(departamentoId?: number): Observable<Inventario[]> {
    let params = new HttpParams();
    if (departamentoId !== undefined) {
      params = params.set('departamento_id', departamentoId);
    }
    return this.http.get<Inventario[]>(`${URL_API}/inventario/stock`, { params });
  }

  /**
   * Catalogo clasificado por producto y por sede.
   *
   * Sin parametros a proposito: la vista filtra en cliente (`spec.md` D-1), asi que
   * la consulta devuelve el catalogo completo una sola vez. Los filtros del
   * endpoint (`q`, `categoria_id`, `departamento_id`, `solo_criticos`) existen para
   * consumidores que necesiten acotar en el servidor.
   */
  obtenerExistencias(): Observable<ProductoExistencia[]> {
    return this.http.get<ProductoExistencia[]>(`${URL_API}/inventario/existencias`);
  }

  registrarMovimiento(datos: MovimientoCrear): Observable<RespuestaMovimiento> {
    return this.http.post<RespuestaMovimiento>(`${URL_API}/inventario/movimientos`, datos);
  }
}