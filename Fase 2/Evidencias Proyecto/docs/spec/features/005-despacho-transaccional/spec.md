# Feature 005: Despacho transaccional con rebaja de stock y auditoría

**Estado:** aprobada
**Release:** 1.0 — Sprint 2
**Tipo:** Valor de negocio (cierre operativo del ciclo de abastecimiento)

## 1. Problema

El tablero de la Feature 004 permite seguir y transicionar tickets, pero aún no realiza la
operación física que da sentido al flujo: descontar existencias al entregar los insumos.
Existe un registro manual de movimientos, pero no está ligado al ciclo del ticket. Sin un
despacho atómico, el stock puede cambiar sin dejar auditoría correlacionada o el ticket
puede quedar cerrado aunque la salida de inventario haya fallado.

El esquema vigente registra cada movimiento contra una fila de inventario, pero no persiste
la referencia al ticket ni al usuario que despacha. Asimismo, un producto puede tener
inventario en más de un departamento; la regla de asignación de stock debe ser inequívoca
para mantener la trazabilidad sin alterar el modelo aprobado.

## 2. Objetivo

Permitir que el bodeguero despache un ticket aprobado en preparación mediante una operación
completa y atómica: rebajar el inventario correspondiente por cada ítem, actualizar las
cantidades entregadas, cerrar el ticket y registrar una salida auditable por ítem. El actor
se valida en la solicitud, pero el esquema actual no persiste su identidad en el movimiento.
La feature también expone la consulta del historial de movimientos.

## 3. Alcance

### Dentro

- Endpoint para despachar un ticket completo, con `usuario_id` explícito y validado porque
  la autenticación sigue siendo decorativa; esto no implica persistir autoría en el historial.
  *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
  (Clerk) y la autorización por roles se implementó en la Feature 007.*
- Elegibilidad restringida al estado cuyo nombre canónico es `EnCurso`, ignorando
  mayúsculas/minúsculas. El despacho lleva el ticket directamente al estado cuyo nombre es
  `Cerrado`, también resuelto por nombre y sin ids fijos. Si hay nombres duplicados en el
  catálogo, gana el de menor `estado_id`, igual que en la regla de la Feature 004; ese mismo
  estado `Cerrado` es el destino protegido contra el PATCH manual.
- El despacho es completo; ticket sin detalles, estado no elegible, ticket ya cerrado,
  falta de stock o inventario ausente/ambiguo se rechazan sin efectos.
- Rebaja por cada producto solicitado, actualización de `cantidad_entregada`, cierre del
  ticket y registro de movimientos `SALIDA` en una única transacción ACID.
- Protección frente a despachos concurrentes del mismo ticket: solo una operación puede
  cerrar/despachar el ticket; la competidora recibe conflicto y no crea salidas duplicadas.
- Restricción operativa de una sola fila de inventario por producto para que el registro de
  salida sea inequívoco sin modificar el modelo. Si existe más de una, el despacho se
  rechaza sin efectos.
- Observación determinista por ítem: `Despacho ticket_id={ticket_id}; detalle_id={detalle_ticket_id}; producto_id={producto_id}`.
  El formato cabe en `VARCHAR(250)` para los identificadores enteros del esquema.
- `GET /api/v1/inventario/movimientos` para consultar movimientos ordenados de forma
  determinista, incluyendo los datos asociados de producto, departamento y ubicación.
- Cambio del `PATCH /api/v1/tickets/{ticket_id}/estado` de la Feature 004: rechazar con 409
  la transición que llevaría de `EnCurso` a `Cerrado`, con mensaje que dirija al endpoint
  de despacho.
- Cambio mínimo en el Kanban: no ofrecer el botón de avanzar desde la columna `EnCurso`
  hacia `Cerrado`; las demás transiciones válidas se conservan.
- Mensajes identificables para referencias inexistentes, estado no elegible, stock
  insuficiente, ticket sin detalles, inventario ausente/ambiguo y despacho concurrente.
- Conservación del endpoint manual `POST /api/v1/inventario/movimientos`; sus contratos y
  comportamiento existente no se amplían en esta especificación.

### Fuera

- Despacho parcial o selección de cantidades menores a las solicitadas.
- Asignación del despacho entre múltiples sedes/departamentos. Se requiere una sola fila de
  inventario para cada producto del ticket.
