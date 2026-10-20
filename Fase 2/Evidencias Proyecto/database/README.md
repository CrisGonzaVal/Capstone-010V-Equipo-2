# database/

Dos scripts, en este orden alfabético y funcional:

| Script | Qué hace |
|---|---|
| `01_esquema.sql` | Crea `control` (20 tablas) y un esquema `tenant_<slug>_<hash>` por institución (17 tablas de negocio cada uno). Siembra la topología: las 4 instituciones de QA (las capacidades funcionales las llena `02_`). |
| `02_datos_semilla.sql` | Llena la semilla QA, la reparte a los tenants, replica catálogos, consolida `stock_sede`, puebla el mapa `correo -> esquema`, fija la versión `013.1` y deja `control` como contexto global. Corre en una transacción con guardia fail-closed. |

El prefijo numérico es funcional: `docker-compose.yml` monta esta carpeta en
`/docker-entrypoint-initdb.d` y PostgreSQL ejecuta los `.sql` en orden
alfabético, con `ON_ERROR_STOP=1`, **solo al crear el volumen**.

## Reset

No hay migraciones ni semilla reejecutable: la guardia de `02_` aborta si la
base ya tiene filas de negocio. Para volver a una base limpia (el entorno es de
QA, sin datos reales):

```bash
docker compose -f docker-compose.yml down -v
docker compose -f docker-compose.yml up -d
```

En Windows: `reset-db.cmd` o `reset-db.ps1` desde la raíz del proyecto.

## Agregar una institución a la topología

1. Agrega la fila en la sección `TOPOLOGIA DE TENANTS` de `01_esquema.sql`
   (inserta en `control.institucion`).
2. Agrega sus datos en `02_datos_semilla.sql` (sedes, departamentos, usuarios,
   catálogo, stock, tickets).
3. Recrea el volumen.

Los esquemas tenant se derivan de esa lista con la misma regla que
`app/services/tenant_service.nombre_esquema_para_institucion`; no hay nombres de
esquema hardcodeados.

## Verificación rápida tras un reset

```sql
SELECT count(*) FROM control.institucion;              -- 4
SELECT count(*) FROM control.mapa_usuario_esquema;     -- 12
SELECT version FROM control.version_esquema;           -- 013.1
SELECT table_schema, count(*) FROM information_schema.tables
WHERE table_schema LIKE 'tenant_%' AND table_type = 'BASE TABLE'
GROUP BY table_schema;                                 -- 17 por tenant
```
