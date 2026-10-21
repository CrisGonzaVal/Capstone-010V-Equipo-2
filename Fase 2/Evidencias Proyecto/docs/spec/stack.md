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

> **Nota de vigencia — base consolidada (20/Oct/2026):** `database/` volvió a dos
> scripts puros. `01_esquema.sql` crea `control` (22 tablas) y un esquema
> `tenant_<slug>_<hash>` por institución (19 tablas de negocio) y siembra la
> topología; `02_datos_semilla.sql` llena la semilla QA, la reparte a los tenants,
> puebla `control.mapa_usuario_esquema` y fija la versión `014.1` con guardia
> fail-closed. **No hay migraciones**: se retiraron `03_construir_tenants_011.sql`,
> `98_`, `99_` y `database/migraciones/`. Los cambios de esquema se resuelven
> recreando el volumen (`docker compose down -v` + `up -d`), nunca actualizando in
> situ. Las menciones a migraciones, constructores de tenants y al «modelo de 12
> entidades» que aparecen más abajo son **históricas** de las features 008–013 y
> quedan superseded por esta nota.

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
├── database/                    # Dos scripts; initdb los corre en orden alfabético
│   ├── 01_esquema.sql           # control + un tenant por institución (DDL)
│   └── 02_datos_semilla.sql     # Semilla QA + reparto a tenants + mapa + versión
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

#### Variante: dashboard consolidado con secciones por rol (Feature 009)

`obtener_dashboard_analitico()` en `dashboard_service.py` reúne en **una sola lectura**
varios KPI (escalares), un listado derivado y una actividad acotada, con autorización por
operación y secciones desactivables por rol:

- **Una consulta por sección**, no una por métrica: los KPI escalares son `select(func.count())`
  / `func.coalesce(func.sum(...), 0)` (agregados en SQL) y las listas son una proyección con
  joins explícitos; así el número de consultas es constante y no hay N+1.
- **La autorización va en la operación** (matriz central), pero **qué sección de datos se
  ensambla lo decide el servicio**: un booleano de contrato (`actividad_disponible`) expresa
  la sección no disponible para un rol sin conceder ni ampliar permiso sobre otro endpoint
  (el Solicitante sigue con 403 en `/inventario/movimientos`).
- **La regla de negocio se reutiliza como predicado puro** (`es_stock_critico`) evaluado por
  **fila** de inventario, no sobre un agregado; el DTO expone `total_alertas == len(alertas)`.
- **Filas multi-institución con atribución institucional** (`institucion_id`/`nombre`) sin
  fundir homónimos; el agregado global de un escalar (Superadmin) es deliberadamente único.

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
  **⚠ Superado por la Feature 010:** la globalidad de `rol`, `prioridad` y `estado_ticket`
  (D-5) queda **invertida** —desde la Feature 010 se replican por esquema— y el aislamiento
  deja de ser particionamiento lógico sobre tablas compartidas para pasar a esquemas
  PostgreSQL separados. El particionamiento por institución de las nueve entidades restantes
  se conserva como **defensa en profundidad**. Ver
  §"Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)".

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

#### Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)

