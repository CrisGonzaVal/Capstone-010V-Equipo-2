# Feature 002: Plan de Implementación

**Estado:** Aprobado para ejecución (`tasks.md`)
**Spec:** [`spec.md`](spec.md) — manda sobre este documento ante cualquier conflicto.

## 1. Resumen técnico

Un endpoint nuevo (`GET /inventario/existencias`) arma en el service un read model
desnormalizado a partir de **una** consulta con `LEFT JOIN`, y la vista de inventario
deja de fingir: consume ese endpoint, filtra con `computed()` y pinta el nombre de la
sede. `/inventario/stock` no se toca. El modelo de datos no se toca.

## 2. Archivos tocados

| Archivo | Acción | Riesgo |
|---|---|---|
| `backend/app/schemas/inventario_schema.py` | + 2 schemas | Nulo (aditivo) |
| `backend/app/services/inventario_service.py` | + 3 funciones, 3 funciones ajustadas, H-1 | Bajo (`AC-12` lo cubre) |
| `backend/app/api/v1/endpoints/inventario.py` | + 1 ruta, `status_code` en 3 GET | Nulo |
| `backend/tests/api/test_catalogo_consulta.py` | **nuevo** | Nulo |
| `backend/tests/api/test_smoke.py` | + 1 caso en `CASOS_LECTURA` | Nulo |
| `frontend/src/app/shared/interfaces/index.ts` | + 2 interfaces | Nulo |
| `frontend/src/app/features/inventario/services/inventario.service.ts` | + 1 método | Nulo |
| `frontend/src/app/features/inventario/inventario.component.ts` | reescritura | Medio (es la vista) |
| `frontend/src/app/features/inventario/inventario.component.html` | reescritura | Medio |
| `frontend/src/app/features/inventario/inventario.component.spec.ts` | **nuevo** | Nulo |
| `docs/spec/stack.md`, `docs/spec/roadmap.md`, `MEMORY.md` | documentación | Nulo |

**No se tocan:** `backend/app/models/`, `backend/tests/conftest.py`, `database/*.sql`,
`app/api/v1/api.py`, `app/schemas/producto_schema.py`, `app/schemas/ticket_schema.py`,
`app/schemas/usuario_schema.py`, `app/services/ticket_service.py`, `app/services/usuario_service.py`,
cualquier archivo de `features/tickets/`, `features/dashboard/` o `features/administracion/`.

## 3. Fase A — Backend: el endpoint de existencias

### 3.1 Schemas (`app/schemas/inventario_schema.py`)

Se agregan al final del archivo. Van aquí y no en `producto_schema.py` porque el read
model es de **consulta de inventario**: `inventario_schema.py` ya importa de
`producto_schema.py`, así que la dirección de dependencia ya está establecida.

```python
class SedeExistenciaRespuesta(BaseModel):
    """Fila de `inventario` con el nombre del departamento resuelto (spec D-3)."""

    inventario_id: int
    departamento_id: int
    departamento_nombre: str
    stock_actual: int
    ubicacion: Optional[str] = None


class ProductoExistenciaRespuesta(BaseModel):
    """Read model de la consulta de existencias (spec §5).

    NO lleva `model_config = ConfigDict(from_attributes=True)`: el service lo arma
    a mano porque cruza 4 tablas y agrega (spec D-7). Con `from_attributes` Pydantic
    intentaria leer estos campos del objeto ORM y no encontraria `stock_total`,
    `es_critico` ni `sedes`.
    """

    producto_id: int
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int
    categoria_id: int
    categoria_nombre: str
    stock_total: int
    es_critico: bool
    sedes: List[SedeExistenciaRespuesta]
```

Se usa `List[...]` y `Optional[...]` de `typing`, no `list[...]`/`X | None`, para
mantener el estilo de los 4 schemas que ya existen en el archivo. `List` ya está
importado.

**Por qué `departamento_nombre: str` y no un `DepartamentoRespuesta` anidado:** el
modelo de datos necesita el nombre, no el resto del departamento. Un schema anidado
obligaría a duplicar `usuario_schema.py.Departamento` en el dominio de inventario y a
serializar `institucion_id` y `descripcion` que la vista no usa.

### 3.2 Service (`app/services/inventario_service.py`)

Imports nuevos: `from sqlalchemy import select` y
`from app.schemas.inventario_schema import MovimientoCrear, ProductoExistenciaRespuesta, SedeExistenciaRespuesta`.

Las funciones existentes conservan `db.query()`; la nueva usa `select()`. Migrar las
viejas a `select()` unifica estilo pero es churn sobre las rutas que `AC-12` exige no
tocar. Se deja para una feature de saneamiento.

#### 3.2.1 La regla única de stock crítico

