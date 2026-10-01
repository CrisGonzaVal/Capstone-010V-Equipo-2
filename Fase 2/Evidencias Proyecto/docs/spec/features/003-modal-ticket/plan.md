# Feature 003 — Plan Técnico

**Spec:** [`spec.md`](spec.md)

Qué archivos se tocan, en qué orden, y los detalles que no se deducen leyendo el spec.
Cada AC de `spec.md` §6 tiene aquí su archivo y su caso de prueba.

## 1. Inventario de archivos

| Archivo | Cambio | Riesgo |
|---|---|---|
| `backend/app/schemas/ticket_schema.py` | +4 DTO de catálogo, +1 DTO contenedor, `min_length`/`max_length`/`gt` en los DTO de entrada | Bajo |
| `backend/app/services/ticket_service.py` | +`obtener_catalogos()` (read model), `crear_ticket` con prevalidación y `try/except` | Medio: toca la transacción |
| `backend/app/api/v1/endpoints/tickets.py` | +`GET /catalogos`, `status_code` y `description` en las 3 rutas | Bajo |
| `frontend/src/app/shared/config/url-api.ts` | **nuevo**: mueve `URL_API` fuera de `features/inventario` | Bajo |
| `frontend/src/app/features/inventario/services/inventario.service.ts` | importa `URL_API` de `shared/config` | Bajo |
| `frontend/src/app/features/administracion/services/usuario.service.ts` | ídem | Bajo |
| `frontend/src/app/features/tickets/services/ticket.service.ts` | ídem + `obtenerCatalogos()` | Bajo |
| `frontend/src/app/features/inventario/inventario.component.spec.ts` | ídem: importa `URL_API` del `./services/inventario.service` | Bajo |
| `frontend/src/app/shared/interfaces/index.ts` | +5 tipos de catálogo | Bajo |
| `frontend/src/app/features/tickets/tickets.component.ts` | signals del modal, `FormGroup` con `FormArray`, abrir/cerrar | Alto: primer formulario |
| `frontend/src/app/features/tickets/tickets.component.html` | `<dialog>` con el formulario, `(click)` del botón, estado de éxito | Alto |
| `backend/tests/api/test_modal_ticket.py` | **nuevo** | — |
| `backend/tests/api/test_smoke.py` | 1 caso migrado de 500 a 404 | — |
| `backend/tests/api/test_transaccion_ticket.py` | 2 casos migrados de 500 a 404 | — |
| `frontend/src/app/features/tickets/tickets.component.spec.ts` | **nuevo** | — |
| `docs/spec/stack.md` §2 y §3 | read model de catálogos + ubicación de `URL_API` | — |
| `AGENTS.md` §5 | nota de los dos puertos | — |
| `docs/spec/roadmap.md`, `MEMORY.md` | estado y fila | — |

**No se tocan:** `backend/app/models/`, `database/01_esquema.sql`,
`backend/app/services/inventario_service.py`, `tickets.component.ts`'s columnas del Kanban,
`listar_tickets`, `actualizar_estado_ticket`, `conftest.py`.

## 2. Orden de ejecución

```
1. shared/config/url-api.ts + los 4 imports                          → grep limpio de imports cruzados
2. schemas: los 4 DTO de catálogo + las validaciones
3. service: obtener_catalogos()
4. endpoints: GET /catalogos + status_code/description
5. pytest de los catálogos                          → verde antes de seguir
6. service: prevalidación + try/except en crear_ticket
7. pytest de la validación y de los 404              → los 43 previos intactos
8. frontend: tipos + ticket.service
9. frontend: componente + template del modal
10. tickets.component.spec.ts + ng test
11. cierre: docs, stack.md, MEMORY.md, rebuild de la imagen
```

El paso 1 va primero a propósito: es el que más rápido revela si el resto del diseño se
sostiene, y no depende de nada.

## 3. `obtener_catalogos()` — el read model

Cuatro catálogos, cuatro consultas, un solo DTO. Cada lista se arma con la técnica que
corresponde, no con una sola consulta para todo: los cuatro conjuntos no comparten clave y
un `UNION` obligaría a castear filas de 3 columnas a 5.

