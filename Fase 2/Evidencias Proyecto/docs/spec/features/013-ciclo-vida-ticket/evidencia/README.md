# Feature 013 — Evidencia del recorrido funcional (T13)

Recorrido funcional contra el backend en contenedor (`uvicorn --reload`, volumen
`./backend/app`) y PostgreSQL **real** (`compustock_db` / `apt_erp`, puerto local
5433, usuario `postgres`), verificando **cada efecto con SQL por `docker exec
psql`**. El frontend se verificó en el dev server **4200** (`npm start`); el
recorrido de humo en **8080** (rebuild de la imagen) quedó documentado en §8.

> **Sin capturas de pantalla:** el recorrido se operó contra la API con tokens
> Clerk reales (no a través de la UI), y cada resultado quedó acreditado con la
> respuesta HTTP literal y con las consultas SQL transcritas en esta evidencia.
> La verificación de la UI en 4200 se limitó al arranque del dev server, al
> serve del shell SPA y a los chunks lazy (T14/T15 hacen el resto).

## 1. Estado inicial de la base

Verificado antes de la primera escritura del recorrido (19/Oct/2026, ~04:55):

| Hecho | Valor observado (SQL/HTTP) |
|---|---|
| Respaldo previo | `respaldos/apt_erp_pre_013.dump` (275.966 bytes, 19/Oct 00:21) |
| Versión de control | `control.version_esquema = '013.1'` (fila única, 19/Oct 03:22) |
| `Anulado` en catálogo de control | `control.estado_ticket = (1, 'Anulado')` — solo esa fila, como es post-004 |
| Catálogo del tenant INST-001 | `tenant_inst_001_038aa2a9.estado_ticket` = Pendiente(1), EnRevision(2), EnCurso(3), Cerrado(4), **Anulado(5)** |
| Historial al iniciar | `control.historial_transicion_ticket` = **0 filas**; `tenant_inst_001_…historial_transicion_ticket` = **0 filas** |
| Backend sirve el código 013 | `GET /openapi.json` = **49 operaciones** bajo `/api/v1/` con las 5 nuevas (ver §6) |
| Frontend 4200 | `npm start` compiló (initial 150,81 kB; lazy `ticket-detalle-component` 61,69 kB y `tickets-component` 48,11 kB); `GET /` y `GET /tickets` = **200** con el shell SPA (`app-root`). Detenido al cerrar (`Get-Process node | Stop-Process`; 4200 deja de responder) |

## 2. Cuentas usadas

Sesiones Clerk **reales** de la instancia dev `relevant-termite-8089` (emitidas
por HTTP durante el recorrido; ningún secreto en esta evidencia). Todas las
cuentas locales de la semilla **sí tienen usuario en Clerk con correo primario
verificado** (verificado vía Backend API `GET /v1/users`), por lo que **no se
usaron contrapartes `+clerk_test` salvo para Superadmin**:

| Cuenta Clerk | Rol efectivo (BD real) | Uso en el recorrido |
|---|---|---|
| `diego.munoz@losalpes.cl` | **Solicitante** (usuario_id 2, depto Secretaria → sede 2) | alta, anulación propia, edición, lecturas |
| `andres.vargas@losalpes.cl` | **Bodeguero** (usuario_id 6, sede 2) | rechazo, PATCH `/estado`, despacho |
| `valentina.reyes@losalpes.cl` | **Administrador** (usuario_id 3) | 409s de estado sobre tickets ajenos de la institución |
| `superadmin.test+clerk_test@example.com` | Superadmin (identidad de control) | 403 en escrituras; lectura global de detalle/historial |

> **Hallazgo de entorno (no es defecto):** el enunciado de la tarea describía
> `valentina.reyes` como Solicitante y `diego.munoz` como Administrador; en la
> BD real es al revés (tabla `rol`: 2=Administrador, 3=Bodeguero, 4=Solicitante;
> Valentina rol_id 2, Diego rol_id 4). El recorrido usó los roles reales.

### Cuentas QA en la semilla (posterior al cierre, para el equipo)

Para que cualquier clon pruebe el circuito completo de la 013 sin crear
usuarios a mano, la semilla `database/02_datos_semilla.sql` siembra dos
usuarios locales adicionales de INST-001, en el departamento 6 (Biblioteca →
Sede 2, la misma que opera el Bodeguero, de modo que el ticket emitido se
despacha desde su sede):

| id | Cuenta Clerk (`+clerk_test`, código `424242`) | Rol | Para probar |
|---|---|---|---|
| 11 | `solicitante.test+clerk_test@example.com` (Paula Rojas) | Solicitante | emitir, anular el propio, 404 en ajenos |
| 12 | `bodeguero.test+clerk_test@example.com` (Roberto Díaz, sede 2) | Bodeguero | rechazar con motivo, despachar |