- Autenticación real, autorización por rol o derivación automática del bodeguero desde una
  sesión; corresponden a las Features 006/007.
- Cambios a las doce entidades, tablas o columnas vigentes. `movimiento_inventario` no
  incorpora una columna de actor ni una FK al ticket; por ello el historial no demuestra
  quién ejecutó la operación.
- Una interfaz de historial, filtros/paginación del historial o edición/borrado de sus
  registros. El frontend incluido se limita a ocultar la transición manual de cierre.
- Cambios ajenos a la transición `EnCurso→Cerrado` en el Kanban de la Feature 004.

## 4. Decisiones

### D-1 — Solo se despacha desde `EnCurso` y se cierra en `Cerrado`

`EnCurso` representa el ticket aprobado que está en preparación; `Cerrado` es el estado
terminal del catálogo canónico. El despacho lleva al ticket de uno a otro. La transición
manual equivalente del endpoint de estado y el botón correspondiente del Kanban quedan
reservados/bloqueados para exigir que el cierre incluya rebaja y auditoría atómicas,
como exige la Constitución §3. Ambos estados se buscan por nombre, sin ids fijos. Si el
nombre está duplicado, se utiliza el estado de menor `estado_id` (Feature 004, D-3).

### D-2 — El despacho es completo, no parcial

La solicitud no incluye cantidades modificables: por cada detalle se entrega exactamente
`cantidad_solicitada`. Esto mantiene alineados solicitud, cantidad entregada, salida de
stock y cierre, sin introducir un estado intermedio que el modelo no representa.

### D-3 — Una insuficiencia cancela todo el despacho

Si cualquier ítem carece de stock suficiente, la operación se rechaza como conflicto y no
modifica ningún detalle, inventario, movimiento, estado ni fecha. Una entrega parcial
requeriría definir cómo reintentar el saldo y representar tickets abiertos, fuera del flujo.

### D-4 — El actor se valida, pero no se atribuye en el registro persistido

El payload incluye `usuario_id` porque no existe una sesión real de la que derivarlo. El
usuario debe existir, pero no se valida su rol, lo que corresponde a 006/007. El identificador
no se persiste en `movimiento_inventario`: no debe presentarse como autoría auditable.

### D-5 — Una única fila de inventario por producto es requisito de despacho

La tabla permite varias filas por producto, una por departamento, pero la solicitud no
identifica desde qué departamento se prepara el pedido ni cómo repartir la salida. Para no
elegir una sede arbitrariamente, se requiere exactamente una fila por producto. Cero o más
de una producen 409 sin escritura. Se descarta repartir en orden determinista porque
inventaría una política de abastecimiento por sedes no aprobada.

### D-6 — Observación estable y acotada para cada detalle

Cada salida usa exactamente el patrón
`Despacho ticket_id={ticket_id}; detalle_id={detalle_ticket_id}; producto_id={producto_id}`.
Solo contiene ids enteros y etiquetas fijas, por lo que cabe holgadamente en los 250
caracteres de la columna y permite aserción literal. No se amplía el esquema.

### D-7 — Cada detalle produce su propio movimiento de salida

Por cada fila de `detalle_ticket` se crea un movimiento `SALIDA` con la cantidad solicitada y
la fila única de inventario del producto. Si hay varias líneas del mismo producto, se valida
el total conjunto antes de escribir y se mantiene un movimiento por detalle.

### D-8 — El historial es una lectura del registro persistido

`GET /inventario/movimientos` devuelve una lista ordenada por fecha descendente y, ante
empate, por identificador descendente. No recalcula ni edita registros; incluye la
información relacionada que permite interpretar cada movimiento.

### D-9 — Serialización del despacho por bloqueo del ticket

La operación bloquea la fila del ticket para escritura al iniciar la transacción. La
validación del estado elegible ocurre después de adquirir el bloqueo; una segunda petición
concurrente espera y, tras el commit de la primera, observa `Cerrado` y responde 409 sin
crear movimientos. Se elige el bloqueo de fila transaccional frente a una comprobación
optimista sin bloqueo porque serializa explícitamente las operaciones del mismo ticket y
permite que todas las escrituras relacionadas permanezcan en una sola transacción.

### D-10 — Ticket sin detalles no se puede cerrar

