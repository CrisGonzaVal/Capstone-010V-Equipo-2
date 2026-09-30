# Feature 002: Catálogo de Insumos Clasificado y Consulta de Existencias

**Estado:** Implementada y verificada (26 AC con evidencia). Pendiente solo el recorrido
visual manual de la vista, que no es automatizable: ver `tasks.md` → *Cierre*.
**Release:** 1.0 — Sprint 1
**Tipo:** Valor de negocio (primera lectura end-to-end del catálogo y el stock)

## 1. Problema

El backend ya expone el catálogo y el stock, pero la vista de inventario no lo usa bien.
Tres huecos concretos, verificados en el código:

- `frontend/src/app/features/inventario/inventario.component.html` muestra
  **datos hardcodeados en su diseño pero no en su contenido**: el `<input>` de
  "Buscar insumos..." no tiene binding (no filtra nada), la columna de categoría
  no existe, y el departamento se descarta (solo se recibe `departamento_id` y
  nunca se muestra). El botón "+ Nuevo Producto" y el botón por fila
  "Registrar Movimiento" no tienen `(click)`: son controles muertos.
- **La consulta no es clasificada**: `listar_productos` y `listar_inventario`
  hacen `db.query(...).all()` sin orden, sin filtros y sin `selectinload`, así
  que el orden es indefinido y cada fila dispara un lazy-load de `producto` (N+1).
- **No se puede ver la disponibilidad con el nombre del lugar.** `InventarioRespuesta`
  expone `departamento_id` y `ubicacion`, pero no el nombre del departamento. Resolverlo
  en el frontend obligaría a cruzar ids contra `/usuarios/departamentos`, que vive en
  `features/administracion/` — y `AC-10` de la Feature 001 prohíbe que una feature
  importe otra.

Resultado: el Actor **Solicitante** no puede responder "¿hay papel? ¿cuánto? ¿dónde?"
sin salir del sistema, que es exactamente el primer caso de uso de `constitucion.md:13`.

## 2. Objetivo

Entregar la consulta de existencias del catálogo, clasificada por categoría y con
el nombre de la sede, de punta a punta: un endpoint de lectura que el backend arma
explícitamente, y una vista que de verdad filtra en lugar de fingir que filtra.

## 3. Alcance

### Dentro

- **Backend — endpoint nuevo** `GET /api/v1/inventario/existencias`: un elemento por
  producto del catálogo, con su categoría, su stock total, su estado crítico y el
  desglose de existencias por sede (§5).
- **Backend — filtros y orden** en ese endpoint: `q`, `categoria_id`,
  `departamento_id`, `solo_criticos`. Orden determinista.
- **Backend — calidad de los listados existentes**: `listar_categorias`,
  `listar_productos` y `listar_inventario` pasan a declarar orden determinista;
  `listar_productos` deja de tener N+1 con `selectinload`. Los 3 GET declaran
  `status_code` y `response_model` explícitos, como exige `AGENTS.md` §6.
- **Backend — corrección de H-1 acotado**: `crear_producto` valida que la categoría
  exista y responde 404 en vez de 500.
- **Frontend — vista de inventario real**: input de búsqueda funcional, panel de
  categorías navegable con conteos, filtro de "solo stock crítico", columna/grupo de
  categoría, nombre del departamento y de la ubicación en cada insumo, estados de
  carga y vacío coherentes.
- **Frontend — tipos y servicio**: `ProductoExistencia` y `SedeExistencia` en
  `shared/interfaces/index.ts`; `obtenerExistencias()` en `InventarioService`.
- **Frontend — tests**: `inventario.component.spec.ts`, el primero del feature.
- **Documentación**: `roadmap.md` (índice), `stack.md` (patrón de read model), `MEMORY.md`.

### Fuera

- **Escrituras de catálogo.** No hay `POST`/`PUT`/`DELETE` de productos ni de
  categorías. El botón "+ Nuevo Producto" y el "Registrar Movimiento" **se eliminan
  del template** (D-6). El CRUD del catálogo maestro es del Actor Administrador
  Institucional y no está planificado en el roadmap: se anotará como pendiente.
- **`GET /inventario/movimientos`.** El historial existe en `movimiento_inventario`
  pero no se expone. Va con la Feature 005 (despacho y auditoría).
- **Filtro por sede en la UI.** La API sí acepta `departamento_id`; la vista no lo
  ofrece (D-3).
