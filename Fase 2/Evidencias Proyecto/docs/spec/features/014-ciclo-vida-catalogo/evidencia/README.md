# Feature 014 — Evidencia del recorrido funcional (T14)

Recorrido con **escritura real** contra el backend del contenedor (`uvicorn --reload`,
volumen `./backend/app`) y PostgreSQL QA (`compustock_db` / `apt_erp`, puerto local
5433), tras **recrear el volumen** (`down -v` + `up -d`) para que la base estrene la
estructura y la versión de la 014. Cada efecto se contrastó con **SQL de solo lectura**
por `docker exec … psql`. La UI se recorrió en el dev server **4200** (`npm start`)
con el MCP `chrome-devtools`; el humo de 8080 (rebuild + verificación) está en §6 (T15).

> **Alcance:** `apt_erp` es la base **QA de desarrollo** autorizada. No se operó ningún
> entorno productivo. El reset por recreación de volumen es el flujo normativo de
> AGENTS.md §8.8 (`down -v` + `up -d`), no una migración.

## 1. Reset y estructura verificada (20/Oct/2026, ~21:00 local)

| Hecho | Valor observado |
|---|---|
| Estado previo | `control.version_esquema = 1 | 013.1 | 2026-10-20 05:43:46` (la base seguía en la 013; los gated de T10/T13 usaron bases desechables) |
| `docker compose -f docker-compose.yml down -v` | contenedores detenidos y removidos; volumen `evidenciasproyecto_postgres_data` **removido**; red removida |
| `docker compose -f docker-compose.yml up -d` | `db`, `backend` y `frontend` recreados; los tres **healthy** |
| Logs de initdb | `01_esquema.sql`: `01: tenant tenant_inst_00X_… creado con 19 tablas.` ×4. `02_datos_semilla.sql`: `Semilla QA: base limpia (4 instituciones, tenants vacios), se permite continuar.` y `02: semilla y tenants completados. control + tenants en version 014.1; datos distribuidos por institucion.` Sin `ERROR` |
| Tablas por esquema | `control` = **22**, `tenant_inst_001_038aa2a9` = **19** |
| Versión | `control.version_esquema = (1, '014.1', '2026-10-21 00:00:32.570714')` |
| Historiales de catálogo | **0 filas** en `control` y **0** en el tenant (la semilla no inventa transiciones) |
| Semilla del catálogo | 10 categorías y 10 productos en INST-001, **todos `activo = true`** |
| Backend vivo | `GET /health` → **200**; `GET /openapi.json` → **60 operaciones** `/api/v1/` (las cinco nuevas presentes: dos `PATCH .../estado`, dos `GET .../historial`, `GET /inventario/gestion`) |

## 2. Cuentas y sesiones usadas

Sesiones Clerk **reales** de la instancia dev `relevant-termite-8089`, emitidas por
HTTP con el patrón de la 013 (dev browser → *sign-in ticket* de la Backend API →
`sign_ins` `strategy=ticket` → `last_active_token.jwt`), con `Origin:
http://localhost:4200`. Ningún secreto se escribe en esta evidencia. Para la UI se
usó la tarjeta prebuilt de Clerk con **código de verificación `424242`** de las
cuentas de prueba.

| Cuenta Clerk | Rol efectivo (BD real) | Uso en el recorrido |
|---|---|---|
| `admin017.test+clerk_test@example.com` | **Administrador** de INST-001 (`usuario_id 13`, "Administrador QA014") | todas las transiciones, historial, gestión, 404 de otro tenant |
| `solicitante.test+clerk_test@example.com` | **Solicitante** de INST-001 (`usuario_id 11`, Biblioteca → Sede 2) | alta/edición de ticket, catálogos filtrados, 403 de gestión |
| `bodeguero.test+clerk_test@example.com` | **Bodeguero** de INST-001 (`usuario_id 12`, Sede 2) | avance de estado y despacho, 403 de gestión |
| `superadmin.test+clerk_test@example.com` | **Superadmin** (identidad de control, `usuario_id 13`) | 403 en gestión, historial y lecturas de negocio |

### 2.1 Ajustes de entorno QA (datos, no código)

1. **Cuenta Administrador QA.** La semilla siembra Administradores con correos
   `@losalpes.cl` (existen en Clerk, pero sin credencial de prueba para la UI). Para
   poder recorrer la sección administrativa **también en el navegador** se mapeó la
   identidad Clerk de prueba ya existente `admin017…` a un usuario local
   Administrador de INST-001 y se le dio fila en el mapa de control:
   ```sql
   INSERT INTO tenant_inst_001_038aa2a9.usuario (usuario_id, nombre, apellido, correo,
     departamento_id, rol_id, sede_id) OVERRIDING SYSTEM VALUE
   VALUES (13,'Administrador','QA014','admin017.test+clerk_test@example.com',1,2,NULL);
   INSERT INTO control.mapa_usuario_esquema (correo, institucion_id, nombre_esquema, activo,
     estado_invitacion) VALUES ('admin017.test+clerk_test@example.com','INST-001',
     'tenant_inst_001_038aa2a9',TRUE,'aceptada');
   ```
   `GET /auth/me` → **200** `rol="Administrador"`, `institucion=INST-001`.