```python
def es_stock_critico(stock_actual: int, stock_minimo: int) -> bool:
    """Regla unica de stock critico. `spec.md` D-5.

    La usan tanto el armado de la respuesta como el filtro `solo_criticos`, para
    que el badge que ve el usuario y el filtro que produjo su lista no puedan
    discrepar. El `<=` es a proposito: `stock_minimo = 0` (default del modelo)
    hace que un producto en cero se marque critico, que es lo correcto.
    """
    return stock_actual <= stock_minimo
```

#### 3.2.2 La consulta

```python
def listar_existencias(
    db: Session,
    q: Optional[str] = None,
    categoria_id: Optional[int] = None,
    departamento_id: Optional[int] = None,
    solo_criticos: bool = False,
) -> List[ProductoExistenciaRespuesta]:
    consulta = select(
        Producto.producto_id,
        Producto.nombre,
        Producto.descripcion,
        Producto.unidad_medida,
        Producto.stock_minimo,
        Categoria.categoria_id,
        Categoria.nombre_cat,
        Inventario.inventario_id,
        Inventario.stock_actual,
        Inventario.ubicacion,
        Departamento.departamento_id,
        Departamento.nombre_dep,
    ).join(
        Categoria, Producto.categoria_id == Categoria.categoria_id
    ).outerjoin(
        Inventario, Producto.producto_id == Inventario.producto_id
    ).outerjoin(
        Departamento, Inventario.departamento_id == Departamento.departamento_id
    )

    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(
            Producto.nombre.ilike(patron) | Producto.descripcion.ilike(patron)
        )
    if categoria_id is not None:
        consulta = consulta.where(Categoria.categoria_id == categoria_id)
    if departamento_id is not None:
        consulta = consulta.where(Inventario.departamento_id == departamento_id)

    consulta = consulta.order_by(
        Producto.nombre,
        Producto.producto_id,
        Departamento.nombre_dep,
        Departamento.departamento_id,
    )
    ...
```

**Cinco detalles que no son obvios:**

1. **`join`/`outerjoin` con onclause explícito, siempre.** Al seleccionar columnas sueltas
   (estilo Core) no hay entidad ORM en el `FROM` que permita a SQLAlchemy deducir el join
   por la FK. Sin el onclause, `select()` no sabe cómo unir y lanza error.
2. **`Categoria` con `join` interno, `Inventario` y `Departamento` con `outerjoin`.**
   `producto.categoria_id` es `NOT NULL` con FK (`01_esquema.sql`, tabla `producto`),
   así que el join interno a categoría no puede descartar filas. `inventario` sí es
   opcional: un producto sin existencias debe aparecer (spec D-4).
3. **`ilike` funciona en los dos motores.** En PostgreSQL compila a `ILIKE`; en SQLite
   (la base de la suite) SQLAlchemy lo traduce a `lower(x) LIKE lower(y)`. No hace falta
   `func.lower()` ni una variante por motor.
4. **`Producto.descripcion.ilike(...)` sobre `NULL` da `NULL`, no `error`.** En
   `nombre ILIKE %x% OR descripcion ILIKE %x%`, si `descripcion` es `NULL` y `nombre`
   coincide, el resultado es `true OR NULL = true`: la fila entra. Si no coincide `nombre`,
   el `NULL` la descarta. Es el comportamiento correcto y no requiere `coalesce`.
5. **`solo_criticos` NO va en el `WHERE`.** Es un predicado sobre el agregado
   (`stock_total`), que no existe hasta agrupar. Se aplica en Python después de
   agrupar. La base de datos hace el trabajo pesado (filtra por texto, categoría y sede);
   solo el agregado se resuelve en memoria, sobre un conjunto ya acotado.

#### 3.2.3 La agrupación

```python
    # Acumulador por producto. Las claves coinciden exactamente con los campos del
    # schema salvo `es_critico`, que se calcula al final: asi el DTO se arma con
    # `**acumulador` y no hay que ir completando un BaseModel mutable.
    acumuladores: dict[int, dict] = {}

    for fila in db.execute(consulta).all():
        if fila.producto_id not in acumuladores:
            acumuladores[fila.producto_id] = {
                "producto_id": fila.producto_id,
                "nombre": fila.nombre,
                "descripcion": fila.descripcion,
                "unidad_medida": fila.unidad_medida,
                "stock_minimo": fila.stock_minimo,
                "categoria_id": fila.categoria_id,
                "categoria_nombre": fila.nombre_cat,
                "stock_total": 0,
                "sedes": [],
            }
        acumulador = acumuladores[fila.producto_id]

        # `inventario_id` es NULL cuando el producto no tiene existencias (D-4).
        if fila.inventario_id is not None:
            acumulador["stock_total"] += fila.stock_actual
            acumulador["sedes"].append(
                SedeExistenciaRespuesta(
                    inventario_id=fila.inventario_id,
                    departamento_id=fila.departamento_id,
                    departamento_nombre=fila.nombre_dep,
                    stock_actual=fila.stock_actual,
                    ubicacion=fila.ubicacion,
                )
            )

    # `dict` conserva el orden de insercion (garantizado desde Python 3.7), asi que
    # el orden del `ORDER BY` se propaga solo: no hay que reordenar.
    existencias = [
        ProductoExistenciaRespuesta(
            **acumulador,
            es_critico=es_stock_critico(acumulador["stock_total"], acumulador["stock_minimo"]),
        )
        for acumulador in acumuladores.values()
    ]

    if solo_criticos:
        existencias = [existencia for existencia in existencias if existencia.es_critico]

    return existencias
```

