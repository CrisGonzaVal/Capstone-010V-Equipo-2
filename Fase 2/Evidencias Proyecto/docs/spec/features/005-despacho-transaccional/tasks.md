# Feature 005 — Tasks

**Spec:** [`spec.md`](spec.md) · **Plan:** [`plan.md`](plan.md)

14 tareas en orden de dependencia; cada tarea está diseñada para ejecutarse por separado. Las tareas de comportamiento siguen TDD: test observable primero, implementación después. No se debe marcar una casilla sin cumplir su `Hecho cuando:` y dejar evidencia concreta.

Leyenda: `[ ]` pendiente · `[x]` hecha y verificada · `[!]` bloqueada (motivo en la línea).

Verificación habitual:
- Backend: `cd backend && .venv\Scripts\python.exe -m pytest`
- Frontend: `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`

---

## T1 — DTO de solicitud y DTO del historial (AC-13, AC-17…AC-21)

- [x] Añadir el modelo de payload con `usuario_id: int` en `ticket_schema.py` y el read model `MovimientoInventarioRespuesta` con todos los campos del contrato en `inventario_schema.py`. El DTO de historial es un mapping de consulta, no una entidad ORM con `from_attributes`.

**Hecho cuando:** se importan ambos DTOs sin error; una validación unitaria/HTTP prueba el `usuario_id` entero requerido y el shape del DTO contiene todos los campos de §5; `pytest` no tiene fallos de colección.

> Evidencia: `TicketDespacho` (`usuario_id: int` requerido) y `MovimientoInventarioRespuesta` (sin `from_attributes`) en `app/schemas/`. `backend/tests/api/test_despacho_dtos.py`: 7 pruebas (usuario_id entero requerido, rechazo de ausente/nulo/no entero, shape exacto §5, read model sin `from_attributes`, instancia con los 11 campos). `pytest` completo: 102 passed.

## T2 — Tests rojos del despacho exitoso y stock por producto (AC-1…AC-3, AC-13)

- [x] Crear `test_despacho_transaccional.py` con fixture de catálogo canónico `Pendiente → EnRevision → EnCurso → Cerrado`, helpers de alta/mover a `EnCurso` y pruebas HTTP rojas para despacho simple: ticket cerrado/fecha, cantidades entregadas, stock rebajado, salida exacta y observación D-6; añadir dos detalles del mismo producto y comprobar stock total más un movimiento por línea. Probar payload ausente/no entero como 422.

**Hecho cuando:** los tests fallan por ausencia de ruta/funcionalidad, no por imports o fixtures; tests previos de 004 se mantienen verdes en su comportamiento todavía válido.

> Evidencia (fase ROJA del TDD, la casilla se marca aunque los tests estén rojos porque el "Hecho cuando" **es** que fallen por ruta ausente): `backend/tests/api/test_despacho_transaccional.py` con 7 pruebas (AC-1 cierre+fecha+entregas completas; AC-2 rebaja de stock y salida `SALIDA` con observación literal D-6; AC-3 dos líneas del mismo producto con un movimiento por línea; AC-3 agregado insuficiente rechazado; AC-13 payload ausente y `usuario_id` no entero). `cd backend && .venv\Scripts\python.exe -m pytest`: **7 failed, 102 passed**. Las 7 fallan exclusivamente en el POST `/{ticket_id}/despacho` con `404 Not Found` (ruta ausente en T5/T3); los helpers de alta y avance a `EnCurso` sí se ejecutan (los tickets se crean y transicionan), así que no hay errores de import, fixture ni sintaxis. Los 102 tests previos (incluida la 004) siguen verdes.

## T3 — Servicio de despacho atómico con lock y validación completa (AC-1…AC-14, AC-23)

- [x] Implementar en `ticket_service.py` la operación de despacho según plan §3.1–3.3: `select(Ticket).with_for_update()`, orden contractual de validaciones, nombres canónicos, detalle/producto/inventario único y stock agregado antes de mutar; luego actualizar inventario y detalles, agregar un `MovimientoInventario` por detalle, cerrar y hacer un commit. Capturar fallos de escritura/commit, ejecutar rollback explícito y relanzar.
- [x] Completar en el test de T2 los asserts observables vía API de todos los efectos y 422.

**Hecho cuando:** AC-1…AC-3 pasan con respuesta y GETs posteriores; cada detalle genera salida con cantidad y observación exactas; tests de errores de T4 aún pueden estar rojos por su implementación pendiente; servicio no depende de ids fijos ni altera modelos.

> Evidencia: `ticket_service.despachar_ticket()` (bloqueo `with_for_update()`, orden contractual de validaciones todo antes de mutar, agregado de stock por producto, un `MovimientoInventario` `SALIDA` por detalle con observación literal D-6, cierre `Cerrado` con `fecha_cierre`, un único `commit()` y `rollback()` explícito ante excepción) y ruta mínima `POST /tickets/{ticket_id}/despacho` en `endpoints/tickets.py` que solo delega al servicio (`response_model=TicketRespuesta`, 200, payload `TicketDespacho`). Los 7 tests de `test_despacho_transaccional.py` (T2) pasaron de `7 failed, 102 passed` a verde, y se añadió a AC-3 el assert persistido de estado/fecha/entregas por línea. `cd backend && .venv\Scripts\python.exe -m pytest`: **109 passed** (los 102 previos intactos, sin tocar la 004). Sin ids de estado fijos (resueltos por nombre con menor `estado_id`) y sin cambios a modelos ni DDL.

## T4 — Rechazos y casos límite del despacho, test-first (AC-4…AC-14, AC-23)

- [x] Añadir antes de ampliar comportamiento tests HTTP para rollback por stock insuficiente (incluyendo un producto suficiente antes de otro insuficiente), ticket/actor inexistentes, estado no elegible, ya cerrado, estado faltante/duplicado/case-insensitive, inventario sin fila y con dos filas, ticket sin detalles y producto no resoluble. Añadir inyección/control de fallo de escritura o commit que verifique rollback completo.
- [x] Ajustar el servicio solo tras observar los rojos; todos los errores de negocio indicados responden 404/409 según spec y no dejan cambios.