2. **Superadmin de una instalación limpia.** La semilla deja `control.usuario` vacía y
   nadie invoca `ejecutar_bootstrap_control` al arrancar (hallazgo vigente desde la
   017). Se ejecutó la propia función dentro del contenedor y se alineó el correo con
   la identidad Clerk de pruebas, igual que en la evidencia 017 §1.1:
   ```sql
   UPDATE control.usuario SET correo='superadmin.test+clerk_test@example.com' WHERE usuario_id=13;
   INSERT INTO control.mapa_usuario_esquema (correo, institucion_id, nombre_esquema, activo,
     estado_invitacion) VALUES ('superadmin.test+clerk_test@example.com','CTRL-SAAS','control',TRUE,'aceptada');
   ```
   No se tocó código ni semilla: es una limitación de despliegue conocida.

## 3. Recorrido por API (escritura real + contraste SQL)

Todos los pasos contra `http://localhost:8000/api/v1`. Instantes de la BD en UTC.
Los códigos son los **devueltos** por el servidor, no los esperados.

### 3.1 Producto: alta, baja, reactivación, idempotencia, motivo e historial

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P01 | `GET /inventario/productos` (Admin) | **200**, 10 productos, todos `activo:true` | AC-15 (base) |
| P02 | `GET /inventario/gestion` (Admin) | **200** `{productos, categorias}` con ambos estados | AC-15 |
| P03 | `POST /inventario/productos` «Grapas QA014» en categoría 1 (activa) | **201** `producto_id=11`, **`activo:true`** | AC-13 |
| P04 | `PATCH /productos/11/estado` `{activo:false, motivo:"Producto duplicado en el catalogo; se retira sin stock"}` | **200**, `activo:false` | AC-7 |
| P05 | `GET /productos/11/historial` | **200**, **1** fila: `historial_producto_id=1`, `usuario_id=13`, `true→false`, motivo literal, actor «Administrador QA014» | AC-7, AC-12 |
| P06 | Repetición `{activo:false}` **sin motivo** | **200** idempotente, `activo:false` | AC-8 |
| P07 | Repetición `{activo:false, motivo:"   "}` | **200** idempotente (el motivo inválido no bloquea la repetición) | AC-8 |
| P08 | `{activo:true, motivo:"Se reincorpora a pedido del area de compras"}` | **200**, `activo:true`; historial **2** filas | AC-7 |
| P09 | Repetición `{activo:true, motivo:""}` | **200** idempotente; historial sigue **2** | AC-8 |
| P10 | `{activo:false, motivo:"   "}` (transición real) | **422** `El motivo no puede estar vacio ni contener solo espacios`; producto sigue activo, historial 2 | AC-3, AC-7 |
| P11 | `{activo:false, motivo:"x"×501}` | **422** `El motivo no puede superar los 500 caracteres`; sin escritura | AC-7 |
| P12 | `PATCH /productos/999999/estado` con motivo vacío | **404** `Producto no encontrado` (el 404 precede al 422) | AC-3 |
| P13 | Cuerpo `{motivo}` sin `activo` | **422** `Field required` (contrato Pydantic) | AC-14 (contrato) |
| P14 | `{activo:false, motivo:"Cierre del recorrido: producto QA sin saldo"}` | **200**, `activo:false` | AC-5/AC-8 |
| P15 | `GET /productos/11/historial` | **200**, **3** filas en orden `fecha_transicion DESC, id DESC` (ids 3, 2, 1) con actor/origen/destino/motivo | AC-7, AC-12 |
| P16 | `GET /inventario/productos` | **200**, producto 11 **ausente** | AC-4 |
| P17 | `GET /inventario/existencias` | **200**, producto 11 **ausente** | AC-4 |
| P18 | `GET /inventario/gestion` | **200**, producto 11 presente con `activo:false` | AC-15 |

### 3.2 Saldo cero y movimientos

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P19 | `PATCH /productos/3/estado` (saldo 200 en Sede Maipu) | **409** `No se puede desactivar un producto con saldo distinto de cero en stock por sede`; stock y producto intactos | AC-6 |
| P20 | `POST /inventario/movimientos` SALIDA 1 de `stock_sede_id=5` (producto 8) | **201** `{"message":"Movimiento registrado exitosamente","nuevo_stock":0}` | AC-6 (prep.) |
| P21 | `PATCH /productos/8/estado` con motivo | **200**, `activo:false` (saldo cero) | AC-6 |
| P22 | `POST /inventario/movimientos` ENTRADA 2 sobre el producto 8 ya inactivo | **409** `No se puede registrar un movimiento sobre un producto inactivo`; sin auditoría | AC-9 |