Verificado con la cadena real de initdb (`01 → 02 → 03`) en una base
desechable: los 12 usuarios llegan al tenant, `mapa_usuario_esquema` resuelve
ambos correos, `departamento_encargado` asocia el departamento 6 a Paula y el
catálogo de estados trae `Anulado` con historial vacío (AC-12). Las cuentas
`@losalpes.cl` de la tabla anterior también siguen valiendo (rol por
departamento) y son útiles para el Administrador (`valentina.reyes`).

### Cómo se obtuvieron los tokens (para reproducibilidad)

El flujo pedido (`signIn.create → prepareFirstFactor → attemptFirstFactor` con
código `424242`) **ya no es ejecutable sin navegador**: el Frontend API con
`Authorization: Basic <pk:>` es *stateless* por request (cada llamada crea un
client nuevo y el sign-in queda huérfano: `signed_out`), y con el código fijo
responde `form_code_incorrect`. Se usó el flujo equivalente documentado de
testing de Clerk, **sin secretos hardcodeados** (todo leído de `.env`):

1. `POST /v1/dev_browser` (FAPI, con `Origin: http://localhost:4200`) → dev
   browser token, usado como query param `__dev_session` (el FAPI de instancias
   dev lo exige; con cookies o sin él responde `dev_browser_unauthenticated`).
2. `POST /v1/sign_in_tokens` (Backend API, secret key) → *sign-in ticket* para
   el `user_id` de la cuenta.
3. `POST /v1/client/sign_ins` + `attempt_first_factor` con
   `strategy=ticket&ticket=…` (FAPI, `Origin: localhost:4200`) → sesión completa.
4. `client.sessions[0].last_active_token.jwt` → token de sesión.

El `Origin: http://localhost:4200` es imprescindible: el backend exige
`azp ∈ {http://localhost:4200, http://localhost:8080}` (`security.py`
`AZP_PERMITIDOS`); un token minteado sin ese origen (p. ej.
`POST /v1/sessions/{id}/tokens` de la Backend API, que no lleva `azp`) recibe
**401**. Cada token de sesión vive ~60 s, así que se emitió uno nuevo por
petición. Ningún usuario fue creado ni modificado en Clerk.

## 3. Recorrido (acción → resultado HTTP + valores SQL reales)

Todos contra `http://localhost:8000/api/v1` con `Authorization: Bearer <token>`
y SQL posterior por psql sobre `tenant_inst_001_038aa2a9` salvo indicación.

### 3.1 Ciclo feliz (Solicitante + Bodeguero)

| # | Acción | Resultado HTTP (real) | Verificación SQL (real) | AC |
|---|---|---|---|---|
| 1 | `POST /tickets/` como Diego (Solicitante), estado inicial 1, producto 4 (Folder Manila) ×5 | **201** `ticket_id=13`, `estado_id=1`, `sede_id=2` (snapshot del depto Secretaria), `usuario_id=2` (atribuido al dueño aunque el payload trajera otro) | fila creada con sus detalles; historial: **1 fila** `(id=1, origen=NULL, destino=1 Pendiente, usuario_id=2, motivo=NULL, 04:57:41)` | AC-9 |
| 2 | `POST /tickets/13/anulacion` como Diego con motivo `"Se anula por duplicado con la solicitud S-0042"` | **200**, `estado_id=5` | `ticket 13 = Anulado, fecha_cierre = NULL`; historial fila `(id=2, 1→5, usuario 2, motivo literal completo)`; `stock_sede (2,4) = 200` **intacto**; `movimiento_inventario` sigue en **21** (0 salidas nuevas) | AC-1, AC-6 |
| 3 | `GET /tickets/13` como Diego | **200** con campos poblados: `estado_nombre:"Anulado"`, `prioridad_nombre:"Alta"`, `solicitante_id:2`, `solicitante_nombre:"Diego"`, `solicitante_apellido:"Munoz"`, `solicitante_correo`, `departamento_nombre:"Secretaria"`, `sede_nombre:"Sede 2"`, detalle con `producto.categoria` | — | AC-10, AC-19 |
| 4 | `GET /tickets/13/historial` como Diego | **200**, 2 filas en orden `fecha_transicion DESC, id DESC`: primero la anulación (con `estado_origen_nombre:"Pendiente"`, `estado_destino_nombre:"Anulado"`, `usuario_nombre:"Diego"`, `usuario_apellido:"Munoz"`, motivo literal), después la creación (origen nulo) | coincide 1:1 con las 2 filas SQL | AC-9, AC-10, AC-19 |
| 5 | `POST /tickets/` como Diego → `ticket_id=14` (2 ítems: producto 1 ×10, producto 8 ×3) | **201** | — | AC-13 (prep.) |
| 6 | `PUT /tickets/14` como Diego con payload nuevo: asunto/descripción distintos, `prioridad_id=3`, ítems **completamente distintos** (producto 2 ×7, producto 5 ×2) | **200** con `prioridad_id=3` y los 2 detalles nuevos | cabecera: asunto/descripción/prioridad actualizados; `usuario_id=2`, `estado_id=1`, `sede_id=2` **intactos**; `detalle_ticket` del ticket = solo ids 16 y 17 (los previos 14–15 **borrados**); historial del ticket sigue en **1** fila (editar no muta estado) | AC-13 |
| 7 | `POST /tickets/14/rechazo` como **Andrés (Bodeguero)** con motivo `"Sin stock disponible en la sede para la fecha solicitada"` | **200**, `estado_id=5` | `ticket 14 = Anulado, fecha_cierre = NULL`; historial añade `(id=4, 1→5, usuario_id=6 Andres, motivo literal)` | AC-3, AC-6 |

