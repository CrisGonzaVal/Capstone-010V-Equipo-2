# Feature 011 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario. Este plan concreta una implementación por fases; no habilita cambios de modelo hasta aprobar e incorporar primero la justificación de `stack.md` descrita abajo. No se agregan dependencias.

## 1. Enfoque técnico

### Prerrequisito: Superación de la norma de `stack.md`

Antes de modificar modelos, DDL, persistencia o migraciones, el usuario debe aprobar e incorporar el siguiente texto a `docs/spec/stack.md`. La tarea inicial de `tasks.md` se limita a esa edición documental y a validar la aprobación; la implementación queda bloqueada hasta entonces.

> #### Evolución del modelo organizacional e inventario por sede (Feature 011)
>
> La Feature 011 supera explícitamente la afirmación de la sección “Multi-tenant por esquemas PostgreSQL (Feature 010)” que establece que se conservan las mismas doce entidades 3NF y que ninguna entidad de dominio se elimina, fusiona o reasigna. La nueva granularidad operativa del inventario es `(sede_id, producto_id)`: el stock por sede sustituye el saldo operativo por departamento de `inventario`, y el total institucional se deriva exclusivamente como suma de los saldos por sede. No se mantienen saldos operativos departamentales o institucionales independientes.
>
> El modelo de dominio pasa de doce a catorce entidades: se incorporan `sede` y `stock_sede`. `departamento_encargado` es una tabla puente auxiliar de asociación, comparable a `mapa_usuario_esquema`, y no se cuenta como entidad de dominio. Se agregan `departamento.sede_id` y `usuario.sede_id` como referencias nullable con precondiciones operativas; `ticket.sede_id` nullable conserva la instantánea de sede de tickets nuevos y permite representar tickets legados; y `movimiento_inventario.stock_sede_id` nullable identifica movimientos nuevos contra stock por sede. Las columnas y restricciones compuestas locales deben impedir asociaciones incoherentes dentro del tenant, sin FK cross-schema.
>
> Las filas legadas de `inventario` referenciadas por `movimiento_inventario.inventario_id` se conservan sin modificación, al igual que sus claves y todos los movimientos históricos. `inventario.ubicacion` queda como dato legado y no se traslada automáticamente a `sede.direccion`. Los movimientos nuevos de negocio y consolidación referencian `stock_sede_id`; para esos movimientos `inventario_id` queda nulo, mientras los movimientos históricos conservan su `inventario_id`.
>
> La migración crea sedes deterministas por tenant y asigna departamentos mediante round-robin estable por `departamento_id`. Antes de cambiar cada tenant mide por producto la suma de las filas departamentales; después exige que la suma de stock por sede sea exactamente ese valor. Para cada `(sede, producto)`, el saldo inicial debe ser igual a la suma de sus movimientos nuevos de consolidación `ENTRADA`. Cualquier discrepancia aborta sin declarar éxito. La consolidación se audita con movimientos nuevos y nunca reescribe ni borra movimientos históricos.
>
> La unicidad operativa es una fila por `(sede_id, producto_id)`. `stock_minimo` y criticidad se evalúan por sede. Los KPI de `GET /dashboard/` conservan las fórmulas y semántica de Feature 009, aplicadas a la nueva granularidad por sede, sin consultar cifras departamentales legadas. `GET /inventario/existencias` expone sede y saldo; los endpoints de consulta no leen ni exponen las filas legadas de `inventario`.
>
> La asignación departamento-sede y usuario Bodeguero-sede se almacena en referencias nullable; la obligatoriedad es operativa, no `NOT NULL`: las operaciones que dependan de una asignación faltante se rechazan. Cada ticket nuevo almacena en `ticket.sede_id` una instantánea al crearse y el despacho usa esa sede aun si el departamento cambia luego. Tickets y movimientos históricos no se redirigen. Un tenant recién aprovisionado recibe automáticamente “Sede Central”; el CRUD administrativo de sedes permanece en Feature 012.
>
> El token objetivo de DDL pasa a `011.1`. Bootstrap/aprovisionamiento, control y cada tenant deben recibir estructura compatible; el routing compara igualdad exacta y deniega cerrado ante versión diferente, ausente, incompleta o duplicada. La migración de instalaciones existentes es explícita, transaccional/idempotente según sus checkpoints y no usa la semilla destructiva.

