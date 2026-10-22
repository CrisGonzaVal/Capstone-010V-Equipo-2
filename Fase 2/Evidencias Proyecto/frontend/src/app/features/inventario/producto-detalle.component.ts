import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ProductoDetalle } from '../../shared/interfaces';
import { InventarioService } from './services/inventario.service';

/** Pestaña del inventario desde la que se abrió el detalle (§6.6 / AC-9). */
type PestanaInventario = 'existencias' | 'gestion';

/**
 * Mensaje legible de un fallo de la consulta de detalle (Feature 019, AC-10).
 *
 * Prefiere el `detail` textual del backend —404 oculto, 409 de sede no
 * resoluble, 403 de capacidad— y, si no hay texto (500 sin cuerpo, red caída,
 * lista de validación de Pydantic), recurre al código de estado. El 422 se
 * explica como identificador no válido (mismo texto que la validación local,
 * §6.5) y el status 0 como servidor inalcanzable.
 */
export function mensajeDeErrorProducto(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (typeof detalle === 'string' && detalle.trim() !== '') {
    return detalle;
  }
  switch (error.status) {
    case 401:
      return 'Tu sesión no es válida. Vuelve a iniciar sesión.';
    case 403:
      return 'No tienes permiso para consultar este producto, o la capacidad inventario está deshabilitada para tu institución.';
    case 404:
      return 'El producto indicado no existe o no está en tu alcance.';
    case 409:
      return 'No se pudo resolver tu sede operativa: tu usuario no tiene una sede asignada.';
    case 422:
      return 'El identificador del producto no es válido: debe ser un entero positivo.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo cargar el detalle del producto (HTTP ${error.status}).`;
  }
}

/** Texto compartido por la validación local y el 422 del servidor (§6.5). */
const MENSAJE_ID_INVALIDO =
  'El identificador del producto no es válido: debe ser un entero positivo.';

/**
 * Detalle de producto por alcance (Feature 019, D-8/AC-1/AC-3/AC-6/AC-8…AC-10).
 *
 * Vista de **solo lectura** de los datos del catálogo y del stock desglosado por
 * sede tal como los devuelve `GET /inventario/existencias/{producto_id}`: el
 * servidor resuelve el ámbito del rol, el total y la criticidad, y el cliente no
 * envía filtros de institución ni de sede (AC-9). `producto_id` e
 * `institucion_id` viajan en el contrato pero **no se pintan** (spec §8).
 *
 * Estados diferenciados: carga, error accesible con reintento (403, 409, red y
 * servidor), 404/422 como error y `200` con `sedes: []` como vacío legible —
 * nunca como error—. Si el identificador no es un entero positivo, la vista
 * muestra un error controlado **sin emitir petición**. Los estados inactivos del
 * producto y de su categoría se indican con badges y no añaden controles de
 * escritura. «Volver al inventario» restaura la pestaña de procedencia.
 */
@Component({
  selector: 'app-producto-detalle',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './producto-detalle.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProductoDetalleComponent {
  private readonly servicioInventario = inject(InventarioService);
  private readonly ruta = inject(ActivatedRoute);

  // --- Estado de la consulta ---

  readonly productoId = signal<number | null>(null);
  readonly producto = signal<ProductoDetalle | null>(null);
  readonly cargando = signal(true);
  readonly errorCarga = signal<string | null>(null);

  // --- Procedencia (retorno contextual, AC-9) ---

  readonly pestanaOrigen = signal<PestanaInventario>('existencias');

  /**
   * Query params del enlace de vuelta: solo Gestión añade `tab=gestion`, para
   * que Existencias se abra con la URL limpia `/inventario`.
   */
  readonly parametrosRetorno = computed<{ tab: string } | null>(() =>
    this.pestanaOrigen() === 'gestion' ? { tab: 'gestion' } : null,
  );

  /**
   * Reintento solo cuando hay un identificador válido: un id inválido no cambia
   * por reintentar y la vista no debe ofrecer una acción inútil.
   */
  readonly puedeReintentar = computed(() => this.productoId() !== null);

  // --- Presentación derivada ---

  /** Estado del stock según la criticidad ya calculada por el servidor (AC-7). */
  readonly estadoStock = computed<string>(() => {
    const producto = this.producto();
    if (producto === null) {
      return '';
    }
    return producto.es_critico ? 'Crítico' : 'Disponible';
  });

  readonly claseEstadoStock = computed(() =>
    this.producto()?.es_critico
      ? 'text-rose-700 bg-rose-50'
      : 'text-emerald-700 bg-emerald-50',
  );

  readonly etiquetaEstadoProducto = computed(() =>
    this.producto()?.activo === false ? 'Producto inactivo' : 'Producto activo',
  );

  readonly claseEstadoProducto = computed(() =>
    this.producto()?.activo === false
      ? 'text-amber-700 bg-amber-50'
      : 'text-emerald-700 bg-emerald-50',
  );

  readonly etiquetaEstadoCategoria = computed(() =>
    this.producto()?.categoria_activa === false
      ? 'Categoría inactiva'
      : 'Categoría activa',
  );

  readonly claseEstadoCategoria = computed(() =>
    this.producto()?.categoria_activa === false
      ? 'text-amber-700 bg-amber-50'
      : 'text-slate-700 bg-slate-100',
  );

  constructor() {
    // Origen del enlace de vuelta: `?tab=gestion` llega desde la pestaña de
    // Gestión del catálogo (AC-8/AC-9); cualquier otro valor es Existencias.
    this.ruta.queryParamMap.subscribe((consulta) => {
      this.pestanaOrigen.set(
        consulta.get('tab') === 'gestion' ? 'gestion' : 'existencias',
      );
    });

    // La ruta `inventario/:productoId` fija el identificador; cada cambio
    // vuelve a cargar. Un valor no entero o no positivo no genera petición.
    this.ruta.paramMap.subscribe((parametros) => {
      const crudo = parametros.get('productoId');
      const numero = crudo === null ? Number.NaN : Number(crudo);
      this.productoId.set(
        Number.isInteger(numero) && numero > 0 ? numero : null,
      );
      this.cargar();
    });
  }

  // --- Carga ---

  private cargar(): void {
    const id = this.productoId();
    if (id === null) {
      this.producto.set(null);
      this.cargando.set(false);
      this.errorCarga.set(MENSAJE_ID_INVALIDO);
      return;
    }

    this.cargando.set(true);
    this.errorCarga.set(null);
    this.producto.set(null);

    this.servicioInventario.obtenerDetalleProducto(id).subscribe({
      next: (detalle) => {
        this.producto.set(detalle);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.producto.set(null);
        this.cargando.set(false);
        this.errorCarga.set(mensajeDeErrorProducto(error));
      },
    });
  }

  /** Reintento explícito tras un error recuperable; nunca automático (AC-10). */
  reintentar(): void {
    this.cargar();
  }
}