La Feature 008 particionó por institución **sobre tablas compartidas** con `institucion_id`
y claves compuestas. La Feature 010 mueve la frontera: cada institución pasa a un **esquema
PostgreSQL propio** dentro de la misma base `apt_erp`, y aparece un **esquema global de
control** que resuelve la identidad antes de abrir cualquier sesión de negocio. Esta sección
es la justificación que exige `AGENTS.md` §7 ("no alterar el modelo de 12 entidades 3NF sin
justificación aprobada en `stack.md`") y se redacta **antes** de tocar modelos, DDL o base,
conforme al prerrequisito de la Feature 010. La aprobación explícita de este cambio es la
que desbloquea las tareas T2…T10 de esa feature.

**Qué no cambia (modelo de dominio invariante)**

- Se conservan las **mismas doce entidades 3NF** del DDL canónico `database/01_esquema.sql`:
  mismas tablas, columnas, PK, claves únicas compuestas, FK, `CHECK`s y valores por defecto.
  Ninguna entidad de dominio se elimina, se fusiona ni se reasigna.
- Se conservan las **nulabilidades** acordadas: `usuario.departamento_id NOT NULL` y
  `departamento.institucion_id NOT NULL` siguen siendo `NOT NULL`. La identidad global del
  Superadmin no introduce excepciones de nulabilidad (ver más abajo).
- Se conserva `institucion_id` y las claves compuestas de la Feature 008 dentro de cada
  tenant como **defensa en profundidad** (D-3): el aislamiento de esquema es la primera
  frontera y las restricciones locales la segunda.

**1. Esquemas por institución y esquema de control**

- Cada institución habita un **esquema tenant** distinto dentro de una única base física
  `apt_erp`; se mantiene **una sola conexión y un solo pool** (D-1). No se crea una base,
  instancia ni pool por institución.
- El **esquema de control** es global y no es el tenant de ninguna institución concreta.
  Contiene el registro fuente de verdad de instituciones, la identidad/rol Superadmin, el
  mapa de resolución y las estructuras auxiliares de esta sección.
- **Por qué:** satisface el requisito de separación física por institución sin multiplicar
  bases ni pools, y fija un punto único y global donde resolver la identidad antes de
  cualquier operación de negocio.

**2. Institución espejo en cada esquema tenant**

- El DDL canónico tiene **seis FK locales hacia `institucion`**: `departamento`,
  `categoria`, `producto`, `inventario`, `ticket` y `detalle_ticket`. Para aplicar ese DDL
  **sin cambios** en cada esquema, cada tenant **replica una fila `institucion`** —la fila
  espejo— de la institución registrada en control.
- La **fuente de verdad** del registro institucional permanece en control (D-5): el espejo
  tenant es una copia local que satisface las FK del esquema, no la autoridad del ciclo de
  vida global. Los cambios del registro canónico se reflejan en el espejo correspondiente.
- **No hay FK cross-schema.** Se descarta declarar en los tenants una FK hacia la
  `institucion` de control: PostgreSQL no admite FK entre esquemas de forma portable/estable
  y, sobre todo, acoplaría cada esquema tenant al esquema de control, contradiciendo el
  aislamiento y la independencia de aprovisionamiento y migración de cada institución.
- **Por qué:** replicar la fila conserva el DDL canónico idéntico por esquema y sus seis FK
  locales, sin introducir referencias entre esquemas.

**3. Catálogos replicados por tenant (inversión de la norma de Feature 008)**

- **Norma anterior (Feature 008, D-5):** `rol`, `prioridad` y `estado_ticket` son catálogos
  **globales y compartidos** por todas las instituciones; `02_datos_semilla.sql` los siembra
  una sola vez sin `institucion_id`.
- **Norma desde la Feature 010:** esos tres catálogos se **replican en cada esquema tenant**
  con sus valores funcionales requeridos. El **`rol` del Superadmin vive en control**, junto
  a la identidad global.
- **Por qué la inversión:** con un esquema por institución, `usuario → rol`, y
  `ticket → prioridad` / `ticket → estado_ticket`, son relaciones que deben resolverse
  **localmente** dentro del esquema del tenant. Mantener un catálogo global obligaría a FK
  cross-schema (descartado en el punto 2) o a referencias colgantes. Replicar catálogos
  pequeños de cardinalidad fija es más simple, mantiene el DDL autocontenido por esquema y
  permite que cada institución evolucione sus valores sin afectar a las demás. El orden del
  flujo de `estado_ticket` sigue siendo parte del contrato (Feature 003, D-4).
- **Alcance de la inversión:** es exactamente esta; el resto de la norma de la Feature 008
  (columnas de pertenencia, claves compuestas, migración `98_`) se conserva.

**4. Mapa `correo → esquema` en control**

- Estructura persistente **nueva** `mapa_usuario_esquema` en el esquema de control. Es
  **auxiliar al modelo de dominio**: no es una de las doce entidades 3NF ni participa de sus
  relaciones; existe para la resolución previa a la sesión tenant.
- Propiedades: `correo` como **clave primaria** (una identidad local no apunta a más de un
  esquema; una fila por usuario), `institucion_id` con FK al registro de control,
  `nombre_esquema` generado/validado en servidor **sin** restricción de unicidad en la base, y
  `activo` (solo asociaciones activas resuelven). Cubre a **todos** los usuarios locales
  migrados, no solo al Superadmin.
- **Por qué el `nombre_esquema` no lleva unicidad de base.** El mapa tiene una fila **por
  usuario** (clave primaria `correo`). Todos los usuarios de una misma institución comparten
  el mismo esquema, así que `nombre_esquema` se repite legítimamente entre sus filas; una
  restricción `UNIQUE (nombre_esquema)` impediría mapear más de un usuario por institución y
  contradiría AC-10 (el mapa debe cubrir a **todos** los usuarios migrados — en la semilla
  real, los 7 usuarios de `INST-001`). La unicidad estaba pensada para sostener la invariante
  "dos instituciones no comparten esquema", pero esa invariante **no es una propiedad
  relacional del mapa** y por tanto no se puede imponer con una restricción en esta tabla.
- **Cómo se garantiza la invariante sin la restricción.** El nombre de esquema es
  **determinista a partir del ID canónico de institución** (`tenant_service.
  nombre_esquema_para_institucion`) y **nunca es input del cliente**: se genera y valida en
  servidor. Dos instituciones con IDs distintos producen nombres distintos (el sufijo estable
  del SHA-256 evita colisiones), y la operación de aprovisionamiento rechaza explícitamente la
  reutilización de un esquema ya tomado (`_reservar_control`/`_mapa_por_nombre_esquema`). La
  garantía es, por tanto, **por derivación en servidor**, no por una restricción de base que
  no puede sostenerse con un mapa por usuario.
- **Por qué:** el correo primario verificado de Clerk es la única entrada confiable del
  cliente; se necesita un punto global, fuera de los tenants, que traduzca correo a esquema
  antes de consultar datos de negocio. Mover la invariante de esquema a la clave de correo
  permite mapear a todos los usuarios sin renunciar a la separación entre instituciones.

**5. `version_esquema` por tenant**

- Estructura persistente **nueva** por cada esquema tenant, con **exactamente una fila
  vigente** (`version_id` PK, `version` texto no vacío, `actualizada_en` timestamp). Tampoco
  es una entidad de dominio: es una marca de control de versión del DDL.
- La versión objetivo es una constante de despliegue (`VERSION_ESQUEMA_OBJETIVO`, inicial
  `010.1`) compartida por el código que resuelve y el procedimiento de migración. La
  comparación es de igualdad exacta; diferente, ausente, duplicada, futura o ilegible
  **deniega cerrado** y el tenant no se enruta.
- **Por qué:** un valor de versión solo sirve como control de seguridad si **determina el
  comportamiento observable de enrutamiento**. Permite distinguir un tenant completo y
  compatible de uno parcial, y es el checkpoint de idempotencia de bootstrap, migración y
  aprovisionamiento.

**6. `schema_translate_map` como selección de esquema por ejecución**

- El esquema efectivo se selecciona con **`schema_translate_map` de SQLAlchemy**, aplicado al
  contexto/ejecución de cada sesión, con el nombre de esquema procedente **únicamente** del
  registro de control y validado contra una allowlist de nombres generados. El modelo usa un
  esquema lógico común traducido al esquema tenant; las operaciones de control usan un
  contexto de control separado. El `schema_translate_map` **no** se muta en el `Engine`
  compartido ni se comparte una `Session` entre solicitudes.
- **Alternativa descartada: `search_path`.** Cambiar `search_path` deja **estado mutable
  asociado a la conexión**; al devolverse la conexión al pool y reciclarse en otra petición,
  ese estado se **filtra** entre tenants. Limpiarlo en un `finally` puede fallar ante
  excepciones, rollback o desconexión. `schema_translate_map` mantiene la elección en la
  ejecución ORM/Core y evita que el estado de la conexión del pool sea autoridad de tenant.
- Al cerrar cada petición se cierra la `Session` y su transacción y la conexión vuelve al
  pool **sin ningún `SET search_path`** ni estado de tenant persistente.

**7. Identidad global del Superadmin en control, con las mismas tablas 3NF**

- El esquema de control contiene el **mismo modelo 3NF** que un tenant: una institución
  administrativa (p. ej. «CompuStock SaaS»), un departamento administrativo y sus filas
  `usuario` y `rol`; la identidad del Superadmin vive ahí.
- Se mantienen `usuario.departamento_id` y `departamento.institucion_id` como `NOT NULL`: la
  identidad global se representa con las **mismas relaciones 3NF**, sin crear entidades
  paralelas ni excepciones de nulabilidad.
- El `rol` del Superadmin reside en el `rol` de control y se consulta en control; **nunca se
  enruta como usuario tenant**.

**8. Convivencia con Docker, semilla destructiva y migración explícita**

- `database/01_esquema.sql` sigue siendo el **DDL canónico** de doce tablas, base para
  bootstrap/control y para construir cada tenant. `database/02_datos_semilla.sql` **conserva
  su carácter destructivo** (`TRUNCATE … RESTART IDENTITY`) únicamente como **semilla QA de
  instalación limpia o reset expresamente autorizado**; debe abortar antes del primer
  truncado si detecta datos, mapeos o versión que indiquen base existente.
- El montaje de `./database` en `/docker-entrypoint-initdb.d` **solo se ejecuta al crear un
  volumen vacío**; en un volumen existente initdb no vuelve a correr. Por eso la migración de
  la base real **no puede** depender del initdb.
- La **migración** de la base `apt_erp` existente es un **script operacional explícito**,
  ejecutado con `psql` y `ON_ERROR_STOP=1` sobre respaldo/ventana de mantenimiento, **fuera
  del montaje automático de initdb**, que **nunca ejecuta la semilla destructiva**. Es
  transaccional por fase, idempotente por comparación de versión y **no renombra ni reordena**
  `98_migracion_particionamiento_institucional.sql` ni `99_migracion_retiro_password.sql`.
- **Por qué:** separa tres situaciones que no comparten flujo —instalación limpia, volumen ya
  inicializado y migración en sitio— y garantiza que la semilla no pueda truncar datos
  operativos, mapeos o tenants aprovisionados.

**Estructuras auxiliares frente al modelo de dominio**

`mapa_usuario_esquema` y `version_esquema` son **estructuras auxiliares** de control y de
tenant respectivamente: viven fuera del modelo de 12 entidades 3NF y no alteran sus
relaciones ni nulabilidades. La aprobación de esta sección cubre su creación en DDL y en
modelos, conforme al prerrequisito de la Feature 010.

#### Evolución del modelo organizacional e inventario por sede (Feature 011)

La Feature 011 supera explícitamente la afirmación de la sección “Multi-tenant por esquemas
PostgreSQL (Feature 010)” que establece que se conservan las mismas doce entidades 3NF y que
ninguna entidad de dominio se elimina, fusiona o reasigna. La nueva granularidad operativa
del inventario es `(sede_id, producto_id)`: el stock por sede sustituye el saldo operativo
por departamento de `inventario`, y el total institucional se deriva exclusivamente como
suma de los saldos por sede. No se mantienen saldos operativos departamentales o
institucionales independientes.

El modelo de dominio pasa de doce a catorce entidades: se incorporan `sede` y `stock_sede`.
`departamento_encargado` es una tabla puente auxiliar de asociación, comparable a
`mapa_usuario_esquema`, y no se cuenta como entidad de dominio. Se agregan
`departamento.sede_id` y `usuario.sede_id` como referencias nullable con precondiciones
operativas; `ticket.sede_id` nullable conserva la instantánea de sede de tickets nuevos y
permite representar tickets legados; y `movimiento_inventario.stock_sede_id` nullable
identifica movimientos nuevos contra stock por sede. Las columnas y restricciones compuestas
locales deben impedir asociaciones incoherentes dentro del tenant, sin FK cross-schema.

**Nota histórica:** las menciones al «modelo de 12 entidades 3NF» que aparecen en las
justificaciones de las Features 008 y 010 (§2 de este documento) y en el comentario del árbol
de `database/` (§1) son **históricas**: describen el estado vigente hasta la Feature 010 y
quedan **superadas** por esta sección, que fija el modelo de dominio en **14 entidades** (más
`departamento_encargado` auxiliar). Se conservan sin reescribir por trazabilidad de las
justificaciones aprobadas.

Las filas legadas de `inventario` referenciadas por `movimiento_inventario.inventario_id` se
conservan sin modificación, al igual que sus claves y todos los movimientos históricos.
`inventario.ubicacion` queda como dato legado y no se traslada automáticamente a
`sede.direccion`. Los movimientos nuevos de negocio y consolidación referencian
`stock_sede_id`; para esos movimientos `inventario_id` queda nulo, mientras los movimientos
históricos conservan su `inventario_id`.

La migración crea sedes deterministas por tenant y asigna departamentos mediante
round-robin estable por `departamento_id`. Antes de cambiar cada tenant mide por producto la
suma de las filas departamentales; después exige que la suma de stock por sede sea
exactamente ese valor. Para cada `(sede, producto)`, el saldo inicial debe ser igual a la
suma de sus movimientos nuevos de consolidación `ENTRADA`. Cualquier discrepancia aborta sin
declarar éxito. La consolidación se audita con movimientos nuevos y nunca reescribe ni borra
movimientos históricos.

La unicidad operativa es una fila por `(sede_id, producto_id)`. `stock_minimo` y criticidad
se evalúan por sede. Los KPI de `GET /dashboard/` conservan las fórmulas y semántica de
Feature 009, aplicadas a la nueva granularidad por sede, sin consultar cifras departamentales
legadas. `GET /inventario/existencias` expone sede y saldo; los endpoints de consulta no leen
ni exponen las filas legadas de `inventario`.

La asignación departamento-sede y usuario Bodeguero-sede se almacena en referencias
nullable; la obligatoriedad es operativa, no `NOT NULL`: las operaciones que dependan de una
asignación faltante se rechazan. Cada ticket nuevo almacena en `ticket.sede_id` una
instantánea al crearse y el despacho usa esa sede aun si el departamento cambia luego.
Tickets y movimientos históricos no se redirigen. Un tenant recién aprovisionado recibe
automáticamente “Sede Central”; el CRUD administrativo de sedes permanece en Feature 012.

El token objetivo de DDL pasa a `011.1`. Bootstrap/aprovisionamiento, control y cada tenant
deben recibir estructura compatible; el routing compara igualdad exacta y deniega cerrado
ante versión diferente, ausente, incompleta o duplicada. La migración de instalaciones
existentes es explícita, transaccional/idempotente según sus checkpoints y no usa la semilla
destructiva.

**Por qué:** el inventario debe representar la bodega física compartida por los departamentos
de una sede y no puede seguir fingiendo una granularidad departamental que el dominio ya no
usa; al mismo tiempo, la auditoría histórica permanece íntegra y el saldo institucional sigue
siendo una derivación, no una segunda fuente de verdad. Esta es la justificación que exige
`AGENTS.md` §7 antes de tocar modelos, DDL o migraciones, y la aprobación de este apartado es
el prerrequisito de implementación de la Feature 011.

#### Gestión del ciclo de vida institucional y capacidades funcionales (Feature 012)

La Feature 012 agrega `control.institucion.activo` como estado de ciclo de vida del registro institucional canónico. La fila de control es la fuente de verdad; `mapa_usuario_esquema.activo` conserva exclusivamente el significado de asociación local correo-esquema y no se reutiliza para suspender una institución. La resolución de identidad consulta `control.institucion.activo` antes de comprobar versión o seleccionar el tenant: una institución inactiva no resuelve a su esquema y las operaciones de negocio de sus identidades locales deniegan con 401. Reactivar restaura el routing solo si el tenant ya cumple la versión objetivo. La desactivación no borra la institución, el tenant, sus mapas, datos ni historial.

La Feature 012 incorpora además `funcion_institucion`, estructura auxiliar únicamente en `control`, con una fila por pareja `(institucion_id, funcion)`, FK local a la institución, estado `habilitada` explícito y unicidad de la pareja. No es entidad de dominio, permiso de usuario, capacidad de rol ni catálogo configurable. El conjunto cerrado de identificadores es `catalogo`, `inventario`, `tickets`, `kanban`, `dashboard` y `gestion_organizacional`; no se crea una tabla de catálogo ni se infiere disponibilidad a partir de roles o datos existentes. Las capacidades deshabilitadas se aplican como gating backend 403 adicional a la matriz central, que permanece como autoridad independiente de rol. La fila de capacidad no concede permisos ni elimina información al deshabilitar.

En instalaciones nuevas, `database/01_esquema.sql`, `database/02_datos_semilla.sql` cuando corresponda y `database/03_construir_tenants_011.sql` (o su constructor vigente) deben crear el atributo/auxiliar solo en control y aprovisionar para cada institución las seis capacidades inicialmente habilitadas. En instalaciones existentes, una migración operacional idempotente bajo `database/migraciones/` añade `activo` con valor inicial compatible, crea las seis filas habilitadas por institución y eleva la versión de control/tenants conforme al procedimiento aprobado, sin semilla destructiva ni pérdida de datos. El espejo tenant de `institucion` permanece limitado a `institucion_id` y `nombre`; `activo` y `funcion_institucion` nunca se copian al tenant.

**Por qué:** el estado canónico permite suspender y reactivar una institución en el punto global que precede al routing, sin confundir institución con asociación individual. La tabla auxiliar hace persistente y auditable la disponibilidad de las seis funciones por tenant, separándola de autorización por rol y del modelo de negocio. Ambos cambios se justifican como ampliación del esquema de control y estructuras auxiliares, no como nuevas entidades de dominio tenant; deben existir en el DDL, modelo, aprovisionamiento, migración y routing antes de habilitar su uso.

La Feature 012 agrega además un estado lógico `activo` a las tablas tenant `sede` y `departamento` (`BOOLEAN NOT NULL DEFAULT TRUE`), porque los criterios aprobados exigen mostrar y alternar el estado activo/inactivo de sedes y departamentos (AC-6/AC-11) y hoy ninguna de esas entidades porta un estado. Marcar `activo = FALSE` es una **desactivación lógica reversible**: la fila, sus claves, sus dependencias y su historial permanecen intactos y la reactivación consiste en reponer el valor, nunca en recrear el registro. El estado del **usuario local** se mantiene en `mapa_usuario_esquema.activo` (la asociación local correo-esquema) y **no** recibe una columna nueva en `usuario`. El DDL de instalación nueva, el constructor de tenants y el modelo ORM materializan `sede.activo` y `departamento.activo`; una instalación existente los recibe por la migración operacional de la 012 con valor inicial compatible y sin pérdida de datos.

**Por qué:** `sede` y `departamento` son entidades tenant cuya vigencia operativa es un atributo propio del dominio organizacional, no una propiedad del esquema de control; añadirlo como estado lógico evita el borrado físico, conserva la trazabilidad histórica ya exigida por el proyecto y mantiene el ciclo de vida institucional (control) diferenciado del ciclo de vida de cada entidad organizacional. No se introduce entidad nueva de dominio —`activo` es una columna de tablas existentes— y el repliegue de una desactivación no depende de reconstruir datos, sino de reponer el estado, por lo que la operación es reversible y auditable.

#### Ciclo de vida del ticket: estado `Anulado` e historial de transiciones (Feature 013)

La Feature 013 añade a cada catálogo `estado_ticket` replicado por tenant (sección «Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)», punto 3 de este §2) una quinta fila canónica, `Anulado`, alcanzable **solo** por anulación (dueño Solicitante o Administrador de la institución) o rechazo (Bodeguero o Administrador), ambos con motivo obligatorio. `Cerrado` y `Anulado` pasan a ser los dos estados terminales, reconocidos por su **nombre canónico** y no por su posición ordinal: el cambio de estado del flujo lineal no puede llevar **a** `Anulado` ni salir **de** él; `Anulado` queda fuera de la secuencia lineal de la Feature 004 y un ticket nacido en ese estado se rechaza en el alta. El estado es de **presencia obligatoria en toda instalación**: la semilla de instalación nueva lo siembra, el constructor de tenants lo replica en cada esquema y una migración operacional idempotente bajo `database/migraciones/` lo añade a las bases existentes junto con el resto de cambios de esta sección, elevando el token de versión de control y de cada tenant a `013.1` (mismo procedimiento de las 011/012). El catálogo permanece sin CRUD, como el resto de estados.

