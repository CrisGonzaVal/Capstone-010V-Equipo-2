# Feature 017 — Evidencia del recorrido funcional (C1)

Recorrido contra el backend en contenedor (`uvicorn --reload`, volumen
`./backend/app`) y PostgreSQL **real** (`compustock_db` / `apt_erp`, puerto local
5433, usuario `postgres`), tras **recrear el volumen** (`down -v` + `up -d`) para
que la semilla estrene las estructuras de la 017. Cada efecto se verificó **por
SQL** con `docker exec … psql` (patrón de la 013). El frontend se sirvió en el
dev server **4200** (`npm start`); el humo de **8080** se hizo tras reconstruir la
imagen (§8).

> **Sin capturas de pantalla:** el recorrido se operó contra la API con tokens
> Clerk **reales** (no con clics en la UI), y cada resultado quedó acreditado con
> la respuesta HTTP literal y las consultas SQL transcritas. La verificación en
> 4200 se limitó al serve del shell SPA y a sus chunks lazy; el comportamiento
> de las vistas está cubierto por `ng test` (375 SUCCESS, T12) y por los specs
> citados en `spec.md` §6.

## 1. Reset y estructura verificada (20/Oct/2026, ~02:43–02:45)

| Hecho | Valor observado |
|---|---|
| `docker compose … down -v` + `up -d` | volumen `evidenciasproyecto_postgres_data` **removido y recreado**; `db`, `backend` y `frontend` arrancaron (*healthy*) |
| Logs de initdb | `01_esquema.sql`: `01: tenant tenant_inst_00X_… creado con 17 tablas.` ×4; `02_datos_semilla.sql`: `Semilla QA: base limpia (4 instituciones, tenants vacios)` y `02: semilla y tenants completados. control + tenants en version 013.1; datos distribuidos por institucion.` Sin `ERROR`. El único `FATAL: the database system is shutting down` es el reinicio interno del entrypoint tras los scripts (esperado) |
| Tablas en `control` | **20** (`…`, `mapa_usuario_esquema`, `registro_motivo_constancia`, …, `version_esquema`) |
| Columnas nuevas de `control.mapa_usuario_esquema` | `estado_invitacion` (varchar, null), `invitacion_id` (varchar, null), `invitacion_expira_en` (timestamp, null), `invitacion_aceptada_en` (timestamp, null), con `CHECK (estado_invitacion IS NULL OR estado_invitacion = ANY (pendiente, aceptada, revocada, expirada))` |
| Tabla auxiliar `control.registro_motivo_constancia` | 13 columnas: `registro_id`, `tipo_registro`, `actor_correo`, `usuario_objetivo_id`, `correo_objetivo`, `institucion_id`, `accion`, `codigo_motivo`, `texto_motivo`, `fecha_registro`, `clave_idempotente`, `invitacion_id`, `resultado_revocacion`; **0 filas** al iniciar |
| Tablas por tenant | `tenant_inst_001_038aa2a9`, `…_002_5efdced3`, `…_003_37b7d724`, `…_004_c24e4e4c` → **17** cada uno |
| Auxiliares en tenants | **ninguna**: cero tablas `%constancia%`/`%registro%` y cero columnas `%invitacion%` en los cuatro esquemas `tenant_*` |
| Versión | `control.version_esquema = (1, 013.1, 2026-10-20 05:43:46)` |
| Semilla del mapa | 12 filas, **todas** con `estado_invitacion = 'aceptada'` y `invitacion_id`/timestamps nulos |
| Backend vivo | `GET /health` → `{"status":"healthy"}`; `GET /openapi.json` → **55 operaciones** bajo `/api/v1/` + `GET /` y `GET /health` (**57** rutas/métodos) |
| Frontend 4200 | `npm start` compiló `Initial total 154.07 kB` con los chunks lazy de la 017: `usuarios-component` 62,20 kB, `administradores-control-component` 42,12 kB, `dashboard-saas-component` 23,60 kB. `GET /`, `/control`, `/control/instituciones/INST-017/administradores` y `/administracion/usuarios` → **200** con el shell SPA (`<app-root>`) |

### 1.1 Identidad Superadmin de una instalación limpia