**Alternativa descartada:** implementar primero DDL/modelos y documentar la excepción después. Contradice AGENTS.md §7 y permitiría que el código operara bajo una norma arquitectónica que niega el modelo aprobado.

### Modelo ORM y relaciones

- Mapear `Sede` y `StockSede` como dos entidades de dominio SQLAlchemy 2.0 en módulos propios, usando `Mapped[...]`/`mapped_column()` para nuevos atributos. Mantener compatibilidad con estilo ORM existente durante transición sin introducir una migración global de estilo ajena a la feature.
- Definir unicidad de stock por sede/producto, claves de pertenencia institucional locales y `CHECK` de stock no negativo. `Departamento.sede_id`, `Usuario.sede_id`, `Ticket.sede_id` y `MovimientoInventario.stock_sede_id` son nullable según spec. La regla funcional de asignación exacta se valida en servicios, no mediante `NOT NULL`.
- Definir `DepartamentoEncargado` como asociación auxiliar con unicidad por pareja departamento/usuario y FKs locales. La consulta de encargados filtra por usuario existente, rol Solicitante y departamento actual coincidente; cambios de rol/departamento no requieren trigger ni mutación de auditoría.
- Mantener las filas heredadas de `Inventario`/movimientos como registros históricos. La entidad `StockSede` es la única fuente operativa nueva; no convertir IDs de inventario heredado en IDs stock_sede ni reutilizar `inventario.ubicacion`.
- Para `MovimientoInventario`, `inventario_id` admite NULL en movimientos nuevos, que usan `stock_sede_id` nullable. Las filas históricas conservan sus valores de `inventario_id` y la FK existente, sin reescritura de movimientos ni de referencias legadas. La integridad de nuevas filas se expresa en el contrato de servicio: exactamente un destino según clase de movimiento; legado: `inventario_id`; nuevo: `stock_sede_id`. Incluir una restricción de exclusividad solo si es compatible con todos los registros/SQLite y no contradice los flujos de auditoría.
- `Ticket.sede_id` será nullable para compatibilidad del histórico. Todo ticket nuevo requiere departamento asignado y guarda la sede en creación. Migración resuelve tickets legados de forma explícita; si la sede no se puede atribuir de forma inequívoca desde su departamento al snapshot previo, aborta en vez de redirigir silenciosamente.
- Añadir relaciones ORM explícitas, índices de FK consultadas y exportaciones desde `models/__init__.py`; conservar PK simples existentes y añadir claves únicas compuestas necesarias para FKs locales seguras.

**Por qué:** el esquema debe conservar integridad aun ante acceso fuera de los servicios, mientras los datos históricos mantienen sus identificadores/FK. Las asociaciones nullable permiten desplegar por fases y hacer fallar cerrado el uso operativo incompleto.

**Alternativa descartada:** reescribir la tabla `inventario` en sitio y cambiar la semántica de `inventario_id`; invalidaría las FK históricas de movimientos y haría indistinguibles los saldos actuales del archivo de auditoría.

**AC:** AC-2, AC-9, AC-10, AC-12.

### Migración de PostgreSQL existente y versión 011.1

