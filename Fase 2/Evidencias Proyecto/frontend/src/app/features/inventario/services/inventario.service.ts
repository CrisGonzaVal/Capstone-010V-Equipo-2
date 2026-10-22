import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AmbitoInventario,
  Categoria,
  FiltrosExistencias,
  GestionCatalogo,
  HistorialTransicionCategoria,
  HistorialTransicionProducto,
  MovimientoCrear,
  Producto,
  ProductoCrear,
  ProductoDetalle,
  ProductoExistencia,
  RespuestaMovimiento,
  TransicionCatalogo,
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

  /**
   * Opciones mínimas para filtrar existencias (Feature 018, AC-4/AC-8).
   *
   * `GET /inventario/ambito` devuelve solo sedes y departamentos activos del
   * alcance del rol, sin consultar `/organizacion/*`: el Bodeguero no tiene
   * acceso a esas lecturas administrativas. Es la única fuente de los selectores
   * de la vista; el servidor autoriza la operación y aplica el gating de
   * `inventario`.
   */
  obtenerAmbitoInventario(): Observable<AmbitoInventario> {
    return this.http.get<AmbitoInventario>(`${URL_API}/inventario/ambito`);
  }

  /**
   * Catalogo clasificado por producto y por sede.
   *
   * Feature 018: los filtros **organizacionales** (`sede_id` y
   * `departamento_id`) los resuelve el servidor, que acota la respuesta, los
   * totales y la criticidad a ese ámbito. Los parámetros se envían solo cuando
   * tienen valor: `null`/`undefined` no agregan la clave de query.
   *
   * El texto (`q`), la categoría y los críticos no se envían: siguen
   * filtrándose en cliente sobre el conjunto organizacional ya cargado.
   */
  obtenerExistencias(
    filtros: FiltrosExistencias = {},
  ): Observable<ProductoExistencia[]> {
    let params = new HttpParams();
    if (filtros.sede_id !== null && filtros.sede_id !== undefined) {
      params = params.set('sede_id', filtros.sede_id);
    }
    if (
      filtros.departamento_id !== null &&
      filtros.departamento_id !== undefined
    ) {
      params = params.set('departamento_id', filtros.departamento_id);
    }
    return this.http.get<ProductoExistencia[]>(
      `${URL_API}/inventario/existencias`,
      { params },
    );
  }

  /**
   * Detalle de un producto por el alcance del rol (Feature 019, AC-1/AC-2/AC-10).
   *
   * `GET /inventario/existencias/{producto_id}`: el identificador viaja en la
   * ruta y el cliente **no** elige ámbito. No admite parámetros de institución,
   * sede ni departamento: el servidor resuelve el alcance completo del actor y
   * acota sedes, `stock_total` y `es_critico`. Reutiliza la forma
   * `SedeExistencia` de la lista de existencias.
   */
  obtenerDetalleProducto(productoId: number): Observable<ProductoDetalle> {
    return this.http.get<ProductoDetalle>(
      `${URL_API}/inventario/existencias/${productoId}`,
    );
  }

  registrarMovimiento(datos: MovimientoCrear): Observable<RespuestaMovimiento> {
    return this.http.post<RespuestaMovimiento>(`${URL_API}/inventario/movimientos`, datos);
  }

  // --- Ciclo de vida del catálogo (Feature 014, AC-11/AC-12/AC-15) ---

  /**
   * Listado de gestión: productos y categorías **con ambos estados** del tenant.
   *
   * Es la única fuente de la sección administrativa. Las consultas operativas
   * (`obtenerExistencias`, `obtenerCategorias`) siguen filtradas para todos los
   * roles, incluido el Administrador, así que no pueden sustituirlo.
   */
  obtenerGestionCatalogo(): Observable<GestionCatalogo> {
    return this.http.get<GestionCatalogo>(`${URL_API}/inventario/gestion`);
  }

  /**
   * Transición de estado de un producto. El servidor responde 200 con el
   * recurso persistido, también cuando el destino ya era el estado actual
   * (repetición idempotente sin motivo ni historial).
   */
  cambiarEstadoProducto(
    productoId: number,
    datos: TransicionCatalogo,
  ): Observable<Producto> {
    return this.http.patch<Producto>(
      `${URL_API}/inventario/productos/${productoId}/estado`,
      datos,
    );
  }

  /** Transición de estado de una categoría (mismo contrato que el producto). */
  cambiarEstadoCategoria(
    categoriaId: number,
    datos: TransicionCatalogo,
  ): Observable<Categoria> {
    return this.http.patch<Categoria>(
      `${URL_API}/inventario/categorias/${categoriaId}/estado`,
      datos,
    );
  }

  /** Historial inmutable de un producto, más reciente primero. */
  obtenerHistorialProducto(
    productoId: number,
  ): Observable<HistorialTransicionProducto[]> {
    return this.http.get<HistorialTransicionProducto[]>(
      `${URL_API}/inventario/productos/${productoId}/historial`,
    );
  }

  /** Historial inmutable de una categoría, más reciente primero. */
  obtenerHistorialCategoria(
    categoriaId: number,
  ): Observable<HistorialTransicionCategoria[]> {
    return this.http.get<HistorialTransicionCategoria[]>(
      `${URL_API}/inventario/categorias/${categoriaId}/historial`,
    );
  }
}