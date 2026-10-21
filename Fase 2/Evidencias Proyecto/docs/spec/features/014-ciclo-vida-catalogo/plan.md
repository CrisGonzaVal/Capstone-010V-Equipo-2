# Feature 014 — Plan técnico

Spec: [`spec.md`](spec.md). La spec fue aprobada por el usuario; este plan concreta su implementación sin ampliar el alcance. No se añaden dependencias.

## Enmienda posterior al cierre: inventario en pestañas

La enmienda aprobada a AC-11 cambia solo la presentación de `frontend/src/app/features/inventario/inventario.component.ts` y `.html`: sustituir las secciones apiladas por un conmutador de dos pestañas, «Existencias» y «Gestión del catálogo». La pestaña por defecto es «Existencias». El conmutador y la pestaña de gestión se renderizan solo para Administrador; Bodeguero y Solicitante ven únicamente Existencias, sin pestaña vacía ni bloqueada. La gestión conserva sus categorías/productos, estados, motivo e historial; Existencias conserva la lista y filtros operativos actuales. El servicio `InventarioService`, listado de gestión, endpoints, autorización backend y reglas de negocio no cambian.

Para el estilo se reutiliza el patrón de navegación con Tailwind ya presente en `administracion-nav.component.html` y `control-nav.component.html` (barra, borde inferior, estado activo y foco visible), adaptándolo a pestañas dentro de una sola vista y declarando semántica accesible de tablist/tab/tabpanel. No se crea ruta ni vista nueva. Adaptar `inventario.component.spec.ts` para pestaña por defecto, cambio de pestañas, visibilidad por rol, gestión dentro de su pestaña y Existencias con filtros dentro de la otra; mantener el resto de aserciones, incluyendo motivo, idempotencia y errores. Verificar con `ng test`, `ng build`, recorrido 4200 y rebuild + humo 8080 según AGENTS.md §8.6.

## 1. Prerrequisito de modelo aprobado en `stack.md`

Se incorporó al final de §2 de `docs/spec/stack.md` el apartado «Ciclo de vida del catálogo: estados reversibles e historiales (Feature 014)». Ese apartado fija `producto.activo` y `categoria.activo`, las dos tablas tenant de historial con paridad en `control`, su clasificación como entidades de dominio 16.ª y 17.ª, la inmutabilidad/relaciones y la elevación de conteos 20/17 → 22/19 y versión `013.1` → `014.1`.

La spec aprobada fija también que la justificación formal debe incorporarse a `stack.md` en la fase de plan. Ese prerrequisito ya está incorporado; T1 solicita que el coordinator registre que la aprobación de la spec cubre el texto incorporado. No tocar modelos, schemas ni DDL hasta esa confirmación. No inferir aprobación por el solo hecho de que exista el texto.

## 2. Decisiones técnicas

