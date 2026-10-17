# CompuStock ERP

Sistema ERP SaaS multi-tenant para la gestión centralizada de insumos de ofimática.

## Estructura del Repositorio
- `database/`: Scripts SQL y modelos relacionales (PostgreSQL).
- `backend/`: API REST desarrollada con FastAPI.
- `frontend/`: Aplicación web desarrollada con Angular.

## Módulos Principales
1. **Administración y Roles**: Gestión de instituciones, departamentos, usuarios y control de permisos basados en roles.
2. **Inventario**: Catálogo de productos, stock por sede y registro automático de movimientos (entradas y salidas).
3. **Tickets y Dashboard**: Creación y seguimiento de solicitudes de insumos con tablero Kanban interactivo y alertas.

## Puesta en marcha

Requisitos: Docker y Docker Compose.

```bash
# 1. Crea tu .env a partir de la plantilla (no sube secretos)
cp env.example .env          # Windows: copy env.example .env

# 2. Completa las claves de Clerk en .env (CLERK_PUBLISHABLE_KEY,
#    CLERK_SECRET_KEY, CLERK_ISSUER). Sin ellas el frontend no inicia sesion.

# 3. Levanta el stack completo
docker compose -f docker-compose.yml up -d
```

En el **primer arranque con el volumen vacío**, PostgreSQL ejecuta automáticamente
(en orden alfabético) los scripts montados de `database/`:

| Script | Función |
|---|---|
| `01_esquema.sql` | Crea el DDL canónico en el esquema `control` (14 entidades de dominio + tablas auxiliares de control). |
| `02_datos_semilla.sql` | Siembra la base QA (4 instituciones, sedes, departamentos, usuarios, catálogo, stock, tickets). Guardia fail-closed: aborta si la base ya tiene datos. |
| `03_construir_tenants_011.sql` | **Construye la base multi-tenant completa**: crea los 4 esquemas `tenant_<institución>_<hash>`, reparte la semilla por institución, replica catálogos, consolida `stock_sede`, puebla `control.mapa_usuario_esquema` y deja control + tenants en `011.1`. |
| `98_`, `99_` | No-ops sobre una instalación nueva. |

Al terminar, la base queda lista **sin pasos manuales**: esquema `control` global
(identidad + mapa correo→esquema + versión) y un esquema `tenant_*` por institución
con sus datos. Reset del entorno de QA: recrear el volumen
(`docker compose -f docker-compose.yml down -v` y luego `up -d`), nunca reejecutar
la semilla.

Servicios tras `up -d`:

- Frontend (nginx): <http://localhost:8080>
- Backend (FastAPI): <http://localhost:8000> — documentación en `/docs` y contrato en `/openapi.json`
- PostgreSQL: `localhost:5433` (contenedor `compustock_db`)

> **`database/migraciones/` es SOLO para actualizar bases ya existentes.** Es un
> subdirectorio que el initdb **no** ejecuta. Los scripts `001_` y `002_` migran
> una base legada o pre-011 a la versión objetivo y se aplican de forma explícita
> con `psql -v ON_ERROR_STOP=1`. En una instalación nueva (`docker compose up -d`)
> no hay que ejecutarlos: `03_construir_tenants_011.sql` ya deja todo en `011.1`.

Antes de migrar una base existente, haz un respaldo con `pg_dump` y reserva una
ventana de mantenimiento. Las migraciones son atómicas e idempotentes, pero un
respaldo es prudente:

```bash
pg_dump "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" > respaldo_pre_migracion.sql
```

La secuencia depende del estado de la base:

- **Base legada pre-010** (las 12 tablas en `public`): ejecutar `001` y **después** `002`.
- **Base ya en `010.1`** (multi-tenant, sin sedes): ejecutar **solo** `002`.

En ambos casos, con `psql ... -v ON_ERROR_STOP=1`, en orden:

```bash
psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" -v ON_ERROR_STOP=1 -f database/migraciones/001_migracion_multitenant_esquemas.sql
psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" -v ON_ERROR_STOP=1 -f database/migraciones/002_migracion_modelo_organizacional_011.sql
```

Tras migrar, verifica la versión: debe haber una fila con `version = '011.1'` en
la tabla `version_esquema` de `control` y de cada esquema tenant.

```sql
SELECT version FROM control.version_esquema;          -- 011.1
SELECT version FROM "<tenant>".version_esquema;       -- 011.1
```

El procedimiento completo —garantías, pasos detallados y recuperación si la `001`
falla— está en `docs/spec/features/010-multi-tenant-por-esquemas/T9-manual-migracion.md`.