La Feature 013 crea además `historial_transicion_ticket`, una tabla de historial **por esquema tenant** (y, por paridad estructural del DDL canónico, también en el esquema de control, que conserva sus tablas de ticket vacías como el resto del modelo 3NF): una fila por transición del ciclo de vida, con `historial_transicion_id` (PK), `ticket_id` (FK local a `ticket`), `estado_origen_id` (FK a `estado_ticket`, **nulo solo en la fila de creación**), `estado_destino_id` (FK a `estado_ticket`), `usuario_id` (FK a `usuario`, el actor), `fecha_transicion` (marca de tiempo) y `motivo` (`VARCHAR(500)` nullable — la escala de la descripción del ticket; la anulación y el rechazo lo exigen no vacío). Es **inmutable y de solo lectura por API**: no existe operación pública de creación, edición ni borrado fuera de las transiciones mismas, y cada fila se escribe en **la misma transacción** que el cambio de estado que representa (`constitucion.md` §3). No lleva columna `institucion_id`: su aislamiento es el de su esquema tenant, con la misma defensa que `movimiento_inventario` (anclado por su ticket, que ya porta la institución), sin duplicar un ancla que la composición local ya garantiza.

**El historial es la 15.ª entidad de dominio, no una estructura auxiliar.** El modelo pasa de **14 a 15 entidades de dominio** (más `departamento_encargado`, que sigue siendo el único puente auxiliar). El criterio que lo separa de las auxiliares es el mismo con que la 011 contó `movimiento_inventario` como entidad: el historial **es un hecho de negocio** (quién movió un ticket, cuándo, de qué estado a qué estado y por qué), sostiene la Trazabilidad Absoluta del `constitucion.md` §2 sobre el ciclo de vida del ticket, participa en relaciones reales (FK a `ticket`, `usuario` y `estado_ticket`) y es **visible para el usuario** a través de una operación pública de la API. Las auxiliares existentes no cumplen ninguno de esos rasgos: `departamento_encargado` es un puente de asociación sin atributos propios, `mapa_usuario_esquema` y `version_esquema` son infraestructura de enrutamiento y control de versión invisibles al negocio, y `funcion_institucion` es una bandera de disponibilidad. Clasificarla como auxiliar obligaría a justificar por qué una tabla de negocio consultable por API queda fuera del modelo de dominio, y a explicar el doble rasero con `movimiento_inventario`.