**Hecho cuando:** cada caso verifica status y estado final del ticket, detalle, inventario y movimientos; el conjunto del archivo pasa y `pytest` completo queda verde.

> Evidencia: 16 pruebas HTTP nuevas en `backend/tests/api/test_despacho_transaccional.py` (más el helper `verificar_sin_efectos`, que en cada rechazo comprueba estado y `fecha_cierre` del ticket, `cantidad_entregada` de sus detalles, el stock de los inventarios implicados y la ausencia de movimientos por la observación D-6). Cobertura por AC: **AC-4** insuficiencia de una línea y no-efectos-parciales con producto suficiente antes de otro insuficiente; **AC-5** ticket inexistente 404 con tabla de movimientos vacía; **AC-6** `usuario_id` inexistente 404; **AC-7** estado no elegible (`Pendiente`) y re-despacho de un ticket `Cerrado` (409 sin duplicar movimientos ni re-rebajar); **AC-8** catálogo sin `EnCurso` y sin `Cerrado` (409), `EnCurso`/`Cerrado` duplicados (funcional: cierra en el de menor `estado_id`, que es el canonico) y catálogo en minúsculas; **AC-9** producto sin fila de inventario y con dos filas (409 nombrando el caso); **AC-10** ticket sin detalles (detalle borrado con el motor); **AC-14** detalle huerfano con `producto_id` inexistente inyectado con `PRAGMA foreign_keys=OFF` (409 de integridad, no 404); **AC-11** fallo inyectado en `Session.commit` tras mutar → 500 y estado persistido íntegro (sin rebajas, sin entregas, sin cierre ni movimientos). **No se modificó el servicio**: los cuatro rechazos (404/409) ya estaban implementados en T3 y ninguna prueba quedó roja, así que no hubo ajuste que hacer; sí se verificó que los tests son sensibles al comportamiento observado (un 200 en vez de 409/500 haría fallar cada caso). `cd backend && .venv\Scripts\python.exe -m pytest`: **125 passed** (109 previos intactos + 16 nuevos); `ng test` no aplica a esta tarea.


## T5 — Endpoint documentado de despacho (AC-1, AC-5…AC-8, AC-21)

- [x] Añadir en `endpoints/tickets.py` `POST /{ticket_id}/despacho` con payload nuevo, `response_model=TicketRespuesta`, `status_code=200`, summary/description con flujo, atomicidad y errores relevantes; el endpoint solo delega a `ticket_service`.

**Hecho cuando:** prueba HTTP demuestra que la ruta usa el servicio y devuelve TicketRespuesta; `/openapi.json` incluye ruta, schema, status y documentación; no hay lógica de negocio en router.

> Evidencia: la ruta quedó declarada en `endpoints/tickets.py` con `response_model=TicketRespuesta`, `status_code=status.HTTP_200_OK`, `summary` y una `description` que describe el flujo `EnCurso→Cerrado`, la atomicidad ("en una sola transaccion") y los errores relevantes (`404` ticket/actor, `409` estado/catálogo/inventario/stock/detalles, `422` payload), y cuyo cuerpo solo devuelve `ticket_service.despachar_ticket(db, ticket_id, datos)` — sin lógica de negocio en el router. **El proyecto no usa `responses=` en ningún endpoint** (los precedentes 004 documentan los códigos en la `description` y así los asertan, p. ej. `test_el_contrato_del_patch_documenta_404_409_y_sellado`), así que se mantuvo ese mismo patrón y no se introdujo convención nueva. Verificación de contrato añadida a `backend/tests/api/test_despacho_transaccional.py`: `test_openapi_declara_el_contrato_del_despacho` (ruta presente, `$ref` a `TicketDespacho` en el request body, `$ref` a `TicketRespuesta` en el 200, y 404/409/422 nombrados en la descripción) y `test_openapi_declara_la_respuesta_200_explicita` (200 explícito y schema `TicketRespuesta` con `ticket_id`/`estado_id`/`fecha_cierre`/`detalles`). Inspección del `/openapi.json` real vía `app.openapi()`: `paths[.../despacho].post` con `summary` "Despachar un ticket y rebajar su inventario", `requestBody` → `TicketDespacho`, `responses` `200` → `TicketRespuesta` (+ `422` automático) y descripción de 656 caracteres. `cd backend && .venv\Scripts\python.exe -m pytest`: **127 passed** (125 previos + 2 nuevos); `ng test` no aplica a esta tarea.

## T6 — PATCH no cierra manualmente y tests previos de 004 migrados (AC-15, AC-23)

- [x] Añadir primero pruebas a `test_tablero_kanban.py` de `EnCurso→Cerrado`: 409 y detalle exacto; estado y fecha permanecen sin cambios; catálogo duplicado usa menor id; una transición distinta permitida conserva 200. Modificar `test_avanzar_a_cerrado_sella_la_fecha` y `test_el_sellado_no_depende_del_id_del_estado` para dejar de exigir cierre manual y cubrir la política nueva (el sellado por cierre se cubre por el despacho). Mantener los tests de alta directa en Cerrado y sellado de creación, si no contradicen la spec.
- [x] Añadir la guardia en `actualizar_estado_ticket()` antes de mutar; demás reglas del flujo de 004 siguen vigentes.

**Hecho cuando:** tests migrados expresan el contrato nuevo; 409 contiene literalmente `El cierre requiere despacho; use POST /api/v1/tickets/{ticket_id}/despacho`; una transición no reservada sigue pasando; `pytest` completa queda verde.