Todo el código nuevo usa `select()` (SQLAlchemy 2.0), no `db.query()`. Los `db.query()`
que quedan en `listar_tickets()` y `actualizar_estado_ticket()` son preexistentes y
pertenecen al alcance de la Feature 004.

```python
def obtener_catalogos(db: Session) -> CatalogosTicketRespuesta:
    prioridades = db.execute(
        select(Prioridad).order_by(Prioridad.prioridad_id)
    ).scalars().all()
    estados = db.execute(
        select(EstadoTicket).order_by(EstadoTicket.estado_id)
    ).scalars().all()

    consulta_productos = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Categoria.nombre_cat.label("categoria_nombre"),
            func.coalesce(func.sum(Inventario.stock_actual), 0).label("stock_total"),
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(Inventario, Inventario.producto_id == Producto.producto_id)
        .group_by(
            Producto.producto_id,
            Producto.nombre,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Categoria.nombre_cat,
        )
        .order_by(Producto.nombre, Producto.producto_id)
    )

    consulta_solicitantes = (
        select(
            Usuario.usuario_id,
            Usuario.nombre,
            Usuario.apellido,
            Usuario.correo,
            Departamento.nombre_dep.label("departamento_nombre"),
        )
        .join(Departamento, Usuario.departamento_id == Departamento.departamento_id)
        .order_by(Usuario.apellido, Usuario.nombre, Usuario.usuario_id)
    )

    return CatalogosTicketRespuesta(
        prioridades=[PrioridadRespuesta.model_validate(p) for p in prioridades],
        estados=[EstadoTicketRespuesta.model_validate(e) for e in estados],
        productos=[
            ProductoCatalogoRespuesta(
                producto_id=fila.producto_id,
                nombre=fila.nombre,
                unidad_medida=fila.unidad_medida,
                categoria_nombre=fila.categoria_nombre,
                stock_total=fila.stock_total,
                es_critico=es_stock_critico(fila.stock_total, fila.stock_minimo),
            )
            for fila in db.execute(consulta_productos).all()
        ],
        solicitantes=[
            SolicitanteRespuesta.model_validate(fila)
            for fila in db.execute(consulta_solicitantes).mappings().all()
        ],
    )
```

Un detalle que el `select()` obliga a hacer explícito y que `db.query()` escondía:
`scalars()` para las dos consultas de entidad (devuelven modelos, no filas) y
`.mappings()` para la de solicitantes (devuelve filas de varias tablas que Pydantic valida
como dict). Con `db.query(...).all()` esa distinción no existía.

Cinco detalles que no son obvios:

1. **`es_stock_critico` se importa de `inventario_service`.** Es la **misma** función que
   usa `GET /inventario/existencias` (`AC-3`). Importar una función pura de otro service no
   es lógica de negocio duplicada ni una violación de capas: si mañana la regla del stock
   crítico cambia, tiene que cambiar en un solo lugar.
2. **`func.coalesce(func.sum(...), 0)`** porque `stock_total` es `NOT NULL` en el DTO: un
   producto sin filas en `inventario` debe salir en 0 y no en `None`. Es el mismo caso que
   `AC-4` de la Feature 002 cubría con `outerjoin`.
3. **`group_by` incluye todas las columnas del `SELECT`.** PostgreSQL 16 exige que una
   columna agrupada esté en el `group_by` o dentro de un agregado; SQLite es más laxo y
   dejaría pasar un error que revienta en producción (`AC-30`).
4. **`Producto.producto_id` es la clave del grupo**, como en el read model de la 002: la
   fila es la unidad de información y se agrupa por clave primaria, no por texto.
5. **`model_validate(p)` para las de `from_attributes`, constructor para las de read model.**
   Mezclarlos en un mismo `list(...)` con la misma llamada es el error fácil de cometer aquí.

## 4. `crear_ticket` — prevalidación y atomicidad

```python
def crear_ticket(db: Session, datos: TicketCrear) -> Ticket:
    _verificar_referencia(db, Usuario, datos.usuario_id, "usuario")
    _verificar_referencia(db, Prioridad, datos.prioridad_id, "prioridad")
    _verificar_referencia(db, EstadoTicket, datos.estado_id, "estado")
    _verificar_productos(db, datos.detalles)

    try:
        nuevo_ticket = Ticket(**datos.model_dump(exclude={"detalles"}))
        db.add(nuevo_ticket)
        db.flush()
        for detalle in datos.detalles:
            db.add(DetalleTicket(
                ticket_id=nuevo_ticket.ticket_id,
                producto_id=detalle.producto_id,
                cantidad_solicitada=detalle.cantidad_solicitada,
                cantidad_entregada=0,
            ))
        db.commit()
        db.refresh(nuevo_ticket)
    except Exception:
        db.rollback()
        raise

    return nuevo_ticket
```