**Por qué no se sella `fecha_cierre` en la anulación (D-5 de la 013):** `fecha_cierre` conserva su significado vigente de la 004/005 —cierre por despacho, estado `Cerrado`— y sellarla en una anulación haría que "fecha de cierre" signifique dos cosas distintas (entregado vs. cancelado), rompería la regla "todo ticket en `Cerrado` tiene fecha" y deformaría cualquier lectura derivada de esa columna. Un ticket anulado queda con `fecha_cierre` **nula**; la fecha exacta de su anulación vive en la fila del historial (actor, instante y motivo), que desde esta feature es la fuente de verdad del ciclo de vida completo. Tampoco se agrega una segunda columna de fecha al ticket: sería redundante con el historial, que ya registra el instante de cada transición, y crear dos columnas de cierre con semánticas rivales replicaría exactamente la ambigüedad que se evita al no sellar la vigente.

**Por qué el token de versión sube a `013.1`:** la comparación de enrutamiento es de igualdad exacta contra `VERSION_ESQUEMA_OBJETIVO` (punto 5 de la sección de la Feature 010 en este §2) y su propósito es deniegar en cerrado a un tenant cuyo DDL no coincide con el que el código espera. La 013 cambia el DDL de cada tenant de dos formas observables —una fila nueva en `estado_ticket` y una tabla nueva `historial_transicion_ticket`—: un tenant que quedara en `012.1` rechazaría anulaciones (catálogo sin `Anulado`) o fallaría al registrar transiciones (tabla ausente), que es exactamente el desajuste que el control de versión existe para impedir. Por eso el objetivo sube de `012.1` a `013.1` en la constante de despliegue, en el constructor y en la migración operacional, con la misma verificación fail-closed (una sola fila vigente por esquema; diferente, ausente, duplicada o ilegible deniega cerrado).