### 3.3 Categoría y dependencias

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P23 | `PATCH /categorias/2/estado` (productos 2 y 7 activos) | **409** `No se puede desactivar una categoria con productos activos` | AC-5 |
| P24 | Solicitante: `POST /tickets/` con productos 7 ×2 y 3 ×1 | **201** `ticket_id=9`, `estado_id=1`, `sede_id=2` | AC-9 (prep.) |
| P25 | SALIDA 18 de `stock_sede_id=2` (producto 2) | **201**, `nuevo_stock=0` | AC-6 |
| P26 | SALIDA 3 de `stock_sede_id=4` (producto 7) | **201**, `nuevo_stock=0` | AC-6 |
| P28 | `PATCH /productos/2/estado` baja | **200**, `activo:false` | AC-5 |
| P29 | `PATCH /productos/7/estado` baja | **200**, `activo:false` | AC-5 |
| P31 | `PATCH /categorias/2/estado` baja (sin productos activos) | **200** `{"categoria_id":2,…,"activo":false}` | AC-5, AC-7 |
| P32 | `POST /inventario/productos` en la categoría 2 inactiva | **409** `No se puede crear un producto en una categoria inactiva`; sin escritura | AC-13 |
| P33 | `PATCH /productos/2/estado` `{activo:true}` con la categoría inactiva | **409** `No se puede reactivar un producto cuya categoria esta inactiva`; sin historial | AC-5 |
| P34 | `PATCH /categorias/2/estado` reactivación | **200**, `activo:true` | AC-5 |
| P35 | `PATCH /productos/2/estado` reactivación | **200**, `activo:true` | AC-5 |
| P36 | `GET /categorias/2/historial` | **200**, **2** filas (true→false y false→true) con motive literal | AC-12 |
| P37 | `GET /productos/2/historial` | **200**, **2** filas | AC-12 |

La reactivación de la categoría **no** reactivó el producto 7: la fila de categoría 2
quedó `activo=true` mientras el producto 7 siguió `activo=false` (SQL §4). El producto
2 se reactivó aparte (P35), como exige D-5.

### 3.4 Tickets, movimientos y despacho

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P38 | Solicitante: `GET /tickets/9` | **200**; el detalle resuelve el producto 7 **inactivo** con nombre, descripción y unidad | AC-4 (histórico) |
| P39 | `PUT /tickets/9` conservando producto 7 con cantidad 2→5 (más producto 3 ×1) | **200**; detalles 7×5 y 3×1; estado/solicitante/sede intactos | AC-9 |
| P40 | `PUT /tickets/9` añadiendo el producto 11 (**inactivo**, no presente) | **409** `El producto indicado no esta disponible: 11`; detalles previos intactos | AC-9 |
| P41 | `POST /tickets/` con el producto 7 inactivo | **409** `El producto indicado no esta disponible: 7`; sin ticket creado | AC-9 |
| P42 | `GET /tickets/catalogos` (Solicitante) | **200**, productos `[4,6,5,3,10,1,9,2]`: **sin** 7 ni 11 (inactivos) | AC-4 |
| P43a/b | Bodeguero: `PATCH /tickets/9/estado` 1→2 y 2→3 | **200**, **200** (`estado_id=3`); el flujo solo admite pasos contiguos | AC-9 (despacho) |
| P44 | `POST /tickets/9/despacho` | **409** `Stock insuficiente para el producto 7: requerido 5, disponible 0`; sin rebaja parcial | AC-9 |
| P45 | `GET /tickets/9` | **200** `estado_id=3`, `fecha_cierre=null`; los dos detalles siguen con `cantidad_entregada=0` | AC-9 |

### 3.5 Dashboard y alertas

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P27 | `GET /dashboard/` (Admin) con productos 2 y 7 en 0 y sus mínimos en 10 | **200** `total_alertas=3`, `alertas` incluye «Toner HP 26A Negro» (0/10) y «Toner Negro 26A Comp.» (0/10) | AC-10 (base) |
| P30 | `GET /dashboard/` tras retirar ambos productos | **200** `total_alertas=1`; las dos filas desaparecen y solo queda «Rotulador Marcador» (6/12). `unidades_en_stock=534` y `tickets_activos=7` no cambian | AC-10 |

### 3.6 Roles, aislamiento y ocultamiento

| # | Acción | Resultado real | AC |
|---|---|---|---|
| P46–P48 | Solicitante: `GET /inventario/gestion`, `PATCH /productos/11/estado`, `GET /productos/11/historial` | **403** ×3 `Permiso insuficiente para la operacion` | AC-2, AC-15 |
| P49–P51 | Bodeguero: las mismas tres | **403** ×3 | AC-2, AC-12 |
| P52–P54 | Superadmin: gestión, mutación e historial | **403** ×3 | AC-2, AC-15 |
| P55 | Superadmin: `GET /dashboard/` | **403** (superficie de negocio retirada desde la 017) | AC-2 |
| P56 | Admin INST-001: `PATCH /inventario/productos/12/estado` (**id 12 de INST-002**) | **404** `Producto no encontrado` | AC-2 |
| P57 | `GET /inventario/productos/12/historial` | **404** con el **mismo** `detail` | AC-12 |
| P58 | `PATCH /inventario/productos/999999/estado` | **404** `Producto no encontrado` (idéntico al ajeno) | AC-2, AC-12 |