La semilla consolidada deja `control.usuario` **vacía** (FASE 3 borra las tablas
de negocio de control) y no siembra al Superadmin: la identidad se crea con
`control_service.ejecutar_bootstrap_control` (correo por defecto
`superadmin@compustock.cl`), que **no se invoca en el arranque**. Para el
recorrido se ejecutó la propia función de la aplicación dentro del contenedor y
se alineó el correo con la identidad Clerk de pruebas ya existente:

```sql
-- tras ejecutar_bootstrap_control: usuario_id 13, rol 1 (Superadmin), depto 11
UPDATE control.usuario SET correo='superadmin.test+clerk_test@example.com'
 WHERE correo='superadmin@compustock.cl';
INSERT INTO control.mapa_usuario_esquema (correo, institucion_id, nombre_esquema, activo, estado_invitacion)
VALUES ('superadmin.test+clerk_test@example.com','CTRL-SAAS','control',TRUE,'aceptada');
```

## 2. Cuentas usadas

Sesiones Clerk **reales** de la instancia dev `relevant-termite-8089`, emitidas
por HTTP (dev browser + sign-in ticket, patrón §2 de la 013). Ningún secreto ni
token se escribe en esta evidencia.

| Cuenta Clerk | Rol efectivo | Uso en el recorrido |
|---|---|---|
| `superadmin.test+clerk_test@example.com` | **Superadmin** (control) | dashboard técnico, alta de instituciones, gestión de Administradores, 403 en lecturas de negocio |
| `admin017.test+clerk_test@example.com` | **Administrador** de INST-017 (creada por invitación en este recorrido) | aceptación de la invitación, primer login, CRUD de usuarios tenant, 409/422/403 |
| `bodega017.test+clerk_test@example.com` | Solicitante de INST-017 (creada por invitación) | objeto del ciclo pendiente → reenvío → baja → reactivación |
| `crise.gonzalez@duocuc.cl` | Solicitante de INST-017 (identidad **preexistente** en Clerk) | alta sin invitación → `aceptada` sin URL |
| `lu.illanes@duocuc.cl` | Administrador de INST-018 (identidad preexistente) | alta institucional sin invitación → `aceptada` |

## 3. Recorrido (acción → resultado HTTP + valores SQL reales)

### 3.1 Superadmin (`/control/*`)

| # | Acción | Resultado HTTP | Verificación SQL / contrato | AC |
|---|---|---|---|---|
| 1 | `GET /auth/me` | **200** `usuario_id=13`, `rol="Superadmin"`, `institucion_id=null` | — | AC-8 |
| 2 | `GET /control/dashboard` | **200** `total_instituciones=4`, `total_instituciones_activas=4`, `total_administradores_activos=4`, `total_administradores_inactivos=0`, `usuarios_por_rol={"Solicitante":5,"Bodeguero":3}`, `conteos_conocidos=4`, `conteos_no_disponibles=0`; las 4 instituciones `operativo` con `version_objetivo=version_persistida="013.1"` | INST-001: 2 sedes, 7 deptos, 3 Administradores activos, Solicitante 3/Bodeguero 3. Sin correos, tickets ni motivos | AC-13, AC-14 |
| 3 | `POST /control/instituciones/` INST-017 con `admin017.test+clerk_test@example.com` (correo **nuevo** en Clerk) | **201**, `nombre_esquema=tenant_inst_017_337fe910`, `version_esquema=013.1`, `estado="operativa"`, `url_invitacion` presente | mapa: `admin017… | tenant_inst_017_337fe910 | activo=true | pendiente | inv_3KwkXJBQdCDXKyBD7iKjY6JYJXA`; **17** tablas en el esquema nuevo | AC-1, AC-3 |
| 4 | `GET /control/instituciones/INST-017/usuarios/` | **200** `[{usuario_id:1, nombre:"Ana", apellido:"Prueba", correo, activo:true, estado_invitacion:"pendiente"}]` | solo los cinco campos de D-10; sin URL | AC-5, AC-8 |
| 5 | `PUT /control/instituciones/INST-017/usuarios/1` (`correccion_datos`, texto «Correccion del nombre del Administrador», idempotencia `cierre-017-edit-admin`) | **200**, `nombre="Ana Maria"` | `registro_motivo_constancia` fila 1: `justificacion | edicion_usuario | correccion_datos | Correccion del nombre del Administrador | cierre-017-edit-admin | admin017…` | AC-10, AC-11 |
| 6 | `POST …/usuarios/1/invitacion/reenvio` | **200** con **URL nueva** y `estado_invitacion="pendiente"` | mapa: `pendiente | inv_3Kwkglea3k4om1rZKYEZOGXusHw | expira 2026-11-19 06:02:11` (el ID rotó) | AC-6 |
| 7 | `PATCH …/usuarios/1/estado` `activo=false` con motivo | **409** «No se puede dar de baja al ultimo Administrador activo de la institucion» | mapa sigue `activo=t`; **0** filas nuevas con `clave_idempotente='cierre-017-ultimo-admin-control'` | AC-12 |
| 8 | `GET /control/instituciones/INST-999/usuarios/` | **404** `la institucion no existe` | — | AC-8 |
| 9 | `GET /dashboard/`, `GET /tickets/`, `GET /inventario/movimientos`, `GET /inventario/categorias`, `POST /usuarios/` como Superadmin | **403** `Permiso insuficiente para la operacion` en las cinco | la matriz se evalúa antes del recurso, sin devolver datos | AC-15, AC-17 |
| 10 | `GET /control/dashboard` como Administrador (C14) | **403** | control es exclusivo del Superadmin | AC-8 |