> Evidencia: guardia en `ticket_service.actualizar_estado_ticket()` tras validar el flujo (orden D-8) y antes de mutar: resuelve `EnCurso`/`Cerrado` por **nombre canónico** con `_resolver_estado_por_nombre()` (menor `estado_id` ante duplicados) y, si el ticket está en el `EnCurso` canónico y el destino es el `Cerrado` canónico, lanza 409 con el detalle literal `El cierre requiere despacho; use POST /api/v1/tickets/{ticket_id}/despacho` (substituyendo el `ticket_id` real); no usa el último ordinal ni un id fijo.
> Tests en `test_tablero_kanban.py` (18 en total): **4 nuevos** — `test_avanzar_a_cerrado_esta_reservado_al_despacho` (migración de `test_avanzar_a_cerrado_sella_la_fecha`: 409 + detalle exacto + estado `EnCurso` sin cambio + `fecha_cierre` `None`), `test_el_cierre_manual_con_cerrado_duplicado_usa_el_de_menor_id` (fixture nuevo `datos_flujo_cerrado_duplicado` con dos `Cerrado` y el canónico NO último: 409 exacto, prueba que no compara contra el último estado), `test_el_cierre_reservado_no_depende_del_id_del_estado` (migración de `test_el_sellado_no_depende_del_id_del_estado`, ahora con catálogo `Archivado→Pendiente→EnRevision→EnCurso→Cerrado`, `Cerrado` id 5: 409 exacto) y `test_una_transicion_no_reservada_desde_en_curso_sigue_siendo_200` (EnCurso→EnRevision responde 200). Se retiró la fixture `datos_flujo_tres_estados` (solo la usaba el test migrado) y se añadió el helper `_instalar_catalogo_lista`. Se mantuvieron intactos `test_crear_ticket_en_cerrado_sella_fecha_cierre` (alta directa en `Cerrado`), `test_el_sellado_no_distingue_mayusculas`, `test_reentrar_en_cerrado_conserva_la_fecha_original` y el resto de transiciones de la 004 (el catálogo sin `EnCurso` no dispara la guardia, así que esas rutas conservan su comportamiento). Verificación de sensibilidad por mutación: neutralizando la guardia (`False and ...`), los 3 tests de la guardia pasan a `200 == 409` (rojo) y el de transición no reservada sigue verde; restaurada, verde. `cd backend && .venv\Scripts\python.exe -m pytest`: **129 passed** (127 previos + 4 nuevos − 2 migrados). `ng test` no aplica (frontend es T10).

## T7 — Tests rojos del read model de historial (AC-17…AC-20, AC-23)

- [x] Crear `test_historial_movimientos.py`: lista vacía; campos asociados completos; orden fecha DESC y desempate `movimiento_id` DESC (crear datos de fechas controladas); salida de despacho aparece con tipo, cantidad, observación e inventario esperados; no hay operaciones de modificación/borrado del recurso.

**Hecho cuando:** tests fallan por endpoint inexistente/contrato ausente, no por fixtures o imports; prueba la consulta por HTTP.

> Evidencia (fase ROJA del TDD; la casilla se marca porque el "Hecho cuando" **es** que fallen por endpoint/contrato ausente): `backend/tests/api/test_historial_movimientos.py` con 8 pruebas (5 de lectura por HTTP + 3 parametrizadas de verbos de mutación). Cobertura por AC: **AC-17** lista vacía (`[]`) con catálogo cargado y sin movimientos; **AC-18** los 11 campos del contrato y datos asociados correctos (producto `Cuaderno linedado`, departamento `Operaciones`, ubicación `Bodega central`) sobre un movimiento creado con el **registro manual de la 002** vía HTTP (misma tabla); **AC-19** orden `fecha_movimiento` DESC con desempate `movimiento_id` DESC, sembrando tres filas con fechas controladas donde **dos comparten la MISMA fecha** (empate insertado antes y después) para forzar el desempate por id; **AC-20** el `SALIDA` de un despacho HTTP real aparece con tipo, cantidad 3, observación literal D-6 e `inventario_id` esperados, y el recurso es de solo lectura (OpenAPI sin `put`/`patch`/`delete`; los verbos de mutación por HTTP responden 404/405). `cd backend && .venv\Scripts\python.exe -m pytest`: **5 failed, 132 passed**. Las 5 fallas son exclusivamente por la ausencia de la ruta de lectura de T9: `GET /api/v1/inventario/movimientos` devuelve **405 Method Not Allowed** (`Allow: POST`) —no 404— porque el path ya existe con el `POST` manual de la 002, y el contrato OpenAPI aún no declara el `get`. Los helpers de alta/avance a `EnCurso` y el despacho se ejecutan sin error (las pruebas de AC-18/19/20 llegan hasta el `GET` final), así que no hay fallos de import, fixture ni sintaxis; los 129 tests previos siguen verdes (los 3 parametrizados de mutación pasan ya en rojo).

## T8 — Consulta de historial en service (AC-17…AC-20, AC-23)

- [x] Implementar `listar_movimientos()` en `inventario_service.py` con `select()` de columnas y joins explícitos de inventario/producto/departamento, `.mappings()`, DTO nuevo y orden descendente compuesto. No tocar `registrar_movimiento()`.

**Hecho cuando:** la operación del service se consume por el endpoint de T9, arma cada campo DTO del mapping y las pruebas rojas del historial continúan fallando exclusivamente por falta de endpoint.