1. **Dos historiales con FK concretas.** Añadir dos modelos al dominio, previsiblemente en el módulo de catálogo existente: historial de transición de producto con FK a `producto` y `usuario`, e historial de transición de categoría con FK a `categoria` y `usuario`. Cada tabla registra origen/destino booleano, instante y motivo de hasta 500 caracteres. Se exportan ambos modelos desde el paquete común para que metadata SQLite y DDL traducido los registren. Se descarta una tabla polimórfica con `recurso_tipo + recurso_id`: no ofrece FK verificable hacia ambos recursos y admite referencias colgantes.
2. **Estados en entidades vigentes.** Añadir `activo` a producto y categoría, booleano no nulo con default de aplicación y de servidor `TRUE`, alineado con sede/departamento. Los modelos se mantienen en el contexto lógico compartido; el DDL materializa columnas/tablas en control y tenants. La fila espejo `institucion` no cambia.
3. **Schemas v2 y motivo validado en servicio.** Schemas explícitos de recurso/gestión, payload de transición (`activo` destino y motivo como cadena sin validadores que adelanten 422), y respuestas separadas de los historiales. La validación no vacía/no espacios y ≤500 se ejecuta en servicio para respetar el orden 404 → idempotencia 200 → 422 → precondición 409. No se usa el catálogo de motivos de 017.
4. **Servicios de negocio, transacciones y atomicidad.** Lógica de transiciones y listado de gestión en `inventario_service.py` (o servicio específico solo si al implementador le resulta imprescindible; no duplicar reglas). Para toda mutación: resolver el recurso y tenant; comparar estado destino para idempotencia; validar motivo; tomar bloqueos de filas en orden determinista; revisar vigencia y precondiciones; asignar estado, insertar una única transición en su tabla e incrementar/confirmar en una sola transacción con rollback completo ante fallo.
   - Baja de producto: coordinar bloqueo de producto con la ruta que modifica stock por sede; bloquear/leer las filas `stock_sede` y exigir saldo cero en todas. La ruta de movimiento debe bloquear el producto antes del stock y comprobar que sigue activo. No se cuentan filas de `inventario` legado.
   - Baja de categoría / alta y reactivación de producto: bloquear categoría primero y comprobar su estado en la misma transacción que crear/reactivar producto; el flujo de baja categoría adquiere bloqueo de categoría y valida que no haya productos activos. Usar el mismo orden de bloqueo (categoría → producto → stock) en los caminos solapados para evitar deadlocks. Resultado concurrente: jamás persistir categoría inactiva con producto activo.
   - Repetición idempotente: tras existencia/pertenencia, responder 200 antes de motivo/precondiciones, sin escritura ni transición; no convierte en reactivación automática.
   **Alternativa descartada:** validar solo con lecturas sin bloqueo o confiar en bloqueo de `stock_sede` por sí solo: productos sin fila de saldo no ofrecen fila que bloquear, y se puede insertar saldo entre comprobación y cambio de vigencia.
5. **Edición de ticket: comparar detalles actuales.** En `_verificar_productos`/`editar_ticket`, permitir un producto inactivo únicamente cuando su ID ya forma parte del conjunto de detalles actuales del ticket `Pendiente`; permitir cambiar su cantidad. El servicio vigente hace `PUT` con reemplazo completo, así que debe comparar los IDs del payload con los detalles persistidos antes de sustituirlos: cualquier producto inactivo no presente en los detalles actuales recibe 409. Se valida el payload completo antes de borrar/reemplazar detalles. El alta de ticket siempre rechaza producto inactivo con 409. El despacho abierto conserva flujo; stock insuficiente mantiene su 409 existente.
6. **Endpoints y autorización aditiva.** Operaciones nuevas de transición por recurso, lectura de historial por recurso y listado de gestión conjunto; los paths/contratos concretos quedan explícitos en OpenAPI. Todas pasan por `requiere_operacion` y `requiere_capacidad` en cada endpoint. La matriz añade únicamente operaciones nuevas: Administrador para mutaciones/listado/historial; no se cambia ninguna fila actual. `catalogo` se aplica como gating adicional. Rol no autorizado 403 antes del recurso; ámbito inexistente/ajeno 404 idéntico para quien sí tiene la operación. Listado de gestión da 401/403 como errores relevantes; mutaciones e historial publican 401/403/404 y, donde aplica, 409/422.
7. **Lecturas operativas frente a gestión.** Mantener todos los listados operativos existentes filtrados para todos los roles, también Administrador. El nuevo listado de gestión devuelve productos y categorías del tenant con ambos estados e incluye estado en sus recursos; solo la vista de inventario del Administrador consume este listado. `GET /inventario/existencias`, categorías/productos de lectura operativa y catálogos para tickets filtran por producto activo y categoría activa.
8. **Inventario, movimientos, tickets y dashboard.** En `registrar_movimiento` rechazar 409 un producto inactivo. Las consultas de movimientos antiguos no filtran ni reescriben nombres. El dashboard excluye producto o categoría inactivos de `_listar_alertas` y del conteo/total de alertas; no se cambian KPI ajenos. El `stock_total` del producto inactivo queda fuera de `existencias`, no se altera.
9. **DDL de instalación limpia, semilla y versión.** Actualizar los dos scripts canónicos existentes (no crear migraciones): campos de vigencia y dos tablas en la plantilla de control y tenant; semilla QA de productos/categorías en activo, copia intacta de los estados al tenant, fila de versión `014.1` y guardia fail-closed actualizada. `VERSION_ESQUEMA_OBJETIVO` pasa a `014.1`. Los conteos de instalación limpia son 22 tablas control/19 tenant. Sin semilla de transiciones ficticias. Validación de instalación con volumen nuevo (`docker compose down -v` + `up -d`); no implica operar ni resetear una base con datos reales.
10. **Frontend Angular existente, sin vista/ruta nueva.** Extender InventarioComponent/HTML con sección condicional para `Administrador`; Signals/computed para listado, filtros/estados de operación y errores; `InventarioService` con gestión/transición/historial. La sección usa listado de gestión, separado de las llamadas operativas existentes. Helpers de rol de presentación en `core/auth/roles.ts`; API continúa siendo frontera. Tailwind, standalone, `inject()`, sin `NgModule` ni paquetes. Ajustar el formulario de ticket detalle: producto inactivo ya presente se conserva y permite modificar cantidad; no se ofrece para añadir líneas nuevas.
11. **Estrategia de pruebas.** TDD con pytest en backend (API, reglas, transacción, orden HTTP, matrices y OpenAPI); PostgreSQL gated para namespaces/paridad/constraints y carreras; Angular `ng test` para gestión y regresiones; cierre incluye `ng build`, OpenAPI vivo y recorridos 4200/8080.

