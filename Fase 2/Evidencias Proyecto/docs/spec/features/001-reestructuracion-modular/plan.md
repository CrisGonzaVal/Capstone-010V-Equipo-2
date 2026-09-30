# Feature 001 — Plan Técnico

## 1. Estrategia

4 fases secuenciales, cada una verificable de forma independiente. Se hace backend
completo antes que frontend, porque el frontend consumirá los DTOs finales.

## 2. Fase A — Backend: estructura

### 2.1 Mapa de movimientos

| Origen | Destino |
|---|---|
| `app/core/database.py` | `app/db/database.py` |
| `get_db` (de `core/database.py`) | `app/api/dependencies.py` |
| — | `app/api/v1/api.py` |
| `app/models/models.py` | 6 módulos + `__init__.py` |
| `app/schemas/schemas.py` | 4 módulos `*_schema.py` |
| — | `app/services/` (3 módulos) |

### 2.2 `app/db/database.py`

Contiene solo `engine`, `SessionLocal` y `Base`. `get_db` **sale** de aquí.

### 2.3 `app/api/dependencies.py`

```python
def get_db() -> Generator[Session, None, None]: ...
def get_current_user(...) -> Usuario:  # stub, raise HTTPException(501)
```

El stub es explícito: la autenticación sigue decorativa (`AGENTS.md` §7).

### 2.4 Reparto de los 12 modelos

Agrupados por dominio, siguiendo los 4 módulos que nombra `stack.md`:

| Archivo | Clases |
|---|---|
| `models/institucion.py` | `Institucion`, `Departamento` |
| `models/rol.py` | `Rol` |
| `models/usuario.py` | `Usuario` |
| `models/producto.py` | `Categoria`, `Producto` |
| `models/inventario.py` | `Inventario`, `MovimientoInventario` |
| `models/ticket.py` | `Prioridad`, `EstadoTicket`, `Ticket`, `DetalleTicket` |

`models/__init__.py` re-exporta los 12. Esto mantiene válido `from app.models import Ticket`,
de modo que `services/` y `endpoints/` no se rompen durante la transición.

Las `relationship()` usan strings (`relationship("Departamento", ...)`), así que el orden
de resolución de SQLAlchemy es idéntico al actual. Sin cambio de comportamiento.

### 2.5 Reparto de schemas

| Archivo | Clases |
|---|---|
| `schemas/usuario_schema.py` | `UsuarioBase`, `UsuarioCrear`, `UsuarioRespuesta` |
| `schemas/producto_schema.py` | `CategoriaRespuesta`, `ProductoBase`, `ProductoCrear`, `ProductoRespuesta` |
| `schemas/inventario_schema.py` | `InventarioRespuesta`, `MovimientoCrear` |
| `schemas/ticket_schema.py` | `DetalleTicketCrear`, `DetalleTicketRespuesta`, `TicketCrear`, `TicketActualizarEstado`, `TicketRespuesta` |

Cada `class Config: from_attributes = True` → `model_config = ConfigDict(from_attributes=True)`.
`core/config.py` → `model_config = SettingsConfigDict(env_file=".env")`.

### 2.6 Fase B — Servicios

Extrae las 15 rutas. Inventario de lógica a mover:

| Servicio | Funciones | Regla de negocio |
|---|---|---|
| `ticket_service.py` | `listar_tickets`, `crear_ticket`, `actualizar_estado_ticket` | `estado_id == 4` → sella `fecha_cierre` |
| `inventario_service.py` | `listar_categorias`, `listar_productos`, `crear_producto`, `listar_inventario`, `registrar_movimiento` | ENTRADA suma, SALIDA resta con validación de stock |
| `auth_service.py` | — | stub; el JWT real es funcionalidad futura |

**Corrección ACID en `crear_ticket`.** Hoy:

```
db.add(nuevo_ticket); db.commit()      # commit 1
for d in detalles: db.add(DetalleTicket(...))
db.commit()                            # commit 2
```

Reestructurado a un solo `add` + un solo `commit`. Verificable con un test que fuerza
error en el segundo detalle y comprueba que no queda ticket persistido.

`main.py` queda con `include_router(api.router, prefix="/api/v1")`.

## 3. Fase C — Tests

`tests/conftest.py`: fixture de sesión con SQLite en memoria + `TestClient` de
`app.main:app`. Motor distinto al de producción, pero el mismo código SQLAlchemy.

`requirements-dev.txt`: `pytest`, `httpx` (dependencia dura de `TestClient`).

## 4. Fase D — Frontend

```
app/
├── core/
│   ├── guards/ auth.guard.ts → AutenticacionGuard
│   │ role.guard.ts  → RolGuard
│   ├── interceptors/ token.interceptor.ts → TokenInterceptor
│   └── services/     api.service.ts, auth.service.ts → AutenticacionService
├── shared/
│   ├── components/   button/, modal/, alert/
│   ├── interfaces/   index.ts
│   └── pipes/        fecha.ts
└── features/
    ├── dashboard/    dashboard.component.ts, dashboard.routes.ts
    ├── inventario/   components/, services/inventario.service.ts,
    │                 inventario.component.ts, inventario.routes.ts
    ├── tickets/      components/, services/ticket.service.ts,
    │                 tickets.component.ts, tickets.routes.ts
    └── administracion/  (feature extra, no está en stack.md — se documenta)
```

`app.routes.ts` → `loadChildren` por feature. Cada `*.routes.ts` es un `Routes` propio.

Templates: el Kanban de `tickets.component.ts` (inline) pasa a `tickets.component.html`.
`*ngIf`/`*ngFor` → `@if`/`@for` con `track`. Se elimina `CommonModule` de los 4
componentes. Se borra `app.component.scss` (vacío).

## 5. Estrategia de verificación

1. **Pre-cambio:** guardar `/openapi.json` con el backend levantado.
2. **Post-cambio:** diff contra el snapshot. Si difiere un solo campo → parar (AC-2).
3. `grep` de los criterios AC-3, AC-4, AC-5, AC-6, AC-11, AC-15.
4. `pytest` y `npm run build`.

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Importaciones rotas al partir `models.py` | `__init__.py` re-exporta los 12 |
| Cambio de contrato JSON | Snapshot de `/openapi.json` antes/después (AC-2) |
| `class Config` a medias produce error silencioso | Pydantic v2 lanza `PydanticUserError`; `pytest` lo detecta |
| Reordenar modelos altera el DDL | `__tablename__` explícito en las 12; el DDL no cambia |
| Plantillas grandes en un string | `tickets.component.ts` es el peor caso; se extrae a `.html` |