### 3.2 Aceptación de la invitación y primer login (AC-4, AC-16)

El invitado aceptó el enlace real en Clerk por HTTP (`sign_up` con
`strategy=ticket`, contraseña y verificación `email_code` `424242` → `status:
complete`), lo que materializa la identidad Clerk de `admin017…` sin que el
backend cree usuarios.

| # | Acción | Resultado | SQL | AC |
|---|---|---|---|---|
| 11 | Primer `GET /auth/me` de `admin017…` | **200**, `rol="Administrador"` | mapa: `estado_invitacion=aceptada`, `invitacion_aceptada_en=2026-10-20 06:03:59.814823` | AC-4 |
| 12 | Segundo `GET /auth/me` | **200** | mismo `invitacion_aceptada_en` (idempotente, no reescribe) | AC-4, AC-16 |

### 3.3 Administrador institucional (INST-017)

| # | Acción | Resultado HTTP | Verificación SQL | AC |
|---|---|---|---|---|
| 13 | `POST /usuarios/` `bodega017.test+clerk_test@example.com` (nuevo en Clerk) | **201** `usuario_id=2`, `activo=true`, `estado_invitacion="pendiente"`, `url_invitacion` | mapa `bodega017… | pendiente` | AC-1 |
| 14 | `POST /usuarios/` `crise.gonzalez@duocuc.cl` (identidad Clerk existente) | **201** `usuario_id=3`, `estado_invitacion="aceptada"`, **`url_invitacion=null`** | mapa `aceptada` sin `invitacion_id` | AC-2 |
| 15 | `GET /usuarios/` | **200** con los 3 usuarios y `estado_invitacion` por fila; el JSON **no contiene** la cadena `url` | SQL: `1|admin017…|true|aceptada`, `2|bodega017…|true|pendiente`, `3|crise…|true|aceptada` | AC-5 |
| 16 | `PUT /usuarios/2` (nombre, `correccion_datos`) | **200** | motivo 2: `edicion_usuario | correccion_datos | Nombre completo | cierre-017-edit-tenant` | AC-10, AC-11 |
| 17 | `POST /usuarios/2/invitacion/reenvio` | **200** con URL nueva | el `invitacion_id` del mapa rota | AC-6 |
| 18 | `PATCH /usuarios/2/estado` `activo=false` (`termino_vinculo`) | **200** `activo=false` | motivo 3 `baja_usuario | termino_vinculo`; mapa `activo=false` | AC-10, AC-11 |
| 19 | `POST /usuarios/2/invitacion/reenvio` con la asociación inactiva | **409** «La asociacion local esta inactiva; reactivela primero con `PATCH .../estado` y un motivo…» | sin cambio de `invitacion_id` | AC-6 |
| 20 | `PATCH /usuarios/2/estado` `activo=true` (`reasignacion_organizacional`) | **200** `activo=true` | motivo 4 `reactivacion_usuario` | AC-2, AC-10 |
| 21 | `POST /usuarios/2/invitacion/reenvio` tras reactivar | **200** con URL nueva (`inv_3KwkwvgbEepd0LbC0XU1dWuy8dd`) | mapa `2|Bruno Andres|true|pendiente|inv_3Kwkw…` | AC-2, AC-6 |
| 22 | `PATCH /usuarios/1/estado` (auto-baja del último Administrador) | **409** «No se puede dar de baja al ultimo Administrador activo…» | usuario y mapa intactos (`1|Ana Maria`, `activo=t`); **0** filas con `cierre-017-autobaja` | AC-12 |
| 23 | `PUT /usuarios/1` degradando a Solicitante | **409** «No se puede degradar al ultimo Administrador activo…» | sin mutación ni motivo | AC-12 |
| 24 | `PUT /usuarios/2` con `motivo.codigo="otro"` y texto `"   "` | **422** «el motivo `otro` exige texto explicativo no vacio» | sin cambio | AC-10 |
| 25 | `POST /usuarios/` con `"  BODEGA017.TEST+clerk_test@example.com "` | **409** «El correo ya esta registrado y vinculado a una institucion» (normalización trim+lowercase) | una sola fila local | AC-2, AC-7 |
| 26 | `GET /control/dashboard` como Administrador | **403** | — | AC-8 |
| 27 | `PATCH /usuarios/2/estado` baja (`seguridad_acceso`) → `GET /usuarios/` → reactivación | **200**, **200**, **200** | el listado muestra `activo=false` con `estado_invitacion="pendiente"` **por separado**, sin URL; motivos 5 y 6 persistidos | AC-5, AC-10 |