`fila` es un `Row` de SQLAlchemy: se accede por atributo (`fila.nombre`), y todos los
nombres de columna del `select` son únicos, así que no hay colisiones.

### 3.3 Router (`app/api/v1/endpoints/inventario.py`)

Se inserta **entre `/stock` y `/movimientos`**, para que el archivo lea en el orden
"consulta de stock → consulta de existencias → escritura de movimiento".

```python
@router.get(
    "/existencias",
    response_model=List[ProductoExistenciaRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Consultar existencias del catalogo clasificadas por sede",
    description=(
        "Un elemento por producto del catalogo, con su categoria, su stock total, "
        "su estado critico y el desglose de existencias por sede. Un producto sin "
        "filas en `inventario` aparece con `sedes` vacio y `stock_total` en 0."
    ),
)
def listar_existencias(
    q: Optional[str] = None,
    categoria_id: Optional[int] = None,
    departamento_id: Optional[int] = None,
    solo_criticos: bool = False,
    db: Session = Depends(dependencies.get_db),
):
    return inventario_service.listar_existencias(
        db, q, categoria_id, departamento_id, solo_criticos
    )
```

Se usa `Optional[int] = None` explícito (a diferencia del `departamento_id: int = None`
implícito de `/stock`, que no se cambia por no ser parte de esta feature).

## 4. Fase B — Backend: las rutas que ya existían

### 4.1 Orden determinista

```python
def listar_categorias(db: Session) -> List[Categoria]:
    return db.query(Categoria).order_by(Categoria.nombre_cat).all()


def listar_productos(db: Session) -> List[Producto]:
    return (
        db.query(Producto)
        .options(selectinload(Producto.categoria))
        .order_by(Producto.nombre, Producto.producto_id)
        .all()
    )


def listar_inventario(db: Session, departamento_id: Optional[int] = None) -> List[Inventario]:
    consulta = db.query(Inventario)
    if departamento_id:
        consulta = consulta.filter(Inventario.departamento_id == departamento_id)
    return consulta.order_by(Inventario.inventario_id).all()
```

`listar_inventario` se ordena por `inventario_id` y no por nombre de producto: es la
ruta heredada, su consumidor ya no es la vista, y `inventario_id` es el orden estable
más barato (no exige el join extra que sí tiene sentido en la ruta nueva).

### 4.2 N+1 de `listar_productos`

`selectinload(Producto.categoria)` resuelve la carga diferida de la relación: N productos
pasan de N+1 consultas a 2 (una de productos + una de categorías, con `IN`). El
`response_model` sigue igual: `categoria` se sigue llenando.

Se importa `selectinload` desde `sqlalchemy.orm`.

### 4.3 H-1 acotado en `crear_producto`

```python
def crear_producto(db: Session, datos: ProductoCrear) -> Producto:
    categoria = db.get(Categoria, datos.categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="No existe la categoria indicada")

    nuevo_producto = Producto(**datos.model_dump())
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return nuevo_producto
```

`db.get()` consulta por clave primaria y además respeta el identity map, así que si la
categoría ya está cargada en la sesión no cuesta nada. El `404` con literal (y no
`status.HTTP_404_NOT_FOUND`) copia el estilo de los tres `HTTPException` que ya tiene
este archivo. Sin este chequeo, la FK viola en el `commit()` y FastAPI responde 500.

## 5. Fase C — Tests backend

Un archivo nuevo: `backend/tests/api/test_catalogo_consulta.py`. Cubre tanto la ruta
nueva como las mejoras de las rutas existentes, porque todas son "consulta de catálogo".
`conftest.py` **no se toca**.

### 5.1 El fixture `datos_catalogo`

Depende de `datos_base` y agrega filas encima, con su propia sesión sobre `motor`:

```python
@pytest.fixture
def datos_catalogo(motor, datos_base):
    """Catalogo con 2 categorias, 2 departamentos y casos borde.

    No reemplaza a `datos_base`: se apoya en ella para no romper los 25 casos que
    dependen de su forma exacta.
    """
```

Contenido (los ids se leen de `datos_base` y de lo que genera la propia sesión; **ningún
id fijo salvo `institucion_id="INST01"`, que es un `VARCHAR` y no una secuencia**):

| Insumo | Categoría | `stock_minimo` | Existencias | Para qué sirve |
|---|---|---|---|---|
| `Cuaderno linedado` (de `datos_base`) | Papeleria | 10 | Operaciones 50 | caso normal, y su descripción sirve para probar `q` |
| `Resma Carta 75g` | Papeleria | 20 | Operaciones 120 + Bodega 30 | **multi-sede**: 1 producto, 2 filas, `stock_total` 150 |
| `Toner HP 26A` | Toner y Cartuchos | 10 | Bodega 3 | crítico |
| `Grapadora Estandar` | Toner y Cartuchos | 5 | **ninguna** | `sedes: []`, `stock_total: 0`, crítico (D-4) |
| `Boligrota Bic Cristal` | Papeleria | 30 | Operaciones 30 | **frontera**: `30 <= 30` → crítico (D-5) |

Devuelve las claves: `categoria_papeleria`, `categoria_toner`, `producto_resma`,
`producto_toner`, `producto_grapadora`, `producto_boligrota`, `departamento_bodega`.

### 5.2 Matriz test → AC

| Test | AC | Qué afirma |
|---|---|---|
| `test_existencias_responde_200` | AC-1 | 200 y lista no vacía con el catálogo sembrado |
| `test_openapi_declara_la_ruta_nueva_y_conserva_las_viejas` | AC-1 | `/api/v1/inventario/existencias` existe en `paths`, su `items.$ref` termina en `ProductoExistenciaRespuesta`, y las 5 rutas previas de inventario siguen presentes |
| `test_existencia_expone_categoria_y_sedes` | AC-2 | Cada elemento tiene `categoria_nombre` no vacío y `sedes` con `departamento_nombre` |
| `test_producto_multi_sede_aparece_una_sola_vez` | AC-3 | El `producto_id` de la resma aparece 1 vez, con 2 sedes y `stock_total == 150` |
| `test_producto_sin_inventario_aparece_con_stock_cero` | AC-4 | La grapadora está en la lista, `sedes == []`, `stock_total == 0`, `es_critico is True` |
| `test_busqueda_por_texto_ignora_mayusculas` | AC-5 | `?q=RESMA` trae la resma y no el cuaderno; `?q=100 hojas` trae el cuaderno (match por descripción); `?q=zzzz` trae `[]` |
| `test_filtro_por_categoria` | AC-6 | `?categoria_id=<toner>` trae solo tóner y grapadora; `?categoria_id=999999` trae `[]` |
| `test_filtro_por_departamento_acota_sedes_y_total` | AC-7 | `?departamento_id=<bodega>` trae la resma con **1** sede y `stock_total == 30` |
| `test_filtro_solo_criticos` | AC-8 | Todos los devueltos traen `es_critico is True`, y el conjunto es exactamente {tóner, grapadora, bolígrafo} |
| `test_stock_en_el_limite_minimo_es_critico` | AC-5, D-5 | El bolígrafo (`30 <= 30`) sale con `es_critico is True` |
| `test_orden_es_determinista` | AC-10 | Dos llamadas seguidas devuelven el mismo orden, y ese orden es el alfabético por nombre |
| `test_sedes_vienen_ordenadas_por_departamento` | AC-10 | La resma trae sus 2 sedes ordenadas por `departamento_nombre` |
| `test_consultar_existencias_no_altera_el_stock` | `constitucion.md:17` | `/inventario/stock` devuelve lo mismo antes y después |
| `test_listados_existentes_conservan_su_json_con_orden_determinista` | AC-12 | `/categorias` y `/productos` salen ordenados por nombre, y `/categorias`, `/productos` y `/stock` conservan **exactamente** su conjunto de claves (comparación de `set(cuerpo[0].keys())` con el esperado) |
| `test_listar_productos_evita_consultas_n_mas_uno` | AC-15 | Con 5 productos, la petición emite **1** `SELECT ... FROM producto` y **1** `SELECT ... FROM categoria` |
| `test_crear_producto_con_categoria_inexistente_responde_404` | AC-11 | `POST /productos` con `categoria_id: 999999` → 404 con mensaje (no 500) |
| `test_crear_producto_con_categoria_valida_sigue_creando` | AC-11 | El camino feliz de `POST /productos` no se rompió (regresión) |