## 4. Contraste en PostgreSQL (solo lectura, tras el recorrido)

```
producto (INST-001)          = 11 filas; activos 9 (1,2,3,4,5,6,9,10,11) / inactivos 2 (7,8)
categoria (INST-001)         = 6 filas; todas activas (la 2 se reactivó en P34)
stock_sede (INST-001)        = 10 filas (ninguna borrada)
   producto 2 = 0 | producto 7 = 0 | producto 8 = 0 | producto 3 = 200 (intacto)
movimiento_inventario        = 13 filas = 10 de la semilla + 3 SALIDA auditadas (ids 11–13)
   id 11 SALIDA 1 stock_sede 5  «Liquidacion para retirar el producto 8 (recorrido 014)»
   id 12 SALIDA 18 stock_sede 2 «Liquidacion para retirar el producto 2 (recorrido 014)»
   id 13 SALIDA 3 stock_sede 4  «Liquidacion para retirar el producto 7 (recorrido 014)»
historial_transicion_producto = 8 filas (producto 11 ×4, producto 8 ×1, producto 2 ×2, producto 7 ×1)
historial_transicion_categoria = 2 filas (categoria 2: true→false y false→true)
ticket 9                     = estado 3 (EnCurso), fecha_cierre NULL
   detalle 11: producto 7 ×5 entregado 0 | detalle 12: producto 3 ×1 entregado 0
detalle_ticket               = 10 filas (8 de la semilla + 2 del ticket 9)
ticket                       = 9 filas (8 + el del recorrido); ningún ticket borrado
```

Consultas literales de cierre:

```sql
-- estados
SELECT producto_id, nombre, activo FROM tenant_inst_001_038aa2a9.producto ORDER BY 2;
--  1 Resma… t | 2 Toner HP… t | 3 Folder… t | 4 Boligrafo… t | 5 Clip… t | 6 Cinta… t
--  7 Toner Negro 26A Comp. f | 8 Grapadora Estandar f | 9 Rotulador… t | 10 Papel Premium… t
--  11 Grapas QA014 t
SELECT categoria_id, nombre_cat, activo FROM tenant_inst_001_038aa2a9.categoria ORDER BY 2;
--  las 6 en true

-- historiales (actor 13 en todas; motivos libres literales)
SELECT historial_producto_id, producto_id, activo_origen, activo_destino, motivo
  FROM tenant_inst_001_038aa2a9.historial_transicion_producto ORDER BY 1;
SELECT historial_categoria_id, categoria_id, activo_origen, activo_destino, motivo
  FROM tenant_inst_001_038aa2a9.historial_transicion_categoria ORDER BY 1;
```

**Conservación (AC-1):** la baja de los productos 2, 7, 8 y 11 no borró ninguna fila de
`producto`, `stock_sede`, `movimiento_inventario` ni `detalle_ticket`; los movimientos
históricos y los detalles del ticket 9 siguen resolviendo producto y categoría
(aunque estén inactivos). La categoría 2 retirada conservó sus dos productos con su
`categoria_id`.

**Aislamiento:** `tenant_inst_002_5efdced3` conserva 4 productos y 4 categorías, todas
activas, y **0** filas en sus dos historiales: el recorrido no tocó otro tenant.

## 5. Recorrido en 4200 (UI, MCP `chrome-devtools`)

Dev server `npm start` → `Initial total 154.79 kB`; lazy `inventario-component`
58.49 kB, `ticket-detalle-component` 64.98 kB, `tickets-component` 48.55 kB.

