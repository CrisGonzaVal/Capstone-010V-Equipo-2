# Feature 013 — Plan técnico

Spec: [`spec.md`](spec.md). La spec está aprobada por el usuario; este plan concreta su implementación sin alterar alcance. No se añaden dependencias.

## 0. Nota de estado de la spec

La aprobación corresponde al usuario/coordinador; la cabecera de `spec.md` aún refleja `**Estado:** borrador` y su actualización pertenece al flujo de aprobación, no a este plan. Este plan no modifica la spec; toda duda de diseño resoluble a nivel técnico se decide aquí y se marca como decisión con su alternativa descartada.

## 1. Prerrequisito desbloqueante: justificación en `stack.md`

La sección «Ciclo de vida del ticket: estado `Anulado` e historial de transiciones (Feature 013)» fue incorporada al final de §2 de `docs/spec/stack.md` (patrón de las secciones 011/012). Fija:

- `Anulado` como quinta fila del catálogo `estado_ticket` replicado por tenant, de presencia obligatoria en toda instalación (semilla, constructor, migración con token `013.1`), sin CRUD.
- `historial_transicion_ticket` como **15.ª entidad de dominio** (no auxiliar): hecho de negocio inmutable, visible por API, con FK a `ticket`, `usuario` y `estado_ticket`; el modelo pasa de 14 a 15 entidades de dominio.
- Por qué `fecha_cierre` **no** se sella en la anulación y por qué no hay segunda columna de fecha.
- Por qué el token sube de `012.1` a `013.1` y por qué las transiciones previas no se reconstruyen.

**Bloqueo:** ninguna tarea puede tocar `backend/app/models/`, `backend/app/schemas/`, `database/` ni `VERSION_ESQUEMA_OBJETIVO` hasta que el usuario/coordinador apruebe ese apartado en `stack.md` (mismo mecanismo de bloqueo de la 012, §6).

## 2. Impacto en la matriz de permisos y en el gating de la 012

- **La matriz pasa de 44 a 49 operaciones** (aditivo; ninguna fila existente se modifica). Las 5 nuevas, con los roles exactos del AC-17:

  | Operación | Roles permitidos |
  |---|---|
  | `POST /api/v1/tickets/{ticket_id}/anulacion` | Solicitante, Administrador |
  | `POST /api/v1/tickets/{ticket_id}/rechazo` | Bodeguero, Administrador |
  | `PUT /api/v1/tickets/{ticket_id}` | Solicitante, Administrador |
  | `GET /api/v1/tickets/{ticket_id}` | los cuatro roles |
  | `GET /api/v1/tickets/{ticket_id}/historial` | los cuatro roles |

  Superadmin queda **fuera de toda escritura** (403) y conserva lectura global de detalle e historial (AC-17/AC-19). Un rol limitado ajeno al ticket recibe **404 idéntico** al inexistente (patrón de ocultamiento vigente).

- **Gating de capacidades de la 012** (`app/core/capacidades.py`, sin tocar la matriz): las 5 operaciones se asocian a capacidades existentes —conjunto cerrado de seis, sin capacidad nueva—. Decisión: anulación y rechazo → `kanban` (son mutaciones del ciclo de vida, la misma familia que `PATCH /estado` y `POST /despacho` que la 012 ya gateó bajo `kanban`); edición, detalle e historial → `tickets` (gestión y consulta del ticket, la familia de `GET /tickets/` y `POST /tickets/`). **Alternativa descartada:** crear una capacidad `ciclo_vida` (rompe el conjunto cerrado de la 012) y asociar todas a `tickets` (dejaría anular/rechazar disponibles con `kanban` deshabilitada, separando mutaciones equivalentes de la misma familia). El gating se aplica con `requiere_capacidad(...)` en cada ruta nueva; `/auth/me` y `/control/*` siguen sin gating.

## 3. Decisiones técnicas (con alternativa descartada)

