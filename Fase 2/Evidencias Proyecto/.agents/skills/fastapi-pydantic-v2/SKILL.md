---
name: fastapi-pydantic-v2
description: "FastAPI + Pydantic v2 + SQLAlchemy 2.0 conventions for this repo - no class Config (use ConfigDict), model_validate() over from_orm(), thin routers delegating to app/services/, Session via Depends(get_db). Use whenever creating, editing or reviewing ANY .py file under backend/ - routers, endpoints, schemas, models, services, config or tests."
---

# FastAPI + Pydantic v2

Regla de oro del proyecto (`docs/spec/stack.md` §2): **el router es un controlador delgado**; toda la logica de negocio y las transacciones viven en `app/services/`.

## Reglas

1. **Cero `class Config:`.** Es sintaxis de Pydantic v1, deprecada en v2. Usa `model_config = ConfigDict(...)` (o `SettingsConfigDict` para `BaseSettings`).
2. **`model_validate()` en lugar de `from_orm()`.** `from_orm()` no existe en v2. Con `ConfigDict(from_attributes=True)` se convierte con `Modelo.model_validate(objeto_orm)`.
3. **El router no toca la base de datos.** Recibe la peticion, valida con el schema y llama a un servicio en `app/services/`. Cero `db.query(...)`, `db.add(...)`, `db.commit()` dentro de `app/api/v1/endpoints/`.
4. **`Session` inyectada con `Depends(get_db)`.** Nunca instanciar `SessionLocal()` a mano en un endpoint.
5. **Nada de SQL raw.** Consultas tipadas via ORM o Core de SQLAlchemy 2.0.
6. **Todo router declara `response_model`, `status_code` explicito y `summary`.** Es requisito de `AGENTS.md` §6.
7. **`snake_case`** para funciones y variables.
8. **Identificadores en español** (ver sección siguiente).

## Español en identificadores

Variables, parámetros, funciones, métodos y clases se escriben **en español** (`AGENTS.md` §6).

**No se renombran:**

- Nombres de archivo y carpetas — los de `docs/spec/stack.md`.
- Tablas y columnas de BD.
- APIs de terceros: `BaseModel`, `ConfigDict`, `BaseSettings`, `SettingsConfigDict`, `Column`, `String`, `ForeignKey`, `relationship`, `declarative_base`, `sessionmaker`, `FastAPI`, `APIRouter`, `Depends`, `HTTPException`, `status`.
- Los 12 modelos de dominio ya están en español (`Ticket`, `Usuario`, `Inventario`…) porque replican los nombres de tabla. **No los toques.**

**Sí se renombran:** las clases Pydantic y las variables.

```python
# ❌ INGLÉS
def list_products(db: Session = Depends(get_db)):
    query = db.query(Producto)
    return query.all()

class TicketCreate(BaseModel): ...      # inglés
class TicketResponse(BaseModel): ...   # inglés

# ✅ ESPAÑOL
def listar_productos(db: Session = Depends(get_db)):
    consulta = db.query(Producto)
    return consulta.all()

class TicketCrear(BaseModel): ...
class TicketRespuesta(BaseModel): ...
```

Al renombrar una clase Pydantic cambian los nombres de esquema en `/docs`, pero **no el contrato JSON**: los nombres de campo ya son español y coinciden con las columnas. Actualiza los imports en `endpoints/` y `services/`.

Nombres de clase: `ServicioTicket`, `ServicioInventario`, `ServicioAutenticacion` — aunque el archivo sea `ticket_service.py`. Python no exige que el nombre de clase derive del archivo.

> La sintaxis v1 (`class Config`) ya no existe en el repo: la Feature 001 migró los
> 7 casos a `ConfigDict`/`SettingsConfigDict`. Si encuentras un `class Config`, es
> código nuevo introducido después: trátalo como deuda y no lo copies.

## Antes / después

### `class Config` → `ConfigDict`

