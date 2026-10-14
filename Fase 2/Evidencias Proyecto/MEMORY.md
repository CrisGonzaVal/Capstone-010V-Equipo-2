# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…008 implementadas y **008 CERRADA**: T1–T15 `[x]`, los 21 AC con evidencia, veredicto **APROBADO** del reviewer y `[x]` en `roadmap.md`. Backend `pytest` **487 passed, 5 skipped** en SQLite; **492 passed** con `POSTGRES_TEST_URL` (PostgreSQL 16). Frontend `ng test` **153 SUCCESS**. Recorrido funcional en 4200 con escritura real en `apt_erp` (ticket 25 cerrado, stock 30→20, movimiento SALIDA) y humo en 8080 sobre la imagen reconstruida `sha256:cfdd5de4…`.
- 008 entregó: `institucion_id` en `categoria`/`producto` (catálogo por institución) y derivada en `inventario`/`ticket`/`detalle_ticket`; claves/relaciones compuestas en `01_esquema.sql`; migración `98_migracion_particionamiento_institucional.sql` fail-closed e idempotente; semilla multiinstitución con homónimos; filtros de ámbito en catálogo/inventario/movimientos/tickets/usuarios; `GET /auth/me` con institución efectiva (`null` para Superadmin); UI con contexto institucional. Ajuste puntual de la matriz de permisos: Superadmin deja de escribir catálogo/stock/tickets (lectura global intacta); matriz **20 operaciones** (las 18 de 007 + 2 `GET` por objeto de catálogo).
- 007 entregó: cuatro roles locales (sin alias `Admin`); autorización cliente+servidor; matriz central `backend/app/core/permisos.py`; ámbito en `services/ambito_service.py`; `RolGuard` + `/acceso-denegado`; retiro de `usuario.password`.
- 006: Clerk (login/logout, `tokenInterceptor`, JWKS, `/auth/me`). 005: despacho transaccional. 003/004: catálogos, modal, Kanban.

## Decisiones de la 008
- D-1: cada categoría/producto pertenece a una sola institución; no hay catálogo maestro compartido ni fallback global.
- D-2: la existencia hereda institución del departamento y su producto debe ser de esa institución (constraint compuesta).
- D-3: los roles limitados no eligen institución (`usuario → departamento → institución`); Superadmin lee global pero no escribe datos de institución concreta; esas escrituras son del Administrador (y del Bodeguero en lo operativo).
- D-4: el servidor filtra y valida; el `institucion_id` del cliente nunca autoriza; objeto ajeno = **404**, departamento ajeno = **403**, ámbito irresoluble = **403**, sin mutación al denegar.
- D-5: `rol`/`prioridad`/`estado_ticket` siguen globales.
- D-6: la migración asigna pertenencia por relaciones persistidas; si es ambigua **aborta antes de cambios destructivos** identificando entidad/ID, sin perder ni reasignar datos, y reintenta tras corrección manual.

## Aprendizajes y errores a evitar
- Cierre = verificación (AGENTS §8.5): hacen falta los dos puertos; 8080 exige reconstruir la imagen (`docker compose build frontend` + `up -d`); el backend sí se recarga solo.
- La migración sobre la semilla legada real **abortó por ambigüedad** (`producto 4` referenciado por INST-001/INST-002, `producto 9` por INST-001/INST-003): el fail-closed funcionó. Se corrigió a mano (`UPDATE ticket … usuario_id`) y el reintento fue exitoso. El backup temporal `backup_apt_erp_pre008.sql` se borró al cerrar la 008 (nunca estuvo versionado).
- Tests PostgreSQL **gated** con `POSTGRES_TEST_URL` (se saltan si no está); SQLite no verifica FK compuestas, `NOT NULL` del DDL ni `FOR UPDATE`.
- Las columnas institucionales del DDL se endurecieron a `NOT NULL`; la migración debe rellenarlas antes de aplicarla.
- `docker exec` con `<` desde PowerShell corrompe la entrada: usar `cmd.exe /c "docker exec -i … < script"`.
- **Karma**: esta máquina solo tiene Edge; fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test` a secas).

## Próximos pasos
- **Feature 009** (siguiente, `[ ]` en el roadmap): dashboard analítico de stock crítico y log de alertas. Los KPI y "Actividad Reciente" siguen quemados a propósito y se reemplazan ahí.