Los helpers de prevalidación:

```python
def _verificar_referencia(db: Session, modelo, valor: int, etiqueta: str) -> None:
    if db.get(modelo, valor) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe {etiqueta} indicado: {valor}",
        )


def _verificar_productos(db: Session, detalles) -> None:
    ids_requeridos = {detalle.producto_id for detalle in detalles}
    faltantes = [id_ for id_ in sorted(ids_requeridos) if db.get(Producto, id_) is None]
    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe producto indicado: {faltantes[0]}",
        )
```

`_verificar_referencia()` cubre las 3 referencias de una fila; `_verificar_productos()`
necesita su propio helper porque recorre una colección. Los mensajes nombran la referencia
con su valor: el 404 es accionable, y `AC-6`/`AC-7` lo exigen.

Tres puntos:

- **Los productos se validan todos y se deduplican primero** con un `set`, así que 5 ítems
  del mismo producto hacen una sola búsqueda, y el mensaje reporta el id más bajo que falta
  (ordenado, para que sea determinista). Por eso el listado de productos va en un helper
  aparte y no reusa `_verificar_referencia()`: la diferencia es que el mensaje nombra la
  colección, no un id suelto.
- **El `rollback()` antes del primer `add()` no hace falta**, porque las 4 validaciones ya
  terminaron. El `try` empieza en la escritura, que es donde puede haber un fallo de base.
- **El `except` es uno solo y es `Exception`, no `HTTPException`.** Los 404 de la
  prevalidación se lanzan **antes** del `try`, así que no necesitan rollback: en ese punto
  todavía no se escribió nada. Dentro del `try` lo que falla es la base de datos
  (`IntegrityError`, `OperationalError`), que no hereda de `HTTPException`. Un
  `except HTTPException` dentro del `try` no se ejecutaría nunca.
- **El `rollback()` explícito es la red de `constitucion.md` §3, no el mecanismo que impide
  el huérfano.** Eso lo hace la prevalidación, que no escribe nada. Y con el `get_db`
  actual sería **redundante de forma observable**: `get_db` hace `db.close()` en su
  `finally` y `close()` ya revierte, así que borrarlo deja la suite en verde (comprobado
  por mutación, ver `tasks.md` §9). Se conserva igualmente porque el método debe ser
  correcto por sí mismo y no por el cleanup de quien lo llama, que es lo que dejaría de
  ser cierto en cuanto dos tickets compartieran transacción. Registrar esto evita que un
  test futuro afirme cubrir el `rollback()` sin poder hacerlo.

## 5. Frontend — el modal

### 5.1 `@angular/forms` es la primera vez que se usa

No hay un solo `FormGroup` en el proyecto. El formulario se declara en el componente con
`inject(NonNullableFormBuilder)`:

```typescript
private readonly fb = inject(NonNullableFormBuilder);

formulario = this.fb.group({
  usuario_id: [null as number | null, Validators.required],
  prioridad_id: [null as number | null, Validators.required],
  estado_id: [null as number | null, Validators.required],
  asunto: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(150)]],
  descripcion: [''],
  detalles: this.fb.array([this.crearFilaDetalle()]),
});

crearFilaDetalle() {
  return this.fb.group({
    producto_id: [null as number | null, Validators.required],
    cantidad_solicitada: [1, [Validators.required, Validators.min(1)]],
  });
}
```

`NonNullableFormBuilder` para que los controles nazcan con valor en vez de `null`, que es lo
que hace `cantidad_solicitada` en 1 en vez de 0 y por lo tanto no nace inválido por accidente.

**El formulario no se guarda en el `FormGroup` de `ticket.component`:** las validaciones del
cliente son espejo de las del schema Pydantic (`AC-19` y `D-5`). El servidor sigue siendo la
fuente; el cliente solo evita el viaje redondo.

