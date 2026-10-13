import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  CatalogosTicket,
  DetalleTicketCrear,
  Prioridad,
  ProductoCatalogo,
  Solicitante,
  Ticket,
  TicketCrear,
} from '../../shared/interfaces';
import { TicketService } from './services/ticket.service';

/** Encabezado de una columna del tablero, una por estado del catalogo. */
interface ColumnaKanban {
  estado_id: number;
  estado: string;
  tarjetas: TarjetaKanban[];
}

/**
 * Tarjeta con los ids ya resueltos a texto. El template no resuelve ids: todo
 * lo que necesita para pintar (nombre de prioridad, solicitante, clases) sale
 * del `computed` de columnas, que es el unico lugar que conoce los catalogos.
 */
interface TarjetaKanban {
  ticket: Ticket;
  asunto: string;
  prioridad: string;
  clasePrioridad: string;
  solicitante: string;
  fechaCreacion: string;
  fechaCierre: string | null;
  puedeRetroceder: boolean;
  puedeAvanzar: boolean;
  estadoAnteriorId: number | null;
  estadoSiguienteId: number | null;
  enProceso: boolean;
}

/** Un error de validacion de FastAPI, con su `loc` y su mensaje original. */
interface DetalleError422 {
  loc: (string | number)[];
  msg: string;
  type: string;
}

const CLASES_PRIO: Record<string, string> = {
  ALTA: 'text-rose-600 bg-rose-50',
  MEDIA: 'text-blue-600 bg-blue-50',
  BAJA: 'text-amber-600 bg-amber-50',
};

const CLASE_PRIORIDAD_NEUTRA = 'text-slate-600 bg-slate-100';

/**
 * Tablero Kanban de tickets, mas el modal de alta.
 *
 * **El tablero es real**: se arma con `GET /tickets/catalogos` (estados ya
 * ordenados por `estado_id`) y `GET /tickets/`, disparados al construir el
 * componente. Una columna por estado del catalogo, en su orden, incluidas las
 * vacias (AC-1); dentro, los tickets de ese `estado_id` ordenados por
 * `fecha_creacion` descendente y, en empate, por `ticket_id` descendente
 * (AC-2). Ningun id de estado se codifica a mano: el nombre sale del catalogo.
 *
 * El modal comparte el catalogo que el tablero ya cargo: `abrirModal` no vuelve
 * a pedirlo si esta disponible. Que el tablero no se actualice al crear un
 * ticket es deliberado (spec, H-3).
 */
