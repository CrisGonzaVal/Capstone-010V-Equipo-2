# T8a — Hallazgos: orden y guardia de scripts Docker antes de editar DDL/seed

> **Tipo:** inspección y evidencia. Esta tarea **no** modifica `docker-compose.yml`, `database/`
> ni código; solo documenta hallazgos verificados y propone un mecanismo. Cualquier cambio de
> `database/` corresponde a T10/T9.
>
> **Método de verificación:** ensayo en bases PostgreSQL **temporales**
> (`postgres:16-alpine`, contenedores `compustock_db_t8a`/`t8b`, volúmenes temporales, puerto
> 5544) montando la carpeta `database/` del proyecto en `/docker-entrypoint-initdb.d`. La base
> real `compustock_db` (`apt_erp` en 5433) **no se tocó**.

## 1. Montaje real de `./database`

`docker-compose.yml` línea 19:

```yaml
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database:/docker-entrypoint-initdb.d
```

- `./database` es relativo al directorio del `docker-compose.yml` (raíz del proyecto), por lo
  que **cae plano** en `/docker-entrypoint-initdb.d`. No hay subcarpeta intermedia: los cuatro
  `.sql` de `database/` quedan directamente en el directorio de inicialización.
- Por lo tanto, **todo** `.sql` que se agregue a `database/` entra al glob de initdb y se
  ejecuta en la instalación limpia. Es el hecho central que condiciona T9/T10.

## 2. Orden de ejecución (alfabético) y momento de `initdb`

La documentación oficial de la imagen (docker-library `postgres`, sección *Initialization
scripts*) establece:

> "These initialization files will be executed in sorted name order as defined by the current
> locale, which defaults to `en_US.utf8`."

Y que el entrypoint **llama primero a `initdb`** para crear el usuario/base por defecto y
**después** ejecuta los `*.sql` de `/docker-entrypoint-initdb.d`.

Verificado en el ensayo (contenedor temporal `t8a`), orden observado:

```
/docker-entrypoint-initdb.d/01_esquema.sql
/docker-entrypoint-initdb.d/02_datos_semilla.sql
/docker-entrypoint-initdb.d/98_migracion_particionamiento_institucional.sql
/docker-entrypoint-initdb.d/99_migracion_retiro_password.sql
```

Coincide con el orden alfabético esperado y con lo declarado en las cabeceras de los scripts.
`initdb` corre **antes** de `01_esquema.sql` y **solo** en ese arranque inicial.

**No recursivo (verificado):** el entrypoint globa **solo** los archivos del primer nivel. En el
ensayo `t8b` se montó `01_top.sql` + `sub/02_sub.sql`; únicamente se creó `top_level_marker`, la
tabla de `sub/02_sub.sql` **no** se ejecutó. Un subdirectorio dentro de `database/` (p. ej.
`database/migraciones/`) queda, por tanto, **fuera** del glob de initdb.

## 3. Cuándo corre `initdb` (y por qué la migración no puede depender de él)

Documentación oficial de la imagen:

> "**Warning**: scripts in `/docker-entrypoint-initdb.d` are only run if you start the container
> with a data directory that is empty; any pre-existing database will be left untouched on
> container startup."

Evidencia empírica (contenedor `t8a`, un arranque + un `docker restart`):

- Conteo de ejecuciones de `01_esquema.sql` a lo largo de toda la vida del contenedor: **1**.
- Tras el reinicio, el log solo muestra `database system is ready to accept connections` y **no**
  vuelve a ejecutar ningún script de initdb.
- Una tabla `public.marcador_t8a` creada tras el initdb **persistió** al reinicio.

Consecuencia: **la migración de la base real no puede depender del initdb**, porque una base
existente (con volumen ya creado) nunca vuelve a ejecutar los scripts montados. Cualquier
transformación de una base con datos tiene que ejecutarse de forma **explícita** con `psql` y
`ON_ERROR_STOP=1`.

## 4. Efecto del `TRUNCATE` de `02_datos_semilla.sql`

La sentencia (líneas 87–90) nombra doce tablas **sin prefijo de esquema**:

```sql
TRUNCATE TABLE detalle_ticket, movimiento_inventario, ticket, inventario,
    producto, categoria, usuario, rol, departamento, prioridad,
    estado_ticket, institucion
RESTART IDENTITY CASCADE;
```

Los nombres sin prefijo se resuelven por `search_path` (por defecto `"$user", public`), así que
apuntan a las tablas de `public` (donde hoy crea las doce tablas `01_esquema.sql`). Pero el
`CASCADE` **sigue las FK**: cualquier tabla que referencie a una de las nombradas también se
trunca.

**Hallazgo crítico, confirmado en el ensayo `t8a`:** `control.mapa_usuario_esquema` declara
`FOREIGN KEY (institucion_id) REFERENCES institucion (institucion_id)`
(`database/01_esquema.sql`, líneas 310–329). Como `institucion` está entre las tablas del
`TRUNCATE`, el `CASCADE` **alcanza el esquema de control**:

```
psql:.../02_datos_semilla.sql:90: NOTICE:  truncate cascades to table "mapa_usuario_esquema"
```

Prueba con filas: se insertó un marcador en `control.mapa_usuario_esquema`
(`marcador.t8a@test`), se ejecutó la semilla completa y el conteo pasó de `1` a `0`. **La semilla
borra el mapa `correo → esquema` del esquema de control**, aunque no nombre ninguna tabla de
`control`. Ejecutada sobre una base real, destruiría la resolución de identidad de todas las
instituciones.

**Alcance sobre tenants:** los esquemas tenant no comparten nombre con las tablas nombradas y,
por diseño aprobado, **no hay FK cross-schema** (stack.md §274, punto 2). Por tanto el
`TRUNCATE` **hoy no alcanza** los esquemas tenant: un tenant existente sobrevive a una
ejecución manual de la semilla. El único punto de fuga actual es `control.mapa_usuario_esquema`,
y proviene del estado transitorio en que las doce tablas canónicas aún viven en `public`
(T4 dejó la reubicación de las tablas dentro de `control` explícitamente para T10; ver
`01_esquema.sql` líneas 303–306).

> Nota de coherencia: una vez que T10 mueva las doce tablas canónicas a `control` y cree el
> espejo `institucion` local por tenant, la FK de `mapa_usuario_esquema` deberá apuntar al
> `institucion` **de control**, y el `TRUNCATE` (que seguirá resolviendo por `search_path`) debe
> excluir `control` de forma deliberada. T8a solo constata el estado actual; no lo corrige.

## 5. Señal segura propuesta (instalación limpia / reset QA / base con datos)

Requisito duro: los `*.sql` montados se ejecutan **sin parámetros** (el entrypoint llama a
`psql` sin `-v`). No es fiable depender de una variable de sustitución de `psql` en la ruta de
initdb: siempre vendría vacía. La señal debe vivir **en la base**, no en la línea de comandos.

**Señal propuesta: guardia "fail-closed por vaciedad" al inicio de `02_datos_semilla.sql`,
antes del primer `TRUNCATE`.** La semilla solo trunca si la base está **genuinamente vacía**;
ante cualquier fila de negocio, mapeo de control o marca de versión, **aborta** con
`RAISE EXCEPTION` (que bajo `ON_ERROR_STOP=1` detiene el arranque) e identifica el conteo.

Criterio de la guardia (suma de filas de las doce tablas canónicas +
`control.mapa_usuario_esquema` + `version_esquema`; si `> 0` → abortar):

- **Instalación limpia (initdb sobre volumen vacío):** `01_esquema.sql` acaba de crear las tablas
  vacías → suma `0` → la semilla procede. La guardia no estorba el arranque normal.
- **Base con datos (real o QA ya sembrada):** suma `> 0` → aborta **antes** del primer
  `TRUNCATE`. Falla cerrado: no puede confundir datos reales con entorno descartable.
- **Reset QA de una base existente:** requiere un **modo QA explícito**, que **no** puede venir
  del initdb. Al estar el modo fuera de la ruta automática, un reset solo ocurre por comando
  deliberado del operador (o recreando el volumen, que es inherentemente seguro).

Ensayo del prototipo de guardia en el contenedor temporal:

| Escenario | Resultado observado | Código de salida |
|---|---|---|
| Base limpia (`qa_vacia`, solo `01_esquema.sql`) | `NOTICE: Semilla QA: base limpia, se permite continuar (0 filas).` | `0` (procede) |
| Base con datos (`apt_erp` sembrada) | `ERROR: Semilla QA abortada: la base ya contiene 107 filas de negocio/control/version.` | `3` (aborta) |

