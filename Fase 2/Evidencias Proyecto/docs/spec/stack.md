# Constitución: Stack Tecnológico y Reglas de Arquitectura

## Precedencia de la norma

Todo lo que sigue es norma. Si el código actual no la cumple, la norma gana: se corrige el código, no al revés. La migración de estructura está especificada en `docs/spec/features/001-reestructuracion-modular/`.

## 1. Componentes del Stack (estado actual)
- **Frontend SPA**: Angular 18.2+, TypeScript 5.5, Tailwind CSS 3.4 (Standalone Components, Signals).
- **Backend API**: Python 3.10+, FastAPI, Pydantic v2, SQLAlchemy 2.0 con psycopg2 (síncrono).
- **Base de Datos Relacional**: PostgreSQL 16, codificación UTF-8. Docker Compose: puerto local 5433, contenedor 5432, base por defecto `apt_erp`.
- **Identidad**: Clerk (Feature 006, Release 2.0). El frontend administra la sesión con
  `@clerk/clerk-js` (UI prebuilt embebida) y presenta el token vigente como Bearer; FastAPI
  valida el JWT de sesión por JWKS de `CLERK_ISSUER` (`core/security.py`) y consulta el
  Backend API de Clerk con `CLERK_SECRET_KEY` para obtener el correo primario verificado y
  vincularlo a un `usuario` local. Config en `backend/app/core/config.py`
  (`CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_ISSUER`). No existe emisión ni
  aceptación de JWT local HS256.
- **Entorno de Contenedores**: Docker Compose levanta `db`, `backend` (puerto 8000) y `frontend` (puerto 8080). pgAdmin no está implementado.

## 2. Estructura de Directorios (Definitiva)

> **Nota de migración**: el código actual está en fase de migración a esta estructura, que es la normativa desde hoy (AGENTS.md describe la nueva estructura).

Para lograr un proyecto verdaderamente modular, escalable y mantenible, la estructura de carpetas debe seguir principios de arquitectura limpia (Clean Architecture) en el backend y diseño guiado por el dominio (Domain-Driven Design - DDD) en el frontend.

Aquí tienes la estructura profesional definitiva, adaptada exactamente a FastAPI y Angular 18+ (Standalone).

### 1. Estructura Raíz del Proyecto
Esta es la vista global dentro de tu carpeta Fase 2/Evidencias Proyecto/. Aísla la infraestructura, la documentación y las dos aplicaciones.

```text
Evidencias Proyecto/
├── docker-compose.yml         # Orquestador de servicios (DB, Backend, Frontend)
├── .env                       # Variables de entorno globales (oculto en git)
├── docs/
│   └── spec/                  # Metodología SDD (Constitution, Features, Tasks)
├── database/                    # Orquestados por el prefijo: ver abajo
│   ├── 01_esquema.sql           # DDL del modelo 3NF (12 entidades)
│   └── 02_datos_semilla.sql     # TRUNCATE + INSERT de datos de QA
├── backend/                   # 🐍 Entorno FastAPI
└── frontend/                  # 🅰️ Entorno Angular 18
```

### 2. Estructura del Backend (FastAPI + SQLAlchemy)
En FastAPI, la mejor forma de escalar es separar los endpoints (controladores) de la lógica de negocio (servicios). Esto evita que los archivos de rutas se vuelvan gigantescos.