> Evidencia (sigue la fase ROJA del TDD para el historial; la casilla se marca porque el "Hecho cuando" exige que las rojas se mantengan): `listar_movimientos(db)` en `backend/app/services/inventario_service.py` con `select()` de columnas (no de entidades), `onclause` explícitos `MovimientoInventario.inventario_id == Inventario.inventario_id`, `Inventario.producto_id == Producto.producto_id` e `Inventario.departamento_id == Departamento.departamento_id` (INNER), `.mappings()` y `MovimientoInventarioRespuesta(**fila)`; orden `fecha_movimiento DESC, movimiento_id DESC`. Solo dos columnas necesitaron `.label()` para casar con el DTO: `Producto.nombre → producto_nombre` y `Departamento.nombre_dep → departamento_nombre`; las demás ya coinciden por nombre de columna (`movimiento_id`, `inventario_id`, `producto_id`, `departamento_id`, `ubicacion`, `observacion`, `cantidad`, `tipo_movimiento`, `fecha_movimiento`), así que **no se tocó el DTO de T1**. `registrar_movimiento()` y el modelo quedaron intactos. El endpoint GET sigue sin declararse (T9), por lo que las 5 rojas de `test_historial_movimientos.py` siguen cayendo exclusivamente con **405 Method Not Allowed** (`Allow: POST`) por el POST manual de la 002. Verificación directa del service con un test temporal (creado y **eliminado** tras correrlo, no queda en la suite): lista vacía `[]`, los 11 campos del DTO, orden con empate de fechas desempatado por `movimiento_id` DESC y datos asociados correctos (`Cuaderno linedado`, `Operaciones`, `Bodega central`) → `2 passed`; confirma que T9 solo necesita declarar la ruta. `cd backend && .venv\Scripts\python.exe -m pytest`: **5 failed, 132 passed** (conteo sin cambios, ningún verde perdido). `ng test` no aplica.

## T9 — Endpoint GET del historial y contrato manual preservado (AC-17…AC-22)

- [x] Añadir en `endpoints/inventario.py` `GET /movimientos`, `response_model=list[MovimientoInventarioRespuesta]`, status 200, summary/description; delegar al service. Revisar que `POST /movimientos` conserva status, request y respuesta previos.

**Hecho cuando:** pruebas del historial de T7 pasan; OpenAPI declara response model y código explícitos; test existente del POST manual sigue pasando sin cambio contractual.

> Evidencia: ruta `GET /movimientos` declarada en `backend/app/api/v1/endpoints/inventario.py` con `response_model=List[MovimientoInventarioRespuesta]`, `status_code=status.HTTP_200_OK`, `summary` y una `description` que documenta el contenido (todas las filas de auditoría enriquecidas con producto/departamento/ubicación), el orden determinista (`fecha_movimiento` DESC, desempate `movimiento_id` DESC) y que el recurso es de solo lectura; el cuerpo solo devuelve `inventario_service.listar_movimientos(db)` — cero lógica de negocio en el router. El `POST /movimientos` de la 002 quedó **intacto** (mismo `status_code=201`, mismo `summary`, mismo body delegando en `registrar_movimiento`, misma respuesta `{"message", "nuevo_stock"}`). Verificación de contrato vía `app.openapi()`: `paths["/api/v1/inventario/movimientos"]` expone `get` y `post`; el `get` declara `responses.200` con `schema` `array` de `$ref` a `MovimientoInventarioRespuesta` y `summary` "Historial de movimientos con sus datos asociados"; el `post` conserva su `201` y summary. Las 5 rojas de T7 (`GET` 405) pasan a verde; los tests del POST manual (`test_smoke.py::test_registrar_movimiento_responde_201`, `test_transaccion_ticket.py`, `test_historial_movimientos.py::test_historial_expone_los_campos_asociados_del_movimiento`) siguen verdes sin cambios. `cd backend && .venv\Scripts\python.exe -m pytest`: **137 passed** (132 verdes previos + 5 del historial). `ng test` no aplica (frontend es T10).

## T10 — Test frontend y regla de no avanzar desde EnCurso (AC-16, AC-25)

- [x] Añadir primero tests Angular con catálogo que incluya `EnCurso` y `Cerrado`, además de un fixture con duplicados: en EnCurso no hay botón/control de avanzar pero sí retroceso; duplicado el menor id es el canónico; las demás columnas conservan controles. Luego ajustar `resolverTarjeta()` para desactivar el avance solo en la columna EnCurso canónica, sin quitar retroceso ni controles ajenos.

**Hecho cuando:** test nuevo demuestra UI/control y ausencia de request PATCH al intentar avance desde EnCurso; `ng test --watch=false --browsers=ChromeHeadless` pasa con la suite completa y el resto de transiciones conserva resultado anterior.

> Evidencia (fase ROJA → VERDE del TDD de frontend): 6 pruebas nuevas en `tickets.component.spec.ts` bajo `describe('regla de despacho: sin avance desde EnCurso (AC-16)')` con fixtures propios (`CATALOGOS_005` con `Pendiente(1) → EnRevision(2) → EnCurso(3) → Cerrado(4)`, `TICKETS_005` reusando T8 + un ticket en `EnCurso`, y el catálogo degenerado `CATALOGOS_EN_CURSO_DUPLICADO` con dos `EnCurso` donde el **menor id (3) va después** del duplicado (4)). Qué asegura cada uno: (1) la tarjeta del `EnCurso` canónico tiene `puedeAvanzar=false`/`estadoSiguienteId=null` **y conserva** `puedeRetroceder=true`/`estadoAnteriorId=2`; (2) el DOM de esa tarjeta no pinta `button[aria-label="Avanzar ticket #6"]` pero sí `"Retroceder ticket #6"`; (3) `moverSiguiente()` sobre esa tarjeta **no emite ningún PATCH** (`expectNone(RUTA_ESTADO(6))`) y no deja `errorMovimiento`; (4) `Pendiente`/`EnRevision`/`Cerrado` conservan sus controles anteriores (avance contiguo en el intermedio, terminal sin controles); (5) el nombre en minúsculas (`encurso`) también resuelve la columna canónica por `normalizar`; (6) con `EnCurso` duplicado **solo la columna de menor `estado_id`** oculta el avance y la duplicada (no canónica) conserva el suyo. En rojo: `5 FAILED, 64 SUCCESS` (el de "demás columnas" ya pasaba). Implementación quirúrgica en `tickets.component.ts`: un `computed<number | null> idEstadoEnCurso` (resuelve por `normalizar(nombre) === 'encurso'` y **`reduce` al menor `estado_id`** — no el primero, no un id fijo, no el penúltimo ordinal) y una sola línea nueva en `resolverTarjeta()`: `const esEnCursoCanonico = estados[indice].estado_id === this.idEstadoEnCurso();` + `puedeAvanzar = !esTerminal && !esEnCursoCanonico`. `puedeRetroceder`, `estadoAnteriorId`, las columnas ajenas y el template quedaron intactos. `$env:CHROME_BIN=...; npx ng test --watch=false --browsers=ChromeHeadless`: **69 SUCCESS** (63 previos + 6 nuevos), suite completa verde. `npx ng build`: build de producción correcto (`tickets-component` 65.60 kB). UI: cambio visual a verificar en el recorrido de 4200 y el humo de 8080 de T13 (la columna `EnCurso` ya no muestra "Avanzar →").