| # | Rol | Paso | Resultado observado | AC |
|---|---|---|---|---|
| U1 | Administrador | `/login` con la tarjeta prebuilt de Clerk (correo + código `424242`) | Aterriza en `/dashboard`; cabecera `Rol: Administrador`, `Institución: Instituto Profesional Los Alpes`; menú con Dashboard/Inventario/Tickets/Administración | — |
| U2 | Administrador | `/inventario` | Aparece la región **«Ciclo de vida del catálogo»** con contadores `ACTIVOS 14 / INACTIVOS 3`, 6 categorías (todas con «Dar de baja» + «Historial»), 11 productos con badge `Activo/Inactivo` y acción coherente (`Dar de baja` para activos, `Reactivar` para inactivos). La tabla operativa muestra **8** insumos (excluye los 3 inactivos) | AC-11, AC-15 |
| U3 | Administrador | «Reactivar el producto Grapas QA014» → «Confirmar» con motivo vacío | `role="alert"` «El motivo es obligatorio para cambiar el estado.»; no se envía petición | AC-11 |
| U4 | Administrador | Mismo formulario con motivo `"Reactivacion aprobada en el recorrido de la Feature 014 (UI)"` | `role="status"` «Estado actualizado: «Grapas QA014» ahora está activo.»; contadores pasan a `ACTIVOS 15 / INACTIVOS 2` (9 productos + 6 categorías activos) y el producto reaparece en la tabla operativa con `Crítico` (0/2). **SQL:** nueva fila `historial_producto_id=8`, `false→true`, actor 13, motivo literal | AC-7, AC-11 |
| U5 | Administrador | «Dar de baja el producto Resma Carta 75g A4» con motivo | `role="alert"` con el `detail` del servidor: «No se puede desactivar un producto con saldo distinto de cero en stock por sede»; el producto y el stock no cambian | AC-6, AC-11 |
| U6 | Administrador | «Ver el historial del producto Grapas QA014» | Panel «Historial de «Grapas QA014»» con 4 entradas en orden reciente→antiguo: `Inactivo → Activo` (la de la UI), `Activo → Inactivo`, `Inactivo → Activo`, `Activo → Inactivo`, cada una con actor, fecha y motivo | AC-11, AC-12 |
| U7 | Solicitante | `/inventario` | **No** se renderiza la sección de gestión ni botones de mutación; la tabla operativa conserva su alcance (9 insumos activos, `Cinta Adhesiva` aparece como «Sin existencias registradas» porque su sede no está en el alcance del Solicitante) | AC-11 |
| U8 | Solicitante | `/tickets` → «+ Crear Ticket» | El selector de ítems ofrece **9** productos activos; **no** aparecen «Toner Negro 26A Comp.» ni «Grapadora Estandar» (inactivos) | AC-4, AC-9 |
| U9 | Solicitante | `/tickets/9` | El detalle resuelve «Toner Negro 26A Comp.» ×5 como ítem histórico, con su historial de transiciones (Pendiente → EnRevision → EnCurso) | AC-4 |
| U10 | Bodeguero | `/inventario` | **No** hay sección de gestión ni acciones de mutación; menú sin «Administración»; tabla operativa con 9 insumos y 5 críticos de su sede | AC-11, AC-15 |

(1) Los contadores del listado de gestión incluyen productos **y** categorías: 15 = 9
productos activos + 6 categorías activas; 2 inactivos = productos 7 y 8.

Capturas: `4200-inventario-administrador-gestion.png`,
`4200-historial-producto.png`, `4200-inventario-bodeguero-sin-gestion.png`.

**Consola del navegador:** sin errores de la 014. Solo aparecen los avisos de keys de
desarrollo de Clerk, el `409` deliberado de U5 (recurso esperado) y un aviso de
accesibilidad «A form field element should have an id or name attribute» que
corresponde al buscador operativo de inventario (previa a la 014), no al formulario
de motivo (que sí lleva `id="motivo-transicion"` y su `<label for>`).

## 6. Humo en 8080 tras rebuild (T15, 21/Oct/2026 ~00:39 local)

El contenedor `frontend` sirve un **build congelado en la imagen** (nginx, sin volumen
montado), así que traía el bundle de la 017 (`main-AQPZZQO7.js`). Se reconstruyó la
imagen y se recreó el contenedor antes de mirar nada (AGENTS.md §5/§8.6).

| Hecho | Valor observado |
|---|---|
| Imagen previa | `main-AQPZZQO7.js` (bundle de la 017, sin la 014) |
| `docker compose -f docker-compose.yml build frontend` | `Application bundle generation complete. [53.064 seconds]`; `Output location: /app/dist/frontend-app`; imagen `evidenciasproyecto-frontend:latest` construida (`sha256:a53269a6…`) |
| `docker compose -f docker-compose.yml up -d frontend` | `compustock_frontend` **Recreated** → **Started**, `Up 8 seconds (healthy)`, `0.0.0.0:8080->80/tcp`; `db` y `backend` sin tocar (el backend sí recarga por volumen) |
| **Bundle servido** | **`main-GVEDOJ7X.js`** + `styles-VAQIYPGO.css` (el anterior ya no se referencia) |
| Chunk lazy de inventario | `chunk-4MTWHQKY.js` (26,0 kB): contiene «Ciclo de vida del catálogo», `inventario/gestion`, `historial` (22 referencias) y las rutas `/estado` |
| Código de la sección en la imagen | verificado con `grep` dentro del contenedor: la cadena vive en el chunk del componente, no en el shell |

### 6.1 Recorrido de humo (MCP `chrome-devtools`, `http://localhost:8080`)

La sesión Clerk de la 4200 se reutilizó en 8080 sin volver a autenticar (la cookie de
sesión es de `localhost`, no del puerto). Después se cerró sesión y se entró de nuevo
con la tarjeta prebuilt (correo + código `424242`) para probar el rol no-Administrador.

