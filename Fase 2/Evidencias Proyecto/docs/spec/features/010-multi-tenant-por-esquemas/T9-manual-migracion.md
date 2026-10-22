# T9 — Manual operativo de la migración multi-tenant

> **Script:** `database/migraciones/001_migracion_multitenant_esquemas.sql`
> **Alcance:** migrar una base `apt_erp` **existente** (las doce tablas canónicas
> 3NF en el esquema `public`, con las columnas/claves de la Feature 008) al estado
> multi-tenant de la Feature 010. No aplica a instalaciones limpias (de eso se
> encarga `01_esquema.sql` + `02_datos_semilla.sql`, T10).

## 0. Por qué vive aquí y no en el montaje de initdb

`database/migraciones/` es un **subdirectorio** de `database/`, y el entrypoint de
la imagen PostgreSQL **no desciende a subdirectorios** (verificado en
`T8a-hallazgos-docker-initdb.md` §2). Por eso el script **nunca** se ejecuta solo:
ni en la instalación limpia, ni en un reinicio, ni al recrear el volumen. Se
invoca **explícitamente**. Tampoco renombra ni reordena `98_`/`99_`.

## 1. Garantías

- **No destructivo.** No ejecuta la semilla (`02_datos_semilla.sql`), no trunca,
  no borra el volumen y **no toca el esquema legado `public`**: sus tablas y filas
  quedan intactas como respaldo de recuperación.
- **Atómico.** Preflight y trabajo viven en un único `DO`. Si cualquier
  comprobación, copia o verificación falla, el bloque **revierte por completo** y
  la base queda **sin cambios**.
- **Idempotente.** Una segunda ejecución detecta los tenants ya en la versión
  objetivo y no vuelve a copiar ni altera datos operativos.
- **Fail-closed.** Una fila sin institución inequívoca, un identificador de
  institución vacío, una colisión de nombre de esquema o un esquema tenant
  preexistente sin versión objetivo **abortan antes de mutar**.
- **Sin dependencias nuevas:** usa `sha256()` y `normalize(..., NFKD)` de núcleo
  de PostgreSQL (≥ 13).

## 2. Estado final

- **`control`**: las doce tablas canónicas; registro de instituciones (`institucion`,
  todas), catálogo `rol` (todas), identidad Superadmin (`departamento` + `usuario`),
  y `mapa_usuario_esquema` con una fila por **cada** usuario local (Superadmin →
  esquema reservado `control`; el resto → su `tenant_…`). Las tablas de negocio de
  `control` quedan vacías.
- **Un esquema `tenant_<slug>_<hash>` por institución**: las doce tablas canónicas,
  la fila `institucion` **espejo**, `rol` (sin Superadmin), `prioridad` y
  `estado_ticket` replicados con **IDs preservados**, las filas de la institución
  particionadas por relación, y `version_esquema = '010.1'` escrita **al final**.

El nombre de esquema se deriva con la regla de `tenant_service.nombre_esquema_para_institucion`
y se verifica contra ella en los tests gated (`…::test_nombre_esquema_sql_reproduce_exactamente_python`).

## 3. Procedimiento

1. **Respaldo completo** de la base (`pg_dump`) y ventana de mantenimiento.
2. Confirmar que no hay otra migración en curso.
3. Ejecutar con `ON_ERROR_STOP=1`:

   ```
   psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" `
        -v ON_ERROR_STOP=1 -f database/migraciones/001_migracion_multitenant_esquemas.sql
   ```

   La salida normal termina con:
   `NOTICE: 010: migracion completada. Esquema legacy public intacto; control y tenants en version 010.1.`

## 4. Verificación posterior (consultas de control)

```sql
-- Todos los usuarios locales tienen mapa activo.
SELECT count(*) FROM control.mapa_usuario_esquema WHERE NOT activo;   -- 0

-- Por cada tenant (nombre derivado del ID): una única fila de versión objetivo.
SELECT version FROM "<tenant>".version_esquema;                        -- 010.1
```

## 5. Recuperación

- **Aborto antes de mutar** (fila ambigua, colisión, identificador vacío): corregir
  el dato en `public` y reintentar. Nada quedó a medio hacer.
- **Esquema tenant preexistente sin versión objetivo** (estado parcial de una
  ejecución interrumpida por el sistema operativo, no por el script —que es
  atómico—): la migración **aborta nombrando el esquema**. No hay limpieza
  automática de objetos no reconocidos. Procedimiento: respaldar ese esquema,
  verificar su contenido/propiedad e **eliminarlo de forma explícita** antes de
  reejecutar, o completarlo y escribir la versión objetivo de forma manual.
- **Fallo entre fases**: no existe (bloque único atómico). Si el proceso muere a
  mitad, PostgreSQL revierte; la base queda como estaba.
- **Reejecución**: segura por diseño; omite tenants ya en versión objetivo.

## 6. Qué **no** hace

- No limpia ni renombra `public` (paso operacional posterior y explícito).
- No habilita el corte de routing: la aplicación sigue resolviendo contra su
  configuración actual hasta T11.
- No crea ni valida identidades en Clerk.
- No ejecuta la semilla destructiva ni reinicia el volumen.