**Compatibilidad y migración:** el DDL de instalación nueva (`database/01_esquema.sql` y el constructor de tenants vigente) crea `historial_transicion_ticket` y siembra `Anulado`; las bases existentes reciben ambos por una migración operacional explícita e idempotente bajo `database/migraciones/` (token `013.1`), transaccional, sin semilla destructiva y sin pérdida de datos. Las transiciones ocurridas antes de esta feature **no se migran ni reconstruyen**: la 005 declaró que no persiste autoría y fabricar filas inventaría trazabilidad; las instalaciones existentes quedan con el historial de cada ticket vacío o desde su primera transición posterior. La suite SQLite funciona pero no acredita replicación por esquema ni el token de versión; esas semánticas se verifican contra PostgreSQL 16 en los tests gated.

**Por qué:** el negocio necesita responder "¿quién movió este ticket, cuándo y por qué?" y hoy solo existe el estado actual; un único estado terminal `Anulado` con motivo en el historial absorbe anulación y rechazo sin partir el vocabulario del tablero, y el historial inmutable cumple la Trazabilidad Absoluta sin deformar `fecha_cierre` ni la auditoría de inventario (la anulación no mueve stock). Esta es la justificación que exige `AGENTS.md` §7 antes de tocar modelos, DDL, semilla, constructor o migraciones, y la aprobación de este apartado es el prerrequisito de implementación de la Feature 013. La aprobación eleva el conteo de `AGENTS.md` §7 a **15 entidades de dominio**; actualizar esa cifra y `MEMORY.md` corresponde al cierre de la feature (grep de coherencia, `AGENTS.md` §8.7).

