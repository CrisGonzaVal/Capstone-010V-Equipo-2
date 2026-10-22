# Feature 003 — Evidencia del recorrido funcional en 4200 y humo en 8080 (Enmienda E22)

Spec: [`../spec.md`](../spec.md) · Plan: [`../plan.md`](../plan.md) · Tareas: [`../tasks.md`](../tasks.md)
Enmienda de autoatribución: [`../../007-control-acceso-roles/spec.md`](../../007-control-acceso-roles/spec.md) (AC-18…AC-20) · [`../../008-particionamiento-institucional/spec.md`](../../008-particionamiento-institucional/spec.md) (AC-11)

Fecha del recorrido: **2026-10-22**, ~18:24–18:45 local (21:24–21:45 UTC).
Frontend dev `npm start` en `http://localhost:4200`, backend `http://localhost:8000`
(contenedor con `uvicorn --reload` y `./backend/app` montado) y PostgreSQL 16 en `5433`.
Esta evidencia cubre **solo la enmienda E22** (autoatribución del alta y autor informativo);
la evidencia histórica de los AC originales no se reescribe.

## 1. Suites y contrato observados antes del recorrido

| Comprobación | Resultado real |
|---|---|
| `backend\.venv\Scripts\python.exe -m pytest` (SQLite en memoria) | **1403 passed, 77 skipped**, 0 failed (189,23 s) |
| `$env:POSTGRES_TEST_URL="postgresql://postgres:postgres@localhost:5433/postgres"` + `pytest` | **1480 passed, 0 skipped**, 0 failed (bases temporales desechables; `apt_erp` intacta en `014.1`, 22 tablas de control y 4 tenants) |
| `$env:CHROME_BIN=…msedge.exe; npx ng test --watch=false --browsers=ChromeHeadless` | **470 SUCCESS / 0 FAILED** (Edge 155.0.0.0) |
| `npx ng build` | **limpio**; entry bundle **`main-QNRFXFUT.js`** (el anterior era `main-KWQKKL6Q.js`) |
| `GET /openapi.json` → `TicketCrear.required` | `prioridad_id, estado_id, asunto, detalles` — **sin `usuario_id`** |
| `GET /openapi.json` → `TicketCrear.properties.usuario_id` | `anyOf [integer, null]` con descripción «Opcional e **ignorado**: la autoría queda fijada por el servidor con la identidad autenticada. Enviarlo (propio, ajeno o inexistente) no cambia el autor ni produce 404/422/403.» |
| `GET /openapi.json` → `TicketDespacho.required` | `usuario_id` (**sigue obligatorio**; es contrato de despacho, distinto del alta) |
| `GET /openapi.json` → `POST /api/v1/tickets/` | `201, 401, 403, 404, 422`; el 404 documenta solo recurso inexistente/ajeno (producto/prioridad/estado), y la descripción declara que `usuario_id` no produce 404, 422 ni 403 |
| `GET /openapi.json` → operaciones `/api/v1` | **62** (coincide con `app.core.permisos.MATRIZ_PERMISOS`: 62; la matriz no cambió) |

Tests de la enmienda que sostienen estos resultados (nombres reales, todos en verde en la
suite anterior):

- `test_tickets_alcance.py::test_solicitante_crea_y_se_atribuye_su_identidad`,
  `::test_roles_autorizados_atienden_la_identidad_de_sesion` (parametrizado por rol con
  `usuario_id` omitido, propio, ajeno e inexistente),
  `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`,
  `::test_administrador_crea_para_solicitante_propio_201`,
  `::test_departamento_sin_sede_responde_409_sin_ticket_detalle_ni_historial`.
- `test_tickets_institucional.py::test_crear_ticket_con_producto_ajeno_404_sin_parcial`
  (404 conservado), `::test_crear_ticket_puebla_institucion_en_ticket_y_detalle`,
  `::test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion`.
- `test_tickets_alcance.py::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`
  (el `usuario_id` ajeno se ignora).
- `test_modal_ticket.py::test_ticket_con_usuario_inexistente_se_ignora_y_atiende_a_la_sesion`,
  `::test_ticket_valido_responde_201_con_detalles_y_entregada_en_cero`.
- `test_ticket_sede_011.py::test_crear_ticket_sin_sede_de_departamento_afecta_a_todos_los_roles_creadores`,
  `::test_departamento_sin_sede_no_crea_ticket_responde_409`; los POST de despacho y sus
  payloads con `usuario_id` quedan intactos.

## 2. Recorrido funcional en 4200 (Paso 2)

