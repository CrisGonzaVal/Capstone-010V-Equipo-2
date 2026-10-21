# Feature 018 — Evidencia del recorrido funcional en 4200 (T11)

Spec: [`../spec.md`](../spec.md) · Plan: [`../plan.md`](../plan.md) · Tareas: [`../tasks.md`](../tasks.md)

Fecha del recorrido: **2026-10-21** (UTC, ~20:05–20:30). Frontend dev `npm start`
en `http://localhost:4200`, backend `http://localhost:8000` (contenedor con
`uvicorn --reload` y `./backend/app` montado) y PostgreSQL 16 en `5433`.

## 1. Entorno verificado antes del recorrido

| Comprobación | Resultado real |
|---|---|
| Contenedores | `compustock_db`, `compustock_backend`, `compustock_frontend` **healthy** (5433 / 8000 / 8080) |
| Dev server 4200 | **No estaba corriendo**; se levantó desprendido (`Start-Process` + `npm start` desde `frontend/`) y respondió **200** tras la compilación (31,3 s). Se detuvo al cerrar la tarea |
| `control.version_esquema` | `(1, '014.1', '2026-10-21 00:00:32.570714')` — sin cambios |
| Cuenta Administrador QA | **Existía**: `control.mapa_usuario_esquema` con `admin017.test+clerk_test@example.com → INST-001 / tenant_inst_001_038aa2a9 / activo=t / aceptada` y usuario local `usuario_id 13` («Administrador QA014», rol 2). **No hubo que recrearla** |
| Tenant INST-001 | 2 sedes activas, 7 departamentos activos **todos con sede asignada**, 11 productos (9 activos), 10 filas `stock_sede` (534 unidades) |

Datos con los que se contrasta todo el recorrido (leídos por SQL **solo lectura**,
sin modificar nada):

- **Sede 1 (Sede Providencia)**: productos 1 (Resma, 50/mín 20), 6 (Cinta, 48/mín 12), 2 (Toner HP, 0/mín 10) activos.
- **Sede 2 (Sede Maipu)**: productos 3 (Folder, 200/mín 25), 4 (Bolígrafo, 150/mín 30), 5 (Clip, 35/mín 15), 9 (Rotulador, 6/mín 12), 10 (Papel Premium, 45/mín 10).
- **Sin fila de stock en ninguna sede**: producto 11 (Grapas QA014, activo).
- Departamentos: sede 1 → 1, 3, 5, 7; sede 2 → 2, 4, 6.

## 2. Identidades usadas

Sesiones **reales** de la instancia dev de Clerk `relevant-termite-8089`, iniciadas
en el navegador con la tarjeta prebuilt (correo + **código `424242`**; Clerk pidió
el método «Email code» porque las cuentas tienen contraseña asociada). Ningún
secreto ni token se transcribe en esta evidencia.

| Cuenta Clerk | Rol efectivo (BD real) | Uso |
|---|---|---|
| `admin017.test+clerk_test@example.com` | **Administrador** INST-001 (`usuario_id 13`) | selectores de sede/departamento, indicadores, combinación y limpieza |
| `bodeguero.test+clerk_test@example.com` | **Bodeguero** INST-001 (`usuario_id 12`, sede 2) | ausencia de selector de sede, selector departamental, nota D-3 |
| `solicitante.test+clerk_test@example.com` | **Solicitante** INST-001 (`usuario_id 11`, Biblioteca → sede 2) | ausencia total de selectores y vista operativa intacta |
| `camila.fernandez@losalpes.cl` | **Bodeguero** INST-001 (`usuario_id 1`, **`sede_id` nulo**) | única identidad sembrada de rol operativo **sin sede**: usada solo por API para el 409 |
| `superadmin.test+clerk_test@example.com` | **Superadmin** (`control`) | 403 por API en ámbito y existencias |

Los tokens de las verificaciones por API se emitieron por HTTP con el patrón
documentado en la 013 (§«Cómo se obtuvieron los tokens»): `POST /v1/dev_browser` →
`POST /v1/sign_in_tokens` (Backend API) → `POST /v1/client/sign_ins`
`strategy=ticket` con `Origin: http://localhost:4200` → `last_active_token.jwt`.
**No se creó ni modificó ningún usuario en Clerk ni en la base**, y ninguna
escritura de negocio ocurrió durante la tarea.

## 3. Recorrido en la UI (Administrador)

