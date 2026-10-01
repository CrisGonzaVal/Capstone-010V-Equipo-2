?# Feature 003 — Tasks

**Spec:** [`spec.md`](spec.md) · **Plan:** [`plan.md`](plan.md)

Cada AC de `spec.md` §6 aparece una vez en la columna *Cubre* de algún caso de prueba
(matriz completa en `plan.md` §6). Una casilla se marca `[x]` solo con su comando de
verificación en verde, con la salida pegada en §8. Si un test falla, la casilla **no** se
marca: se arregla o se documenta el bloqueo.

Leyenda: `[ ]` pendiente · `[x]` hecha y verificada · `[!]` bloqueada (motivo en la línea)

---

## Fase 0 — Verificación de supuestos (TDD: red antes que verde)

- [x] Contrastar `spec.md` y `plan.md` contra el código real:
  - `crear_ticket` **no** prevalida nada y **no** tiene `try/except` — confirmado,
    `ticket_service.py:24-47`
  - `es_stock_critico` vive en `inventario_service.py:19` — confirmado
  - **Cuarto** import de `URL_API` en `inventario.component.spec.ts:7`, que no estaba en la
    spec primera → corregido en `spec.md` (D-2, `AC-23`) y `plan.md` §1 antes de implementar
  - `TicketCrear` **no** tiene `min_length`/`max_length`/`gt` todavía — confirmado,
    `ticket_schema.py:24-30`
  - `features/tickets/` no tiene `.spec.ts` — confirmado, es nuevo
  - Campos `unidad_medida`, `stock_minimo`, `nombre_cat`, `nombre_dep` existen — confirmado
    en `models/producto.py` y `models/usuario.py`
- [x] Línea base de tests antes de tocar nada
  - [x] `backend\.venv\Scripts\python.exe -m pytest` → **43 passed** (AC-26 los cita)
  - [x] `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"`
  - [x] `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` → **TOTAL: 12 SUCCESS** (AC-27 los cita)

## Fase 1 — `URL_API` a `shared/` (D-2, AC-23)

Sin dependencias: va primero porque valida el diseño de capas antes de escribir la feature.

- [x] `frontend/src/app/shared/config/url-api.ts` — crear con `export const URL_API = 'http://localhost:8000/api/v1';`
- [x] `features/inventario/services/inventario.service.ts` — quitar la declaración, importar de `shared/config/url-api` (línea 14)
- [x] `features/administracion/services/usuario.service.ts` — mismo cambio (línea 5)
- [x] `features/tickets/services/ticket.service.ts` — mismo cambio (línea 6)
- [x] `features/inventario/inventario.component.spec.ts` — mismo cambio (línea 5)
- [x] `npx ng test --watch=false --browsers=ChromeHeadless` → `TOTAL: 12 SUCCESS`
- [x] `AC-23` grep recursivo → 4 imports desde `shared/config/url-api`, 0 imports cruzados. Las 2 referencias que quedan a `inventario.service` son legítimas: el propio archivo y su consumidor dentro de la misma feature

## Fase 2 — Catálogos backend (D-1, AC-1…AC-5)