- **`crear_ticket` y su validación de stock.** Es Feature 003, junto con la corrección
  del 500 por FK inválida en tickets.
- **El dashboard.** `features/dashboard/` sigue con sus 4 KPI hardcodeados. Las
  cifras reales son de la Feature 009 (`roadmap.md:34`).
- **`shared/components/` y `shared/pipes/`.** Se mantienen sin crear: la barra de
  filtros y el panel de categorías son específicos de inventario, y un componente
  compartido sin segundo consumidor es código muerto (`stack.md` §3, Nota 2).
- **Modelo de datos.** `app/models/` y `database/01_esquema.sql` no se tocan.
- **`CheckConstraint` en el ORM.** El DDL tiene 3 CHECKs que los modelos no declaran
  (`producto_stock_minimo_ck`, `inventario_stock_ck`, `movimiento_cantidad_ck`).
  Es una divergencia real, pero tocar `app/models/` exige justificación en `stack.md`
  primero (`sdd-workflow`), así que se documenta para
  una feature de saneamiento, no aquí.
- **Nombres de categoría duplicados.** Los datos de QA tienen `Papeleria` (1) y
  `Papeleria Premium` (10). Son dos categorías distintas y la vista las muestra
  separadas. No se normalizan: `AGENTS.md` §7.

## 4. Decisiones de diseño

### D-1 — El filtro vive en el cliente, no en el servidor
La vista hace **una** consulta sin filtros y resuelve categoría, texto y crítico con
`computed()`. Los parámetros `q`, `categoria_id`, `departamento_id` y `solo_criticos`
se implementan y se prueban en el endpoint porque son parte del contrato público, pero
la vista no los envía todavía.

Por qué: una ida y vuelta por pulsación de tecla es peor UX que filtrar al instante;
los conteos por categoría que muestra el panel lateral solo son coherentes si el filtro
es local (con filtro de servidor, "Toner" marcaría 0 resultados y el usuario no
distinguiría "no tengo" de "no coincide"); y filtrar 2 criterios en cliente y 1 en
servidor sería incoherente. ** disparador para revertir:** cuando el catálogo supere
~500 filas por institución o entre multi-tenant, el filtro pasa al servidor con
paginación, y entonces el panel de categorías deja de calcular conteos localmente.

### D-2 — Un endpoint nuevo, `/stock` no se toca
`GET /inventario/stock` sigue exactamente igual. Se agrega
`GET /inventario/existencias` con un read model desnormalizado. Beneficios: el contrato
congelado por `AC-2` de la Feature 001 queda intacto, los 25 casos de `backend/tests/`
siguen verdes sin reescribirlos, y la vista deja de tener que cruzar ids en cliente.

### D-3 — El nombre de la sede lo arma el backend
`SedeExistenciaRespuesta.departamento_nombre` viene del `JOIN` con `departamento`. Así la
vista no necesita `/usuarios/departamentos` y no se rompe `AC-10`. Por el mismo motivo la
vista **no** ofrece filtro por sede: hacerlo exigiría descubrir el catálogo de
departamentos desde `features/inventario/`, que es una decisión de capa que corresponde
a la Feature 009, donde el dashboard por sede la va a necesitar igual.

### D-4 — `LEFT JOIN` desde `producto`: el catálogo no pierde los productos sin stock
Un producto con filas en `inventario` es el caso normal; uno sin ninguna fila es un
insumo agotado, que es justo lo que el solicitante necesita ver. Con `INNER JOIN`
desaparecería de la respuesta. Se incluye con `sedes: []` y `stock_total: 0`.
Consecuencia: si se envía `departamento_id`, el filtro degrada a `INNER JOIN` (solo
interesan los productos con existencias en esa sede) y `stock_total` pasa a sumar solo
las sedes informadas. Se documenta en el OpenAPI de la ruta.

### D-5 — `es_critico` es un campo de la respuesta, no una función del frontend
La regla `stock_actual <= stock_minimo` hoy está duplicada en el componente
(`esStockCritico`, `inventario.component.ts`). Pasa a existir **una sola vez** en el
backend, en `es_stock_critico(stock_actual, stock_minimo)` de `inventario_service.py`,
que usan tanto el armado de la respuesta como el filtro `solo_criticos`. El color lo
pinta el campo `es_critico` que llega en el JSON. Se borra `esStockCritico`.

