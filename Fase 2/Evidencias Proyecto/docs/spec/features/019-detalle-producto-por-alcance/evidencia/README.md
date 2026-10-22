# Feature 019 — Evidencia del recorrido funcional en 4200 (T12) y humo en 8080 (T13)

Spec: [`../spec.md`](../spec.md) · Plan: [`../plan.md`](../plan.md) · Tareas: [`../tasks.md`](../tasks.md)

Fecha del recorrido: **2026-10-22**, ~13:37–14:10 local (16:37–17:10 UTC).
Frontend dev `npm start` en `http://localhost:4200`, backend `http://localhost:8000`
(contenedor con `uvicorn --reload` y `./backend/app` montado) y PostgreSQL 16 en `5433`.

> Los artefactos PNG de un intento previo de esta tarea (cancelado) se retiraron y se
> reemplazaron por la secuencia de este recorrido (01…11).

## 1. Entorno verificado antes del recorrido (Paso 0)

| Comprobación | Resultado real |
|---|---|
| `docker compose -f docker-compose.yml ps` | `compustock_db` (5433), `compustock_backend` (8000) y `compustock_frontend` (8080) **Up / healthy** |
| `GET http://localhost:8000/health` | **200** |
| `GET http://localhost:8000/api/v1/inventario/existencias/1` sin token | **401** (no 404: la ruta nueva existe en el backend recargado) |
| `GET http://localhost:4200/` | **200** (dev server `node` ya corriendo desde las 02:34 del 22/Oct; sirve `main.js` + chunks actuales) |
| `GET http://localhost:8080/` | **200** (imagen congelada; el humo es T13) |

## 2. Datos QA de contraste (SQL de solo lectura, sin modificaciones)

INST-001 → `tenant_inst_001_038aa2a9`. Dos sedes **activas**, 7 departamentos activos
(todos con sede), 11 productos (9 activos; **7 y 8 inactivos** con categoría activa),
10 filas `stock_sede`, 534 unidades.

| Producto | Estado | Categoría | Mín. | Stock por sede |
|---|---|---|---|---|
| 1 Resma Carta 75g A4 | activo | Papeleria (activa) | 20 | Providencia **50** |
| 2 Toner HP 26A Negro | activo | Toner y Cartuchos | 10 | Providencia **0** |
| 3 Folder Manila Carta | activo | Organizacion | 25 | Maipu **200** |
| 4 Boligrafo Bic Cristal | activo | Escritura | 30 | Maipu **150** |
| 5 Clip Metrico 33mm | activo | Oficina | 15 | Maipu **35** |
| 6 Cinta Adhesiva 48mm | activo | Limpieza | 12 | Providencia **48** |
| 7 Toner Negro 26A Comp. | **inactivo** | Toner y Cartuchos | 10 | Providencia **0** |
| 8 Grapadora Estandar | **inactivo** | Oficina | 5 | Providencia **0** |
| 9 Rotulador Marcador | activo | Escritura | 12 | Maipu **6** |
| 10 Papel Premium A4 | activo | Papeleria | 10 | Maipu **45** |
| 11 Grapas QA014 | activo | Papeleria | 2 | **sin filas** |

Cuentas usadas: `admin017.test+clerk_test@example.com` (Administrador, usuario 13),
`bodeguero.test+clerk_test@example.com` (Bodeguero, usuario 12, **sede 2**),
`solicitante.test+clerk_test@example.com` (Solicitante, usuario 11, Biblioteca → **sede 2**)
y `superadmin.test+clerk_test@example.com` (Superadmin). Sesiones **reales** de la instancia
dev de Clerk `relevant-termite-8089` con la tarjeta prebuilt y el código de prueba `424242`.
Ningún secreto ni token se transcribe en esta evidencia. No se creó ni modificó ningún
usuario en Clerk ni en la base.

## 3. Recorrido (Paso 2)

### 3.1 Caso 1 — Administrador: Existencias → detalle → «Volver al inventario»