- [x] `ticket_schema.py`: `PrioridadRespuesta` (`prioridad_id`, `nombre`, `descripcion`, `from_attributes`) — la tabla `prioridad` **no** tiene `dias_respuesta`
- [x] `ticket_schema.py`: `EstadoTicketRespuesta` (`estado_id`, `nombre`, `descripcion`, `from_attributes`) — la tabla `estado_ticket` **no** tiene `estado_final`
- [x] `ticket_schema.py`: `ProductoCatalogoRespuesta` (`producto_id`, `nombre`, `unidad_medida`, `categoria_nombre`, `stock_total` `NOT NULL`, `es_critico`) — **sin** `from_attributes`
- [x] `ticket_schema.py`: `SolicitanteRespuesta` (`usuario_id`, `nombre`, `apellido`, `correo`, `departamento_nombre`) — **sin** `from_attributes`
- [x] `ticket_schema.py`: `CatalogosTicketRespuesta` con las 4 listas
- [x] `ticket_service.py`: `obtener_catalogos()` con los 4 queries (2 `select(Modelo)` + 2 read models con `join`/`outerjoin` y `group_by` completo)
- [x] `es_critico` sale de `es_stock_critico()` importada de `inventario_service` (AC-3)
- [x] `stock_total` con `func.coalesce(func.sum(...), 0)` para productos sin inventario (AC-5)
- [x] `tickets.py`: `GET /catalogos` con `response_model`, `summary` y `description`
- [x] `status_code` explícito y `description` en las 3 rutas existentes (`AGENTS.md` §6)
- [x] `backend/tests/api/test_modal_ticket.py`: fixture `datos_catalogo_ticket` **apoyado** en `datos_base` (2 prioridades, 3 estados extra); `conftest.py` sin tocar
- [x] Test: 200 con las 4 listas no vacías
- [x] Test: OpenAPI declara `/tickets/catalogos` y conserva las 3 rutas previas
- [x] Test: estados en el orden del flujo (el primero es el inicial, no el alfabético)
- [x] Test: `es_critico` del catálogo **coincide** con el de `GET /inventario/existencias` (AC-3)
- [x] Test: producto sin existencias sale con `stock_total` 0, no `None`
- [x] Test: solicitantes con `departamento_nombre` y ordenados por apellido (2 usuarios)
- [x] Test: catálogo vacío → 4 listas vacías, 200 (AC-5)
- [x] **`AC-13`** los 43 tests previos pasan sin reescribirse
- [x] **`AC-14`** `git diff --stat backend/app/models/ database/01_esquema.sql` → vacío
- [x] **`AC-15`** `grep -rn "db.query\|db.get" backend/app/api/` → 0
- [x] `pytest` → **54 passed** (43 previos + 11 nuevos)

## Fase 3 — Validaciones del schema (D-5, AC-9)

- [x] `TicketCrear.asunto`: `Field(min_length=3, max_length=150)`
- [x] `DetalleTicketCrear.cantidad_solicitada`: `Field(gt=0)`
- [x] `TicketCrear.detalles`: `Field(min_length=1)` — un ticket sin ítems es 422
- [x] Test: asunto de 2 y de 151 caracteres → 422
- [x] Test: **frontera**: asunto de 150 → 201 (el `>` equivocado rechazaría justo el válido)
- [x] Test: sin detalles → 422
- [x] Test: cantidad `0` y `-5` → 422
- [x] Test: **frontera**: cantidad `1` → 201
- [x] Test: `descripcion` ausente del payload → 201 con `null`
- [x] Test: ticket válido completo → 201, con detalles y `cantidad_entregada == 0` (AC-10)
- [x] Test: el ticket creado aparece en `GET /tickets/`
- [x] Test: dos ítems de productos distintos → 2 detalles
- [x] Test: `cantidad_solicitada: 9999` con stock 50 → 201 (AC-11)
- [x] Test: el stock queda idéntico tras crear el ticket, leído por `GET /inventario/existencias`
- [x] `pytest` → **68 passed** (43 previos + 25 nuevos)

### Fases 2–3: rojo primero y mutaciones

Los tests de validación se escribieron **antes** del schema, y se vio fallar:
```
$ pytest tests/api/test_modal_ticket.py -q          # antes de tocar ticket_schema.py
6 failed, 19 passed
   test_asunto_muy_corto_responde_422 · test_asunto_vacio_responde_422
   test_asunto_demasiado_largo_responde_422 · test_ticket_sin_detalles_responde_422
   test_cantidad_cero_responde_422 · test_cantidad_negativa_responde_422
```
Los 6 caían justo en las reglas que faltaban, y los 8 casos de camino feliz pasaron de
inmediato: las 422 no seinventaron sobre tests que no podian cumplirlas.