## T11 — Backend completo y contrato OpenAPI (AC-21…AC-23)

- [x] Consolidar todos los tests de backend, resolver cualquier regresión y ejecutar `pytest` completo. Revisar `/openapi.json` para POST despacho, PATCH estado, GET historial y POST manual de movimientos: códigos, modelos, payload y mensajes/documentación relevantes. Añadir/ajustar aserción automatizada del OpenAPI donde resulte estable.

**Hecho cuando:** salida de `pytest` final está verde y anotada; los cuatro contratos son verificables en OpenAPI, especialmente `TicketRespuesta`, DTO nuevo y 409 del PATCH exacto.

> Evidencia: `cd backend && .venv\Scripts\python.exe -m pytest`: **140 passed, 1 warning** (17.25 s). Son los 137 verdes que dejó T9 **+3 nuevas aserciones de contrato**; ninguna regresión ni test frágil, sin recolocar ni borrar pruebas. Auditoría de los cuatro contratos con `app.openapi()`:
> - **`POST /tickets/{ticket_id}/despacho`** — `summary`, `requestBody` → `$ref TicketDespacho`, `200` → `$ref TicketRespuesta` (+`422` automático) y `description` que nombra `404`/`409`/`422`. Ya quedó fijado en T5 con `test_openapi_declara_el_contrato_del_despacho` y `test_openapi_declara_la_respuesta_200_explicita`; **no se tocó nada**.
> - **`PATCH /tickets/{ticket_id}/estado`** — `response_model=TicketRespuesta`, `200` explícito (+`422`). **Ajuste real y único del código de producción**: la `description` estaba obsoleta (todavía prometía "al entrar en `Cerrado` se sella `fecha_cierre`" sin la restricción de la 005 y solo mencionaba el 409 genérico de flujo). Se le añadió el párrafo del **cierre manual reservado al despacho** con el literal exacto `El cierre requiere despacho; use POST /api/v1/tickets/{ticket_id}/despacho`, resolviendo `EnCurso`/`Cerrado` por nombre con menor `estado_id`. Se conservaron `404`, `409` y `fecha_cierre` en la descripción para no romper el aserto de la 004. Es solo documentación de ruta: cero cambio de comportamiento (la guardia del servicio es T6). Nuevo test `test_el_contrato_del_patch_documenta_el_cierre_reservado` (TDD: **rojo** antes del ajuste, verde después) que exige el literal en `/openapi.json`.
> - **`GET /inventario/movimientos`** — declaraba `200`, `array` → `$ref MovimientoInventarioRespuesta` y orden; faltaba aserción que lo fijara. Nuevo test `test_openapi_del_historial_declara_el_200_el_read_model_y_el_orden` (200 explícito + DTO nuevo + `fecha_movimiento`/`movimiento_id` en la descripción).
> - **`POST /inventario/movimientos`** — contrato previo intacto: `201` + `requestBody` → `$ref MovimientoCrear`, sin `response_model` (respuesta `{message, nuevo_stock}`). Nuevo test `test_openapi_del_registro_manual_conserva_201_y_su_payload` fija AC-22. **No se modificó el endpoint.**
>
> Convención respetada: los códigos de error siguen documentándose en la `description` (sin `responses=`), como en la 004 y T5; no hay precedente en contrario en el proyecto. Archivos tocados: `app/api/v1/endpoints/tickets.py` (solo `description` del PATCH), `tests/api/test_tablero_kanban.py` y `tests/api/test_historial_movimientos.py` (aserciones). `ng test` no aplica (frontend es T10/T13).


## T12 — PostgreSQL 16 real y concurrencia (AC-12, AC-24)

- [x] Ejecutar flujo con PostgreSQL real y datos de prueba identificables: confirmar despacho exitoso mediante lectura persistida de inventario, movimientos, cantidades entregadas y estado/fecha. Lanzar dos solicitudes superpuestas desde sesiones independientes al mismo ticket con sincronización controlada; comprobar exactamente 200/409 y un único conjunto de salidas. Consultar también el historial.

**Hecho cuando:** se pega evidencia reproducible de PostgreSQL 16 (comandos/lecturas sanitizadas, sin secretos) que demuestra AC-12 y AC-24; SQLite no se usa como evidencia de `FOR UPDATE`.

