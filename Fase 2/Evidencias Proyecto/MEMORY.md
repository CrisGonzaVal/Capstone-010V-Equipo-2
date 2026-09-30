# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Feature 001 (Reestructuración modular) completada: backend (routers delgados → services con ACID, DTOs por dominio, Pydantic v2) y frontend (Standalone + inject() + signals + @if/@for con track + loadChildren).
- Backend: 25 tests (pytest) en verde sobre SQLite en memoria. Sin lógica de negocio en `app/api/`, ACID de `crear_ticket` verificado y protegido por test de regresión.
- Frontend: 4 tests en verde (Chrome Headless), build OK (286.80 kB inicial), sin `@NgModule` ni `CommonModule`. Rutas con `loadChildren` y tipos en `shared/interfaces/`.
- Contrato OpenAPI idéntico (AC-2). Modelo 3NF sin modificaciones (AC-12). BD PostgreSQL intacta tras la suite.
- Estructura alineada con `docs/spec/stack.md`. Decisiones y desviaciones documentadas en `tasks.md`.
- Coherencia documental verificada: 15/15 AC de `spec.md` §5 con `[x]`, §Cierre de `tasks.md` cerrado, 0 rutas `.md` rotas. El bloque obsoleto "Deuda técnica conocida" (de `AGENTS.md` y de la skill `fastapi-pydantic-v2`) se borró: afirmaba `class Config` pendientes cuando ya había 0.

## Decisiones (y por qué)
- Capas backend: routers delgados → `app/services/` (transacciones ACID) → ORM. Facilita escalar a Features 002–005 y deja la lógica testeable.
- Frontend 100% Standalone: `inject()` en lugar de constructor, `signal()/computed()` en lugar de RxJS para estado local, `@if/@for` con `track`. Reduce boilerplate y sigue Angular 18.
- No corregir H-1 (FK inválido devuelve 500) en Feature 001: evita cambiar el contrato (AC-2). Mejor mapear a 4xx cuando existan validaciones explícitas (Feature 003).
- No crear `shared/components/` ni `shared/pipes/` vacíos (D-1): evita código muerto. Se crearán cuando haya un consumidor real.
- Kanban con datos de muestra (H-3): no inventar agrupamiento por `estado_id` (resultado falso, ver `ESTADO_CERRADO_ID = 4`). Se resolverá con catálogo de estados (Feature 004).
- `api.service.ts` eliminado (D-3): repartido por feature (`inventario.service.ts`, `ticket.service.ts`, `usuario.service.ts`) para evitar god-service.
- `database/datos_semilla.sql` con datos de QA (10 filas por tabla): standalone, no altera el esquema 3NF, y `script_apt_erp.sql` sigue intacto (AC-12 verde). Es idempotente vía `TRUNCATE ... RESTART IDENTITY CASCADE`.

## Aprendizajes y errores a evitar
- SQLite requiere `PRAGMA foreign_keys=ON` para que las FKs provoquen la violación que dispara el `rollback` en tests.
- Transacciones con hijos: usar `flush()` (no `commit()`) tras crear la cabecera para obtener el PK sin romper la atomicidad.
- Probar por el **seam HTTP** (`TestClient`), nunca consultando la BD directamente en los tests: los hace resistentes a refactors.
- `@if/@for` exige `track` obligatorio (no compila sin él).
- Sin ids fijos en fixtures: usar los ids generados (evita depender de secuencias de identidad).
- Node 24 funciona con Angular 18 pero muestra warnings de paquetes legacy (no bloqueantes).
- `OVERRIDING SYSTEM VALUE` inserta ids explícitos pero **no avanza la secuencia**: tras insertar, hay que `setval(...)` a `MAX(id)` o el siguiente POST autogenerado choca con el id 1 y devuelve 500.
- En PowerShell, `Get-Content -Raw | docker exec` mete el archivo por la codificación de la consola y destruye los acentos (`á` → `??`). Usar `cmd /c "... < archivo.sql"`, que copia bytes crudos.

## Próximos pasos
- Feature 002: Catálogo de insumos clasificado + consulta de existencias (end-to-end API + frontend con tipos).
- Feature 003: Crear ticket con detalles + validaciones. Buen momento para mapear FK inválida a 400/422 (corregir H-1, justificado y acotado).
- Feature 004: Catálogo de estados + Kanban operativo por estados (resolver `estado_id` vs nombre). Aquí se corrige `ESTADO_CERRADO_ID`.
- Feature 005: Despacho transaccional con rebaja automática de stock + auditoría (trazabilidad).
- Feature 006: Aplicar guards/interceptor a rutas + login/JWT real (mantener autenticación decorativa hasta entonces).