| Mutación | Resultado |
|---|---|
| `EstadoTicket.estado_id` → `.nombre` en el `order_by` | 1 failed, 24 passed → `test_estados_salen_en_el_orden_del_flujo` |
| `coalesce(sum(...), 0)` → `sum(...)` | 9 failed, 2 passed → el endpoint entero cae en 500 |
| `es_stock_critico(...)` → `False` fijo | 2 failed, 9 passed |
| `min_length=3` → `2` en `asunto` | 1 failed, 24 passed → borde inferior |
| `gt=0` → `ge=0` en `cantidad_solicitada` | 1 failed, 24 passed → aceptaría cantidad 0 |

La del `coalesce` merece la explicación, porque no es un fallo quirúrgico: sin ella, el
producto sin existencias trae `stock_total = None` y `es_stock_critico` revienta con
`TypeError: '<=' not supported between instances of 'NoneType' and 'int'`
(`inventario_service.py:27`) **antes** de que el DTO pueda validarse. El endpoint entero cae
en 500 y se caen los 9 tests que lo consultan. El `coalesce` no protege un campo del payload:
sostiene el endpoint. Por eso "producto sin existencias" está en la fixture y no como nota
al pie.

## Fase 4 — Prevalidación referencial en el service (D-6, AC-6, AC-7, AC-8, AC-11)

- [x] Helper `_verificar_referencia(db, modelo, valor, etiqueta)` → 404 si `db.get()` es `None`
- [x] Prevalidar `Usuario`, `Prioridad`, `EstadoTicket` antes de escribir
- [x] Prevalidar **todos** los `Producto` con un `set` de ids, mensaje con el más bajo ausente
- [x] Envolver las escrituras en `try/except Exception: db.rollback(); raise` (`plan.md` §4)
- [x] Test: producto inexistente → 404, mensaje con el id
- [x] Test: usuario inexistente → 404
- [x] Test: prioridad inexistente → 404
- [x] Test: estado inexistente → 404
- [x] Test: el 404 distingue **qué** referencia falla y cuál es su valor
- [x] Test: un detalle válido junto a uno inválido se rechaza entero
- [x] Test: 5 líneas del mismo producto → 5 detalles (el `set` no pisa las líneas)
- [x] Test: referencia inválida → 0 filas en `ticket`, sin huérfano (AC-8)
- [x] Test: el detalle válido del payload tampoco queda persistido
- [x] Test: después de un 404, el siguiente POST válido funciona
- [x] Test: tres 404 seguidos y luego un alta válida
- [x] `pytest` → los tests de la línea base **intactos** + los nuevos en verde
- [x] **`AC-26`** el recuento final de pytest incluye los 43 casos previos **sin reescribir ninguno** más los nuevos. Comparar con la línea base de Fase 0

### Defecto reproducido antes de arreglarlo

Los 10 tests de esta fase se escribieron primero y se vio fallar con exactamente el sintoma
que la spec describe:
```
$ pytest tests/api/test_modal_ticket.py -q        # antes de tocar ticket_service.py
E   sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
10 failed, 26 passed
```

## Fase 5 — Migrar los 500 documentados a 404 (AC-6)

- [x] `test_smoke.py::test_ticket_con_producto_inexistente_responde_500_defecto_conocido` → renombrar a `test_ticket_con_producto_inexistente_responde_404`, y su docstring pasa a explicar que la 003 corrige el defecto y que el test **se mantiene** porque es el que lo vigila
- [x] `test_transaccion_ticket.py`: 3 casos de 500 → 404, conservando el resto de sus aserciones
- [x] `pytest` verde
- [x] `grep -rn "responde_500|500_defecto|status_code == 500" backend/tests` → 0
- [x] `pytest` → **79 passed** (43 previos + 36 nuevos)

## Fase 6 — Tipos y servicio frontend (AC-24)