### 5.2 El `<dialog>` se abre con `viewChild` + `effect`, no en el handler

Este es el detalle que rompe el modal si se hace de la forma obvia. Con `@if (modalAbierto())`
el `<dialog>` **no existe en el DOM** hasta que Angular renderiza, así que
`dialogo.nativeElement.showModal()` dentro del `(click)` de "Abrir" encuentra `undefined`.

La forma que funciona en Angular 18:

```typescript
readonly dialogo = viewChild.required<ElementRef<HTMLDialogElement>>('dialogo');

constructor() {
  effect(() => {
    const abierto = this.modalAbierto();
    const nativo = this.dialogo().nativeElement;
    if (abierto && !nativo.open) nativo.showModal();
    if (!abierto && nativo.open) nativo.close();
  });
}
```

El `effect` corre **después** del render, así que la `viewChild` ya resuelve. El `if (!nativo.open)`
protege de que `showModal()` se llame dos veces sobre un diálogo abierto, que lanza
`InvalidStateError`.

Para cerrar por `Esc` no hace falta `@HostListener`: el `<dialog>` nativo ya lo hace y
dispara el evento `close`. El `(close)="cerrar()"` del template sincroniza el signal.

### 5.3 Los catálogos se piden al abrir, una vez

`catalogos = signal<CatalogosTicket | null>(null)` y un `cargandoCatalogos`. Se pide en
`abrirModal()`, no en `ngOnInit`: si el usuario nunca abre el modal, no se descargó nada. Con
`cargandoCatalogos` y el error de catálogos hay **dos** estados de error distintos en la vista,
que `AC-21` exige que se distingan.

