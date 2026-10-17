# Constitución: Roadmap de Entregas y Sprints

## Estrategia de Entrega
El proyecto se ejecuta en dos grandes Versiones (Releases), priorizando el motor de abastecimiento operativo antes de integrar la arquitectura SaaS Multi-tenant federada.

## Cómo leer este documento
**Leyenda de estado:** `[x]` implementada y verificada, cerrada · `[!]` implementada y verificada por tests, le falta solo la verificación manual para cerrarse · `[ ]` no iniciada

> El estado dueño de cada feature vive en **una sola columna**, en el índice de especificaciones. Las listas de sprint son la vista cronológica y llevan únicamente la marca `[x]`/`[ ]` (sin estado en prosa); no son fuente de estado y no deben desincronizarse del índice.
> Ojo: en los `tasks.md` de cada feature, `[!]` significa "bloqueado". Acá significa "falta la verificación manual de cierre".

**Siguiente feature:** 011 — Modelo organizacional (entidad `sede`, stock por sede y encargado de departamento), Sprint 5. El **Hito 2** permanece programado para el 11/Dic/2026.

---

### Release 1.0 (MVP 1): Sistema Operativo de Insumos y Tickets
*Meta: Sistema end-to-end donde los funcionarios emiten requerimientos de materiales y bodega despacha rebajando el inventario físico.*

#### Sprint 1 (22/Sep/2026 - 30/Sep/2026): Estructura, Catálogo y Emisión de Solicitudes
- [x] Feature 000: Modelado relacional 3NF y entorno Docker local.
- [x] Feature 001: Reestructuración modular del proyecto según `docs/spec/stack.md` (servicios, DTOs por dominio, `shared/`/`guards/` en Angular) y convención de identificadores en español.
- [x] Feature 002: Catálogo de insumos clasificado y consulta de existencias.
- [x] Feature 003: Formulario modal reactivo y persistencia transaccional de tickets con ítems detallados.

#### Sprint 2 (01/Oct/2026 - 09/Oct/2026): Gestión Kanban y Despacho Físico
- [x] Feature 004: Tablero Kanban operativo con columnas por estados.
- [x] Feature 005: Endpoint transaccional de despacho con rebaja automática de stock y auditoría.

> **Hito 1 (12/Oct/2026)**: Demostración técnica del flujo de abastecimiento completo ante el docente guía.

---

### Release 2.0 (MVP 2): Plataforma SaaS Multi-Tenant y Seguridad Clerk
*Meta: Extender la solución a múltiples sedes independientes con autenticación cifrada en la nube y roles restringidos.*

#### Sprint 3 (10/Oct/2026 - 14/Oct/2026): Identidad Federada y Control de Acceso
- [x] Feature 006: Integración de Clerk en Angular y validación JWT en FastAPI.
- [x] Feature 007: Angular Route Guards y permisos por roles (los cuatro roles locales). Retiró además la columna obsoleta `usuario.password` (texto plano, sin uso desde la 006) del esquema, la semilla, el modelo SQLAlchemy, el schema `UsuarioCrear` y los tests.

#### Sprint 4 (15/Oct/2026 - 16/Oct/2026): Aislamiento Multi-Tenant y Métricas
- [x] Feature 008: Particionó catálogo e inventario por institución con claves compuestas, ajustó la matriz (Superadmin con lectura global), añadió institución efectiva a `/auth/me` y aplicó migración idempotente a la base real.
- [x] Feature 009: Dashboard analítico de stock crítico y log de alertas (16 AC en verde; endpoint consolidado con KPIs/alertas/actividad reales, criticidad por fila, log derivado sin tabla nueva).

#### Sprint 5 (17/Oct/2026 - 21/Nov/2026): Aislamiento por Esquemas y Administración Institucional
- [x] Feature 010: Multi-tenant por esquemas (control, routing y aprovisionamiento) — carpeta `010-multi-tenant-por-esquemas/`.
- [ ] Feature 011: Modelo organizacional — entidad `sede`, stock por sede y encargado de departamento — carpeta `011-modelo-organizacional/`.
- [ ] Feature 012: Gestión administrativa — CRUD de instituciones, sedes, departamentos y usuarios con UI real — carpeta `012-gestion-administrativa/`.

Las Features 013–016 quedan en backlog posterior al Sprint 5: ciclo de vida del ticket, ciclo de vida del catálogo, informes PDF/Excel y notificaciones in-app, respectivamente. Se incorporarán al índice cuando exista carpeta de especificación para cada una.

> **Hito 2 (11/Dic/2026)**: Despliegue en producción y entrega del proyecto de título.

---

## Índice de Especificaciones por Feature

Cada feature tiene su carpeta en `docs/spec/features/NNN-nombre-feature/` con `spec.md`, `plan.md` y `tasks.md` (flujo SDD, `AGENTS.md` §8).

**Esta tabla es la única fuente del estado.** Una feature está cerrada solo si su `tasks.md` tiene todas las casillas en verde, incluidos los checks de "Cierre" (`AGENTS.md` §8.5: cierre es verificación, no marcado), **y** fue recorrida en los dos puertos del frontend (`AGENTS.md` §8.6): 4200 para el recorrido funcional y 8080 para confirmar que el build de producción de la imagen también la refleja. Tests en verde no cierran una feature.