| Paso | Resultado real | AC |
|---|---|---|
| `/inventario`, pestaña **Existencias** | franja **9 / 7 / 3**, 9 filas, dos selectores (Sede y Departamento) | AC-1 |
| Filtrar **Sede Providencia** | `GET /inventario/existencias?sede_id=1` **200**; 3 filas (Cinta 48, Resma 50, Toner 0) | AC-9 |
| Clic en **Resma Carta 75g A4** | `/inventario/1`; petición **`GET /inventario/existencias/1` 200** **sin** `sede_id` ni otros filtros | **AC-9** |
| Detalle | nombre, descripción, «Producto activo», «Categoría activa», Categoría `Papeleria`, unidad `RESMA`, mínimo 20, **STOCK TOTAL 50**, 1 sede, «Disponible», tabla **Sede Providencia 50** | **AC-1** |
| «← Volver al inventario» | URL `/inventario`, pestaña **Existencias** seleccionada (los filtros de lista no viajan en la URL y vuelven a su valor inicial) | **AC-8/AC-9** |

Capturas: `01-admin-existencias-detalle.png`, `02`, `03`.

### 3.2 Caso 2 — Administrador: Gestión → detalle inactivo → vuelta a Gestión

| Paso | Resultado real | AC |
|---|---|---|
| Pestaña **Gestión del catálogo** | panel de ciclo de vida, 15 activos / 2 inactivos; los nombres enlazan a `…/inventario/{id}?tab=gestion` | AC-8 |
| Clic en **Toner Negro 26A Comp.** (id 7, inactivo) | `/inventario/7?tab=gestion`; `GET /inventario/existencias/7` **200** (Admin conserva inactivos) | **AC-3** |
| Detalle | «**Producto inactivo**», «Categoría activa», aviso de solo consulta («…sin acciones de modificación»), total 0, 1 sede, **Sede Providencia 0**, «Crítico»; **sin botones de baja/reactivación ni historial** | **AC-3/AC-10** |
| «← Volver al inventario» | URL **`/inventario?tab=gestion`** y pestaña **Gestión del catálogo** activa | **AC-8/AC-9** |

Capturas: `02-admin-gestion-detalle-inactivo.png`, `03-admin-vuelta-gestion.png`.

### 3.3 Caso 3 — Bodeguero (sede 2)

| Paso | Resultado real | AC |
|---|---|---|
| `/inventario` | 9 filas, sin selector de sede, con selector de departamento y nota de stock compartido | — |
| Clic en **Boligrafo Bic Cristal** (id 4) | `/inventario/4`; **`GET /inventario/existencias/4` 200** → `sedes:[{sede_id:2,"Sede Maipu",150}]`, `stock_total 150`, `es_critico false`; la UI muestra **solo Sede Maipu 150** (no aparece Providencia) | **AC-2, AC-7** |
| Abrir **Resma Carta 75g A4** (id 1, stock solo en sede 1) | total **0**, 0 sedes, «Crítico», mensaje de **vacío** («Sin existencias registradas… este es un resultado vacío, no un error») | **AC-2, AC-6** |
| Abrir **Toner Negro 26A Comp.** (id 7, inactivo) | estado **404** «Producto no encontrado» + botón **Reintentar** | **AC-3, AC-10** |
| «Volver al inventario» | `/inventario` | AC-8 |

Capturas: `04-bodeguero-detalle.png`, `05-bodeguero-sin-existencias.png`, `06-bodeguero-inactivo-404.png`.

### 3.4 Caso 4 — Solicitante (Biblioteca → sede 2)

| Paso | Resultado real | AC |
|---|---|---|
| `/inventario` | **0 selectores** (sin sede ni departamento), 9 filas, nombres enlazables | — |
| Clic en **Boligrafo Bic Cristal** (id 4) | `/inventario/4`; petición 200; UI muestra **solo Sede Maipu 150**, total 150, «Disponible» | **AC-2, AC-7** |

Captura: `07-solicitante-detalle.png`.

### 3.5 Caso 5 — Estados de UI

