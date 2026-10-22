# Feature 008 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario (AC-1…AC-21, D-1…D-6). Este plan define implementación y evidencias; no altera los requisitos. No se añaden dependencias.

## 1. Enfoque técnico

### Modelo relacional, integridad y justificación

El catálogo adquiere pertenencia institucional explícita en `categoria.institucion_id` y `producto.institucion_id`. Se mantienen las claves primarias simples actuales para conservar todos los identificadores públicos, y se agregan claves únicas compuestas `(institucion_id, categoria_id)` y `(institucion_id, producto_id)` como destinos de relaciones compuestas. Producto referencia `(institucion_id, categoria_id)` de su categoría; inventario continúa heredando institución del departamento, pero su relación `(producto_id, institucion_id derivado)` debe quedar garantizada por el esquema mediante una clave institucional en inventario o una estrategia de clave foránea equivalente. No repetir institución sin constraint crearía contradicción; el implementador deberá modelar las referencias compuestas para que PostgreSQL rechace asociaciones cruzadas.

La pertenencia de tickets sigue derivada de `usuario → departamento → institución`; detalles deben hacer referencia a producto de esa misma institución. Se recomienda incluir/derivar `institucion_id` en `ticket` y en `detalle_ticket` para establecer FKs compuestas (ticket-usuario, detalle-ticket-producto), con valores mantenidos por el servicio y controles de integridad. La alternativa de depender solo de validación Python se descarta porque deja una vía para insertar referencias inválidas fuera del servicio. Las PK simples se conservan; las claves compuestas son restricciones de consistencia, no identidad nueva.

Este cambio aumenta el modelo descrito como 12 entidades 3NF sin agregar entidades de dominio: añade atributos de pertenencia/constraints en las existentes para satisfacer D-1…D-5. Antes de tocar modelos o SQL, actualizar `docs/spec/stack.md` con la justificación, relaciones institucionales, claves compuestas y nota de compatibilidad/migración. No normalizar una tabla nueva salvo que la spec se modifique y apruebe.

**Alternativa descartada:** producto/categoría globales con solo filtros por servicio; no cumple independencia ni evita referencias cruzadas. También se descarta duplicar nombres como clave o cambiar las PK públicas, porque rompería integridad/contratos y compatibilidad de IDs.

### Ámbito de autorización y permisos

Extender `ambito_service.py` para obtener el alcance único del usuario limitado desde departamento y ofrecer helpers para filtrar/validar categoría, producto, inventario, usuario y ticket. Los servicios reciben `IdentidadAutenticada`, nunca un `institucion_id` confiado del cliente. Los filtros se aplican en consultas ORM/Core y en la validación previa a cualquier escritura; objeto ajeno se oculta como 404, departamento explícitamente ajeno conserva 403 y ámbito limitado irresoluble es 403. Superadmin conserva las lecturas globales autorizadas, con identificadores/nombres de institución explícitos en lecturas agregadas cuando el contrato lo requiera.

Actualizar exclusivamente las entradas de `MATRIZ_PERMISOS` relativas a escritura de categoría/producto, stock/movimientos y tickets: Superadmin ya no escribe datos de institución concreta; Administrador institucional obtiene esas capacidades conforme al requisito y la matriz restante de 007 no cambia. Las lecturas autorizadas continúan globales para Superadmin. `requiere_operacion` / `requiere_roles` permanecen como frontera HTTP; reglas de ámbito siguen en servicios.

**Alternativa descartada:** escoger institución a partir de parámetros/selector frontend o dispersar comprobaciones de rol por routers; el cliente no es autoridad y duplicaría la matriz.

### Referencias cruzadas y transacciones

En creación de producto se valida categoría dentro de la institución autenticada antes de insertar. En inventario/movimientos se resuelve la institución del departamento/inventario y se comprueba que el producto pertenece a ella antes de modificar cantidades. En creación de ticket se valida el usuario solicitante en su ámbito, todos los productos por institución y las referencias compartidas antes del primer `add`; cualquier rechazo deja cero filas. En cambio de estado y despacho se valida primero ocultación del ticket y luego el ámbito de cada producto e inventario en la misma transacción. El despacho mantiene `FOR UPDATE`, única transacción y creación indivisible de movimiento, stock, cantidades entregadas, cierre y auditoría; SQLite no acredita concurrencia ni reglas PostgreSQL.