Vista `/inventario`, pestaña «Existencias», rol `Administrador` / INST-001.

| # | Acción | Resultado real observado | AC | Captura |
|---|---|---|---|---|
| A1 | Abrir `/inventario` sin filtros | Franja **INSUMOS 9 / CON EXISTENCIAS 7 / STOCK CRÍTICO 3**; 9 filas; Grapas QA014 con «Sin existencias registradas», `0`, `Crítico`; cada fila muestra su desglose «EXISTENCIAS POR SEDE» (p. ej. Resma Providencia 50, Folder Maipu 200) | AC-1 (agregado), AC-6 (producto sin stock) | `01-admin-sin-filtros.png` |
| A2 | Inspeccionar los selectores | Existen **`#filtro-sede`** y **`#filtro-departamento`**, cada uno con `<label for>` («Sede» → `filtro-sede`, «Departamento» → `filtro-departamento`) y opción `''` = «Todas las sedes» / «Todos los departamentos» | AC-5 | `01` |
| A3 | Leer las opciones | Sede: `2 Sede Maipu`, `1 Sede Providencia` (**solo INST-001**). Departamento: `3 Administracion`, `6 Biblioteca`, `1 Direccion`, `5 Docencia`, `4 RRHH`, `2 Secretaria`, `7 Servicios Generales` (**los 7 de INST-001**, todos activos y con sede) | AC-4, AC-5, D-5, D-6 | `01` |
| A4 | Elegir **Sede Providencia** en `#filtro-sede` | Franja pasa a **INSUMOS 3 / CON EXISTENCIAS 2 / STOCK CRÍTICO 1**; 3 filas, todas de la sede 1: Cinta Adhesiva `stock_total 48` «Disponible», Resma Carta `50` «Disponible», Toner HP `0` «Crítico». Coincide 1:1 con el SQL de la sede 1 | **AC-1** | `02-admin-sede-providencia.png` |
| A5 | Abrir el selector departamental tras elegir la sede | Las opciones se acotan a los **departamentos de esa sede**: `3 Administracion`, `1 Direccion`, `5 Docencia`, `7 Servicios Generales` (desaparecen Biblioteca/RRHH/Secretaria, que son de sede 2) | **AC-5** | `02` |
| A6 | Elegir departamento **Direccion (1)** | Se consulta `departamento_id=1`; la lista y la franja no cambian (3 insumos, 48/50/0, críticos 1) | AC-2 | — |
| A7 | Cambiar a **Docencia (5)** (misma sede) | Resultado **idéntico** al de Direccion: mismos 3 productos y los mismos saldos físicos de Providencia → un departamento **no** particiona el saldo | **AC-2**, D-2 | `03-admin-departamento-docencia.png` |
| A8 | Cambiar la sede a **Sede Maipu** con Docencia seleccionada | El departamento se **limpia sola** (`#filtro-departamento` vuelve a `''`); las opciones pasan a `6 Biblioteca`, `4 RRHH`, `2 Secretaria`; franja **5 / 5 / 1** con 5 filas de sede 2 (150, 35, 200, 45, 6). En la pestaña Network **no** se envió ningún par incoherente: la petición fue `?sede_id=2` (reqid 66) | **AC-5**, D-4 | `04-admin-cambio-sede-limpia-departamento.png` |
| A9 | Elegir **Secretaria (2)** y después escribir `clip` en la búsqueda y pulsar la categoría **Oficina** | Se envía `?sede_id=2&departamento_id=2` y los tres filtros se aplican a la vez: 1 fila (Clip Métrico) y contadores por categoría «Todas 1 / Oficina 1» | **AC-7** | `05-admin-combinacion-filtros.png` |
| A10 | Marcar **«Solo stock crítico»** con los filtros anteriores | 0 filas y mensaje **«Ningún insumo coincide con los filtros aplicados»** (no el de catálogo vacío) | **AC-6** | `06-admin-vacio-filtrado.png` |
| A11 | Desmarcar críticos y pulsar **«Limpiar filtros»** | Todo vuelve al estado inicial: `#filtro-sede=''`, `#filtro-departamento=''`, búsqueda vacía, checkbox off, 8 opciones departamentales, **9 filas** y franja **9 / 7 / 3** (agregado del rol) | **AC-7** | `07-admin-limpiar-filtros.png` |

