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
  /**
   * Estado vigente del catálogo (Feature 014, AC-15). El listado operativo de
   * `GET /inventario/categorias` solo devuelve activas, pero la transición de
   * estado responde con el recurso completo y este campo persistido.
   */
  activo: boolean;
}

export interface Producto {
  producto_id: number;
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
  /** Estado vigente (Feature 014, AC-13/AC-15), igual que en `Categoria`. */
  activo: boolean;
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

/**
 * Opción de sede de `GET /inventario/ambito` (`SedeFiltroRespuesta`, Feature
 * 018, AC-4).
 *
 * Contrato mínimo del selector: id y nombre, sin institución, estado ni saldo.
 * La lectura solo devuelve sedes activas del alcance del actor.
 */
export interface SedeFiltro {
  sede_id: number;
  sede_nombre: string;
}

/**
 * Opción de departamento de `GET /inventario/ambito`
 * (`DepartamentoFiltroRespuesta`, Feature 018, AC-4).
 *
 * `sede_id` es la asociación obligatoria que permite acotar los departamentos a
 * la sede elegida sin consultar `/organizacion/departamentos` (el Bodeguero
 * recibiría 403). Un departamento sin sede no es opción, por eso no es nulo.
 */
export interface DepartamentoFiltro {
  departamento_id: number;
  departamento_nombre: string;
  sede_id: number;
}

/**
 * Read model de `GET /inventario/ambito` (`AmbitoInventarioRespuesta`, Feature
 * 018, D-6/AC-4).
 *
 * Ambas colecciones llegan siempre, aunque estén vacías: un Bodeguero con sede
 * inactiva recibe listas vacías y uno sin sede recibe 409 desde el servidor,
 * nunca un ámbito sustituto. No incluye usuarios, tickets, productos ni stock.
 */
export interface AmbitoInventario {
  sedes: SedeFiltro[];
  departamentos: DepartamentoFiltro[];
}

/**
 * Filtros organizacionales opcionales de `GET /inventario/existencias`
 * (Feature 018, AC-3/AC-5).
 *
 * Solo `sede_id` y `departamento_id` viajan al servidor: el texto, la categoría
 * y los críticos siguen resolviéndose en cliente sobre el conjunto ya cargado.
 * Un valor `null`/`undefined` no agrega el parámetro de query.
 */
export interface FiltrosExistencias {
  sede_id?: number | null;
  departamento_id?: number | null;
}

// --- Ciclo de vida del catálogo (Feature 014) ---

/**
 * Payload de `PATCH /inventario/productos/{id}/estado` y `.../categorias/{id}/estado`
 * (`TransicionCatalogo` del backend, T6).
 *
 * El servidor valida el motivo (no vacío, no solo espacios, ≤ 500) en el
 * servicio, no en el schema, para respetar el orden 404 → idempotencia → 422.
 * Un `motivo` ausente solo es válido cuando el destino ya es el estado
 * persistido (repetición idempotente, 200 sin historial).
 */
export interface TransicionCatalogo {
  activo: boolean;
  motivo?: string | null;
}

/**
 * Fila de categoría de `GET /inventario/gestion` (`CategoriaGestionRespuesta`).
 *
 * El listado de gestión devuelve **ambos** estados, a diferencia del listado
 * operativo, que sigue filtrado para todos los roles (AC-15).
 */
export interface CategoriaGestion {
  categoria_id: number;
  nombre_cat: string;
  descripcion_cat: string | null;
  institucion_id?: string | null;
  activo: boolean;
}

/**
 * Fila de producto de `GET /inventario/gestion` (`ProductoGestionRespuesta`).
 *
 * `categoria_nombre` y `categoria_activa` llegan resueltos porque el estado de
 * la categoría condiciona qué acciones son viables: un producto no puede
 * reactivarse bajo una categoría inactiva (AC-5).
 */
export interface ProductoGestion {
  producto_id: number;
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
  categoria_nombre: string;
  categoria_activa: boolean;
  institucion_id?: string | null;
  activo: boolean;
}

/** Read model de `GET /inventario/gestion` (`GestionCatalogoRespuesta`). */
export interface GestionCatalogo {
  productos: ProductoGestion[];
  categorias: CategoriaGestion[];
}

/**
 * Fila de `GET /inventario/productos/{id}/historial`
 * (`HistorialTransicionProductoRespuesta`).
 *
 * Solo lectura e inmutable. `usuario_nombre`/`usuario_apellido` son los campos
 * de presentación que resuelve el servicio; la vista degrada si faltan.
 */
export interface HistorialTransicionProducto {
  historial_producto_id: number;
  producto_id: number;
  usuario_id: number;
  fecha_transicion: string;
  activo_origen: boolean;
  activo_destino: boolean;
  motivo: string;
  usuario_nombre?: string | null;
  usuario_apellido?: string | null;
}

/** Fila de `GET /inventario/categorias/{id}/historial` (hermana de la de producto). */
export interface HistorialTransicionCategoria {
  historial_categoria_id: number;
  categoria_id: number;
  usuario_id: number;
  fecha_transicion: string;
  activo_origen: boolean;
  activo_destino: boolean;
  motivo: string;
  usuario_nombre?: string | null;
  usuario_apellido?: string | null;
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
  /**
   * Estado del producto (Feature 014, AC-4/AC-9).
   *
   * `GET /tickets/catalogos` ya excluye en servidor los productos inactivos y
   * los de categoría inactiva, así que hoy este campo no viaja. Se declara
   * opcional como salvaguarda: si una regresión lo enviara con `false`, la UI
   * no debe ofrecerlo para líneas nuevas. Ausente equivale a disponible.
   */
  activo?: boolean;
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

// --- Ciclo de vida del ticket (Feature 013) ---

/**
 * Payload de anulación y rechazo (`TicketMotivo` del backend, T8).
 *
 * El backend valida el motivo en el servicio (no vacío, ≤ 500) y responde 422;
 * aquí viaja como texto crudo para que ese 422 sea observable por API.
 */
export interface TicketMotivo {
  motivo: string;
}

/**
 * Fila del historial de transiciones (`GET /tickets/{id}/historial`).
 *
 * Los siete primeros campos son el contrato congelado de
 * `backend/tests/api/_soporte_ciclo_vida_013.py` (`CAMPOS_HISTORIAL`): ids, no
 * textos. Los campos `*_nombre` son los de presentación que
 * `HistorialTransicionRespuesta` (T9) debe poblar para que la vista pueda
 * mostrar el historial completo (AC-23: actor, de→a) sin cruzar catálogos ni
 * resolver usuarios; son opcionales y la vista degrada si faltan.
 */
export interface HistorialTransicion {
  historial_transicion_id: number;
  ticket_id: number;
  /** `null` solo en la fila de creación (AC-9). */
  estado_origen_id: number | null;
  estado_destino_id: number;
  usuario_id: number;
  fecha_transicion: string;
  motivo: string | null;
  estado_origen_nombre?: string | null;
  estado_destino_nombre?: string | null;
  usuario_nombre?: string | null;
  usuario_apellido?: string | null;
}

/**
 * Detalle completo del ticket (`GET /tickets/{id}`, spec §6).
 *
 * Refleja el `TicketDetalleRespuesta` previsto por el plan §4 (T9): la
 * cabecera del `TicketRespuesta` vigente más los campos resueltos que la vista
 * necesita para AC-23 (estado, prioridad, solicitante con departamento y
 * sede). Los resueltos son opcionales porque el schema del backend se define
 * en T9; la vista degrada a los catálogos y a etiquetas `#id` si faltan.
 */
export interface TicketDetalle {
  ticket_id: number;
  usuario_id: number;
  prioridad_id: number;
  estado_id: number;
  asunto: string;
  descripcion: string | null;
  fecha_creacion: string;
  fecha_cierre: string | null;
  sede_id: number | null;
  detalles: DetalleTicket[];
  estado_nombre?: string | null;
  prioridad_nombre?: string | null;
  solicitante_nombre?: string | null;
  solicitante_apellido?: string | null;
  solicitante_correo?: string | null;
  departamento_nombre?: string | null;
  sede_nombre?: string | null;
}

/**
 * Payload de `PUT /tickets/{ticket_id}` (`TicketEditar`, T8): edición del
 * ticket en `Pendiente` con el **conjunto completo** de ítems (reemplazo
 * atómico, D-9). No viajan estado, solicitante, sede ni institución: no son
 * editables.
 */
export interface TicketEditar {
  asunto: string;
  descripcion: string | null;
  prioridad_id: number;
  detalles: DetalleTicketCrear[];
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
  /**
   * Sede del usuario cuando es Bodeguero (Feature 011/012). El listado
   * `GET /usuarios/` la publica siempre (`null` = sin asignación vigente); se
   * actualiza localmente tras `PUT /organizacion/usuarios/{id}/sede`.
   */
  sede_id?: number | null;
  /**
   * Estado del vínculo local usuario-esquema (Feature 012,
   * `mapa_usuario_esquema.activo`). El listado `GET /usuarios/` lo publica
   * siempre (activo/inactivo); puede faltar (`null`) en la respuesta de
   * alta/edición, donde el mapa de control no se consulta.
   */
  activo?: boolean | null;
  /**
   * Proyección persistida del ciclo de invitación (Feature 017, D-3/AC-5).
   * Es un concepto **separado** del vínculo local `activo`: los estados son
   * `pendiente`, `aceptada`, `revocada`, `expirada` y `no disponible` para
   * legados. Nunca contiene la URL de la invitación.
   */
  estado_invitacion?: string | null;
}

/** Códigos cerrados del catálogo de motivos de mutación (Feature 017, D-5). */
export type MotivoCodigo =
  | 'cambio_funciones'
  | 'reasignacion_organizacional'
  | 'correccion_datos'
  | 'termino_vinculo'
  | 'seguridad_acceso'
  | 'otro';

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
  /**
   * URL de la invitación del primer Administrador (Feature 017, D-1/D-4).
   * Solo llega en esta respuesta y nunca se persiste; `null` cuando el correo ya
   * existía en Clerk.
   */
  url_invitacion?: string | null;
}

// --- Control / gestión SaaS (Feature 012) ---

/**
 * Lectura administrativa del registro institucional canónico (Feature 012, AC-1).
 *
 * Refleja 1:1 el `InstitucionControlRespuesta` de `backend/app/schemas/control_schema.py`:
 * publica el estado de ciclo de vida persistido (`activo`) y el `nombre_esquema`
 * derivado en servidor (informativo). `rut` y `direccion` permanecen solo en
 * control y admiten `null`.
 */
export interface InstitucionControl {
  institucion_id: string;
  nombre: string;
  rut: string | null;
  direccion: string | null;
  activo: boolean;
  nombre_esquema: string | null;
}

/**
 * Entrada de `PUT /api/v1/control/instituciones/{id}` (Feature 012, AC-1).
 *
 * Refleja 1:1 el `InstitucionEdicion`: solo atributos canónicos. El cliente
 * **nunca** envía `activo`, esquema ni versión (`extra="forbid"`).
 */
export interface InstitucionEdicion {
  nombre: string;
  rut: string | null;
  direccion: string | null;
}

/** Entrada de `PATCH /api/v1/control/instituciones/{id}/estado` (AC-2). */
export interface InstitucionEstado {
  activo: boolean;
}

/** Respuesta del cambio de estado institucional: el estado persistido (AC-2). */
export interface InstitucionEstadoRespuesta {
  institucion_id: string;
  activo: boolean;
}

/**
 * Los seis identificadores cerrados de capacidad funcional por institución
 * (Feature 012, D-6/AC-5). Es un conjunto estable; no se infiere de roles ni datos.
 */
export type CapacidadFuncional =
  | 'catalogo'
  | 'inventario'
  | 'tickets'
  | 'kanban'
  | 'dashboard'
  | 'gestion_organizacional';

/** Estado persistido de una capacidad funcional de una institución (AC-5). */
export interface CapacidadRespuesta {
  funcion: string;
  habilitada: boolean;
}

/** Entrada del cambio de una capacidad funcional (`extra="forbid"`). */
export interface CapacidadActualizar {
  habilitada: boolean;
}

/**
 * Métricas atribuidas a una institución en el dashboard SaaS (Feature 012,
 * D-5/AC-4; ampliadas por Feature 017, D-8/AC-13/AC-14).
 *
 * `estado_tecnico` es la clase única de la taxonomía: `operativo`,
 * `no enrutable` o `no disponible`. Los conteos del tenant solo son fiables en
 * la clase operativa; en las otras quedan en `null` (nunca en cero). La vista
 * distingue explícitamente lo conocido de lo no disponible.
 */
export interface InstitucionMetricas {
  institucion_id: string;
  nombre: string;
  activo: boolean;
  estado_tecnico: string;
  detalle_tecnico: string | null;
  version_objetivo: string;
  version_persistida: string | null;
  sedes: number | null;
  departamentos: number | null;
  administradores_activos: number | null;
  administradores_inactivos: number | null;
  usuarios_por_rol: Record<string, number> | null;
}

/**
 * Panorama global del Superadmin (Feature 017, D-8/AC-13).
 *
 * Los agregados suman solo instituciones operativas y separan las cantidades
 * conocidas de las no disponibles: `conteos_conocidos + conteos_no_disponibles`
 * es el total de instituciones. No contiene datos personales ni de negocio.
 */
export interface DashboardSaaS {
  total_instituciones: number;
  total_instituciones_activas: number;
  total_administradores_activos: number;
  total_administradores_inactivos: number;
  usuarios_por_rol: Record<string, number>;
  conteos_conocidos: number;
  conteos_no_disponibles: number;
  instituciones: InstitucionMetricas[];
}

// --- Gobierno de Administradores por institución (Feature 017, D-10/AC-5) ---

/**
 * Fila del listado mínimo de Administradores de una institución.
 *
 * Refleja 1:1 `AdministradorListadoControlRespuesta`: solo los campos
 * acordados, con `estado_invitacion` proyectado por el servidor. **Nunca**
 * contiene la URL de la invitación ni consulta Clerk.
 */
export interface AdministradorListadoControl {
  usuario_id: number;
  nombre: string;
  apellido: string;
  correo: string;
  activo: boolean;
  estado_invitacion: string;
}

// --- Administración institucional (Feature 012, AC-6…AC-12) ---

/**
 * Sede del tenant (Features 011 y 012).
 *
 * Refleja 1:1 el `SedeRespuesta` de `backend/app/schemas/organizacion_schema.py`:
 * `activo` es el estado lógico persistido (AC-6/AC-11) y `institucion_id` es el
 * tenant resuelto por el servidor desde la sesión, nunca enviado por el cliente.
 */
export interface Sede {
  sede_id: number;
  nombre: string;
  direccion: string | null;
  institucion_id: string;
  activo: boolean;
}

/** Entrada de `POST /organizacion/sedes` (el tenant lo resuelve el servidor). */
export interface SedeCrear {
  nombre: string;
  direccion: string | null;
}

/** Entrada de `PUT /organizacion/sedes/{id}`. */
export interface SedeEdicion {
  nombre: string;
  direccion: string | null;
}

/** Entrada de `PATCH /organizacion/sedes/{id}/estado`. */
export interface SedeEstado {
  activo: boolean;
}

/** Respuesta del cambio de estado de sede: estado persistido. */
export interface SedeEstadoRespuesta {
  sede_id: number;
  activo: boolean;
}

/** Entrada de asignación de sede: solo el id de la sede del tenant. */
export interface AsignacionSedeCrear {
  sede_id: number;
}

/** Respuesta de `PUT /organizacion/departamentos/{id}/sede`. */
export interface AsignacionSedeDepartamentoRespuesta {
  departamento_id: number;
  sede_id: number;
}

/** Respuesta de `PUT /organizacion/usuarios/{id}/sede` (Bodeguero). */
export interface AsignacionSedeUsuarioRespuesta {
  usuario_id: number;
  sede_id: number;
}

/**
 * Departamento del tenant con su sede y estado (Features 011 y 012).
 *
 * Refleja 1:1 el `DepartamentoRespuesta` del backend: `sede_id` es `null` cuando
 * no hay asignación (la vista muestra la ausencia) y `activo` es el estado lógico
 * (AC-7/AC-11).
 */
export interface DepartamentoGestion {
  departamento_id: number;
  nombre_dep: string;
  descripcion: string | null;
  institucion_id: string;
  sede_id: number | null;
  activo: boolean;
}

/** Entrada de `POST /organizacion/departamentos` (sin sede obligatoria). */
export interface DepartamentoCrear {
  nombre_dep: string;
  descripcion: string | null;
}

/** Entrada de `PUT /organizacion/departamentos/{id}`. */
export interface DepartamentoEdicion {
  nombre_dep: string;
  descripcion: string | null;
}

/** Entrada de `PATCH /organizacion/departamentos/{id}/estado`. */
export interface DepartamentoEstado {
  activo: boolean;
}

/** Respuesta del cambio de estado de departamento: estado persistido. */
export interface DepartamentoEstadoRespuesta {
  departamento_id: number;
  activo: boolean;
}

/**
 * Encargado vigente y compatible de un departamento (Feature 011, spec D-4).
 *
 * Refleja 1:1 el `EncargadoRespuesta`: la asociación solo es visible si el
 * usuario existe, es Solicitante y pertenece al mismo departamento.
 */
export interface Encargado {
  usuario_id: number;
  departamento_id: number;
  nombre: string;
  apellido: string;
  correo: string;
}

/** Entrada de `POST /organizacion/departamentos/{id}/encargados`. */
export interface EncargadoCrear {
  usuario_id: number;
}

/** Entrada de `PUT /usuarios/{id}` (sin correo: clave de identidad local). */
export interface UsuarioEdicion {
  nombre: string;
  apellido: string;
  departamento_id: number;
  rol_id: number;
}

/**
 * Motivo obligatorio de las mutaciones del conjunto cerrado D-7 (Feature 017,
 * D-5). El catálogo es cerrado; `otro` exige texto y el texto admite hasta 500
 * caracteres. No viaja en listados.
 */
export interface MotivoMutacion {
  codigo: MotivoCodigo;
  texto: string | null;
}

/** Entrada de `PUT /usuarios/{id}` con motivo e idempotencia (Feature 017). */
export interface UsuarioEdicionConMotivo extends UsuarioEdicion {
  /** Obligatorio solo si la edición cambia efectivamente algún atributo. */
  motivo?: MotivoMutacion | null;
  /** Clave que permite completar el motivo en un reintento sin repetir el cambio. */
  idempotencia?: string | null;
}

/** Entrada de `PATCH /usuarios/{id}/estado` con motivo e idempotencia (017). */
export interface UsuarioEstadoConMotivo extends UsuarioEstado {
  /** Obligatorio solo si el estado cambia; una repetición es idempotente. */
  motivo?: MotivoMutacion | null;
  idempotencia?: string | null;
}

/**
 * Entrada de `POST /usuarios/` (Feature 012, AC-8): alta de usuario local.
 *
 * El cliente aporta solo el correo (que debe existir ya en Clerk) y el ámbito
 * del tenant; la institución y el esquema los resuelve el servidor. La sede del
 * Bodeguero no forma parte del alta: se asigna después con
 * `PUT /organizacion/usuarios/{id}/sede`.
 */
export interface UsuarioCrear {
  nombre: string;
  apellido: string;
  correo: string;
  departamento_id: number;
  rol_id: number;
}

/** Entrada de `PATCH /usuarios/{id}/estado` (estado en `mapa_usuario_esquema`). */
export interface UsuarioEstado {
  activo: boolean;
}

/**
 * Respuesta de `POST /usuarios/` y del reenvío de invitación (Feature 017, D-4).
 *
 * `url_invitacion` solo existe en la respuesta inmediata de alta/reenvío: no se
 * persiste ni aparece en listados. Puede ser `null` cuando Clerk ya tenía
 * identidad (alta `aceptada`) o cuando la operación no generó enlace.
 */
export interface UsuarioInvitacionRespuesta extends Usuario {
  url_invitacion: string | null;
}

/** Respuesta del cambio de estado local de usuario: estado persistido. */
export interface UsuarioEstadoRespuesta {
  usuario_id: number;
  activo: boolean;
}