`es_critico` se evalúa a nivel de insumo (`stock_total <= stock_minimo`), que es la
granularidad de la fila de la tabla. `stock_minimo = 0` (valor por defecto del modelo)
hace que cualquier producto en cero se marque crítico: es el comportamiento correcto.

### D-6 — Se borran los dos controles muertos
"+ Nuevo Producto" y "Registrar Movimiento" no hacen nada. Un control que no hace nada
es peor que su ausencia: promete una capacidad que no existe y no hay formulario que
la cumpla. Se eliminan del template en vez de dejarlos deshabilitados con un tooltip.
El CRUD de catálogo y el registro de movimientos se entregan en sus features.

### D-7 — El read model se arma en el service, no con `from_attributes`
`ProductoExistenciaRespuesta` **no** usa `ConfigDict(from_attributes=True)`: cruza 4
tablas y agrega. El service ejecuta **una** consulta con `select()` y joins
(`Producto` LEFT JOIN `Categoria` LEFT JOIN `Inventario` LEFT JOIN `Departamento`),
agrupa las filas en Python y construye los DTO. Se agrupa en Python y no con `GROUP BY`
porque la fila es la unidad de información (una sede), y la agregación es de 3 líneas de
Python sobre una lista ya traída — en vez de un `GROUP BY` con `sum()` que la base
optimiza peor para este caso. Ventaja secundaria: el service controla el
`selectinload` implícito y no queda N+1.

### D-8 — H-1 se corrige solo en `crear_producto`
`crear_producto` hoy inserta a ciegas: si `categoria_id` no existe, la FK viola y la
petición muere con 500. Se valida la existencia de la categoría y se responde **404
"No existe la categoría indicada"**, siguiendo el precedente de
`registrar_movimiento`, que ya responde 404 cuando el `inventario_id` no existe. No se
agrega validación de nombre duplicado: el modelo no declara `UNIQUE` sobre
`producto.nombre` y una regla de negocio sin respaldo en el esquema es deuda
(Feature de CRUD).

El 500 por `producto_id` inexistente **en tickets** no se toca: es de la Feature 003 y su
test de regresión sigue esperando 500.

## 5. Contrato de la API

### `GET /api/v1/inventario/existencias`

`response_model=list[ProductoExistenciaRespuesta]` · `status_code=200` ·
resumen: "Consultar existencias del catálogo clasificadas por sede"

| Query | Tipo | Efecto |
|---|---|---|
| `q` | `str \| None` | Coincidencia sin distinguir mayúsculas sobre `producto.nombre` o `producto.descripcion` |
| `categoria_id` | `int \| None` | Solo productos de esa categoría |
| `departamento_id` | `int \| None` | Solo productos con existencias en esa sede; acota también `sedes` y `stock_total` (D-4) |
| `solo_criticos` | `bool = false` | Solo insumos con `stock_total <= stock_minimo` |

```python
class SedeExistenciaRespuesta(BaseModel):
    inventario_id: int
    departamento_id: int
    departamento_nombre: str
    stock_actual: int
    ubicacion: str | None

class ProductoExistenciaRespuesta(BaseModel):
    producto_id: int
    nombre: str
    descripcion: str | None
    unidad_medida: str | None
    stock_minimo: int
    categoria_id: int
    categoria_nombre: str
    stock_total: int
    es_critico: bool
    sedes: list[SedeExistenciaRespuesta]
```

La respuesta es una **lista desnuda**, igual que las otras 4 rutas de `/inventario`. No
lleva envoltorio con totales: el conteo lo calcula la vista y la paginación no está
prevista (D-1).

**Invariante de agrupación:** un `producto_id` aparece **exactamente una vez** en la
lista, aunque tenga existencias en N sedes. `stock_total` es la suma de `stock_actual`
de las sedes informadas.

**Orden:** `producto.nombre`, luego `producto.producto_id` como desempate; dentro de
`sedes`, por `departamento.nombre_dep`, luego `departamento_id`. Totalmente determinista.

**Ejemplo de elemento** (producto 1 de los datos de QA, `departamento_id` 7):

