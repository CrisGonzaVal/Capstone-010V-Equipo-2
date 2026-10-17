# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**011 cerradas**. **011 (modelo organizacional)** quedó **cerrada formalmente** (17/Oct/2026): reviewer APROBADO, T1–T16 completas, AC verificados con recorrido en 4200 (escritura real) y 8080 (imagen reconstruida).
- Suites 011 (finales): `pytest` gated `POSTGRES_TEST_URL` **742 passed / 0 failed / 0 skipped**; SQLite **696 passed / 46 skipped**; `ng test` **198 SUCCESS**; `ng build` limpio. Matriz de permisos: **28 operaciones** (22 de la 010 + 6 de organización de la 011).
- Recorridos: **4200** funcional con escritura real (T13: ticket snapshot, reasignación, despacho, persistido en `apt_erp` migrada a `011.1` con respaldo); **8080** con imagen reconstruida (T14: dashboard e inventario con sede visibles).
- 010: cada institución en un **esquema** PostgreSQL propio dentro de `apt_erp`; esquema **control** global; selección por `schema_translate_map` **por ejecución** (nunca `search_path`). 009: dashboard; 008: `institucion_id` + claves compuestas; 007: matriz + `RolGuard`; 006: Clerk; 005: despacho transaccional.
- **Reproducibilidad post-011 cerrada**: `docker compose up -d` en un clon nuevo reconstruye la BD multi-tenant completa (ver sección propia).

## Feature 011 — decisiones clave
- **Stock por sede sustituye al departamental**: `stock_sede` es la única fuente operativa (`(sede_id, producto_id)`); el total institucional es derivado (suma de sedes). `inventario` legado queda congelado: no se expone por API ni alimenta consultas; filas y movimientos históricos intactos, `movimiento_inventario.stock_sede_id` nullable para movimientos nuevos.
- Modelo: **14 entidades de dominio** + `departamento_encargado` como tabla puente **auxiliar** (no cuenta como entidad); `Sede` y `StockSede` nuevas.
- Ámbitos: Solicitante por departamento/sede; Bodeguero solo su `usuario.sede_id`; Admin Institucional toda su institución; Superadmin lectura global atribuida, sin escritura tenant. Departamentos/Bodegueros sin sede → **409** sin fallback.
- Encargados N:N: usuarios con rol **Solicitante del mismo departamento**; API valida y filtra asociaciones vigentes; sin privilegio extra ni triggers.
- Ticket guarda `ticket.sede_id` (**snapshot**) al crearse; el despacho usa esa sede aunque el departamento se reasigne; tickets futuros usan la asignación vigente.
- Migración `database/migraciones/002_…sql` a `011.1`: reparto **2/3/4/2**, round-robin por `departamento_id`, movimientos de consolidación `ENTRADA`, **cuadre exacto** por producto, respaldo en `database/migraciones/respaldos/`.
- **"Sede Central"** automática al aprovisionar tenant nuevo (bootstrap, no CRUD). UI administrativa de sedes/departamentos/usuarios/encargados queda para **012**.

## Reproducibilidad post-011 (cerrada)
- Un clon nuevo (`docker compose up -d`) **no reproducía** la BD multi-tenant: la semilla dejaba todo en `control` (sin esquemas `tenant_*`, sin `version_esquema` ni `mapa_usuario_esquema`). Las migraciones `001`/`002` **no sirven para installs nuevos**: son upgrades de una base legada pre-010 con tablas en `public`, fallan sobre la semilla que escribe en `control`.
- Nuevo constructor **`database/03_construir_tenants_011.sql`** (initdb, corre entre `02_` y `98_`): crea los 4 esquemas `tenant_*` (hash `sha256(institucion_id)[:8]`), distribuye datos por institución, puebla `mapa_usuario_esquema` y marca `version_esquema='011.1'` en los 5 esquemas; deja `control` igual que `apt_erp` (institución + rol, negocio vacío). Verificado contra `apt_erp`: tenant 58/58 constraints, sedes 2/3/4/2, 0 huérfanos.
- Nuevo `env.example` (raíz) + sección "Puesta en marcha" en `README.md` (copiar `env.example`→`.env`, completar Clerk, `docker compose up -d`). `database/migraciones/` queda SOLO para upgrades de bases existentes.
- Decisión (usuario): el constructor **no** materializa un Superadmin; la app lo crea al primer login vía `/control` (bootstrap idempotente), como en `apt_erp`. Resultado: un compañero con claves Clerk clona, copia `.env` y levanta la BD multi-tenant completa sin migraciones manuales.

## Aprendizajes y errores a evitar
- Cierre = verificación (AGENTS §8.5–§8.7): hacen falta los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas.
- PowerShell redirige binarios mal: para `pg_dump`/restauración usar `cmd /c`.
- `inventario` legado en tests se lee por ORM, no por API (la 011 no lo expone).
- El **500 de `GET /tickets/`** venía de la 010: la sesión del legor global se cerraba antes de serializar; fix `selectinload` de `Producto.categoria` (`test_lectura_global_tickets_011.py`).
- Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test`).
- Semilla destructiva: el `TRUNCATE ... CASCADE` de `02_` alcanza `control.mapa_usuario_esquema`; por eso la guardia fail-closed.
- Clerk `SignIn` prebuilt: pasar `forceRedirectUrl`/`fallbackRedirectUrl` (sin esto `/control` caía a `/dashboard`).

## Decisión de producto — la 012 se amplía (usuario aprobó)
- **012 = CRUD administrativo + panel de control del Superadmin a nivel SaaS.** Además del CRUD (sedes, departamentos, usuarios, encargados), incluirá: dashboard de visión general (instituciones activas, sedes por institución, conteo de usuarios por rol por institución), gestión de instituciones (crear, modificar, desactivar) y vista de funciones activas por institución.
- **UI del Superadmin resuelta:** el tablero Kanban operativo de tenants **no es para el Superadmin** (su identidad global no tiene catálogos por tenant); en la 012 se oculta/reemplaza por la vista de control.

## Próximos pasos
- **012** CRUD administrativo + panel Superadmin ampliado; luego **013/014** ciclos de ticket/catálogo, **015** informes, **016** notificaciones, Hito 2.
- `stack.md` mantiene menciones de "12 entidades" (superadas por la sección 011): revisar en el cierre, no bloquean.