@Component({
  selector: 'app-tickets',
  standalone: true,
  imports: [ReactiveFormsModule, DatePipe],
  templateUrl: './tickets.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TicketsComponent {
  // --- Estado del tablero ---

  /** Tickets reales, tal como los devuelve `GET /tickets/` (orden ya explicito). */
  readonly tickets = signal<Ticket[]>([]);

  /** Ids de tickets con un `PATCH /estado` en vuelo (anti doble envio, AC-19). */
  readonly enProceso = signal<Set<number>>(new Set());

  readonly cargandoTablero = signal(false);
  readonly errorTablero = signal<string | null>(null);

  /**
   * Mensaje del rechazo de una transicion (404, 409, 500 o red caida). Distinto
   * de `errorTablero`, que reemplaza el tablero entero cuando falla la carga:
   * este avisa de un `PATCH` no aceptado sin esconder las columnas (AC-20).
   */
  readonly errorMovimiento = signal<string | null>(null);

  /** Filtro de prioridad del tablero. `null` = "todas" (valor por defecto, AC-6). */
  readonly filtroPrioridad = signal<number | null>(null);

  /** Texto de busqueda por asunto. Vacio o solo espacios = sin filtro (AC-7). */
  readonly busqueda = signal('');

  /** Hay algun filtro activo: distingue el vacio "por filtros" del vacio real (AC-5). */
  readonly hayFiltros = computed(
    () => this.filtroPrioridad() !== null || this.busqueda().trim() !== ''
  );

  /**
   * Columnas del tablero: una por estado del catalogo, en su orden, incluidas
   * las que no tienen tickets (AC-1). Dentro de cada una, los tickets de ese
   * `estado_id` (AC-2) ordenados por `fecha_creacion` descendente y, en empate,
   * por `ticket_id` descendente. Es `computed` y no `signal`: todo sale de
   * `estados()`, `tickets()` y las señales de filtro, no hay estado propio que
   * mantener.
   *
   * Los filtros se aplican **antes de agrupar** (plan §3.5): es un filtrado de
   * cliente sobre el conjunto ya cargado, no una consulta nueva. Con eso los
   * contadores de cada columna (`tarjetas.length`) quedan ya "despues de
   * filtrar" (AC-3) sin una señal de contador aparte. Los dos predicados se
   * combinan en interseccion (AC-7, D-6).
   */
  readonly columnas = computed<ColumnaKanban[]>(() => {
    const prioridad = this.filtroPrioridad();
    const busqueda = this.normalizar(this.busqueda());

    const filtrados = this.tickets().filter(
      (ticket) =>
        (prioridad === null || ticket.prioridad_id === prioridad) &&
        (busqueda === '' || this.normalizar(ticket.asunto).includes(busqueda))
    );

    return this.estados().map((estado, indice) => ({
      estado_id: estado.estado_id,
      estado: estado.nombre,
      tarjetas: filtrados
        .filter((ticket) => ticket.estado_id === estado.estado_id)
        .sort(
          (a, b) =>
            Date.parse(b.fecha_creacion) - Date.parse(a.fecha_creacion) ||
            b.ticket_id - a.ticket_id
        )
        .map((ticket) => this.resolverTarjeta(ticket, indice)),
    }));
  });

  /**
   * Id del estado canonico `EnCurso`, resuelto por **nombre** (sin distinguir
   * mayusculas ni acentos, via `normalizar`) y, ante duplicados, por el **menor
   * `estado_id`** — la misma regla del backend (Feature 004, D-3). `null` si el
   * catalogo no lo trae. No se usa un id fijo ni la posicion ordinal: el catalogo
   * es mutable.
   *
   * La transicion `EnCurso → Cerrado` esta reservada al despacho (Feature 005):
   * el PATCH responde 409 y el Kanban no debe ofrecer ese avance manual (AC-16).
   *
   * Se buscó el menor id sobre **todos** los candidatos y no sobre el primero:
   * asi el canonico sigue siendo el menor aunque el catalogo llegue desordenado.
   */
  private readonly idEstadoEnCurso = computed<number | null>(() => {
    const candidatos = this.estados().filter(
      (estado) => this.normalizar(estado.nombre) === 'encurso'
    );
    if (candidatos.length === 0) {
      return null;
    }
    return candidatos.reduce(
      (menor, estado) => Math.min(menor, estado.estado_id),
      candidatos[0].estado_id
    );
  });

  /**
   * Resuelve ids contra los catalogos y la **posicion del estado** para que el
   * template no conozca ninguno ni calcule indices.
   *
   * `indice` es la posicion del estado de la columna dentro de `estados()` (el
   * orden del flujo). De ahi salen los botones, sin comparar nombres:
   * - primer estado (indice 0): sin retroceso;
   * - estado terminal (ultimo indice): sin avanzar y **sin retroceso** (AC-11);
   * - cualquier otro: anterior = indice - 1, siguiente = indice + 1 (contiguos,
   *   nunca un salto, AC-12).
   *
   * Sobre esa base, la columna del `EnCurso` canonico no ofrece avance aunque
   * haya un siguiente (AC-16); el retroceso se calcula igual y las demas
   * columnas quedan intactas.
   *
   * Como solo se llama para tickets que ya cayeron en una columna, el estado
   * siempre existe en el catalogo; no hay busqueda lineal extra por tarjeta.
   */
  private resolverTarjeta(ticket: Ticket, indice: number): TarjetaKanban {
    const estados = this.estados();
    const esTerminal = indice === estados.length - 1;
    const puedeRetroceder = indice > 0 && !esTerminal;
    const esEnCursoCanonico = estados[indice].estado_id === this.idEstadoEnCurso();
    const puedeAvanzar = !esTerminal && !esEnCursoCanonico;

    const prioridad = this.prioridades().find((p) => p.prioridad_id === ticket.prioridad_id);
    const solicitante = this.solicitantes().find((s) => s.usuario_id === ticket.usuario_id);
    const nombrePrioridad = prioridad?.nombre ?? `Prioridad #${ticket.prioridad_id}`;
    return {
      ticket,
      asunto: ticket.asunto,
      prioridad: nombrePrioridad,
      clasePrioridad: this.clasePrioridad(nombrePrioridad),
      solicitante: solicitante
        ? `${solicitante.apellido}, ${solicitante.nombre} · ${solicitante.departamento_nombre}`
        : `Usuario #${ticket.usuario_id}`,
      fechaCreacion: ticket.fecha_creacion,
      fechaCierre: ticket.fecha_cierre,
      puedeRetroceder,
      puedeAvanzar,
      estadoAnteriorId: puedeRetroceder ? estados[indice - 1].estado_id : null,
      estadoSiguienteId: puedeAvanzar ? estados[indice + 1].estado_id : null,
      enProceso: this.enProceso().has(ticket.ticket_id),
    };
  }

  /**
   * Clase Tailwind de la prioridad por su nombre real, tolerante a mayusculas;
   * si el catalogo trae un nombre inesperado cae en una clase neutra en vez de
   * pintar `undefined`.
   */
  private clasePrioridad(nombre: string): string {
    return CLASES_PRIO[nombre.toUpperCase()] ?? CLASE_PRIORIDAD_NEUTRA;
  }

  // --- Filtros ---

  /** Fija el filtro de prioridad desde el `<select>`: `''` es "todas". */
  cambiarPrioridad(valor: string) {
    this.filtroPrioridad.set(valor === '' ? null : Number(valor));
  }

  /** Actualiza el texto de busqueda desde el `<input>`. */
  actualizarBusqueda(valor: string) {
    this.busqueda.set(valor);
  }

  /**
   * Normaliza para comparar: sin acentos, minusculas y sin espacios sobrantes.
   *
   * Se usa tanto para el asunto como para la consulta. Al no haber `LIKE` en
   * SQL, `%` y `_` son caracteres literales por construccion (D-6, AC-7). Sobre
   * la consulta, el `.trim()` es lo que implementa "vacio = sin filtro".
   */
  private normalizar(texto: string): string {
    return texto
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  private readonly servicioTickets = inject(TicketService);
  private readonly fb = inject(NonNullableFormBuilder);

  // --- Estado del modal ---

  readonly modalAbierto = signal(false);
  readonly catalogos = signal<CatalogosTicket | null>(null);
  readonly cargandoCatalogos = signal(false);
  readonly guardando = signal(false);
  readonly ticketCreado = signal<number | null>(null);
  readonly errorCatalogos = signal<string | null>(null);
  readonly errorGuardado = signal<string | null>(null);
  readonly detalleErrores = signal<DetalleError422[]>([]);

  /**
   * El `<dialog>` nativo, no un overlay de Tailwind.
   *
   * `showModal()` da el foco atrapado, `Esc` para cerrar y el fondo atenuado
   * sin escribir una sola linea de codigo de foco. Se accede por `viewChild`
   * y no por `@ViewChild` porque el componente es standalone y no usa decoradores
   * de clase.
   */
  readonly dialogo = viewChild.required<ElementRef<HTMLDialogElement>>('dialogo');

  constructor() {
    // El `effect` corre **después** del render, que es justo lo que necesita:
    // con `@if (modalAbierto())` el `<dialog>` no existe en el DOM hasta que
    // Angular lo crea, asi que llamar a `showModal()` desde el `(click)` del
    // boton encontraria `undefined`. La guarda `!nativo.open` evita el
    // `InvalidStateError` de abrir un dialogo que ya esta abierto.
    effect(() => {
      const abierto = this.modalAbierto();
      const nativo = this.dialogo().nativeElement;
      if (abierto && !nativo.open) {
        nativo.showModal();
      }
      if (!abierto && nativo.open) {
        nativo.close();
      }
    });

    // El tablero se carga al construir: catalogos de estados + tickets.
    this.cargarTablero();
  }

  // --- Formulario ---

  /**
   * `NonNullableFormBuilder` para que los controles nazcan con valor y no con
   * `null`: la cantidad arranca en 1, que es valida, en vez de en 0, que por
   * `gt=0` seria un 422 garantizado en el primer envio.
   *
   * Los validadores del cliente son espejo de `TicketCrear` en el backend. El
   * servidor sigue siendo la fuente de verdad: esto solo evita el viaje de ida
   * y vuelta para descubrir un error que ya se conocia.
   */
  readonly formulario = this.fb.group({
    usuario_id: [null as number | null, Validators.required],
    prioridad_id: [null as number | null, Validators.required],
    estado_id: [null as number | null, Validators.required],
    asunto: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(150)]],
    descripcion: [''],
    detalles: this.fb.array([this.crearFilaDetalle()]),
  });

  readonly detalles = this.formulario.controls.detalles;

  crearFilaDetalle() {
    return this.fb.group({
      producto_id: [null as number | null, Validators.required],
      cantidad_solicitada: [1, [Validators.required, Validators.min(1)]],
    });
  }

  // --- Catálogos ---

  readonly prioridades = computed<Prioridad[]>(() => this.catalogos()?.prioridades ?? []);
  readonly estados = computed(() => this.catalogos()?.estados ?? []);
  readonly productos = computed<ProductoCatalogo[]>(() => this.catalogos()?.productos ?? []);
  readonly solicitantes = computed<Solicitante[]>(() => this.catalogos()?.solicitantes ?? []);

  /** Etiqueta de un producto en el desplegable: nombre, unidad y categoria. */
  etiquetaProducto(producto: ProductoCatalogo): string {
    const unidad = producto.unidad_medida ? ` (${producto.unidad_medida})` : '';
    return `${producto.nombre}${unidad} · ${producto.categoria_nombre}`;
  }

  etiquetaSolicitante(solicitante: Solicitante): string {
    return `${solicitante.apellido}, ${solicitante.nombre} · ${solicitante.departamento_nombre}`;
  }

  /**
   * El estado inicial es **la primera entrada del catalogo**, no una constante.
   *
   * El orden de `estados` es el del flujo (Pendiente → EnRevision → ...), asi
   * que el primero es el correcto sin que el componente sepa ningun nombre. Una
   * constante tipo `'Pendiente'` seria una comparacion de strings que depende de
   * que elCatalogo se llame asi en otra parte.
   */
  estadoInicial(): number | null {
    return this.estados()[0]?.estado_id ?? null;
  }

  // --- Carga del tablero ---

  /**
   * Carga inicial del tablero: catalogo de estados y tickets en paralelo. Con
   * los dos OK llena `catalogos()` y `tickets()`; si cualquiera falla —o si el
   * catalogo de estados viene vacio, que dejaria columnas en blanco silenciosas
   * (spec §7)— publica un error visible con mensaje propio. `reintentarTablero()`
   * la repite.
   */
  private cargarTablero(): void {
    this.cargandoTablero.set(true);
    this.errorTablero.set(null);

    forkJoin({
      catalogos: this.servicioTickets.obtenerCatalogos(),
      tickets: this.servicioTickets.obtenerTickets(),
    }).subscribe({
      next: ({ catalogos, tickets }) => {
        if (catalogos.estados.length === 0) {
          this.cargandoTablero.set(false);
          this.errorTablero.set(
            'El catálogo de estados está vacío. El tablero no se puede mostrar.'
          );
          return;
        }
        this.catalogos.set(catalogos);
        this.tickets.set(tickets);
        const inicial = this.estadoInicial();
        if (inicial !== null) {
          this.formulario.controls.estado_id.setValue(inicial);
        }
        this.cargandoTablero.set(false);
      },
      error: () => {
        this.cargandoTablero.set(false);
        this.errorTablero.set(
          'No se pudo cargar el tablero. Revisa la conexión e inténtalo de nuevo.'
        );
      },
    });
  }

  /** Reintenta la carga del tablero tras un error visible. */
  reintentarTablero() {
    this.cargarTablero();
  }

  // --- Acciones del modal ---

  abrirModal() {
    this.errorGuardado.set(null);
    this.errorCatalogos.set(null);
    this.detalleErrores.set([]);
    this.ticketCreado.set(null);
    this.modalAbierto.set(true);

    // El tablero ya cargo el catalogo al construir el componente: si esta
    // disponible, abrir el modal no vuelve a pedirlo. Solo se pide cuando el
    // arranque fallo o aun no se completo, para no dejar el formulario vacio.
    if (this.catalogos() !== null) {
      return;
    }

    this.cargandoCatalogos.set(true);
    this.servicioTickets.obtenerCatalogos().subscribe({
      next: (catalogos) => {
        this.catalogos.set(catalogos);
        this.cargandoCatalogos.set(false);
        const inicial = this.estadoInicial();
        if (inicial !== null) {
          this.formulario.controls.estado_id.setValue(inicial);
        }
      },
      error: () => {
        this.cargandoCatalogos.set(false);
        this.errorCatalogos.set(
          'No se pudieron cargar las prioridades, estados ni productos. Revisa la conexión e inténtalo de nuevo.'
        );
      },
    });
  }

  /** Cierra el modal. El `effect` se encarga de llamar a `close()`. */
  cerrarModal() {
    this.modalAbierto.set(false);
  }

  agregarDetalle() {
    this.detalles.push(this.crearFilaDetalle());
  }

  /** Con una sola fila no se puede quitar: un ticket sin items es un 422. */
  puedeQuitarDetalle(): boolean {
    return this.detalles.length > 1;
  }

  quitarDetalle(indice: number) {
    if (this.puedeQuitarDetalle()) {
      this.detalles.removeAt(indice);
    }
  }

  /**
   * Suma las cantidades de los productos repetidos antes de enviar.
   *
   * `detalle_ticket` no declara `UNIQUE(ticket_id, producto_id)`, asi que el
   * servidor aceptaria las dos filas. Fusionarlas aqui es corregir un error de
   * uso del formulario, no imponer una regla de negocio: quien use la API
   * directamente puede seguir mandando dos lineas, y el backend las respeta.
   */
  combinarDetalles(): DetalleTicketCrear[] {
    const cantidades = new Map<number, number>();
    for (const detalle of this.detalles.controls) {
      const productoId = detalle.controls.producto_id.value;
      if (productoId === null) {
        continue;
      }
      cantidades.set(productoId, (cantidades.get(productoId) ?? 0) + detalle.controls.cantidad_solicitada.value);
    }
    return [...cantidades].map(([producto_id, cantidad_solicitada]) => ({
      producto_id,
      cantidad_solicitada,
    }));
  }

  // --- Errores ---

  /**
   * Traduce el `detail` de FastAPI a un mensaje por control.
   *
   * `loc` termina en el nombre del campo; para un error de detalle termina en
   * `[..., 'detalles', indice, 'cantidad_solicitada']`, y ese indice se muestra
   * como numero de fila empezando en 1.
   */
  mensajeDe(campo: string): string | null {
    for (const error of this.detalleErrores()) {
      const ultimo = error.loc.at(-1);
      if (ultimo === campo) {
        return this.traducirMensaje(error);
      }
    }
    return null;
  }

  mensajeDeDetalle(indice: number): string | null {
    for (const error of this.detalleErrores()) {
      // En un error de detalle el `loc` es [..., 'detalles', <indice>, <campo>]:
      // el nombre del campo es el ultimo elemento y el indice el penultimo.
      const campo = error.loc.at(-1);
      const fila = error.loc.at(-2);
      if (campo === 'cantidad_solicitada' && fila === indice) {
        return this.traducirMensaje(error);
      }
      if (campo === 'producto_id' && fila === indice) {
        return this.traducirMensaje(error);
      }
    }
    return null;
  }

  /**
   * Los mensajes de Pydantic vienen en ingles y con la forma de la libreria
   * ("String should have at most 150 characters"). Se traducen porque el resto
   * de la interfaz esta en espanol y el usuario no tiene por que reconocer un
   * `max_length`.
   */
  private traducirMensaje(error: DetalleError422): string {
    const cantidad = error.msg.match(/(\d+)/)?.[1];
    switch (error.type) {
      case 'string_too_short':
        return `Debe tener al menos ${cantidad ?? 3} caracteres.`;
      case 'string_too_long':
        return `No puede superar los ${cantidad ?? 150} caracteres.`;
      case 'missing':
        return 'Este campo es obligatorio.';
      case 'greater_than':
        return 'La cantidad debe ser mayor que 0.';
      case 'less_than_equal':
        return 'La cantidad debe ser 1 o mayor.';
      case 'too_short':
        return 'Agrega al menos un ítem.';
      default:
        return 'Revisa este valor.';
    }
  }

  // --- Envío ---

  enviar() {
    this.errorGuardado.set(null);
    this.detalleErrores.set([]);

    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }
    if (this.guardando()) {
      return;
    }

    const valor = this.formulario.getRawValue();
    const cuerpo: TicketCrear = {
      usuario_id: valor.usuario_id!,
      prioridad_id: valor.prioridad_id!,
      estado_id: valor.estado_id!,
      asunto: valor.asunto,
      descripcion: valor.descripcion === '' ? null : valor.descripcion,
      detalles: this.combinarDetalles(),
    };

    this.guardando.set(true);
    this.servicioTickets.crearTicket(cuerpo).subscribe({
      next: (ticket: Ticket) => {
        this.guardando.set(false);
        this.ticketCreado.set(ticket.ticket_id);
        // AC-8: el ticket creado se refleja en el tablero sin recargar. Nada de
        // filtrar a mano: el `computed` de columnas aplica los filtros activos,
        // asi que un ticket que no los cumpla queda fuera por construccion.
        this.tickets.update((lista) => [ticket, ...lista]);
        this.cerrarModal();
        this.formulario.reset({ asunto: '', descripcion: '' });
        this.detalles.clear();
        this.detalles.push(this.crearFilaDetalle());
      },
      error: (fallo: { error?: { detail?: unknown } }) => {
        this.guardando.set(false);
        const detalle = fallo?.error?.detail;

        if (Array.isArray(detalle)) {
          this.detalleErrores.set(detalle as DetalleError422[]);
          this.errorGuardado.set('Revisa los campos marcados.');
        } else if (typeof detalle === 'string') {
          // Un 404 de referencia (producto borrado entre la carga del catalogo y
          // el envio, por ejemplo). No se mapea a un control: no sabemos cual, y
          // adivinar seria peor que mostrar el mensaje del backend.
          this.errorGuardado.set(detalle);
        } else {
          this.errorGuardado.set('No se pudo crear el ticket. Inténtalo de nuevo.');
        }
      },
    });
  }

  // --- Transiciones del tablero ---

  /**
   * Mueve un ticket al estado destino y refleja la respuesta sin recargar
   * (AC-9, AC-10, AC-19).
   *
   * Mientras el `PATCH` esta en vuelo el id vive en `enProceso`, asi que la
   * tarjeta muestra el control deshabilitado y un segundo intento se descarta
   * (anti doble envio). Con la respuesta del servidor se **reemplaza** el ticket
   * en `tickets()` con un `.map` inmutable: el `computed` de columnas agrupa de
   * nuevo y mueve la tarjeta (y su contador) sin volver a pedir el tablero.
   *
   * Ante un rechazo (404, 409, 500 o red caida, AC-20) la tarjeta no se toca: se
   * publica el mensaje en `errorMovimiento` (el `detail` del backend si es
   * string, si no uno propio), se libera la tarjeta y se reconsultan los
   * tickets para reflejar la verdad del servidor.
   */
  mover(ticketId: number, destino: number): void {
    if (this.enProceso().has(ticketId)) {
      return;
    }
    // Un intento nuevo borra el aviso de un rechazo anterior; si este falla,
    // la rama de error vuelve a publicarlo.
    this.errorMovimiento.set(null);
    this.enProceso.update((ids) => new Set(ids).add(ticketId));

    this.servicioTickets.actualizarEstado(ticketId, destino).subscribe({
      next: (ticket: Ticket) => {
        this.tickets.update((lista) =>
          lista.map((actual) => (actual.ticket_id === ticketId ? ticket : actual))
        );
        this.liberar(ticketId);
      },
      error: (fallo: { error?: { detail?: unknown } }) => {
        // La tarjeta nunca se mueve con un rechazo (D-7, AC-20): lo unico que
        // cambia en el cliente es el mensaje (con el `detail` del backend si lo
        // trae; si no —500 sin cuerpo o red caida—, uno propio) y la
        // reconsulta, que refleja la verdad del servidor.
        const detalle = fallo?.error?.detail;
        this.errorMovimiento.set(
          typeof detalle === 'string'
            ? detalle
            : 'No se pudo cambiar el estado del ticket. El tablero se actualizó con la información del servidor.'
        );
        this.liberar(ticketId);
        this.reconsultarTickets();
      },
    });
  }

  /**
   * Reconsulta solo los tickets (AC-20): la verdad del servidor tras un
   * rechazo, incluido el caso de que otro usuario ya haya movido el ticket.
   *
   * No es `cargarTablero()`: esa vuelve a pedir tambien los catalogos y pone
   * `cargandoTablero`; aqui solo se reemplaza `tickets()`. Si la reconsulta
   * misma falla, el tablero pasa al estado de error visible (spec §7).
   */
  private reconsultarTickets(): void {
    this.servicioTickets.obtenerTickets().subscribe({
      next: (tickets) => this.tickets.set(tickets),
      error: () => {
        this.errorTablero.set(
          'No se pudo cargar el tablero. Revisa la conexión e inténtalo de nuevo.'
        );
      },
    });
  }

  /** Quita el id de `enProceso` con una copia inmutable del Set. */
  private liberar(ticketId: number): void {
    this.enProceso.update((ids) => {
      const copia = new Set(ids);
      copia.delete(ticketId);
      return copia;
    });
  }

  /** Retrocede la tarjeta un paso en el flujo; no hace nada si no hay anterior. */
  moverAnterior(tarjeta: TarjetaKanban) {
    if (tarjeta.estadoAnteriorId !== null) {
      this.mover(tarjeta.ticket.ticket_id, tarjeta.estadoAnteriorId);
    }
  }

  /** Avanza la tarjeta un paso en el flujo; no hace nada si no hay siguiente. */
  moverSiguiente(tarjeta: TarjetaKanban) {
    if (tarjeta.estadoSiguienteId !== null) {
      this.mover(tarjeta.ticket.ticket_id, tarjeta.estadoSiguienteId);
    }
  }

  }