### 3.2 Regresión de la Feature 005 (despacho transaccional)

| # | Acción | Resultado HTTP (real) | Verificación SQL (real) | AC |
|---|---|---|---|---|
| 8 | `POST /tickets/` como Diego → `ticket_id=15` (producto 6 Clip Métrico ×3, sede 2) | **201** | historial: creación origen nulo | AC-9 |
| 9 | `PATCH /tickets/15/estado` 1→2 y 2→3 como Andrés (Bodeguero) | **200**, **200** (`estado_id=3` EnCurso) | historial suma exactamente 1 fila por mutación (ids 6 y 7) | AC-9 |
| 10 | `PATCH /tickets/15/estado` hacia `Cerrado` (4) | **409** literal `El cierre requiere despacho; use POST /api/v1/tickets/15/despacho` | sin cambios (ticket sigue EnCurso, sin filas nuevas) | AC-5, AC-26 |
| 11 | `POST /tickets/15/despacho` como Andrés con `usuario_id=6` | **200**, `estado_id=4`, **`fecha_cierre=2026-10-19T05:04:14`**, `cantidad_entregada=3` | `stock_sede (2,6): 35 → 32` (rebajo exacto de 3); movimiento **id=22** `SALIDA, cantidad=3, stock_sede_id=5, observacion='Despacho ticket_id=15; detalle_id=18; producto_id=6'`; historial añade `(id=8, 3→4 EnCurso→Cerrado, usuario 6)` | AC-5, AC-6, AC-9 |

### 3.3 Rechazos y guardingas (todos verificados sin efectos colaterales)

| # | Acción | Resultado HTTP (real) | AC |
|---|---|---|---|
| 12 | `POST /tickets/5/anulacion` (ticket de Isabel, **EnCurso**) como Valentina (Admin) | **409** `El estado actual no admite anulacion ni rechazo: solo se admiten 'Pendiente' o 'EnRevision'` | AC-2 |
| 13 | `POST /tickets/6/anulacion` (ticket **Cerrado**) como Admin | **409** ídem | AC-2 |
| 14 | `POST /tickets/13/anulacion` (ticket **ya Anulado**) como dueño | **409** `El ticket ya esta en 'Anulado'` | AC-2 |
| 15 | `POST /tickets/5/rechazo` (EnCurso) como Bodeguero | **409** (mismo literal de estado) | AC-3 |
| 16 | `PATCH /tickets/1/estado` **hacia** `Anulado` (id 5) | **409** `El estado 'Anulado' solo se alcanza por anulacion o rechazo; use POST /api/v1/tickets/1/anulacion o POST /api/v1/tickets/1/rechazo` | AC-4 |
| 17 | `PATCH /tickets/13/estado` **desde** `Anulado` | **409** `El ticket esta en 'Anulado', estado terminal del que ninguna operacion lo saca; …` | AC-4 |
| 18 | `POST /tickets/99999/anulacion` (inexistente) y `POST /tickets/2/anulacion` (ajeno: de Isabel) como Diego | ambos **404** con detalle **idéntico** `Ticket no encontrado` (sin revelar existencia) | AC-7, AC-18 |
| 19 | `POST /tickets/1/anulacion` con `motivo="   "` (solo espacios) | **422** `El motivo es obligatorio y no puede exceder 500 caracteres`; ticket 1 **sigue Pendiente** e historial sin filas nuevas (verificado por SQL) | AC-8 |
| 20 | `POST /tickets/` con `estado_id=5` (Anulado) | **409** `El estado 'Anulado' no es elegible para alta: un ticket nuevo no puede nacer anulado` | AC-4 (D-11) |
| 21 | `PUT /tickets/13` (edición sobre ticket **Anulado**) | **409** `La edicion solo se aplica a tickets en estado 'Pendiente'` | AC-14 |
| 22 | `POST /tickets/1/anulacion`, `POST /tickets/1/rechazo`, `PUT /tickets/1` como **Superadmin** | los tres **403** `Permiso insuficiente para la operacion` (matriz evaluada antes del recurso) | AC-17, AC-18 |
| 23 | `POST /tickets/1/rechazo` como **Diego (Solicitante)**: rol sin la operación | **403** `Permiso insuficiente para la operacion` (sin mirar el ticket, que es suyo) | AC-17, AC-18 |
| 24 | `GET /tickets/14` y `GET /tickets/14/historial` como **Superadmin** (ticket de INST-001) | **200** y **200** con presentación resuelta y alcance global (lector `leer_global_unico`), sin `DetachedInstanceError` | AC-19 |
| 25 | `GET /dashboard/` como Diego | **200** `kpi.tickets_activos = 3` — sus tickets anulados (13, 14) **no cuentan**: SQL por estado = Pendiente 3, EnRevision 2, EnCurso 1, **Anulado 2**, Cerrado 7; para Diego (alcance propio) sus activos son los tickets 1, 4 y 12 = 3 | AC-22 |