### 3.4 Alta institucional con identidad preexistente (AC-2, AC-3)

| # | Acción | Resultado | SQL | AC |
|---|---|---|---|---|
| 28 | `POST /control/instituciones/` INST-018 con `lu.illanes@duocuc.cl` (identidad Clerk existente) | **201** `nombre_esquema=tenant_inst_018_e1ef6916`, `estado="operativa"`, **`url_invitacion=null`** | mapa INST-018: `aceptada | NULL | NULL` (sin invitación ni timestamps) | AC-2, AC-3 |
| 29 | `GET /control/instituciones/INST-018/usuarios/` | **200** un Administrador con `estado_invitacion="aceptada"` | — | AC-5 |
| 30 | `GET /control/dashboard` con 6 instituciones | **200** `total_instituciones=6`, `conteos_conocidos=6`, las 6 `operativo` (la institución administrativa `CTRL-SAAS` **no** se cuenta) | — | AC-13, AC-14 |

### 3.5 Integridad final (SQL de cierre)

```
instituciones = 7 en control.institucion (4 semilla + CTRL-SAAS + INST-017 + INST-018)
tenants       = 6 esquemas tenant_* (4 semilla + INST-017 + INST-018), 17 tablas cada uno
mapa          = admin017 aceptada (inv rotada) | bodega017 pendiente | crise aceptada | lu aceptada
motivos       = 6 justificaciones (1 de control, 5 de tenant); ninguna constancia de compensacion
version       = 013.1
```

## 4. Contrato OpenAPI (backend vivo)

`GET /openapi.json` → **55 operaciones** v1 (57 con `GET /` y `GET /health`).
Las seis operaciones D-10 publicadas con sus `response_model`, códigos de éxito
y errores 401/403/404/409/422/503:

| Operación | Éxito |
|---|---|
| `GET /control/instituciones/{institucion_id}/usuarios/` | 200 `AdministradorListadoControlRespuesta[]` |
| `POST /control/instituciones/{institucion_id}/usuarios/` | 201 `UsuarioInvitacionRespuesta` |
| `PUT /control/instituciones/{institucion_id}/usuarios/{usuario_id}` | 200 `UsuarioRespuesta` |
| `PATCH /control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado` | 200 `UsuarioRespuesta` |
| `POST /control/instituciones/{institucion_id}/usuarios/{usuario_id}/invitacion/reenvio` | 200 `UsuarioInvitacionRespuesta` |
| `POST /usuarios/{usuario_id}/invitacion/reenvio` | 200 `UsuarioInvitacionRespuesta` |

## 5. Mapeo AC → evidencia

La evidencia AC por AC está en `spec.md` §6 (bloque `Evidencia` de cada AC).
Este documento es la fuente del recorrido con escritura real que allí se cita.