Observación (no es defecto): la franja `INSUMOS / CON EXISTENCIAS / STOCK CRÍTICO`
mide el **resultado server-side** cargado, así que con `sede_id` se recalcula sobre
la sede (A4, A8) pero **no** cambia al aplicar búsqueda/categoría, que son filtros de
cliente (A9: franja 5 con 1 fila visible). Ese es el comportamiento previo documentado
en el propio componente («Miden el catálogo CARGADO, no el filtrado») y está fijado
por `inventario.component.spec.ts`; la spec pide que la franja corresponda al ámbito
seleccionado, y así ocurre.

## 4. Recorrido en la UI (Bodeguero)

`bodeguero.test+clerk_test@example.com` → `/inventario`.

| # | Acción | Resultado real observado | AC | Captura |
|---|---|---|---|---|
| B1 | Abrir `/inventario` | **No existe `#filtro-sede`** (`document.getElementById('filtro-sede')` = `null`); solo se renderiza `#filtro-departamento` | **AC-4**, D-3 | `08-bodeguero-nota-y-departamento.png` |
| B2 | Leer la nota | Texto literal junto al selector: «El stock es compartido por la sede. Elegir un departamento no divide ni cambia el saldo; solo muestra productos con stock en esta sede.» | **AC-2**, D-3 | `08` |
| B3 | Leer las opciones departamentales | Solo departamentos de **su sede (2)**: `6 Biblioteca`, `4 RRHH`, `2 Secretaria`. Ninguna opción de sede 1 | **AC-4** | `08` |
| B4 | Estado sin filtro | Franja **9 / 5 / 5** y 9 filas: el agregado permitido por rol es su sede (los productos con saldo solo en Providencia aparecen en 0, p. ej. Cinta Adhesiva «Sin existencias registradas»), comportamiento heredado de la 011 | AC-1 (agregado) | `08` |
| B5 | Elegir **Biblioteca (6)** | Se envía `?departamento_id=6`; 5 filas, todas de **Sede Maipu**, con los saldos físicos de la sede (150, 35, 200, 45, 6) y franja 5 / 5 / 1 | **AC-2** | `09-bodeguero-departamento-biblioteca.png` |
| B6 | Cambiar a **Secretaria (2)** (misma sede) | Resultado **idéntico** al de Biblioteca: mismos 5 productos y mismos saldos → dos departamentos de una sede común dan el mismo stock | **AC-2**, D-2/D-3 | — |

En la pestaña Network de esta sesión: `GET /inventario/ambito` **200** (reqid 243) y
`GET /inventario/existencias` **200** → `?departamento_id=6` **200** (246) →
`?departamento_id=2` **200** (249). Sin 4xx/5xx.

### 4.1 Caso «Bodeguero sin sede» (409) — no reproducible en la UI

No pudo provocarse de forma **no destructiva**: la única identidad operativa sin
sede del tenant es `camila.fernandez@losalpes.cl` (`usuario_id 1`, rol Bodeguero,
`sede_id` nulo), y para verla en el navegador haría falta su credencial (su correo no
es una cuenta de prueba `+clerk_test`, y su única vía sería reasignar/quitar la sede
de otra cuenta: una escritura de datos organizacionales fuera del alcance de T11).
Se verificó entonces **por API con su sesión Clerk real** (ver §6.1): **409** en
`/inventario/ambito` y en `/inventario/existencias` (con y sin `sede_id`). El
componente tiene el estado cubierto por `inventario.component.spec.ts` (T8).

## 5. Recorrido en la UI (Solicitante)

`solicitante.test+clerk_test@example.com` → `/inventario`.

| # | Acción | Resultado real observado | AC | Captura |
|---|---|---|---|---|
| S1 | Abrir `/inventario` | **0 elementos `<select>` en el DOM**: ni selector de sede ni de departamento; tampoco la nota D-3. La búsqueda y las categorías siguen operativas | **AC-7** (visibilidad), D-8 | `10-solicitante-sin-selectores.png` |
| S2 | Estado de la vista | Franja **9 / 5 / 5** y 9 filas (mismo agregado de sede que el Bodeguero: compartió Biblioteca → sede 2) | AC-1 (agregado) | `10` |
| S3 | Red | **Ninguna** llamada a `GET /inventario/ambito`; solo `categorias` y `existencias` **200**. El rol no pide la lectura que no le corresponde | **AC-8** (lado cliente) | — |

## 6. Contraste por API (roles, ámbitos y códigos que la UI no alcanza)