### 3.4 Integridad final (SQL de cierre, 19/Oct ~05:06)

```
tickets 13 y 14  = Anulado con fecha_cierre NULL
ticket 15        = Cerrado con fecha_cierre 2026-10-19 05:04:14
tickets 1, 2, 5, 6 (usados solo en rechazos 409/404/422) = INTACTOS (mismo estado que al inicio)
historial        = 8 filas (solo creaciones y transiciones reales del recorrido; ninguna inventada)
movimiento_inventario = 22 (solo +1: el despacho del ticket 15)
stock (2,4)=200 intacto (anulaciones no tocan stock); (2,6) 35→32 (solo el despacho)
```

## 4. Contrato OpenAPI (verificado contra el backend vivo)

`GET /openapi.json` en el contenedor: **49 operaciones** bajo `/api/v1/`. Las 5
de la 013 con sus códigos documentados:

| Operación | Códigos |
|---|---|
| `POST /tickets/{id}/anulacion` | 200, 401, 403, 404, 409, 422 |
| `POST /tickets/{id}/rechazo` | 200, 401, 403, 404, 409, 422 |
| `PUT /tickets/{id}` | 200, 401, 403, 404, 409, 422 |
| `GET /tickets/{id}` | 200, 401, 403, 404 |
| `GET /tickets/{id}/historial` | 200, 401, 403, 404 |

## 5. Mapeo AC-1…AC-26 → evidencia

Tests de la suite (T12: SQLite **952 passed / 68 skipped / 0 failed**; gated PG
**1020 passed / 0 failed**; `ng test` **323 SUCCESS**; ambos citados en T12 de
`tasks.md`) + recorrido real de esta evidencia (§3):