Cuentas: `admin017.test+clerk_test@example.com` (**Administrador QA014**, usuario 13,
Dirección → sede 1), `solicitante.test+clerk_test@example.com` (**Paula Rojas**, Solicitante,
usuario 11, Biblioteca → sede 2) y, para el humo, la misma Solicitante. Sesiones **reales** de
la instancia dev de Clerk `relevant-termite-8089` con la UI prebuilt; el acceso por correo se
verificó con el código de prueba `424242`. Ningún secreto ni token se transcribe.

### 2.1 Caso 1 — Administrador crea un ticket real

| Paso | Resultado real | AC |
|---|---|---|
| `/tickets` → **«+ Crear Ticket»** | el modal abre con el campo **«Solicitante (sesión)»** en solo lectura: **«Administrador QA014»** + `admin017.test+clerk_test@example.com`; **no hay `<select>` ni control editable** `usuario_id` | **003 AC-34 / 007 AC-19** |
| Formulario | prioridad **Alta**, estado inicial **Pendiente**, asunto y descripción llenados, ítem **Resma Carta 75g A4** (producto 1) × 2 | 003 AC-35 |
| **Crear ticket** | `POST http://localhost:8000/api/v1/tickets/` → **201**; cuerpo **`{"prioridad_id":1,"estado_id":1,"asunto":…,"descripcion":…,"detalles":[{"producto_id":1,"cantidad_solicitada":2}]}`** — **sin `usuario_id`** | **003 AC-33/AC-34, 007 AC-18/AC-19, 008 AC-11** |
| Respuesta | `ticket_id 11`, **`usuario_id 13`** (el de la sesión), `sede_id 1`, detalle con `institucion_id INST-001` | **007 AC-18/AC-20, 008 AC-11** |
| Listado | columna **Pendiente** con `#11 «Enmienda E22 autoatribucion Admin»` y solicitante **«QA014, Administrador · Direccion»** | 003 AC-33 |
| Verificación en BD (`tenant_inst_001_038aa2a9`) | `ticket 11 → usuario_id 13, institucion_id INST-001, sede_id 1`; `detalle_ticket 14 → ticket 11, producto 1, institucion_id INST-001` | **008 AC-11** |

Capturas: `01-4200-modal-solicitante-sesion-admin.png`, `02-4200-alta-exitosa-ticket-11.png`.

### 2.2 Caso 2 — Solicitante crea un ticket real

Se cerró sesión y se inició con la Solicitante de la misma institución (correo + código de
prueba).

| Paso | Resultado real | AC |
|---|---|---|
| `/tickets` → **«+ Crear Ticket»** | campo **«Solicitante (sesión)»**: **«Paula Rojas»** + `solicitante.test+clerk_test@example.com`; **sin selector** | **003 AC-34 / 007 AC-19** |
| Formulario | prioridad **Media**, estado **Pendiente**, ítem **Boligrafo Bic Cristal** (producto 4) × 3 | 003 AC-35 |
| **Crear ticket** | `POST /api/v1/tickets/` → **201**; cuerpo **sin `usuario_id`**: `{"prioridad_id":2,"estado_id":1,…,"detalles":[{"producto_id":4,"cantidad_solicitada":3}]}` | **003 AC-33/AC-34, 007 AC-18/AC-19, 008 AC-11** |
| Respuesta | `ticket_id 12`, **`usuario_id 11`** (la sesión), **`sede_id 2`** (Biblioteca), detalle `institucion_id INST-001` | **007 AC-18/AC-20, 008 AC-11** |
| Listado | columna **Pendiente** con `#12 «Enmienda E22 autoatribucion Solicitante»` y solicitante **«Rojas, Paula · Biblioteca»** | 003 AC-33 |
| Verificación en BD | `ticket 12 → usuario_id 11, institucion_id INST-001, sede_id 2`; `detalle_ticket 15 → ticket 12, producto 4, institucion_id INST-001` | **008 AC-11** |

Capturas: `03-4200-modal-solicitante-sesion-solicitante.png`, `04-4200-alta-exitosa-ticket-12-solicitante.png`.

### 2.3 Lo que el recorrido no demuestra

- No se probó el alta con **Bodeguero** en la UI por esta vía; la variante está cubierta por
  `test_roles_autorizados_atienden_la_identidad_de_sesion` (Administrador, Bodeguero,
  Solicitante parametrizados) en la suite.
- No se provocó en la UI el 409 por departamento sin sede ni el 404 por producto ajeno; ambos
  tienen cobertura HTTP dedicada (§1) y su comportamiento no cambió con la enmienda.

## 3. Humo en 8080 con imagen reconstruida (Paso 3)

Se reconstruyó la imagen porque el modal cambió (`AGENTS.md` §8.6):

```
docker compose -f docker-compose.yml build frontend     # imagen e46b5d390c24, 2026-10-22 18:34
docker compose -f docker-compose.yml up -d frontend     # contenedor Recreated → Started / healthy
```

