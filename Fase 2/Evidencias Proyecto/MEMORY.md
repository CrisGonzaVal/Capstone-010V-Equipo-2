# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…006 cerradas. **006 (autenticación Clerk) CERRADA** (13/Oct/2026): **16 AC en verde**. Backend `pytest` 195 passed; frontend `ng test` 113 SUCCESS; `ng build` OK (`Initial total` 318.93 kB, sin warnings). `/openapi.json` publica `HTTPBearer` y `IdentidadAutenticadaRespuesta` con 6 campos sin `rol_id`. Recorrido funcional en 4200 (login/logout real contra Clerk, `/auth/me` 200 con perfil local "Camila Fernandez"/correo local/"Rol: Administrador"/avatar "C") y humo en 8080 tras reconstruir la imagen.
- 006 entregó: login alojado de Clerk embebido en Angular (`/login` con UI prebuilt) y logout; `AutenticacionService` sobre `@clerk/clerk-js` con signals (sesión e identidad separadas) sin `localStorage`; `tokenInterceptor` adjunta el Bearer de `session.getToken()`; `auth.guard.ts` exige sesión y `role.guard.ts` queda inerte (007). Backend: `core/security.py` valida el JWT por JWKS de `CLERK_ISSUER` y consulta el Backend API con `CLERK_SECRET_KEY`; `GET /api/v1/auth/me` devuelve la identidad local; `get_current_user` se aplica al router agregado.
- 005 entregó: `POST /tickets/{ticket_id}/despacho` (rebaja stock, cierra ticket y crea `SALIDA` en una transacción), `GET /inventario/movimientos` y el PATCH que reserva `EnCurso→Cerrado` con 409. 003/004: catálogos, modal nativo y Kanban.
- Backend 195 tests y frontend 113 tests, todos en verde; estructura alineada con `docs/spec/stack.md`. Agentes en frontmatter V2 nativo.

## Decisiones de la 006
- Clerk es la única autoridad de autenticación: se retiró JWT HS256, el login simulado y el almacenamiento local del token (D-1).
- El correo se lee del Backend API de Clerk (`GET /v1/users/{sub}`) tras validar el JWT; el token de sesión no trae email y no se usa JWT template (D-2/D-6).
- Vínculo local por correo primario verificado contra `usuario.correo` (UNIQUE); sin coincidencia → 401 sin crear usuario; el `sub` no se persiste (D-3).
- `/auth/me` devuelve 6 campos (`usuario_id`, `sub`, `nombre`, `apellido`, `correo`, `rol`), sin `rol_id`; el rol es informativo y la autorización es Feature 007 (D-4/D-13/D-14).
- La identidad local se carga una vez por sesión y se limpia al logout/cambio/error; sesión e identidad son estados separados.
- `CLERK_PUBLISHABLE_KEY` va en `environment.ts` (build time); 8080 es build congelado y exige reconstruir la imagen.

## Aprendizajes y errores a evitar
- **Cierre = verificación, no marcado** (AGENTS.md §8.5): tests verdes no cierran una feature; hacen falta los dos puertos (4200 funcional + 8080 de humo).
- **8080 sirve un build congelado**: `docker compose build frontend` + `up -d --force-recreate frontend`. El backend sí se actualiza solo (`./backend/app` montado + `--reload`).
- **`@clerk/clerk-js` v6 no incluye la UI prebuilt**: hay que cargar el bundle `@clerk/ui` desde el CDN del Frontend API y pasarlo a `load({ ui })`; sin eso `mountSignIn` lanza "Clerk was not loaded with Ui components".
- **`docker compose restart` no recrea el contenedor ni relee el `.env`**: para aplicar variables nuevas hace falta `docker compose up -d` (recrear).
- **Un `CLERK_ISSUER` mal escrito en el `.env` produce 401 silenciosos** en todas las rutas protegidas.
- **Karma**: arranca en watch y esta máquina solo tiene Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless`.
- **SQLite ignora `FOR UPDATE`** y no aplica los CHECK del DDL: el bloqueo de fila y los 422 de constraint se verifican contra PostgreSQL 16 real.

## Próximos pasos
- **Feature 007** (Sprint 3): Angular Route Guards y permisos por rol (`Admin`, `Bodeguero`, `Solicitante`); `role.guard.ts` queda inerte listo para implementarla. Luego 008 (multi-tenant) y 009 (dashboard analítico).
- Los KPI del dashboard (`1,240` productos, `14` tickets, `6` departamentos, `2` alertas y "Actividad Reciente") siguen quemados a propósito: se dejan intactos para resolverlos en la **Feature 009** (dashboard analítico).
