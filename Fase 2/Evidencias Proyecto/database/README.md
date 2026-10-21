# database/

Dos scripts, en este orden alfabético y funcional. Son los **únicos** scripts de
instalación vigentes: no hay migraciones ni cadena incremental.

| Script | Qué hace |
|---|---|
| `01_esquema.sql` | Crea `control` (22 tablas) y un esquema `tenant_<slug>_<hash>` por institución (19 tablas de negocio cada uno). Siembra la topología: las 4 instituciones de QA (las capacidades funcionales las llena `02_`). |
| `02_datos_semilla.sql` | Llena la semilla QA, la reparte a los tenants, replica catálogos, consolida `stock_sede`, puebla el mapa `correo -> esquema`, fija la versión `014.1` y deja `control` como contexto global. Corre en una transacción con guardia fail-closed. |

Estructura de la Feature 014: `producto.activo` y `categoria.activo` (booleanas,
`NOT NULL DEFAULT TRUE`) y las dos tablas de historial de transición del catálogo
—`historial_transicion_producto` e `historial_transicion_categoria`, entidades de
dominio 16.ª y 17.ª—, creadas tanto en `control` como en la plantilla tenant. La
semilla siembra todo el catálogo activo y **no** inventa transiciones: los dos
historiales quedan vacíos.

El prefijo numérico es funcional: `docker-compose.yml` monta esta carpeta en
`/docker-entrypoint-initdb.d` y PostgreSQL ejecuta los `.sql` en orden
alfabético, con `ON_ERROR_STOP=1`, **solo al crear el volumen**.

## Reset

No hay migraciones ni semilla reejecutable: la guardia de `02_` aborta si la
base ya tiene filas de negocio. El reset es **recrear el volumen**, no ejecutar
scripts sobre la base existente. Para volver a una base limpia (el entorno es de
QA, sin datos reales):

```bash
docker compose -f docker-compose.yml down -v
docker compose -f docker-compose.yml up -d
```

En Windows: `reset-db.cmd` o `reset-db.ps1` desde la raíz del proyecto.

Un cambio de esquema o de semilla se resuelve actualizando `01_`/`02_` y
recreando el volumen; no se crean scripts nuevos ni carpetas de migración.

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
SELECT version FROM control.version_esquema;           -- 014.1
SELECT count(*) FROM control.historial_transicion_producto;   -- 0
SELECT count(*) FROM control.historial_transicion_categoria;  -- 0
SELECT table_schema, count(*) FROM information_schema.tables
WHERE table_schema = 'control' AND table_type = 'BASE TABLE'
GROUP BY table_schema;                                 -- control: 22
SELECT table_schema, count(*) FROM information_schema.tables
WHERE table_schema LIKE 'tenant_%' AND table_type = 'BASE TABLE'
GROUP BY table_schema;                                 -- 19 por tenant
```

Cada tenant debe declarar la versión `014.1` en su `version_esquema`: el routing
exige igualdad exacta con `VERSION_ESQUEMA_OBJETIVO` (`backend/app/core/config.py`)
y una versión menor no se enruta.