1. **Tabla de historial vs. columnas en `ticket`.** Se crea la tabla `historial_transicion_ticket` (decisión D-10 de la spec). **Descartado:** añadir `estado_anterior`, `fecha_anulacion`, `motivo_anulacion`… al ticket: una sola fila por ticket no puede representar el ciclo completo (creación → revisión → curso → cierre/anulación con actores distintos) y multiplicaría columnas por cada transición posible.
2. **`GET /tickets/{id}/historial` propio vs. historial embebido en el detalle.** Se crea el endpoint separado (spec §6). **Descartado:** embeberlo en `GET /tickets/{id}`: el detalle se carga siempre y el historial crece de forma independiente; un endpoint aparte permite reconsultar solo el historial tras cada transición (AC-24) sin retraer la cabecera, y mantiene response_models simples.
3. **Motivo validado en el servicio, no en Pydantic.** `TicketMotivo` acepta `motivo: str` sin restricciones de vacío/longitud; el servicio valida no vacío y longitud ≤ 500 y responde **422**. Es imprescindible para el orden 404 → 409 → 422 del AC-7: si Pydantic rechazara el payload, el 422 se dispararía **antes** del handler y ganaría al 404 de un ticket inexistente. **Descartado:** validación en el schema (incumple AC-7 ante problemas simultáneos).
4. **Dos endpoints (`/anulacion`, `/rechazo`) vs. uno genérico con bandera.** Dos operaciones (D-7): conjuntos de roles distintos en la matriz y significado público distinto. **Descartado:** `POST /anulacion` con `tipo=rechazo` (la matriz no podría distinguir los roles sin una operación intermedia, y el contrato público perdería semántica).
5. **Terminales por nombre, no por ordinal.** `ticket_service` resuelve `cerrado` y `anulado` con `_resolver_estado_por_nombre` (casefold, menor `estado_id` ante duplicados) y la regla de flujo deja de usar `indice_actual == len(estados) - 1` como único terminal. El `PATCH /estado` responde **409** con detalle que dirige a `/anulacion` o `/rechazo` si el destino es `Anulado` o el origen es `Anulado` (AC-4), y conserva intactos el orden de validación 404→404→409 y la guarda de cierre reservado al despacho de la 005. **Descartado:** mantener la terminalidad ordinal (con `Anulado` al final del catálogo convertiría a `Cerrado` en no-terminal y habilitaría `Cerrado → Anulado`).
6. **Un solo helper de servicio para anulación y rechazo.** `_cambiar_a_anulado(db, ticket_id, motivo, identidad)` comparte el camino (404 alcance → 409 estado → 422 motivo → escritura atómica de ticket + fila de historial); la distinción de roles vive en la matriz, no en el servicio. **Descartado:** duplicar la lógica en dos funciones.
7. **Edición con `PUT` y reemplazo atómico del conjunto de detalles.** `editar_ticket` valida todo el payload (referencias 404, forma 422) antes de escribir; luego borra los detalles previos e inserta los nuevos y actualiza la cabecera en **una sola transacción** (AC-15). **Descartado:** patch parcial por campo (dejaría cabecera sin detalles ante un fallo a mitad) y `PATCH` con campos parciales (la spec fija payload equivalente al alta).
8. **Alta con `estado_id = Anulado` → 409.** D-11 exige rechazarlo; el 409 ("estado existente pero no elegible para alta") sigue el patrón de conflictos de precondición de la 004/005. **Descartados:** 422 (el estado es válido en forma, inválido en precondición) y 404 (mentiría: el estado existe en el catálogo).
9. **Filas de historial del alta y del despacho.** `crear_ticket` inserta la fila de creación (`estado_origen_id` nulo, destino = estado inicial, actor = identidad autenticada; en invocación directa al servicio sin identidad —no observable por HTTP— usa `ticket.usuario_id`) y `despachar_ticket` inserta su transición en la misma transacción ACID que ya maneja (AC-5/AC-9/AC-11).
10. **KPI del dashboard por nombre exacto.** `_contar_tickets_activos` pasa de excluir `nombre != 'Cerrado'` a `nombre NOT IN ('Cerrado', 'Anulado')`, conservando la semántica de coincidencia exacta documentada en la 009 (AC-22). **Descartado:** excluir también variantes de mayúsculas (rompería la decisión documentada de la 009 de contar `cerrado`/`CERRADO` como activos).
11. **Detalle e historial del Superadmin global vía `global_service.leer_global_unico`.** Mismo patrón que la lectura global de lista: recorre tenants en una transacción `REPEATABLE READ` y devuelve el primer ticket resoluble; un rol limitado usa su única sesión (AC-19).
12. **Sin filas de historial en la semilla.** `02_datos_semilla.sql` añade la fila `Anulado` pero **no** inventa filas de historial para sus tickets QA (AC-12: sin trazabilidad fabricada); el historial vacío de un ticket sembrado ejercita el estado vacío del detalle. **Descartado:** siembra de filas de creación (datos ficticios de trazabilidad, prohibidos por D-10).