| # | Release | Sprint | Carpeta | Estado | Especificación |
|---|---|---|---|---|---|
| 000 | 1.0 | 1 | — | `[x]` Cerrada: modelado 3NF + Docker local | — |
| 001 | 1.0 | 1 | `001-reestructuracion-modular/` | `[x]` Cerrada | [spec.md](features/001-reestructuracion-modular/spec.md) · [plan.md](features/001-reestructuracion-modular/plan.md) · [tasks.md](features/001-reestructuracion-modular/tasks.md) |
| 002 | 1.0 | 1 | `002-catalogo-insumos/` | `[x]` Cerrada: 26 AC en verde, 43 casos de backend, 12 tests de frontend y recorrido visual de la vista a 1366px | [spec.md](features/002-catalogo-insumos/spec.md) · [plan.md](features/002-catalogo-insumos/plan.md) · [tasks.md](features/002-catalogo-insumos/tasks.md) |
| 003 | 1.0 | 1 | `003-modal-ticket/` | `[x]` Cerrada: 32 AC en verde, 79 tests de backend (43 previos + 36 nuevos, 4 migrados de 500 a 404), 40 tests de frontend (12 previos + 28 nuevos), recorrido funcional en 4200 con escritura real contra PostgreSQL y recorrido de humo en 8080 tras reconstruir la imagen | [spec.md](features/003-modal-ticket/spec.md) · [plan.md](features/003-modal-ticket/plan.md) · [tasks.md](features/003-modal-ticket/tasks.md) |
| 004 | 1.0 | 2 | `004-tablero-kanban/` | `[x]` Cerrada: 27 AC en verde, 95 tests de backend, 63 tests de frontend, recorrido funcional en 4200 con escritura real contra PostgreSQL y recorrido de humo en 8080 tras reconstruir la imagen | [spec.md](features/004-tablero-kanban/spec.md) · [plan.md](features/004-tablero-kanban/plan.md) · [tasks.md](features/004-tablero-kanban/tasks.md) |
| 005 | 1.0 | 2 | `005-despacho-transaccional/` | `[x]` Cerrada: 28 AC en verde, 140 tests de backend, 69 tests de frontend, recorrido funcional en 4200 con despacho real persistido en PostgreSQL y recorrido de humo en 8080 tras reconstruir la imagen; `FOR UPDATE` y concurrencia (200/409) verificados contra PostgreSQL 16 real | [spec.md](features/005-despacho-transaccional/spec.md) · [plan.md](features/005-despacho-transaccional/plan.md) · [tasks.md](features/005-despacho-transaccional/tasks.md) |
| 006 | 2.0 | 3 | `006-autenticacion-clerk/` | `[x]` Cerrada: 16 AC en verde, 195 tests de backend, 113 tests de frontend, recorrido funcional en 4200 con login/logout real contra Clerk y recorrido de humo en 8080 tras reconstruir la imagen | [spec.md](features/006-autenticacion-clerk/spec.md) · [plan.md](features/006-autenticacion-clerk/plan.md) · [tasks.md](features/006-autenticacion-clerk/tasks.md) |
| 007 | 2.0 | 3 | `007-control-acceso-roles/` | `[x]` Cerrada: 17 AC en verde, 377 tests de backend, 140 tests de frontend, build de producción OK; autorización por rol cliente+servidor con matriz central y ámbito institucional; retiro de `usuario.password` con migración PostgreSQL idempotente (12 usuarios/10 tickets preservados); recorrido funcional en 4200 con los cuatro roles y humo en 8080 tras reconstruir la imagen | [spec.md](features/007-control-acceso-roles/spec.md) · [plan.md](features/007-control-acceso-roles/plan.md) · [tasks.md](features/007-control-acceso-roles/tasks.md) |
| 008 | 2.0 | 4 | `008-particionamiento-institucional/` | `[x]` Cerrada: 21 AC en verde, 487 tests de backend (5 omitidos; 492 verificados con PostgreSQL 16), 153 tests de frontend; recorrido funcional en 4200 con escritura real y humo en 8080 tras reconstruir la imagen; migración idempotente aplicada in-place y matriz de permisos de 20 operaciones | [spec.md](features/008-particionamiento-institucional/spec.md) · [plan.md](features/008-particionamiento-institucional/plan.md) · [tasks.md](features/008-particionamiento-institucional/tasks.md) |
| 009 | 2.0 | 4 | `009-dashboard-analitico-alertas/` | `[x]` Cerrada: 16 AC en verde, 540 tests de backend (5 omitidos; los 5 gated verificados con PostgreSQL 16), 172 tests de frontend; `GET /dashboard/` consolidado con KPIs, log de alertas derivado y actividad limitada a 10; recorrido funcional en 4200 con los cuatro roles contra la BD y humo en 8080 tras reconstruir la imagen; matriz de permisos de 21 operaciones; sin tabla/columna nueva | [spec.md](features/009-dashboard-analitico-alertas/spec.md) · [plan.md](features/009-dashboard-analitico-alertas/plan.md) · [tasks.md](features/009-dashboard-analitico-alertas/tasks.md) |
| 010 | 2.0 | 5 | `010-multi-tenant-por-esquemas/` | `[x]` Cerrada: 18 AC en verde, 601 tests de backend (32 omitidos; 633 verificados con PostgreSQL 16), 198 tests de frontend; multi-tenant por esquemas (`control` global + un esquema por institución, `schema_translate_map` por ejecución, `version_esquema` por tenant), aprovisionamiento Superadmin y portal `/control` standalone; migración idempotente aplicada a `apt_erp` con datos preservados; recorrido funcional en 4200 y humo en 8080 con la imagen reconstruida (`main-GLSSTSDS.js`); matriz de 22 operaciones | [spec.md](features/010-multi-tenant-por-esquemas/spec.md) · [plan.md](features/010-multi-tenant-por-esquemas/plan.md) · [tasks.md](features/010-multi-tenant-por-esquemas/tasks.md) |
| 011 | 2.0 | 5 | `011-modelo-organizacional/` | `[ ]` No iniciada | — |
| 012 | 2.0 | 5 | `012-gestion-administrativa/` | `[ ]` No iniciada | — |