```json
{
  "producto_id": 1,
  "nombre": "Resma Carta 75g A4",
  "descripcion": "Resma de 500 hojas tamano carta",
  "unidad_medida": "RESMA",
  "stock_minimo": 20,
  "categoria_id": 1,
  "categoria_nombre": "Papeleria",
  "stock_total": 120,
  "es_critico": false,
  "sedes": [
    {
      "inventario_id": 1,
      "departamento_id": 7,
      "departamento_nombre": "Operaciones",
      "stock_actual": 120,
      "ubicacion": "Bodega Central - Estante A1"
    }
  ]
}
```

## 6. Criterios de aceptación

### Contrato y lógica de negocio

- [x] **AC-1** `GET /api/v1/inventario/existencias` responde 200 con la lista de productos
      del catálogo, y `/openapi.json` la declara con su `response_model`.
- [x] **AC-2** Cada elemento trae `categoria_nombre`, `stock_total`, `es_critico` y
      `sedes`, y cada sede trae `departamento_nombre` y `ubicacion`.
- [x] **AC-3** Un producto con existencias en 2 departamentos aparece **una sola vez**,
      con 2 entradas en `sedes` y `stock_total` igual a la suma (D-4, AC de agrupación).
- [x] **AC-4** Un producto **sin** filas en `inventario` aparece en la respuesta con
      `sedes: []` y `stock_total: 0`, y con `es_critico: true`.
- [x] **AC-5** `?q=resma` devuelve solo productos cuyo nombre o descripción coincida,
      ignorando mayúsculas; `?q=zzzz` devuelve `[]`.
- [x] **AC-6** `?categoria_id=<válida>` devuelve solo esa categoría;
      `?categoria_id=999999` devuelve `[]` (no 500, no 404).
- [x] **AC-7** `?departamento_id=<válida>` acota la lista y el contenido de `sedes` a esa
      sede, y `stock_total` deja de sumar las demás.
- [x] **AC-8** `?solo_criticos=true` devuelve únicamente insumos con
      `stock_total <= stock_minimo`, y **todos** los devueltos traen `es_critico: true`.
      Con los datos de QA son los productos 7, 9 y 10 (`02_datos_semilla.sql:151-153`; antes
      `datos_semilla.sql:138-140`).
- [x] **AC-9** `es_critico` y el filtro `solo_criticos` salen de la **misma** función
      `es_stock_critico()` en `app/services/inventario_service.py` (D-5).
- [x] **AC-10** El orden es determinista: repetir la llamada dos veces devuelve las listas
      en el mismo orden, y `sedes` viene ordenada por nombre de departamento.
- [x] **AC-11** `POST /api/v1/inventario/productos` con `categoria_id` inexistente responde
      **404** con mensaje, no 500 (D-8). Test de regresión nuevo.
- [x] **AC-12** `GET /categorias`, `GET /productos` y `GET /stock` devuelven **el mismo
      JSON** que antes: el único cambio es que el orden pasa de indefinido a determinista.
      Verificado con un test que fija el orden esperado.
- [x] **AC-13** Los 3 GET existentes declaran `status_code` y `response_model` explícitos
      (`AGENTS.md` §6).
- [x] **AC-14** `git diff` no muestra cambios en `backend/app/models/` ni en el DDL de
      `database/01_esquema.sql` (`AGENTS.md` §7, `AC-12` de la Feature 001). Ese archivo se
      renombró desde `script_apt_erp.sql` en esta feature para garantizar el orden de
      ejecución de los `.sql`; las 42 sentencias `CREATE TABLE`/`CONSTRAINT`/`REFERENCES`
      son idénticas a las del original.
- [x] **AC-15** `listar_productos` no tiene N+1: una consulta a `/productos` con N
      productos emite 1 consulta de productos + 1 de categorías, no N+1.
      Verificado contando con el event listener de SQLAlchemy.

### Frontend

- [x] **AC-16** El input "Buscar insumos..." filtra de verdad por nombre, categoría y
      descripción, combinándose con la categoría seleccionada y con "solo críticos".
- [x] **AC-17** La vista muestra el nombre de la categoría de cada insumo y el nombre del
      departamento y la ubicación de cada sede, sin que el componente consulte
      `/usuarios/departamentos` ni importe nada de `features/administracion/`
      (`AC-10` de la Feature 001).
- [x] **AC-18** El panel de categorías permite cambiar de categoría y muestra el conteo
      de insumos que coinciden con los filtros activos.