En `test_smoke.py` se agrega **un** caso a `CASOS_LECTURA`:
`("existencias", "GET", "/api/v1/inventario/existencias", 200)`, y se actualizan los
docstrings del módulo y de `test_endpoint_de_lectura_responde` ("10" → "11"). No se
toca ninguna aserción existente.

### 5.3 Cómo contar las consultas (`AC-15`)

```python
sentencias: list[str] = []

def contar(conn, cursor, statement, parameters, context, executemany):
    sentencias.append(statement)

event.listen(motor, "before_cursor_execute", contar)
try:
    respuesta = cliente.get("/api/v1/inventario/productos")
finally:
    event.remove(motor, "before_cursor_execute", contar)
```

El listener se registra **después** de que el fixture siembre los datos, y se quita en
`finally` para no filtrar listeners entre tests (el motor es function-scoped, pero el
`event` es global al `Engine`; si se acumulara, los conteos de otros tests se ensucian).
`selectinload` lanza su segunda consulta **durante la serialización de la respuesta**,
dentro de la petición, así que el listener la captura. Antes del fix serían 1+5 = 6
consultas; después, 2.

## 6. Fase D — Frontend

### 6.1 `shared/interfaces/index.ts`

Se agregan en la sección `// --- Inventario ---`, después de `RespuestaMovimiento`:

```ts
/** Fila de `inventario` con el nombre del departamento resuelto. */
export interface SedeExistencia {
  inventario_id: number;
  departamento_id: number;
  departamento_nombre: string;
  stock_actual: number;
  ubicacion: string | null;
}

/** Read model de `GET /inventario/existencias`. */
export interface ProductoExistencia {
  producto_id: number;
  nombre: string;
  descripcion: string | null;
  unidad_medida: string | null;
  stock_minimo: number;
  categoria_id: number;
  categoria_nombre: string;
  stock_total: number;
  es_critico: boolean;
  sedes: SedeExistencia[];
}
```

Este archivo refleja 1:1 los schemas del backend, así que los dos tipos nuevos van aquí
y no en el componente.

### 6.2 `InventarioService`

```ts
obtenerExistencias(): Observable<ProductoExistencia[]> {
  return this.http.get<ProductoExistencia[]>(`${URL_API}/inventario/existencias`);
}
```

Sin parámetros: la vista filtra en cliente (spec D-1). Se coloca después de
`obtenerStock`.

**No se borran** `obtenerStock`, `obtenerProductos`, `crearProducto` ni
`registrarMovimiento` aunque la vista deje de llamarlos: son la superficie tipada del
cliente contra la API, y tres de los cuatro tienen consumidor futuro garantizado
(Feature 003 usa `obtenerProductos`; Feature 005 usa `registrarMovimiento`).

### 6.3 `inventario.component.ts`

**Sin tildes ni eñes en los identificadores**, para no apartarse del estilo que ya tiene
el archivo (`cargarStock`, `esStockCritico`) y del resto del frontend.

Estado:

```ts
private readonly inventarioService = inject(InventarioService);

readonly categorias = signal<Categoria[]>([]);
readonly insumos = signal<ProductoExistencia[]>([]);
readonly categoriaSeleccionada = signal<number | null>(null);
readonly consulta = signal('');
readonly soloCriticos = signal(false);
readonly cargando = signal(true);
readonly mensajeError = signal<string | null>(null);
```

Derivados (todo `computed()`, sin estado duplicado):

| Signal | Qué calcula |
|---|---|
| `insumosCoincidentes` | Filtra por texto (nombre, descripción o categoría) y por `soloCriticos`. **No** por categoría. |
| `insumosVisibles` | `insumosCoincidentes` + filtro de `categoriaSeleccionada` |
| `conteoPorCategoria` | `Map<number, number>` sobre `insumosCoincidentes`: cuántos insumos tendría cada categoría si se pulsara |
| `totalCatalogo` / `totalConStock` / `totalCriticos` | Los 3 números de la franja de indicadores |
| `hayFiltros` | `true` si hay texto, categoría o crítico activo |
| `categoriaActual` | Nombre de la categoría seleccionada, para el encabezado |

La separación `insumosCoincidentes` / `insumosVisibles` es la clave del diseño: el panel
de categorías tiene que contar **cuántos habría** si se pulsara cada una, así que sus
conteos se calculan antes de aplicar el filtro de categoría. Si se contara sobre
`insumosVisibles`, al elegir "Papelería" las otras categorías marcarían 0 y el panel
dejaría de poder navegar.

Carga: `forkJoin` de las dos peticiones, para tener **un** estado de carga y **un** estado
de error en vez de dos.