| AC | Evidencia |
|---|---|
| AC-1 anulación con motivo → 200, Anulado, fecha_cierre nula, stock/movs intactos, historial | test `test_ciclo_vida_flujo_013.py::test_anulacion_desde_pendiente…ac_1` (+`…desde_en_revision…ac_1`); recorrido §3.1 #2 (SQL: estado, fecha NULL, stock 200, movs 21, fila con motivo literal) |
| AC-2 409 desde EnCurso/Cerrado/Anulado sin efectos | test `…flujo_013.py::test_anulacion_desde_estado_inadmisible_responde_409_sin_efectos_ac_2`; recorrido §3.3 #12–#14 |
| AC-3 rechazo Bodeguero/Admin 200; 409 sin efectos | tests `…flujo_013.py::test_rechazo_por_bodeguero…ac_3`, `…por_administrador…ac_3`, `…desde_en_curso…409…ac_3`; recorrido §3.1 #7 y §3.3 #15 |
| AC-4 terminales por nombre: 409 hacia/desde Anulado | tests `…flujo_013.py::test_patch_estado_no_lleva_a_anulado…ac_4`, `…no_sale_de_anulado_ac_4`, `…alta_en_anulado…d11` + AC-26 (catálogos degenerados); recorrido §3.3 #16, #17, #20 |
| AC-5 `EnCurso→Cerrado` reservado al despacho; historial del despacho; Anulado no despachable | tests `…flujo_013.py::test_en_curso_a_cerrado_sigue_reservado_al_despacho_ac_5`, `…despacho_registra_su_transicion…ac_5`, `…despacho_de_un_anulado…409…ac_5`; recorrido §3.2 #10 (409 literal) y #11 |
| AC-6 `Cerrado` sella fecha; `Anulado` la deja nula y no escribe movimientos | tests `…flujo_013.py::test_alta_en_cerrado_sella_fecha_cierre_ac_6`, `…despacho_sella_fecha_cierre_ac_6`; recorrido §3.1 #2 (fecha NULL, movs intactos) y §3.2 #11 (fecha sellada) |
| AC-7 orden 404→409→422 | tests `…flujo_013.py::test_orden_404_ante_422…ac_7`, `…409_ante_422…ac_7`, `…422_de_motivo_invalido_no_modifica_nada_ac_7`, `…409_de_estado_inadmisible_con_motivo_valido_ac_7`; recorrido §3.3 #18 (404 idéntico), #12 (409), #19 (422 sin efectos) |
| AC-8 motivo obligatorio, no vacío, ≤500, literal | tests `…motivo_013.py` (4 tests AC-8: faltante/vacio/exceso/límite con literal persistido); recorrido §3.1 #2 y #7 (motivos literales en SQL), §3.3 #19 (422) |
| AC-9 una fila por mutación (creación origen nulo, cambio, despacho, anulación/rechazo) | tests `…historial_013.py::…creacion_con_origen_nulo_ac_9`, `…cambio_de_estado_suma_exactamente_una_fila_ac_9`, `…anulacion_y_rechazo_suman_exactamente_una_fila_ac_9`; recorrido §3.1 #1 (fila creación), #4, §3.2 #9 (1 fila/PATCH), #11 (fila despacho) |
| AC-10 historial solo lectura + orden determinista | tests `…historial_013.py::test_orden_mas_reciente_primero_con_desempate_por_id_ac_10`, `…no_expone_operaciones_de_escritura_ac_10`; recorrido §3.1 #4 (orden DESC con desempate por id) |
| AC-11 atomicidad estado+historial | tests `…historial_013.py::…persiste_estado_y_fila_juntos_ac_11`, `…si_la_fila_no_puede_registrarse_el_estado_no_cambia_ac_11` (inserción forzada a fallar) |
| AC-12 sin trazabilidad fabricada (legados con historial vacío) | tests `…historial_013.py::…legado_sin_transiciones_muestra_historial_vacio_ac_12`, `…anulacion_de_legado_no_inventa_fila_de_creacion_ac_12`; recorrido: los tickets 6–12 pre-013 siguen sin filas inventadas (el total de 8 filas corresponde solo al recorrido) |
| AC-13 edición en Pendiente: 200 con conjunto reemplazado, campos intactos | tests `…edicion_013.py::…reemplaza_cabecera_y_detalles_ac_13`, `…conserva_estado_solicitante_sede_e_institucion_ac_13`; recorrido §3.1 #6 (SQL: ids viejos borrados, cabecera nueva, estado/sede/solicitante intactos) |
| AC-14 409 fuera de Pendiente sin efectos | test `…edicion_013.py::test_edicion_fuera_de_pendiente_responde_409_sin_efectos_ac_14`; recorrido §3.3 #21 |
| AC-15 validación total antes de escribir (404/422 sin escritura parcial) | 5 tests `…edicion_013.py::…ac_15` (prioridad/producto inexistente, producto ajeno, cantidad no positiva, detalles vacíos) |
| AC-16 Bodeguero/Superadmin no editan (403); Solicitante solo los suyos; ajeno = 404 idéntico | tests `…edicion_013.py::test_bodeguero_y_superadmin_no_pueden_editar_ac_16`, `…solicitante_no_edita_ticket_ajeno…identico_ac_16`, `…administrador_de_otra_institucion…404_ocultado…ac_16`, `…administrador_edita_tickets_de_su_institucion_ac_16` |
| AC-17 matriz exacta (5 filas aditivas), Superadmin sin escritura, 49 operaciones | tests `…autorizacion_013.py` (matriz/OpenAPI/gating: 12 tests ac_17 incl. capacidades apagadas); contrato vivo §4 |
| AC-18 403 por matriz antes del recurso; 404 idéntico sin revelar existencia | tests `…autorizacion_013.py::…operar_ticket_ajeno_responde_404_identico_ac_18`, `…leer_ajeno_responde_404_identico_ac_18`; recorrido §3.3 #18 (detalle idéntico), #22, #23 (403 sin mirar el recurso) |
| AC-19 los 4 roles leen con su alcance; Superadmin global sin escritura | tests `…autorizacion_013.py::…superadmin_lee_detalle_e_historial_ac_19`, `…solicitante_lee_su_detalle_y_no_el_ajeno_ac_19`, `…administrador_y_bodeguero_leen…ac_19`; recorrido §3.1 #3–#4 (Solicitante), §3.3 #24 (Superadmin global 200) |
| AC-20 instalación nueva con `Anulado`; migración idempotente a 013.1 | gated `test_ciclo_vida_ticket_postgres_013.py` (7/7: cadena 01→02→03+mig 004, idempotencia, preflight); estado real de la base §1 (versión 013.1, catálogo completo, respaldo previo) |
| AC-21 solo enrutan tenants en 013.1 con `Anulado` | gated `test_ciclo_vida_ticket_postgres_013.py` (tenant en 012.1 deniega cerrado; en 013.1 enruta); §1 (el recorrido entero operó sobre tenant enrutado en 013.1) |
| AC-22 KPI excluye `Cerrado`/`Anulado` por nombre | tests `…dashboard_013.py` (3 tests ac_22); recorrido §3.3 #25 (tickets_activos=3 para Diego; sus 2 anulados fuera del conteo, contrastado con SQL por estado) |
| AC-23 vista de detalle: cabecera, ítems, historial, estados vacíos y errores visibles | `frontend/.../ticket-detalle.component.spec.ts` (27 specs, `ng test` 323 SUCCESS en T12); dev server 4200 sirvió el chunk lazy `ticket-detalle-component` (§1) |
| AC-24 toda mutación desde el detalle; tablero solo lectura con «Gestionar» y columna Anulado; errores accesibles sin doble envío | `ticket-detalle.component.spec.ts` + `tickets.component.spec.ts` (T11: sin controles de mutación, «Gestionar», columna Anulado, alta sin `Anulado`); 4200 sirvió `tickets-component` (§1) |
| AC-25 suites en verde y recorrido en 4200 con escritura real | T12 (`tasks.md`: SQLite 952/68/0, gated PG 1020/0, ng 323 SUCCESS, build limpio); 4200 §1; escritura real §3 (tickets 13–15 persistidos) |
| AC-26 terminalidad por nombre en cualquier catálogo | tests `…flujo_013.py::test_catalogo_degenerado_sin_salida_desde_cerrado_ac_26`, `…desde_anulado_ac_26`, `…reentrada_en_cerrado…ac_26`, `…ticket_despachado_no_vuelve…ac_26`; recorrido §3.3 #10, #16, #17 (catálogo canónico) |