- [x] **AC-19** `esStockCritico` desaparece del componente; el estado crítico se pinta
      desde el campo `es_critico`. `grep -rn "esStockCritico" frontend/src` → 0.
- [x] **AC-20** No queda ningún control sin manejador: cada `(click)` del template
      corresponde a un método del componente, y el template no tiene `@NgModule`, `*ngIf`,
      `*ngFor` ni CSS quemado (`AGENTS.md` §6).
- [x] **AC-21** `shared/interfaces/index.ts` declara `ProductoExistencia` y
      `SedeExistencia` en `snake_case`, reflejando 1:1 los schemas nuevos.
- [x] **AC-22** Estados de carga, vacío con filtros activos y error de backend
      distinguishse entre sí; ante un fallo la lista queda vacía y el mensaje indica que
      se revise el servicio en el puerto 8000.

### Verificación

- [x] **AC-23** `cd backend && pytest` pasa: los **25 casos preexistentes siguen verdes**
      (sin reescribirlos) más los nuevos de `/existencias` y de H-1.
- [x] **AC-24** `cd frontend && npm test` pasa, incluido el nuevo
      `inventario.component.spec.ts` con cobertura de carga, filtro por texto, filtro
      por categoría, filtro de críticos y estado de error (los 4 tests de
      `app.component.spec.ts` siguen verdes).
- [x] **AC-25** `cd frontend && npm run build` compila sin errores y sin crecer el bundle
      inicial de forma relevante.
- [x] **AC-26** Coherencia documental: `roadmap.md` con la Feature 002 en el índice,
      `stack.md` con el patrón de read model (D-7) y la nota de `shared/components/`
      revisada, `MEMORY.md` actualizado, y `grep` de rutas `.md` rotas → 0.

### Evidencia de verificación de cada AC

La tabla nombra el test o el comando que comprueba cada AC. `pytest` =
`backend\.venv\Scripts\python.exe -m pytest`; `ng test` =
`npx ng test --watch=false --browsers=ChromeHeadless` (el `npm test` a secas se queda
esperando navegador: ver `AGENTS.md` §5).

| AC | Evidencia |
|---|---|
| AC-1 | `test_existencias_responde_200` y `test_openapi_declara_la_ruta_nueva_y_conserva_las_viejas` en verde. `/openapi.json` declara `ProductoExistenciaRespuesta` como `items.$ref` y conserva las 5 rutas previas de inventario |
| AC-2 | `test_existencia_expone_categoria_y_sedes`. Contra PostgreSQL real: el elemento de Boligrota trae `categoria_nombre: Escritura` y `departamento_nombre: Biblioteca` |
| AC-3 | `test_producto_multi_sede_aparece_una_sola_vez`: la resma sale 1 vez, con 2 sedes y `stock_total` 150 = 120 + 30 |
| AC-4 | `test_producto_sin_inventario_aparece_con_stock_cero`: `sedes: []`, `stock_total: 0`, `es_critico: true`. **Mutación**: cambiar el `outerjoin` de `Inventario` por `join` pone 5 tests en rojo |
| AC-5 | `test_busqueda_por_texto_ignora_mayusculas`. Contra PostgreSQL, `?q=RESMA` devuelve las 2 resmas y `?q=26A NEGRO` encuentra por descripción |
| AC-6 | `test_filtro_por_categoria`; `?categoria_id=999999` devuelve `[]` contra PostgreSQL, sin 500 |
| AC-7 | `test_filtro_por_departamento_acota_sedes_y_total`. Contra PostgreSQL, `?departamento_id=1` trae 1 producto con 1 sola sede |
| AC-8 | `test_filtro_solo_criticos`. Contra PostgreSQL devuelve exactamente los 3 de la semilla (Grapadora 1/5, Rotulador 6/12, Tóner Negro 3/10), todos con `es_critico: true` |
| AC-9 | `es_stock_critico()` se invoca en el armado de la respuesta **y** en el filtro `solo_criticos`, en el mismo archivo. **Mutación**: `<=` → `<` pone 2 tests en rojo |
| AC-10 | `test_orden_es_determinista` y `test_sedes_vienen_ordenadas_por_departamento` |
| AC-11 | `test_crear_producto_con_categoria_inexistente_responde_404` (404 con mensaje y sin crear el producto a medias) más `test_crear_producto_con_categoria_valida_sigue_creando` de regresión |
| AC-12 | `test_listados_existentes_conservan_su_json_con_orden_determinista` fija el conjunto de claves exacto de los 3 listados. Los 25 casos previos siguen verdes **sin reescribir ninguno** |
| AC-13 | Los 3 GET declaran `status_code=status.HTTP_200_OK` y `response_model`, visible en `app/api/v1/endpoints/inventario.py` |
| AC-14 | `git diff --stat -- backend/app/models database` → vacío |
| AC-15 | `test_listar_productos_evita_consultas_n_mas_uno`: 5 productos → 1 consulta a `producto` + 1 a `categoria`. **Mutación**: quitar el `selectinload` lo pone en rojo |
| AC-16 | `debe filtrar por texto` y `debe limpiar los filtros`. El texto compara nombre, descripción y categoría con `normalizar()` |
| AC-17 | `debe renderizar los insumos con su categoria y su sede`. `grep` de `features/administracion\|features/tickets\|features/dashboard` dentro de `features/inventario` → 0 |
| AC-18 | `debe filtrar por categoria sin inutilizar el panel`: los conteos salen de `insumosCoincidentes`, no de `insumosVisibles` |
| AC-19 | `grep -rn "esStockCritico" frontend/src` → 0 |
| AC-20 | `grep` de `@NgModule\|*ngIf\|*ngFor\|CommonModule` en `src/app` → 0; `grep` de `style=` en `features/inventario` → 0; los 3 `(click)` del template tienen método |
| AC-21 | `SedeExistencia` y `ProductoExistencia` en `shared/interfaces/index.ts`, en `snake_case`, 1:1 con los schemas |
| AC-22 | `debe distinguir el estado vacio del estado con filtros` y `debe mostrar un error si el backend no responde` |
| AC-23 | `pytest` → **43 en verde** (25 previos + 17 de `test_catalogo_consulta.py` + 1 de `test_smoke.py`) |
| AC-24 | `ng test` → **12 en verde** (4 previos + 8 nuevos) |
| AC-25 | `npm run build` compila. El chunk `inventario-component` quedó en 11.90 kB y sigue siendo lazy |
| AC-26 | `roadmap.md`, `stack.md` y `MEMORY.md` actualizados en esta feature; sin rutas `.md` rotas |