- Crear `database/migraciones/002_migracion_modelo_organizacional_011.sql` siguiendo el patrón operacional de `001_migracion_multitenant_esquemas.sql`: ubicación fuera del glob de initdb, ejecución explícita con `psql -v ON_ERROR_STOP=1`, respaldo y ventana de mantenimiento; no ejecutar `02_datos_semilla.sql`.
- La migración debe cubrir esquema `control` y los cuatro tenants operativos INST-001..004, así como cualquier tenant ya registrado que exista al ejecutarse. Control recibe el DDL canónico actualizado; los tenants reciben el DDL tenant completo y datos locales.
- Preflight sin mutaciones: estado/versiones reconocibles; inventarios/movimientos/tickets legados íntegros; departamentos y productos resolubles; instituciones enumeradas; colisiones/estados parciales; conteos y snapshots previos por `producto_id`; integridad de todas las FKs y versiones actuales `010.1`. Una inconsistencia aborta identificando tenant/recurso.
- Adquirir lock operacional/migración compatible para impedir escrituras concurrentes durante medición y consolidación. Medir totales por producto antes de cambios. Crear sedes según tabla de D-7 y asignar departamentos por `departamento_id` ascendente a sedes por identificador estable, índice módulo N.
- Crear `stock_sede` y registrar un movimiento `ENTRADA` de consolidación por cada par sede/producto con saldo positivo (o fila representable según contrato), usando `stock_sede_id`; no modificar filas `inventario`, movimientos históricos ni sus FK. Asignar `ticket.sede_id` a tickets históricos con la sede del departamento resuelta durante la migración; preservar el snapshot obtenido para futuros despachos.
- Verificar por cada producto: suma de `stock_sede.stock_actual` idéntica a total medido antes; por cada par sede/producto, saldo idéntico a suma de movimientos de consolidación `ENTRADA`; cada departamento y ticket migrado resuelve sede; referencias legadas permanecen idénticas. La falla revierte la fase completa o deja tenant sin versión enrutable; nunca declara éxito parcial.
- Actualizar `version_esquema` a una sola fila `011.1` al final de la transacción/verificación para control y todos los tenants. `VERSION_ESQUEMA_OBJETIVO` debe fijarse en `011.1` en la tarea de configuración antes de habilitar routing del nuevo modelo. Routing permanece cerrado durante la ventana de migración si los esquemas no son aún compatibles.
- Segunda ejecución: tenants ya verificados en `011.1` no reciben duplicados; estados parciales o discrepantes abortan con diagnóstico y no se “reparan” destruyendo datos.

**Alternativa descartada:** migrar durante una petición, usar initdb o mantener el código aceptando simultáneamente saldo departamental y stock por sede. Eso expone estados parciales, hace la suma ambigua y puede romper la auditoría.

**AC:** AC-2, AC-9, AC-10, AC-12, AC-13.

### DDL de instalación limpia y semilla

- Actualizar `database/01_esquema.sql` como DDL canónico para control y para tenants, en orden compatible con la creación de FKs y claves compuestas. Incluir entidades, columnas nullable, checks, índices y auxiliares nuevos en el esquema global y en la plantilla replicada por tenant.
- `database/02_datos_semilla.sql` conservará intacta la guardia fail-closed previa al primer `TRUNCATE`; actualizar el conteo y la limpieza únicamente conforme a las estructuras autorizadas en instalación limpia. No convertirlo en migración.
- Sembrar las cuatro instituciones INST-001..004 existentes, las sedes según D-7, departamentos con sede por la misma regla determinista, usuarios Bodegueros con sede coherente y stock por sede. Los totales por producto de la semilla deben cuadrar con el agregado declarado en sus filas seed. Control conserva identidad Superadmin y no recibe filas QA de negocio que la semilla pueda truncar.
- En instalaciones limpias, la generación de DDL de tenants nuevos se mantiene en el flujo de aprovisionamiento, no por ejecutar la semilla SQL contra esquemas tenant ya aprovisionados.

**Por qué:** `01_`/`02_` corren por orden alfabético solo en volumen vacío; la migración real y la semilla QA tienen propósitos distintos.

**Alternativa descartada:** introducir `CREATE/ALTER/DROP` de migración en `02_`; violaría su guardia y convertiría el script destructivo en migrador implícito.

**AC:** AC-10, AC-12, AC-13.

### Servicios, API y autorización

#### Servicios