```text
backend/
├── requirements.txt
├── Dockerfile
├── tests/                     # Suite de pruebas automatizadas (pytest)
│   ├── conftest.py            # Fixtures de pruebas (DB en memoria, cliente de prueba)
│   └── api/                   # Pruebas de endpoints
└── app/
    ├── __init__.py
    ├── main.py                # Punto de entrada (instancia de FastAPI y CORS)
    │
    ├── core/                  # Configuraciones globales y seguridad
    │   ├── config.py          # Variables de entorno (Pydantic Settings)
    │   └── security.py        # Validación del JWT de sesión de Clerk (JWKS) y consulta al Backend API
    │
    ├── db/                    # Persistencia
    │   └── database.py        # Configuración de SQLAlchemy (Engine, SessionLocal)
    │
    ├── models/                # 🗄️ Modelos de Base de Datos (SQLAlchemy)
    │   ├── __init__.py        # Importa todos los modelos para que Alembic/Base los detecte
    │   ├── institucion.py
    │   ├── usuario.py
    │   ├── producto.py
    │   └── ticket.py
    │
    ├── schemas/               # 📦 DTOs (Pydantic) para validación de In/Out
    │   ├── usuario_schema.py  # Ej: UsuarioCreate, UsuarioResponse
    │   ├── producto_schema.py
    │   └── ticket_schema.py
    │
    ├── services/              # 🧠 Lógica de Negocio (Transacciones ACID)
    │   ├── auth_service.py    # Resuelve la identidad de Clerk y la vincula al usuario local (Feature 006)
    │   ├── ticket_service.py  # Descuenta stock, cambia estados, etc.
    │   ├── usuario_service.py # Alta de usuarios y validación de correo duplicado
    │   └── inventario_service.py
    │
    └── api/                   # 🌐 Capa de Rutas (Endpoints)
        ├── dependencies.py    # Inyecciones (ej: get_db, get_current_user)
        └── v1/
            ├── api.py         # Une todos los routers de v1 (APIRouter principal)
            └── endpoints/     # Controladores ligeros
                ├── auth.py
                ├── usuarios.py
                ├── inventario.py
                └── tickets.py
```

**Regla de oro del Backend**: El router en `api/v1/endpoints/tickets.py` solo recibe la petición HTTP, valida con schemas y llama a `services/ticket_service.py`. Todo el procesamiento complejo y las consultas a la base de datos se hacen en el servicio.

#### Autorización por rol (Feature 007)

La autorización por rol es **norma** desde la Feature 007 y separa la frontera de seguridad
(backend) de la navegación (frontend). Es el patrón a seguir para cualquier operación nueva:

- **Política central.** `backend/app/core/permisos.py` define los cuatro literales de rol
  (`RolConocido`: `Superadmin`, `Administrador`, `Bodeguero`, `Solicitante`; `Admin` es solo
  abreviatura documental, sin alias runtime) y `MATRIZ_PERMISOS`, un mapa explícito
  `(MÉTODO, ruta) → roles permitidos`. Una operación ausente de la matriz **no concede**
  permiso a nadie.
- **Dependencia por operación.** Cada endpoint declara su permiso con
  `requiere_operacion(metodo, ruta)` o `requiere_roles(...)` desde
  `backend/app/api/dependencies.py`. La dependencia reutiliza `get_current_user` (la
  identidad Clerk se resuelve una sola vez por solicitud): sesión ausente o inválida
  conserva el **401**; identidad autenticada sin el rol requerido obtiene **403**; un rol
  ausente, vacío o desconocido nunca concede. `respuestas_de_autorizacion()` publica 401 y
  403 en `/openapi.json` sin alterar el `response_model` de éxito.
- **Alcance de datos en servicios, no en routers.** La regla por objeto/institución vive en
  `backend/app/services/ambito_service.py`: deriva la institución por
  `usuario.departamento_id → departamento.institucion_id`. Un ámbito no resoluble para un rol
  limitado responde **403** (nunca se eleva a global); solo `Superadmin` es global. Los
  servicios reciben la identidad ya resuelta, no flags de confianza del cliente. El catálogo
  maestro de producto/categoría y el `stock_total` de `GET /tickets/catalogos` permanecen
  globales en 007; su particionamiento es la Feature 008.
- **Navegación en el frontend.** `frontend/src/app/core/guards/role.guard.ts` (`RolGuard`,
  standalone) espera la identidad de `AutenticacionService` sin repetir `/auth/me` y compara
  el rol exacto; `frontend/src/app/core/auth/roles.ts` es la única fuente de roles de ruta y
  capacidades. La denegación navega a `/acceso-denegado` y no cierra sesión ni manda a
  `/login`. El guard es navegación, **no** la frontera de seguridad: la autorización real es
  la API (un cliente puede llamarla sin Angular).