| Comprobación | Resultado real |
|---|---|
| `GET http://localhost:8080/` | **200**; el `index.html` referencia **`main-QNRFXFUT.js`** (el anterior era `main-KWQKKL6Q.js`) → **8080 sirve el build de la enmienda** |
| Recursos descargados | `main-QNRFXFUT.js` **200**, `styles-EDFQIXBX.css` **200**, `chunk-ZRZHWDIG.js` (`tickets-component`) **200** |
| `/tickets` con la sesión de la Solicitante | tablero cargado; la cookie de Clerk del mismo host se reutilizó (sin volver a iniciar sesión) |
| **«+ Crear Ticket»** | modal abre con **«Solicitante (sesión)» → «Paula Rojas» + correo**; **sin selector**; catálogos cargados (`GET /tickets/catalogos` y `GET /tickets/` **200**) |
| Navegación básica | clic en **Inventario** → `/inventario` con catálogo real (**9 insumos**, 5 con existencias) y enlaces de detalle; sin errores |
| Consola | solo el aviso preexistente de Clerk con claves de desarrollo y el issue preexistente «A form field element should have an id or name attribute». **Sin errores nuevos** |
| Escrituras en el humo | **ninguna** `POST/PUT/PATCH/DELETE` a `localhost:8000` (el alta real se hizo en 4200) |

Capturas: `05-8080-modal-solicitante-sesion.png`, `06-8080-navegacion-inventario.png`.

## 4. Hallazgos

1. **Sin defectos de la enmienda:** el body del alta no incluye `usuario_id`, el servidor
   atribuye la identidad de sesión para Administrador y Solicitante, la institución y la sede
   se derivan de la identidad, y los 8080/4200 coinciden.
2. **Aviso de accesibilidad preexistente** en los campos del formulario («A form field element
   should have an id or name attribute», 8–9 campos): no lo introduce la enmienda y no afecta
   los AC; queda registrado como deuda de UI.
3. El contenedor `frontend` quedó **recreado** por el rebuild; `db` y `backend` no se tocaron.

## 5. Re-ejecución de cierre de enmienda (E22-C1…E22-C3, 22/Oct/2026)

Gates repetidos para no cerrar con resultados heredados:

| Comprobación | Resultado real |
|---|---|
| `backend\.venv\Scripts\python.exe -m pytest` (SQLite en memoria) | **1403 passed, 77 skipped**, 0 failed (297,38 s) |
| `$env:POSTGRES_TEST_URL="postgresql://postgres:postgres@localhost:5433/postgres"` + `pytest` | **1480 passed, 0 skipped**, 0 failed (517,51 s); `apt_erp` intacta (`control.version_esquema = 014.1`, 22 tablas de `control`, 4 esquemas `tenant_*`) y **sin bases temporales residuales** en `pg_database` |
| `$env:CHROME_BIN=…msedge.exe; npx ng test --watch=false --browsers=ChromeHeadless` | **470 SUCCESS / 0 FAILED** (Edge 155.0.0.0) |
| `npx ng build` | **limpio**; entry bundle **`main-QNRFXFUT.js`** (mismo hash que el servido por 8080) |
| `GET /openapi.json` (backend vivo en 8000) | `TicketCrear.required` = `prioridad_id, estado_id, asunto, detalles`; `usuario_id` `anyOf[integer,null]` documentado como ignorado; `TicketDespacho.required` = `usuario_id`; `POST /api/v1/tickets/` → `201,401,403,404,422`; **62** operaciones `/api/v1` |
| `GET http://localhost:8080/` | **200**, `index.html` referencia **`main-QNRFXFUT.js`** → sirve el build de la enmienda (no se reconstruyó: el hash no cambió) |
| `GET http://localhost:4200/` | **200** (dev server vivo) |
| Contraste en BD del recorrido | `ticket 11 → usuario 13, INST-001, sede 1`; `ticket 12 → usuario 11, INST-001, sede 2`; `detalle_ticket 14/15` con `INST-001` |
| `roadmap.md` | sin cambios (`git diff` vacío; último commit `6e2ec6f`, Feature 019): la enmienda no reabre estados |

**Grep de coherencia (`AGENTS.md`, `MEMORY.md`, `.agents/skills/`) ejecutado en el cierre:**
sin rutas ni afirmaciones obsoletas. `AGENTS.md` no menciona selector de solicitante ni
`usuario_id` del alta; `MEMORY.md` (40 líneas) describe la enmienda cerrada con los mismos
números y bundle, sin secretos; `.agents/skills/fastapi-pydantic-v2` solo usa `usuario_id`
en ejemplos de `UsuarioResponse`, ajenos al alta. Nada que corregir.