- Crear un servicio organizacional para asignación de departamento/sede, Bodeguero/sede y asociaciones departamento/encargado. Aceptar identidad ya resuelta, resolver alcance institucional mediante `ambito_service`, validar recursos dentro del tenant y usar 404 para recurso inexistente/ajeno, 409 para conflicto/precondición organizacional y 422 para payload inválido.
- `inventario_service.py`: `listar_existencias()` consulta exclusivamente `StockSede`, devuelve fila con sede/saldo, agrega `stock_total` por producto y aplica criticidad por saldo de sede. Lecturas legacy `/inventario/stock` se mantienen compatibles solo si pueden expresarse sin exponer filas legadas; no deben usarse como fuente vigente. Registrar movimientos nuevos mediante `stock_sede_id` y transacción de stock/auditoría.
- `ticket_service.py`: al crear, resolver departamento del solicitante y guardar `ticket.sede_id` actual dentro de transacción. Despacho bloquea ticket/stock según patrón `FOR UPDATE`, usa `ticket.sede_id` como snapshot, actualiza `StockSede`, crea movimiento con `stock_sede_id`, completa detalle/estado/fecha y hace un único commit. Ticket legada sin snapshot se rechaza con 409 hasta que la migración la resuelva.
- `dashboard_service.py`: conservar exactamente las fórmulas KPI de Feature 009 (unidades suma, tickets activos por estado, departamentos por PK, alertas como cantidad de filas críticas), sustituyendo fuente de stock por `StockSede`; criticidad y alertas por sede, con atribución institucional/sede. La actividad reconoce movimientos históricos por `inventario_id` y nuevos por `stock_sede_id` mediante proyección única compatible.
- `control_service.py`/`tenant_service.py`: crear “Sede Central” en aprovisionamiento nuevo; estructurarla antes de marcar versión operativa. Control/bootstrap también recibe la estructura canónica de 011 y su versión correspondiente, sin asociar una sede operativa al Superadmin de control salvo que la regla de contexto lo requiera.

#### Endpoints y permisos

El plan propone operaciones concretas en el router organizacional nuevo (p. ej. `endpoints/organizacion.py`) o en control administrativo según la decisión de integración de API, manteniendo rutas estables y sin CRUD de sede. Superficie mínima: consulta de sedes; asignación de sede a departamento; asignación de sede a Bodeguero; alta/baja de relación encargado-departamento; toda ruta declara `response_model`, `status_code` explícito, documentación OpenAPI y `respuestas_de_autorizacion()`.

Las operaciones de escritura de asignación corresponden solo a Administrador institucional en matriz central. Lecturas respetan los ámbitos de la spec; Superadmin solo lecturas globales existentes y atribuidas. Cada operación se agrega explícitamente a `MATRIZ_PERMISOS`; no existe permiso implícito. Las rutas concretas de la matriz se fijan al definir el contrato y se verifican en OpenAPI. La UI no se crea en 011.

**Por qué:** la política central es la autoridad de backend; los servicios resuelven ámbito de objeto. Mantener endpoints delgados y DTOs evita duplicación de autorización y SQL en routers.

**Alternativa descartada:** aceptar `institucion_id`/`schema` del cliente para seleccionar sedes, o usar guard Angular como control de acceso; ambos vulneran el routing de Feature 010.

**AC:** AC-1, AC-3…AC-9, AC-14.

### Frontend limitado a lecturas afectadas

- No se implementa interfaz administrativa; permanece en Feature 012.
- Actualizar `frontend/src/app/shared/interfaces/index.ts` para que los DTO de `GET /inventario/existencias`, dashboard y actividad coincidan con los schemas API: sede/saldo nuevos y atribución conservada.
- Ajustar `frontend/src/app/features/inventario/` para presentar la sede asociada a la existencia, sin presuponer un departamento como unidad de stock. Mantener filtros/conteos existentes salvo cambios necesarios por contrato.
- Ajustar `frontend/src/app/features/dashboard/` para representar alertas con sede y mantener KPI existentes; el frontend sigue siendo presentación de DTO, sin fórmulas de autorización/criticidad.
- No añadir componentes/rutas administrativas ni paquetes. Aplicar Angular standalone, signals/computed, inject y Tailwind.

**AC:** AC-2, AC-8, AC-11, AC-14.

