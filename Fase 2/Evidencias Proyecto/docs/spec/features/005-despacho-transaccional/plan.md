# Feature 005 — Plan Técnico

Spec: [`spec.md`](spec.md) (aprobada). El plan se limita a las decisiones técnicas necesarias para cumplir sus AC; no cambia el modelo de doce entidades ni el DDL.

## 1. Flujo técnico

### Despacho

`POST /api/v1/tickets/{ticket_id}/despacho` recibe el DTO mínimo con `usuario_id` y delega a `ticket_service`. El servicio abre la operación en la sesión síncrona recibida por `Depends(get_db)`, obtiene el ticket mediante `select(Ticket).where(...).with_for_update()` y comprueba existencia antes de otras referencias. El bloqueo de fila se conserva hasta commit o rollback; con PostgreSQL, la segunda operación del mismo ticket espera y al continuar lee el estado confirmado por la primera. SQLite no implementa semántica de bloqueo de fila para la suite: allí se prueban los contratos y rollback, mientras AC-12 se verifica con PostgreSQL real.

Después de bloquear, el servicio valida en el orden contractual: actor existente; catálogo ordenado por `estado_id` y resolución case-insensitive de `EnCurso`/`Cerrado` (la primera coincidencia es el menor id); elegibilidad; detalles no vacíos; producto resoluble; exactamente una fila de inventario por cada producto; stock suficiente para el total agrupado por producto. Todas estas comprobaciones ocurren antes de cambiar entidades.

Con el conjunto validado, por cada detalle se decrementa el inventario único, se fija `cantidad_entregada = cantidad_solicitada` y se agrega un `MovimientoInventario` `SALIDA` con la cantidad de ese detalle y la observación literal D-6. Se cambia el ticket al id canónico de `Cerrado`, sella `fecha_cierre` y se hace un único `commit()`, seguido de `refresh()`/carga necesaria para devolver `TicketRespuesta` con detalles y productos. Cualquier excepción durante escrituras o commit ejecuta `rollback()` y se propaga; los rechazos de negocio previos a escritura no producen efectos.

### Protección del cierre manual

`actualizar_estado_ticket()` conserva el orden de validación existente (ticket, estado destino, flujo) y agrega una guardia específica antes de modificar el ticket: si el estado actual es el `EnCurso` canónico y el destino es el `Cerrado` canónico, responde 409 con el detalle literal especificado por AC-15. Los estados se eligen de la lista ya ordenada por id; no se usa ordinal como sustituto del nombre. La regla normal de pasos contiguos sigue intacta para el resto de transiciones.

### Historial

`listar_movimientos()` usa una consulta SQLAlchemy Core con columnas de `MovimientoInventario`, `Inventario`, `Producto` y `Departamento`, con joins explícitos por sus FK y order-by `fecha_movimiento DESC, movimiento_id DESC`. Convierte cada mapping en `MovimientoInventarioRespuesta`. Es una lectura de múltiples entidades y no debe depender de `from_attributes` sobre una entidad individual. No se devuelve actor ni ticket como autoría/campos persistidos: la correlación del despacho está únicamente en `observacion`.