```ts
ngOnInit(): void {
  this.cargarCatalogo();
}

private cargarCatalogo(): void {
  this.cargando.set(true);
  this.mensajeError.set(null);

  forkJoin({
    categorias: this.inventarioService.obtenerCategorias(),
    insumos: this.inventarioService.obtenerExistencias(),
  }).subscribe({
    next: ({ categorias, insumos }) => {
      this.categorias.set(categorias);
      this.insumos.set(insumos);
      this.cargando.set(false);
    },
    error: (fallo) => { /* mismo mensaje que hoy: puerto 8000 */ },
  });
}
```

Métodos públicos: `seleccionarCategoria(categoriaId: number | null)`,
`alternarSoloCriticos()` y `limpiarFiltros()`. Se borran `cargarStock()` y
`esStockCritico()` (spec D-5, `AC-19`).

No hace falta ningun tipo de agrupamiento en el componente: la vista es una tabla y
itera `insumosVisibles()` directo. La separacion `insumosCoincidentes` /
`insumosVisibles` ya resuelve lo unico que exijia el agrupamiento, que es que el panel
pueda contar cuantos habria por categoria.

Comparación de texto: un helper privado `normalizar(texto: string | null): string` que
baja a minúsculas y colapsa espacios, aplicado a la consulta y a los tres campos
comparados. Sin esto, escribir "  RESMA " no encuentra nada.

### 6.4 `inventario.component.html`

**La vista sigue siendo una tabla, con las sedes dentro de la celda del producto.** Es
la decisión tomada por el usuario al revisar este plan.

La razón por la que el read model existía sigue vigente — una fila por sede obligaba a
repetir el producto en N filas y a sumar a mano para saber el total — pero se resuelve
dentro de la tabla: **una fila por insumo**, con las sedes anidadas en la celda
"Existencias por sede" y el total ya calculado en la columna "Stock". Así se conserva
la lectura de tabla que ya tenía la vista sin volver a la duplicación de filas.

Consecuencia asumida: una tabla de 6 columnas es hambrienta de ancho, y el panel lateral
de categorías le quita 220px. Por eso el panel es columna desde `xl:` (1280px) y no
desde `lg:`, y por eso la tabla lleva `overflow-x-auto` con `min-w-[760px]`. En una
pantalla de 1366px con el sidebar abierto el panel sale vertical; en 1280px salen los
chips horizontales. Para la demo, 1366px o más.

Estructura, toda con clases de Tailwind (no hay tokens custom: `theme.extend` está vacío
y esta feature no lo crea):

```
div.space-y-6
├── header  (flex justify-between items-center)
│   ├── título "Catálogo de Insumos" + subtítulo
│   └── franja de 3 indicadores (Insumos / Con existencias / Stock crítico)
├── error (role="alert")            @if (mensajeError())
└── div.grid.xl:grid-cols-[220px_1fr].gap-6
    ├── nav[aria-label="Categorías de insumos"]        ← el panel lateral
    │   ├── botón "Todas"  + conteo
    │   └── @for (categoria of categorias(); track categoria.categoria_id)
    │       └── botón con nombre + conteo, [attr.aria-current]
    └── section
        ├── barra de filtros: input[type=search] + checkbox "Solo stock crítico"
        │   + botón "Limpiar" (@if (hayFiltros()))
        ├── @if (cargando())   → "Cargando catálogo..."
        ├── @else if (hayFiltros() && !insumosVisibles().length)
        │                      → "Ningún insumo coincide con los filtros"
        ├── @else if (!insumosVisibles().length)
        │                      → "El catálogo no tiene insumos cargados"
        └── div.overflow-x-auto
            └── table.w-full.min-w-[760px] (tabla de 6 columnas)
                ├── thead
                │   └── tr.bg-slate-50
                │       th: "Producto", "Categoría", "Existencias por sede",
                │           "Stock", "Mín", "Estado"
                └── tbody.divide-y.divide-slate-100
                    @for (insumo of insumosVisibles(); track insumo.producto_id)
                      tr
                        td: nombre + descripción + unidad
                        td: insumo.categoria_nombre
                        td: @if (insumo.sedes.length)
                             @for (sede of insumo.sedes; track sede.inventario_id)
                               div: sede.departamento_nombre + " · " + (sede.ubicacion ?? "Sin ubicación") + " — " + sede.stock_actual
                           @else "Sin existencias registradas"
                        td: insumo.stock_total
                        td: insumo.stock_minimo
                        td: badge "Crítico" @if (insumo.es_critico) o "Disponible"
```

Detalles de interacción y accesibilidad:

- El input de búsqueda usa una **variable de referencia de template** en vez de
  `FormsModule`: `<input #buscador type="search" [value]="consulta()" (input)="consulta.set(buscador.value)" />`.
  Evita traer un módulo de formularios por un solo campo y evita casts de `$event.target`.