## 2. Archivos previstos y responsabilidad

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Incorporar el texto completo de superación aprobado; prerrequisito documental antes de cambios de datos. | AC-2, AC-9, AC-10, AC-12 |
| `backend/app/models/sede.py`, `stock_sede.py`, modelo auxiliar organizacional y modelos existentes | Nuevas entidades y columnas/relaciones; conservar inventario legado y FKs de movimientos. | AC-2, AC-4, AC-9, AC-10, AC-12 |
| `backend/app/models/__init__.py` | Registrar/exportar modelos para metadata y pruebas. | AC-2, AC-12 |
| `backend/app/schemas/organizacion_schema.py`, `inventario_schema.py`, `ticket_schema.py`, `dashboard_schema.py` | DTO Pydantic v2 de asignación, existencia, movimiento, ticket y dashboard. | AC-2…AC-9, AC-11, AC-14 |
| `backend/app/services/organizacion_service.py` | Ámbito y operaciones de asociaciones/consulta mínima organizacional. | AC-1, AC-3…AC-8 |
| `backend/app/services/inventario_service.py` | Lectura exclusivamente por stock sede, criticidad por sede, escritura/auditoría nueva. | AC-2, AC-7, AC-8, AC-11 |
| `backend/app/services/ticket_service.py` | Snapshot en alta y despacho desde `ticket.sede_id`; movimiento nuevo por `stock_sede_id`. | AC-6, AC-9 |
| `backend/app/services/dashboard_service.py` | Mismas fórmulas 009 sobre stock sede y lectura mixta histórica/nueva de auditoría. | AC-8, AC-11 |
| `backend/app/services/control_service.py`, `tenant_service.py`, `backend/app/core/config.py` | Versión `011.1`, routing estricto, sede inicial en aprovisionamiento, actualización de control. | AC-12 |
| `backend/app/api/v1/endpoints/organizacion.py`, `api.py`, `backend/app/core/permisos.py` | API mínima, contratos FastAPI explícitos y entradas de matriz para Administrador institucional. | AC-1, AC-3…AC-8, AC-14 |
| `backend/app/db/database.py` | Confirmar que sesiones `schema_translate_map` siguen cubriendo entidades nuevas en control/tenant. | AC-1, AC-12 |
| `database/01_esquema.sql`, `02_datos_semilla.sql` | DDL canónico y seed QA con sedes/asignaciones; guardia fail-closed y orden preservados. | AC-10, AC-12, AC-13 |
| `database/migraciones/002_migracion_modelo_organizacional_011.sql` | Migración operacional de control y tenants: sedes, consolidación, auditoría y versión `011.1`. | AC-2, AC-9, AC-10, AC-12 |
| `backend/tests/` modelos, servicios, API, tickets, dashboard y gated PostgreSQL | Regresión y nuevos contratos; SQLite ordinario y PostgreSQL real para DDL/migración/FKs/tenant routing. | AC-1…AC-14 |
| `frontend/src/app/shared/interfaces/index.ts`, features inventario/dashboard y tests | Reflejar API y presentar sede/saldo y KPI existentes; sin UI administrativa. | AC-2, AC-8, AC-11, AC-14 |
| `docs/spec/features/011-modelo-organizacional/tasks.md`, `MEMORY.md` | Checklist secuencial, estado y decisiones al cerrar conforme a AGENTS. | AC-14 |

Los nombres de archivos adicionales se fijan al comienzo de cada tarea solo si el árbol real requiere un módulo específico; no se altera el alcance. La matriz y rutas API concretas deben quedar documentadas en el plan revisado antes de empezar la tarea de endpoints. Si la justificación de `stack.md` no está aprobada o el preflight de migración detecta discrepancia, se detiene implementación y se vuelve a spec/plan.

## 3. Estrategia de pruebas

### SQLite ordinario (`pytest`)

- TDD por interfaz pública: pruebas rojas de servicios y `TestClient` primero para asignaciones, sede de ticket, despacho, lecturas de existencias y casos de error.
- SQLite en memoria demuestra reglas de dominio y contratos pero no namespaces. Activar FKs en fixtures; incorporar entidades seed en fixtures sin fingir aislamiento físico.
- Verificar DTOs Pydantic v2, respuestas/status codes/OpenAPI, permisos 401/403, ocultación 404, conflictos 409 y validación 422.
- Testear: encargados múltiples/compatibles, exclusión de asociaciones incompatibles; departamento/Bodeguero sin sede; asignaciones y lectura acotadas; identificadores ajenos vía servicio/router; stock no negativo; ticket snapshot estable tras reasignación; rollback de despacho al fallar auditoría/commit.
- Actualizar pruebas existentes de inventario, despacho, dashboard y catálogos que afirmaban inventario departamental. Conservar todas las fórmulas y semánticas KPI 009 sobre fixtures StockSede; verificar que endpoints no leen `Inventario` legado.
- Ejecutar suite completa `pytest` tras cada conjunto coherente.

### PostgreSQL gated (`POSTGRES_TEST_URL`)

Las pruebas se omiten claramente cuando no está configurado `POSTGRES_TEST_URL`. Deben ejecutarse antes del cierre.