### 5.1 Suites ejecutadas en el cierre (20/Oct/2026)

| Suite | Comando | Resultado |
|---|---|---|
| Backend (SQLite en memoria) | `cd backend && .venv\Scripts\python.exe -m pytest -q` | **1158 passed, 56 skipped, 0 failed** (375,9 s) — los 1156 de T11/T13 **+ 2** tests nuevos del defecto §7.1 |
| Backend gated PostgreSQL 16 | `$env:POSTGRES_TEST_URL="postgresql://postgres:postgres@localhost:5433/postgres"` sobre 12 módulos (`instalacion_limpia`, `esquema`, `aprovisionamiento_010`, `bootstrap_control_010`, `ciclo_vida_ticket_013`, `gestion_administrativa_012` HTTP/servicio, `aceptacion_invitacion_017`, `dashboard_tecnico_017`, `correcciones_017`, `integracion_multitenant_010`, `lectura_global_011`) | **51 passed, 0 failed** (607,8 s) sobre bases temporales; `test_aislamiento_sede_011.py` → **1 passed**. `apt_erp` no se toca |
| Frontend | `$env:CHROME_BIN=…msedge.exe; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless` | **375 SUCCESS, 0 FAILED** (17,2 s) |
| Build de producción | `docker compose -f docker-compose.yml build frontend` | **OK** (§8) |

## 6. Datos residuales en `apt_erp` (QA real, sin borrado)

- **INST-017** «Instituto de Prueba 017» (`tenant_inst_017_337fe910`, 17 tablas)
  con 3 usuarios: `admin017…` (Administrador, `aceptada`), `bodega017…`
  (Solicitante, `pendiente`, con invitación vigente) y `crise.gonzalez@duocuc.cl`
  (Solicitante, `aceptada`).
- **INST-018** «Instituto de Prueba 018» (`tenant_inst_018_e1ef6916`) con un
  Administrador `lu.illanes@duocuc.cl` (`aceptada`).
- `control.registro_motivo_constancia`: 6 filas (ids 1–6) de justificaciones
  reales del recorrido; ninguna de compensación.
- Superadmin de control `usuario_id=13`, correo
  `superadmin.test+clerk_test@example.com`, mapa a `control`.
- En Clerk se creó **una** identidad (`admin017…`, al aceptar su invitación) y
  quedó pendiente la invitación de `bodega017…`. La invitación de `admin018…`
  creada al depurar la frontera (§7.1) se **revocó** al cerrar el recorrido
  (`status: revoked`), de modo que no queda ninguna invitación huérfana.
- Las 4 instituciones de la semilla quedaron **intactas**.

## 7. Hallazgos

1. **Defecto real corregido (bloqueante del alta con correo nuevo).**
   `security.buscar_identidad_o_invitacion` exigía que `GET /v1/invitations`
   devolviera `{"data": [...]}`, pero la API de la instancia dev responde una
   **lista JSON desnuda**; `_invitacion_pendiente_de` lanzaba
   `ErrorClerkNoDisponible("respuesta de Clerk inesperada")` y el alta de
   cualquier correo sin identidad (y el reenvío) terminaba en **503**. Los tests
   no lo detectaban porque el transporte fake devolvía la forma envuelta. Se
   corrigió aceptando ambas formas, con dos tests nuevos en rojo primero
   (`test_busqueda_detecta_invitacion_pendiente_en_lista_desnuda`,
   `test_busqueda_acepta_lista_desnuda_vacia_de_invitaciones`).
2. **La instalación limpia no crea la identidad Superadmin.** `02_` vacía
   `control.usuario` y nadie invoca `ejecutar_bootstrap_control` en el arranque,
   así que un clon nuevo no tiene con qué entrar a `/control` (y el correo por
   defecto del bootstrap, `superadmin@compustock.cl`, no existe en Clerk). En el
   recorrido se resolvió ejecutando la propia función y alineando el correo
   (§1.1). No se tocó código ni semilla: es una decisión de despliegue/seed.
3. **`estado: "operativa"` en el alta institucional con invitación pendiente.**
   La respuesta de `POST /control/instituciones/` informa la institución como
   operativa aunque la invitación del primer Administrador siga `pendiente`; el
   estado de invitación vive por separado (mapa). Coincide con AC-3 (el flujo de
   aprovisionamiento se completó) y con los tests, pero conviene tenerlo
   presente al leer la respuesta.
