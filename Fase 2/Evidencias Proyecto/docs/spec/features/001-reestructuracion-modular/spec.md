# Feature 001: Reestructuración Modular del Proyecto

**Estado:** Aprobado para implementación
**Release:** 1.0 — Sprint 1
**Tipo:** Saneamiento técnico (sin valor de negocio por sí mismo)

## 1. Problema

El código no cumple `docs/spec/stack.md`, que se declara norma definitiva. `AGENTS.md` §9
registra 4 desviaciones conocidas. La más grave: `app/services/` no existe, y los 3 endpoints ejecutan transacciones y reglas de negocio inline.

Impacto actual:

- `tickets.py:crear_ticket` abre **dos** `commit()` separados para ticket y detalles.
  Si el segundo falla, queda un ticket huérfano. Contradice `constitucion.md:18`
  (Consistencia Transaccional).
- `inventario.py:registrar_movimiento` mezcla validación de stock, mutación y registro
  de auditoría en un controlador.
- `models.py` (147 líneas) y `schemas.py` (107 líneas) monolíticos.
- Backend sin un solo `__init__.py`: funciona por namespace packages implícitos, frágil
  en la imagen Docker.
- Frontend sin `shared/`, sin `guards/`, sin `interceptors/`, sin `services/` por feature,
  con las 4 rutas centralizadas en `app.routes.ts`.
- `inventario.component.ts:39` renderiza `stockList` hardcodeado, no consulta la API.

## 2. Objetivo

Dejar el proyecto alineado con `docs/spec/stack.md` sin alterar comportamiento observable.

## 3. Alcance

### Dentro

- Backend: `app/db/`, `app/api/dependencies.py`, `app/api/v1/api.py`, `app/services/`,
  `__init__.py` en todos los paquetes, `models/` y `schemas/` partidos por dominio,
  los 7 `class Config` migrados a Pydantic v2.
- Extracción de las 15 rutas a funciones de servicio.
- Corrección de la transacción partida de `crear_ticket`.
- Frontend: `shared/`, `core/guards/`, `core/interceptors/`, `services/` y
  `*_routes.ts` por feature, templates inline extraídos a `.html`,
  `*ngIf`/`*ngFor` → `@if`/`@for`.
- Convenciones: identificadores en español (§4).
- Documentación: `roadmap.md` reparado, `stack.md` y `AGENTS.md` actualizados.

### Fuera

- Modelo de datos 3NF de 12 entidades (`AGENTS.md` §7). **`database/01_esquema.sql` no se toca** (antes `script_apt_erp.sql`; renombrado en la Feature 002, sin cambios de DDL).
- `core/security.py` y `endpoints/auth.py` — son funcionalidad nueva (JWT), no
  reestructuración. Quedan como desviación documentada.
- Migrar `inventario` de datos hardcodeados a la API real. Es Feature 002.
- Clerk, guards con lógica real, multi-tenant.
- `datetime.utcnow()` deprecado en Python 3.12+ (`tickets.py:50`). Se marca, no se arregla.

## 4. Regla de convención: español en identificadores

**Alcance:** variables, parámetros, funciones, métodos, clases, campos de interfaces
y type aliases — en Python y TypeScript.

**Excepciones (nunca se renombran):**

- Nombres de archivo y carpetas: los de `stack.md`.
- Tablas y columnas de BD (§7).
- APIs de terceros: `BaseModel`, `ConfigDict`, `BaseSettings`, `SettingsConfigDict`,
  `Column`, `String`, `relationship`, `FastAPI`, `APIRouter`, `Depends`,
  `HTTPException`, `signal`, `computed`, `inject`, `input`, `output`,
  `CanActivateFn`, `HttpInterceptorFn`, `loadComponent`, `loadChildren`.
- Sufijos estructurales de Angular: `Component`, `Service`, `Guard`,
  `Interceptor`, `Pipe`, `Routes`. Se españoliza el dominio, no el sufijo.

**Renombres esperados:**

| Actual | Nuevo |
|---|---|
| `UsuarioCreate` | `UsuarioCrear` |
| `TicketResponse` | `TicketRespuesta` |
| `TicketUpdateEstado` | `TicketActualizarEstado` |
| `query`, `ticket_data`, `detalles_data` | `consulta`, `datos_ticket`, `datos_detalles` |
| `read_root`, `health_check` | `leer_raiz`, `verificar_salud` |
| `stockList` (Angular) | `listaStock` |

Las 12 clases SQLAlchemy (`Ticket`, `Usuario`, `Inventario`…) ya están en español y no cambian.

En Angular, `auth.service.ts` exporta `AutenticacionService`, `role.guard.ts` exporta
`RolGuard`. El sufijo se preserva porque es vocabulario de Angular; el dominio se traduce.

## 5. Criterios de aceptación

- [x] **AC-1** `cd backend && uvicorn app.main:app --reload` levanta y `/docs` responde.
- [x] **AC-2** Los 15 endpoints devuelven **el mismo JSON** que antes del cambio.
      Verificado diffando el OpenAPI de `/openapi.json` antes y después.
- [x] **AC-3** `grep -r "class Config" backend/` → 0 resultados.
- [x] **AC-4** `grep -r "@NgModule" frontend/src` → 0 resultados.
- [x] **AC-5** `grep -rn "db.commit()" backend/app/api/` → 0 resultados.
- [x] **AC-6** `find backend/app -name "__init__.py"` → 1 por cada directorio con `.py`.
- [x] **AC-7** `cd backend && pytest` pasa (mínimo: smoke de los 15 endpoints).
- [x] **AC-8** `crear_ticket` persiste ticket + detalles en **una** transacción ACID.
- [x] **AC-9** `cd frontend && npm run build` compila sin errores.
- [x] **AC-10** `app.routes.ts` usa `loadChildren`; ninguna feature importa otra.
- [x] **AC-11** Cero `*ngIf`, `*ngFor`, `CommonModule` en `frontend/src/app/`.
- [x] **AC-12** `database/01_esquema.sql` sin cambios en `git diff`. Cumplido: el archivo se renombró desde `script_apt_erp.sql` en la Feature 002 (prefijo de orden, ver `AGENTS.md` §4), pero el DDL es byte a byte idéntico; `git diff HEAD -M` solo reporta las líneas de comentario añadidas a la cabecera.
- [x] **AC-13** `AGENTS.md` §9 sin la sección "Desviaciones de stack.md".
- [x] **AC-14** `roadmap.md` sin bloque de código envolvente ni artefactos `[cite: N]`.
- [x] **AC-15** Todo identificador del §4 renombrado; cero residuos en `grep`.

## 6. Restricciones

- `AGENTS.md` §7: sin paquetes nuevos sin análisis. `pytest` y `httpx` van a
  `requirements-dev.txt`, fuera de la imagen de producción.
- `constitucion.md:17` — Trazabilidad Absoluta: `registrar_movimiento` debe seguir
  escribiendo en `movimiento_inventario`. La extracción no puede perderlo.
- `constitucion.md:18` — AC-1 de negocio: la extracción no puede partir más transacciones de las que ya existen.