**Alternativa descartada:** confiar solo en filtros de listas o comprobar cruces después de escribir, por riesgo de acceso por ID y persistencia parcial.

### Migración de esquema existente y semilla

Crear `database/98_migracion_particionamiento_institucional.sql`, inmediatamente antes de `99_migracion_retiro_password.sql` en orden alfabético y después de los scripts de instalación limpia. No alterar el prefijo/nombre `99_` ya instalado. Tanto `98_` como `99_` deben ser válidos en instalación nueva; initdb se ejecuta una sola vez, por lo que una BD existente recibirá la migración mediante `psql` manual con `ON_ERROR_STOP=1`, no reinicializando el volumen ni corriendo la semilla destructiva.

La migración empieza con una fase de detección de ambigüedades sin cambios destructivos: determinar institución candidata de cada categoría/producto por referencias a inventario y detalle/ticket/usuario/departamento y propagación categoría-producto. Si un registro tiene más de una institución candidata o no se puede inferir inequívocamente, aborta con excepción/mensaje que identifica entidad e ID; transacción PostgreSQL garantiza rollback completo. Comentarios SQL documentan el algoritmo y el procedimiento de corrección manual. Solo tras pasar la validación se agrega/rellena pertenencia, constraints y claves compuestas; los IDs existentes y filas operativas se preservan. DDL condicional (`IF NOT EXISTS`/consultas de catálogo) hace la ejecución repetible, incluyendo reinicio después de una corrección manual. Verificar segunda ejecución sin cambios operativos.

Actualizar `01_esquema.sql` para instalación nueva con el mismo modelo y ajustar `02_datos_semilla.sql` a catálogos institucionales de al menos dos instituciones; repetir deliberadamente nombres de categoría y producto con IDs distintos y stock diferente. Conservar las cuatro instituciones, tickets y relaciones válidas, y sincronizar secuencias. La semilla es solo para base nueva/reset QA autorizado; nunca forma parte de la migración de datos existentes.

**Alternativa descartada:** renombrar `99_` o reinicializar volumen/ejecutar seed sobre datos reales, porque puede alterar orden de ejecución o destruir datos.

### Contrato `/auth/me` y Angular

Extender `IdentidadAutenticadaRespuesta` y el tipo Angular `IdentidadAutenticada` con la institución efectiva para roles limitados y explícitamente `null` para Superadmin, preferiblemente como objeto/identificador y nombre coherentes con lo ya expuesto por `/usuarios/instituciones`. El servicio de autenticación construye ese campo desde el ámbito resuelto; no aceptar entrada cliente ni usarlo para autorizar. Actualizar descripción OpenAPI. Angular consume la identidad ya cargada por `AutenticacionService` y muestra el contexto institucional donde corresponde; Superadmin muestra su contexto global. No se añade selector, cambio de ámbito ni dependencia nueva.

**Alternativa descartada:** consultar institución desde el perfil Clerk, aceptar un ámbito del navegador como autorización o introducir selector multiinstitución, que contradice D-3.

