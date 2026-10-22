import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';

import {
  puedeAnularTicket,
  puedeEditarTicket,
  puedeOperarTickets,
  puedeRechazarTicket,
} from '../../core/auth/roles';
import { AutenticacionService } from '../../core/services/auth.service';
import {
  CatalogosTicket,
  DetalleTicket,
  DetalleTicketCrear,
  EstadoTicket,
  HistorialTransicion,
  ProductoCatalogo,
  TicketDetalle,
  TicketEditar,
} from '../../shared/interfaces';
import { TicketService } from './services/ticket.service';

/** Fila resuelta del historial para el template (sin ids que el template no conozca). */
interface FilaHistorial {
  historial_transicion_id: number;
  origen: string;
  destino: string;
  actor: string;
  fecha: string;
  motivo: string | null;
}

/** Acciones que la barra ofrece según estado y rol (AC-24). */
interface AccionesDetalle {
  avanzar: boolean;
  retroceder: boolean;
  editar: boolean;
  anular: boolean;
  rechazar: boolean;
}

/**
 * Opción de un selector de producto de la edición (Feature 014, AC-9).
 *
 * `inactivo` distingue el producto que ya figura en los detalles actuales del
 * ticket y ya no está disponible: se ofrece **solo en su propia fila** para
 * conservarlo, nunca en una línea nueva.
 */
interface OpcionProductoEdicion {
  producto_id: number;
  etiqueta: string;
  inactivo: boolean;
}

/** Badge de prioridad por su nombre real; sin correspondencia, clase neutra. */
const CLASES_PRIORIDAD: Record<string, string> = {
  ALTA: 'text-rose-600 bg-rose-50',
  MEDIA: 'text-blue-600 bg-blue-50',
  BAJA: 'text-amber-600 bg-amber-50',
};

/**
 * Mensaje legible de un fallo del ciclo de vida (Feature 013).
 *
 * Prefiere el `detail` textual del backend —404 oculto, 409 de flujo y 422 de
 * motivo/edición del contrato §6— y, si no hay texto (500 sin cuerpo, red
 * caída, lista de validación de Pydantic), recurre al código de estado.
 */
export function mensajeDeErrorTickets(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  if (typeof detalle === 'string' && detalle.trim() !== '') {
    return detalle;
  }
  switch (error.status) {
    case 401:
      return 'Tu sesión no es válida. Vuelve a iniciar sesión.';
    case 403:
      return 'Tu rol no tiene permiso para esta operación sobre el ticket.';
    case 404:
      return 'El ticket indicado no existe o no está en tu alcance.';
    case 409:
      return 'La operación entra en conflicto con el estado actual del ticket.';
    case 422:
      return 'Los datos enviados no son válidos: revisa el motivo y los campos del ticket.';
    case 0:
      return 'No se pudo contactar al servidor. Verifica la conexión e inténtalo de nuevo.';
    default:
      return `No se pudo completar la operación (HTTP ${error.status}).`;
  }
}

/**
 * Vista de detalle del ticket (Feature 013, D-13/AC-23/AC-24).
 *
 * Muestra cabecera (asunto, prioridad, estado, solicitante con departamento,
 * sede y fechas), ítems con cantidades solicitadas y entregadas, y el
 * historial completo. **Toda mutación del ciclo de vida se opera aquí** (D-14):
 * avanzar/retroceder vía `PATCH /estado`, edición en `Pendiente` y
 * anulación/rechazo con confirmación previa que exige motivo. La barra de
 * acciones se deriva del estado y del rol (AC-24); `Cerrado` y `Anulado` no
 * ofrecen ninguna (terminales por nombre, D-4).
 *
 * Tras cada mutación aceptada —y también tras un rechazo del servidor— se
 * reconsultan detalle e historial para reflejar la verdad del backend. Un
 * `enOperacion` común bloquea todos los controles mientras hay una petición en
 * vuelo (anti doble envío).
 */