> Evidencia. Motor real: `docker exec compustock_db psql -U <DB_USER> -d apt_erp -c "SELECT version();"` → **PostgreSQL 16.14 on x86_64-pc-linux-musl**. El backend de la verificación se lanzó desde el host con el engine real (`postgresql+psycopg2://<DB_USER>:<DB_PASS>@localhost:5433/apt_erp`, el `5433` que publica Compose; dentro de la red docker es 5432). Datos de prueba identificables: sufijo `T12-<YYYYmmddHHMMSS>`, producto `Producto T12-… exito|concurrencia`, tickets con asunto `Evidencia T12-…`, ubicación `Bodega Evidencia T12`.
>
> **1) Despacho exitoso contra PostgreSQL real (AC-24).** Script temporal `backend/_evidencia_t12.py` (creado, usado y **eliminado**; no queda en el repo) que creó el producto/inventario (stock 10), dio de alta el ticket por el servicio real, lo avanzó con el PATCH hasta `EnCurso` y llamó a `ticket_service.despachar_ticket` con una sesión real. Respuesta del servicio: `200` (`TicketRespuesta ticket_id=21`). Lectura persistida posterior (SQL directo contra el contenedor):
>
> ```sql
> SELECT t.ticket_id, t.estado_id, e.nombre AS estado, t.fecha_cierre
> FROM ticket t JOIN estado_ticket e ON e.estado_id = t.estado_id
> WHERE t.ticket_id = 21;
>  ticket_id | estado_id | estado  |        fecha_cierre
> -----------+-----------+---------+----------------------------
>         21 |         4 | Cerrado | 2026-10-13 20:02:46.950146
>
> SELECT detalle_ticket_id, producto_id, cantidad_solicitada, cantidad_entregada
> FROM detalle_ticket WHERE ticket_id = 21;
>  detalle_ticket_id | producto_id | cantidad_solicitada | cantidad_entregada
> -------------------+-------------+---------------------+--------------------
>                 22 |          11 |                   4 |                  4
>
> SELECT inventario_id, stock_actual, ubicacion FROM inventario WHERE inventario_id = 11;
>  inventario_id | stock_actual |      ubicacion
> ---------------+--------------+----------------------
>             11 |            6 | Bodega Evidencia T12   -- 10 inicial - 4 entregadas
>
> SELECT movimiento_id, tipo_movimiento, cantidad, observacion
> FROM movimiento_inventario WHERE inventario_id = 11;
>  movimiento_id | tipo_movimiento | cantidad |                     observacion
> ---------------+-----------------+----------+------------------------------------------------------
>             11 | SALIDA          |        4 | Despacho ticket_id=21; detalle_id=22; producto_id=11
> ```
>
> Cierra las cuatro capas de AC-1/AC-2/AC-24: estado `Cerrado` (id 4) con `fecha_cierre` no nula, entrega completa (`4/4`), stock `10 → 6` y una salida `SALIDA` de 4 con observación **literal D-6** apuntando al inventario único.
>
> **2) Concurrencia: dos sesiones independientes al mismo ticket (AC-12/D-9).** Con un segundo ticket llevado a `EnCurso` (stock 10, entrega 4), dos hilos crearon **cada uno su propia `Session`** contra el mismo engine y llamaron `despachar_ticket` de forma solapada. La sincronización fue controlada con hooks de SQLAlchemy sobre la sentencia que contiene `FOR UPDATE`: el hilo **A** retenía la transacción abierta (escuchando `after_cursor_execute`, aún sin commit) mientras el hilo **B** ya había entrado a su propio `FOR UPDATE` (`before_cursor_execute`) y quedaba a la espera; el hilo principal verificó que **B seguía vivo/bloqueado** con A reteniendo el lock y solo entonces liberó a A. Resultado exacto de cada sesión:
>
> ```
> Resultado A: (200, 'TicketRespuesta ticket_id=22')
> Resultado B: (409, "El ticket no esta en 'EnCurso': el despacho solo se realiza desde ese estado")
> ```
>
> B despierta **después** del commit de A, relee la versión comprometida (`Cerrado`) y es rechazado sin crear salidas. Un único juego de movimientos (sin doble rebaja):
>
> ```sql
> SELECT inventario_id, count(*) AS salidas, sum(cantidad) AS unidades
> FROM movimiento_inventario WHERE inventario_id = 12 GROUP BY inventario_id;
>  inventario_id | salidas | unidades
> ---------------+---------+----------
>             12 |       1 |        4        -- una sola SALIDA aunque hubo dos peticiones
>
> SELECT ticket_id, estado_id, fecha_cierre FROM ticket WHERE ticket_id = 22;
>  ticket_id | estado_id |        fecha_cierre
> -----------+-----------+----------------------------
>         22 |         4 | 2026-10-13 20:02:48.684228
>
> SELECT stock_actual FROM inventario WHERE inventario_id = 12;   -- 10 - 4 = 6
>  stock_actual
> --------------
>             6
> ```
>
> **3) Historial (`GET /inventario/movimientos`, misma lectura que `inventario_service.listar_movimientos`).** Las salidas del despacho aparecen en el historial con sus datos asociados, orden `fecha_movimiento DESC, movimiento_id DESC`:
>
> ```sql
> SELECT m.movimiento_id, m.tipo_movimiento, m.cantidad, m.fecha_movimiento,
>        p.nombre, d.nombre_dep, i.ubicacion, m.observacion
> FROM movimiento_inventario m
> JOIN inventario i ON i.inventario_id = m.inventario_id
> JOIN producto p ON p.producto_id = i.producto_id
> JOIN departamento d ON d.departamento_id = i.departamento_id
> WHERE m.inventario_id IN (11,12)
> ORDER BY m.fecha_movimiento DESC, m.movimiento_id DESC;
>  movimiento_id | tipo_movimiento | cantidad |      fecha_movimiento      |                 producto                 | nombre_dep |      ubicacion       |                     observacion
> ---------------+-----------------+----------+----------------------------+------------------------------------------+------------+----------------------+------------------------------------------------------
>             12 | SALIDA          |        4 | 2026-10-13 20:02:47.132337 | Producto T12-20261013170246 concurrencia | Direccion  | Bodega Evidencia T12 | Despacho ticket_id=22; detalle_id=23; producto_id=12
>             11 | SALIDA          |        4 | 2026-10-13 20:02:46.921334 | Producto T12-20261013170246 exito        | Direccion  | Bodega Evidencia T12 | Despacho ticket_id=21; detalle_id=22; producto_id=11
> ```
>
> **Limpieza.** Los datos de evidencia se identifican por el sufijo `T12-…` y se **borraron** al terminar (`DELETE FROM movimiento_inventario/detalle_ticket/ticket/inventario/producto` en orden de FK, 2 filas por tabla); tras borrar, `producto LIKE 'Producto T12-%'`, `ticket LIKE 'Evidencia T12-%'` y los movimientos de los tickets 21/22 cuentan `0`. No se tocó ningún dato de las 003/004.
>
> **SQLite vs PostgreSQL (asimetría).** La suite de T11 (`140 passed`) es SQLite en memoria y **no** es evidencia de `FOR UPDATE`: allí la segunda sesión no se bloquea y por eso AC-12 se verificó aquí, con dos sesiones reales y el lock de fila de PostgreSQL 16. El resto de la evidencia (rollback, validaciones, contrato) sí se cubre en la suite; esta tarea aporta lo que la suite no puede. No se modificó código de producción (`pytest` sigue `140 passed, 1 warning`).

