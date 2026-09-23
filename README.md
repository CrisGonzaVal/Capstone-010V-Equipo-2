# CompuStock ERP

Sistema ERP SaaS multi-tenant para la gestión centralizada de insumos de ofimática.

## Estructura del Repositorio
- `database/`: Scripts SQL y modelos relacionales (PostgreSQL).
- `backend/`: API REST desarrollada con FastAPI.
- `frontend/`: Aplicación web desarrollada con Angular.

## Módulos Principales
1. **Administración y Roles**: Gestión de instituciones, departamentos, usuarios y control de permisos basados en roles.
2. **Inventario**: Catálogo de productos, stock por departamento y registro automático de movimientos (entradas y salidas).
3. **Tickets y Dashboard**: Creación y seguimiento de solicitudes de insumos con tablero Kanban interactivo y alertas.