| Caso | Resultado real | AC |
|---|---|---|
| `/inventario/abc` | mensaje accesible «El identificador del producto no es válido: debe ser un entero positivo.» y **ninguna** petición a `/inventario/existencias/*` (en la pestaña Red solo aparece `auth/me`) | **AC-10** |
| `/inventario/0` | mismo mensaje controlado; **sin** petición al endpoint | **AC-10** |
| `/inventario/99999` (Admin) | **404** «Producto no encontrado» + **Reintentar**; al pulsarlo se emite **una** nueva petición 404 (reqid 1875 → 1876) y **no** hay bucle | **AC-10** |
| `/inventario/11` (Admin, sin `stock_sede`) | 200 con total 0, 0 sedes y estado vacío legible («Sin existencias registradas… este es un resultado vacío, no un error»), distinto de 404 | **AC-6, AC-10** |
| Producto inactivo visible al Admin | «Producto inactivo» explícito y sin controles de modificación (§3.2) | **AC-10** |

Capturas: `08-invalido-abc.png`, `09-id-cero.png`, `10-404-reintento.png`, `11-sin-existencias-admin.png`.

### 3.6 Caso 6 — Sin escrituras

Ventana controlada (carga de `/inventario` + apertura del detalle, Admin). Todas las
peticiones al backend observadas:

| reqid | Petición | Código |
|---|---|---|
| 2360 | `GET /api/v1/auth/me` | 200 |
| 2364 | `GET /api/v1/inventario/ambito` | 200 |
| 2365 | `GET /api/v1/inventario/categorias` | 200 |
| 2366 | `GET /api/v1/inventario/existencias` | 200 |
| 2367 | `GET /api/v1/inventario/gestion` | 200 |
| **2369** | **`GET /api/v1/inventario/existencias/4`** | **200** |

**Cero** `POST`/`PATCH`/`PUT`/`DELETE` hacia `localhost:8000`. (Los `POST …/tokens` que
aparecen en la pestaña Red van al dominio de Clerk y son la renovación de token de la
sesión, no escrituras de negocio.) Consola: **sin errores**; único aviso, el preexistente
de Clerk con claves de desarrollo.

## 4. Caso 7 — API por rol (`http://localhost:8000/api/v1`)

Método: token de la sesión real leído de la cabecera `authorization` de una petición del
navegador y usado con `curl.exe` dentro de su vigencia (~60 s). Ningún token se transcribe.

| Identidad | Petición | Código | Cuerpo / notas |
|---|---|---|---|
| — (sin token) | `GET /inventario/existencias/4` | **401** | — |
| Administrador | `GET /inventario/existencias/4` | **200** | `producto_id 4`, `stock_total 150`, `sedes:[{2,"Sede Maipu",150}]`, `es_critico false` |
| Administrador | `GET /inventario/existencias/1` | **200** | `stock_total 50`, `sedes:[{1,"Sede Providencia",50}]` |
| Administrador | `GET /inventario/existencias/7` (inactivo) | **200** | `activo false`, `stock_total 0`, 1 sede (Providencia 0) |
| Administrador | `GET /inventario/existencias/11` (sin filas) | **200** | `sedes: []`, `stock_total 0`, `es_critico true` (0 ≤ 2) |
| Administrador | `GET /inventario/existencias/99999` | **404** | recurso oculto |
| Administrador | `GET /inventario/existencias/0` | **404** | cero no identifica producto |
| Administrador | `GET /inventario/existencias/abc` | **422** | coerción de tipo |
| Bodeguero | `GET /inventario/existencias/4` | **200** | visto en Red al abrir el detalle (§3.3), solo sede 2 |
| Solicitante | `GET /inventario/existencias/4` | **200** | visto en Red (§3.4), solo sede 2 |
| Superadmin | `GET /inventario/existencias/4` | **403** | `{"detail":"Permiso insuficiente para la operacion"}` |
| Superadmin | `GET /inventario/existencias/99999` | **403** | 403 por matriz **antes** de mirar el producto (precedencia AC-4) |
| Superadmin | `GET /inventario/existencias/abc` | **403** | idem; la autorización precede a la validación de tipo |