Por qué es "no manipulable": la condición es una propiedad de la base calculada en servidor; no
la aporta el cliente, el correo, ni un parámetro, y ante duda se cierra (aborta). Esto satisface
el requisito del plan ("el DDL debe establecer una señal segura y no manipulable de instalación
limpia o la semilla destructiva debe salir del initdb automático").

**Precio de la señal:** cambia el contrato de la semilla documentada hoy. La cabecera actual de
`02_datos_semilla.sql` (líneas 36–39) promete que la semilla "es idempotente: se puede correr
las veces que quieras para resetear el entorno de QA". Con la guardia por vaciedad, una
re-ejecución sobre una base ya sembrada **abortaría** salvo que se pase el modo QA explícito.
Es un cambio de flujo que debe decidir el usuario (ver §7).

## 6. Ubicación de la migración (T9)

Dado que initdb **solo** corre en volumen vacío (§3) y que su glob **no es recursivo** (§2):

- **La migración no puede vivir en el primer nivel de `database/`:** todo `.sql` allí se
  ejecutaría en la instalación limpia (lo que la tarea prohíbe).
- **Opción confirmada por evidencia: subdirectorio de `database/`** (p. ej.
  `database/migraciones/`). Verificado en `t8b` que initdb **no** desciende a subdirectorios, por
  lo que un script allí queda fuera del montaje automático y se invoca de forma explícita con
  `psql -v ON_ERROR_STOP=1` (mismo patrón que hoy documentan `98_`/`99_` para aplicación manual).
- **Alternativa:** una ruta operacional **fuera** de `database/` (fuera del montaje). Es más
  robusta frente a la no-recursividad, que es un detalle de implementación del entrypoint, pero
  rompe la convención "scripts SQL en `database/`".

Recomendación: **`database/migraciones/`** (subdirectorio), por conservar la convención de
ubicación y quedar comprobadamente fuera del glob de initdb; sin renombrar ni reordenar `98_`/
`99_`. La elección final de ruta y nombre queda para T9 tras aprobación.

## 7. Decisiones que requieren al usuario (no resueltas aquí)

1. **¿La semilla destructiva permanece en el montaje automático de initdb?**
   - Puede permanecer **solo** con la guardia por vaciedad de §5 (segura en instalación limpia).
     Sin guardia, es insegura: el ensayo demuestra que destruye `control.mapa_usuario_esquema`
     por `CASCADE` y, sobre una base con datos, truncaría todo.
   - **Decisión pedida:** confirmar que se añade la guardia (T10) y aceptar el cambio de flujo
     del reset QA, **o** retirar la semilla del montaje automático y moverla a ejecución
     explícita. La tarea prohíbe que T8a resuelva esto por su cuenta.
2. **Modo QA explícito:** definir la forma concreta (¿comando wrapper que fija el modo?,
   ¿recrear volumen?, ¿script separado fuera del montaje?) para el reset autorizado de una base
   QA existente, ya que el initdb no puede pasar parámetros.
3. **Estado transitorio `public` vs `control`:** confirmar que la reubicación de las doce tablas
   canónicas dentro de `control` y el espejo `institucion` por tenant se abordan en T10 (T4 las
   dejó pendientes), y que la FK de `mapa_usuario_esquema` se reorientará a `control` en esa
   tarea. Hoy la FK apunta a `public.institucion`; es el origen del `CASCADE` de §4.

## 8. Resolución (implementada en T10)

Las decisiones de §7 quedaron resueltas por el usuario e implementadas en T10:

1. **La semilla destructiva permanece en el montaje de initdb, con guardia fail-closed.**
   `02_datos_semilla.sql` abre con una guardia (§0a) que aborta antes del primer `TRUNCATE`
   si la suma de filas de las doce tablas canónicas más `mapa_usuario_esquema` más
   `version_esquema` es `> 0` (mismo criterio del §5).
2. **El reset de QA de una base existente se hace recreando el volumen**
   (`docker compose -f docker-compose.yml down -v` y luego `up -d db`). No hay script de
   reset: la guardia convierte la reejecución de la semilla sobre una base con datos en un
   aborto deliberado. Documentado en la cabecera de `02_datos_semilla.sql`.
3. **Las doce tablas canónicas se reubicaron en `control`** en `01_esquema.sql` (prefijo
   `control.`) y la FK de `mapa_usuario_esquema` se reorientó a `control.institucion`. Para
   que `02_`, `98_` y `99_` (sin renombrar ni reordenar) y la sesión de control sigan
   resolviendo a `control` con nombres sin prefijo, `01_esquema.sql` fija el `search_path`
   por defecto de la base en `control, public`. Con esto, la nota del §4 («el `TRUNCATE` debe
   excluir `control` de forma deliberada») queda superada: el `TRUNCATE` **sí** apunta a las
   tablas de `control` (que ahora alojan también los datos de QA) y la seguridad la da la
   guardia fail-closed, no la exclusión de esquema.

Verificación empírica en contenedor temporal `postgres:16-alpine` con `./database` montado:
instalación limpia `01→02→98→99` correcta; base ya sembrada aborta antes de truncar (exit 3).
Recuentos tras la tarea: `pytest` SQLite `591 passed, 19 skipped`; gated `POSTGRES_TEST_URL`
`610 passed, 0 skipped`; `ng test` `172 SUCCESS`.

## 9. Conclusión

- Montaje plano y orden alfabético confirmados; `initdb` corre **solo** en volumen vacío
  (documentación + evidencia de reinicio).
- `TRUNCATE ... CASCADE` de la semilla **alcanza `control.mapa_usuario_esquema`** (baremo:
  FK a `institucion`); hoy **no** alcanza tenants (sin FK cross-schema).
- Mecanismo seguro propuesto: guardia **fail-closed por vaciedad** (§5), verificada en base
  temporal; obliga a un modo QA explícito para reset de base existente.
- Ubicación de la migración propuesta: **`database/migraciones/`** (subdirectorio no recorrido
  por initdb), invocada explícitamente (§6).
- Pendientes de decisión del usuario: §7.