Un ticket sin líneas se rechaza con 409 antes de cualquier escritura. Cerrarlo sin una salida
de stock contradiría la regla observable de que un despacho exitoso cierra el ticket con
movimientos correspondientes.

### D-11 — Producto inexistente es una referencia inválida, no un caso de stock

El DDL declara FK `detalle_ticket.producto_id → producto.producto_id` sin `ON DELETE
CASCADE` ni otra acción de borrado; el valor por defecto impide eliminar un producto
referenciado. En operación normal, cada detalle persistido apunta a un producto existente.
Si una inconsistencia o corrupción permite que no se resuelva, se rechaza con 409 sin
escrituras (conflicto de integridad), no 404: el cliente no está aportando una nueva
referencia de producto, sino despachando un detalle ya persistido.

### D-12 — La ruta PATCH identifica el estado solicitado por el catálogo

La prohibición del cierre manual se aplica cuando el estado solicitado corresponde al
`Cerrado` canónico (menor `estado_id` si está duplicado) y el ticket está en el `EnCurso`
canónico. No basta con que el destino sea el último estado ordinal: en un catálogo
degenerado eso podría impedir una transición que no sea el cierre de negocio.

## Impacto en la Feature 004

La decisión de reservar `EnCurso→Cerrado` deroga parcialmente la transición general descrita
por la 004. El override es necesario para que ningún cierre evite la rebaja y la auditoría
atómicas exigidas por la Constitución §3. La 005 modifica el `PATCH` de estado (409 con
referencia al despacho), el test de la 004 que permite avanzar manualmente de `EnCurso` a
`Cerrado` y el botón de avanzar del Kanban en la columna `EnCurso`; el cierre solo se logra
mediante el endpoint de despacho.

## 5. Contrato de la API

### `POST /api/v1/tickets/{ticket_id}/despacho`

`response_model=TicketRespuesta` (DTO existente) · `status_code=200` · respuesta con el
ticket actualizado y sus detalles; queda en `Cerrado`, con fecha de cierre no nula y cada
`cantidad_entregada` igual a `cantidad_solicitada`.

Payload:

```json
{
  "usuario_id": 6
}
```

Respuestas de error contractuales:

- `404`: ticket inexistente; o `usuario_id` inexistente.
- `409`: transición manual `EnCurso→Cerrado` (detalle dirige a
  `POST /tickets/{ticket_id}/despacho`); ticket en estado no elegible/ya despachado; catálogo
  sin los nombres requeridos; ticket sin detalles; detalle sin producto resoluble; inventario
  ausente/ambiguo; stock insuficiente; despacho concurrente ya completado.
- `422`: payload inválido o `usuario_id` ausente/no entero.

Orden de validación: bloqueo y existencia del ticket, actor, estados y elegibilidad, detalles
no vacíos, productos e inventarios, suficiencia total de stock; luego se realizan las
escrituras y se confirma una sola transacción. Ninguna validación de negocio posterior a una
escritura puede dejar efectos parciales. Dos llamadas superpuestas se serializan en el
bloqueo; la segunda revalida el estado después del commit inicial y responde 409, dejando un
solo despacho.

### `PATCH /api/v1/tickets/{ticket_id}/estado` — restricción incorporada desde 004

Conserva `response_model=TicketRespuesta` y `status_code=200` para transiciones permitidas.
Si una petición manual desde `EnCurso` solicita el estado `Cerrado`, responde `409` sin
modificar estado ni fecha, con el detalle exacto `El cierre requiere despacho; use
POST /api/v1/tickets/{ticket_id}/despacho`. El estado de cierre se resuelve por nombre,
incluyendo duplicados resueltos por menor `estado_id`.

### `GET /api/v1/inventario/movimientos`

`response_model=list[MovimientoInventarioRespuesta]` (DTO nuevo) · `status_code=200` · lista,
incluso vacía, de movimientos con `movimiento_id`, `tipo_movimiento`, `cantidad`,
`fecha_movimiento`, `observacion`, `inventario_id`, `producto_id`, nombre del producto,
`departamento_id`, nombre del departamento y `ubicacion`.

Orden: `fecha_movimiento` descendente y `movimiento_id` descendente. Sin paginación ni
filtros en esta entrega.

## 6. Criterios de aceptación

### Despacho y consistencia

