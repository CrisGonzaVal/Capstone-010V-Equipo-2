# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**010 cerradas**. **010 (multi-tenant por esquemas)** cerró con T18 (confirmación de cierre SDD) y el roadmap la marca `[x]`. Próxima: **011** modelo organizacional.
- Suites 010 (tras cierre post-validación): `pytest` SQLite **601 passed, 33 skipped**; gated `POSTGRES_TEST_URL` **634 passed, 0 skipped**; `ng test` **198 SUCCESS**; `ng build` limpio. Matriz de permisos: **22 operaciones** (21 previas + `POST /api/v1/control/instituciones/`, solo Superadmin).
- 010: cada institución en un **esquema** PostgreSQL propio dentro de `apt_erp`; esquema **control** global con las 12 tablas 3NF + `mapa_usuario_esquema` + identidad Superadmin; `version_esquema` por tenant (`010.1`). Selección de esquema por `schema_translate_map` **por ejecución** (nunca `search_path`). Base real `apt_erp` migrada con script `database/migraciones/001_migracion_multitenant_esquemas.sql` (fuera del glob de initdb).
- 009: dashboard consolidado; 008: `institucion_id` + claves compuestas (conservadas dentro de cada tenant como defensa en profundidad, D-3); 007: matriz + `RolGuard`; 006: Clerk; 005: despacho transaccional.

## Feature 010 — decisiones clave
- `01_esquema.sql` crea las 12 tablas en `control` y fija su `search_path` por defecto; `02_datos_semilla.sql` pasa a seed QA con **guardia fail-closed** antes del primer `TRUNCATE`. Reset QA = recrear el volumen (`docker compose down -v`).
- Catálogos `rol`/`prioridad`/`estado_ticket` ahora **replicados por tenant** (invierten la norma global de 008); justificado en `stack.md` §"Multi-tenant por esquemas PostgreSQL".
- Aprovisionamiento solo Superadmin; el correo del Administrador debe existir en Clerk (422 si no, 503 si la frontera cae, 409 duplicado/colisión). Portal `/control` standalone (login Clerk prebuilt + alta); `ControlSuperadminGuard`.
- El alta replicaba el catálogo `Administrador` (`_ROLES_TENANT`) y **además** creaba otro `Administrador` para el usuario inicial: el tenant quedaba con el rol **duplicado**. Corregido en `control_service._rol_administrador` (reutiliza el del catálogo); test gated `test_aprovisionamiento_postgres_010.py`. La migración **no** duplicaba.
- Durante T15, `crise.gonzalez@duocuc.cl` fue **ascendida a Superadmin a mano** en `control` (fila de tenant inerte) para poder recorrer la 010; el usuario decidió dejarlo así (mutación out-of-band, registrada en `tasks.md` T15). No la produce el bootstrap ni la migración.
- Limpieza post-validación: eliminados `INST-TEST-010`, su esquema `tenant_inst_test_010_e4b81830` y su mapa en `apt_erp` (una transacción con verificación). Quedan **4 tenants** (INST-001..004) y 14 filas de mapa.

## Entregable: diagramas de casos de uso
- `docs/diagramas/`: `casos-uso-general` + `casos-uso-{superadmin,administrador,bodeguero,solicitante}`, en **HTML y PNG**.
- Los 5 PNG también en `../Evidencias Grupales/diagramas/` (fuera del proyecto, pedido explícito del usuario).
- Skill **`diagram-design`** en `.agents/skills/`; su `style-guide.md` lleva la paleta CompuStock (slate + blue); `npx skills update` la revierte.

## Aprendizajes y errores a evitar
- Cierre = verificación (AGENTS §8.5–§8.7): hacen falta los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas.
- Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test`).
- Clerk `SignIn` prebuilt (6.39): al reconocer una sesión activa redirige solo; pasar `forceRedirectUrl` (o `fallbackRedirectUrl`); `afterSignInUrl` ya no es prop. Sin esto `/control` caía a `/dashboard` (defecto AC-15, corregido).
- Semilla destructiva: el `TRUNCATE ... CASCADE` de `02_` alcanza `control.mapa_usuario_esquema`; por eso la guardia fail-closed.

## Próximos pasos
- Empezar **011** modelo organizacional (sede, stock por sede, `departamento.encargado_id`), luego 012 CRUD administrativo, 013/014 ciclos de ticket/catálogo, 015 informes, 016 notificaciones, Hito 2.
- Rama `dev` fusionada en `main`; diagramas/skill/notas en `origin/main` (`955280a`).