| # | Rol | Paso | Resultado observado | AC |
|---|---|---|---|---|
| S1 | Administrador | `/inventario` en 8080 | Se renderiza la región **«Ciclo de vida del catálogo»** con contadores `ACTIVOS 15 / INACTIVOS 2`, 6 categorías con badge `Activa` y botones «Dar de baja»/«Historial», y 11 productos con badge `Activo`/`Inactivo` y acción coherente («Reactivar» en los 2 retirados). La tabla operativa sigue con **9** insumos | AC-11, AC-15 |
| S2 | Administrador | Red | `GET /api/v1/inventario/gestion` → **200**; `…/categorias` **200**; `…/existencias` **200**; `/auth/me` **200**. Ningún **4xx/5xx** entre las 25 peticiones de la carga de la vista de Administrador | AC-11 |
| S3 | Administrador | «Ver el historial del producto Grapas QA014» | Panel «Historial de «Grapas QA014»» con las 4 transiciones (dos `Inactivo → Activo`, dos `Activo → Inactivo`), cada una con actor, fecha y motivo literal. La lectura respondió **200** | AC-11, AC-12 |
| S4 | Solicitante | Cerrar sesión → tarjeta Clerk (`solicitante.test+clerk_test@example.com`, código `424242`) → `/inventario` | **No** hay región de gestión ni botones de mutación; la tabla operativa carga con normalidad. Menú sin «Administración». Red: **ninguna** llamada a `/inventario/gestion` | AC-11 |

Nota: al cerrar sesión estando en `/inventario`, la vista alcanza a pintar el aviso genérico
«No se pudo contactar el backend (401)» antes de que el guard redirija a `/login`. Es el
manejo de 401 **preexistente** de la app (el texto no es de la 014) y no afecta al humo.

**Consola del navegador (8080):** solo dos mensajes en toda la sesión — el aviso de
_claves de desarrollo_ de Clerk y el aviso de accesibilidad «A form field element should
have an id or name attribute» del buscador operativo (ambos preexistentes y ya anotados
en §5). Ningún error atribuible a la 014.

Captura: `8080-inventario-administrador-gestion.png` (sección con ambos estados, rol
Administrador, bundle nuevo).

## 7. Mapeo AC → evidencia

| AC | Evidencia de recorrido | Evidencia automatizada (T13) |
|---|---|---|
| AC-1 | §4: sin borrados; referencias, saldos, movimientos y detalles intactos; historiales solo añaden filas | `test_ciclo_vida_catalogo_estado_014.py` (`baja_conserva_referencias…`, `no_existe_operacion_de_borrado_fisico_ac_1`); OpenAPI sin `DELETE` |
| AC-2 | D9–D14: 403 de Solicitante/Bodeguero/Superadmin; P56–P58: 404 idéntico ajeno/inexistente | `test_ciclo_vida_autorizacion_014.py`; gated de matriz 60 |
| AC-3 | P10–P12: 422 de motivo y 404 previo; P40/P41: 409 sin escritura; P19/P23/P32/P33: 409 sin mutación | `test_ciclo_vida_catalogo_estado_014.py` (orden 404→200→422→409) |
| AC-4 | P16/P17 (operativas sin inactivos), P38/P42 (histórico y catálogos), P30 (dashboard), U8/U9 | `test_ciclo_vida_operativas_014.py`, `test_ciclo_vida_operativas_servicio_014.py`, specs de tickets |
| AC-5 | P23, P31–P35: dependencia de categoría, no cascada y reactivación en orden | `test_ciclo_vida_catalogo_014.py` (servicio, AC-5) |
| AC-6 | P19 (409 con saldo), P21 (200 con saldo 0), P20/P25/P26 (liquidación auditada); concurrencia real en gated | `test_ciclo_vida_catalogo_postgres_014.py` (AC-6, 4 anillos + rollback) |
| AC-7 | P04/P05/P08/P15/P36/P37 y U4/U6: motivo obligatorio y una fila por transición real | `test_ciclo_vida_catalogo_estado_014.py`, `test_ciclo_vida_catalogo_014.py` |
| AC-8 | P06/P07/P09: 200 idempotente sin motivo ni historial | `test_ciclo_vida_catalogo_estado_014.py` (idempotencia), servicio |
| AC-9 | P22 (movimiento 409), P39/P40/P41 (edición conserva, rechaza nuevo, alta 409), P43–P45 (despacho 409 sin efectos), U8/U9 | `test_ciclo_vida_operativas_014.py`, `test_ciclo_vida_operativas_servicio_014.py`, `ticket-detalle.component.spec.ts` |
| AC-10 | P27 vs P30: alertas y conteo excluyen inactivos sin cambiar otros KPI | `test_ciclo_vida_operativas_014.py` (dashboard), `services/test_ciclo_vida_operativas_servicio_014.py` |
| AC-11 | U1–U7, U10 y capturas: sección solo Administrador, motivo, estado, historial, 409/422 visibles. §6 S1–S4: la misma sección en el **build de producción** (8080) y oculta para Solicitante | `inventario.component.spec.ts` (bloques AC-11/AC-15), `roles.spec.ts` |
| AC-12 | P05/P15/P36/P37 (orden y campos), P48/P51/P54, P57 (404 oculto), U6 | `test_ciclo_vida_catalogo_estado_014.py`, autorización 014; OpenAPI historiales solo `GET` |
| AC-13 | P03 (nace activo), P32 (409 en categoría inactiva), P14/P21 | `test_ciclo_vida_catalogo_estado_014.py` (`producto_nuevo_nace_activo_ac_13`) |
| AC-14 | §1: 22/19 tablas, versión `014.1`, historiales vacíos; `/openapi.json` 60 operaciones | `test_esquema_postgres.py`, `test_instalacion_limpia_postgres.py`, T13 OpenAPI |
| AC-15 | P02/P18 (ambos estados), D9/D13 (403), U2 (sección alimentada por gestión; operativa filtrada) | `test_ciclo_vida_catalogo_estado_014.py`, `inventario.component.spec.ts` |
| AC-16 | No se repite aquí: la carrera categoría/producto se acredita en PostgreSQL 16 con dos conexiones | `test_ciclo_vida_catalogo_postgres_014.py` (categoría vs alta y vs reactivación) — **26 passed** en T13 |