- [x] **AC-1** DADO QUE el ticket existe, su estado corresponde por nombre a `EnCurso`, tiene
      detalles y el payload contiene un usuario existente, CUANDO se solicita el despacho,
      ENTONCES responde 200 con el ticket en `Cerrado`, fecha de cierre no nula y todos sus
      detalles con `cantidad_entregada = cantidad_solicitada`.
- [x] **AC-2** DADO QUE el despacho se acepta, ENTONCES por cada detalle se rebaja exactamente
      la cantidad solicitada de su inventario único y se crea una salida `SALIDA` de esa
      cantidad. La observación es exactamente
      `Despacho ticket_id={ticket_id}; detalle_id={detalle_ticket_id}; producto_id={producto_id}`
      con los valores persistidos, y el movimiento apunta al `inventario_id` correspondiente.
- [x] **AC-3** DADO QUE un ticket contiene varias líneas del mismo producto, ENTONCES el
      sistema valida el stock total requerido por todas ellas antes de escribir y crea un
      movimiento por línea, sin permitir stock negativo.
- [x] **AC-4** SI falta stock para al menos un producto, ENTONCES responde 409 y no cambia
      ningún stock, cantidad entregada, movimiento, estado o fecha de cierre, incluidos los
      ítems que sí tenían stock.
- [x] **AC-5** SI el ticket no existe, ENTONCES responde 404 y no produce modificación alguna.
- [x] **AC-6** SI el `usuario_id` enviado no existe, ENTONCES responde 404 y no produce
      modificación alguna.
- [x] **AC-7** SI el ticket no está en `EnCurso`, ya está en `Cerrado` o ya fue despachado,
      ENTONCES responde 409 y no duplica movimientos ni modifica ticket o inventario.
- [x] **AC-8** Los estados se resuelven por nombre sin distinguir mayúsculas. Si falta uno
      de los nombres `EnCurso` o `Cerrado`, responde 409 sin cambios; si alguno está
      duplicado, usa el de menor `estado_id`, conforme a la 004. Ningún id fijo gobierna la
      regla.
- [x] **AC-9** SI un producto de los detalles no tiene fila de inventario o tiene más de una,
      ENTONCES responde 409 identificando el caso y no escribe cambios.
- [x] **AC-10** SI el ticket no contiene detalles, ENTONCES responde 409 sin modificar estado,
      fecha, inventario ni movimientos.
- [x] **AC-11** DADO QUE falla cualquier escritura o confirmación, ENTONCES se revierten en
      conjunto rebajas, movimientos, cantidades entregadas, estado y fecha; no quedan efectos
      parciales.
- [x] **AC-12** DADO QUE llegan concurrentemente dos solicitudes de despacho del mismo
      ticket, ENTONCES exactamente una responde 200 y la otra 409; queda un único cierre y
      solo un juego de movimientos, sin doble rebaja (D-9).
- [x] **AC-13** El payload exige un `usuario_id` entero existente (si no existe, aplica AC-6).
      El esquema de `movimiento_inventario` no incorpora columna de actor: esto se verifica
      contra el DDL/modelo, y la respuesta/historial no afirma autoría persistida.
- [x] **AC-14** Si el producto de un detalle persistido no se puede resolver, responde 409
      como conflicto de integridad, no 404; no modifica ningún dato (D-11).

### Transición manual y Kanban

- [x] **AC-15** SI `PATCH /tickets/{ticket_id}/estado` solicita la transición manual desde
      el `EnCurso` canónico hacia el `Cerrado` canónico, ENTONCES responde 409, mantiene
      estado/fecha y devuelve el detalle exacto `El cierre requiere despacho; use
      POST /api/v1/tickets/{ticket_id}/despacho`. Ambos estados se resuelven por nombre,
      aplicando menor `estado_id` ante duplicados; las demás transiciones válidas conservan
      su comportamiento.
- [x] **AC-16** En el Kanban, una tarjeta en el `EnCurso` canónico no ofrece el control de
      avanzar hacia el `Cerrado` canónico; conserva la opción de retroceder y el resto de
      columnas mantiene los controles válidos de la 004. Ante duplicados de nombres, se
      aplican las mismas resoluciones por menor `estado_id`.

### Historial de movimientos y contratos

