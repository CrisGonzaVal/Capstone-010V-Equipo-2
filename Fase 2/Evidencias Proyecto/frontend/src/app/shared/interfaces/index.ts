/**
 * Tipos compartidos que reflejan 1:1 los schemas de `backend/app/schemas/`.
 *
 * El backend serializa en `snake_case` y no aplica un alias de camelCase, asi
 * que estos tipos usan `snake_case` a proposito: cualquier normalizacion
 * tendria que happen en el servicio, no en la vista.
 *
 * Antes de editar estos tipos, cambia el schema Pydantic correspondiente y no
 * al reves: el contrato de la API es el que manda.
 */

// --- Inventario ---

export interface Categoria {
  categoria_id: number;
  nombre_cat: string;
  descripcion_cat: string | null;
}

export interface Producto {
  producto_id: number;
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
  categoria: Categoria | null;
}

export interface Inventario {
  inventario_id: number;
  stock_actual: number;
  ubicacion: string | null;
  departamento_id: number;
  producto_id: number;
  producto: Producto | null;
}

export interface ProductoCrear {
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
}

export type TipoMovimiento = 'ENTRADA' | 'SALIDA';

export interface MovimientoCrear {
  tipo_movimiento: TipoMovimiento;
  cantidad: number;
  observacion: string | null;
  inventario_id: number;
}

/** Respuesta de `POST /inventario/movimientos` (no usa `response_model`). */
export interface RespuestaMovimiento {
  message: string;
  nuevo_stock: number;
}

// --- Tickets ---

export interface DetalleTicket {
  detalle_ticket_id: number;
  producto_id: number;
  cantidad_solicitada: number;
  cantidad_entregada: number;
  producto: Producto | null;
}

export interface Ticket {
  ticket_id: number;
  usuario_id: number;
  prioridad_id: number;
  estado_id: number;
  asunto: string;
  descripcion: string | null;
  fecha_creacion: string;
  fecha_cierre: string | null;
  detalles: DetalleTicket[];
}

export interface DetalleTicketCrear {
  producto_id: number;
  cantidad_solicitada: number;
}

export interface TicketCrear {
  usuario_id: number;
  prioridad_id: number;
  estado_id: number;
  asunto: string;
  descripcion: string | null;
  detalles: DetalleTicketCrear[];
}

// --- Usuarios ---

export interface Usuario {
  usuario_id: number;
  nombre: string;
  apellido: string;
  correo: string;
  departamento_id: number;
  rol_id: number;
}

export interface Rol {
  rol_id: number;
  nombre_rol: string;
  descripcion: string | null;
}

export interface Departamento {
  departamento_id: number;
  nombre_dep: string;
  descripcion: string | null;
  institucion_id: string;
}

export interface Institucion {
  institucion_id: string;
  nombre: string;
  rut: string;
  direccion: string | null;
}