## 8. Datos residuales del recorrido en `apt_erp` (QA, sin borrado)

- **Producto 11 «Grapas QA014»** (Papeleria), activo, sin filas en `stock_sede`.
- **Productos 7** («Toner Negro 26A Comp.») y **8** («Grapadora Estandar») **inactivos**
  con saldo 0; el producto 2 («Toner HP 26A Negro») quedó **reactivado** con saldo 0 y
  por tanto vuelve a figurar en alertas de stock.
- **3 movimientos SALIDA** auditados (ids 11–13) que liquidaron 1, 18 y 3 unidades.
- **10 filas de historial** (8 de producto, 2 de categoría), todas con actor 13 y motivo
  literal.
- **Ticket 9** (EnCurso) del Solicitante QA con un ítem del producto 7 ya retirado y
  `cantidad_entregada=0`.
- Usuario local **13 «Administrador QA014»** en INST-001 y su fila en el mapa de control;
  identidad Superadmin de control con el correo de pruebas.
- Las instituciones INST-002/003/004 y la semilla de INST-001 (fuera de lo anterior)
  quedaron intactas.

## 9. Hallazgos

1. **La base QA estaba en `013.1`.** No es un defecto: los gated de T10/T13 usan bases
   desechables. El reset por recreación de volumen (§1) es lo que la deja en `014.1`
   con 22/19 tablas, y es el paso obligatorio antes de cualquier recorrido de la 014.
2. **Falta una cuenta Administrador de prueba en la semilla.** Los Administradores
   sembrados usan correos institucionales sin credencial de prueba para la UI. Se
   resolvió mapeando una identidad Clerk `+clerk_test` existente a un usuario local
   Administrador (§2.1). Si se quiere un clon «listo para recorrer», la semilla (o una
   feature posterior) debería sembrar un Administrador con correo `+clerk_test`.
3. **La instalación limpia no crea al Superadmin** (hallazgo heredado de la 017): se
   ejecutó `ejecutar_bootstrap_control` a mano y se alineó el correo. Los 403 de
   Superadmin del §3.6 se verificaron con esa identidad.
4. **El flujo de estados del ticket exige pasos contiguos.** La primera prueba de
   despacho desde `Pendiente` respondió 409 «El ticket no esta en 'EnCurso'» (comportamiento
   correcto de la 013). El recorrido se rehizo pasando por `EnRevision` antes de
   `EnCurso` (P43a/P43b) para llegar al 409 de stock insuficiente que exige AC-9.
5. **Aviso de accesibilidad preexistente:** el buscador operativo de inventario no
   declara `id`/`name` (la consola lo señala una vez). No es de la 014 ni bloquea
   ningún AC; queda anotado para una limpieza de UI.
6. **Sin defectos de la Feature 014.** No se modificó código ni tests durante T14. Las suites se
   volvieron a ejecutar al cerrar la tarea y siguen verdes: `pytest` SQLite **1290 passed /
   70 skipped / 0 failed** (193,46 s), `ng test` (`CHROME_BIN`=Edge, `--watch=false
   --browsers=ChromeHeadless`) **392 SUCCESS / 0 FAILED**. Los gated PG16 (70 passed) y el
   `ng build` limpio son los de T13: no hubo cambios de código ni de DDL.

## 10. Enmienda de UI posterior al cierre: inventario en dos pestañas (T17, 21/Oct/2026)

Enmienda aprobada de **AC-11** (solo presentación, sin tocar servicio, endpoints,
autorización ni reglas): la vista de inventario se divide en las pestañas
**«Existencias»** (operativa, seleccionada por defecto para todos los roles) y
**«Gestión del catálogo»** (solo Administrador). Bodeguero y Solicitante no ven el
conmutador ni una pestaña vacía: reciben directamente la vista operativa.