## 4. Archivos previstos y responsabilidades

### Base de datos

| Archivo | Responsabilidad | AC |
|---|---|---|
| `database/01_esquema.sql` | `control.historial_transicion_ticket` (PK, FKs locales a `ticket`/`estado_ticket`×2/`usuario`, `motivo VARCHAR(500)`), tras `detalle_ticket`; `estado_ticket` sin cambio de DDL (fila nueva solo en semilla). | AC-9, AC-20 |
| `database/02_datos_semilla.sql` | Quinta fila `(5, 'Anulado', …)` al final del `INSERT` de `estado_ticket` (preserva el orden del flujo de la 003, D-4); la guardia fail-closed suma la tabla nueva a sus canónicas ("16 tablas"); sin filas de historial. | AC-20 |
| `database/03_construir_tenants_011.sql` (constructor vigente) | Plantilla de `historial_transicion_ticket` en `v_plantillas` (se replica a cada tenant); `v_version_objetivo` `012.1` → `013.1`; los tenants ya reciben `Anulado` por el `INSERT … SELECT * FROM control.estado_ticket`. | AC-20, AC-21 |
| `database/migraciones/004_migracion_ciclo_vida_ticket_013.sql` (nuevo) | Migración operacional explícita `012.1 → 013.1`, patrón del bloque único `DO` de la 002/003: preflight (control y tenants en `012.1`, sin estructura 013 parcial), `INSERT` idempotente de `Anulado` (`WHERE NOT EXISTS` por nombre) en control y cada tenant, `CREATE TABLE IF NOT EXISTS historial_transicion_ticket` en control y cada tenant, versión al final y verificación global fail-closed. Sin semilla destructiva, sin DELETE, sin reconstrucción de historial. | AC-20, AC-21 |