- El checkbox de críticos igual: `<input #critico type="checkbox" [checked]="soloCriticos()" (change)="soloCriticos.set(critico.checked)" />`.
- Todos los interactivos con `focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2`,
  porque `focus:outline-none` sin sustituto deja el teclado sin foco visible.
- El panel de categorías en `xl:` es columna; debajo de `xl:` es una fila horizontal con
  `overflow-x-auto` y chips, para que no robe ancho a la lista en móvil.
- La tabla va dentro de `overflow-x-auto` con `min-w-[760px]` para evitar quiebres en
  pantallas de 1280px.
- Se eliminan los dos botones muertos (spec D-6) y con ellos la columna "Acciones".
- La franja de indicadores **no** duplica el dashboard: son 3 números reales derivados de
  la respuesta, con la etiqueta que los distingue de las cifras de muestra.

Columnas, y por qué cambió cada una respecto a la tabla actual:

| # | Columna | Nota |
|---|---|---|
| 1 | `Producto` | nombre en `font-medium` + `unidad_medida` como badge + `descripcion` en línea propia con `text-slate-500` |
| 2 | `Categoría` | `insumo.categoria_nombre`. Redundante con el panel lateral, pero es la que clasifica cada fila cuando la vista está en "Todas" |
| 3 | `Existencias por sede` | **la celda anidada**: un `div` por sede con `departamento_nombre`, `ubicacion` y la cantidad. Reemplaza la columna "Ubicación", que no tenía nombre de departamento. Con `sedes` vacío, texto atenuado "Sin existencias registradas" |
| 4 | `Stock` | `stock_total`, alineado a la derecha, en `font-bold`, `text-rose-600` si `es_critico` y `text-emerald-600` si no |
| 5 | `Mín.` | `stock_minimo`, a la derecha y en `text-slate-500`. Columna propia y no acumulada con la anterior: en una tabla los números se comparan verticalmente |
| 6 | `Estado` | badge "Crítico" / "Disponible", pintado desde `es_critico`. Ocupa el lugar de la columna "Acciones" |

Dos columnas desaparecen a propósito:

- **"ID"**: mostraba `inventario_id`, que era el identificador de la fila y no del
  producto. Con el read model ya no hay un id único por fila, y el número no le dice
  nada a un bodeguero. Si se quiere, es `producto_id` en la primera columna.
- **"Acciones"**: era el botón "Registrar Movimiento" sin manejador (spec D-6).

Accesibilidad, sin excepción:

- El `caption.sr-only` **se conserva**: la tabla sigue siendo una tabla y el texto
  alternativo para lector de pantalla va en el `caption`, no en un `div`.
- El estado se distingue **por texto y color**, no solo por color: el badge dice
  "Crítico", no solo se pinta de rosa.
- El panel lateral es un `nav` con `aria-label`, y cada botón marca la selección con
  `[attr.aria-current]`, que es el atributo correcto para "elemento actual de un
  conjunto" (a diferencia de `aria-pressed`, que es para interruptores).

Pendiente conocido, fuera de alcance: **la tabla no es ordenable por columna**. Es una
consulta de lectura para el bodeguero, no una grilla de trabajo; el orden es el del
backend (por nombre). Si más adelante hace falta, se agrega con un `signal` de columna
y un `computed` que reordene `insumosVisibles()`.

## 7. Fase E — Tests frontend

`frontend/src/app/features/inventario/inventario.component.spec.ts`, el primero del
feature. Harnessed con el backend HTTP real de Angular, no con mocks de servicio:

```ts
TestBed.configureTestingModule({
  imports: [InventarioComponent],
  providers: [provideHttpClient(), provideHttpClientTesting()],
});
```

| Test | Qué afirma |
|---|---|
| `debe pedir el catalogo y las categorias` | Se emiten exactamente 2 peticiones: `GET .../inventario/existencias` y `GET .../inventario/categorias` |
| `debe renderizar los insumos con su categoria y su sede` | Con `flush` de los fixtures, la fila muestra el nombre del insumo, su categoría y "departamento · ubicación" |
| `debe filtrar por texto` | `consulta.set('resma')` + `detectChanges()` deja solo la resma en el DOM |
| `debe filtrar por categoria` | `seleccionarCategoria(id)` + `detectChanges()` deja solo las filas de esa categoría |
| `debe filtrar solo los insumos criticos` | `alternarSoloCriticos()` deja únicamente los que traen `es_critico` |
| `debe limpiar los filtros` | `limpiarFiltros()` restablece consulta, categoría y crítico |
| `debe mostrar un error si el backend no responde` | `req.flush('error', { status: 500, statusText: 'Error' })` produce el `role="alert"` con la mención al puerto 8000 |
| `debe distinguir el estado vacio del estado con filtros` | Sin filtros y lista vacía muestra un mensaje; con filtros activos muestra el otro |