### 10.1 Suites y build

| Verificación | Resultado |
|---|---|
| `npx ng test --watch=false --browsers=ChromeHeadless` (`CHROME_BIN`=Edge) | baseline **392 SUCCESS** → **396 SUCCESS / 0 FAILED** (4 casos nuevos de pestañas) |
| `npx ng build` | limpio, `Application bundle generation complete` en **28,9 s**; inicial 329,10 kB / 91,56 kB estimado; `inventario-component` 29,16 kB |

### 10.2 Recorrido en 4200 (MCP `chrome-devtools`)

| # | Rol | Paso | Resultado observado | AC |
|---|---|---|---|---|
| T1 | Administrador | `/inventario` | El conmutador muestra **«Existencias»** (seleccionada) y **«Gestión del catálogo»**; la pestaña por defecto trae la franja `INSUMOS 9 / CON EXISTENCIAS 7 / STOCK CRÍTICO 3`, el panel de categorías con sus conteos, el buscador/filtro y la tabla con **9** filas. Ninguna llamada extra: `categorias`, `existencias` y `gestion` | AC-11 |
| T2 | Administrador | Pestaña «Gestión del catálogo» | Se oculta el panel operativo y aparece la región «Ciclo de vida del catálogo» con `ACTIVOS 15 / INACTIVOS 2`, 6 categorías y 11 productos con su badge y acciones. `aria-selected` conmuta entre las dos pestañas | AC-11, AC-15 |
| T3 | Administrador | «Reactivar» «Grapadora Estandar» con motivo «Verificación enmienda pestañas T17» | `role="status"` «Estado actualizado: «Grapadora Estandar» ahora está activo»; contadores 15/2 → **16/1**; la fila pasa a `Activo` | AC-11, AC-12 |
| T4 | Administrador | «Dar de baja» del mismo producto con motivo «Reversión tras verificación de la enmienda T17» | `role="status"` «… ahora está inactivo»; contadores **15/2** (estado restituido al de partida) | AC-11, AC-12 |
| T5 | Solicitante | Cerrar sesión → tarjeta Clerk (`solicitante.test+clerk_test@example.com`, código `424242`) → `/inventario` | **Sin** conmutador (`[role="tablist"]` ausente, 0 pestañas), sin «Gestión del catálogo» ni «Ciclo de vida del catálogo»; el panel `#panel-existencias` pinta la tabla con **9** filas y ninguna acción de mutación. Red: **ninguna** llamada a `/inventario/gestion` | AC-11 |

Capturas: `4200-inventario-pestanas-existencias.png`, `4200-inventario-pestanas-gestion.png`,
`4200-inventario-pestana-unica-solicitante.png`.

### 10.3 Rebuild y humo en 8080

| Hecho | Valor observado |
|---|---|
| `docker compose -f docker-compose.yml build frontend` | `Image evidenciasproyecto-frontend Built` (imagen `0f61e881…`); el contenedor sirve el build nuevo tras `up -d frontend` → **Recreated/Started**, `healthy`, `0.0.0.0:8080->80/tcp` |
| **Bundle servido** | `main-24CPLXSZ.js` + `styles-UDHSLMVH.css` (antes `main-GVEDOJ7X.js` de T15) |
| Chunk de inventario | `chunk-Q3MWJNJM.js` (29,2 kB) — coincide con el chunk generado por `ng build` local; verificado con `grep 'pestana-gestion'` **dentro** del contenedor |
| Humo Solicitante (sesión compartida de `localhost`) | `[role="tablist"]` ausente, `#panel-existencias` con **9** filas; `gestionTexto: false`; red solo `…/inventario/categorias` y `…/inventario/existencias` |
| Humo Administrador (login real, tarjeta `+clerk_test` y `424242`) | Dos pestañas con «Existencias» seleccionada por defecto y `#panel-existencias` con 9 filas; `GET /inventario/gestion` **200**. Al pulsar «Gestión del catálogo»: `#panel-gestion` visible, `#panel-existencias` fuera del DOM, `ACTIVOS 15 / INACTIVOS 2`, 11 productos |
| Consola (8080) | solo los dos avisos preexistentes (claves de desarrollo de Clerk y el buscador sin `id`/`name`); ningún error atribuible a la enmienda |

Capturas: `8080-inventario-pestanas-gestion.png`, `8080-inventario-pestana-unica-solicitante.png`.

### 10.4 Datos residuales de la verificación

La transición T3/T4 dejó **2 filas nuevas** en `historial_transicion_producto` (producto 8,
actor 13, motivos literales): el historial de producto pasa de **8 a 10** filas. El estado
del catálogo **no cambió**: «Grapadora Estandar» sigue **inactiva** con saldo 0 y los
contadores son 15/2. Categorías (2 filas) y el resto de datos del §8 quedan igual.