- [x] **AC-17** `GET /api/v1/inventario/movimientos` responde 200 con lista vacía cuando no
      hay movimientos.
- [x] **AC-18** Cada elemento de `GET /api/v1/inventario/movimientos` incluye todos los
      campos de movimiento e información relacionada definidos en §5.
- [x] **AC-19** El historial se ordena por fecha descendente y desempate por
      `movimiento_id` descendente, de forma determinista.
- [x] **AC-20** Cada salida de despacho aparece en el historial como `SALIDA`, con cantidad,
      observación literal definida en D-6 y destino de inventario esperados; la API no ofrece
      modificación ni borrado del historial.
- [x] **AC-21** `/openapi.json` documenta despacho, transición de estado e historial con
      `response_model`, `status_code` explícito, resumen y respuestas de error relevantes.
- [x] **AC-22** La ruta existente `POST /inventario/movimientos` conserva contrato y
      comportamiento previos.

### Verificación

- [x] **AC-23** `pytest` queda verde y cubre despacho exitoso, insuficiencia con rollback
      total, estados no elegibles/duplicados/ausentes, referencias inválidas, ticket sin
      detalles, inventario ausente/ambiguo, producto no resoluble, concurrencia, orden e
      integración del historial.
- [x] **AC-24** El despacho y su historial se verifican contra PostgreSQL 16 real, confirmando
      mediante lectura persistida rebaja, movimientos, cantidades entregadas y cierre.
- [x] **AC-25** El frontend compila y `ng test` queda verde, incluyendo que no se ofrezca el
      cierre manual desde `EnCurso` y que el resto de las transiciones del Kanban siga
      funcionando.
- [x] **AC-26** El flujo se recorre en 4200 contra el backend real: despacho exitoso con
      cambios persistidos y rechazo del cierre manual sin despacho. También se recorre en
      8080 tras `docker compose -f docker-compose.yml build frontend` y
      `docker compose -f docker-compose.yml up -d --force-recreate frontend`, verificando de
      humo que el Kanban ya no ofrece el cierre manual y el flujo básico responde
      (`AGENTS.md` §8.5-§8.6).
- [x] **AC-27** No se modifican las doce entidades ni `database/01_esquema.sql`; no se agregan
      dependencias, se mantiene la autenticación decorativa y la lógica de negocio permanece
      fuera de los routers.
      *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
      (Clerk) y la autorización por roles se implementó en la Feature 007.*
- [x] **AC-28** `roadmap.md` y `MEMORY.md` se actualizan al cierre solo después de todos los AC
      verificados; no se marca la feature cerrada antes de esa evidencia.

### Evidencia de verificación al cierre

