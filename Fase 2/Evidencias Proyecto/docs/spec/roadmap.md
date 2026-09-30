# Constitución: Roadmap de Entregas y Sprints

## Estrategia de Entrega
El proyecto se ejecuta en dos grandes Versiones (Releases), priorizando el motor de abastecimiento operativo antes de integrar la arquitectura SaaS Multi-tenant federada.

---

### Release 1.0 (MVP 1): Sistema Operativo de Insumos y Tickets
*Meta: Sistema end-to-end donde los funcionarios emiten requerimientos de materiales y bodega despacha rebajando el inventario físico.*

#### Sprint 1 (22/Sep/2026 - 12/Oct/2026): Estructura, Catálogo y Emisión de Solicitudes
- [x] Feature 000: Modelado relacional 3NF y entorno Docker local.
- [x] Feature 001: Reestructuración modular del proyecto según `docs/spec/stack.md` (servicios, DTOs por dominio, `shared/`/`guards/` en Angular) y convención de identificadores en español.
- [ ] Feature 002: Catálogo de insumos clasificado y consulta de existencias.
- [ ] Feature 003: Formulario modal reactivo y persistencia transaccional de tickets con ítems detallados.

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

| Feature | Carpeta | Especificación |
|---|---|---|
| 000 | — | Completada (modelado 3NF + Docker) |
| 001 | `001-reestructuracion-modular/` | [spec.md](features/001-reestructuracion-modular/spec.md) · [plan.md](features/001-reestructuracion-modular/plan.md) · [tasks.md](features/001-reestructuracion-modular/tasks.md) |