- DDL real: nuevas tablas/columnas, unicidad sede-producto, FKs compuestas locales, `stock_sede_id` nullable, conservación de FK `inventario_id`, ausencia de referencias cross-schema.
- Migración sobre base temporal derivada del patrón de `test_migracion_multitenant_010.py`: tenants 4 y control, snapshots previos, round-robin determinista, balances exactos, movimientos históricos idénticos, movimientos nuevos de consolidación y rollback en discrepancia.
- Idempotencia: una repetición en `011.1` no duplica sedes ni movimientos; estado parcial o versión no objetivo deniega routing y no deja éxito.
- Aprovisionamiento tenant nuevo crea sede “Sede Central” y versiona correctamente; sesión tenant/control usa `schema_translate_map` y la versión exacta `011.1`.
- Alternancia tenant y payloads con `sede_id` ajenos/inexistentes se rechazan sin mutación cruzada.
- Despacho con dos sedes: ticket creado en A, departamento reasignado a B, despacho rebaja A; B permanece sin cambios. Concurrencia/ACID comprobada en PostgreSQL.
- Contrato de auditoría: movimientos legados siguen enlazados a inventario; nuevos despachos/entradas se enlazan a StockSede; rollback atómico.
- Verificar KPI y alertas con tenants múltiples/homónimos, atribución institucional y criticidad por sede; prueba real de queries PostgreSQL (SQLite `GROUP BY` puede ocultar defectos).

### Frontend

- Actualizar las pruebas de inventario/dashboard que reflejan DTO y composición nueva, sin crear pruebas de UI administrativa.
- Ejecutar `npx ng test --watch=false --browsers=ChromeHeadless` (configurar `CHROME_BIN` a Edge según AGENTS §5 en esta máquina) y `ng build`.
- Confirmar contrato de `GET /inventario/existencias` y dashboard con fixtures HTTP que incluyan sede, saldo y atribución.

### Contrato y recorridos de cierre

- Inspeccionar `/openapi.json`: rutas nuevas, `response_model`, `status_code`, seguridad, 401/403/404/409/422, matriz coincidente.
- Recorrido funcional en 4200 con tenant real y escritura contra PostgreSQL: asignación sede-departamento/Bodeguero/encargado, creación ticket, cambio de departamento de sede y despacho desde snapshot correcto; revisar inventario/dashboard.
- Reconstruir y ejecutar `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d frontend`; smoke en 8080 para inventario/dashboard/rutas existentes.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Norma de doce entidades contradice el modelo aprobado | Bloquear todo cambio de modelo hasta incorporar y aprobar la justificación completa de `stack.md`. |
| Consolidación duplica o pierde stock | Medición previa externa por producto, migración con lock, round-robin determinista y aserciones exactas en cada fase; aborto transaccional. |
| Movimientos nuevos rompen FK histórica NOT NULL | Añadir `stock_sede_id` nullable, preservar `inventario_id` y FKs existentes; escrituras nuevas usan referencia nueva. Prueba PostgreSQL de ambas poblaciones. |
| Migración reescribe auditoría sin querer | Snapshot/hash de movimientos legados pre/post; solo INSERT de movimientos de consolidación; mismatch aborta. |
| Un ticket abierto se despacha en otra sede tras reasignación | Snapshot `ticket.sede_id` al crear; despacho consulta exclusivamente esa columna; gated test de reasignación. |
| Tenant nuevo no puede operar sin CRUD 012 | Aprovisionamiento crea “Sede Central” automáticamente antes de registrar versión operativa. |
| DDL/control/tenants quedan en versiones mixtas | Cambiar objetivo a `011.1`, migrar control y tenants bajo ventana; versión exacta solo tras verificación; fail-closed fuera de objetivo. |
| Semilla destruye datos existentes | Preservar guardia fail-closed antes de `TRUNCATE`; migración separada fuera de initdb. |
| KPI o alertas cambian semántica al variar granularidad | Reutilizar fórmulas 009 y probarlas sobre StockSede; actualizaciones de tests y atribución por sede/institución. |
| Legacy `inventario.ubicacion` se interpreta como dirección sede | Mantenerla legado; no copiar salvo decisión posterior que pruebe interpretación inequívoca; no es ubicación operativa nueva. |
| Asociación de encargado queda obsoleta por cambio de rol/departamento | Validar al asociar y filtrar en lecturas por usuario existente, rol Solicitante y departamento actual; limpieza por API, sin triggers. |
| SQL o fixture SQLite oculta diferencia PostgreSQL | Gated tests obligatorios de FK, schemas, migración, locks y consultas; SQLite no acredita estas garantías. |
| Superadmin obtiene escritura accidental | No ampliar permisos de escritura; pruebas de regresión 403 y lecturas globales atribuidas. |
| Imagen 8080 sirve frontend desactualizado | Rebuild explícito antes del smoke test de cierre. |