#### Read models de consulta (Feature 002)

Un schema Pydantic con `model_config = ConfigDict(from_attributes=True)` sirve para
serializar **una** entidad ORM. En cuanto la consulta cruza tablas y agrega, ese schema
miente: Pydantic busca los campos en el objeto y no los encuentra.

El patrón que usa `listar_existencias()` en `inventario_service.py`:

- El schema de salida **no** lleva `from_attributes`. Lo arma el service a mano.
- **Una** consulta con `select()` de estilo Core, con los onclause **explícitos**
  (`join` / `outerjoin` con la condición a la vista): al elegir columnas sueltas no hay
  entidad en el `FROM` desde la que SQLAlchemy deduzca el join.
- La fila es la **unidad de información** (una sede), así que se agrupa en Python con un
  `dict` por clave primaria, en vez de con `GROUP BY`. `dict` conserva el orden de
  inserción, con lo que el `ORDER BY` de SQL se propaga solo al arma
  `list(acumuladores.values())`.
- Un filtro que dependa del agregado (`solo_criticos` sobre `stock_total`) **no** puede ir
  en el `WHERE`: se aplica en Python después de agrupar. La base de datos acota por texto,
  categoría y sede; solo el agregado se resuelve en memoria, sobre un conjunto ya acotado.

Es el patrón a seguir para cualquier consulta de lectura que no sea "una tabla, una fila".

#### Variante: catálogo multi-lista (Feature 003)

`obtener_catalogos()` en `ticket_service.py` devuelve cuatro listas en un solo DTO, y ahí
el patrón anterior se abre en dos:

- **Una consulta por lista, no un `UNION`.** Los cuatro conjuntos no comparten clave y un
  `UNION` obligaría a castear filas de 3 columnas a 5. Cada lista usa la técnica que le
  corresponde: las dos de entidad son `select(Modelo)` con `.scalars()`, y las dos que
  cruzan tablas son `select()` de columnas con `.mappings()` para validar el DTO desde dict.
- **Aquí sí hay `GROUP BY`, agrupando por clave primaria** (`Producto.producto_id`), porque
  el agregado es una sola columna y no hace falta acumular en Python. Las columnas del
  `group_by` tienen que listar **todas** las del `SELECT`: PostgreSQL 16 lo exige y SQLite es
  más laxo, así que un `group_by` incompleto pasa la suite en memoria y revienta en el
  contenedor.
- **`outerjoin` + `func.coalesce(func.sum(...), 0)`** cuando el DTO declara `NOT NULL` y la
  fila puede no existir: un producto sin filas en `inventario` sale en `0`, no en `None`.
- **El orden de las listas es parte del contrato**, no un detalle: los desplegables del
  frontend toman `estados[0]` como estado inicial (D-4 de la 003). Ordenar por
  `estado_id` da el primero del flujo; ordenar por nombre daría otro.

#### Modelo relacional y particionamiento por institución (Feature 008)

La Feature 007 dejó el catálogo maestro (`categoria`, `producto`) y el `stock_total` de
`/tickets/catalogos` como excepción global. La Feature 008 los particiona por institución
sobre el **mismo modelo de 12 entidades 3NF**: no se crean entidades ni relaciones de
dominio nuevas; solo se añaden atributos de pertenencia y claves/restricciones compuestas
en tablas existentes. Esta es la justificación que exige `AGENTS.md` §7 antes de alterar
modelos, DDL o el esquema de datos.

**Pertenencia institucional explícita y derivada**

- `categoria.institucion_id` y `producto.institucion_id` (`VARCHAR(20)`, `NOT NULL`, FK a
  `institucion`) hacen que cada registro del catálogo pertenezca a una sola institución
  (D-1). Dos instituciones pueden repetir `nombre_cat`/`nombre`: son filas independientes y
  sus identificadores no sirven para acceder a la otra (AC-1, AC-2).