### Backend

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/models/ticket.py` | Modelo `HistorialTransicionTicket` (mapeo exacto del DDL; relaciones a `Ticket`, `Usuario`, `EstadoTicket` origen/destino). | AC-9 |
| `backend/app/models/__init__.py` | Exportar el modelo nuevo en el paquete (SQLite/heredado lo crea `Base.metadata`). | AC-9 |
| `backend/app/schemas/ticket_schema.py` | `TicketMotivo` (entrada de anulación/rechazo, sin validación de vacío/longitud — decisión 3), `HistorialTransicionRespuesta`, `TicketEditar` (asunto, descripción, prioridad_id, detalles; sin `usuario_id`), `TicketDetalleRespuesta` si `TicketRespuesta` no basta para el contrato del detalle. | AC-8, AC-10, AC-13 |
| `backend/app/core/permisos.py` | 5 filas nuevas (sección «Feature 013», comentario explícito de aditividad); 44 → 49 operaciones; ninguna fila previa modificada. | AC-17 |
| `backend/app/core/capacidades.py` | 5 asociaciones nuevas (kanban ×2, tickets ×3) en `MAPA_OPERACION_CAPACIDAD`. | AC-1…AC-4, AC-17 |
| `backend/app/core/config.py` | `VERSION_ESQUEMA_OBJETIVO = "013.1"` (comentario actualizado). | AC-20, AC-21 |
| `backend/app/services/ticket_service.py` | `NOMBRE_ESTADO_ANULADO`; terminales por nombre; `_registrar_transicion(...)` (misma transacción que el cambio); filas de creación y de despacho; guards `Anulado` en `actualizar_estado_ticket` (409 dirigiendo a la operación); `anular_ticket`/`rechazar_ticket` sobre `_cambiar_a_anulado` (orden 404→409→422); `editar_ticket` (404→409 `Pendiente`→validación total→reemplazo atómico de detalles); `obtener_ticket_detalle` y `obtener_historial_ticket` con alcance por rol y `leer_global_unico` para Superadmin; rechazo del `estado_id` `Anulado` en `crear_ticket` (409). | AC-1…AC-19 |
| `backend/app/services/dashboard_service.py` | `_contar_tickets_activos` excluye `('Cerrado', 'Anulado')` por nombre exacto. | AC-22 |
| `backend/app/api/v1/endpoints/tickets.py` | 5 rutas nuevas con `response_model`, `status_code`, OpenAPI, `respuestas_de_autorizacion()` + `respuesta_recurso_oculto()` (+ `respuesta_conflicto()` donde aplica), `requiere_operacion` y `requiere_capacidad`; descripción de `PATCH /estado` actualizada con los 409 de `Anulado`. | AC-1…AC-19 |
| `backend/tests/` | Ver §6. | AC-1…AC-22, AC-25 |

### Frontend

| Archivo | Responsabilidad | AC |
|---|---|---|
| `frontend/src/app/shared/interfaces/index.ts` | Tipos nuevos 1:1 con los schemas: `HistorialTransicion`, `TicketEditar` (y `TicketDetalle` si aplica). | AC-23 |
| `frontend/src/app/features/tickets/services/ticket.service.ts` | `obtenerDetalleTicket`, `obtenerHistorial`, `anularTicket`, `rechazarTicket`, `editarTicket`. | AC-23, AC-24 |
| `frontend/src/app/features/tickets/ticket-detalle.component.ts` (+ `.html`, `.spec.ts`) | Vista de detalle standalone (nueva, `frontend-design`): cabecera, ítems con cantidades solicitadas/entregadas, fechas, historial completo; barra de acciones por estado y rol (avanzar/retroceder vía `PATCH /estado`, editar en `Pendiente`, anular/rechazar con modal de confirmación que exige motivo); errores 404/409/422 accesibles (`role="alert"`), anti doble envío y reconsulta tras cada mutación. Signals + `computed()`, Tailwind, `inject()`. | AC-23, AC-24 |
| `frontend/src/app/features/tickets/tickets.routes.ts` | Ruta hija `tickets/:ticketId` con `loadComponent` perezoso. | AC-24 |
| `frontend/src/app/features/tickets/tickets.component.ts` (+ `.html`, `.spec.ts`) | Tablero a solo lectura: se **eliminan** los botones avanzar/retroceder y su lógica (`puedeAvanzar`/`puedeRetroceder`/`estadoAnteriorId`/`estadoSiguienteId`, `errorMovimiento` de transición); cada tarjeta ofrece **Gestionar** → navega al detalle; la columna `Anulado` surge sola del catálogo; se conservan filtros y modal de alta. | AC-24 |
| `frontend/src/app/core/auth/roles.ts` | Helpers de presentación espejo de la matriz (`puedeAnularTicket`, `puedeRechazarTicket`, `puedeEditarTicket`); `ROLES_TICKETS` intacto (Superadmin no navega `/tickets` desde la 012; su lectura global de detalle es solo API). | AC-16, AC-24 |
| `frontend/src/app/features/dashboard/` | Sin cambios: el KPI se corrige en el backend y el componente ya muestra el valor del API. | AC-22 |

### Documentación

| Archivo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Sección de modelo aprobada (§1 de este plan). | AC-20, AC-21 |
| `docs/spec/features/013-ciclo-vida-ticket/spec.md`, `tasks.md`, `roadmap.md`, `MEMORY.md`, `AGENTS.md` (§7) | Al cierre: evidencia por AC, tareas, y el grep de coherencia (§8.7) que actualice el conteo «14 → 15 entidades de dominio» en `AGENTS.md` §7 y `MEMORY.md`. `AGENTS.md` lo edita el coordinador/implementer, no el planner. | AC-25 |

## 5. Estrategia de pruebas

### Backend SQLite (`pytest` ordinario)

- TDD sobre la interfaz HTTP (`TestClient`, patrón del `conftest.py` vigente): primero los tests de los endpoints nuevos y luego la implementación.
- Flujo y estados (AC-1…AC-7): anulación/rechazo desde `Pendiente`/`EnRevision` → 200 con ticket en `Anulado`, `fecha_cierre` nula, stock intacto y fila de historial; 409 desde `EnCurso`/`Cerrado`/`Anulado` sin efectos; guards de `PATCH /estado` hacia/desde `Anulado` (409 literal) y despacho de un `Anulado` (409 de la 005 intacto); alta con `Anulado` → 409.
- Orden de respuestas (AC-7): casos con problemas simultáneos para cada combinación 404/409/422 (motivo vacío y largo ≤ escala).
- Historial (AC-9…AC-12): exactamente una fila por mutación (creación, cambio de estado, despacho, anulación, rechazo), origen nulo solo en la creación, orden `fecha_transicion DESC, historial_transicion_id DESC`, atomicidad (fila y estado juntos), sin endpoints de escritura del historial, ticket legado con historial vacío.
- Edición (AC-13…AC-16): reemplazo completo de detalles, estado/solicitante/sede/institución intactos, 409 fuera de `Pendiente`, validación total sin escritura parcial, 404/403 por rol.
- Autorización (AC-17…AC-19): matriz por operación (los 5 roles exactos; Superadmin 403 en escritura), 404 idéntico inexistente/ajeno, `/openapi.json` con las 49 operaciones, 401/403/404/409/422 documentados y aserción de no-modificación de las 44 filas previas.
- KPI (AC-22): anulado no cuenta como activo para ningún rol; resto de KPI intacto.
- Gating (012): capacidad `kanban`/`tickets` apagada → 403 sin mutación en las 5 operaciones nuevas.

### PostgreSQL gated (`POSTGRES_TEST_URL`, obligatorio para cierre)

- Nuevo módulo `tests/test_ciclo_vida_ticket_postgres_013.py` con el patrón de los gated de 011/012 (`skip` sin la variable):
  - **Migración `012.1 → 013.1`** sobre una base construida con el mismo harness de la 012 (cadena `01 → 02 → 03` + migraciones `001`–`003` hasta `012.1`, aspecto real de una instalación existente): `Anulado` presente en control y cada tenant, tabla creada, datos/mapas/historial previo intactos, segunda ejecución sin cambios, fallo de preflight sin versión parcial.
  - **Constructor/initdb** (`01 → 02 → 03` recién levantado): tenants nacen en `013.1` con `Anulado` replicado y la tabla creada.
  - **Token de versión:** un tenant en `012.1` (sin los cambios 013) **deniega cerrado** en el routing con el objetivo `013.1`, y solo se enrutan tenants exactamente en `013.1` (AC-21).
- Actualizar los tests que fijan el literal `012.1` como objetivo vigente (`test_control_modelo_010.py`, `api/test_control_instituciones_010.py`, `_soporte_sede_011.py`, `api/test_capacidades_gating_012.py`, `test_aprovisionamiento_postgres_010.py`, `test_gestion_administrativa_postgres_012.py`): preferir importar `VERSION_ESQUEMA_OBJETIVO` en vez de repetir el literal. El test gated de la migración 012 conserva su propio objetivo `012.1` como fase de la cadena; revisar que ninguna aserción exija enrutar a `012.1` con el nuevo objetivo.

### Frontend

- `npx ng test --watch=false --browsers=ChromeHeadless` con `$env:CHROME_BIN` apuntando a Edge (AGENTS §5; nunca `npm test`).
- Actualizar `tickets.component.spec.ts` (tablero sin controles de transición, acción Gestionar, columna `Anulado`) y crear `ticket-detalle.component.spec.ts` (render por estado/rol, estados vacíos, mensajes `role="alert"` en 404/409/422, confirmación con motivo obligatorio, sin doble envío).
- `ng build` de producción limpio. Sin paquetes nuevos.

### Recorridos de cierre (AC-25)

`pytest` ordinario en verde; suite gated con `POSTGRES_TEST_URL` en verde; `ng test` y `ng build`; inspección de `/openapi.json`; recorrido funcional en 4200 con escritura real (alta → anulación con motivo → detalle con historial → edición → rechazo, más regresión de despacho); `docker compose -f docker-compose.yml build frontend` + `up -d frontend` y humo en 8080. Evidencia y cierre conforme a `AGENTS.md` §8.5–§8.7 (incluido el grep de coherencia que actualice `AGENTS.md` §7 y `MEMORY.md`).

## 6. Riesgos y cobertura spec → plan

| Riesgo | Mitación |
|---|---|
| La terminalidad ordinal vigente convierte `Cerrado` en no-terminal al añadir `Anulado` | Decisión 5: terminales por nombre en `actualizar_estado_ticket`; tests de 409 `Cerrado → Anulado` y de regresión del flujo 004. |
| El 422 de Pydantic se adelanta al 404/409 (AC-7) | Decisión 3: motivo validado en servicio; test con problema simultáneo. |
| Migración deja `Anulado` o la tabla a medias por tenant | Bloque único `DO` + verificación global + gated de reejecución y de fallo inyectado (patrón 002/003). |
| Bump de versión rompe tests gated previos que fijan `012.1` | Actualizar literales/import; revisar el test de la migración 012 dentro de la cadena. |
| El tablero hereda lógica muerta de transiciones al quitar botones | Eliminar señales y métodos obsoletos junto con los botones; spec del componente actualizada. |
| UI de 8080 desactualizada | Rebuild obligatorio antes del humo (AGENTS §5/§8.6). |

| AC | Partes |
|---|---|
| AC-1, AC-2, AC-3 | `ticket_service` (anulación/rechazo), endpoints, permisos/capacidades, tests de flujo. |
| AC-4, AC-5, AC-6, AC-7 | Guards de `PATCH /estado` y despacho, terminales por nombre, orden de respuestas, tests. |
| AC-8 | `TicketMotivo` + validación en servicio (decisión 3), tests 422. |
| AC-9…AC-12 | Modelo/tabla, `_registrar_transicion`, semilla/migración sin filas inventadas, tests de historial. |
| AC-13…AC-16 | `editar_ticket` + `TicketEditar`, alcance por rol, tests de edición. |
| AC-17…AC-19 | `permisos.py` (49 operaciones), `capacidades.py`, OpenAPI, ocultamiento 404, `leer_global_unico`. |
| AC-20, AC-21 | `01_esquema.sql`, `02_datos_semilla.sql`, constructor, migración `004_…013.sql`, `config.py`, gated. |
| AC-22 | `dashboard_service._contar_tickets_activos`, tests de KPI. |
| AC-23, AC-24 | Componente de detalle, tablero a solo lectura, rutas, `ticket.service.ts`, `roles.ts`, specs Angular. |
| AC-25 | Suites completas, build y recorridos en 4200/8080, evidencia y grep de coherencia. |

## 7. Condición de bloqueo

No iniciar ninguna tarea de modelos, schemas, DDL, semilla, constructor, migración ni `VERSION_ESQUEMA_OBJETIVO` hasta la aprobación del apartado de `stack.md` (§1). Si la implementación revela una contradicción real con la spec aprobada —p. ej. un contrato de códigos imposible de satisfacer con el orden 404→409→422, o un rol que la matriz no puede representar—, se detiene la tarea y se eleva el hallazgo al coordinador; no se amplía la spec ni se corrige el código de forma implícita. El `tasks.md` de la 013 se genera en la fase posterior, con tareas en orden de dependencia ancladas a este plan.
