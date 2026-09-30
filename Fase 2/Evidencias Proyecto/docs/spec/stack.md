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
├── database/
│   └── script_apt_erp.sql     # Script de inicialización 3NF para PostgreSQL
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
        │   └── interfaces/    # Tipos TypeScript que reflejan los schemas del backend
        │
        └── features/          # 🚀 Dominios de Negocio (Smart Components)
            ├── dashboard/
            │   ├── dashboard.component.ts
            │   └── dashboard.routes.ts
            │
            ├── inventario/
            │   ├── services/               # inventario.service.ts (+ URL_API)
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

**Nota 2 — `shared/components/` y `shared/pipes/` están planificados pero vacíos.** Los diagramas los preveen; la Feature 001 no los creó porque ningún componente actual tendría un consumidor real, y un componente sin uso es código muerto. Se crean en la feature que agregue la vista que los necesita.

**Nota 3 — sin subcarpeta `components/` en las features.** Los componentes viven en la raíz de su feature. `plan.md` de la Feature 001 los situaba en `features/*/components/`; prevalece este documento.

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

## 5. ¿Por qué esta estructura es la correcta para tu Capstone?

- **Pasa la revisión de cualquier arquitecto de software**: Sigue el principio de Responsabilidad Única (SOLID).
- **Cero dolores de cabeza con OpenCode / IA**: Al tener los servicios separados de las rutas (backend) y las features separadas del core (frontend), el agente de IA sabe exactamente qué archivo modificar sin romper el resto de la aplicación.
- **Escalabilidad directa a Release 2.0**: Cuando integren Clerk, solo tendrán que modificar `core/security.py` en backend y `core/guards/` en Angular. No tendrán que tocar ni un solo archivo de la lógica de Tickets o Inventario.