#### Proyección del ciclo de invitaciones y evidencia administrativa (Feature 017)

La Feature 017 amplía `control.mapa_usuario_esquema` con `estado_invitacion`, `invitacion_id`, `invitacion_expira_en` e `invitacion_aceptada_en`. `estado_invitacion` admite `pendiente`, `aceptada`, `revocada` y `expirada`; este último se deriva únicamente de `invitacion_expira_en`. `invitacion_id` identifica la invitación en Clerk. La aceptación se registra mediante una escritura condicional en el primer login con correo primario verificado y asociación local activa. El estado de invitación es una proyección persistida: los listados no consultan Clerk, no exponen URLs y presentan los estados legados o desconocidos como `no disponible`. El indicador `mapa_usuario_esquema.activo` conserva por separado el estado de la asociación local.

La Feature 017 incorpora además `control.registro_motivo_constancia`, una estructura auxiliar de control para evidencia recuperable de mutaciones administrativas y fallos de compensación. Registra actor, usuario objetivo cuando exista, institución, acción, código y texto del motivo cuando corresponda, fecha/hora e identificador idempotente. Admite constancias de compensación de invitación fallida y de fallo al persistir un motivo; la constancia de invitación fallida conserva `invitacion_id`, el instante y el resultado del intento de revocación, nunca la URL. La estructura no tiene endpoint lector en la Feature 017. Se conserva para su posible lectura en una futura feature de bitácora de motivos, aún sin numerar, que definirá la política de retención antes de exponerla.