Los fixtures se escriben como funciones locales (`crearInsumo(...)` con sobreescritura
de campos) que devuelven `ProductoExistencia[]` y `Categoria[]`. Todas las consultas se
atienden con `httpMock.expectOne(...)` + `flush(...)` dentro de un `afterEach` con
`httpMock.verify()`, que es lo que hace que el test falle si el componente pide algo que
el test no espera.

El componente es `OnPush`: cada `it` termina con `fixture.detectChanges()` antes de
leer el DOM.

## 8. Fase F — Documentación

- **`docs/spec/stack.md`**: en §2 (backend), un bloque "Read models de consulta"
  explicando el patrón de D-7 (el service arma el DTO a mano cuando la consulta cruza
  tablas, sin `from_attributes`) y por qué se agrupa en Python. En §3, Nota 2, se
  actualiza para dejar constancia de que la Feature 002 revisó la necesidad de
  `shared/components/` y decidió no crearlos, con el motivo. En §4, se agrega
  `ProductoExistencia` / `SedeExistencia` a la lista de convención de idioma.
- **`docs/spec/roadmap.md`**: marcar `Feature 002` con `[x]` **solo al cierre**, y
  completar la fila del índice con los enlaces a `plan.md` y `tasks.md`.
- **`MEMORY.md`**: estado nuevo, la decisión D-1 con su disparador, y los aprendizajes
  de implementación (por ejemplo: `select()` estilo Core exige onclause explícito).
- **`AGENTS.md`**: `grep` de coherencia. No se anticipa cambio: §6 y §9 no nombran nada
  de inventario. Se revisa al cierre.
- **`docs/spec/features/001-*/`**: se lee, no se edita. Si algún doc historico quedara
  contradicho, la Feature 002 lo documenta en su `tasks.md`.

## 9. Orden de ejecución y compuertas

| # | Fase | Compuerta para pasar a la siguiente |
|---|---|---|
| 1 | Test backend nuevo, en rojo | Falla por 404 (la ruta no existe) |
| 2 | Schemas → service → router | `pytest tests/api/test_catalogo_consulta.py` en verde |
| 3 | Ajustes a rutas existentes + sus tests | `pytest` completo en verde, **los 25 casos viejos sin reescribir** |
| 4 | Interfaces + servicio Angular | `npm run build` compila |
| 5 | Componente + template | `npm run build` compila, la vista se ve en el navegador |
| 6 | Spec del componente | `npm test` en verde |
| 7 | Documentación + AC de cierre | Todas las verificaciones de `spec.md` §6 |

La compuerta de la fase 3 es la importante: si algún test viejo falla, el problema está
en la fase B y se corrige ahí, no ajustando el test.

## 10. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El orden determinista rompe un test viejo que dependía del orden de inserción | 2-3 tests | La suite siembra 1-2 filas por tabla, así que el orden no cambia de hecho. Si falla, se revisa el test, no se revierte el `order_by` |
| `db.execute(select(...))` con `Row` de estilo Core no expone los campos por atributo | Rompe la fase 2 | Se confirma con un test del caso mínimo antes de escribir el agrupador |
| `ilike` sobre SQLite se comporta distinto que `ILIKE` en PostgreSQL | Falso verde en CI | El test se escribe con los mismos términos que usaría el usuario ("RESMA" en mayúsculas), no con un caso que solo funcione en un motor |
| La reescritura del template rompe algo que no se ve en los tests | Regresión visual | Se levanta `npm start` contra el backend con `02_datos_semilla.sql` cargado y se recorre la vista antes de dar la fase 5 por cerrada |
| La franja de indicadores se confunde con el dashboard de cifras de muestra | Confusión en la demo | Se rotula con la fuente ("catálogo cargado") y se anota en `MEMORY.md` que el dashboard sigue pendiente de la Feature 009 |

## 11. No hacer en esta feature

- No agregar `POST`/`PUT`/`DELETE` de productos o categorías.
- No agregar `GET /inventario/movimientos`.
- No tocar `app/models/`, el DDL de `database/01_esquema.sql` ni `conftest.py`.
- No cambiar el 500 de `crear_ticket` por `producto_id` inexistente (su test sigue
  esperando 500: es de la Feature 003).
- No tocar `features/dashboard/`, `features/tickets/` ni `features/administracion/`.
- No crear `shared/components/` ni `shared/pipes/`.
- No migrar las funciones existentes del service de `db.query()` a `select()`.
- No agregar dependencias a `requirements.txt` ni a `package.json`.
- No tocar `institucion_id="INST01"` en los fixtures: es `VARCHAR`, no una secuencia.
