# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**013 cerradas** (la 013 el **19/Oct/2026**). **013 (ciclo de vida del ticket):** estado `Anulado` único para anulación (dueño/Administrador) y rechazo (Bodeguero/Administrador) con motivo obligatorio, edición completa en `Pendiente`, historial de transiciones inmutable (**15.ª entidad de dominio**) y vista de detalle; tablero Kanban a solo lectura con acción «Gestionar» (D-14). Suites de cierre: `pytest` SQLite **952 passed / 68 skipped / 0 failed**; gated PostgreSQL 16 **1020 passed / 0 skipped / 0 failed**; `ng test` **323 SUCCESS**; `ng build` limpio. Matriz/OpenAPI: **49 operaciones** v1 (51 totales con `/` y `/health`), 5 nuevas aditivas. Migración `004_migracion_ciclo_vida_ticket_013.sql` **012.1→013.1** aplicada a `apt_erp` (respaldo `respaldos/apt_erp_pre_013.dump`). Recorrido 4200 con escritura real (tickets 13–15) y humo 8080 con imagen reconstruida (bundle `main-R6LIXDWJ.js`): evidencia en `docs/spec/features/013-ciclo-vida-ticket/evidencia/README.md`.
- **013 — decisiones clave:** terminales `Cerrado`/`Anulado` **por nombre canónico en cualquier catálogo** (enmienda D-4/AC-26; sustituye la terminalidad ordinal de la 004, cuyo test degenerado `test_reentrar_en_cerrado_conserva_la_fecha_original` quedó derogado). `Anulado` no sella `fecha_cierre` (queda nula) ni toca stock; el historial es la fuente de verdad del ciclo de vida; no es elegible en alta (409, D-11). KPI de activos excluye `('Cerrado','Anulado')` por nombre. Enmienda AC-18: un rol sin la operación en la matriz (p. ej. Solicitante en rechazo) recibe **403**, no 404; el 404 idéntico de ocultamiento es solo para rol concedido fuera de alcance. Gating de capacidades: anulación/rechazo → `kanban`; edición/detalle/historial → `tickets`. `MATRIZ_012` congelada en 44 como línea base. Conteo de modelo: **15 de dominio** + `departamento_encargado` (AGENTS §7 y skills `sdd-workflow`/`fastapi-pydantic-v2` actualizadas en el cierre; justificación en `stack.md` §2).

## Feature 011 — decisiones clave
- **Stock por sede sustituye al departamental**: `stock_sede` es la única fuente operativa (`(sede_id, producto_id)`); `inventario` legado congelado. (La 011 cerró con 14 entidades de dominio; desde la 013 son 15.)
- Ámbitos: Solicitante por departamento/sede; Bodeguero solo su `usuario.sede_id`; Admin toda su institución; Superadmin lectura global atribuida. Sin sede → **409**. Encargados N:N sin privilegio extra.
- Ticket guarda `ticket.sede_id` (**snapshot**) al crearse. Migración `002_…sql` a `011.1`; "Sede Central" automática al aprovisionar; UI administrativa → 012.

## Feature 012 — decisiones clave
- `control.institucion.activo` es el ciclo de vida institucional; inactiva → identidad no resoluble **401** antes de versión; reactivar restaura routing si la versión es objetivo.
- `funcion_institucion` en `control`: conjunto cerrado de 6 IDs (`catalogo`,`inventario`,`tickets`,`kanban`,`dashboard`,`gestion_organizacional`), gating **403 adicional a la matriz**; espejo tenant de 2 columnas. `activo` lógico en sede/departamento; el usuario local usa `mapa_usuario_esquema.activo`.
- Superadmin excluido de `/tickets` **solo por UI/guard** (`ROLES_TICKETS`); alta de usuario local exige Clerk preexistente. El combo de alta filtra roles en frontend (`puedeAsignarRol`); `GET /usuarios/roles` sigue devolviendo los 4.

## Reproducibilidad post-011 (cerrada)
- Constructor `database/03_construir_tenants_011.sql` (entre `02_` y `98_`): crea esquemas `tenant_*`, distribuye datos, puebla `mapa_usuario_esquema`, marca `version_esquema` (hoy nace en **013.1**). Un clon nuevo (`docker compose up -d`) levanta la BD multi-tenant completa.
- `database/migraciones/` es SOLO para upgrades de bases existentes; `001`/`002`/`003` no sirven para installs nuevos.

## Aprendizajes y errores a evitar
- Cierre = verificación (AGENTS §8.5–§8.7): los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo; grep de coherencia sobre AGENTS/MEMORY/skills al cerrar.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas. Bugs que solo salen en PG: sesión de control vs tenant (012) y `DetachedInstanceError` del lector global (013: construir el DTO eager dentro de la sesión de cada tenant). Base desechable para gated; `apt_erp` nunca se toca.
- Al subir `VERSION_ESQUEMA_OBJETIVO`, los tests de cadena que construyen con el constructor rompen: arreglar el **test** (helper `_degradar_a_012_1`, aserción con `VERSION_MIGRACION_012`), nunca la migración histórica.
- Toda mutación de estado exige actor **persistido** (FK del historial): fixtures con la sonda sintética `9999` deben pasar a un usuario real; si no, el INSERT del historial revienta con `IntegrityError`.
- Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test`). PowerShell: `pg_dump`/restauración con `cmd /c`; `docker exec sh -c` con `$()` y comillas anidadas se rompe; BusyBox `grep` sin `--include` (usar `grep -r`); `curl.exe` conserva backslashes de escape (usar archivos de body).
- Clerk por HTTP sin navegador: el FAPI con Basic auth es stateless por request y el código `424242` ya no se acepta; usar dev browser (`POST /v1/dev_browser`, query `__dev_session`) + sign-in ticket BAPI (`POST /v1/sign_in_tokens`, el campo se llama `token`, estrategia `ticket`, form-encoded) + `Origin: localhost:4200` (el backend exige `azp`; sin él → 401). Tokens ~60 s.
- Specs Angular de navegación: con `provideRouter([])` el click de un `routerLink` no actualiza `router.url`; probar «navega a X» con el `href` y un espía a `router.navigateByUrl`.
- psycopg2 2.9+ **no expone `password`** en `get_dsn_parameters()`: reutilizar la URL original cambiando solo el nombre de base.
- `resolver_contexto_solicitud` sin `abrir_sesion_tenant` lee la versión de **control**, no del tenant: el gated debe cablear `abrir_sesion_tenant=crear_sesion_esquema` (espejo de `dependencies.py`).
- Tras el constructor, `control.estado_ticket` conserva **solo** la fila `Anulado` (espejo del estado post-004 de una base migrada real).
- `stack.md` aún menciona "12 entidades" en justificaciones históricas (008/010) y en el comentario del árbol §1; cosmético, no bloquea.

## Próximos pasos
- Backlog: **014** ciclo de vida del catálogo, **015** informes PDF/Excel, **016** notificaciones in-app. **Hito 2**: 11/Dic/2026.
