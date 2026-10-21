import { DOCUMENT, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';

import { puedeGestionarCatalogo } from '../../core/auth/roles';
import { AutenticacionService } from '../../core/services/auth.service';
import {
  Categoria,
  GestionCatalogo,
  HistorialTransicionCategoria,
  HistorialTransicionProducto,
  ProductoExistencia,
} from '../../shared/interfaces';
import { InventarioService } from './services/inventario.service';

/** Los dos recursos con ciclo de vida propio (Feature 014, AC-11). */
type TipoRecursoCatalogo = 'producto' | 'categoria';

/**
 * Pestañas de la vista de inventario (enmienda de presentación de AC-11).
 *
 * `existencias` es la pestaña operativa y la predeterminada para todos los
 * roles; `gestion` solo existe para el Administrador.
 */
type PestanaInventario = 'existencias' | 'gestion';

/** Transición que el Administrador está confirmando en el formulario de motivo. */
interface TransicionSolicitud {
  tipo: TipoRecursoCatalogo;
  id: number;
  nombre: string;
  /** Estado destino: `true` reactiva, `false` da de baja. */
  activo: boolean;
}

/** Recurso cuyo historial está abierto en la sección de gestión. */
interface HistorialRecurso {
  tipo: TipoRecursoCatalogo;
  id: number;
  nombre: string;
}

/** Fila resuelta del historial para el template (sin ids internos). */
interface FilaHistorial {
  id: number;
  origen: string;
  destino: string;
  actor: string;
  fecha: string;
  motivo: string;
}

/**
 * Mensaje legible de un fallo del ciclo de vida del catálogo (Feature 014).
 *
 * Prefiere el `detail` textual del backend —404 oculto, 409 de precondición y
 * 422 de motivo— y, si no hay texto, recurre al código de estado. Es el mismo
 * patrón que usa el detalle de ticket de la 013.
 */
export function mensajeDeErrorCatalogo(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (typeof detalle === 'string' && detalle.trim() !== '') {
    return detalle;
  }
  switch (error.status) {
    case 401:
      return 'Tu sesión no es válida. Vuelve a iniciar sesión.';
    case 403:
      return 'Tu rol no tiene permiso para gestionar el catálogo.';
    case 404:
      return 'El recurso indicado no existe o no está en tu alcance.';
    case 409:
      return 'La operación entra en conflicto con el estado actual del catálogo.';
    case 422:
      return 'Los datos enviados no son válidos: revisa el motivo.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}

/**
 * Vista de inventario (Features 002/011/014).
 *
 * Muestra el catálogo **operativo** filtrado por estado para todos los roles
 * (AC-4) y, solo para el Administrador, una sección de ciclo de vida del
 * catálogo (AC-11) alimentada **exclusivamente** por `GET /inventario/gestion`
 * (AC-15): categorías y productos activos e inactivos, con transición
 * (motivo obligatorio, ≤ 500) e historial. No se crea una vista nueva.
 *
 * Desde la enmienda de AC-11 las dos caras se reparten en pestañas: la
 * operativa —«Existencias»— es la predeterminada para todos los roles y la de
 * «Gestión del catálogo» solo se ofrece al Administrador. Bodeguero y
 * Solicitante no ven el conmutador: reciben directamente la vista operativa.
 */
@Component({
  selector: 'app-inventario',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './inventario.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventarioComponent implements OnInit {
  private readonly inventarioService = inject(InventarioService);
  private readonly autenticacion = inject(AutenticacionService);
  private readonly documento = inject(DOCUMENT);

  readonly categorias = signal<Categoria[]>([]);
  readonly insumos = signal<ProductoExistencia[]>([]);

  readonly consulta = signal('');
  readonly categoriaSeleccionada = signal<number | null>(null);
  readonly soloCriticos = signal(false);

  readonly cargando = signal(true);
  readonly mensajeError = signal<string | null>(null);

  // --- Ciclo de vida del catálogo (Feature 014) ---

  /** Rol de presentación; la autorización real la decide la API (D-2). */
  readonly rolActual = computed(() => this.autenticacion.identidad()?.rol ?? null);

  /** La sección de gestión solo se renderiza para Administrador (AC-11). */
  readonly gestionVisible = computed(() => puedeGestionarCatalogo(this.rolActual()));

  // --- Pestañas (enmienda de AC-11) ---

  /** Pestaña seleccionada; «Existencias» es la predeterminada para todos. */
  readonly pestanaActiva = signal<PestanaInventario>('existencias');

  /** Orden de las pestañas para la navegación con teclado. */
  private readonly ordenPestanas: readonly PestanaInventario[] = ['existencias', 'gestion'];

  /**
   * El panel operativo se pinta siempre que no haya conmutador (Bodeguero y
   * Solicitante no tienen pestaña de gestión) o cuando su pestaña está activa.
   */
  readonly existenciasVisibles = computed(
    () => !this.gestionVisible() || this.pestanaActiva() === 'existencias',
  );

  /** La pestaña de gestión solo existe y se pinta para Administrador. */
  readonly gestionPestanaVisible = computed(
    () => this.gestionVisible() && this.pestanaActiva() === 'gestion',
  );

  readonly gestion = signal<GestionCatalogo | null>(null);
  readonly cargandoGestion = signal(false);
  readonly errorGestion = signal<string | null>(null);

  readonly categoriasGestion = computed(() => this.gestion()?.categorias ?? []);
  readonly productosGestion = computed(() => this.gestion()?.productos ?? []);

  readonly totalActivosGestion = computed(
    () =>
      this.categoriasGestion().filter((categoria) => categoria.activo).length +
      this.productosGestion().filter((producto) => producto.activo).length,
  );

  readonly totalInactivosGestion = computed(
    () =>
      this.categoriasGestion().filter((categoria) => !categoria.activo).length +
      this.productosGestion().filter((producto) => !producto.activo).length,
  );

  /** Transición abierta en el formulario de motivo; `null` si no hay ninguna. */
  readonly transicion = signal<TransicionSolicitud | null>(null);
  readonly motivo = signal('');
  readonly errorMotivo = signal<string | null>(null);
  readonly errorOperacion = signal<string | null>(null);
  readonly mensajeOperacion = signal<string | null>(null);
  /** `true` mientras una transición está en vuelo: bloquea el formulario. */
  readonly enOperacion = signal(false);

  readonly historialVisible = signal<HistorialRecurso | null>(null);
  readonly historial = signal<FilaHistorial[]>([]);
  readonly cargandoHistorial = signal(false);
  readonly errorHistorial = signal<string | null>(null);

  /**
   * Insumos que pasan el texto y el filtro de criticos, todavia SIN aplicar la
   * categoria. Es la base de dos cosas: las filas visibles y los conteos del
   * panel. Si el panel contara sobre las filas ya filtradas por categoria, al
   * elegir "Papeleria" las demas categorias marcarian 0 y el panel dejaria de
   * poder navegar.
   */
  readonly insumosCoincidentes = computed(() => {
    const texto = this.normalizar(this.consulta());
    const soloCriticos = this.soloCriticos();

    return this.insumos().filter((insumo) => {
      if (soloCriticos && !insumo.es_critico) {
        return false;
      }
      if (!texto) {
        return true;
      }
      return (
        this.normalizar(insumo.nombre).includes(texto) ||
        this.normalizar(insumo.descripcion).includes(texto) ||
        this.normalizar(insumo.categoria_nombre).includes(texto)
      );
    });
  });

  /** Lo que se pinta en la tabla: `insumosCoincidentes` mas la categoria elegida. */
  readonly insumosVisibles = computed(() => {
    const categoriaId = this.categoriaSeleccionada();
    const coincidencias = this.insumosCoincidentes();

    if (categoriaId === null) {
      return coincidencias;
    }
    return coincidencias.filter((insumo) => insumo.categoria_id === categoriaId);
  });

  /** Cuantos insumos habria en cada categoria si se pulsara su boton. */
  readonly conteoPorCategoria = computed(() => {
    const conteos = new Map<number, number>();
    for (const insumo of this.insumosCoincidentes()) {
      conteos.set(insumo.categoria_id, (conteos.get(insumo.categoria_id) ?? 0) + 1);
    }
    return conteos;
  });

/**
 * Los tres numeros de la franja de indicadores. Miden el catalogo CARGADO, no el
 * filtrado: la franja es el resumen de lo que hay, y los filtros ya tienen su
 * propio lugar (el panel de categorias y la tabla). Por eso no se mueven mientras
 * se escribe en el buscador.
 */
readonly totalCatalogo = computed(() => this.insumos().length);

readonly totalConStock = computed(() => this.insumos().filter((insumo) => insumo.stock_total > 0).length);

readonly totalCriticos = computed(() => this.insumos().filter((insumo) => insumo.es_critico).length);

  readonly hayFiltros = computed(
    () => this.consulta().trim().length > 0 || this.categoriaSeleccionada() !== null || this.soloCriticos(),
  );

  readonly categoriaActual = computed(
    () => this.categorias().find((categoria) => categoria.categoria_id === this.categoriaSeleccionada())?.nombre_cat ?? null,
  );

  ngOnInit(): void {
    this.cargarCatalogo();
    if (this.gestionVisible()) {
      this.cargarGestion();
    }
  }

  seleccionarCategoria(categoriaId: number | null): void {
    this.categoriaSeleccionada.set(categoriaId);
  }

  alternarSoloCriticos(): void {
    this.soloCriticos.update((valor) => !valor);
  }

  limpiarFiltros(): void {
    this.consulta.set('');
    this.categoriaSeleccionada.set(null);
    this.soloCriticos.set(false);
  }

  // --- Pestañas (enmienda de AC-11) ---

  /**
   * Cambia de pestaña. La de gestión se ignora si el rol no la tiene: la
   * visibilidad por rol no depende de un clic, sino de `gestionVisible()`.
   */
  seleccionarPestana(pestana: PestanaInventario): void {
    if (pestana === 'gestion' && !this.gestionVisible()) {
      return;
    }
    this.pestanaActiva.set(pestana);
  }

  /**
   * Navegación por teclado del tablist (`←`/`→`/`Home`/`End`), con foco en la
   * pestaña recién seleccionada. `Enter` y `Espacio` ya los resuelve el botón.
   */
  alNavegarPestanas(evento: KeyboardEvent): void {
    if (!this.gestionVisible()) {
      return;
    }

    const actual = this.ordenPestanas.indexOf(this.pestanaActiva());
    let destino: number;
    switch (evento.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        destino = (actual + 1) % this.ordenPestanas.length;
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        destino = (actual - 1 + this.ordenPestanas.length) % this.ordenPestanas.length;
        break;
      case 'Home':
        destino = 0;
        break;
      case 'End':
        destino = this.ordenPestanas.length - 1;
        break;
      default:
        return;
    }

    evento.preventDefault();
    const pestana = this.ordenPestanas[destino];
    this.seleccionarPestana(pestana);
    this.documento
      .getElementById(pestana === 'existencias' ? 'pestana-existencias' : 'pestana-gestion')
      ?.focus();
  }

  // --- Acciones de gestión (solo Administrador, AC-11/AC-12) ---

  /** Abre el formulario de motivo para la transición indicada. */
  solicitarTransicion(
    tipo: TipoRecursoCatalogo,
    id: number,
    nombre: string,
    activo: boolean,
  ): void {
    this.transicion.set({ tipo, id, nombre, activo });
    this.motivo.set('');
    this.errorMotivo.set(null);
    this.errorOperacion.set(null);
    this.mensajeOperacion.set(null);
  }

  cancelarTransicion(): void {
    this.transicion.set(null);
    this.motivo.set('');
    this.errorMotivo.set(null);
  }

  /**
   * Valida el motivo en cliente (el servidor vuelve a validarlo y responde 422)
   * y envía la transición. Un 200 —también el idempotente— deja el estado
   * actual visible sin error; un 409/422/otro se muestra con su mensaje.
   */
  confirmarTransicion(): void {
    const solicitud = this.transicion();
    if (solicitud === null || this.enOperacion()) {
      return;
    }

    const motivo = this.motivo();
    if (motivo.trim() === '') {
      this.errorMotivo.set('El motivo es obligatorio para cambiar el estado.');
      return;
    }
    if (motivo.length > 500) {
      this.errorMotivo.set('El motivo no puede superar los 500 caracteres.');
      return;
    }

    this.enOperacion.set(true);
    this.errorMotivo.set(null);
    this.errorOperacion.set(null);
    this.mensajeOperacion.set(null);

    const datos = { activo: solicitud.activo, motivo };
    // Dos ramas separadas: el `Observable` de producto y el de categoría no son
    // uniones con una firma de `subscribe` común.
    if (solicitud.tipo === 'producto') {
      this.inventarioService.cambiarEstadoProducto(solicitud.id, datos).subscribe({
        next: () => this.alTransicionExitosa(solicitud),
        error: (fallo: HttpErrorResponse) => this.alFalloDeTransicion(fallo),
      });
    } else {
      this.inventarioService.cambiarEstadoCategoria(solicitud.id, datos).subscribe({
        next: () => this.alTransicionExitosa(solicitud),
        error: (fallo: HttpErrorResponse) => this.alFalloDeTransicion(fallo),
      });
    }
  }

  private alTransicionExitosa(solicitud: TransicionSolicitud): void {
    this.enOperacion.set(false);
    this.transicion.set(null);
    this.motivo.set('');
    this.mensajeOperacion.set(
      `Estado actualizado: «${solicitud.nombre}» ahora está ${
        solicitud.activo ? 'activo' : 'inactivo'
      }.`,
    );
    // La transición mueve las dos caras de la vista: el listado de gestión
    // (ambos estados) y el operativo (solo activos).
    this.cargarGestion();
    this.cargarCatalogo();
    const abierto = this.historialVisible();
    if (abierto !== null && abierto.tipo === solicitud.tipo && abierto.id === solicitud.id) {
      this.cargarHistorial(abierto.tipo, abierto.id);
    }
  }

  private alFalloDeTransicion(fallo: HttpErrorResponse): void {
    this.enOperacion.set(false);
    this.errorOperacion.set(mensajeDeErrorCatalogo(fallo));
  }

  /** Abre/cierra el historial del recurso y lo carga si se abre. */
  alternarHistorial(tipo: TipoRecursoCatalogo, id: number, nombre: string): void {
    const abierto = this.historialVisible();
    if (abierto !== null && abierto.tipo === tipo && abierto.id === id) {
      this.historialVisible.set(null);
      this.historial.set([]);
      this.errorHistorial.set(null);
      return;
    }
    this.historialVisible.set({ tipo, id, nombre });
    this.cargarHistorial(tipo, id);
  }

  /**
   * Una sola carga para categorias e insumos: dos observables sueltos darían dos
   * estados de carga y dos de error, y la vista solo puede mostrar uno de cada.
   */
  private cargarCatalogo(): void {
    this.cargando.set(true);
    this.mensajeError.set(null);

    forkJoin({
      categorias: this.inventarioService.obtenerCategorias(),
      insumos: this.inventarioService.obtenerExistencias(),
    }).subscribe({
      next: ({ categorias, insumos }) => {
        this.categorias.set(categorias);
        this.insumos.set(insumos);
        this.cargando.set(false);
      },
      error: (fallo) => {
        this.categorias.set([]);
        this.insumos.set([]);
        this.cargando.set(false);
        this.mensajeError.set(
          `No se pudo contactar el backend (${fallo.status ?? 'sin respuesta'}). ` +
            'Revisa que el servicio en el puerto 8000 este levantado.',
        );
      },
    });
  }

  private cargarGestion(): void {
    this.cargandoGestion.set(true);
    this.errorGestion.set(null);

    this.inventarioService.obtenerGestionCatalogo().subscribe({
      next: (gestion) => {
        this.gestion.set(gestion);
        this.cargandoGestion.set(false);
      },
      error: (fallo: HttpErrorResponse) => {
        this.gestion.set(null);
        this.cargandoGestion.set(false);
        this.errorGestion.set(
          `No se pudo cargar la gestión del catálogo (${fallo.status ?? 'sin respuesta'}).`,
        );
      },
    });
  }

  private cargarHistorial(tipo: TipoRecursoCatalogo, id: number): void {
    this.cargandoHistorial.set(true);
    this.errorHistorial.set(null);
    this.historial.set([]);

    const alCargar = (
      filas: Array<HistorialTransicionProducto | HistorialTransicionCategoria>,
    ): void => {
      this.historial.set(filas.map((fila) => this.aFilaHistorial(fila)));
      this.cargandoHistorial.set(false);
    };
    const alFallar = (fallo: HttpErrorResponse): void => {
      this.cargandoHistorial.set(false);
      this.errorHistorial.set(mensajeDeErrorCatalogo(fallo));
    };

    if (tipo === 'producto') {
      this.inventarioService.obtenerHistorialProducto(id).subscribe({
        next: alCargar,
        error: alFallar,
      });
    } else {
      this.inventarioService.obtenerHistorialCategoria(id).subscribe({
        next: alCargar,
        error: alFallar,
      });
    }
  }

  private aFilaHistorial(
    fila: HistorialTransicionProducto | HistorialTransicionCategoria,
  ): FilaHistorial {
    const actor = [fila.usuario_nombre, fila.usuario_apellido]
      .filter((parte): parte is string => !!parte)
      .join(' ');
    return {
      id:
        'historial_producto_id' in fila
          ? fila.historial_producto_id
          : fila.historial_categoria_id,
      origen: fila.activo_origen ? 'Activo' : 'Inactivo',
      destino: fila.activo_destino ? 'Activo' : 'Inactivo',
      actor: actor === '' ? `Usuario ${fila.usuario_id}` : actor,
      fecha: fila.fecha_transicion,
      motivo: fila.motivo,
    };
  }

  /** Minusculas sin acentos ni espacios dobles, para comparar contra la consulta. */
  private normalizar(texto: string | null): string {
    return (texto ?? '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }
}