## 6. Datos de prueba residuales (QA real, sin borrado)

Creados por el recorrido en `apt_erp` (esquema `tenant_inst_001_038aa2a9`):

- **Tickets nuevos: 13** (`T13 recorrido: anulable`, Anulado, dueño Diego),
  **14** (`T13 recorrido: editado con exito`, editado y rechazado → Anulado,
  dueño Diego), **15** (`T13 regresion 005: despacho`, Cerrado con despacho
  auditado, dueño Diego).
- **Historial:** 8 filas (ids 1–8) repartidas en esos 3 tickets.
- **Movimiento de inventario:** id 22 (SALIDA ×3, producto 6, sede 2) por el
  despacho del ticket 15.
- **Stock:** `stock_sede (sede 2, producto 6)` quedó en 32 (rebajo legítimo del
  despacho); el resto intacto.
- Residuos de una sesión previa interrumpida (no tocados): tickets **11**
  (`T13 recorrido 4200`, Cerrado) y **12** (`T13 ticket futuro`, Pendiente).
- Los tickets de la semilla usados en rechazos (1, 2, 5, 6) quedaron
  **intactos** (los 409/404/422 no escriben).
- En Clerk **no se creó ni modificó ningún usuario**; las sesiones emitidas
  expiraron solas (~60 s).

## 7. Hallazgos para T14/T15

1. **El flujo HTTP de sign-in de Clerk ya no funciona sin navegador.** El
   Frontend API con Basic auth es stateless por request y el código fijo `424242`
   fue rechazado (`form_code_incorrect`); el flujo de *sign-in ticket* + dev
   browser (§2) es el sustituto válido para futuros recorridos por API. Para el
   humo de 8080/T14, la UI usa `clerk-js` en el navegador y no depende de esto.
2. **`security.py` exige `azp` de localhost:4200/8080.** Cualquier token no
   emitido con ese origen (p. ej. Backend API `POST /v1/sessions/{id}/tokens`)
   recibe 401; útil al documentar cualquier prueba automatizada futura.