Estas dos estructuras viven **solo en `control`**: sus columnas y tabla no se copian a los esquemas tenant ni modifican las relaciones o nulabilidades del modelo canónico. Son estructuras auxiliares de gobierno y resolución, no entidades de dominio. Por tanto, la Feature 017 no altera las **15 entidades de dominio** ni `departamento_encargado`, que continúa siendo una tabla auxiliar de asociación.

La instalación limpia debe materializar ambos cambios mediante `database/01_esquema.sql` y `database/02_datos_semilla.sql`, y las pruebas gated de esquema e instalación limpia deben verificar su estructura en control y su ausencia en los tenants. Conforme a AGENTS.md §8.8, la base se reconstruye recreando el volumen; no se crean migraciones.

**Por qué:** el estado persistido de invitación evita consultas vivas a Clerk en listados y permite marcar la aceptación a partir de un login verificado. El registro auxiliar conserva evidencia e idempotencia para cambios que abarcan confirmaciones tenant y control sin una transacción distribuida, y permite localizar invitaciones huérfanas sin almacenar enlaces. Ambas estructuras apoyan el gobierno y el enrutamiento SaaS, pero no describen hechos del dominio de inventario, tickets u organización; mantenerlas en control evita añadir tablas o atributos de identidad a cada tenant y preserva intacto el modelo canónico.

#### Ciclo de vida del catálogo: estados reversibles e historiales (Feature 014)

La Feature 014 incorpora el atributo lógico `activo` a las entidades tenant `producto` y `categoria`. Ambos nacen activos en instalaciones limpias y las transiciones activo/inactivo son reversibles. La desactivación no elimina las entidades ni altera stock, movimientos o detalles de tickets; el catálogo operativo omite productos inactivos y productos cuya categoría está inactiva. El estado de categoría solo puede pasar a inactivo sin productos activos vinculados; un producto solo se puede desactivar con saldo cero en `stock_sede` (la tabla `inventario` es legado congelado y no participa en esa regla). La creación vigente de producto en categoría inactiva se rechaza y un producto activo no puede quedar bajo categoría inactiva.

