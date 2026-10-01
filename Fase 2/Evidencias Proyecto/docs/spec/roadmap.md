# Constitución: Roadmap de Entregas y Sprints

## Estrategia de Entrega
El proyecto se ejecuta en dos grandes Versiones (Releases), priorizando el motor de abastecimiento operativo antes de integrar la arquitectura SaaS Multi-tenant federada.

## Cómo leer este documento
**Leyenda de estado:** `[x]` implementada y verificada, cerrada · `[!]` implementada y verificada por tests, le falta solo la verificación manual para cerrarse · `[ ]` no iniciada

> El estado de cada feature vive en **una sola columna**, en el índice de especificaciones. Las listas de sprint son la vista cronológica y no llevan estado en prosa, para que no se desincronicen.
> Ojo: en los `tasks.md` de cada feature, `[!]` significa "bloqueado". Acá significa "falta la verificación manual de cierre".

**Siguiente feature:** la primera fila `[ ]` del índice, hoy la **004** (Kanban operativo por estados). Se mueve al cerrar cada una.

---

### Release 1.0 (MVP 1): Sistema Operativo de Insumos y Tickets
*Meta: Sistema end-to-end donde los funcionarios emiten requerimientos de materiales y bodega despacha rebajando el inventario físico.*

#### Sprint 1 (22/Sep/2026 - 12/Oct/2026): Estructura, Catálogo y Emisión de Solicitudes
- [x] Feature 000: Modelado relacional 3NF y entorno Docker local.
- [x] Feature 001: Reestructuración modular del proyecto según `docs/spec/stack.md` (servicios, DTOs por dominio, `shared/`/`guards/` en Angular) y convención de identificadores en español.
- [x] Feature 002: Catálogo de insumos clasificado y consulta de existencias.
- [x] Feature 003: Formulario modal reactivo y persistencia transaccional de tickets con ítems detallados.

#### Sprint 2 (13/Oct/2026 - 02/Nov/2026): Gestión Kanban y Despacho Físico
- [ ] Feature 004: Tablero Kanban operativo con columnas por estados.
- [ ] Feature 005: Endpoint transaccional de despacho con rebaja automática de stock y auditoría.

> **Hito 1 (02/Nov/2026)**: Demostración técnica del flujo de abastecimiento completo ante el docente guía.

---

### Release 2.0 (MVP 2): Plataforma SaaS Multi-Tenant y Seguridad Clerk
*Meta: Extender la solución a múltiples sedes independientes con autenticación cifrada en la nube y roles restringidos.*

#### Sprint 3 (03/Nov/2026 - 23/Nov/2026): Identidad Federada y Control de Acceso
- [ ] Feature 006: Integración de Clerk en Angular y validación JWT en FastAPI.
- [ ] Feature 007: Angular Route Guards y permisos por roles (`Admin`, `Bodeguero`, `Solicitante`).

#### Sprint 4 (24/Nov/2026 - 11/Dic/2026): Aislamiento Multi-Tenant y Métricas
- [ ] Feature 008: Particionamiento lógico de datos por institución (SaaS multi-inquilino).
- [ ] Feature 009: Dashboard analítico de stock crítico y log de alertas.

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
| 004 | 1.0 | 2 | *(sin carpeta)* | `[ ]` No iniciada | — |
| 005 | 1.0 | 2 | *(sin carpeta)* | `[ ]` No iniciada | — |
| 006 | 2.0 | 3 | *(sin carpeta)* | `[ ]` No iniciada | — |
| 007 | 2.0 | 3 | *(sin carpeta)* | `[ ]` No iniciada | — |
| 008 | 2.0 | 4 | *(sin carpeta)* | `[ ]` No iniciada | — |
| 009 | 2.0 | 4 | *(sin carpeta)* | `[ ]` No iniciada | — |