## 2. Archivos previstos y responsabilidad

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Justificar extensión del modelo 3NF existente, pertenencia y constraints institucionales antes de cambios de datos. | AC-1…4, 14, 20 |
| `backend/app/models/producto.py`, `inventario.py`, `ticket.py`, `institucion.py` y registro de modelos si aplica | Mapear pertenencia y relaciones/constraints; preservar PK simples y relaciones existentes. | AC-2…4, 14, 20 |
| `backend/app/schemas/producto_schema.py`, `inventario_schema.py`, `ticket_schema.py`, `auth_schema.py` | DTOs para institución efectiva/etiquetas institucionales y referencias; OpenAPI documentado. | AC-2, 8, 9, 11, 16, 17 |
| `backend/app/core/permisos.py` | Ajustar permisos puntuales de Superadmin escritura frente a Administrador; resto matriz 007 inalterado. | AC-10, 16, 18 |
| `backend/app/services/ambito_service.py`, `usuario_service.py`, `inventario_service.py`, `ticket_service.py`, `auth_service.py` | Filtros y validaciones de ámbito; referencias cruzadas y atomicidad; identidad institucional. | AC-4…18 |
| `backend/app/api/v1/endpoints/auth.py`, `inventario.py`, `tickets.py`, `usuarios.py` | Transportar identidad, respetar response_model/status/respuestas OpenAPI y contratos existentes. | AC-5…17 |
| `database/01_esquema.sql` | DDL limpio y constraints compuestas para instalaciones nuevas. | AC-1…4, 20 |
| `database/02_datos_semilla.sql` | Datos reproducibles en cuatro instituciones, homónimos independientes y stock/tickets coherentes. | AC-1, 3, 20 |
| `database/98_migracion_particionamiento_institucional.sql` (nuevo) | Detectar ambigüedad y abortar sin cambios; migrar preservando datos, IDs y relaciones; idempotencia y manual de operación. | AC-14, 15, 18, 20 |
| `backend/tests/conftest.py`, `backend/tests/api/test_ambito_institucional.py`, tests de permisos/migración y casos API relacionados | Fixtures para dos instituciones y cuatro roles; aislamiento, intentos cruzados y no mutación; prueba PG real para constraints/migración. | AC-1…18, 20 |
| `frontend/src/app/shared/interfaces/index.ts`, `frontend/src/app/core/services/auth.service.ts`, features inventario/tickets/dashboard y sus specs | Tipos y presentación institucional; consume `/auth/me`, no decide autorización. | AC-8, 17, 19 |
| `frontend/src/app/features/**` specs existentes de inventario/tickets/auth | Regresión de vista para institución limitada y Superadmin global sin contaminación de stock. | AC-19 |
| `docs/spec/features/008-particionamiento-institucional/spec.md` | Solo al cierre, marcar AC verificados e incluir evidencia específica. | AC-21 |
| `docs/spec/features/008-particionamiento-institucional/tasks.md`, `MEMORY.md`, revisión `AGENTS.md`/`.agents/skills/` | Marcar cierre y actualizar estado/documentación solo con evidencia real; no cambiar AGENTS/skills salvo referencias obsoletas demostrables. | AC-21 |

Los archivos concretos pueden ajustarse por el implementador si el código revela responsabilidades adicionales, manteniendo arquitectura, AC y límites de edición. No se propone paquete nuevo.

## Enmienda de autoatribución de tickets (22/Oct/2026)

> Se limita a D-7/D-8 y AC-11 reescrita. No reabre las 21 AC originales ni altera el modelo de particionamiento.

### Decisiones técnicas por capa y orden de validación

- **Entrada:** `TicketCrear.usuario_id` se vuelve opcional. Su valor, exista o no, no se usa ni valida. La identidad autenticada ya autorizada es la única fuente del usuario autor y ancla institucional.
- **Orden final de `crear_ticket`, completo y previo a la primera escritura:** (1) atribuir DTO a `identidad.usuario.usuario_id` incondicionalmente, ignorando campo de payload; (2) resolver institución efectiva de identidad y departamento/institución del usuario autenticado; ámbito limitado no resoluble mantiene denegación 403 conforme a seguridad existente; (3) verificar referencias compartidas prioridad/estado; (4) verificar cada producto contra la institución de identidad, preservando **404 producto ajeno**; (5) resolver sede del departamento de identidad y devolver **409** si no resoluble; (6) conservar reglas posteriores de estado inicial (p. ej. `Anulado` 409); (7) en una transacción escribir ticket con `institucion_id`/sede y detalles con misma institución, más historial. La autoría no se obtiene del usuario del payload, y el 404 por solicitante ajeno desaparece.
- **Semilla/sede:** roles 2 (Administradores 1/3/4/10, departamentos 1/3/4/10) y 3 (Bodegueros 6/7/12, departamentos 6/7/6) tienen sede asignada en sus departamentos. Si un departamento carece de sede, cualquier rol que tenga permiso vigente recibe 409 sin ticket, detalle ni historial; `usuario.sede_id` de un Bodeguero no es fallback.
- **Contrato:** no cambia `/tickets/`, response/status, matriz ni contrato de `GET /tickets/catalogos`; la lista `solicitantes` permanece. OpenAPI solo documenta optional/ignored para `usuario_id` y ya no presenta 404 por solicitante payload.
- **UI compartida:** campo informativo read-only con `nombre`, `apellido`, `correo` desde `AutenticacionService.identidad()` (la interfaz real expone también usuario_id/sub/rol/institucion, pero **no departamento**). No llamada extra, no selector. El formulario no incluye `usuario_id` en cuerpo. Solicitantes permanece como dato de lectura para listados/detalle.