- `inventario.institucion_id` se **deriva del departamento** y la mantiene el servicio
  (D-2); no es un ámbito independiente que pueda contradecir al departamento.
  `ticket.institucion_id` se deriva del solicitante (`usuario → departamento → institucion`)
  y `detalle_ticket.institucion_id`, del ticket. Son anclas institucionales para las claves
  compuestas, con valores mantenidos por el servicio.
- `rol`, `prioridad` y `estado_ticket` **no** reciben pertenencia: siguen globales y
  compartidos por todas las instituciones (D-5, AC-3). `institucion`, `departamento`,
  `usuario`, `categoria`, `producto`, `inventario`, `movimiento_inventario`, `ticket` y
  `detalle_ticket` quedan aislados directa o transitivamente (`movimiento_inventario` lo
  hereda por su `inventario_id`, sin columna nueva; es auditoría inmutable).

**Claves simples conservadas y claves compuestas como destinos**

Se conservan las PK simples actuales (`categoria_id`, `producto_id`, `departamento_id`,
`ticket_id`, `inventario_id`, …): los identificadores públicos no cambian y los contratos
existentes siguen válidos. La pertenencia se garantiza con claves únicas compuestas que
sirven de destino a FK compuestas, de modo que PostgreSQL rechace asociaciones cruzadas:

| Tabla | Clave única compuesta | Para qué |
|---|---|---|
| `categoria` | `(institucion_id, categoria_id)` | destino de la FK producto→categoría |
| `producto` | `(institucion_id, producto_id)` | destino de inventario→producto y detalle→producto |
| `departamento` | `(institucion_id, departamento_id)` | destino de inventario→departamento |
| `ticket` | `(institucion_id, ticket_id)` | destino de detalle→ticket |

**Relaciones compuestas que el esquema hace cumplir**

- `producto (institucion_id, categoria_id) → categoria (institucion_id, categoria_id)`:
  un producto solo puede apuntar a una categoría de su misma institución. Sustituye a la FK
  simple `producto.categoria_id → categoria.categoria_id`, que queda subsumida.
- `inventario (institucion_id, departamento_id) → departamento (institucion_id, departamento_id)`
  **y** `inventario (institucion_id, producto_id) → producto (institucion_id, producto_id)`:
  como `inventario.institucion_id` es única por fila, ambas FK obligan a que el departamento
  y el producto del inventario compartan institución; no hay vía para un inventario con
  producto ajeno (AC-2, AC-4). Se mantiene además la FK a `institucion` y la unicidad
  `(departamento_id, producto_id)` existente.
- `detalle_ticket (institucion_id, ticket_id) → ticket (institucion_id, ticket_id)` y
  `detalle_ticket (institucion_id, producto_id) → producto (institucion_id, producto_id)`:
  el detalle queda anclado a la institución de su ticket y obligado a un producto de esa
  misma institución (AC-4). La coherencia del `ticket.institucion_id` con la institución del
  solicitante la valida el servicio en la transacción de alta (AC-11), porque la institución
  del usuario se deriva de su departamento y **no se duplica en `usuario`**, que no se
  modifica en esta feature.

Se descarta confiar solo en filtros de Python: dejaría una vía para insertar referencias
cruzadas fuera del servicio. También se descarta duplicar el nombre como clave o cambiar las
PK, porque rompería la integridad y la compatibilidad de identificadores.

**Compatibilidad y migración**

- `database/01_esquema.sql` pasa a crear el modelo particionado para instalaciones nuevas;
  `database/02_datos_semilla.sql` siembra al menos dos instituciones con catálogo y stock
  homónimos y distintos (AC-1, AC-20).
- Las bases existentes se actualizan con
  `database/98_migracion_particionamiento_institucional.sql`, **idempotente y no
  destructivo**: infiere la institución de cada categoría/producto legado a partir de
  inventario y de detalle/ticket/usuario/departamento, y **aborta sin cambios** identificando
  el registro si la pertenencia es ambigua (AC-14). Preserva IDs, usuarios, tickets,
  detalles, stock y movimientos, y una segunda ejecución no altera datos operativos (AC-15).
  El prefijo `98_` corre antes de `99_migracion_retiro_password.sql`, que no se renombra.