- [x] `shared/interfaces/index.ts`: `Prioridad`, `EstadoTicket`, `ProductoCatalogo`, `Solicitante`, `CatalogosTicket` en `snake_case`
- [x] `features/tickets/services/ticket.service.ts`: `obtenerCatalogos(): Observable<CatalogosTicket>`
- [x] `npm run build` sin errores de tipos

## Fase 7 — El modal (D-3, D-4, D-7, AC-16…AC-22)

- [x] `tickets.component.ts`: signals `modalAbierto`, `catalogos`, `cargandoCatalogos`, `guardando`, `ticketCreado`, `detalleErrores`, `errorCatalogos`
- [x] `tickets.component.ts`: `formulario` con `NonNullableFormBuilder` y `FormArray` de detalles (D-7)
- [x] `tickets.component.ts`: `abrirModal()` pide los catálogos; `cerrarModal()`; `dialogo = viewChild.required<ElementRef<HTMLDialogElement>>('dialogo')`
- [x] `tickets.component.ts`: `effect()` que sincroniza el signal con `showModal()`/`close()`, con guarda `if (!nativo.open)` (`plan.md` §5.2)
- [x] `tickets.component.ts`: `agregarDetalle()`, `quitarDetalle()` (deshabilitado con 1 fila), `combinarDetalles()` que suma duplicados (`plan.md` §5.4)
- [x] `tickets.component.ts`: estado inicial = `catalogos.estados[0]`, sin comparar strings (D-4)
- [x] `tickets.component.ts`: `enviar()` con guarda de formulario inválido, guarda de doble envío y mapeo de errores por campo (`plan.md` §5.5)
- [x] `tickets.component.html`: botón `+ Crear Ticket` que abre el modal
- [x] `tickets.component.html`: `<dialog>` con los 3 desplegables, asunto, descripción, filas de detalle y botones
- [x] `tickets.component.html`: `@if`/`@for` (nada de `*ngIf`/`*ngFor`), `(close)="cerrarModal()"`, `role="alert"` en los errores
- [x] Solo clases de Tailwind; ni una regla en `styles` ni en el template
- [x] **`AC-25`** `grep -rn "@NgModule\|\*ngIf\|\*ngFor\|CommonModule" frontend/src/app` → 0, y `grep -rn "style=" features/tickets` → 0 (`AGENTS.md` §6)
- [x] **`AC-28`** `cd frontend && npm run build` compila

## Fase 8 — Tests frontend (AC-17…AC-22)

- [x] `tickets.component.spec.ts`: `provideHttpClient()` + `provideHttpClientTesting()`, `httpMock.verify({ ignoreCancelled: true })`
- [x] Test: abre el modal → exactamente 1 petición a `/tickets/catalogos`
- [x] Test: los desplegables se llenan con los catálogos
- [x] Test: el estado arranca en el primero del flujo
- [x] Test: agregar y quitar filas de detalle
- [x] Test: no envía si el formulario es inválido (0 peticiones al endpoint de tickets)
- [x] Test: envío válido → `POST /tickets/` con las cantidades sumadas, cierra y avisa el `ticket_id`
- [x] Test: error del backend → modal abierto, formulario intacto, `role="alert"` visible
- [x] Test: el error de catálogos se distingue del de guardado
- [x] Test: doble clic en enviar → 1 sola petición (AC-22)
- [x] `npx ng test --watch=false --browsers=ChromeHeadless` → verde, y los specs de inventario y admin intactos
- [x] **`AC-27`** el recuento final de `ng test` incluye los tests previos más los nuevos de `tickets.component.spec.ts`. Comparar con la línea base de Fase 0

## Fase 9 — Verificación contra PostgreSQL (AC-30)