@Component({
  selector: 'app-ticket-detalle',
  standalone: true,
  imports: [ReactiveFormsModule, DatePipe, RouterLink],
  templateUrl: './ticket-detalle.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TicketDetalleComponent {
  private readonly servicioTickets = inject(TicketService);
  private readonly autenticacion = inject(AutenticacionService);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(NonNullableFormBuilder);

  // --- Estado de la carga ---

  readonly ticketId = signal<number | null>(null);
  readonly ticket = signal<TicketDetalle | null>(null);
  readonly historial = signal<HistorialTransicion[]>([]);
  readonly catalogos = signal<CatalogosTicket | null>(null);
  readonly cargando = signal(true);
  readonly errorCarga = signal<string | null>(null);

  // --- Estado de las operaciones ---

  readonly errorAccion = signal<string | null>(null);
  readonly mensajeExito = signal<string | null>(null);
  /** `true` mientras una mutación está en vuelo: bloquea todos los controles. */
  readonly enOperacion = signal(false);
  /** `null` sin confirmación abierta; `'anular'` o `'rechazo'` con el modal. */
  readonly confirmando = signal<'anular' | 'rechazo' | null>(null);
  readonly editando = signal(false);

  // --- Identidad (presentación; la autorización la decide la API, D-2) ---

  readonly rolActual = computed(() => this.autenticacion.identidad()?.rol ?? null);

  /** `true` si el ticket abierto pertenece al usuario de la sesión. */
  readonly esDueno = computed(() => {
    const identidad = this.autenticacion.identidad();
    const ticket = this.ticket();
    return identidad !== null && ticket !== null && identidad.usuario_id === ticket.usuario_id;
  });

  // --- Catálogos resolutivos ---

  readonly estados = computed<EstadoTicket[]>(() => this.catalogos()?.estados ?? []);
  readonly prioridades = computed(() => this.catalogos()?.prioridades ?? []);
  /**
   * Productos disponibles del catálogo. El servidor ya excluye inactivos y los
   * de categoría inactiva; el filtro es la salvaguarda de UI (AC-4/AC-9).
   */
  readonly productos = computed<ProductoCatalogo[]>(() =>
    (this.catalogos()?.productos ?? []).filter((producto) => producto.activo !== false)
  );
  readonly solicitantes = computed(() => this.catalogos()?.solicitantes ?? []);

  // --- Derivación del estado actual ---

  /** Nombre del estado del ticket: catálogo por id, luego el campo del detalle. */
  readonly nombreEstado = computed<string | null>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return null;
    }
    return (
      this.estados().find((estado) => estado.estado_id === ticket.estado_id)?.nombre ??
      ticket.estado_nombre ??
      null
    );
  });

  private readonly estadoNormalizado = computed(() =>
    this.nombreEstado() === null ? null : normalizar(this.nombreEstado()!),
  );

  /** Terminales por nombre, nunca por posición del catálogo (D-4). */
  private readonly esTerminal = computed(() => {
    const estado = this.estadoNormalizado();
    return estado === 'cerrado' || estado === 'anulado';
  });

  private readonly esEnCurso = computed(() => this.estadoNormalizado() === 'encurso');

  private readonly admiteAnulacionORechazo = computed(() => {
    const estado = this.estadoNormalizado();
    return estado === 'pendiente' || estado === 'enrevision';
  });

  /** Posición del estado del ticket en el orden del catálogo; `-1` si no está. */
  private readonly indiceEstado = computed(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return -1;
    }
    return this.estados().findIndex((estado) => estado.estado_id === ticket.estado_id);
  });

  /** Id del estado contiguo siguiente, sin saltos y nunca hacia un terminal. */
  private readonly idEstadoSiguiente = computed<number | null>(() => {
    const indice = this.indiceEstado();
    if (indice < 0 || this.esTerminal() || this.esEnCurso()) {
      // El avance desde `EnCurso` está reservado al despacho de la 005 (AC-16).
      return null;
    }
    const siguiente = this.estados()[indice + 1] ?? null;
    if (siguiente === null || esEstadoTerminal(siguiente.nombre)) {
      return null;
    }
    return siguiente.estado_id;
  });

  /** Id del estado contiguo anterior (nunca desde un terminal). */
  private readonly idEstadoAnterior = computed<number | null>(() => {
    const indice = this.indiceEstado();
    if (indice <= 0 || this.esTerminal()) {
      return null;
    }
    return this.estados()[indice - 1].estado_id;
  });

  /**
   * Acciones ofrecidas por estado y rol (AC-24).
   *
   * Transiciones: solo roles operativos (la 004 vigente por matriz). Anulación
   * y edición: Administrador o el **dueño** Solicitante. Rechazo: Bodeguero o
   * Administrador. Solo `Pendiente`/`EnRevision` admiten anular/rechazar (D-3)
   * y solo `Pendiente` admite edición (D-9). En `Cerrado`/`Anulado` no se
   * ofrece nada.
   */
  readonly acciones = computed<AccionesDetalle>(() => {
    const rol = this.rolActual();
    const estado = this.estadoNormalizado();
    const esAdministrador = rol === 'Administrador';
    const esDueno = this.esDueno();
    return {
      avanzar: puedeOperarTickets(rol) && this.idEstadoSiguiente() !== null,
      retroceder: puedeOperarTickets(rol) && this.idEstadoAnterior() !== null,
      editar:
        estado === 'pendiente' &&
        puedeEditarTicket(rol) &&
        (esAdministrador || esDueno),
      anular:
        this.admiteAnulacionORechazo() &&
        puedeAnularTicket(rol) &&
        (esAdministrador || esDueno),
      rechazar: this.admiteAnulacionORechazo() && puedeRechazarTicket(rol),
    };
  });

  /** `true` si al menos una acción está disponible. */
  readonly hayAcciones = computed(() => Object.values(this.acciones()).some(Boolean));

  /**
   * Nota visible cuando no hay ninguna acción: distingue el terminal (estado
   * del ticket) del permiso (rol), para que el vacío sea informativo (AC-23).
   */
  readonly notaAcciones = computed<string | null>(() => {
    if (this.hayAcciones() || this.ticket() === null) {
      return null;
    }
    if (this.esTerminal()) {
      return 'Este ticket está en un estado terminal (Cerrado o Anulado): no admite acciones del ciclo de vida.';
    }
    return 'Tu rol no puede operar el ciclo de vida de este ticket: solo puede consultarlo.';
  });

  // --- Etiquetas de presentación ---

  readonly etiquetaPrioridad = computed<string>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return '';
    }
    const prioridad = this.prioridades().find(
      (p) => p.prioridad_id === ticket.prioridad_id,
    );
    return prioridad?.nombre ?? ticket.prioridad_nombre ?? `Prioridad #${ticket.prioridad_id}`;
  });

  /** Clase Tailwind del badge de prioridad, tolerante a mayúsculas (mismo criterio que el tablero). */
  readonly clasePrioridad = computed(() => {
    const nombre = this.etiquetaPrioridad().toUpperCase();
    return CLASES_PRIORIDAD[nombre] ?? 'text-slate-600 bg-slate-100';
  });

  readonly etiquetaEstado = computed<string>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return '';
    }
    return this.nombreEstado() ?? `Estado #${ticket.estado_id}`;
  });

  /** Badge de estado: `Anulado` y `Cerrado` se distinguen de un vistazo (AC-23). */
  readonly claseEstado = computed(() => {
    const estado = this.estadoNormalizado();
    if (estado === 'anulado') {
      return 'text-rose-700 bg-rose-50';
    }
    if (estado === 'cerrado') {
      return 'text-emerald-700 bg-emerald-50';
    }
    if (estado === 'encurso') {
      return 'text-indigo-700 bg-indigo-50';
    }
    if (estado === 'enrevision') {
      return 'text-amber-700 bg-amber-50';
    }
    return 'text-slate-700 bg-slate-100';
  });

  readonly etiquetaSolicitante = computed<string>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return '';
    }
    const solicitante = this.solicitantes().find(
      (s) => s.usuario_id === ticket.usuario_id,
    );
    if (solicitante) {
      return `${solicitante.apellido}, ${solicitante.nombre}`;
    }
    const nombre = [ticket.solicitante_apellido, ticket.solicitante_nombre]
      .filter((parte): parte is string => typeof parte === 'string' && parte !== '')
      .join(', ');
    return nombre !== '' ? nombre : `Usuario #${ticket.usuario_id}`;
  });

  readonly correoSolicitante = computed<string | null>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return null;
    }
    return (
      this.solicitantes().find((s) => s.usuario_id === ticket.usuario_id)?.correo ??
      ticket.solicitante_correo ??
      null
    );
  });

  readonly etiquetaDepartamento = computed<string | null>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return null;
    }
    return (
      this.solicitantes().find((s) => s.usuario_id === ticket.usuario_id)
        ?.departamento_nombre ??
      ticket.departamento_nombre ??
      null
    );
  });

  readonly etiquetaSede = computed<string>(() => {
    const ticket = this.ticket();
    if (ticket === null) {
      return '';
    }
    if (ticket.sede_nombre) {
      return ticket.sede_nombre;
    }
    return ticket.sede_id !== null ? `Sede #${ticket.sede_id}` : 'Sin sede registrada';
  });

  // --- Historial resuelto ---

  /** Historial listo para el template: nombres resueltos, sin ids sueltos. */
  readonly filasHistorial = computed<FilaHistorial[]>(() =>
    this.historial().map((fila) => ({
      historial_transicion_id: fila.historial_transicion_id,
      origen:
        fila.estado_origen_id === null
          ? 'Creación'
          : (fila.estado_origen_nombre ??
            this.nombreDeEstado(fila.estado_origen_id) ??
            `Estado #${fila.estado_origen_id}`),
      destino:
        fila.estado_destino_nombre ??
        this.nombreDeEstado(fila.estado_destino_id) ??
        `Estado #${fila.estado_destino_id}`,
      actor: this.actorDeFila(fila),
      fecha: fila.fecha_transicion,
      motivo: fila.motivo,
    })),
  );

  // --- Formularios ---

  /** Motivo obligatorio de la confirmación de anulación/rechazo (D-6). */
  readonly motivoForm = this.fb.group({
    motivo: ['', [Validators.required, Validators.maxLength(500)]],
  });

  /** Edición en `Pendiente`: asunto, descripción, prioridad e ítems completos (D-9). */
  readonly formularioEdicion = this.fb.group({
    asunto: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(150)]],
    descripcion: [''],
    prioridad_id: [null as number | null, Validators.required],
    detalles: this.fb.array([this.crearFilaEdicion()]),
  });

  readonly detallesEdicion = this.formularioEdicion.controls.detalles;

  crearFilaEdicion() {
    return this.fb.group({
      producto_id: [null as number | null, Validators.required],
      cantidad_solicitada: [1, [Validators.required, Validators.min(1)]],
    });
  }

  agregarDetalleEdicion() {
    this.detallesEdicion.push(this.crearFilaEdicion());
  }

  /** Con una sola fila no se quita: el backend exige al menos un ítem (422). */
  puedeQuitarDetalleEdicion(): boolean {
    return this.detallesEdicion.length > 1;
  }

  quitarDetalleEdicion(indice: number) {
    if (this.puedeQuitarDetalleEdicion()) {
      this.detallesEdicion.removeAt(indice);
    }
  }

  /** Ítems repetidos por producto se fusionan antes de enviar (mismo criterio que el alta). */
  combinarDetallesEdicion(): DetalleTicketCrear[] {
    const cantidades = new Map<number, number>();
    for (const fila of this.detallesEdicion.controls) {
      const productoId = fila.controls.producto_id.value;
      if (productoId === null) {
        continue;
      }
      cantidades.set(
        productoId,
        (cantidades.get(productoId) ?? 0) + fila.controls.cantidad_solicitada.value,
      );
    }
    return [...cantidades].map(([producto_id, cantidad_solicitada]) => ({
      producto_id,
      cantidad_solicitada,
    }));
  }

  /**
   * Opciones del selector de producto de una fila de edición (Feature 014, AC-9).
   *
   * Ofrece los productos **activos** del catálogo y, además, el producto de esa
   * misma fila cuando ya figura en los detalles actuales del ticket y dejó de
   * estar disponible. Así un ítem cuyo producto se retiró se puede conservar y
   * su cantidad modificar, pero no se puede elegir ese producto en una línea
   * nueva: una fila nueva arranca sin producto y solo recibe opciones activas.
   *
   * El servidor aplica la misma delimitación por `producto_id` (D-7): un
   * inactivo que no figure en los detalles actuales responde 409.
   */
  opcionesProductoEdicion(indice: number): OpcionProductoEdicion[] {
    const activos = this.productos().map((producto) => ({
      producto_id: producto.producto_id,
      etiqueta: `${producto.nombre} · ${producto.categoria_nombre}`,
      inactivo: false,
    }));

    const productoId = this.detallesEdicion.at(indice)?.controls.producto_id.value ?? null;
    if (productoId === null || activos.some((opcion) => opcion.producto_id === productoId)) {
      return activos;
    }

    const detalle = this.detalleActual(productoId);
    return [
      ...activos,
      {
        producto_id: productoId,
        etiqueta:
          detalle === null
            ? `Producto #${productoId} — no disponible (solo se conserva)`
            : this.etiquetaProductoConservado(detalle),
        inactivo: true,
      },
    ];
  }

  /** `true` si la fila conserva un producto que ya no está disponible. */
  esProductoInactivoEdicion(indice: number): boolean {
    const productoId = this.detallesEdicion.at(indice)?.controls.producto_id.value ?? null;
    return this.opcionesProductoEdicion(indice).some(
      (opcion) => opcion.inactivo && opcion.producto_id === productoId,
    );
  }

  /** Fila de los detalles **actuales** del ticket para un producto, si existe. */
  private detalleActual(productoId: number): DetalleTicket | null {
    return this.ticket()?.detalles.find((detalle) => detalle.producto_id === productoId) ?? null;
  }

  /**
   * Etiqueta de un producto conservado: nombre y categoría resueltos para que
   * la fila sea legible aunque el producto ya no viaje en el catálogo.
   */
  private etiquetaProductoConservado(detalle: DetalleTicket): string {
    const nombre = detalle.producto?.nombre ?? `Producto #${detalle.producto_id}`;
    const categoria = detalle.producto?.categoria?.nombre_cat;
    const base = categoria ? `${nombre} · ${categoria}` : nombre;
    return `${base} — inactivo (solo se conserva)`;
  }

  // --- Diálogos ---

  readonly dialogoConfirmacion =
    viewChild.required<ElementRef<HTMLDialogElement>>('dialogoConfirmacion');
  readonly dialogoEdicion = viewChild.required<ElementRef<HTMLDialogElement>>('dialogoEdicion');

  constructor() {
    // El `<dialog>` nativo da foco atrapado, `Esc` y fondo atenuado sin código de
    // foco propio (mismo patrón que el modal del tablero). Los diálogos viven
    // siempre en el DOM; estas señales solo abren/cierran.
    effect(() => {
      const tipo = this.confirmando();
      const nativo = this.dialogoConfirmacion().nativeElement;
      if (tipo !== null && !nativo.open) {
        nativo.showModal();
      }
      if (tipo === null && nativo.open) {
        nativo.close();
      }
    });
    effect(() => {
      const abierto = this.editando();
      const nativo = this.dialogoEdicion().nativeElement;
      if (abierto && !nativo.open) {
        nativo.showModal();
      }
      if (!abierto && nativo.open) {
        nativo.close();
      }
    });

    // La ruta `tickets/:ticketId` fija el id; cada cambio de parámetro recarga.
    this.route.paramMap.subscribe((parametros) => {
      const crudo = parametros.get('ticketId');
      const numero = crudo === null ? Number.NaN : Number(crudo);
      this.ticketId.set(Number.isNaN(numero) ? null : numero);
      this.cargar();
    });
  }

  // --- Carga ---

  /** Carga inicial y visible: detalle + historial + catálogos (los catálogos solo si faltan). */
  private cargar(): void {
    if (this.ticketId() === null) {
      this.cargando.set(false);
      this.errorCarga.set('El identificador del ticket no es válido.');
      return;
    }
    this.cargando.set(true);
    this.errorCarga.set(null);
    this.errorAccion.set(null);
    this.mensajeExito.set(null);

    forkJoin({
      detalle: this.servicioTickets.obtenerDetalleTicket(this.ticketId()!),
      historial: this.servicioTickets.obtenerHistorial(this.ticketId()!),
      catalogos:
        this.catalogos() === null
          ? this.servicioTickets.obtenerCatalogos()
          : of(this.catalogos()!),
    }).subscribe({
      next: ({ detalle, historial, catalogos }) => {
        this.catalogos.set(catalogos);
        this.ticket.set(detalle);
        this.historial.set(historial);
        this.cargando.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.ticket.set(null);
        this.historial.set([]);
        this.cargando.set(false);
        this.errorCarga.set(mensajeDeErrorTickets(error));
      },
    });
  }

  /** Reintenta la carga visible tras un error (404 incluido: cambia el id o vuelve). */
  reintentar(): void {
    this.cargar();
  }

  /**
   * Reconsulta silenciosa de detalle e historial: la verdad del servidor tras
   * una mutación aceptada o rechazada (AC-24), sin esconder la vista tras un
   * spinner global. Si la reconsulta falla, el aviso de la operación ya visible
   * manda y aquí no se duplica el error.
   */
  private reconsultar(): void {
    const id = this.ticketId();
    if (id === null) {
      return;
    }
    forkJoin({
      detalle: this.servicioTickets.obtenerDetalleTicket(id),
      historial: this.servicioTickets.obtenerHistorial(id),
    }).subscribe({
      next: ({ detalle, historial }) => {
        this.ticket.set(detalle);
        this.historial.set(historial);
      },
      error: () => {
        /* silencioso: el error de la operación ya está publicado */
      },
    });
  }

  // --- Transiciones del flujo lineal (PATCH /estado) ---

  /** Avanza un paso en el flujo lineal. No hace nada sin destino. */
  avanzar(): void {
    this.transicion(this.idEstadoSiguiente());
  }

  /** Retrocede un paso en el flujo lineal. No hace nada sin destino. */
  retroceder(): void {
    this.transicion(this.idEstadoAnterior());
  }

  private transicion(destino: number | null): void {
    if (destino === null || this.enOperacion() || this.ticketId() === null) {
      return;
    }
    this.limpiarAvisos();
    this.enOperacion.set(true);
    this.servicioTickets.actualizarEstado(this.ticketId()!, destino).subscribe({
      next: () => this.terminarOperacion('Estado del ticket actualizado.'),
      error: (error: HttpErrorResponse) => this.fallarOperacion(error),
    });
  }

  // --- Anulación y rechazo (confirmación con motivo obligatorio) ---

  solicitarAnulacion(): void {
    if (this.enOperacion() || !this.acciones().anular) {
      return;
    }
    this.limpiarAvisos();
    this.motivoForm.reset({ motivo: '' });
    this.confirmando.set('anular');
  }

  solicitarRechazo(): void {
    if (this.enOperacion() || !this.acciones().rechazar) {
      return;
    }
    this.limpiarAvisos();
    this.motivoForm.reset({ motivo: '' });
    this.confirmando.set('rechazo');
  }

  cancelarConfirmacion(): void {
    if (this.enOperacion()) {
      return;
    }
    this.confirmando.set(null);
  }

  /** Envía la anulación/rechazo. El motivo vacío o en blanco no sale del cliente. */
  confirmar(): void {
    const tipo = this.confirmando();
    if (tipo === null || this.enOperacion() || this.ticketId() === null) {
      return;
    }
    const motivo = this.motivoForm.controls.motivo.value.trim();
    if (motivo === '') {
      this.motivoForm.controls.motivo.markAsTouched();
      return;
    }
    this.limpiarAvisos();
    this.enOperacion.set(true);
    const peticion =
      tipo === 'anular'
        ? this.servicioTickets.anularTicket(this.ticketId()!, motivo)
        : this.servicioTickets.rechazarTicket(this.ticketId()!, motivo);
    peticion.subscribe({
      next: () => {
        this.confirmando.set(null);
        this.terminarOperacion(tipo === 'anular' ? 'Ticket anulado.' : 'Ticket rechazado.');
      },
      error: (error: HttpErrorResponse) => this.fallarOperacion(error),
    });
  }

  // --- Edición en Pendiente (PUT) ---

  /** Abre el formulario de edición precargado con el ticket actual (D-9). */
  iniciarEdicion(): void {
    const ticket = this.ticket();
    if (ticket === null || this.enOperacion() || !this.acciones().editar) {
      return;
    }
    this.limpiarAvisos();
    this.formularioEdicion.reset({
      asunto: ticket.asunto,
      descripcion: ticket.descripcion ?? '',
      prioridad_id: ticket.prioridad_id,
    });
    this.detallesEdicion.clear();
    for (const detalle of ticket.detalles) {
      this.detallesEdicion.push(
        this.fb.group({
          producto_id: [detalle.producto_id as number | null, Validators.required],
          cantidad_solicitada: [
            detalle.cantidad_solicitada,
            [Validators.required, Validators.min(1)],
          ],
        }),
      );
    }
    if (this.detallesEdicion.length === 0) {
      // Un ticket sin ítems no puede editarse en el backend (422: al menos un
      // detalle); se ofrece una fila vacía para agregar el primero.
      this.detallesEdicion.push(this.crearFilaEdicion());
    }
    this.editando.set(true);
  }

  cancelarEdicion(): void {
    if (this.enOperacion()) {
      return;
    }
    this.editando.set(false);
  }

  /** Envía la edición completa (`PUT`): cabecera + reemplazo del conjunto de ítems. */
  guardarEdicion(): void {
    if (this.enOperacion() || this.ticketId() === null) {
      return;
    }
    if (this.formularioEdicion.invalid) {
      this.formularioEdicion.markAllAsTouched();
      return;
    }
    const valores = this.formularioEdicion.getRawValue();
    const cuerpo: TicketEditar = {
      asunto: valores.asunto.trim(),
      descripcion: valores.descripcion.trim() === '' ? null : valores.descripcion.trim(),
      prioridad_id: valores.prioridad_id!,
      detalles: this.combinarDetallesEdicion(),
    };
    this.limpiarAvisos();
    this.enOperacion.set(true);
    this.servicioTickets.editarTicket(this.ticketId()!, cuerpo).subscribe({
      next: () => {
        this.editando.set(false);
        this.terminarOperacion('Ticket editado.');
      },
      error: (error: HttpErrorResponse) => this.fallarOperacion(error),
    });
  }

  // --- Ciclo común de las mutaciones ---

  /** Éxito: cierra modales, publica el aviso y reconsulta detalle + historial. */
  private terminarOperacion(mensaje: string): void {
    this.mensajeExito.set(mensaje);
    this.reconsultar();
    this.enOperacion.set(false);
  }

  /** Rechazo del servidor (404/409/422/…): mensaje accesible y reconsulta. */
  private fallarOperacion(error: HttpErrorResponse): void {
    this.errorAccion.set(mensajeDeErrorTickets(error));
    this.reconsultar();
    this.enOperacion.set(false);
  }

  private limpiarAvisos(): void {
    this.errorAccion.set(null);
    this.mensajeExito.set(null);
  }

  // --- Auxiliares de presentación ---

  private nombreDeEstado(estadoId: number): string | null {
    return this.estados().find((estado) => estado.estado_id === estadoId)?.nombre ?? null;
  }

  /** Actor de la fila: nombre y apellido resueltos, con degradación a `#id`. */
  private actorDeFila(fila: HistorialTransicion): string {
    const partes = [fila.usuario_apellido, fila.usuario_nombre].filter(
      (parte): parte is string => typeof parte === 'string' && parte !== '',
    );
    return partes.length > 0 ? partes.join(', ') : `Usuario #${fila.usuario_id}`;
  }
}

/** Normaliza para comparar nombres de estado: sin acentos, minúsculas, sin sobrantes. */
function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

/**
 * `true` si el nombre de estado es uno de los dos terminales canónicos (D-4),
 * reconocidos por nombre y no por su posición en el catálogo.
 */
function esEstadoTerminal(nombre: string): boolean {
  const propio = normalizar(nombre);
  return propio === 'cerrado' || propio === 'anulado';
}