### Archivos de la enmienda

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/ticket_schema.py`, `ticket_service.py`, `backend/app/api/v1/endpoints/tickets.py` | Opcionalidad, autoatribución/orden institución-productos-sede, documentación de contrato. | AC-11 |
| `backend/tests/api/test_tickets_institucional.py` | Cambiar 404 de solicitante ajeno a autoría de sesión; probar anclas; conservar producto ajeno 404. | AC-11 |
| `backend/tests/api/test_tickets_alcance.py`, `test_modal_ticket.py`, `test_ticket_sede_011.py`, `test_transaccion_ticket.py` y demás altas halladas por grep | Compatibilidad de payload y todas las identidades permitidas; mantener despacho aparte. | AC-11 |
| `frontend/src/app/features/tickets/tickets.component.ts`, `.html`, `.spec.ts`, `frontend/src/app/shared/interfaces/index.ts` | Campo solo lectura desde identidad y cuerpo sin usuario_id; sin selector. | AC-11 |
| `database/` y `backend/app/models/` | **No se modifican**: no hay DDL ni cambio de entidad. | AC-11 |

### Orden TDD único entre las tres features

`008/tasks.md` orquesta el único flujo porque AC-11 es dueña del resultado institucional pero la implementación también actualiza requisitos cerrados 003/007. Las secciones E22 en las tres tasks remiten a estas tareas; no crear copias concurrentes:

1. **E22-1 backend rojo→verde:** en `test_tickets_alcance.py` reemplazar obligatorio y actualizar creación para Admin/Solicitante/Bodeguero; en `test_tickets_institucional.py` reemplazar `test_crear_ticket_con_solicitante_ajeno_404_sin_parcial` y `test_administrador_crea_para_solicitante_de_otra_institucion_404_sin_mutar`; actualizar `test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion`. Añadir casos omitido/propio/ajeno/inexistente atribuidos a sesión, sede ausente 409 sin persistencia, producto ajeno 404 intacto, y anclas ticket/detalle en institución autenticada. Ajustar schema/service/docs del POST solo tras ver rojos.
2. **E22-2 frontend rojo→verde:** reescribir tests que fijan select, `formulario.controls.usuario_id.setValue(5)`, presencia del campo en body y `solicitantes().length` como requisito de UI; comprobar campo con nombre/apellido/correo, identidad existente, no llamada adicional, sin selector/control y sin campo en body. Catálogo sigue conservando solicitantes y tests de listados/detalle no se eliminan.
3. **E22-3 regresión:** inventariar con grep todos los `usuario_id` en tests API que corresponden a POST alta; mantener `test_crear_ticket_con_producto_ajeno_404_sin_parcial` y `test_crear_ticket_puebla_institucion_en_ticket_y_detalle` (ajustar actor a identidad persistida si requerido). Conservar payloads de `TicketDespacho` en `test_despacho_transaccional.py`; en `test_ticket_sede_011.py` adaptar altas solamente, no despacho.
4. **E22-4 verificación/cierre:** pytest SQLite + gated PostgreSQL si aplica a comprobación de esquema/tenant; ng test con Edge; `/openapi.json`; recorrido 4200 y 8080 tras rebuild si frontend cambiado. Actualizar evidencia por AC en 003/007/008 y `MEMORY.md`; grep de coherencia; roadmap solo con gates cumplidos.

### Riesgos y alcance excluido

| Riesgo | Mitigación |
|---|---|
| Seguir respondiendo 404 por solicitante de otra institución | Prueba el valor enviado ignorado y las columnas institucionales procedentes de sesión; retirar solamente ese 404. |
| Relajar aislamiento de producto junto con autoría | Test de producto ajeno permanece idéntico: 404 y cero ticket/detalles; prueba explícita independiente. |
| Admin/Bodeguero sin sede | 409 explícito antes de escritura; no fallback a `usuario.sede_id`; semilla actual y caso sin sede verificados. |
| Payload heredado pasa un `usuario_id` como si fuese actor | Grep completo de pruebas, mapear altas frente a despacho, probar omisión y valores ajeno/inexistente. |
| UI/evidencia antigua habilita suplantación | Campo read-only desde identidad, DOM/body tests y evidencia actualizada en los AC afectados. |

No se toca matriz ni permisos, Superadmin 403, catálogo de solicitantes, DDL/esquema/modelos, dependencias, schema/versión tenant, ni resto de despacho/stock/historial/estado/transacción de `crear_ticket`.

---

## Plan original (cerrado)

## 3. Estrategia de pruebas e integración

1. **Modelo/DDL**: nueva base PostgreSQL 16 desde `01` + `02`; verificar homónimos, restricciones categoría-producto, departamento-producto y ticket-producto. Fixture SQLite activa FKs, pero restricciones compuestas/cascadas relevantes se confirman en PostgreSQL.
2. **Migración PostgreSQL 16**: clonar/restaurar base legada con datos válidos, comprobar conteos, claves e IDs; ejecutar `98_` y verificar preservación. Ejecutar de nuevo y comparar estado. Preparar caso ambiguo (un producto/categoría usados desde dos instituciones): ejecutar, comprobar error con entidad/ID, rollback del DDL y filas intactas; corregir manualmente y reintentar.
3. **Backend pytest**: parametrizar por rol e institución A/B; validar lecturas para categorías, productos, existencias, stock, movimientos, usuarios, tickets y catálogos; Superadmin lectura global etiquetada; 401/403/404; ID ajeno vs inexistente; payloads cruzados para alta producto/inventario/ticket, PATCH y despacho; verificar estado/cantidad/detalles/movimientos no mutados. PostgreSQL real adicional para constraints compuestas y migración, pues SQLite no cubre esas semánticas.
4. **Contrato**: consultar `/openapi.json` para response models, status y 401/403/404 en rutas afectadas, y verificar `/auth/me` con institución limitada y `null` para Superadmin. Clerk no cambia.
5. **Frontend ng test**: probar mapeo de contexto en identidad, despliegue de nombre institucional para roles limitados, presentación global de Superadmin y ausencia de datos de catálogo/stock de B en vistas de A. Ejecutar `npx ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` Edge según AGENTS.
6. **Recorrido manual**: en 4200 con dos identidades institucionales, demostrar catálogo/stock separado, ticket/despacho real persistido y contexto mostrado; probar que Superadmin lee ambas instituciones y recibe denegación de escritura específica. Para 8080 reconstruir frontend (`docker compose -f docker-compose.yml build frontend` y `up -d frontend`) y hacer humo de visualización/navegación básica.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Asignación ambigua del legado o suposición errónea de pertenencia | Migración fail-closed preflight, rollback transaccional, mensaje por entidad/ID y corrección manual; no asignación automática. |
| FK simple deja pasar producto/categoría/tenant cruzado | Constraints compuestas y validación de servicio; pruebas directas en PostgreSQL 16. |
| Endpoint por ID no aplica filtro, aunque los listados sí | Matriz de pruebas objeto ajeno/inexistente en GET, PATCH y despacho; no mutación. |
| Aggregate global filtra productos pero mezcla stock de instituciones | Todos los joins/agrupaciones se filtran por ámbito; respuesta global atribuye institución sin fusionar registros. |
| Se altera accidentalmente matriz 007 más allá de la escritura acordada | Diff de permisos acotado y tests parametrizados de capacidades restantes. |
| Cambio de `/auth/me` rompe tipos o UI | Schema/type 1:1, pruebas de auth Angular y backend; campo informativo nunca autoriza. |
| SQLite verde con DDL/semántica diferente | Pruebas PostgreSQL 16 expresas para constraints, rollback/idempotencia y migración. |
| Seed destructiva ejecutada sobre volumen existente o script en orden incorrecto | Mantener `01`/`02`; migración `98` antes de `99`, aplicación explícita a volúmenes existentes, sin seed durante migración. |
| 8080 sirve imagen vieja | Reconstrucción frontend requerida antes del humo final. |

## 5. Evidencia de verificación AC por AC

| AC | Evidencia requerida al cierre |
|---|---|
| AC-1 | PostgreSQL nuevo con cuatro instituciones; consulta de dos instituciones muestra departamentos/usuarios/catálogos/stock/movimientos/tickets y homónimos con IDs/stock distintos. |
| AC-2 | Tests de catálogo aislado y constraints inválidas de categoría/producto e inventario/producto, sin filas tras rechazo. |
| AC-3 | Tests de prioridades/estados/roles compartidos por ambos ámbitos y regresión de catálogo/contrato. |
| AC-4 | POST de producto/detalle/inventario cruzado rechazado; verificación de cero persistencia en cada tabla afectada. |
| AC-5 | Tests HTTP por Administrador, Bodeguero y Solicitante de A: listas y catálogo tickets no contienen registros B, aun con filtro/ID cliente. |
| AC-6 | Fixture mismo producto homónimo y stocks diferentes; asserts de existencias, stock y catalogos tickets (total/sedes/crítico) solo de A. |
| AC-7 | Tests de usuarios/departamentos/instituciones/tickets/movimientos y anidados por rol; producto anidado correcto; tickets ajenos 404 sin cambio y Solicitante solo propios. |
| AC-8 | Superadmin obtiene lectura global con `institucion_id` o atribución equivalente; dos registros separados y agregados no mezclados. |
| AC-9 | Matriz parametrizada para GET por objeto, GET ticket, PATCH y despacho con ID ajeno/inexistente; ambos 404; POST ticket producto ajeno 404; no mutación. |
| AC-10 | Administrador intentando recurso/departamento ajeno denegado sin cambios; Superadmin escritura prohibida 403; Administrador dueño crea operación válida. |
| AC-11 | Pruebas de ticket con solicitante/producto en A/B, departamento ajeno 403, autoatribución Solicitante, respuestas 404 y cero ticket/detalle tras rechazo. |
| AC-12 | Pruebas de despacho con productos/inventarios cruzados, stock insuficiente y fallo inyectado: inventario/detalles/ticket/movimientos permanecen iguales; caso válido todo junto. |
| AC-13 | Pruebas de movimiento con inventario ajeno no cambian stock ni auditoría; movimiento válido deja fila de auditoría. |
| AC-14 | PostgreSQL legado: conteos/IDs/FKs antes-después; caso ambiguo aborta con ID explícito y rollback; corrección manual y reintento documentado. |
| AC-15 | Ejecutar migración dos veces y comparar conteos, IDs, stock, tickets, detalles, movimientos y constraints; ningún cambio operativo adicional. |
| AC-16 | Tests auth/roles/ámbito y `/openapi.json`: 401/403/404 publicados/observables para recursos pertinentes; Clerk se conserva. |
| AC-17 | Test API `/auth/me` para los tres roles limitados con institución derivada y Superadmin con `null`; contrato no acepta selector/ámbito de entrada. |
| AC-18 | `pytest` verde; casos con dos instituciones y cuatro roles; evidencia PostgreSQL 16 para migración y constraints que SQLite no prueba. |
| AC-19 | `ng test` verde y recorrido funcional 4200 con contexto, catálogo/stock aislado y roles; evidencia de no filtración UI. |
| AC-20 | DDL + seed coherentes con pertenencia y evidencia de migración existente sin reset de volumen ni seed. |
| AC-21 | Todas las tareas marcadas, tabla AC de spec con evidencia, pytest/ng test, recorrido 4200 y humo 8080 reconstruido, y grep documental de AGENTS/MEMORY/skills registrado. |