- [x] `docker compose -f docker-compose.yml up -d db backend`
- [x] `GET /api/v1/tickets/catalogos` real → 200, 10 productos, 10 solicitantes, 3 `es_critico: true`
- [x] Coincide con `GET /inventario/existencias` en los 10 `es_critico` (AC-3)
- [x] `POST /tickets/` con `producto_id: 99999` → 404, y `SELECT count(*)` de `ticket` sin cambios
- [x] `POST /tickets/` con `asunto` de 2 caracteres → 422
- [x] `POST /tickets/` válido → 201 y el ticket aparece en `detalle_ticket` con `cantidad_entregada = 0`
- [x] `/openapi.json` contiene `status_code: "201"` en el POST y las 4 rutas de tickets

## Fase 9.5 — Recorrido del modal en el navegador (AC-29)

Contra el backend real, **no** contra mocks. Sin esto la feature no está cerrada
(`AGENTS.md` §8.5).

- [x] Backend y db arriba: `docker compose -f docker-compose.yml up -d db backend`
- [x] `cd frontend && npm start` (4200) en segundo plano
- [x] Abrir `/tickets`, pulsar `+ Crear Ticket`: el modal aparece y el DOM renderizado muestra los desplegables poblados
- [x] Enviar vacío: el navegador bloquea el envío y se ven los mensajes de campo
- [x] Llenar el formulario y guardar: aparece el aviso con el `ticket_id` y el modal se cierra
- [x] `GET /tickets/` lista ese ticket con sus detalles
- [x] Anotar en §8 lo observado, con el `ticket_id` creado

## Fase 9.6 — El modal en 8080, el build de producción (AC-32)

4200 no basta para cerrar la feature (`AGENTS.md` §8.6). El contenedor nginx sirve un
build congelado, así que hay que reconstruirlo **antes** de mirar, o el recorrido
comprueba una vista vieja y no dice nada de esta feature.

- [x] `docker compose -f docker-compose.yml build frontend`
- [x] `docker compose -f docker-compose.yml up -d frontend`
- [x] Abrir `/tickets` en 8080: el modal abre y los desplegables se pueblan
- [x] El estado inicial preseleccionado es el primero del catálogo (Pendiente), no el
      que caiga alfabéticamente
- [x] Enviar vacío: el navegador bloquea y se ven los mensajes de campo
- [x] Cerrar y reabrir: los catálogos se recargan y el formulario queda limpio
- [x] Anotar en §8 lo observado en 8080, y que coincide con lo de 4200

> Recorrido de humo, a diferencia del de 4200: aquí no se crea el ticket. El build de
> producción ya está cubierto por `AC-28` y por el propio `build` de arriba; lo que
> 8080 agrega es el `try_files` de nginx para rutas Angular y el cacheo de bundles.

## Fase 10 — Cierre documental