Contra `http://localhost:8000/api/v1` con `curl.exe` y token de sesión real por rol.

### 6.1 Bodeguero sin sede (`camila.fernandez@losalpes.cl`, `usuario_id 1`)

| Petición | Código real | Cuerpo |
|---|---|---|
| `GET /auth/me` | **200** | `usuario_id 1`, `rol:"Bodeguero"`, `institucion: INST-001` |
| `GET /inventario/ambito` | **409** | `{"detail":"El bodeguero no tiene una sede asignada"}` |
| `GET /inventario/existencias` | **409** | ídem |
| `GET /inventario/existencias?sede_id=1` | **409** | ídem — no ofrece sede sustituta |

### 6.2 Administrador (`admin017…`)

| Petición | Código | Resultado |
|---|---|---|
| `GET /inventario/ambito` | **200** | 2 sedes (2 y 1) y 7 departamentos con `sede_id`; solo INST-001 |
| `GET /inventario/existencias?sede_id=1` | **200** | 3 productos: Cinta `stock_total 48` `es_critico false`, Resma `50` `false`, Toner HP `0` `true` |
| `GET /inventario/existencias?sede_id=2` | **200** | 5 productos con sus saldos de Maipu (Rotulador `6` `es_critico true`) |
| `GET /inventario/existencias?sede_id=99999` | **200** | `[]` — el id ajeno/inexistente no se distingue (AC-1/AC-3) |
| `GET /inventario/existencias?sede_id=1&departamento_id=6` | **200** | `[]` — pareja incoherente (departamento de sede 2 con sede 1) |

### 6.3 Solicitante y Superadmin

| Identidad | Petición | Código |
|---|---|---|
| Solicitante | `GET /inventario/ambito` | **403** `Permiso insuficiente para la operacion` |
| Solicitante | `GET /inventario/existencias?sede_id=2` (sede de su departamento) | **200**, 5 productos |
| Solicitante | `GET /inventario/existencias?sede_id=1` (otra sede) | **200** `[]` |
| Superadmin | `GET /inventario/ambito` | **403** |
| Superadmin | `GET /inventario/existencias` | **403** |

## 7. Red observada en el navegador (pestaña Network)

Todas las llamadas nuevas respondieron **200**; **no hubo ningún 4xx ni 5xx** en el
recorrido (el único 4xx del feature es el 409 de la identidad sin sede, que no se
ejecuta desde el navegador).

| reqid | Petición (rol Administrador) | Código |
|---|---|---|
| 51 | `GET /api/v1/inventario/ambito` | **200** |
| 53 | `GET /api/v1/inventario/existencias` | **200** |
| 60 | `GET /api/v1/inventario/existencias?sede_id=1` | **200** |
| 62 | `GET /api/v1/inventario/existencias?sede_id=1&departamento_id=1` | **200** |
| 63 | `GET /api/v1/inventario/existencias?sede_id=1&departamento_id=5` | **200** |
| 66 | `GET /api/v1/inventario/existencias?sede_id=2` | **200** (cambio de sede: el departamento incompatible **no** viaja) |
| 69 | `GET /api/v1/inventario/existencias?sede_id=2&departamento_id=2` | **200** |
| 71 | `GET /api/v1/inventario/existencias` (tras «Limpiar filtros») | **200** |
| — | Cambios de búsqueda/categoría/críticos | **sin** petición (filtros de cliente, como antes de 018) |

Respuesta real de `GET /inventario/ambito` (reqid 51, Admin):

```json
{"sedes":[{"sede_id":2,"sede_nombre":"Sede Maipu"},{"sede_id":1,"sede_nombre":"Sede Providencia"}],
 "departamentos":[{"departamento_id":3,"departamento_nombre":"Administracion","sede_id":1},
   {"departamento_id":6,"departamento_nombre":"Biblioteca","sede_id":2},
   {"departamento_id":1,"departamento_nombre":"Direccion","sede_id":1},
   {"departamento_id":5,"departamento_nombre":"Docencia","sede_id":1},
   {"departamento_id":4,"departamento_nombre":"RRHH","sede_id":2},
   {"departamento_id":2,"departamento_nombre":"Secretaria","sede_id":2},
   {"departamento_id":7,"departamento_nombre":"Servicios Generales","sede_id":1}]}
```

## 8. Capturas