## 2. Archivos que se crean o modifican

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/ticket_schema.py` | DTO Pydantic v2 del payload `usuario_id` para despacho. | AC-1, AC-6, AC-13, AC-21 |
| `backend/app/schemas/inventario_schema.py` | DTO de lectura `MovimientoInventarioRespuesta` para el read model del historial. | AC-17…AC-21 |
| `backend/app/services/ticket_service.py` | Servicio de despacho con lock, validaciones y escrituras ACID; impedir cierre por PATCH sin alterar las demás transiciones. | AC-1…AC-16, AC-23, AC-27 |
| `backend/app/services/inventario_service.py` | Consulta de historial por joins explícitos, mapping al DTO y orden determinista; conserva intacto el registro manual existente. | AC-17…AC-20, AC-22, AC-23 |
| `backend/app/api/v1/endpoints/tickets.py` | Declarar ruta POST con `TicketRespuesta`, código 200, resumen/descripción y errores contractuales; documentar el PATCH restringido. Sin lógica de negocio. | AC-1, AC-5…AC-8, AC-15, AC-21 |
| `backend/app/api/v1/endpoints/inventario.py` | Exponer GET de movimientos con `list[MovimientoInventarioRespuesta]`, 200 y documentación de orden/campos. Mantener POST manual. | AC-17…AC-22 |
| `backend/tests/api/test_despacho_transaccional.py` (nuevo) | Pruebas HTTP y fixtures de catálogo/datos para despacho, errores, atomicidad y casos degenerados. | AC-1…AC-14, AC-23 |
| `backend/tests/api/test_historial_movimientos.py` (nuevo) | Pruebas HTTP del listado vacío, campos relacionados, orden e integración con salidas de despacho. | AC-17…AC-23 |
| `backend/tests/api/test_tablero_kanban.py` | Migrar los casos de cierre manual (`EnCurso→Cerrado`) a 409 exacto y verificar que las otras transiciones válidas siguen operando. | AC-15, AC-23 |
| `frontend/src/app/features/tickets/tickets.component.ts` | Resolver canónicamente `EnCurso` por nombre/id menor y no ofrecer avance desde esa columna; conservar retroceso y controles de otras columnas. | AC-16, AC-25 |
| `frontend/src/app/features/tickets/tickets.component.spec.ts` | Añadir casos de control ausente en `EnCurso`, retroceso disponible, demás columnas sin regresión y nombres duplicados. | AC-16, AC-25 |
| `docs/spec/features/005-despacho-transaccional/tasks.md` | Checklist ordenado; cada implementación marca su propia tarea con evidencia. | AC-23…AC-28 |
| `docs/spec/features/005-despacho-transaccional/spec.md` | Al cierre, consignar evidencia verificable por AC en §6, sin alterar requisitos aprobados. | AC-23…AC-28 |
| `docs/spec/roadmap.md` | Solo en el task final y tras evidencias completas, marcar la fila 005 cerrada y añadir el enlace/estado al índice. | AC-28 |
| `MEMORY.md` | Solo al cierre, actualizar estado y aprendizajes de la 005 de forma breve. | AC-28 |

No se modifican modelos, `database/01_esquema.sql`, semilla, dependencias ni estructura de autenticación. `TicketRespuesta` ya refleja el ticket y detalles; el despacho la reutiliza.

## 3. Decisiones técnicas y alternativas

### 3.1 `SELECT ... FOR UPDATE` en SQLAlchemy síncrono

La lectura inicial del ticket será `db.execute(select(Ticket).where(Ticket.ticket_id == ticket_id).with_for_update()).scalar_one_or_none()`. Se mantiene la misma `Session` hasta commit/rollback; no se abre una transacción aparte ni se libera el lock entre validación y escritura. La adquisición ocurre antes de leer/validar estado. La segunda petición bloqueada lee de nuevo la versión comprometida y se rechaza por estado ya no elegible. Una excepción en cualquier escritura/commit invoca `db.rollback()` explícito.

**Alternativa descartada:** check-then-write sin lock o bloqueo solo del inventario. No serializa el derecho único a cerrar el ticket, y podría duplicar movimientos aunque cada inventario quedara sin stock negativo. El test concurrente determinante requiere PostgreSQL porque SQLite ignora `FOR UPDATE`.

### 3.2 Resolver estados por nombre sin ids constantes

Leer `EstadoTicket` con `select(...).order_by(EstadoTicket.estado_id)`, luego tomar la primera coincidencia con `nombre.casefold()` para cada nombre canónico. La lista da menor id ante duplicados y deja claro el criterio incluso con catálogos degenerados. Las faltas de estado producen 409. El PATCH realiza la misma resolución para identificar el par origen/destino reservado; no infiere que el último ordinal equivale necesariamente a `Cerrado`.

**Alternativa descartada:** ids constantes, `max(estado_id)` como terminal o depender del nombre sin desempate; cada una contradice la regla de catálogo aprobada o falla ante duplicados/reordenamientos.

### 3.3 Validación global antes de mutar

Las líneas se cargan ordenadas por `detalle_ticket_id`; productos requeridos se deduplican para resolución. Se validan las referencias de Producto y se consulta el conjunto de `Inventario` de esos ids, acumulando filas por `producto_id`. Cada producto debe resolver exactamente una fila. La cantidad total se suma por producto y se contrasta con `stock_actual` antes de tocar cualquier fila; luego se escriben salidas individuales por detalle. De este modo varias líneas de un mismo producto requieren stock agregado pero conservan un movimiento por línea.

**Alternativa descartada:** descontar línea a línea validando cada una al escribir. Con líneas repetidas podría mutar una parte antes de descubrir insuficiencia, y la asignación del departamento sería implícita.

### 3.4 Read model del historial

La consulta seleccionará columnas con etiquetas que coincidan con los campos del DTO, uniendo `MovimientoInventario.inventario_id` con `Inventario`, `Inventario.producto_id` con `Producto`, y `Inventario.departamento_id` con `Departamento`. Se ejecutará con `.mappings()` y el DTO se arma por mapping. Los joins son internos: las FKs requeridas implican que cada movimiento persistido tiene inventario, producto y departamento resolubles.

**Alternativa descartada:** `select(MovimientoInventario)` con relaciones lazy (riesgo N+1 y lectura no aplanada) o añadir columnas al esquema (prohibido por AC-27). No hay paginación ni filtros en esta entrega.

### 3.5 TDD y verificación de base real

Primero se implementan pruebas HTTP rojas que observan respuestas y efectos persistidos en el motor de prueba, siguiendo el seam actual y sus fixtures. Las pruebas de concurrencia no se simulan como garantía SQLite: se reservan para PostgreSQL 16 real en el task de AC-24, con dos sesiones/solicitudes sincronizadas al mismo ticket y comprobación de 200/409 y juego único de movimientos. La lectura persistida verifica stock, detalles, ticket e historial.

**Alternativa descartada:** afirmar concurrencia a partir de un test SQLite o llamar directamente al service como única prueba. La suite de memoria no ofrece el bloqueo de fila real ni reproduce el contrato HTTP.

### 3.6 Kanban sin cierre manual

El cálculo de controles mantiene la lógica por posición existente y añade una condición de negocio independiente: cuando la columna es el estado canónico `EnCurso` (resuelto case-insensitive y con menor id ante duplicados), `puedeAvanzar` es falso aunque exista una columna siguiente. `puedeRetroceder` se calcula como hoy para esa columna. No se ocultan controles en otras columnas por nombre ni se añade interfaz de despacho, que está fuera de alcance.

**Alternativa descartada:** convertir `EnCurso` en terminal para todos los controles, lo que ocultaría retroceso; comparar ids fijos o asumir que es siempre el penúltimo estado también rompe los catálogos mutables.

## 4. Estrategia de pruebas y cobertura

- Backend: tests HTTP nuevos y migrados en `backend/tests/api/`, primero rojos y luego `cd backend && pytest`. Casos: despacho satisfactorio, líneas repetidas, stock insuficiente sin efectos, inexistencias, estados faltantes/duplicados/case-insensitive, inventario 0/varias filas, detalle vacío, producto no resoluble, rollback, PATCH 409 exacto y transiciones no afectadas; historial vacío/campos/orden/salidas. Suite completa obligatoria.
- PostgreSQL: reproducir despacho concurrente de un mismo ticket desde dos conexiones independientes; exactamente 200 y 409, y consulta SQL/HTTP posterior evidencia un solo juego de movimientos, rebaja, cantidades entregadas y cierre (AC-24).
- Frontend: añadir test de AC-16 en `tickets.component.spec.ts`, verificando ausencia del control de avance en `EnCurso`, presencia de retroceso y controles válidos en el resto; ejecutar `npx ng test --watch=false --browsers=ChromeHeadless` (Edge vía `CHROME_BIN` según AGENTS.md §5).
- OpenAPI: inspeccionar `/openapi.json` para los tres endpoints, esquemas de payload/respuesta, códigos explícitos, resumen, descripción y errores relevantes; revisar también que el POST manual de movimientos conserva su contrato.
- Cierre: build de producción; recorrido en 4200 con backend/PostgreSQL real (despacho persistido y PATCH manual 409); construir y recrear frontend para humo en 8080; grep de coherencia; documentar evidencia por AC antes del roadmap.

## 5. Cobertura AC → pieza

| AC | Pieza principal |
|---|---|
| AC-1…AC-3 | DTO/servicio de despacho: línea por detalle, suma y stock validado antes de escribir |
| AC-4…AC-14 | Servicio/endpoint y pruebas HTTP: rechazos, nombres, inventario, ticket vacío, rollback y lock |
| AC-15 | Guard del servicio `actualizar_estado_ticket()` y pruebas migradas de 004 |
| AC-16 | Resolución de estado en componente + test Angular |
| AC-17…AC-20 | DTO, consulta de historial, endpoint y pruebas HTTP integradas |
| AC-21…AC-22 | OpenAPI de tickets/inventario; no regresión del POST manual |
| AC-23 | Suite `pytest` completa y tests de casos de dominio |
| AC-24 | Recorrido/test de concurrencia y lectura persistida en PostgreSQL 16 |
| AC-25 | `ng test` y regresión de controles Kanban |
| AC-26 | Recorrido funcional 4200 y humo 8080 tras build + `--force-recreate` |
| AC-27 | Diff y grep: sin modelos/DDL/dependencias/auth; lógica permanece en services |
| AC-28 | Evidencia AC, coherencia textual, roadmap y `MEMORY.md` al cierre |

## 6. Riesgos y mitigaciones

- **Diferencia SQLite/PostgreSQL en bloqueos:** SQLite ignora `FOR UPDATE`; no presentar tests en memoria como prueba AC-12, verificarla en PostgreSQL real.
- **Rollback ante error de commit o escritura:** mantener las mutaciones dentro de un único bloque transaccional y probar fallo que ocurra después de iniciar escrituras con estado final íntegro.
- **Stock repetido por producto:** comparar total requerido contra la fila única antes de rebajar y probar múltiples detalles del mismo producto.
- **Catálogos anómalos:** centralizar la regla de menor `estado_id` luego de ordenar; tests deben incluir nombres duplicados, distintas mayúsculas y falta de nombre.
- **Cambio de contrato de la 004:** tests existentes que aprobaban cierre vía PATCH deben actualizarse, sin borrar cobertura de las transiciones permitidas restantes.
- **Build congelado en 8080:** el recorrido de cierre usa `docker compose -f docker-compose.yml build frontend` y `up -d --force-recreate frontend`; un `up` sin recreación no demuestra que se sirva el build nuevo.
- **No afirmar autoría:** `usuario_id` valida el actor de la petición, pero no aparece como autor en movimientos ni historial, porque no existe tal columna.