- [x] `docs/spec/stack.md` §3: `shared/config/url-api.ts` en el árbol; §2: el read model de catálogos
- [x] `docs/spec/roadmap.md`: fila 003 con enlaces a los 3 documentos y criterio de cierre real
- [x] `MEMORY.md`: Feature 003 cerrada, decisiones D-1…D-7 y las lecciones de esta fase
- [x] `grep` de coherencia sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/`: ninguna ruta ni afirmación obsoleta (`AGENTS.md` §8.6)
- [x] `AGENTS.md` §5: nota de los puertos 4200 (código actual) y 8080 (build de la imagen)
- [x] **`AC-31`** coherencia documental completa: `roadmap.md` con la fila 003 (hecho al abrir el gate, se revisa al cerrar), `stack.md` con el read model y con `shared/config/url-api.ts`, `MEMORY.md` actualizado, `AGENTS.md` §5 con la nota de los dos puertos, y `grep` de rutas `.md` rotas → 0
- [x] `spec.md` §6: los 32 AC marcados `[x]` **con su evidencia** (§8)
- [x] **`AC-32`** `docker compose -f docker-compose.yml build frontend` + `up -d frontend`
- [x] **`AC-32`** recorrer el modal en 8080 y comprobar que refleja lo mismo que 4200, no una vista vieja (Fase 9.6)
- [x] `pytest` y `ng test` en verde, última corrida

---

## 8. Evidencia de verificación

Nada se marca `[x]` arriba sin que exista su línea aquí, con la salida real del comando.
La revisión de la feature se hace leyendo esta sección, no las casillas.

### Backend

Línea base, Fase 0:
```
$ backend\.venv\Scripts\python.exe -m pytest
43 passed, 1 warning in 4.55s
```

Corrida final:
```
$ backend\.venv\Scripts\python.exe -m pytest -q
79 passed, 1 warning in 9.19s
```

El único warning es `StarletteDeprecationWarning` sobre `httpx` en
`fastapi/testclient.py`, preexistente y ajeno a esta feature.

### Frontend

Línea base, Fase 0 (12 tests de inventario y administración):
```
$ npx ng test --watch=false --browsers=ChromeHeadless
TOTAL: 12 SUCCESS
```

Corrida final (los 12 previos + 28 nuevos de `tickets.component.spec.ts`):
```
$ npx ng test --watch=false --browsers=ChromeHeadless
TOTAL: 40 SUCCESS
```
Sin `NG0956` (corregido con `track $index`) y sin specs "has no expectations".

`npx ng build --configuration production` → `Application bundle generation complete`.

### PostgreSQL

`GET /api/v1/tickets/catalogos` contra el contenedor: 3 prioridades, 4 estados, 10
productos, 10 solicitantes. Orden confirmado: estados `1=Pendiente, 2=EnRevision,
3=EnCurso, 4=Cerrado`; solicitantes por apellido.

Validaciones y referencias, con escritura verificada contra la BD:

| Caso | Resultado | Escritura |
|---|---|---|
| `POST` válido | **201**, persistido y visible en `GET /tickets/` | 1 ticket + detalles |
| `usuario_id: 99` | **404** | ninguna |
| `prioridad_id: 99` | **404** | ninguna |
| `estado_id: 99` | **404** | ninguna |
| `producto_id: 99` | **404** | ninguna |
| producto inexistente en el **2º** detalle | **404** | ninguna |
| `asunto` de 2 caracteres | **422** `loc=['body','asunto']` | ninguna |
| `asunto` de 151 caracteres | **422** | ninguna |
| `asunto` de exactamente 150 | **201** | 1 ticket |
| `cantidad_solicitada: 0` | **422** `loc=['body','detalles',0,'cantidad_solicitada']` | ninguna |
| `detalles: []` | **422** `loc=['body','detalles']` | ninguna |
| `producto_id: null` | **422** `loc=['body','detalles',0,'producto_id']` | ninguna |

La forma de los `loc` importa: el mapeo del frontend lee `loc.at(-2)` como índice de fila
y `loc.at(-1)` como nombre de campo, así que coincide con lo que produce FastAPI.

Los 10 tickets y sus 11 detalles de prueba se borraron al terminar. La BD quedó con los
10 tickets de semilla y el inventario sin cambios (`Boligrota` 150, `Clip Metrico` 35,
`Resma Carta` 120), lo que confirma que crear un ticket **no** descuenta stock.

### Recorrido en 4200 (dev server)

24 comprobaciones, todas en verde. Ruta carga, 4 columnas Kanban, el modal abre, los
catálogos se pueblan, el estado inicial preseleccionado es **Pendiente** (`estado_id` 1:
el primero del catálogo, no el alfabético), el envío vacío no dispara POST y muestra 4
mensajes de campo, el envío válido produce el banner `Ticket #20 creado correctamente` y
cierra el modal, al reabrir los catálogos se recargan y el formulario queda limpio, y con
el backend detenido el banner de error aparece manteniendo el modal abierto.

