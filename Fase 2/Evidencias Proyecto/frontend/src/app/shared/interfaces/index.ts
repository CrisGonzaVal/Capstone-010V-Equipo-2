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

/**
 * Existencia de un producto en una sede (Feature 011, D-6/AC-11).
 *
 * Refleja 1:1 el `SedeExistenciaRespuesta` del backend: la granularidad vigente
 * es `(sede, producto)` y el nombre de la sede viaja resuelto para que la vista
 * no tenga que cruzar `sede_id` contra `/organizacion/sedes`.
 */
export interface SedeExistencia {
  sede_id: number;
  sede_nombre: string;
  stock_actual: number;
}

/**
 * Read model de `GET /inventario/existencias`: un elemento por producto del
 * catalogo, con el total ya calculado y el desglose por sede.
 */
export interface ProductoExistencia {
  producto_id: number;
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
  categoria_nombre: string;
  stock_total: number;
  es_critico: boolean;
  sedes: SedeExistencia[];
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

/** Catálogos de `GET /tickets/catalogos`, que pueblan el modal de creación. */

export interface Prioridad {
  prioridad_id: number;
  nombre: string;
  descripcion: string | null;
}

/** `estado_final` no existe en la tabla `estado_ticket`: el catalogo solo
 * proyecta sus tres columnas. Que un estado sea final es una regla del flujo
 * (Feature 004), no del esquema. */
export interface EstadoTicket {
  estado_id: number;
  nombre: string;
  descripcion: string | null;
}

export interface ProductoCatalogo {
  producto_id: number;
  nombre: string;
  unidad_medida: string | null;
  categoria_nombre: string;
  stock_total: number;
  es_critico: boolean;
}

export interface Solicitante {
  usuario_id: number;
  nombre: string;
  apellido: string;
  correo: string;
  departamento_nombre: string;
}

export interface CatalogosTicket {
  prioridades: Prioridad[];
  estados: EstadoTicket[];
  productos: ProductoCatalogo[];
  solicitantes: Solicitante[];
}

// --- Autenticación ---

/**
 * Institución efectiva del usuario autenticado (Feature 008, AC-17).
 *
 * Refleja 1:1 el `InstitucionEfectivaRespuesta` de
 * `backend/app/schemas/auth_schema.py`: `institucion_id` es la misma clave que
 * la entidad `Institucion` (y la que expone `GET /usuarios/instituciones`) y
 * `nombre` es su etiqueta legible. Es **contexto informativo** de UI: nunca
 * autoriza ni permite elegir el ámbito, que resuelve el servidor.
 */
export interface InstitucionEfectiva {
  institucion_id: string;
  nombre: string;
}

/**
 * Respuesta de `GET /api/v1/auth/me` (identidad local vinculada).
 *
 * Refleja 1:1 el `IdentidadAutenticadaRespuesta` de
 * `backend/app/schemas/auth_schema.py`: los siete campos del backend y **no**
 * `rol_id`. `correo` es el correo del registro local (clave del vínculo), no el
 * del perfil de Clerk, y `rol` es el nombre legible (`rol.nombre_rol`).
 *
 * `institucion` (Feature 008, AC-17) es la institución efectiva derivada en el
 * servidor para Administrador, Bodeguero y Solicitante; es `null` para
 * Superadmin, que conserva su carácter global. El campo es informativo: la
 * vista lo presenta como contexto y no lo trata como autorización.
 */
export interface IdentidadAutenticada {
  usuario_id: number;
  sub: string;
  nombre: string;
  apellido: string;
  correo: string;
  rol: string;
  institucion: InstitucionEfectiva | null;
}

// --- Dashboard analítico ---

/**
 * Los cuatro KPI del dashboard consolidado (Feature 009, D-4).
 *
 * Refleja 1:1 el `DashboardKpiRespuesta` de `backend/app/schemas/dashboard_schema.py`.
 * Todos los conteos son escalares: sin datos devuelven cero.
 */
export interface DashboardKpi {
  unidades_en_stock: number;
  tickets_activos: number;
  total_departamentos: number;
  total_alertas: number;
}

/**
 * Fila de stock por sede actualmente crítica (Features 009 y 011, D-1/D-6).
 *
 * Refleja 1:1 el `AlertaStockRespuesta` del backend (Feature 011): una fila es
 * crítica si `stock_actual <= stock_minimo` por pareja **sede-producto**, así que
 * la alerta identifica la bodega física y se atribuye a la sede
 * (`sede_id`/`sede_nombre`) y a la institución
 * (`institucion_id`/`institucion_nombre`, pobladas en la lectura global del
 * Superadmin y `null` solo si la atribución no puede resolverse). No se expone
 * ningún saldo departamental legado.
 */
export interface AlertaStock {
  sede_id: number;
  sede_nombre: string;
  producto_id: number;
  producto_nombre: string;
  stock_actual: number;
  stock_minimo: number;
  institucion_id: string | null;
  institucion_nombre: string | null;
}

/**
 * Fila de la actividad reciente (Features 009 y 011, D-5/D-6).
 *
 * Refleja 1:1 el `MovimientoDashboardRespuesta` del backend: una proyección única
 * y compatible de las dos poblaciones de movimientos. Un movimiento **nuevo**
 * (Feature 011) puebla `sede_id`/`sede_nombre` y deja el bloque de departamento
 * en `null`; un movimiento **legado** puebla `departamento_id`/`departamento_nombre`
 * y `ubicacion`. `fecha_movimiento` llega como cadena ISO (el backend serializa
 * `datetime` a JSON), igual que `Ticket.fecha_creacion`.
 */
export interface MovimientoDashboard {
  movimiento_id: number;
  tipo_movimiento: string;
  cantidad: number;
  fecha_movimiento: string;
  producto_id: number;
  producto_nombre: string;
  sede_id: number | null;
  sede_nombre: string | null;
  departamento_id: number | null;
  departamento_nombre: string | null;
  ubicacion: string | null;
  institucion_id: string | null;
  institucion_nombre: string | null;
}

/**
 * Respuesta consolidada de `GET /api/v1/dashboard/` (Feature 009).
 *
 * Refleja 1:1 el `DashboardAnaliticoRespuesta` del backend. `actividad_disponible`
 * es `false` con lista vacía para el Solicitante (su permiso sobre el historial
 * de movimientos sigue denegado); para los demás roles es `true` aun con lista
 * vacía. Es un valor de presentación y no autoriza por sí mismo.
 */
export interface DashboardAnalitico {
  kpi: DashboardKpi;
  alertas: AlertaStock[];
  actividad_disponible: boolean;
  actividad_movimientos: MovimientoDashboard[];
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

// --- Control (Feature 010) ---

/**
 * Entrada de `POST /api/v1/control/instituciones/` (Feature 010, D-7).
 *
 * Refleja 1:1 el `InstitucionAltaControlCrear` de `backend/app/schemas/control_schema.py`.
 * El cliente **nunca** envía el nombre de esquema, la versión, el rol ni el estado:
 * los deriva y valida el servidor (`extra="forbid"`). `rut` y `direccion` son
 * opcionales y viajan como `null` cuando no se informan.
 */
export interface InstitucionAltaControlCrear {
  institucion_id: string;
  nombre: string;
  rut: string | null;
  direccion: string | null;
  correo_administrador: string;
  nombre_administrador: string;
  apellido_administrador: string;
  departamento_nombre_administrativo: string;
}

/**
 * Respuesta de `POST /api/v1/control/instituciones/` (201).
 *
 * Refleja 1:1 el `InstitucionAltaControlRespuesta`: el tenant quedó registrado y
 * operativo. `nombre_esquema` es el nombre determinista derivado en servidor y
 * `version_esquema` la versión objetivo con la que quedó marcado.
 */
export interface InstitucionAltaControlRespuesta {
  institucion_id: string;
  nombre: string;
  correo_administrador: string;
  nombre_esquema: string;
  version_esquema: string;
  estado: string;
  mensaje: string;
}