**Verificación adicional no exigida por los AC:** el endpoint se ejecutó contra
**PostgreSQL 16 real** (no solo SQLite), porque el riesgo principal de `plan.md` §10 es que
`ilike` se comporte distinto en el motor de producción. Los 4 filtros, el orden y la
forma de la respuesta se comportaron igual que en la suite.

**Único punto sin verificación automática:** el recorrido visual de la vista en el
navegador (que el panel salga en columna a 1366px y la tabla no se corte). Queda como
`[!]` en `tasks.md` y es un paso manual de 2 minutos.

## 7. Restricciones

- `constitucion.md:17` (Trazabilidad Absoluta): esta feature es **de solo lectura**, así
  que no toca `movimientos_inventario`. El `registrar_movimiento` existente y sus tests
  quedan intactos.
- `constitucion.md:18` (Consistencia Transaccional): no se abre ninguna transacción.
  `AC-12` y `AC-14` protegen el contrato y el esquema.
- `AGENTS.md` §6: identificadores en español en Python y TypeScript; nada de
  `class Config` (solo `model_config = ConfigDict(...)`); la `Session` entra por
  `Depends(get_db)`; sin SQL raw; la lógica de negocio vive en `app/services/`.
- `AGENTS.md` §7: sin paquetes nuevos. `pytest` ya está en `requirements-dev.txt`; el
  frontend usa `provideHttpClientTesting` de `@angular/common/http/testing`, que viene
  en `@angular/common`.
- La suite corre sobre **SQLite en memoria** con `PRAGMA foreign_keys=ON` y `create_all`.
  Ojo: los CHECKs del DDL **no** existen en SQLite, así que ningún test puede afirmar
  que `stock_minimo < 0` es rechazado por la base.
- Los tests se escriben por el **seam HTTP** (`TestClient`), nunca consultando la BD
  directamente, y sin ids fijos: se usan los ids que devuelve `datos_base`.
- Los tests de `/existencias` usan un **fixture propio** con más de una categoría y más
  de un departamento. `conftest.datos_base` no se modifica, para no tocar los 25 casos
  que dependen de su forma.
