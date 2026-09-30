import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

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

const CLASES_PRIO = {
  ALTA: 'text-rose-600 bg-rose-50',
  MEDIA: 'text-blue-600 bg-blue-50',
  BAJA: 'text-amber-600 bg-amber-50',
} as const;

/**
 * Tablero Kanban de tickets.
 *
 * **Los datos son de muestra, no vienen de la API.** Se conserva el
 * comportamiento actual en vez de inventar el agrupamiento: para distribuir
 * tickets en columnas haria falta un endpoint que exponga el *nombre* del
 * estado, porque hoy `Ticket` solo trae `estado_id` y esos ids dependen del
 * orden en que se llenaron las secuencias de identidad.
 *
 * Ya se documento ese problema en el backend como `ESTADO_CERRADO_ID` en
 * `ticket_service.py`: un id fijo resulto ser falso. Codificar el mismo supuesto
 * aca repetiria el error en otra capa. El agrupamiento real llega con el
 * catalogo de estados (Feature 004/005).
 */
@Component({
  selector: 'app-tickets',
  standalone: true,
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
}