## 5. Hallazgos

1. **Sin defectos de la Feature 019.** Todos los casos observados coinciden con `spec.md`
   §6/§7 y con el SQL de contraste; no se modificó código durante la verificación.
2. **Sede inactiva (AC-2):** la semilla QA de INST-001 tiene **ambas sedes activas**, así
   que el caso «sede asignada inactiva → 200» no es reproducible en 4200 sin una escritura
   organizacional (fuera del alcance de una tarea de verificación). Queda cubierto por las
   pruebas de backend de T1/T4.
3. **409 de rol operativo sin sede (AC-5):** el dato existe (`camila.fernandez@losalpes.cl`,
   Bodeguero con `sede_id` nulo, usuario 1), pero **no hay credencial disponible**: su correo
   no es una cuenta `+clerk_test` y no se conoce su contraseña, y quitar la sede de otra
   cuenta sería una escritura organizacional no autorizada en T12. El 409 sigue cubierto por
   `pytest` (T1) y por la evidencia de la 018 (§6.1). **Pendiente de reproducir en UI/API si
   el usuario aporta la credencial.**
4. **No hay producto con stock en ambas sedes** en la semilla, por lo que el desglose
   multi-sede del Administrador no se puede mostrar con un caso real; la no-herencia de
   filtros sí queda probada porque la petición del detalle no lleva `sede_id` (§3.1).
5. **Observación (no defecto):** un `GET /inventario/gestion` se emite al cargar
   `/inventario` para el Administrador aunque la pestaña activa sea Existencias; es el
   comportamiento heredado de T10 (la carga depende de `gestionVisible()`, no de la pestaña).
6. **Observación (no defecto):** al cerrar sesión estando en el detalle, este muestra el
   estado «No autenticado» con Reintentar antes de que el guard redirija a `/login`
   (mapeo del 401, AC-10).

## 6. Estado de los datos al cerrar

Ninguna escritura de negocio ni SQL de escritura durante la tarea.

| Métrica (INST-001) | Antes | Después |
|---|---|---|
| `stock_sede` (filas / unidades) | 10 / 534 | **10 / 534** |
| `producto` (total / activos) | 11 / 9 | **11 / 9** |
| `control.version_esquema` | `014.1` | **`014.1`** |
| `ticket` | 10 | **10** |

Sesión final del navegador: Administrador. El dev server de 4200 sigue en ejecución.

## 7. Recorrido de humo en 8080 con la imagen reconstruida (T13)

Fecha: **2026-10-22**, ~13:48–13:51 local (16:48–16:51 UTC). `AGENTS.md` §8.6: el 8080
sirve un build de producción congelado en la imagen, así que se reconstruyó **antes** de
verificar.

### 7.1 Rebuild de la imagen (obligatorio, orden real)

```
docker compose -f docker-compose.yml build frontend
docker compose -f docker-compose.yml up -d frontend
```

| Comprobación | Resultado real |
|---|---|
| `build frontend` | **OK** — `Application bundle generation complete` en 58.7 s; el log del build ya lista `producto-detalle-component | 8.70 kB` y `chunk-4MWF2NDY.js`; sin errores ni advertencias de presupuesto. Imagen `sha256:0520aefd335b15e0d675c02174a5aa11949b64a74bf296b096554d56be3d9647` (2026-10-22T16:49:31Z). |
| `up -d frontend` | **OK** — `compustock_frontend` recreado y `Started`; queda **Up (healthy)** en `0.0.0.0:8080->80`. `db` y `backend` siguieron corriendo sin cambios. |

### 7.2 Bundle servido: antes vs. después del rebuild

