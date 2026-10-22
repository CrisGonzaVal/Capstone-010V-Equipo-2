# Feature 019 — Plan técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario. Este plan concreta su implementación sin ampliar el alcance. No se añaden dependencias ni se modifica el modelo de datos.

## 1. Decisiones técnicas

### 1.1 Backend por capas

1. **DTO de lectura.** Añadir `ProductoDetalleRespuesta` a `backend/app/schemas/inventario_schema.py` con exactamente los campos del §8 de la spec: `producto_id`, `nombre`, `descripcion`, `unidad_medida`, `stock_minimo`, `categoria_id`, `categoria_nombre`, `categoria_activa`, `activo`, `institucion_id`, `stock_total`, `es_critico` y `sedes: List[SedeExistenciaRespuesta]`. Es un read model agregado: no usar `from_attributes`; construirlo desde mappings explícitos como `ProductoExistenciaRespuesta`.
2. **Servicio.** Añadir `obtener_detalle_producto(db, producto_id, identidad)` a `backend/app/services/inventario_service.py`. Resolver primero `alcance_institucional`; luego `sede_del_alcance_por_rol` para imponer 409 operativo antes de examinar el producto; luego consultar producto/categoría y stock con `select()`/joins explícitos y `.mappings()`. Reutilizar `_es_producto_critico`, `SedeExistenciaRespuesta` y el patrón de `listar_existencias`. El Administrador incluye activos e inactivos y no filtra `Sede.activo`; los roles operativos exigen producto y categoría activos. Consultar exclusivamente `stock_sede`, devolver producto visible aunque no tenga filas dentro del ámbito, y ordenar sedes por `(sede_nombre, sede_id)` ascendente.
3. **Endpoint.** Publicar `GET /api/v1/inventario/existencias/{producto_id}` en `backend/app/api/v1/endpoints/inventario.py`, con `response_model=ProductoDetalleRespuesta`, `status_code=200`, descripción de alcance y errores, `Depends(requiere_operacion(...))` + `Depends(requiere_capacidad(...))`, y composición de `respuestas_de_autorizacion()`, `respuesta_recurso_oculto()` y `respuesta_conflicto()`. La ruta delega toda resolución y regla de negocio al servicio. Códigos 401/403 de matriz/capacidad/institución preceden a 409 de sede no resoluble; 404 de producto inexistente/ajeno/retirado solo después de esa resolución; 422 por coerción de path de FastAPI.
4. **Permiso y gating aditivos.** Añadir únicamente `("GET", "/api/v1/inventario/existencias/{producto_id}"): _LECTURA_NEGOCIO` a `MATRIZ_PERMISOS`; añadir la misma clave a `MAPA_OPERACION_CAPACIDAD` con valor `inventario`. No ampliar roles ni modificar otra asociación. La cardinalidad sube de 61 a 62.

### 1.2 Frontend

1. **Tipo y cliente HTTP.** Agregar `ProductoDetalle` en `frontend/src/app/shared/interfaces/index.ts`, espejo del DTO y con `sedes: SedeExistencia[]`. `InventarioService.obtenerDetalleProducto(productoId)` ejecuta el GET nuevo.
2. **Ruta.** En `inventario.routes.ts`, conservar la ruta raíz y agregar la hija `:productoId`, cargada como `ProductoDetalleComponent` y con título de detalle; espejo de `tickets.routes.ts` con `:ticketId`. La protección de área existente permanece intacta.
3. **Vista de detalle.** Crear `producto-detalle.component.ts`, `.html` y `.spec.ts`. El componente standalone usa `ActivatedRoute.paramMap`, `RouterLink`, signals, `ChangeDetectionStrategy.OnPush`, y el servicio tipado. Un parámetro que no sea entero positivo muestra error controlado sin petición. Carga/errores 403, 404, 409, red/servidor y parámetro inválido se presentan diferenciadamente con `role="alert"` cuando son errores, y reintento solo cuando corresponde; HTTP 422 queda mapeado como identificador no válido. Un 200 con `sedes: []` muestra vacío legible, total cero y criticidad del DTO, distinto del error. Los estados de producto/categoría inactivos se hacen explícitos y no hay controles de escritura. La plantilla usa solo Tailwind, sin `styles: []`.
4. **Retorno contextual.** Elegir `?tab=gestion` para representar el origen únicamente cuando el Administrador abre el detalle desde Gestión; el enlace de Existencias navega sin ese parámetro. El detalle usa `RouterLink` a `/inventario` o `/inventario?tab=gestion`. Al inicializar `InventarioComponent`, leer el query param y, solo si `gestionVisible()` es verdadero y `tab === 'gestion'`, seleccionar Gestión antes de renderizar; la carga de gestión que ya condiciona `ngOnInit` a `gestionVisible()` se conserva. Esta opción es explícita, serializable y sobrevive recarga/enlace compartido, a diferencia de `NavigationExtras.state`, que se pierde al recargar o abrir URL directamente; no guardar la pestaña en almacenamiento global, que puede dejar estado obsoleto entre navegaciones.
5. **Entradas.** Importar `RouterLink` en `InventarioComponent`; convertir el nombre del producto en enlace a `:productoId` en Existencias y en Gestión. El enlace de Gestión lleva `?tab=gestion`; el enlace operativo no. Mantener acciones y disponibilidad actual de las pestañas/capacidad: la UI solo construye navegación, la API sigue siendo la frontera.