La feature crea dos tablas de historial de negocio tenant, una para transiciones de producto y otra para transiciones de categoría. Cada fila referencia directamente el recurso de su tipo, el actor persistido, instante, estado anterior/nuevo y motivo libre obligatorio de hasta 500 caracteres. Cada escritura de estado y su fila de historial se confirman o revierten juntas; la lectura es inmutable y exclusiva del Administrador Institucional de su tenant. Por paridad estructural del DDL canónico, las dos tablas existen también en `control`, que no recibe registros operativos de estas transiciones.

**Son la 16.ª y 17.ª entidades de dominio** (historial de producto e historial de categoría), no auxiliares: cada una registra hechos de negocio con actor, tiempo, estados y motivo, mantiene relación verificable con el recurso correspondiente y se consulta por API. Separarlas evita una referencia polimórfica a dos tablas distintas que no podría verificarse con una FK ordinaria. El modelo canónico pasa de 15 a 17 entidades de dominio (más `departamento_encargado`, auxiliar). El DDL pasa de 20 a **22 tablas en control** y de 17 a **19 tablas por tenant**; la semilla de instalación limpia inicializa productos/categorías como activos y la versión objetivo sube de `013.1` a **`014.1`**. La aprobación de esta justificación precede a cambios de modelos y DDL conforme a AGENTS.md §7.

**Por qué:** el estado explícito evita que artículos retirados permanezcan disponibles para nuevas solicitudes, mientras que los dos historiales preservan quién cambió la disponibilidad, cuándo y por qué sin romper referencias ni la auditoría de stock. La paridad de esquema garantiza que cada tenant enrutado puede ejecutar las operaciones con estructura compatible.

#### Filtros organizacionales de existencias y lectura de ámbito (Feature 018)

La Feature 018 **no altera el modelo de datos, el DDL ni la versión de esquema**: sigue en **17 entidades de dominio** (más `departamento_encargado` auxiliar), 22 tablas en `control`, 19 por tenant y token **`014.1`**. Es una ampliación **aditiva de contrato**, no de entidades.

Sobre la matriz central de autorización (`backend/app/core/permisos.py`) se añade **una sola** operación: `GET /api/v1/inventario/ambito` → `{Administrador, Bodeguero}`. La cardinalidad pasa de **60 a 61 operaciones**; las 60 previas conservan exactamente sus roles y ninguna se retira. La operación nueva se ata a la capacidad institucional ya existente **`inventario`** en `backend/app/core/capacidades.py`, de modo que una institución con `inventario` apagada recibe **403** en la lectura de ámbito, además del gating preexistente de `GET /inventario/existencias`. El conjunto cerrado de seis capacidades de la Feature 012 no cambia.

El contrato de `GET /api/v1/inventario/existencias` se amplía con el parámetro de consulta opcional **`sede_id`** (`int | None`), combinable con el `departamento_id` vigente. `sede_id` se incorpora al predicado de `stock_sede` **antes del `outerjoin`** y, cuando hay filtro organizacional, exige `stock_sede_id.is_not(None)`, degradando el `outerjoin` a `INNER` efectivo. No se hace un `db.get(Sede, sede_id)` previo: un identificador ausente del esquema del actor —incluido el de otro tenant— es un filtro de lista que responde **200 con `[]`**. Esto **no** contradice el **404** de `GET /inventario/stock?sede_id=…` (Feature 011 AC-3): allí se consulta un recurso individual, aquí se filtra una lista.

La semántica del filtro departamental de la 011 se **conserva**: `departamento_id` selecciona la sede del departamento y el `outerjoin` restringido omite los productos sin fila de stock en esa sede; varios departamentos de una sede común producen el mismo saldo físico. Nunca se crea ni expone saldo departamental: `stock_sede` sigue siendo la única fuente de saldo operativo.

La operación de ámbito responde exclusivamente opciones de filtro: sedes activas (`sede_id`, `sede_nombre`) y departamentos activos **con sede asignada** (`departamento_id`, `departamento_nombre`, `sede_id`). No incluye usuarios, tickets, productos, stock ni agregados. Para el Administrador cubre su institución; para el Bodeguero, su sede asignada y los departamentos de ella, o **409** si no tiene sede. El frontend decide la visibilidad de los selectores con el helper `puedeVerFiltrosInventario` en `frontend/src/app/core/auth/roles.ts` (solo presentación; la API sigue siendo la frontera de seguridad).

**Por qué:** el Administrador necesita acotar la lectura a una sede y el Bodeguero confirmar la ubicación física de su departamento sin requerir una granularidad que el dominio no posee, y el Bodeguero no tiene acceso a las lecturas organizacionales de `/organizacion/*`; una operación mínima con los mismos roles de negocio y la capacidad `inventario` aporta las opciones sin abrir datos de administración. Reutilizar `inventario` mantiene el catálogo cerrado de capacidades, y el parámetro de filtro dentro de `condicion_stock` preserva el aislamiento por esquema sin un lookup que revelaría la existencia de una sede ajena.

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
