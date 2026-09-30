import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';

import { Categoria, ProductoExistencia } from '../../shared/interfaces';
import { InventarioService } from './services/inventario.service';

@Component({
  selector: 'app-inventario',
  standalone: true,
  templateUrl: './inventario.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventarioComponent implements OnInit {
  private readonly inventarioService = inject(InventarioService);

  readonly categorias = signal<Categoria[]>([]);
  readonly insumos = signal<ProductoExistencia[]>([]);

  readonly consulta = signal('');
  readonly categoriaSeleccionada = signal<number | null>(null);
  readonly soloCriticos = signal(false);

  readonly cargando = signal(true);
  readonly mensajeError = signal<string | null>(null);

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