3. **Roles de la semilla ≠ enunciado de la tarea:** en la BD real
   `rol(2=Administrador, 3=Bodeguero, 4=Solicitante)`; Valentina Reyes es
   Administrador y Diego Munoz Solicitante. Las cuentas `+clerk_test` de la 012
   siguen vigentes para Superadmin e INST-002, pero para INST-001 las cuentas
   locales existen en Clerk con sus correos planos.
4. **Windows + PowerShell:** `curl.exe` dentro de PS conserva backslashes de
   escape (JSON malformado si se escapa con `\"`); usar archivos de body. Y
   `ForEach-Object` sobre salidas de curl disparó un falso positivo del
   antivirus de Windows que bloqueó el script (usar acceso por índice).

## 8. 8080 — humo (T14, 19/Oct/2026 ~05:23–05:46 UTC)

Rebuild de la imagen (AGENTS §5/§8.6: sin esto el 8080 sirve un build congelado
y la evidencia sería falsa):

| Paso | Resultado |
|---|---|
| `docker compose -f docker-compose.yml build frontend` | **sin errores**; `ng build` dentro del builder: **55,55 s**; capa del builder `DONE 63,1 s`; export de la imagen 1,1 s. Re-ejecución de control (todo en caché): **exit 0**, mismo digest de manifiesto `sha256:1acf53e1d8b7b55df46c9886dd23459c242f2d87d666f463ef88ba17ef6aa123` |
| `docker compose -f docker-compose.yml up -d frontend` | contenedor `compustock_frontend` **recreado** y **healthy** (`Up … (healthy)`, 0.0.0.0:8080->80/tcp); imagen en uso `sha256:1b8351b1468c…` = `evidenciasproyecto-frontend:latest` |

### 8.1 Bundle nuevo y humo del shell

| Verificación (HTTP contra `http://localhost:8080`) | Resultado real |
|---|---|
| `GET /` | **200**, shell SPA (`<app-root>`, 2.554 B) que referencia **`main-R6LIXDWJ.js`** (9.234 B) y `styles-2W3BHTMI.css`, con modulepreload de `chunk-PEC22F4L/YI56XUUK/EPU4OVNG/CWKE7X32/BCOWUETH/GMZLEGE6/WYQAXJ3U` |
| `GET /tickets` y `GET /tickets/13` (`try_files` de nginx) | **200** con el **mismo shell** (deep-link Angular resuelto por `try_files $uri $uri/ /index.html`) |
| Bundle anterior | `GET /main-6C2R7UG2.js` → **404** (el HTML previo al rebuild apuntaba a `main-6C2R7UG2.js` + `styles-4S7CHXBN.css`: **tanto el CSS como todos los chunks cambiaron de hash**) |
| Cacheo con hash | `HEAD /main-R6LIXDWJ.js` → `Cache-Control: max-age=31536000,public, immutable`, `Last-Modified: 19/Oct 05:23:56 GMT`, `nginx/1.31.7` |

### 8.2 Chunks de la 013 presentes y referenciados

- `GET /chunk-URBQGDLO.js` (el mapa de rutas perezosas que consume el bundle)
  sirve, **por HTTP**, el cableado de la feature:

  ```js
  var e=[{path:"",loadComponent:()=>import("./chunk-GGSHOG7T.js").then(t=>t.TicketsComponent),title:"Tickets y Kanban | CompuStock"},
         {path:":ticketId",loadComponent:()=>import("./chunk-FYJSV5V5.js").then(t=>t.TicketDetalleComponent),title:"Detalle del ticket | CompuStock"}];
  ```

- Búsqueda de marcadores en los `.js` **servidos** (`docker exec … grep -r`,
  BusyBox sin `--include`):

  | Marcador (literal del template) | Chunk servido | Tamaño |
  |---|---|---|
  | `Gestionar` (acción única de la tarjeta del tablero, T11) | `chunk-GGSHOG7T.js` = `TicketsComponent` | 20.523 B |
  | `Historial de transiciones` y `Avanzar un paso en el flujo` (vista de detalle, T10) | `chunk-FYJSV5V5.js` = `TicketDetalleComponent` | 28.509 B |

  Los tamaños coinciden con los chunks que reportó `ng build` en T12
  (`tickets-component` 20,52 kB y `ticket-detalle-component` 28,51 kB).