```python
# ❌ PYDANTIC v1
class UsuarioResponse(BaseModel):
    usuario_id: int
    nombre: str

    class Config:
        from_attributes = True
```

```python
# ✅ PYDANTIC v2
from pydantic import BaseModel, ConfigDict

class UsuarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    usuario_id: int
    nombre: str
```

### Configuracion con `.env`

```python
# ❌ PYDANTIC v1
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_NAME: str = "apt_erp"

    class Config:
        env_file = ".env"
```

```python
# ✅ PYDANTIC v2
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DB_NAME: str = "apt_erp"
```

### `from_orm()` → `model_validate()`

```python
# ❌ v1 (ademas ya no existe en v2)
dto = UsuarioResponse.from_orm(usuario)

# ✅ v2
dto = UsuarioResponse.model_validate(usuario)
```

El schema debe declarar `model_config = ConfigDict(from_attributes=True)` para que la conversion desde el objeto ORM funcione.

### Router delgado vs. router con logica

```python
# ❌ LOGICA EN EL ROUTER
@router.post("/", response_model=TicketResponse, status_code=201, summary="Crear ticket")
def crear_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    producto = db.query(Producto).filter(Producto.producto_id == payload.producto_id).first()
    if producto is None:
        raise HTTPException(404, "Producto no encontrado")
    if producto.stock < payload.cantidad:
        raise HTTPException(400, "Stock insuficiente")
    producto.stock -= payload.cantidad
    ticket = Ticket(**payload.model_dump(), estado_id=1, creado_en=datetime.utcnow())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket
```

```python
# ✅ ROUTER DELEGADO
@router.post("/", response_model=TicketResponse, status_code=201, summary="Crear ticket")
def crear_ticket(payload: TicketCreate, db: Session = Depends(get_db)) -> Ticket:
    return ticket_service.crear(db, payload)
```

```python
# ✅ app/services/ticket_service.py - aqui vive la transaccion
from sqlalchemy.orm import Session

def crear(db: Session, payload: TicketCreate) -> Ticket:
    producto = db.query(Producto).filter(Producto.producto_id == payload.producto_id).first()
    if producto is None:
        raise HTTPException(404, "Producto no encontrado")
    if producto.stock < payload.cantidad:
        raise HTTPException(400, "Stock insuficiente")

    producto.stock -= payload.cantidad
    ticket = Ticket(**payload.model_dump(), estado_id=1, creado_en=datetime.utcnow())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket
```

El servicio recibe la `Session` ya inyectada y es dueño del `commit`. El router nunca hace `commit`.

## Rutas reales (verificadas)

`get_db` vive en **`app/api/dependencies.py`** (no en `app/core/database.py`, que ya no existe). `stack.md` §2 lo prescribe así y los endpoints lo consumen por módulo, no por import directo:

```python
from app.api import dependencies

def listar_tickets(estado_id: int = None, db: Session = Depends(dependencies.get_db)):
    return ticket_service.listar_tickets(db, estado_id)
```

`app/services/` **ya existe** y tiene `ticket_service.py`, `inventario_service.py`,
`usuario_service.py` y `auth_service.py` (stub). La logica de negocio va ahí; el
router solo cablea. Reusa esos servicios antes de escribir HTTP en un endpoint.

## Cuando ademas aplicar otras skills

- **Escribiendo tests de endpoint o servicio**: carga `tdd`. Test primero por la interfaz publica - para un router eso es un cliente HTTP (`TestClient`), no una llamada directa a la funcion del endpoint. Mockea solo fronteras de sistema, no `Session` si podés usar una base de prueba real.
- **Cambiando el modelo de datos**: las 12 entidades en 3NF son intocables sin justificacion aprobada en `docs/spec/stack.md` (`AGENTS.md` §7). No propongas migraciones por tu cuenta.
- **Tocando autenticacion**: sigue siendo JWT local HS256 decorativo. No implementes Clerk.

## Nada de esto aplica a

`frontend/`. Para Angular usa la skill `angular-standalone`.