| Archivo | Contenido |
|---|---|
| `01-admin-sin-filtros.png` | Admin, `/inventario`, sin filtros: dos selectores, franja 9/7/3, Grapas QA014 en cero |
| `02-admin-sede-providencia.png` | Admin con `sede_id=1`: 3 filas, franja 3/2/1 y departamentos acotados a la sede |
| `03-admin-departamento-docencia.png` | Admin con `sede_id=1&departamento_id=5`: mismos saldos que con solo la sede |
| `04-admin-cambio-sede-limpia-departamento.png` | Cambio a Sede Maipu: departamento limpiado, opciones nuevas, franja 5/5/1 |
| `05-admin-combinacion-filtros.png` | `sede_id=2&departamento_id=2` + texto `clip` + categoría Oficina: 1 fila |
| `06-admin-vacio-filtrado.png` | Mismo combo + «Solo stock crítico»: «Ningún insumo coincide con los filtros aplicados» |
| `07-admin-limpiar-filtros.png` | Tras «Limpiar filtros»: estado inicial restaurado (9 filas, franja 9/7/3) |
| `08-bodeguero-nota-y-departamento.png` | Bodeguero: sin selector de sede, con selector departamental y la nota literal D-3 |
| `09-bodeguero-departamento-biblioteca.png` | Bodeguero con `departamento_id=6`: 5 filas de Sede Maipu |
| `10-solicitante-sin-selectores.png` | Solicitante: sin selectores ni nota; búsqueda y tabla operativas |

## 9. Hallazgos

1. **Sin defectos.** El comportamiento observado coincide uno a uno con `spec.md`
   §7/§8 y con el SQL de contraste; no se modificó código de la feature.
2. **Franja de indicadores = resultado server-side** (descrito en §3): la franja sigue
   al `sede_id`/`departamento_id`, no a los filtros de cliente. Es el comportamiento
   previo del componente y está cubierto por pruebas; se documenta para que no se lea
   como incoherencia.
3. **Bodeguero y Solicitante sin filtros ven el catálogo completo con ceros** para los
   productos que solo tienen saldo en otra sede (p. ej. Cinta Adhesiva a 0 con
   «Sin existencias registradas»). Es la semántica de alcance heredada de la 011
   (`outerjoin` + intersección por sede), intacta por 018.
4. **409 del Bodeguero sin sede**: verificado por API con sesión real (§6.1); en la UI
   no es reproducible sin una escritura organizacional, que T11 no autoriza.

## 10. Estado de los datos al cerrar

Ninguna escritura de negocio ni SQL de escritura durante la tarea. Contraste
antes/después por SQL de solo lectura:

| Métrica | Antes | Después |
|---|---|---|
| `stock_sede` (filas / unidades) | 10 / 534 | **10 / 534** (mismos `stock_actual` por fila 50, 0, 48, 0, 0, 200, 150, 35, 6, 45) |
| `usuario` (filas / sin sede) | 10 / 7 | **10 / 7** |
| `producto` | 11 (9 activos) | **11** |
| `control.mapa_usuario_esquema` | 14 | **14** |
| `control.version_esquema` | `014.1` | **`014.1`** (mismo timestamp) |

Estado final del navegador: sesión de Solicitante abierta; el dev server de 4200 se
detuvo al cerrar la tarea (T12 reconstruye el frontend para el humo de 8080).

## 11. 8080 — humo tras rebuild (T12, 2026-10-21 ~20:42–20:52 UTC)

El contenedor `frontend` sirve un **build de producción congelado** en la imagen
(AGENTS §5/§8.6), así que el humo exige reconstruir y recrear antes de verificar;
el **backend no** se reconstruye (monta `./backend/app` y corre `uvicorn --reload`).

### 11.1 Rebuild y contenedor

| Paso | Resultado real |
|---|---|
| `docker compose -f docker-compose.yml build frontend` | **sin errores**, `Image evidenciasproyecto-frontend Built` (build Angular de producción, 80,2 s; imagen `sha256:adfa0464…3ceb638`) |
| `docker compose -f docker-compose.yml up -d frontend` | `compustock_frontend` **recreado** y **healthy** (`Up 10 seconds (healthy)`, `0.0.0.0:8080->80/tcp`); `db` y `backend` `Up (healthy)` en 5433/8000 |
| `GET /` en `http://localhost:8080` | **200**, shell SPA (2.554 B) que referencia **`main-7QF7T5XQ.js`** y **`styles-CJEZKEOK.css`** |
| Bundle previo | `GET /main-CVFVAEJC.js` → **404**: el shell ya no lo cita (el hash cambió con el rebuild) |
| Coincidencia con el build local | **`main-7QF7T5XQ.js`** es exactamente el hash que dejó `npx ng build` en T8/T10 (sin deriva de código entre esa verificación y la imagen) |