## T13 — Recorridos de frontend y build desplegado (AC-25, AC-26)

- [x] Ejecutar build de producción frontend y suite `ng test`; recorrer en 4200 contra backend/PostgreSQL real un despacho con escritura persistida y un PATCH manual rechazado sin cambios. Luego ejecutar `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d --force-recreate frontend`; recorrer 8080 de humo: Kanban actualizado, sin avance desde EnCurso y flujo básico responde.

**Hecho cuando:** se documentan resultados de tests/build y evidencia separada de 4200 (flujo funcional) y 8080 (imagen nueva recreada); el build anterior no se confunde con cambios actuales.

> **Evidencia (2026-10-13).** Backend/DB de la verificación: los contenedores ya levantados por Compose — `compustock_backend` (volumen `./backend/app` + `--reload`, apuntando al servicio `db` interno) y `compustock_db` (PostgreSQL 16). El frontend se sirvió con `npm start` en 4200. No se tocó backend en esta tarea.
>
> **1) Suite y build de frontend (AC-25).** `$env:CHROME_BIN="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless` → **`TOTAL: 69 SUCCESS`** (incluye los 6 casos de AC-16 que prueban que el `EnCurso` canónico no ofrece avance). `npx ng build` → `Application bundle generation complete [17.4s]`, `Initial total 312.97 kB` / `88.01 kB` transferidos, chunk lazy `tickets-component 65.60 kB`.
>
> **2) Recorrido funcional en 4200 (AC-26, evidencia principal).** Navegador real (MCP chrome-devtools) contra `http://localhost:4200/tickets`, backend/PostgreSQL real (mismo `localhost:8000`).
> - **Alta real por UI**: `+ Crear Ticket` → solicitante `Munoz, Diego · Secretaria` (`usuario_id=2`), prioridad `Alta`, estado `Pendiente`, asunto `Evidencia T13 4200 despacho`, ítem `Boligrota Bic Cristal` (producto 5) × `7`. El modal cierra y el banner muestra `Ticket #23 creado correctamente`; la tarjeta aparece en `Pendiente` sin recargar.
> - **Avance real por UI**: `Avanzar ticket #23` → `EnRevision`; segundo `Avanzar ticket #23` → `EnCurso`. Persistido por `GET /tickets/`: `ticket_id 23 · usuario_id 2 · estado_id 3 · detalle 24 · producto_id 5 · cantidad_solicitada 7 · cantidad_entregada 0`.
> - **Sin avance desde `EnCurso` (AC-16)**: la tarjeta del #23 en `EnCurso` muestra **solo** `button "Retroceder ticket #23"`, sin ningún `button "Avanzar ticket #23"`; #5 (el otro `EnCurso`) igual. `EnRevision` (#4) conserva Retroceder **y** Avanzar; `Pendiente` conserva Avanzar; `Cerrado` no tiene controles.
> - **Despacho**: al no existir control de despacho en la UI (005 es backend-only en UI), se usó la API real `POST /api/v1/tickets/23/despacho` con `{"usuario_id": 2}` → **200**, respuesta `estado_id 4` (`Cerrado`), `fecha_cierre` no nula, `cantidad_entregada 7`. Refrescada la vista de 4200, el #23 aparece en la columna `Cerrado` con `Cerrado: 10/13/26, 8:08 PM`.
> - **Lectura persistida (SQL directo al contenedor `db`)**:
>   ```
>   SELECT t.ticket_id,t.estado_id,e.nombre,t.fecha_cierre FROM ticket t JOIN estado_ticket e ON e.estado_id=t.estado_id WHERE t.ticket_id=23;
>    ticket_id | estado_id | estado  |        fecha_cierre
>         23    |     4     | Cerrado | 2026-10-13 20:08:56.348992
>   SELECT detalle_ticket_id,producto_id,cantidad_solicitada,cantidad_entregada FROM detalle_ticket WHERE ticket_id=23;
>         24    |     5     |          7          |          7
>   SELECT inventario_id,stock_actual FROM inventario WHERE inventario_id=5;   -- 150 inicial - 7 entregadas
>          5    |   143
>   SELECT movimiento_id,tipo_movimiento,cantidad,observacion FROM movimiento_inventario WHERE inventario_id=5;
>         13    | SALIDA |   7 | Despacho ticket_id=23; detalle_id=24; producto_id=5
>   ```
>   y por `GET /api/v1/inventario/movimientos` la salida aparece con sus datos asociados (movimiento 13, `producto_nombre Boligrota Bic Cristal`, `departamento_nombre Biblioteca`, `ubicacion Bodega Central - Estante C2`, observación literal D-6).
> - **PATCH manual rechazado sin cambios (AC-15)**: `PATCH /api/v1/tickets/5/estado` con `{"estado_id": 4}` → **409** `{"detail":"El cierre requiere despacho; use POST /api/v1/tickets/5/despacho"}`; `SELECT` posterior: #5 sigue `estado_id 3` (`EnCurso`) con `fecha_cierre` nula.
>
> **3) Despliegue y humo en 8080 (AC-26).** Imagen **anterior**: `evidenciasproyecto-frontend:latest → 75f24026eedb` (creada 2026-10-07, era previa a la 005). `docker compose -f docker-compose.yml build frontend` → nueva imagen `0af582ff27ce` (manifest `0af582ff27ce…`, creada **2026-10-13 17:10**). `docker compose -f docker-compose.yml up -d --force-recreate frontend` → `Container compustock_frontend Recreated`/`Started`; `docker inspect` del contenedor vivo → `sha256:0af582ff27ce…`, es decir la imagen **nueva**, no el build congelado anterior. Humo en `http://localhost:8080/tickets`: el tablero carga con datos reales (`GET /tickets/catalogos` 200 y `GET /tickets/` 200, sin mensajes de consola) y la tarjeta #5 en `EnCurso` muestra **solo** `Retroceder`, sin `Avanzar` — prueba directa de que 8080 sirve el bundle nuevo (el viejo build showaba el avance). Kanban ya refleja el cierre de la evidencia (#23 en `Cerrado`). Sin escritura en el humo.
>
> **Asimetría declarada:** el alta y el avance del ticket se hicieron por UI real en 4200; el despacho se hizo por la API `POST /despacho` porque la 005 no añade interfaz de despacho (spec §3 "Fuera" limita el frontend a ocultar el cierre manual). El PATCH manual se probó por API por la misma razón (no hay control de avanzar que ofrezca ese camino).
>
> **Limpieza.** Los datos de la evidencia se identifican por el asunto `Evidencia T13 4200 despacho` y el `ticket_id 23`; se **borraron** en orden de FK (`movimiento_inventario` observación `Despacho ticket_id=23;%`, `detalle_ticket`, `ticket`) y se restauró `inventario 5` a `stock_actual 150`. Verificado: `ticket`, `detalle_ticket` y `movimiento` de #23 en `0`; stock `150`. No se tocó ningún dato de las 003/004 ni de la semilla.