## 5. Cobertura AC por partes

| AC | Partes principales | Evidencia requerida |
|---|---|---|
| AC-1 | Servicio de ámbito, endpoints de sede, matriz | API contra dos tenants: sede creada en A no visible/usada en B, 404 sin mutación. SQLite contract + gated PostgreSQL. |
| AC-2 | Modelos StockSede, inventario_service, migración | Gated PostgreSQL: unicidad sede/producto; endpoints solo leen StockSede y no leen/exponen inventario legado. |
| AC-3 | DTO, servicio de asignación/consulta | API con ID inexistente/ajeno: 404, no mutación; gated cross-schema. |
| AC-4 | Tabla puente y servicio de encargados | SQLite/API: múltiples válidos; inválidos rechazados; consulta filtra relaciones incompatibles. |
| AC-5 | Endpoints y matriz | TestClient + `/openapi.json`: Administrador autorizado; 401/403/404/409/422 declarados y observados. |
| AC-6 | Departamento.sede_id y consulta/alta ticket | Tests asignación y ausencia: recibe sede correcta o 409 claro sin fallback. |
| AC-7 | Usuario.sede_id y servicio de inventario | Bodeguero opera una sede; otra devuelve 404, ausencia 409; autorización backend. |
| AC-8 | Read models globales | PostgreSQL: Admin ve institución; Superadmin ve lectura atribuida y escritura continúa 403. |
| AC-9 | Ticket.sede_id, TicketService, movimiento | Gated: ticket almacena A; departamento pasa a B; despacho rebaja A, movimiento `stock_sede_id`, transacción todo-o-nada. |
| AC-10 | Migración 002 y control de preparación | Snapshot por producto, asignación fija round-robin, igualdad exacta, movimientos legados idénticos, consolidación `ENTRADA`, aborto ante discrepancia. |
| AC-11 | Dashboard/inventario frontend y servicios | Tests backend 009 adaptados a sede; OpenAPI/DTO y ng test verifican sede/saldo y KPI sin cifras legadas. |
| AC-12 | DDL/semilla/aprovisionamiento/config/version | PostgreSQL: control y tenants en `011.1`, routing fail-closed, cuatro seeds, tenant nuevo con Sede Central. |
| AC-13 | DDL y seed | Instalación temporal limpia respeta orden; guardia sobre base con filas aborta antes de truncar. |
| AC-14 | Suites, OpenAPI y cierre | pytest, PostgreSQL gated, ng test/build, OpenAPI, recorridos 4200/8080, grep coherencia y MEMORY. |

## 6. Fuera de alcance

- UI/CRUD administrativo de sedes, departamentos, usuarios o encargados: Feature 012. Solo se actualiza el frontend existente de dashboard/inventario para reflejar contratos nuevos.
- Implementar edición/eliminación general de sedes. La sede “Sede Central” es solo bootstrap para tenant nuevo.
- Reescribir movimientos históricos o usar inventario legado como fuente de saldo.
- Transferencias entre sedes, múltiples bodegas, compras, reservas o nuevos ciclos de catálogo/ticket.
- Cambiar Clerk, routing `schema_translate_map`, identidad Superadmin global o abrir escrituras Superadmin a tenants.
- Añadir dependencias de Python o npm.

## 7. Cierre técnico

No iniciar modelos/DDL/migración hasta verificar que la edición propuesta de `stack.md` está aprobada e incorporada. No marcar AC ni roadmap como cerrados por implementación sola. Cierre requiere tests SQLite y PostgreSQL gated en verde, pruebas frontend, contrato OpenAPI, recorridos 4200/8080, memoria actualizada y grep de coherencia según AGENTS.md §8.5–§8.7. Cada AC se marca con evidencia observada en `spec.md` después de verificación.