4. **`PUT /usuarios/{id}` (tenant) no devuelve `activo`/`estado_invitacion`.**
   La respuesta 200 cumple `UsuarioRespuesta` con `activo=null` y
   `estado_invitacion="no disponible"`; el listado sí publica ambos. No es un
   incumplimiento (el DTO los admite nulos y el contrato no los exige en la
   edición), pero la UI debe refrescar la lista para mostrar el estado.
5. **Aceptar la invitación sin navegador** requiere el flujo completo
   `sign_up` `strategy=ticket` → fijar contraseña (`PATCH sign_ups/{id}`) →
   `prepare_verification` + `attempt_verification` `email_code` `424242`. Solo
   con `ticket` la instancia exige `password` y no permite verificar por código.
6. **Windows/PowerShell:** `docker exec … sh -c` con `$()` y comillas anidadas
   se rompe; usar psql con `-Atc` y consultas de una línea. `urllib` de Python
   recibe **403 (Cloudflare 1010)** contra Clerk si no se envía `User-Agent`.

## 8. 8080 — humo tras rebuild (20/Oct/2026, ~03:07–03:10)

Rebuild obligatorio (AGENTS §5/§8.6): el contenedor sirve un build de producción
congelado en la imagen.

| Paso | Resultado |
|---|---|
| `docker compose -f docker-compose.yml build frontend` | **sin errores**; `Image evidenciasproyecto-frontend Built`; manifiesto `sha256:8d8531971373ff4636c1b012e04b792694b642f0471d85ce2a64dd4475bda38b` |
| `docker compose -f docker-compose.yml up -d frontend` | `compustock_frontend` recreado y **healthy** (`Up 12 seconds (healthy)`, `0.0.0.0:8080->80/tcp`) |

### 8.1 Bundle nuevo y shell

| Verificación (HTTP contra `http://localhost:8080`) | Resultado real |
|---|---|
| `GET /` | **200**, shell SPA (`<app-root>`, 2.554 B) que referencia **`main-AQPZZQO7.js`** (9.592 B) y **`styles-B37IEAY7.css`** |
| Bundle previo | `GET /main-R6LIXDWJ.js` → **404** (antes del rebuild el shell apuntaba a `main-R6LIXDWJ.js` y `styles-2W3BHTMI.css`: cambió el hash del JS **y** del CSS) |
| Cacheo con hash | `HEAD /main-AQPZZQO7.js` → `Cache-Control: max-age=31536000,public, immutable`, `Last-Modified: Tue, 20 Oct 2026 06:07:44 GMT`, `nginx/1.31.7` |
| Deep links (`try_files` de nginx) | `GET /control`, `/control/instituciones/INST-017/administradores` y `/administracion/usuarios` → **200** con el mismo shell (`<app-root>`) |
| Mapa de rutas servido | `chunk-O44XKPPW.js` (control routes) cablea `{path:"instituciones/:institucionId/administradores", canActivate:[GuardSuperadmin], loadComponent: …AdministradoresControlComponent, title:"Administradores institucionales | CompuStock"}` |
| Marcadores de la 017 en los `.js` servidos (`docker exec … grep -r`, BusyBox sin `--include`) | `no enrutable` (taxonomía D-8, dashboard SaaS) en `chunk-QRH57NLB.js` (9.726 B); `invitacion/reenvio` en `chunk-QIAYQ5SH.js` (control.service, 2.920 B) y `chunk-WZA4CLDV.js` (administracion.service, 1.495 B); `institucionId` además en `chunk-M6O52J3V.js` (22.836 B, componente de Administradores) y `chunk-YUG4Y3PI.js` (capacidades) |

### 8.2 API a través del proxy de nginx (`/api/` → `backend:8000`)

| Verificación | Resultado real |
|---|---|
| `GET :8080/api/v1/control/dashboard` **sin token** | **401** (autorización intacta tras el proxy) |
| `GET :8080/api/v1/control/dashboard` con token Clerk real | **200**, `total_instituciones=6` |
| `GET :8080/api/v1/auth/me` con el mismo token | **200**, `rol="Superadmin"`, `correo="superadmin.test+clerk_test@example.com"` |