## 3. Archivos previstos y responsabilidades

Los nombres de recursos de historial nuevos son descriptivos para planificar; en implementación se respetan las convenciones existentes de kebab-case para frontend y nombres españoles para identificadores.

### Documentación y base

| Archivo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Justificación aprobada de estado lógico, 16.ª/17.ª entidades, relaciones y paridad control/tenant; prerrequisito §1. | AC-14 |
| `database/01_esquema.sql` | Columnas `activo` en producto/categoría; dos tablas de historial en control y en plantilla tenant; conteo fail-closed de 20→22 control y 17→19 tenant. | AC-1, AC-7, AC-14 |
| `database/02_datos_semilla.sql` | Estado activo inicial de categoría/producto en control y tenants; versión `014.1`; guardia/validación de esquema con nuevos conteos; ninguna transición ficticia. | AC-13, AC-14 |
| `database/README.md` | Conteos 22/19, versión y pasos para reset limpio, reflejando instalación por los dos scripts vigentes. | AC-14 |

### Backend

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/models/producto.py` | Columnas `activo` en `Producto` y `Categoria`, defaults true, relaciones a los dos historiales. | AC-5, AC-13 |
| `backend/app/models/catalogo.py` (nuevo, si se mantiene separación por entidad) | Modelos de historial de transición de producto y categoría, FK reales a recurso y actor, fecha/motivo/estado origen-destino. Alternativa de menor dispersión: añadir modelos a `producto.py`; escoger una sola ubicación y documentar en implementación si diverge. | AC-7, AC-12, AC-14 |
| `backend/app/models/__init__.py` | Reexportar ambos modelos de historial. | AC-7, AC-14 |
| `backend/app/schemas/producto_schema.py` | Estado en respuestas existentes necesarias y schema del listado de gestión/operaciones de ciclo de vida. | AC-11, AC-15 |
| `backend/app/schemas/inventario_schema.py` | DTOs de historial y lectura agregada de gestión si no encajan semánticamente en producto_schema. | AC-7, AC-12, AC-15 |
| `backend/app/services/inventario_service.py` | Crear producto solo en categoría activa; listado de gestión; transiciones idempotentes/validación de motivo/atomicidad; filtro operativo de activo; movimiento sobre inactivo 409 y coordinación de bloqueos. | AC-3…AC-8, AC-13, AC-15, AC-16 |
| `backend/app/services/ticket_service.py` | Filtro de catálogos para productos/categorías activos; alta ticket 409 para producto inactivo; edición Pendiente compara detalles actuales antes del reemplazo completo, conserva/modifica cantidad de IDs inactivos existentes y rechaza IDs inactivos nuevos; despacho sin regla especial. | AC-4, AC-9 |
| `backend/app/services/dashboard_service.py` | Excluir productos/categorías inactivos de stock crítico/alertas y sus agregados sin cambiar demás KPI. | AC-10 |
| `backend/app/api/v1/endpoints/inventario.py` | Publicar listado de gestión, transiciones y consultas de historial con response_model/status/OpenAPI, matriz y capacidad. Mantener listados operativos previos. | AC-2, AC-11, AC-12, AC-14, AC-15 |
| `backend/app/core/permisos.py` | Entradas nuevas aditivas y exclusivas de Administrador donde dicta la spec; preservar literalmente las existentes. | AC-2, AC-12, AC-15 |
| `backend/app/core/capacidades.py` | Asociar cada nueva operación a `catalogo` sin ampliar conjunto cerrado. | AC-2, AC-12, AC-15 |
| `backend/app/core/config.py` | `VERSION_ESQUEMA_OBJETIVO = "014.1"` y comentario del token. | AC-14 |
| `backend/tests/api/test_ciclo_vida_catalogo_014.py` (nuevos módulos por tema si crecen) | Tests HTTP SQLite: estado, concurrencia lógica, motivos, idempotencia, autorización, filtros, edición, movimientos, dashboard, UI/API contracts. | AC-1…AC-13, AC-15 |
| `backend/tests/test_esquema_postgres.py` | Verificar DDL de las nuevas columnas/relaciones/tablas y su paridad. | AC-14 |
| `backend/tests/test_instalacion_limpia_postgres.py` | Conteos 22/19, filas activas por tenant, tablas de historial vacías en control/tenants, versión objetivo 014.1 y guardia de semilla. | AC-13, AC-14 |
| `backend/tests/test_ciclo_vida_catalogo_postgres_014.py` (nuevo gated) | Concurrencia real saldo-vs-baja y categoría-vs-alta/reactivación, con barreras/segunda conexión contra PG16; verificar no quedar en estados incoherentes. | AC-6, AC-16 |
| Tests existentes `backend/tests/api/test_permisos*.py`, `test_gating_capacidades_endpoints_012.py`, pruebas de tickets/inventario/dashboard y gated de versión | Ajustar transcripciones/literales de versión y ampliar casos sin cambiar baseline previo; regresiones relevantes para productos siempre activos. | AC-2…AC-16 |

### Frontend

| Archivo | Responsabilidad | AC |
|---|---|---|
| `frontend/src/app/shared/interfaces/index.ts` | Tipos de recurso gestionable, historial de producto/categoría y transiciones coherentes con schemas. | AC-7, AC-11, AC-12, AC-15 |
| `frontend/src/app/core/auth/roles.ts` | Helper de presentación para mostrar sección a Administrador; no sustituye API. | AC-11 |
| `frontend/src/app/features/inventario/services/inventario.service.ts` | Llamadas al listado de gestión, transición e historiales, manteniendo consultas operativas. | AC-11, AC-12, AC-15 |
| `frontend/src/app/features/inventario/inventario.component.ts` / `.html` / `.spec.ts` | Sección dentro de vista existente, role-gated en UI, listado con estado activo/inactivo, motivo, acciones, historial y errores/idempotencia. | AC-11, AC-15 |
| `frontend/src/app/features/tickets/tickets.component.ts` / `.spec.ts` | Regresión de catálogo de alta: productos y categoría inactivos no aparecen en selectores. | AC-4, AC-9 |
| `frontend/src/app/features/tickets/ticket-detalle.component.ts` / `.spec.ts` / `.html` | Edición: un item inactivo ya presente se conserva y su cantidad puede cambiar; nuevos selectores no ofrecen inactivos. | AC-9 |
| `frontend/src/app/features/dashboard/dashboard.component.spec.ts` | Comprobar render de salida API filtrada sin alteración de estructura UI si el componente no calcula alertas localmente. | AC-10 |

### Cierre documental

| Archivo/área | Responsabilidad | AC |
|---|---|---|
| `docs/spec/features/014-ciclo-vida-catalogo/tasks.md`, `spec.md`, `MEMORY.md`, `AGENTS.md` §7, `roadmap.md` | Registrar evidencia por AC, actualizar conteo de dominio a 17, verificar coherencia §8.7 y cerrar roadmap solo tras suites y ambos puertos. `AGENTS.md` y `MEMORY.md` se actualizan en el cierre, no durante la implementación ordinaria. | AC-14, cierre |

## 4. Estrategia de pruebas

### Backend SQLite — `pytest`

- Escribir tests de contrato por TestClient antes de la implementación: códigos, orden 401 → 403 matriz → 403 capacidad → 404 ámbito → 200 idempotente → 422 motivo → 409 precondición, y ninguna escritura parcial.
- Transiciones: baja/reactivación producto y categoría, motivo faltante/vacío/espacios/501, límite 500, historial exacto (una transición por cambio efectivo), reintento idempotente sin motivo, precondiciones de saldo/categoría y reactivación con categoría inactiva.
- Tickets/inventario: alta en categoría inactiva 409; producto inactivo en alta ticket 409; edición Pendiente conserva producto inactivo ya presente y puede modificar cantidad; un ID no presente se rechaza 409; movimientos nuevos 409; despacho abierto conserva flujo/409 de stock insuficiente sin efectos parciales.
- Lecturas: operativas filtradas para todos los roles; gestión incluye activos/inactivos solo Administrador; historial solo Administrador, tenant ajeno 404 oculto; existencias/dashboard omiten productos inactivos y categorías inactivas.
- Matriz y OpenAPI: operaciones nuevas aditivas, roles correctos, gating apagado 403; listados con clases de error aplicables; no hay rutas de escritura de historiales.
- Mantener verdes casos anteriores que esperan siempre activos: actualizar fixtures solo cuando el nuevo requisito exige estado explícito, sin debilitar sus afirmaciones previas.

### PostgreSQL gated — obligatorio con `POSTGRES_TEST_URL`

- Ejecutar `test_esquema_postgres.py`, `test_instalacion_limpia_postgres.py` y los nuevos tests gated en base temporal desechable; nunca usar `apt_erp` como base de prueba.
- Instalación `01 + 02`: verificar exactamente 22 tablas en control y 19 por tenant, columnas de estado, ambas tablas de historial en todos los esquemas, constraints/FK, filas de producto/categoría activas, historiales vacíos, control como contexto global y versión única `014.1`.
- Concurrencia real en dos conexiones: entrada a producto frente a desactivación; baja categoría frente a creación/reactivación; bloquear/verificar resultado serializable y ausencia de categoría inactiva con producto activo o producto inactivo con nueva cantidad positiva. SQLite no acredita estos casos.

### Frontend

- `cd frontend; $env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; npx ng test --watch=false --browsers=ChromeHeadless`.
- Probar Admin frente a Bodeguero/Solicitante, listado administrativo separado del operativo, envío de motivo, 200/idempotencia, 409/422 y mensajes de error; ticket Pendiente conserva/modifica cantidad de producto inactivo existente sin ofertarlo como producto nuevo.
- `cd frontend; npx ng build` sin errores de producción.

## 5. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Carrera entre entrada de stock y desactivación de producto, especialmente si no existe fila de saldo para bloquear. | Bloqueo común de producto, ordenado antes de stock, tanto en movimiento como en transición; test gated PG16 de dos sesiones y saldo final. |
| Carrera entre desactivación de categoría y alta/reactivación de producto. | Bloqueo común de categoría y validación dentro de la misma transacción en ambas rutas; fijar orden categoría→producto→stock; prueba gated intercalada en PostgreSQL. |
| Deadlock por caminos que bloquean categoría/producto/stock en orden diferente. | Definir y documentar orden único de adquisición; tests de concurrencia repetidos con timeout finito y comprobación de rollback. |
| Cambios de vigencia no llegan a todas las plantillas o el token queda desfasado. | Paridad exacta de DDL control/tenant, pruebas de instalación limpia de conteos y versión; no admitir tenants sin `014.1`. |
| Suites previas asumen productos/categorías siempre activos. | Buscar fixtures/selectores/tests existentes; añadir activo explícito en fixtures base o crear fixtures específicas, preservando asserts de otras features. |
| Dos filtros (producto y categoría) divergen entre existencias, tickets, dashboard o movimientos. | Predicado de disponibilidad consistente (`producto.activo` y `categoria.activo`) en cada lectura/operación; pruebas de contrato cruzadas con mismos IDs. |
| Cambio en ticket Pendiente borra/reinserta detalles y confunde conservar ID inactivo con añadir. | Capturar IDs actuales antes de validar; validar conjunto completo antes de escritura; prueba HTTP de edición con conservación y cantidad modificada, y caso de ID no presente →409. |
| Vista de gestión accidentalmente reutiliza lista operativa filtrada o aparece a roles no Admin. | Endpoint/listado de gestión separado; prueba de consumo de esa operación y renderizado por rol; autorización real server-side. |
| Rebuild o recuento de inicialización incompletos dan falsa señal de cierre. | Gated PG valida conteos y versión; 4200 se recorre contra backend/BD actual; 8080 exige rebuild antes de humo. |

## 6. Cobertura spec → plan

| AC | Cobertura principal |
|---|---|
| AC-1, AC-7, AC-8 | Servicio de transiciones + modelos/tablas de historial + pruebas de conservación, atomicidad, motivo e idempotencia. |
| AC-2, AC-12, AC-15 | Matriz aditiva, gating `catalogo`, endpoints/listado/historial y pruebas de 403/404/aislamiento. |
| AC-3 | Tests HTTP de precedencia y no efectos. |
| AC-4, AC-10 | Filtros del catálogo/existencias, tickets, dashboard y consultas históricas. |
| AC-5, AC-13, AC-16 | Reglas categoría/producto, alta en categoría activa, serialización de baja vs altas/reactivación; gated PG. |
| AC-6 | Bloqueo coordinado producto/stock, solo `stock_sede`, movimiento auditado; gated PG. |
| AC-9 | `ticket_service`, `inventario_service` y tests de alta/edición/movimientos/despacho. |
| AC-11 | Sección Angular en inventario, service/roles/interfaces y `ng test`. |
| AC-14 | OpenAPI, DDL/semilla/versionado `014.1`, conteos 22/19, pruebas gated de instalación. |

## 7. Condición de bloqueo y límites

La justificación ya está escrita en `stack.md`; la confirmación explícita del coordinator/usuario es la condición para levantar el bloqueo sobre modelos y DDL. Si el coordinator confirma que la aprobación de la spec cubre el prerrequisito, T1 registra la decisión y las tareas pueden avanzar.

Si durante implementación se confirma una contradicción no resuelta entre dos criterios aprobados —en especial: serialización de `stock_sede` sin fila existente, aislamiento por lock order, o la equivalencia entre editar el detalle existente e insertar una línea adicional del mismo ID—, detener esa tarea y elevar al coordinator; no cambiar spec ni requisito de forma implícita. La política de AC-9 considera conservación por `producto_id` ya presente en el ticket actual y permite ajustar cantidad, no una línea nueva del mismo producto si se puede distinguir de forma fiable en el payload; si el reemplazo de conjunto hace esa distinción técnicamente imposible, solicitar decisión antes de relajar AC-9.
