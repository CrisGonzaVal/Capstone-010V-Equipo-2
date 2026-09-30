import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  Categoria,
  Inventario,
  MovimientoCrear,
  Producto,
  ProductoCrear,
  RespuestaMovimiento,
} from '../../../shared/interfaces';

/** Raiz de la API. Coincide con el `prefix` de `app/api/v1/api.py`. */
export const URL_API = 'http://localhost:8000/api/v1';

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

  registrarMovimiento(datos: MovimientoCrear): Observable<RespuestaMovimiento> {
    return this.http.post<RespuestaMovimiento>(`${URL_API}/inventario/movimientos`, datos);
  }
}