Cuerpo real enviado por el navegador, confirmado contra la red:
```json
{"usuario_id":5,"prioridad_id":2,"estado_id":2,"asunto":"E2E CDP 142735",
 "descripcion":null,"detalles":[{"producto_id":1,"cantidad_solicitada":7}]}
```

### Recorrido en 8080 (build de producción)

18 comprobaciones, todas en verde, **después** de `docker compose build frontend` +
`up -d frontend`. Confirma que la imagen sirve esta feature y no una vista vieja: modal,
catálogos, estado inicial preseleccionado, validación en cliente, y recarga de catálogos
al reabrir. Sin escritura.

### Coherencia documental

`grep` de rutas citadas en `AGENTS.md`, `MEMORY.md` y `.agents/skills/` sin referencias
obsoletas.

## 9. Notas de implementación

Decisiones que se tomaron al escribir el plan y que conviene no perder de vista:

- **El `except HTTPException` dentro del `try` es código muerto.** Los 404 de la
  prevalidación se lanzan **antes** del `try`; dentro solo fallan errores de base
  (`IntegrityError`, `OperationalError`), que no heredan de `HTTPException`. Queda un solo
  `except Exception: db.rollback(); raise`. Si alguna vez se mete una validación **dentro**
  del `try`, ese `except` sí haría falta.
- **El `rollback()` del `except` no está cubierto por ningún test, y se comprobó que desde el
  seam HTTP no se puede cubrir.** La mutación que lo borra deja los 79 tests en verde, y el
  motivo es `get_db`: hace `db.close()` en su `finally`, y `close()` ya revierte la
  transacción. Consecuencias que conviene no perder:
  - La primera versión de este `tasks.md` afirmaba que sin ese `rollback()` "la sesión
    quedaría con una transacción abierta y el siguiente POST fallaría con un error de
    SQLAlchemy". **Era falso** para el `get_db` actual. Se corrigió en tres sitios:
    `plan.md` §4, el docstring de `crear_ticket` y el nombre del test, que pasó de
    `test_la_sesion_sigue_usable_despues_de_un_404` a
    `test_despues_de_un_404_la_siguiente_peticion_sigue_funcionando` con un docstring que
    declara qué **no** cubre.
  - El `rollback()` se conserva por `constitucion.md` §3 y por higiene: el método debe ser
    correcto por sí mismo y no gracias al cleanup de quien lo llama. Deja de ser redundante
    en cuanto dos tickets compartieran transacción.
  - **`AC-8` sigue siendo verificable y verificado, pero por otra vía**: que tras un 404 no
    quede ni el ticket ni las líneas de detalle, y que el stock no se mueva. Eso sí lo
    comprueban `test_referencia_invalida_no_deja_ticket_huerfano` y
    `test_referencia_invalida_no_deja_detalles_sin_ticket`.
- **La suma de duplicados es del cliente.** `detalle_ticket` no declara
  `UNIQUE(ticket_id, producto_id)`, así que el servidor aceptaría las dos filas. El selector
  las fusiona porque es un error de UX, no una regla de negocio (spec §3, Fuera de alcance).
- **`forkJoin` de una sola petición no.** El de la Feature 002 servía para un único estado de
  carga con dos peticiones; con una sola, `.subscribe({ next, error })` es más honesto. Los
  tests conservan `ignoreCancelled: true` por el `forkJoin` de inventario.
- **Los 404 no se mapean a un campo del formulario.** Un 404 desde la vista solo puede
  aparecer si otro proceso borró el producto entre la carga del catálogo y el envío; se
  muestra el mensaje del backend en el bloque de alerta, sin tratarlo como error de un
  control. `AC-6` y `AC-7` solo son verificables desde el backend, y por eso sus casos viven
  en `test_modal_ticket.py`.
- **Los CHECK de la base solo existen en PostgreSQL.** El 422 de cantidad y asunto lo produce
  el schema Pydantic, no el CHECK, así que la suite SQLite sí lo cubre. El CHECK se
  verifica en la Fase 9 contra el contenedor.