### 11.2 Humo por rol (MCP `chrome-devtools`, ambos puertos comparten sesión Clerk por `localhost`)

Ruta directa `/inventario` (deep link) servida por el `try_files` de nginx: **200**
(igual que `/login` **200** y cualquier ruta Angular **200** — fallback SPA).

| # | Rol | Acción | Resultado real observado | AC | Captura |
|---|---|---|---|---|---|
| H1 | Administrador | Abrir `http://localhost:8080/inventario` (deep link) | Vista carga; **`#filtro-sede` y `#filtro-departamento`** presentes; franja **INSUMOS 9 / CON EXISTENCIAS 7 / STOCK CRÍTICO 3**; 9 filas | AC-5 | `8080-01-admin-selectores.png` |
| H2 | Administrador | Leer las opciones | Sede: `Sede Maipu`, `Sede Providencia` (solo INST-001); Departamento: los **7** de INST-001 | AC-4, AC-5 | `8080-01` |
| H3 | Administrador | Elegir **Sede Providencia** en `#filtro-sede` | Petición **`GET /inventario/existencias?sede_id=1` → 200** (reqid 1384); franja **3 / 2 / 1**, 3 filas (Cinta, Resma, Toner HP); el selector departamental se acota a los 4 de la sede 1 | **AC-1**, AC-2 | `8080-02-admin-sede-filtrada.png` |
| H4 | Bodeguero | Abrir `/inventario` | **Sin `#filtro-sede`**; **con `#filtro-departamento`** limitado a su sede (Biblioteca, RRHH, Secretaria); **nota literal D-3**; franja 9 / 5 / 5 | **AC-4**, AC-2 (D-3) | `8080-03-bodeguero-departamento.png` |
| H5 | Bodeguero | Elegir **Biblioteca** | Petición **`GET /inventario/existencias?departamento_id=6` → 200** (reqid 1295); 5 filas, franja 5 / 5 / 1 | **AC-2** | `8080-03` |
| H6 | Solicitante | Abrir `/inventario` | **0 elementos `<select>`** en el DOM, sin nota D-3; búsqueda y categorías operativas; franja 9 / 5 / 5 | **AC-7** (D-8) | `8080-04-solicitante-sin-selectores.png` |

Red observada en el navegador (misma pestaña, rol a rol): `GET /inventario/ambito`
**200** y `GET /inventario/existencias` **200** (con y sin `?sede_id=1` /
`?departamento_id=6`, más sus `OPTIONS` **200**); `auth/me`, `categorias` **200**.
**Ningún 4xx ni 5xx** en la carga de la vista (30 peticiones inspeccionadas). El
único 409 del feature sigue siendo el Bodeguero sin sede, ya cubierto por API en §6.1.

### 11.3 Capturas de 8080

| Archivo | Contenido |
|---|---|
| `8080-01-admin-selectores.png` | Admin en 8080: dos selectores, franja 9/7/3 |
| `8080-02-admin-sede-filtrada.png` | Admin con `?sede_id=1`: 3 filas, franja 3/2/1, departamentos acotados |
| `8080-03-bodeguero-departamento.png` | Bodeguero: sin selector de sede, con departamental + nota D-3, `?departamento_id=6` |
| `8080-04-solicitante-sin-selectores.png` | Solicitante: sin selectores ni nota |

### 11.4 Hallazgos de T12

1. **Sin defectos.** La 018 se ve en el 8080 tras el rebuild y el flujo básico por
   rol coincide 1:1 con el recorrido de 4200 (T11 §3–§5). No se modificó código.
2. **4200 no corría durante el humo** (el dev server de T11 ya se había detenido);
   el 8080 se verificó contra el bundle `main-7QF7T5XQ.js` de la imagen reconstruida.
3. **Sesión Clerk compartida por `localhost`**: al ser mismo host, la cookie sirve a
   `4200` y `8080`, así que no hubo que reautenticar por puerto; los cambios de rol
   se hicieron con «Cerrar sesión» + tarjeta prebuilt y código `424242`.
