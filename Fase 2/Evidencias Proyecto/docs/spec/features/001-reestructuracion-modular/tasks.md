# Feature 001 — Checklist de Tareas

Leyenda: `[ ]` pendiente · `[x]` hecho y verificado · `[!]` bloqueado

## Fase 0 — Gate SDD (docs primero)

- [x] Crear `docs/spec/features/001-reestructuracion-modular/` con spec, plan y tasks
- [x] Reparar `docs/spec/roadmap.md` — quitar bloque ```` ```markdown ````, quitar
      `[cite: 14]`, normalizar encabezados
- [x] Roadmap: insertar Feature 001 (reestructuración) en Sprint 1
- [x] Roadmap: renumerar 001-008 → 002-009
- [x] `AGENTS.md` §6 — regla de español en identificadores, con excepciones
- [x] `AGENTS.md` §9 — borrar "Desviaciones de stack.md" (AC-13)
- [x] `.agents/skills/fastapi-pydantic-v2/SKILL.md` — sección de español
- [x] `.agents/skills/angular-standalone/SKILL.md` — sección de español
- [x] `docs/spec/stack.md` — regla de español + documentar feature `administracion`

## Fase A — Backend: estructura

- [x] Guardar snapshot de `/openapi.json` con el backend actual
- [x] Crear `app/db/database.py` desde `core/database.py`
- [x] Borrar `app/core/database.py`
- [x] Crear `app/api/dependencies.py` con `get_db` + stub `get_current_user`
- [x] Añadir `__init__.py` a los 9 paquetes de `app/`
- [x] Partir `models/models.py` → 6 módulos
- [x] Crear `models/__init__.py` re-exportando los 12
- [x] Verificar import: `python -c "from app.models import Ticket, DetalleTicket"`
- [x] Partir `schemas/schemas.py` → 4 módulos `*_schema.py`
- [x] Migrar 6 × `class Config` → `ConfigDict` (AC-3)
- [x] Migrar `core/config.py` → `SettingsConfigDict`
- [x] Verificar: `uvicorn app.main:app --reload` levanta
- [x] Comparar `/openapi.json` contra el snapshot (AC-2)
- [x] **Corrección**: `back_populates` rotos en `Ticket.prioridad` y
      `DetalleTicket.producto` (ver abajo)

### Hallazgo de Fase A — `back_populates` rotos (corregido)

Al arrancar los mappers, SQLAlchemy falló con
`Mapper[Prioridad] has no property 'prioridad'`. La causa: el working copy tenía
cambios **sin commitear** respecto a la versión commiteada, y ambos tenian
`back_populates` inconsistentes:

| Atributo | Estado previo | Corrección |
|---|---|---|
| `Ticket.prioridad` | `back_populates="prioridad"` (working copy) — no existe en `Prioridad` | `"tickets"` |
| `Producto.detalle*` ↔ `DetalleTicket.producto` | commiteado: `Producto.detalles_ticket` vs `DetalleTicket` → `"detalles"` — no emparejaban | unificado a `Producto.detalles` ↔ `"detalles"` |

El seed `database/script_apt_erp.sql` solo contiene DDL, sin `INSERT`, así que el
comportamiento de los ids de `estado_ticket` nunca estuvo definido. Verificar con
`configure_mappers()`: 12 modelos OK.

## Fase B — Servicios

- [x] Crear `app/services/__init__.py`
- [x] Crear `ticket_service.py` con `listar_tickets`, `crear_ticket`, `actualizar_estado_ticket`
- [x] Crear `inventario_service.py` con las 5 funciones
- [x] Crear `auth_service.py` stub
- [x] Reescribir `endpoints/tickets.py` delgado
- [x] Reescribir `endpoints/inventario.py` delgado
- [x] Reescribir `endpoints/usuarios.py` delgado
- [x] Verificar `grep -rn "db.commit()" backend/app/api/` → 0 (AC-5)
- [x] Corregir `crear_ticket` a una sola transacción ACID
- [x] Añadir `summary=` a las 15 rutas (§6)
- [x] Renombrar a español: `read_root`→`leer_raiz`, `health_check`→`verificar_salud`
- [x] Renombrar a español: variables (`query`→`consulta`, `ticket_data`→`datos_ticket`)
- [x] Crear `app/api/v1/api.py` con el `APIRouter` agregador
- [x] `main.py` → `include_router(api.router, prefix="/api/v1")`
- [x] Comparar `/openapi.json` contra el snapshot (AC-2)

### Desviación de `stack.md` en Fase B — `usuario_service.py`

`stack.md` §2 lista `auth_service.py`, `ticket_service.py` e `inventario_service.py`.
No lista un servicio para el CRUD de `usuarios.py`, que si tiene logica (validacion
de correo duplicado + alta). Se creo `usuario_service.py` en vez de mezclar ese CRUD
dentro de `auth_service.py`, cuyo proposito documentado es emitir JWT (Feature 006).
`auth_service.py` queda como stub. Decision registrada en `stack.md` §2.

### Verificacion de Fase B

| Prueba | Resultado |
|---|---|
| AC-2 contrato tras extraer servicios | 12 rutas, 14 esquemas, identico |
| AC-5 `db.commit` en `app/api/` | 0 resultados |
| AC-8 ticket con detalle de producto inexistente | 500, `tickets=0 detalles=0` — revierte todo |
| AC-8 ticket valido con 2 detalles | 201, `tickets=1 detalles=2` — una sola transaccion |
| `summary` en las 15 operaciones | 15/15 |
| Inventario ENTRADA 100 (stock 50) | 201, stock 150 |
| Inventario SALIDA 30 | 201, stock 120 |
| Inventario SALIDA 999 (insuficiente) | 400, sin movimiento registrado |
| Inventario tipo invalido | 400, sin movimiento registrado |
| Trazabilidad (`constitucion.md` §2) | 2 filas en `movimiento_inventario`, solo las exitosas |
| AC-15 identificadores | 13/13 funciones de servicio en espanol |
| BD tras la verificacion | 0 filas en las 12 tablas |

## Fase C — Tests

- [x] Crear `requirements-dev.txt` con `pytest`, `httpx`
- [x] Crear `tests/__init__.py`, `tests/api/__init__.py`
- [x] Crear `tests/conftest.py` — sesión SQLite en memoria + `TestClient`
- [x] Crear `tests/api/test_smoke.py` — los 15 endpoints responden
- [x] Crear test de ACID: error en el 2º detalle no deja ticket huérfano
- [x] `cd backend && pytest` en verde (AC-7)

### Diseno de la suite

- **Seam unico: la interfaz HTTP.** Ningun test importa `app.services` ni consulta
  la sesion de SQLAlchemy. El rollback se comprueba leyendo `GET /api/v1/tickets/`
  y no con un `SELECT count(*)`, siguiendo la regla anti-patron de la skill `tdd`.
- **SQLite en memoria con `PRAGMA foreign_keys=ON`.** SQLite ignora las FKs por
  omision; sin ese PRAGMA el test de atomicidad no podria provocar la violacion
  que dispara el rollback. `StaticPool` mantiene una unica conexion para que la
  base sobreviva al salto de hilo de `TestClient`.
- **PostgreSQL intacto.** La suite no toca el contenedor `db`; se verifico que
  sigue en 0 filas tras correr los 25 tests.
- **Sin ids fijos.** El fixture `datos_base` devuelve los ids generados y se
  consume `estado_cerrado_id` real, en vez de asumir el `ESTADO_CERRADO_ID = 4`
  que resulto ser falso.
- **`cliente_sin_excepcion`.** `TestClient` por defecto relanza la excepcion en
  vez de responder, lo que ocultaba el 500. Este fixture lo expone como respuesta.

### Hallazgos de la Fase C

**H-1 — `POST /api/v1/tickets/` responde 500 ante un `producto_id` inexistente.**

`crear_ticket` no captura el `IntegrityError` de la violacion de FK, asi que
FastAPI responde 500 en lugar de un 4xx. Es **preexistente**: se verifico que la
version previa al refactor tambien devolvia 500, o sea que la extraccion a
servicios no lo introdujo.

La Feature 001 **no lo corrige** porque su mandato es reordenar codigo sin
cambiar el contrato (AC-2), y un 500 -> 400 es un cambio de comportamiento que
corresponde a la feature que implemente la validacion del requerimiento.
Queda registrado en
`tests/api/test_smoke.py::test_ticket_con_producto_inexistente_responde_500_defecto_conocido`
y en los 3 tests de `test_transaccion_ticket.py` que dependen de el. Cuando se
corrija, esos 4 tests deben pasar a 400.

La atomicidad (AC-8) si esta garantizada y verificada: el ticket no se persiste.

### Verificacion de Fase C

| Prueba | Resultado |
|---|---|
| Suite completa | **25 passed** |
| Cobertura del seam | 15 operaciones HTTP, incluidos 4xx y 500 |
| Mutacion: reintroducir `commit()` intermedio | **2 tests en rojo** con `ticket_id: 1` huerfano |
| Suite tras revertir la mutacion | 25 passed |
| PostgreSQL tras la suite | 0 filas (intacto) |

## Fase D — Frontend

- [x] Crear `shared/interfaces/index.ts`
- [x] Crear `core/guards/{auth.guard.ts,role.guard.ts}` (`AutenticacionGuard`, `RolGuard`)
- [x] Crear `core/interceptors/token.interceptor.ts` (`tokenInterceptor`)
- [x] Crear `core/services/auth.service.ts` → `AutenticacionService`
- [x] `features/dashboard/`: + `dashboard.routes.ts`
- [x] `features/inventario/`: `services/inventario.service.ts` + rutas
- [x] `features/tickets/`: `services/ticket.service.ts` + rutas
- [x] `features/administracion/`: `services/usuario.service.ts` + rutas
- [x] `app.routes.ts` → `loadChildren` (AC-10)
- [x] Extraer los 4 templates inline a `.html`
- [x] Migrar `*ngIf`/`*ngFor` → `@if`/`@for` con `track` (AC-11)
- [x] Quitar `CommonModule` de los 4 componentes
- [x] Borrar `app.component.scss` vacío
- [x] Renombrar a español: `stockList`→`listaStock`, `getProductos`→`obtenerProductos`, etc. (AC-15)
- [x] `npm run build` compila (AC-9)

### Desviaciones de `stack.md` en Fase D

**D-1 — `shared/components/` y `shared/pipes/` NO se crearon.**

`plan.md` §4 los listaba (`button/`, `modal/`, `alert/`, `fecha.ts`), pero no habria
consumidor: los botones de las vistas son distintos entre si y no comparten una
API, y el unico modal posible ("Registrar Movimiento") exigiria disenar una vista
nueva, que es alcance de la feature de tickets. Crear componentes sin usar es
codigo muerto que se mantiene sin fino. Se crearan en la feature que si tenga la vista
(`frontend-design` aplica ahi: componente o vista **nueva**).

**D-2 — No se creo `components/` dentro de las features.**

`plan.md` §4 decia `features/inventario/components/` y
`features/tickets/components/`, pero `stack.md` §2 —que es la norma— muestra los
componentes en la raiz de la feature (`features/tickets/tickets.component.ts`) sin
subcarpeta `components/`. Prevalece `stack.md`, segun la regla de este feature.
Los componentes quedaron en la raiz.

**D-3 — `core/services/api.service.ts` se elimino, no se migro.**

`plan.md` §4 lo mantenia junto a `auth.service.ts`. Era un *god service*: mezclaba
catalogo, stock y tickets en un solo archivo con 7 metodos. Sus endpoints se
repartieron en `inventario.service.ts`, `ticket.service.ts` y
`usuario.service.ts`, cada uno junto a la feature que los usa. Conservarlo habria
dejado el problema original intacto.
`URL_API` quedo exportada desde `inventario.service.ts` como constante compartida.

### Hallazgos de la Fase D

**H-2 — El repositorio tenia 2 tests de frontend rotos en `HEAD`.**

`app.component.spec.ts` (generado por `ng new`) exigia
`expect(app.title).toEqual('frontend-app')` y que el `<h1>` contuviera
`Hello, frontend-app`, pero `app.component.ts` declara `title = 'CompuStock ERP'`
y el `<h1>` real dice "Sistema ERP - Gestión de Insumos". Se verifico contra
`git show HEAD:...` que el spec ya estaba commiteado asi. Ademas el tercer test
fallaba por otra causa: sin `provideRouter`, `routerLink`/`router-outlet` no se
resuelven y el fixture no se puede crear.

El spec se reescribio contra el comportamiento real (`titulo`, encabezado real y
un test del signal `sidebarAbierto`), y se agrego `provideRouter(routes)`.
Resultado: 4/4 en verde.

**H-3 — Los datos del Kanban no se pueden cablear a la API todavia.**

Para distribuir tickets en columnas haria falta agrupar por estado, y `Ticket`
solo trae `estado_id` sin el nombre. Como ya quedo demostrado en el backend con
`ESTADO_CERRADO_ID = 4` (un id fijo resulto ser falso), codificar un mapa
`estado_id -> columna` en el frontend repetiria el mismo error en otra capa.
El Kanban se dejo data-driven desde una constante tipada, preservando el
comportamiento actual, y el agrupamiento real llega con el catalogo de estados.

### Verificacion de Fase D

| Prueba | Resultado |
|---|---|
| AC-9 `npm run build` | bundle generado, 286.80 kB inicial |
| AC-10 `loadChildren` | 4 chunks de rutas (185-200 B) + 4 de componentes |
| AC-11 `@if`/`@for` con `track` | 0 ocurrencias de `*ngIf`/`*ngFor` |
| AC-4 `@NgModule` | 0 |
| `CommonModule` | 0 imports |
| `ng test` (Chrome Headless 154) | 4/4 SUCCESS |
| Bundle inicial | 291.51 kB → 286.80 kB (menos `CommonModule`) |

## Cierre

- [x] `git diff database/script_apt_erp.sql` vacío (AC-12)
- [x] `grep -r "@NgModule" frontend/src` → 0 (AC-4)
- [x] `find backend/app -name "__init__.py"` completo (AC-6)
- [x] `grep -r "class Config" backend/` → 0 (AC-3)
- [x] Pasada de grep de AC-15 sobre todo el proyecto
- [x] Actualizar `stack.md` con las decisiones tomadas en este feature
- [x] Marcar Feature 001 como `[x]` en `roadmap.md`

> Verificado el 30/09/2026 los 15 AC de `spec.md` §5: los 15 `[x]`, con
> evidencia de `pytest` 25 verdes, `ng test` 4 verdes, y los greps de
> AC-3/4/5/6/11/15 en cero. AC-13 es un criterio negativo (que §9 de
> `AGENTS.md` *no* contenga una sección "Desviaciones de stack.md") y se
> cumple: esa sección no existe.