- Las PK simples intactas mantienen la compatibilidad de identificadores en la API. Las
  lecturas globales de Superadmin ganan atribución explícita de institución sin fusionar
  registros de instituciones distintas (AC-8).
- La suite SQLite funciona pero no acredita claves/restricciones compuestas ni la migración;
  esas semánticas se verifican contra PostgreSQL 16 (AC-18).

### 3. Estructura del Frontend (Angular 18 Standalone)
En Angular moderno (sin NgModules), la clave es el agrupamiento por Características (Features). Esto facilita el Lazy Loading (carga perezosa) y hace que la aplicación escale sin que el código se enrede.

```text
frontend/
├── package.json
├── tailwind.config.js         # Configuración de Tailwind CSS
├── angular.json
└── src/
    ├── main.ts                # Inicialización de Angular Standalone
    ├── index.html
    ├── styles.scss            # Estilos globales y capas de Tailwind
    ├── assets/                # Imágenes, íconos y logos
    └── app/
        ├── app.component.ts   # Componente raíz (<router-outlet>)
        ├── app.routes.ts      # Enrutador principal (Lazy loading de features)
        ├── app.config.ts      # Proveedores globales (HttpClient, Router)
        │
├── core/              # ⚙️ Cosas de un solo uso (Singletons)
        │   ├── guards/        # Protección de rutas (auth.guard.ts, role.guard.ts)
        │   ├── interceptors/  # Interceptores HTTP (token.interceptor.ts inyecta el Bearer de Clerk)
        │   └── services/      # Servicios globales puros (auth.service.ts → AutenticacionService)
        │
        ├── shared/            # 🧩 Tipos y piezas reutilizables por cualquier feature
        │   ├── config/        # url-api.ts → URL_API (constante de la API, sin dependencia de dominio)
        │   └── interfaces/    # Tipos TypeScript que reflejan los schemas del backend
        │
        └── features/          # 🚀 Dominios de Negocio (Smart Components)
            ├── dashboard/
            │   ├── dashboard.component.ts
            │   └── dashboard.routes.ts
            │
            ├── inventario/
            │   ├── services/               # inventario.service.ts (importa URL_API de shared/config)
            │   ├── inventario.component.ts # Vista principal
            │   └── inventario.routes.ts
            │
            ├── tickets/
            │   ├── services/               # ticket.service.ts
            │   ├── tickets.component.ts
            │   └── tickets.routes.ts
            │
            └── administracion/
                ├── services/               # usuario.service.ts
                ├── administracion.component.ts
                └── administracion.routes.ts
```

**Nota 1**: existe además una cuarta feature, `features/administracion/`, que agrupa la gestión de usuarios, roles e instituciones. No figura en el diagrama original pero forma parte del sistema (`AGENTS.md` §2) y se documenta aquí para que la estructura real y la norma no diverjan.

**Nota 2 — `shared/components/` y `shared/pipes/` están planificados pero vacíos.** Los diagramas los preveen; la Feature 001 no los creó porque ningún componente actual tendría un consumidor real, y un componente sin uso es código muerto. **La Feature 002 vuelve a revisar la pregunta y vuelve a no crearlos**: la barra de filtros y el panel de categorías de la vista de inventario son específicos de ese dominio, y su lógica (los conteos por categoría antes del filtro) no le sirve a otra feature tal cual. Se crean en la feature que agregue **el segundo** consumidor; mientras haya uno, la regla es "código de la feature".

**Nota 3 — sin subcarpeta `components/` en las features.** Los componentes viven en la raíz de su feature. `plan.md` de la Feature 001 los situaba en `features/*/components/`; prevalece este documento.

**Nota 4 — `shared/config/url-api.ts` (Feature 003).** `URL_API` nació dentro de
`features/inventario/services/inventario.service.ts`, lo que incumplía en los hechos el
`AC-10` de la Feature 001 ("nada fuera de `shared/`") en cuanto una segunda feature lo
necesitó. Vive ahora en `shared/config/` porque es una constante de infraestructura de la
que dependen todas las features y no pertenece a ningún dominio. Si alguna vez necesita
diferirse por entorno, se resuelve con un interceptor de entorno, no con un segundo
`URL_API` en cada feature.

