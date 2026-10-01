# Constitución: Stack Tecnológico y Reglas de Arquitectura

## Precedencia de la norma

Todo lo que sigue es norma. Si el código actual no la cumple, la norma gana: se corrige el código, no al revés. La migración de estructura está especificada en `docs/spec/features/001-reestructuracion-modular/`.

## 1. Componentes del Stack (estado actual)
- **Frontend SPA**: Angular 18.2+, TypeScript 5.5, Tailwind CSS 3.4 (Standalone Components, Signals).
- **Backend API**: Python 3.10+, FastAPI, Pydantic v2, SQLAlchemy 2.0 con psycopg2 (síncrono).
- **Base de Datos Relacional**: PostgreSQL 16, codificación UTF-8. Docker Compose: puerto local 5433, contenedor 5432, base por defecto `apt_erp`.
- **Identidad**: decorativa por ahora — JWT local HS256 con `SECRET_KEY` (config en `backend/app/core/config.py`). Clerk (SDK frontend + validación JWT backend) queda como objetivo de Release 2.0, aún no implementado.
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
    │   └── security.py        # Lógica de JWT local (hashing y tokens)
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
    │   ├── auth_service.py    # Valida contraseñas simuladas y emite JWT (stub, Feature 006)
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
        │   ├── interceptors/  # Interceptores HTTP (token.interceptor.ts para inyectar JWT)
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
- **Escalabilidad directa a Release 2.0**: Cuando integren Clerk, solo tendrán que modificar `core/security.py` en backend y `core/guards/` en Angular. No tendrán que tocar ni un solo archivo de la lógica de Tickets o Inventario.