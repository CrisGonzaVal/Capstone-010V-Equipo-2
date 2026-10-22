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
(en orden alfabético) los dos scripts montados de `database/`:

| Script | Función |
|---|---|
| `01_esquema.sql` | Crea el DDL completo: el esquema global `control` (20 tablas) y un esquema `tenant_<slug>_<hash>` por institución con las 17 tablas de negocio replicadas. Siembra la topología (4 instituciones). |
| `02_datos_semilla.sql` | Siembra la base QA y la reparte a los tenants: capacidades, sedes, departamentos, usuarios, catálogo, stock, movimientos, tickets y el mapa `correo -> esquema`. Corre en una transacción con guardia fail-closed. |

Al terminar, la base queda lista **sin pasos manuales**: esquema `control` como
contexto global (topología, capacidades, roles, estado `Anulado`, mapa y versión
`013.1`) y un esquema `tenant_*` por institución con sus datos.

Reset del entorno de QA: recrear el volumen, nunca reejecutar la semilla.

```bash
docker compose -f docker-compose.yml down -v
docker compose -f docker-compose.yml up -d
```

En Windows puedes usar los atajos `reset-db.cmd` (o `reset-db.ps1` en PowerShell)
desde la raíz del proyecto.

Servicios tras `up -d`:

- Frontend (nginx): <http://localhost:8080>
- Frontend (dev server, `cd frontend && npm start`): <http://localhost:4200>
- Backend (FastAPI): <http://localhost:8000> — documentación en `/docs` y contrato en `/openapi.json`
- PostgreSQL: `localhost:5433` (contenedor `compustock_db`)

> **No hay migraciones.** `database/` es intencionalmente de dos archivos: la base
> se reconstruye desde cero (entorno de QA sin datos reales), no se actualiza in
> situ. Ver `database/README.md` y `docs/spec/stack.md`.
