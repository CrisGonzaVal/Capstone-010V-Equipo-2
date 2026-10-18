# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**012 cerradas**. **012 (gestión administrativa)** **cerrada (18/Oct/2026)**: T1–T16 completas, reviewer APROBADO (14 AC), `roadmap.md` marcado. Reviewer de la 011: APROBADO.
- Suites 012 (finales, incl. corrección post-T13): `pytest` SQLite **839 passed / 61 skipped / 0 failed**; gated `POSTGRES_TEST_URL` **900 passed / 0 skipped / 0 failed**; `ng test` **292 SUCCESS**; `ng build` limpio. Matriz: **44 operaciones** (28 previas intactas + 16 nuevas: 7 control Superadmin + 9 organizacionales Admin); gating de capacidad 403 en 35 rutas (`/auth/me` y `/control/*` sin gating).
- Recorridos 012: **4200** funcional con escritura real (`evidencia/README.md` + capturas 01–18; `apt_erp` migrada a **012.1** con respaldo `respaldos/apt_erp_pre_012.dump`); **8080** con imagen reconstruida (bundle `main-GAEBNACE.js`, `8080-01`…`8080-05`).
- 010: cada institución en un **esquema** PostgreSQL propio dentro de `apt_erp`; esquema **control** global; selección por `schema_translate_map` **por ejecución** (nunca `search_path`). 009: dashboard; 008: `institucion_id` + claves compuestas; 007: matriz + `RolGuard`; 006: Clerk; 005: despacho transaccional.

## Feature 011 — decisiones clave
- **Stock por sede sustituye al departamental**: `stock_sede` es la única fuente operativa (`(sede_id, producto_id)`); `inventario` legado congelado. **14 entidades de dominio** + `departamento_encargado` auxiliar (no cuenta como entidad).
- Ámbitos: Solicitante por departamento/sede; Bodeguero solo su `usuario.sede_id`; Admin toda su institución; Superadmin lectura global atribuida. Departamentos/Bodegueros sin sede → **409** sin fallback. Encargados N:N: Solicitantes del mismo departamento, sin privilegio extra.
- Ticket guarda `ticket.sede_id` (**snapshot**) al crearse. Migración `002_…sql` a `011.1`: reparto 2/3/4/2, cuadre exacto por producto. "Sede Central" automática al aprovisionar (bootstrap). UI administrativa queda para la 012.

## Feature 012 — decisiones clave
- `control.institucion.activo` es el ciclo de vida institucional (no se reutiliza `mapa_usuario_esquema.activo`); institución inactiva → identidad no resoluble **401** antes de versión; reactivar restaura routing si la versión es objetivo.
- `funcion_institucion` en `control`: conjunto cerrado de 6 IDs (`catalogo`,`inventario`,`tickets`,`kanban`,`dashboard`,`gestion_organizacional`), fila por par, gating **403 adicional a la matriz** (sin fila de capacidad ⇒ habilitada por defecto). Espejo tenant `institucion` reducido a **2 columnas** (`institucion_id`,`nombre`).
- `activo` lógico añadido a `sede` y `departamento` (tenant) para AC-6/AC-11; el estado del usuario local sigue en `mapa_usuario_esquema.activo` (sin columna nueva). Desactivación idempotente; dependencias incompatibles → 409 con motivo.
- Superadmin se excluye de `/tickets` **solo por UI/guard** (`ROLES_TICKETS`): la matriz backend no cambia. Alta de usuario local usa sesión de tenant + control (Clerk preexistente obligatorio, 422/503).
- Ajuste post-cierre (UX): el combo de rol del **alta** filtra en frontend los roles asignables (`puedeAsignarRol`/`ROLES_ASIGNABLES_ADMINISTRADOR` en `core/auth/roles.ts`; Admin→2, Superadmin→4). `GET /usuarios/roles` **sigue devolviendo los 4** (catálogo compartido, D-5/AC-3 de la 008, usado también para nombrar roles del listado); no se filtra server-side. Backend sin cambios.

## Reproducibilidad post-011 (cerrada)
- Constructor `database/03_construir_tenants_011.sql` (initdb entre `02_` y `98_`): crea esquemas `tenant_*`, distribuye datos, puebla `mapa_usuario_esquema`, marca `version_esquema`. Un clon nuevo (`docker compose up -d`) levanta la BD multi-tenant completa.
- `database/migraciones/` es SOLO para upgrades de bases existentes; `001`/`002`/`003` no sirven para installs nuevos.

## Aprendizajes y errores a evitar
- Cierre = verificación (AGENTS §8.5–§8.7): los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas. Harness cross-`MetaData` en SQLite necesita `BaseControl.metadata` primero y `flush()` antes de la FK.
- Bugs de la 012 en PostgreSQL: `GET /auth/me` y `POST /usuarios/` usaban la sesión de **control** y devolvían 401/403 a un rol de tenant; usar `get_db_negocio` (tenant) + `get_db` (control). La suite SQLite (contexto lógico único) no los detectaba.
- El espejo tenant real de `011.1` tenía **4 columnas** (`rut`,`direccion` de más), no 2. Ruta `/control` aterriza en `/control/alta` (decisión de la 010).
- Edge: fijar `CHROME_BIN` (Edge) y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test`). PowerShell redirige binarios mal: `pg_dump`/restauración con `cmd /c`.

## Próximos pasos
- Backlog posterior al Sprint 5: **013/014** ciclos de ticket/catálogo, **015** informes, **016** notificaciones, **Hito 2** (11/Dic/2026).
- `stack.md` conserva menciones históricas de "12 entidades" (justificaciones 008/010 y comentario del árbol §1) **explícitamente superadas** por la sección 011 (14 de dominio) y ahora señaladas con una **nota histórica** en §2; el comentario del árbol §1 sigue diciendo "12 entidades" (cosmético). No bloquean.