**Nota 5 — errores de validación del backend en el formulario (Feature 003).** FastAPI
responde 422 con `detail` como lista de objetos `{"loc": [...], "msg": ...}`. Para un
`FormArray`, `loc` llega como `['body', 'detalles', <índice de fila>, '<campo>']`, así que
el mapeo toma `loc.at(-2)` como índice de fila y `loc.at(-1)` como nombre de campo. El caso
`['body', 'asunto']` no tiene fila y hay que tratarlo aparte: no se puede usar un alias de
plantilla en el `@else if` de un `@if` para repetir la condición del error de la cabecera.

**Regla de oro del Frontend**: Todo lo que va en `features/` es específico de ese módulo de negocio y debe ser Lazy Loaded desde `app.routes.ts` con `loadChildren`. Todo lo que va en `shared/` puede ser usado por cualquier feature. No uses clases de CSS quemadas en el HTML, usa clases de Tailwind. Todo se importa con la función `inject()` de Angular 14+.

## 4. Convención de idioma: identificadores en español

Aplica a **backend y frontend**. Definido en `AGENTS.md` §6, originate en Feature 001.

**En español:** variables, parámetros, funciones, métodos, clases, campos de interfaces y type aliases.

```text
Backend      listar_productos()   crear_ticket()   ServicioInventario
             UsuarioCrear         TicketRespuesta  InventarioRespuesta
Frontend     obtenerTickets()     listaStock       AutenticacionService
```

**No se renombran:**

- Nombres de archivo y carpetas — los de este documento.
- Tablas y columnas de BD — ya están en español y son inmutables (§4 de `AGENTS.md`).
- APIs de terceros y de framework.
- Sufijos estructurales de Angular (`Component`, `Service`, `Guard`, `Interceptor`, `Pipe`, `Routes`): se traduce el dominio, no el sufijo. Por eso `auth.service.ts` exporta `AutenticacionService`.

**Los 12 modelos de dominio ya cumplen** la regla: `Institucion`, `Departamento`, `Rol`, `Usuario`, `Categoria`, `Producto`, `Inventario`, `MovimientoInventario`, `Prioridad`, `EstadoTicket`, `Ticket`, `DetalleTicket`.

**Los DTO de lectura también, y en las dos capas.** La Feature 002 agregó un par de
schemas y su par de tipos de TypeScript, con el mismo nombre en ambos lados:

```text
Backend      SedeExistenciaRespuesta   ProductoExistenciaRespuesta
             es_stock_critico()        listar_existencias()
Frontend     SedeExistencia            ProductoExistencia
             obtenerExistencias()
```

Los campos viajan en `snake_case` a propósito: el backend serializa sin alias de
camelCase, y normalizar en la vista partaría la regla de "los tipos reflejan 1:1 los
schemas". `shared/interfaces/index.ts` es el único lugar donde viven esos tipos: el
componente los importa, no los declara.

## 5. ¿Por qué esta estructura es la correcta para tu Capstone?

- **Pasa la revisión de cualquier arquitecto de software**: Sigue el principio de Responsabilidad Única (SOLID).
- **Cero dolores de cabeza con OpenCode / IA**: Al tener los servicios separados de las rutas (backend) y las features separadas del core (frontend), el agente de IA sabe exactamente qué archivo modificar sin romper el resto de la aplicación.
- **Escalabilidad directa a Release 2.0**: Clerk ya está integrado (Feature 006). La exigencia de
  identidad se aplica por dependencia de seguridad en el **router agregado**
  (`backend/app/api/v1/api.py`), de modo que todas las rutas de negocio de `/api/v1` piden un
  Bearer válido sin tocar la lógica de Tickets o Inventario; salud y documentación quedan sin
  protección. La autorización por rol se implementó en la Feature 007 (matriz central en el
  backend + `RolGuard` en el frontend; ver §2).