| Artefacto | Antes (imagen vieja) | Después (rebuild 019) |
|---|---|---|
| Entry bundle | `main-7QF7T5XQ.js` | **`main-D6GKPODP.js`** |
| Estilos | `styles-CJEZKEOK.css` | **`styles-EDFQIXBX.css`** |
| Chunk lazy del detalle | **no existía** | **`chunk-4MWF2NDY.js`** (`producto-detalle-component`, 200 en `http://localhost:8080/chunk-4MWF2NDY.js`) |

El HTML de `http://localhost:8080/` referencia `main-D6GKPODP.js`; la pestaña Red del
navegador lo descarga junto a `styles-EDFQIXBX.css` y, al abrir el detalle, el chunk
`chunk-4MWF2NDY.js`. Es decir, **8080 ya sirve el build de la 019**, no el anterior.

### 7.3 Humo del detalle

Sesión: **Administrador** (`admin017.test+clerk_test@example.com`). La cookie de sesión de
Clerk es compartida entre puertos del mismo host, así que el 8080 entró autenticado sin
volver a iniciar sesión; ningún token se transcribe.

| Paso | Resultado real | AC |
|---|---|---|
| Deep link directo `GET http://localhost:8080/inventario/4` | **200** con el `index.html` de Angular (nginx `try_files`, no 404 de nginx ni white screen); el router renderiza el detalle de **Boligrafo Bic Cristal**: `STOCK TOTAL 150`, 1 sede, **Sede Maipu 150**, «Disponible», sin `producto_id`/`institucion_id` en la vista | **AC-1, AC-13** |
| Petición del detalle | **`GET http://localhost:8000/api/v1/inventario/existencias/4` 200** (backend del contenedor, actualizado por volumen) | AC-1 |
| `/inventario` (Existencias) | franja **9 / 7 / 3** y 9 filas; el nombre es enlace con URL `http://localhost:8080/inventario/1`, etc. | **AC-8** |
| Clic en **Resma Carta 75g A4** | navega a **`/inventario/1`** y muestra `STOCK TOTAL 50`, Sede Providencia 50 | AC-8 |
| «← Volver al inventario» | vuelve a **`/inventario`** con la pestaña **Existencias** seleccionada | AC-9 |
| Deep link `GET /inventario/7?tab=gestion` | detalle de **Toner Negro 26A Comp.** con «**Producto inactivo**», aviso de solo consulta, total 0, Sede Providencia 0, «Crítico»; sin controles de baja/reactivación | **AC-3, AC-10** |
| «← Volver al inventario» desde ese detalle | URL **`/inventario?tab=gestion`** y pestaña **Gestión del catálogo** activa (`selected`); el listado de ciclo de vida carga con sus enlaces `…/inventario/{id}?tab=gestion` | **AC-9** |
| `GET /inventario/abc` | mensaje accesible «El identificador del producto no es válido: debe ser un entero positivo.» y **ninguna** petición a `/inventario/existencias/*` (en Red solo `auth/me`) | AC-10 |
| Consola | un único mensaje: el aviso preexistente de Clerk con claves de desarrollo. **Sin errores nuevos.** | AC-13 |
| Escrituras | ninguna petición `POST/PUT/PATCH/DELETE` a `localhost:8000` durante el humo | AC-12 |

Capturas: `12-8080-deep-link-detalle.png`, `13-8080-lista-a-detalle.png`,
`14-8080-detalle-inactivo-tab-gestion.png`, `15-8080-vuelta-gestion.png`,
`16-8080-parametro-invalido.png`.

### 7.4 Hallazgos del humo 8080

1. **Sin defectos de la Feature 019:** el build de producción compila la ruta lazy, nginx
   resuelve el deep link y el detalle consume la API real. Coincide con lo observado en 4200.
2. El detalle autenticado **pudo** verificarse en 8080 (no hizo falta degradar el humo): la
   sesión de Clerk del mismo host se reutilizó. Los roles Bodeguero/Solicitante se
   acreditaron en 4200 (T12); el humo de 8080 se hizo con Administrador.
3. El contenedor `frontend` quedó **recreado** por el rebuild; `db` y `backend` no se
   tocaron.