| AC | Evidencia |
|---|---|
| AC-1 | `test_despacho_cierra_el_ticket_con_fecha_y_entregas_completas` (`test_despacho_transaccional.py`, T2/T3); PostgreSQL real T12: ticket 21 → estado `Cerrado` (id 4), `fecha_cierre` no nula y entrega `4/4`. |
| AC-2 | `test_despacho_rebaja_el_stock_del_inventario_unico` y `test_despacho_registra_una_salida_con_observacion_literal` (T3); T12: stock `10→6` y una `SALIDA` de 4 con observación literal D-6 apuntando al `inventario_id` único. |
| AC-3 | `test_despacho_de_dos_lineas_del_mismo_producto_suma_stock_y_deja_una_por_linea` y `test_despacho_rechaza_el_agregado_insuficiente_sin_efectos` (T3). |
| AC-4 | `test_despacho_rechaza_stock_insuficiente_sin_efectos` y `test_despacho_no_deja_efectos_parciales_si_un_producto_anterior_si_tenia_stock` (T4), con el helper `verificar_sin_efectos` (estado, fecha, entregas, stock y ausencia de movimientos). |
| AC-5 | `test_despacho_de_ticket_inexistente_responde_404_sin_efectos` (T4). |
| AC-6 | `test_despacho_con_usuario_inexistente_responde_404_sin_efectos` (T4). |
| AC-7 | `test_despacho_rechaza_estado_no_elegible_sin_efectos` y `test_redespachar_un_ticket_cerrado_responde_409_sin_duplicar` (T4). |
| AC-8 | `test_despacho_sin_en_curso_en_el_catalogo_responde_409...`, `...sin_cerrado...`, `...en_curso_duplicado_usa_el_de_menor_id`, `...cerrado_duplicado_cierra_en_el_de_menor_id` y `...resuelve_los_nombres_sin_distinguir_mayusculas` (T4). |
| AC-9 | `test_despacho_rechaza_producto_sin_fila_de_inventario` y `test_despacho_rechaza_producto_con_dos_filas_de_inventario` (T4). |
| AC-10 | `test_despacho_de_ticket_sin_detalles_responde_409_sin_efectos` (T4). |
| AC-11 | `test_despacho_revierte_todo_si_el_commit_falla` (T4): fallo inyectado en `Session.commit` tras mutar → 500 y estado persistido íntegro (sin rebajas, entregas, cierre ni movimientos). |
| AC-12 | T12 con PostgreSQL 16.14 real: dos sesiones independientes sincronizadas sobre `FOR UPDATE` → `(200, ticket 22)` y `(409, "El ticket no esta en 'EnCurso'...")`, un único `SALIDA` y stock `10→6`. La suite SQLite no es evidencia de `FOR UPDATE`. |
| AC-13 | `test_despacho_sin_payload_responde_422` y `test_despacho_con_usuario_id_no_entero_responde_422` (T2), más los DTO de T1 (`test_despacho_dtos.py`); `git diff` sin cambios a `backend/app/models/` ni a `database/01_esquema.sql` confirman que `movimiento_inventario` no tiene columna de actor. |
| AC-14 | `test_despacho_rechaza_detalle_con_producto_no_resoluble` (T4), con `producto_id` huérfano inyectado bajo `PRAGMA foreign_keys=OFF`: 409 de integridad, no 404. |
| AC-15 | Guardia en `ticket_service.actualizar_estado_ticket()` (T6); tests `test_avanzar_a_cerrado_esta_reservado_al_despacho`, `test_el_cierre_manual_con_cerrado_duplicado_usa_el_de_menor_id`, `test_el_cierre_reservado_no_depende_del_id_del_estado` y `test_una_transicion_no_reservada_desde_en_curso_sigue_siendo_200` (T6), más `test_el_contrato_del_patch_documenta_el_cierre_reservado` (T11); recorrido 4200 T13: `PATCH /tickets/5/estado` → 409 con el detalle literal y estado/fecha sin cambios. |
| AC-16 | `tickets.component.spec.ts` §`regla de despacho: sin avance desde EnCurso (AC-16)` (6 casos, T10: sin avanzar, con retroceso, sin PATCH, demás columnas intactas, minúsculas y duplicado por menor id); recorrido T13 en 4200 y 8080: la tarjeta en `EnCurso` muestra solo "Retroceder". |
| AC-17 | `test_historial_sin_movimientos_devuelve_lista_vacia` (T7). |
| AC-18 | `test_historial_expone_los_campos_asociados_del_movimiento` (T7) y `test_movimiento_inventario_respuesta_expone_todos_los_campos_del_contrato` (T1). |
| AC-19 | `test_historial_ordena_por_fecha_desc_y_desempata_por_id_desc` (T7), con dos filas sembradas con la MISMA fecha para forzar el desempate por `movimiento_id`. |
| AC-20 | `test_la_salida_de_un_despacho_aparece_en_el_historial` (observación literal D-6 y destino), `test_el_historial_solo_declara_lectura_en_el_contrato` y `test_el_historial_rechaza_verbos_de_mutacion_por_http` (T7). |
| AC-21 | `test_openapi_declara_el_contrato_del_despacho` y `test_openapi_declara_la_respuesta_200_explicita` (T5); `test_openapi_del_historial_declara_el_200_el_read_model_y_el_orden` y `test_el_contrato_del_patch_documenta_el_cierre_reservado` (T11). Los códigos de error se documentan en la `description`, como en la 004. |
| AC-22 | `test_openapi_del_registro_manual_conserva_201_y_su_payload` (T11); el `POST /inventario/movimientos` de la 002 conserva su `201` y su contrato sin cambios. |
| AC-23 | `cd backend && .venv\Scripts\python.exe -m pytest` → **140 passed, 1 warning** (T11, re-ejecutado en el cierre T14). |
| AC-24 | T12: PostgreSQL 16.14 real; lectura persistida de stock, detalle, ticket y movimientos de los tickets 21 y 22, con datos de prueba borrados al terminar. |
| AC-25 | `ng test --watch=false --browsers=ChromeHeadless` → **TOTAL: 69 SUCCESS** (T10/T13, re-ejecutado en el cierre T14); `npx ng build` de producción compila. |
| AC-26 | T13: recorrido funcional en 4200 (ticket #23 despachado con persistencia verificada por SQL; PATCH manual rechazado sin cambios) y recorrido de humo en 8080 tras `build frontend` y `up -d --force-recreate` (imagen nueva `0af582ff27ce`). |
| AC-27 | `git diff` del cierre: vacío sobre `backend/app/models/`, `database/01_esquema.sql`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `frontend/package.json` y `backend/app/core/security.py`; los endpoints de despacho e historial solo delegan en `ticket_service`/`inventario_service` (cero lógica de negocio en routers). Ver "Verificación de cierre (T14)". |
| AC-28 | `roadmap.md` fila 005 → `[x]` y `MEMORY.md` actualizado, solo tras evidenciar AC-1…AC-27. Ver "Verificación de cierre (T14)". |

### Verificación de cierre (T14)

- **Suites (re-ejecutadas):** backend `140 passed, 1 warning`; frontend `TOTAL: 69 SUCCESS`; build de producción OK.
- **Restricciones (AC-27):** `git status`/`git diff` del cambio de la 005 toca únicamente
  `backend/app/schemas/{ticket,inventario}_schema.py`,
  `backend/app/services/{ticket,inventario}_service.py`,
  `backend/app/api/v1/endpoints/{tickets,inventario}.py` (solo rutas que delegan),
  los tests de API del backend, el componente/spec de `tickets` y documentación.
  Sin cambios a modelos, `database/01_esquema.sql`, semilla, dependencias ni
   `backend/app/core/security.py`; autenticación decorativa intacta.
   *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
   (Clerk) y la autorización por roles se implementó en la Feature 007.*
- **Coherencia documental (AGENTS.md §8.7):** `grep` sobre `AGENTS.md`, `MEMORY.md` y
  `.agents/skills/` no deja rutas ni estados falsos; ninguna skill describe el `PATCH` de
  la 004 como capaz de cerrar manualmente. Las rutas nuevas
  `POST /api/v1/tickets/{ticket_id}/despacho` y `GET /api/v1/inventario/movimientos`
  quedan citadas aquí y en `MEMORY.md`. Los archivos citados existen.
- **Autoría:** la evidencia no afirma autoría persistida del actor; el `usuario_id` se
  valida en la petición pero no se escribe en `movimiento_inventario` (no existe tal
  columna).

## 7. Restricciones

- `constitucion.md` §3: rebajas de stock, movimientos, cantidades entregadas y estado/fecha
  del ticket forman una sola transacción ACID.
- `constitucion.md` §2: todo cambio de stock producido por despacho requiere movimiento de
  auditoría en la misma transacción.
- `AGENTS.md` §6: identificadores en español, rutas con `response_model` y `status_code`
  explícitos, reglas de negocio en servicios, sesión inyectada y sin SQL raw.
- `AGENTS.md` §7 y `stack.md`: sin cambios al modelo de 12 entidades ni al DDL; autenticación
  decorativa hasta 006/007 y sin dependencias nuevas.
  *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
  (Clerk) y la autorización por roles se implementó en la Feature 007.*
- La unicidad de inventario por producto es un requisito de operación del despacho, no una
  nueva restricción de esquema. La base solo garantiza unicidad por pareja departamento/
  producto, de modo que los casos sin fila o con varias filas se rechazan explícitamente.
- El usuario actor se valida al momento de la petición, pero no puede quedar asociado
  estructuralmente al movimiento con el esquema actual. Ni la respuesta ni el historial
  deben afirmar autoría persistida.
- El último paso ordinal de la 004, desde `EnCurso` a `Cerrado`, queda reservado al despacho:
  PATCH responde 409 y el Kanban no lo ofrece manualmente.
- Los tickets sin detalles se rechazan para que ningún cierre exitoso carezca de movimientos
  y rebajas correspondientes.
- En la verificación de la parte frontend se exige recorrido funcional en 4200 y humo en
  8080 después de reconstruir y recrear la imagen; 8080 no refleja cambios automáticamente.