### 1.3 Pruebas y cardinalidad

- **Fixture API:** reutilizar `mundo` de `test_filtros_inventario_018.py`, `dos_instituciones` de conftest y `cliente_de_rol`/`sembrar_contexto_capacidades` de `_soporte_ciclo_vida_catalogo_014.py`, además de `cliente`, `sesion` y `SIN_AUTENTICAR` de `_soporte_sede_011.py`. No mover fixtures a un soporte compartido: el mundo 018 ya tiene múltiples sedes, sede inactiva, dos instituciones, departamentos asociados, stock y producto sin saldo; moverlo ampliaría el cambio a la 018 y sus consumidores. Exponer su fixture al test nuevo con importación explícita desde el módulo 018 en `test_detalle_producto_019.py`, o extraer solo tras confirmar que pytest no duplica/renombra fixtures; la opción base del plan es importarlo explícitamente para evitar tocar fixtures heredados. Aprovechar `cliente_de_rol` para las tres identidades persistidas y `cliente` para sesión ausente/usuario operativo sin sede, según los datos del mundo.
- **Backend TDD SQLite.** En `backend/tests/api/test_detalle_producto_019.py`, fijar primero la respuesta exacta, campos, suma, criticidad, orden y sedes inactivas; los roles/ámbitos; visibilidad activa/inactiva; vacíos; filtros de lista ignorados; secuencia 401/403 matriz/capacidad/institución/409/404; ceros/negativos, path no entero (422); gating de inventario con catalogo en ambos estados; ausencia de mutaciones. Fijar una expectativa independiente de operación/rol/capacidad y OpenAPI. Ampliar las dos aserciones absolutas de 61 a 62 en `test_ciclo_vida_autorizacion_014.py` y `test_filtros_inventario_018.py`, conservando sus baselines históricos y documentando que la 019 agrega una lectura. Mantener transcripciones históricas de permisos sin alterar.
- **PostgreSQL 16 gated.** AC-13 requiere una prueba tenant A/B que confirme que la consulta del detalle no incluye catálogo ni stock del otro esquema; crear tenants/bases temporales con guardia de desechabilidad y `$env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"`. Nunca usar `apt_erp` como base desechable.
- **Frontend TDD.** Pruebas de `InventarioService` donde corresponda, detalle (paramMap válido/inválido, contrato HTTP, estados, reintento, retorno por tab, estados inactivos y vacío) y componente de inventario (enlace en ambas listas, origen correcto y ausencia del enlace Gestión para roles que no la ven). Proveer `provideRouter([])` al spec de Inventario que importa `RouterLink`; verificar URL/link y navegación según el patrón de tests existente, no asumir que `router.url` cambia sin navegación configurada.
- **Comandos.** Backend `cd backend && pytest`; gated con la variable indicada. Frontend: configurar `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"` y ejecutar `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`; nunca `npm test`. Ejecutar `cd frontend && npx ng build` limpio. Verificar `/openapi.json` con 62 rutas de matriz y contrato coincidente.

### 1.4 Alternativas técnicas

- **Query `tab=gestion` (elegida):** permite restituir pestaña en navegación interna, recarga y deep link, y se puede probar con URL visible. **Descartado:** `NavigationExtras.state`, que no persiste al recargar/pegar la URL; estado global/local storage, que puede sobrevivir de forma indebida a una navegación posterior.
- **Reusar lectura/listado de existencias (descartado):** no contiene descripción, unidad/estado de categoría ni permite ver producto inactivo como Administrador; además sus filtros no representan el alcance completo del detalle. Se añade un GET dedicado, sin alterar endpoints existentes.
- **Reusar `stock_sede` con proyección única (elegida):** una consulta de lectura con join conserva producto sin filas mediante outer join y permite derivar total/criticidad solo de sedes devueltas. **Descartado:** leer `inventario` legado o consultar endpoint por sede en N+1, que rompe la fuente única vigente o genera consultas variables y complicadas de aislar.
- **Fixture `mundo` existente (elegida):** suficiente para tres perfiles de rol, dos instituciones, filas de stock en sedes activas/inactivas y producto sin filas. **Descartado:** duplicar escenario equivalente o refactorizar soporte compartido: aumenta superficie y riesgo de regresión sin aumentar cobertura.

