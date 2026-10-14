# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…007 cerradas. **007 (control de acceso por roles) CERRADA** (14/Oct/2026): **17 AC en verde**. Backend `pytest` **377 passed**; frontend `ng test` **140 SUCCESS** (Edge 155); build de producción OK (reflejado en la imagen reconstruida `sha256:3862981…`). Migración `99_migracion_retiro_password.sql` aplicada a `apt_erp` (**12 usuarios/10 tickets intactos**, segunda ejecución idempotente). Recorrido funcional 4200 con los cuatro roles y humo en 8080 sobre la imagen reconstruida.
- 007 entregó: los cuatro roles locales (`Superadmin`, `Administrador`, `Bodeguero`, `Solicitante`; sin alias `Admin`); autorización cliente+servidor; matriz central `backend/app/core/permisos.py` (18 endpoints) consumida por `requiere_roles`/`requiere_operacion` (`api/dependencies.py`); ámbito institucional en `services/ambito_service.py`; `RolGuard` + `/acceso-denegado` en el frontend; retiro de `usuario.password` (esquema, semilla, modelo `Usuario`, `UsuarioCrear` y tests).
- 006 entregó: login/logout Clerk en Angular, `AutenticacionService` sobre `@clerk/clerk-js`, `tokenInterceptor` con el Bearer, `auth.guard`; backend valida el JWT por JWKS y vincula por correo primario verificado; `GET /auth/me` devuelve `usuario_id/sub/nombre/apellido/correo/rol` (sin `rol_id`).
- 005 entregó: despacho transaccional (rebaja stock + cierre + `SALIDA` en una transacción), movimientos y PATCH `EnCurso→Cerrado` con 409. 003/004: catálogos, modal nativo y Kanban.

## Decisiones de la 007
- Cuatro roles distintos; `Admin` es abreviatura documental, no alias ni normalización runtime (D-1).
- La autorización se exige en servidor (frontera real) y en cliente (navegación); el guard **no** es seguridad (D-2).
- Matriz explícita por operación (D-3); ámbito `usuario → departamento → institución` para Administrador/Bodeguero/Solicitante, **403** si no resuelve; solo Superadmin es global (D-4).
- Ticket ajeno e inexistente responden ambos **404** para no revelar existencia; denegación general es **403** (D-5).
- `POST /usuarios/`: Administrador solo asigna Bodeguero/Solicitante; Superadmin los cuatro (D-6).
- Solicitante autoatribuido al crear ticket (ignora `usuario_id` ajeno); los demás roles conservan `usuario_id` obligatorio (AC-6).
- Catálogo maestro y `stock_total` de `/tickets/catalogos` siguen globales en 007; su particionamiento es 008.
- `usuario.password` se **elimina, no se sustituye** por hash; migración reproducible e idempotente (D-7).

## Aprendizajes y errores a evitar
- **Cierre = verificación, no marcado** (AGENTS.md §8.5): hacen falta los dos puertos; 8080 exige reconstruir la imagen (`docker compose build frontend` + `up -d`) — el backend sí se recarga solo.
- **Pipes de `docker exec` desde PowerShell corrompen la entrada por codificación**: usar `cmd.exe /c "docker exec -i … < script"` (así se documentó la migración).
- **Sin credenciales de contraseña en Clerk**, el recorrido por rol se hizo con sign-in tokens; el login por contraseña se verificó con la cuenta de prueba.
- **Karma**: esta máquina solo tiene Edge; fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test` a secas).
- **SQLite ignora `FOR UPDATE`** y no aplica los CHECK del DDL: esas semánticas —y la migración— se verifican contra PostgreSQL 16 real.
- **`@clerk/clerk-js` v6 no trae UI prebuilt**: cargar `@clerk/ui` desde el CDN del Frontend API y pasarlo a `load({ ui })`.

## Próximos pasos
- **Feature 008** (Sprint 4): particionamiento lógico de datos por institución (SaaS multi-tenant), incluido el catálogo/stock hoy globales.
- **Feature 009**: dashboard analítico de stock crítico y log de alertas (los KPI y "Actividad Reciente" siguen quemados a propósito).
