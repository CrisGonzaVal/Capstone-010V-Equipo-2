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

/** Encabezado de una columna del tablero. */
interface ColumnaKanban {
  estado: string;
  tarjetas: TarjetaKanban[];
}

interface TarjetaKanban {
  referencia: string;
  prioridad: 'ALTA' | 'MEDIA' | 'BAJA';
  departamento: string;
  descripcion: string;
}

/** Un error de validacion de FastAPI, con su `loc` y su mensaje original. */
interface DetalleError422 {
  loc: (string | number)[];
  msg: string;
  type: string;
}

const CLASES_PRIO: Record<TarjetaKanban['prioridad'], string> = {
  ALTA: 'text-rose-600 bg-rose-50',
  MEDIA: 'text-blue-600 bg-blue-50',
  BAJA: 'text-amber-600 bg-amber-50',
};

/**
 * Tablero Kanban de tickets, mas el modal de alta.
 *
 * **El tablero sigue con datos de muestra, no vienen de la API.** Se conserva el
 * comportamiento actual en vez de inventar el agrupamiento: para distribuir
 * tickets en columnas haria falta un endpoint que exponga el *nombre* del
 * estado, porque hoy `Ticket` solo trae `estado_id` y esos ids dependen del
 * orden en que se llenaron las secuencias de identidad.
 *
 * Ya se documento ese problema en el backend como `ESTADO_CERRADO_ID` en
 * `ticket_service.py`: un id fijo resulto ser falso. Codificar el mismo supuesto
 * aca repetiria el error en otra capa. El agrupamiento real llega con el
 * catalogo de estados (Feature 004/005).
 *
 * Lo que si es real es el modal: sus cuatro desplegables se llenan con
 * `GET /tickets/catalogos` y su alta se persiste con `POST /tickets/`. Que el
 * tablero no se actualice al crear un ticket es deliberado (spec, H-3).
 */
@Component({
  selector: 'app-tickets',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './tickets.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TicketsComponent {
  readonly columnas = signal<ColumnaKanban[]>([
    {
      estado: 'INGRESADO',
      tarjetas: [
        {
          referencia: '#101',
          prioridad: 'ALTA',
          departamento: 'Dpto. Salud',
          descripcion: 'Insumos varios: Guantes, Mascarillas, Jeringas',
        },
        {
          referencia: '#102',
          prioridad: 'BAJA',
          departamento: 'Construcción',
          descripcion: 'Materiales: Cemento, Ladrillos',
        },
      ],
    },
    {
      estado: 'EN PREPARACIÓN',
      tarjetas: [
        {
          referencia: '#099',
          prioridad: 'MEDIA',
          departamento: 'Dpto. Administración',
          descripcion: 'Artículos de oficina: Papel, Toner, Carpetas',
        },
        {
          referencia: '#098',
          prioridad: 'ALTA',
          departamento: 'Dpto. IT',
          descripcion: 'Componentes: Cable UTP, Monitores',
        },
      ],
    },
    {
      estado: 'DESPACHADO',
      tarjetas: [
        {
          referencia: '#095',
          prioridad: 'BAJA',
          departamento: 'Dpto. Logística',
          descripcion: 'Herramientas: Cajas plásticas, Etiquetas',
        },
      ],
    },
    {
      estado: 'ENTREGADO',
      tarjetas: [
        {
          referencia: '#090',
          prioridad: 'MEDIA',
          departamento: 'Dpto. Ventas',
          descripcion: 'Material promocional: Folletos, Banners',
        },
      ],
    },
  ]);

  readonly clasesPrioridad = CLASES_PRIO;

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

  // --- Acciones del modal ---

  abrirModal() {
    this.errorGuardado.set(null);
    this.errorCatalogos.set(null);
    this.detalleErrores.set([]);
    this.ticketCreado.set(null);
    this.modalAbierto.set(true);

    // Los catalogos se piden al abrir, no en `ngOnInit`: si el usuario nunca
    // abre el modal, no se descargo nada. Con una sola peticion no hace falta
    // `forkJoin`, que solo tiene sentido cuando hay varias y se quiere un unico
    // estado de carga.
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

  }