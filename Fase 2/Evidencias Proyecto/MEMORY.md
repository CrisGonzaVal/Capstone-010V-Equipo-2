# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…009 implementadas y **cerradas** (008 y 009 con veredicto APROBADO). Backend `pytest`: **540 passed, 5 skipped** (los 5 gated pasan con `POSTGRES_TEST_URL`). Frontend `ng test`: **172 SUCCESS**. Matriz de permisos: **21 operaciones**.
- 009: `GET /api/v1/dashboard/` consolidado (KPIs + alertas por fila + actividad limitada a 10). 008: `institucion_id` en catálogo/inventario/ticket/detalle, claves compuestas y migración `98_` idempotente. 007: autorización por rol (matriz central + `RolGuard`). 006: Clerk. 005: despacho transaccional.
- No queda ninguna fila `[ ]` en el índice de features; el roadmap apunta al **Hito 2** (despliegue + entrega).

## Sprint 5 (en análisis, sin spec todavía)
- Matriz de acciones compartidas por rol **aprobada** por el usuario: **18 casos de uso en 4 módulos** (A administración, C catálogo e inventario, T tickets, R informes y avisos).
- Cobertura por actor: Superadmin 11 · Administrador 17 · Bodeguero 11 · Solicitante 6.
- Candidatas a feature: 010 gestión admin real · 011 instituciones y **entidad `sede`** · 012 ciclo de vida del catálogo · 013 ciclo de vida del ticket (asignado + SLA + historial) · 014 informes PDF/Excel · 015 notificaciones in-app · Hito 2 despliegue.
- **Decisión descartada**: base de datos por institución. Se mantiene la base compartida + `institucion_id` (008); el aislamiento por fila con FK compuestas se argumenta como suficiente.
- Decisiones abiertas para las specs: `sede` como 13ª entidad (¿inventario por sede o por departamento? ¿alcance del Bodeguero?) y SLA del ticket.

## Entregable: diagramas de casos de uso
- `docs/diagramas/`: `casos-uso-general` + `casos-uso-{superadmin,administrador,bodeguero,solicitante}`, en **HTML y PNG** (UML clásico compuesto con el skill).
- Los **5 PNG** se copiaron además a `../Evidencias Grupales/diagramas/` (fuera del proyecto, pedido explícito del usuario) para la entrega grupal; el folder es `Evidencias Grupales` (plural).
- Skill **`diagram-design`** (cathrynlavery) instalado en `.agents/skills/diagram-design/`.

## Aprendizajes y errores a evitar
- `diagram-design` **no tiene tipo "caso de uso"** entre sus 45: se compone a mano con su sistema de diseño, y ahí se relaja la regla de conectores ortogonales (las asociaciones actor→caso son rectas, como en UML real).
- Se editó `references/style-guide.md` del skill con la **paleta CompuStock** (slate + blue); `npx skills update` la revierte.
- `skills-lock.json` **no quedó actualizado** con `diagram-design`: el hash del CLI no es sha256 simple y el comando se interrumpió dos veces. No se inventó un hash.
- PNG sin Playwright: se capturó el elemento `<svg>` con `chrome-devtools` (`take_screenshot` con `uid` + `filePath`), que da un PNG solo-diagrama.
- Cierre = verificación (AGENTS §8.5): hacen falta los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida FK compuestas.
- Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless`.

## Próximos pasos
- Cerrar el inventario de casos de uso y abrir `docs/spec/features/010-…` (spec → plan → tasks).
- La rama `dev` con el trabajo de la 009 y estos diagramas **no se ha commiteado** (decisión del usuario).