> **Nota sobre la imagen previa:** la evidencia de la 012 cita el bundle
> `main-GAEBNACE.js`, pero la imagen pre-T14 servía `main-6C2R7UG2.js` (hubo un
> rebuild intermedio no documentado). La imagen previa ya no existe (no quedan
> imágenes colgantes tras el `up -d`), por lo que no pudo inspeccionarse; el
> cambio de hash del **CSS** y de **todos** los chunks indica que compilaba
> fuentes distintas a las actuales (los templates de la 013 alteran las clases
> Tailwind, de donde sale el hash del CSS).

### 8.3 API a través del proxy de nginx (`/api/` → `backend:8000`)

| Verificación | Resultado real |
|---|---|
| `GET :8080/api/v1/openapi.json` | **404** — hallazgo: `frontend/nginx.conf` solo proxya `/api/` y FastAPI publica el OpenAPI en la **raíz** (`/openapi.json`, `main.py` sin `root_path`), así que el documento **no es accesible desde 8080** (en `:8080/openapi.json` y `:8080/health` nginx cae al shell SPA por `try_files`) |
| Contrato en el mismo backend vivo que proxya 8080 (`GET :8000/openapi.json`) | **49 operaciones** bajo `/api/v1/` (51 totales con `GET /` y `GET /health`); las 5 nuevas: `POST /tickets/{id}/anulacion`, `POST /tickets/{id}/rechazo`, `PUT /tickets/{id}` → 200,401,403,404,409,422; `GET /tickets/{id}` y `GET /tickets/{id}/historial` → 200,401,403,404,422 |
| `GET :8080/api/v1/tickets/13` **sin token** | **401** (autorización intacta tras el proxy) |
| `GET :8080/api/v1/auth/me` con token Clerk real | **200**, `usuario_id=2` Diego Munoz (Solicitante) |
| `GET :8080/api/v1/tickets/13` con token | **200** con presentación poblada: `estado_nombre:"Anulado"`, `prioridad_nombre:"Alta"`, `solicitante_id:2`, `solicitante_nombre:"Diego"`, `solicitante_apellido:"Munoz"`, `solicitante_correo:"diego.munoz@losalpes.cl"`, `departamento_nombre:"Secretaria"`, `sede_nombre:"Sede 2"`, **`fecha_cierre:null`**, detalle con `producto.categoria` **eager** (`nombre_cat:"Organizacion"`), `cantidad_solicitada=5`, `cantidad_entregada=0` |
| `GET :8080/api/v1/tickets/13/historial` con token | **200**, 2 filas en orden `fecha_transicion DESC, id DESC`: (2) `Pendiente→Anulado` por Diego Munoz con el motivo literal `Se anula por duplicado con la solicitud S-0042`; (1) creación con **origen nulo** |
| `GET :8080/api/v1/tickets/` con token | **200**, 7 tickets (estados 4×2, 5×2, 1×2, 2×1) |

Tokens emitidos por HTTP con el flujo de §2 (caducan a los ~60 s; uno nuevo por
petición). **Aprendizaje nuevo del flujo** (para futuros recorridos): el campo
de la Backend API se llama **`token`** (no `ticket`), y los endpoints FAPI de
client (`/v1/client/sign_ins` y `/v1/client/sign_ins/{id}/attempt_first_factor`)
exigen parámetros **form-encoded**: con `application/json` responden
`form_param_missing` / dejan el intento en `needs_identifier`. Flujo que
funcionó: `dev_browser` → `sign_in_tokens` (BAPI) → `sign_ins` con
`identifier` → `attempt_first_factor` con `strategy=ticket&ticket=<token>` →
`client.sessions[0].last_active_token.jwt`.

### 8.4 Limitación de esta sesión y hallazgos para T15

- **Sin herramienta de navegador** en esta sesión: el humo se verificó por
  **HTTP + inspección del bundle servido** (shell, `try_files`, mapa de rutas,
  chunks de tablero y detalle, API por el proxy). **No se capturaron
  pantallazos** de la columna `Anulado` renderizada ni del clic en «Gestionar»;
  la evidencia visual funcional de la 013 vive en el recorrido 4200 (§3) y en
  los specs (`ng test` 323 SUCCESS, T12). El humo visual en 8080 queda pendiente
  de captura para T15/cierre.
- Hallazgos: (1) el OpenAPI no es accesible desde 8080 (solo `/api/` está
  proxyado); (2) la imagen pre-T14 no coincidía con el bundle citado en la
  evidencia 012 (rebuild intermedio no documentado; ya no inspeccionable);
  (3) el flujo HTTP de Clerk descrito en §2 necesita las correcciones de forma
  anotadas arriba; (4) en Windows, `docker exec … sh -c '…'` con `$()` y comillas
  anidadas se rompe (PowerShell) y BusyBox `grep` no admite `--include`: usar
  `grep -r` sobre el directorio.