## 2. Archivos a crear o modificar

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/inventario_schema.py` | Read model `ProductoDetalleRespuesta` con campos exactos y sedes reutilizadas. | AC-1, AC-6, AC-7, AC-11 |
| `backend/app/services/inventario_service.py` | Consulta por producto, resolución de tenant/sede, visibilidad por rol, agregado, criticidad y orden, usando `stock_sede`. | AC-1…AC-7, AC-9, AC-12 |
| `backend/app/api/v1/endpoints/inventario.py` | GET dedicado, response/status/OpenAPI, autorización, gating y errores documentados. | AC-4, AC-5, AC-10…AC-12 |
| `backend/app/core/permisos.py` | Una operación aditiva `_LECTURA_NEGOCIO`, total de matriz 62. | AC-4, AC-11 |
| `backend/app/core/capacidades.py` | Asociación de la lectura nueva a `inventario`; sin nueva capacidad. | AC-10, AC-11 |
| `backend/tests/api/test_detalle_producto_019.py` | Contrato HTTP, roles/alcance, estados, precedencia, gating, agregado y OpenAPI; usa mundo 018 reutilizado. | AC-1…AC-12 |
| `backend/tests/api/test_ciclo_vida_autorizacion_014.py` | Ampliar explícitamente aserciones absolutas de matriz/OpenAPI 61→62 por Feature 019. | AC-11 |
| `backend/tests/api/test_filtros_inventario_018.py` | Ampliar explícitamente cardinalidad absoluta de matriz/OpenAPI 61→62 por Feature 019. | AC-11 |
| Nuevo módulo de pruebas gated bajo `backend/tests/` para Feature 019 | Aislamiento del detalle entre tenants reales PostgreSQL 16. | AC-2, AC-13 |
| `frontend/src/app/shared/interfaces/index.ts` | Interface `ProductoDetalle` con contrato exacto. | AC-1, AC-6, AC-7 |
| `frontend/src/app/features/inventario/services/inventario.service.ts` | Método GET `obtenerDetalleProducto`. | AC-1, AC-10, AC-13 |
| `frontend/src/app/features/inventario/inventario.routes.ts` | Ruta hija `:productoId` y título de detalle. | AC-8, AC-13 |
| `frontend/src/app/features/inventario/producto-detalle.component.ts` | Lectura del id/ruta, petición, estado, error, reintento y retorno contextual. | AC-1, AC-9, AC-10, AC-13 |
| `frontend/src/app/features/inventario/producto-detalle.component.html` | Presentación accesible de detalle, empty state y enlace de retorno; solo Tailwind. | AC-1, AC-6, AC-9, AC-10 |
| `frontend/src/app/features/inventario/producto-detalle.component.spec.ts` | Tests servicio/render/param inválido/errores/reintento/retorno/estado inactivo y vacío. | AC-1, AC-3, AC-6, AC-8…AC-10, AC-13 |
| `frontend/src/app/features/inventario/inventario.component.ts` | Importar RouterLink y restaurar Gestión desde query param solo para Administrador. | AC-8, AC-9 |
| `frontend/src/app/features/inventario/inventario.component.html` | Enlace del nombre en ambas listas, con tab de origen apropiado. | AC-8, AC-9 |
| `frontend/src/app/features/inventario/inventario.component.spec.ts` | `provideRouter([])` y tests de links/origen/visibilidad por rol. | AC-8, AC-9, AC-13 |
| `docs/spec/stack.md` | Al cierre, registrar contrato nuevo, rol y capacidad `inventario`, coexistencia con GET de `catalogo`, matriz 61→62 y ausencia de cambios de DDL. | AC-10…AC-12, cierre |
| `docs/spec/roadmap.md` | Al cierre, enlazar y reflejar estado de Feature 019. | cierre |
| `docs/spec/features/019-detalle-producto-por-alcance/spec.md` | En fase de cierre, incorporar evidencia verificable por AC §7 y estado correspondiente; no editar durante implementación sin cambio aprobado. | AC-1…AC-13, cierre |
| `MEMORY.md` | Al cierre, estado y decisiones/evidencia de la Feature 019, dentro del límite del archivo. | cierre |
| `AGENTS.md`, `.agents/skills/` | Solo inspección de coherencia de rutas/afirmaciones; no se esperan cambios si no hay referencias obsoletas. | cierre |

## 3. Orden de implementación TDD

1. **Backend rojo:** escribir la suite de contrato en `test_detalle_producto_019.py` y la expectativa aditiva de matriz/capacidad/OpenAPI. Casos por fase: exactitud DTO y éxito; roles y alcance; visibilidad/casos límite; precedencia/gating; aserciones de cardinalidad. Deben fallar por la ruta/operación ausente, no por imports ni setup.
2. **Matriz/gating:** registrar solo la nueva clave en permisos y capacidades; adaptar los asserts absolutos 014 y 018 con comentario explícito 61→62. Los tests de endpoint/contrato permanecen rojos hasta publicar la ruta.
3. **DTO y servicio:** añadir read model y `obtener_detalle_producto`; ejecutar el módulo API con servicio ejercido por `TestClient`. Implementar resolución de institución y sede antes del lookup de producto. Aplicar pertenencia/producto activo/categoría activa según rol; proyecto de stock con predicados institucional y por sede, sin `Sede.activo`; construir `sedes`, total y criticidad en el conjunto visible.
4. **Endpoint:** conectar DTO y servicio; declarar dependencias en el orden central, documentar 200/401/403/404/409/422 y comprobar exclusión de Superadmin, capacidad y precedencia. SQLite backend debe quedar verde y OpenAPI/matriz exactamente en 62.
5. **Gated PostgreSQL:** escribir primero test de aislamiento con tenant A/B y luego implementarlo con esquemas/base desechables; probar respuesta de A no contiene producto, stock ni sede de B. Ejecutar la suite gated con `POSTGRES_TEST_URL`.
6. **Frontend rojo:** tipos y contrato HTTP testeados; iniciar `producto-detalle.component.spec.ts` y ampliar el spec inventario para rutas/enlaces/retorno, con fixtures de respuesta acordes al §8. Deben fallar por superficies ausentes sin romper compilación por imports nominales prematuros.
7. **Frontend verde:** interface y método, componente + template, ruta, después integración de `RouterLink` en inventario. Resolver y probar `?tab=gestion`; asegurar que Gestión no se solicita para roles operativos y que query param no concede visibilidad ni cambia autorización.
8. **Verificación integrada:** pytest SQLite, gated PG16, Angular tests, `ng build`, inspección real de `/openapi.json`, recorrido funcional 4200 y humo 8080 tras reconstrucción. Capturar evidencia y cerrar documentación según §5 de tareas.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Buscar producto antes de resolver sede revela existencia a actor operativo sin asignación | Servicio resuelve `alcance_institucional` y `sede_del_alcance_por_rol` antes de consultar el producto; tests usan id inexistente y 409 simultáneamente. |
| Mezcla accidental de saldos institucionales/tenant o sedes fuera de rol | Predicados de institución/sede en consulta; SQLite con sedes múltiples y gated PG16 con dos tenants. |
| Excluir sedes inactivas por reuso literal de opciones de filtro 018 | No reutilizar `obtener_ambito_inventario`; el detalle no filtra `Sede.activo`; test verifica sede inactiva, saldo y criticidad incluidos. |
| Lectura operativa aplica filtro de producto/categoría activos al Administrador | Separar selección administrativa de operativa: Admin permite inactivos; Bodeguero/Solicitante requieren ambos activos; comparar 404 indistinguible para operativo. |
| Criticidad calculada sobre saldo fuera de ámbito o total agregado | Reutilizar `_es_producto_critico` con solo `sedes` devueltas, incluyendo vacío evaluado a cero; probar cambios de alcance. |
| Retorno de Gestión pierde contexto al actualizar o pegar URL | Llevar origen en `?tab=gestion`; probar recarga/deep link y guard `gestionVisible()` impide activar Gestión en otro rol. |
| `RouterLink` cambia imports del componente/spec existente | Proveer `provideRouter([])` en TestBed y probar destino/param; ejecutar suite frontend completa. |
| Aserciones absolutas de operaciones quedan en 61 | Expandir y comentar las dos aserciones indicadas; comprobar igualdad exacta OpenAPI↔matriz a 62. |
| Contrato nuevo deriva hacia la operación existente de detalle de producto | Mantener paths/capacidades distintos: producto solo bajo `catalogo`; detalle de producto más stock bajo `inventario`; verificar OpenAPI y gating independiente. |
| 8080 muestra build anterior | Reconstruir imagen frontend antes del humo, conforme AGENTS.md §5/§8.6. |

## 5. Alcance no tocado

- No se cambia `spec.md` durante la implementación ordinaria, ni se crean movimientos, historial, endpoint de escritura, DDL, entidades, semillas o versión de esquema; `014.1` y 22/19 tablas permanecen.
- No se modifica el contrato existente `GET /inventario/productos/{producto_id}`, la lista `/inventario/existencias`, sus filtros, las capacidades existentes ni la semántica de saldo por departamento.
- No se añaden rutas de dashboard/tickets ni acceso de negocio a Superadmin. No se añade dependencia ni se altera Clerk.
- El cierre sí documenta el reparto de capacidad/rol y evidencia en `stack.md`, `roadmap.md`, `spec.md` §7 y `MEMORY.md`; las suites y recorridos no autorizan escritura de negocio fuera de datos QA autorizados.