Un solo `forkJoin` no alcanza porque hay **una** petición. `forkJoin` de una sola Observable es
un `switchMap` con pasos innecesarios; la forma idiomática es(mapear(() => ...))` o, más
simple, un `.subscribe` con los dos handlers. Se usa `.subscribe({ next, error })` y se
documenta por qué no `forkJoin`.

### 5.4 El `FormArray` y los duplicados

`detalles` es un `FormArray`. `agregarDetalle()` hace `push(this.crearFilaDetalle())` y
`quitarDetalle(indice)` hace `removeAt(indice)`, con el botón deshabilitado cuando queda una
sola fila (un ticket sin ítems es 422, `D-5`).

Al enviar, `combinarDetalles()` recorre el array y **suma las cantidades de los productos
repetidos** antes de mandar el payload. La base admite duplicados (`detalle_ticket` no
declara `UNIQUE`), pero el selector no debería dejar que eso llegue al servidor: es un error
de UX, no una regla de negocio (§3, Fuera).

### 5.5 Errores del backend por campo

Un 422 de FastAPI trae `detail` como lista de `{loc, msg, type}`. Se mapea:

```typescript
private erroresPorCampo(): Record<string, string> {
  const salida: Record<string, string> = {};
  for (const error of this.detalleErrores()) {
    const campo = error.loc.at(-1);          // ['body', 'detalles', 0, 'cantidad_solicitada']
    if (typeof campo === 'string') salida[campo] = error.msg;
  }
  return salida;
}
```

`loc.at(-1)` funciona para los dos casos: en un error de `TicketCrear` el último elemento es
el nombre del campo, y en un error de detalle es el índice del ítem más el nombre
(`detalles.0.cantidad_solicitada`), que se lee como "fila 1". Se aplica con un helper
`etiquetaDeError()` que traduce los mensajes de Pydantic al español que ya usa el resto de la
interfaz, porque `max_length` sale como "String should have at most 150 characters".

### 5.6 Los errores 404 no se prueban desde el cliente

`AC-6` y `AC-7` son del backend. Desde la vista, un 404 solo puede aparecer si otro proceso
borró el producto entre la carga del catálogo y el envío; se muestra el mensaje del backend
en un bloque `role="alert"` sin tratar de mapearlo a un campo. Se documenta en `tasks.md`.

## 6. Casos de prueba

### 6.1 Backend — `test_modal_ticket.py`

Fixture `datos_catalogo_ticket`, **apoyado** en `datos_base` (no lo reemplaza) que agrega
2 prioridades y 3 estados más, para que el orden y el corte se puedan distinguir de un catálogo
de un solo elemento. `conftest.py` no se toca.

| Caso | AC |
|---|---|
| `test_catalogos_responde_200_con_las_cuatro_listas` | AC-1 |
| `test_openapi_declara_catalogos_y_conserva_las_tres_rutas` | AC-1, AC-12 |
| `test_estados_salen_en_el_orden_del_flujo` | AC-2 |
| `test_productos_del_catalogo_traen_stock_y_critico` | AC-3 |
| `test_es_critico_del_catalogo_coincide_con_existencias` | AC-3 |
| `test_solicitantes_traen_departamento_y_orden_por_apellido` | AC-4 |
| `test_catalogos_vacios_responden_listas_vacias` | AC-5 |
| `test_ticket_con_producto_inexistente_responde_404` | AC-6 |
| `test_ticket_con_usuario_inexistente_responde_404` | AC-7 |
| `test_ticket_con_prioridad_inexistente_responde_404` | AC-7 |
| `test_ticket_con_estado_inexistente_responde_404` | AC-7 |
| `test_referencia_invalida_no_deja_ticket_huerfano` | AC-8 |
| `test_asunto_corto_o_largo_responde_422` | AC-9 |
| `test_ticket_sin_detalles_responde_422` | AC-9 |
| `test_cantidad_solicitada_no_positiva_responde_422` | AC-9 |
| `test_ticket_valido_responde_201_con_detalles_y_entregada_en_cero` | AC-10 |
| `test_crear_ticket_no_valida_stock` | AC-11 |

Los dos casos de atomicidad que se migran en otros archivos (`AC-8`):
`test_smoke.py::test_ticket_con_producto_inexistente_responde_500_defecto_conocido` → se
renombra a `..._responde_404` y se actualiza su docstring, que hoy dice "Cuando se corrija,
este test debe pasar a 400"; y `test_transaccion_ticket.py::test_detalle_invalido_no_deja_
ticket_huerfano` y su gemelo de tres detalles, que pasan de 500 a 404 conservando el resto de
sus aserciones.

### 6.2 Frontend — `tickets.component.spec.ts`

`provideHttpClient()` + `provideHttpClientTesting()`, y `httpMock.verify({ ignoreCancelled:
true })` en el `afterEach` por el `forkJoin` de la Feature 002.

| Caso | AC |
|---|---|
| `debe pedir los catalogos al abrir el modal` (1 petición exacta a `/tickets/catalogos`) | AC-17 |
| `debe_llenar_los_desplegables_con_los_catalogos` | AC-17, AC-18 |
| `debe_arrancar_el_estado_en_el_primero_del_flujo` | AC-2 |
| `debe_pedir_al_menos_un_detalle` | AC-18 |
| `debe_agregar_y_quitar_detalles` | AC-18 |
| `no_debe_enviar_con_el_formulario_invalido` | AC-19 |
| `debe_enviar_el_ticket_y_avisar_el_id_creado` (payload con las cantidades sumadas) | AC-20 |
| `debe_mostrar_el_error_del_backend_sin_cerrar_el_modal` | AC-21 |
| `debe_distinguir_el_error_de_catalogos_del_de_guardado` | AC-21 |
| `no_debe_permitir_el_doble_envio` | AC-22 |
| `debe_ignorar_los_catalogos_anteriores_al_recargar` | AC-22 |

## 7. Riesgos

| Riesgo | Mitigación |
|---|---|
| El `FormArray` desincroniza el índice que muestra el error del 422 | Un solo helper (`etiquetaDeError`) y el test del error de cantidad en la fila 2 |
| Cambiar `group_by` a algo más laxo revienta solo en PostgreSQL | El `group_by` completo y `AC-30` contra el contenedor |
| El test de 422 en SQLite pasa sin probar el CHECK de la base | Documentado en §7 del spec; el 422 viene del schema, no del CHECK |
| El `effect()` del `<dialog>` llama `showModal()` dos veces | La guarda `if (!nativo.open)` |
| El modal tapa el botón que lo abrió y no se ve cerrarlo | El botón "Cancelar" y el `Esc` nativos, con foco en el primero al abrir |
| El `rebuild` de la imagen del frontend al cierre tarda minutos | Va al final, después de los tests, una sola vez |