## T14 — Cierre: coherencia, AC-27 y AC-28 (AC-27, AC-28)

- [x] Revisar diff y greps: sin cambios a modelos, `database/01_esquema.sql`, dependencias ni auth; reglas de negocio solo en services. Hacer grep de coherencia de rutas/afirmaciones en `AGENTS.md`, `MEMORY.md` y `.agents/skills/`. Actualizar `spec.md` §6 con evidencia por AC. Solo si todas las tareas previas están verificadas y AC-1…AC-27 tienen evidencia, actualizar la fila 005 a `[x]` en `roadmap.md` y actualizar `MEMORY.md` con estado y aprendizajes; si falta evidencia, mantener roadmap `[ ]` y registrar bloqueo.

**Hecho cuando:** evidencia por AC-1…AC-28 está documentada sin afirmar autoría persistida; grep de coherencia no deja rutas/estados falsos; diff confirma las restricciones; roadmap se cierra únicamente tras el conjunto de evidencias y `MEMORY.md` refleja correctamente el estado.

> Evidencia (2026-10-13). **Suites re-ejecutadas por el cierre:** `cd backend && .venv\Scripts\python.exe -m pytest` → **140 passed, 1 warning** (el warning es el `StarletteDeprecationWarning` preexistente de `starlette.testclient`, ajeno a la 005); `$env:CHROME_BIN=...; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless` → **TOTAL: 69 SUCCESS**. Ambas verdes sin tocar código de producción.
>
> **Diff de restricciones (AC-27).** `git status`/`git diff` del cambio de la 005 lista solo: `backend/app/schemas/{ticket,inventario}_schema.py`, `backend/app/services/{ticket,inventario}_service.py`, `backend/app/api/v1/endpoints/{tickets,inventario}.py`, `backend/tests/api/{test_tablero_kanban.py,test_despacho_dtos.py,test_despacho_transaccional.py,test_historial_movimientos.py}` (los tres últimos nuevos), `frontend/src/app/features/tickets/tickets.component{,.spec}.ts`, y documentación (`spec.md` de la 004 con la nota de derogación parcial de AC-9/AC-16, y la carpeta nueva de la 005). `git diff` sobre `backend/app/models/`, `database/01_esquema.sql`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `frontend/package.json` y `backend/app/core/security.py` **vacío**: sin cambios a modelos, DDL, semilla, dependencias ni autenticación decorativa. Los endpoints solo delegan: `despachar_ticket(...)` devuelve `ticket_service.despachar_ticket(...)`, `listar_movimientos(...)` devuelve `inventario_service.listar_movimientos(...)`; cero lógica de negocio en routers. La única edición de código de producción fuera de services/schemas fue la `description` del `PATCH` (documentación de ruta, T11), ya reportada.
>
> *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006 (Clerk) y la autorización por roles se implementó en la Feature 007.*
>
> **Grep de coherencia (AGENTS.md §8.7).** `grep` sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/`: `AGENTS.md` describe endpoints y estructura de forma genérica (`auth, usuarios, inventario, tickets`) y no cita rutas de la 005, así que no quedó nada obsoleto; ninguna skill menciona el `PATCH` de la 004 como capaz de cerrar manualmente (la única coincidencia de "cerrar" en skills es el título genérico "Cuando cerrar una feature" de `sdd-workflow`); los nombres de archivo citados por las skills existen. Rutas nuevas `POST /api/v1/tickets/{ticket_id}/despacho` y `GET /api/v1/inventario/movimientos` quedan citadas en `spec.md` §6, en este `tasks.md` y en `MEMORY.md`. `MEMORY.md` se reescribe al cierre. No hubo nada que corregir por obsolescencia real.
>
> **`spec.md` §6.** Los 28 AC pasan a `[x]` y la tabla de evidencia se sustituye por una fila por AC que cita el test o la lectura/recorrido concretos y la tarea de origen, más una subsección "Verificación de cierre (T14)". Sin afirmar autoría persistida del actor: AC-13 y la nota de cierre declaran que `usuario_id` se valida pero no se escribe en `movimiento_inventario` (no existe columna). El encabezado de estado pasa de "borrador" a "aprobada", como la 004.
>
> **`roadmap.md` y `MEMORY.md` (AC-28).** Con AC-1…AC-27 evidenciados y ambas suites verdes, la fila 005 se marca `[x]` con resumen de cierre (28 AC, 140 tests backend, 69 frontend, recorridos 4200/8080, concurrencia y despacho real en PostgreSQL 16) y el índice añade sus enlaces; `MEMORY.md` se actualiza con estado y aprendizajes de la 005. `ng test` re-ejecutado: 69 SUCCESS.
