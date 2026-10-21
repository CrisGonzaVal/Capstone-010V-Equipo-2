# Feature 018 — Plan técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario. Este plan concreta su implementación sin ampliar el alcance. No se agregan dependencias ni se toca el modelo de datos.

## 1. Decisiones técnicas

### 1.1 Backend por capas

1. **DTOs Pydantic v2.** En `backend/app/schemas/inventario_schema.py` añadir `AmbitoInventarioRespuesta` con `sedes: List[SedeFiltroRespuesta]` y `departamentos: List[DepartamentoFiltroRespuesta]`; los DTO mínimos reflejan campos `sede_id`, `sede_nombre`, `departamento_id`, `departamento_nombre` y `sede_id` asociado. Construir las respuestas desde mappings/proyecciones explícitas. Si se usa `ConfigDict`, solo configuración Pydantic v2; no se precisa `from_attributes` para filas agregadas.
2. **Servicio.** Extender `backend/app/services/inventario_service.py` con `obtener_ambito_inventario(db, identidad)` y extender `listar_existencias(..., sede_id=None, ...)`. La ruta no contiene reglas de alcance ni consultas SQL. Reutilizar `ambito_service.alcance_institucional(db, identidad)` y `sede_del_alcance_por_rol(db, identidad)`; ORM/SQLAlchemy Core tipado, joins explícitos y sin SQL raw.
3. **Ruta.** En `backend/app/api/v1/endpoints/inventario.py` publicar `GET /api/v1/inventario/ambito` y añadir `sede_id: Optional[int]` a `GET /api/v1/inventario/existencias`. Cada ruta declara `response_model`, `status_code`, summary/description, errores OpenAPI y dependencias existentes `requiere_operacion` + `requiere_capacidad`.
4. **Autorización.** Añadir exactamente una entrada a `MATRIZ_PERMISOS`: `GET /api/v1/inventario/ambito` → `{Administrador, Bodeguero}`. Asociarla a la capacidad ya existente `inventario` en `backend/app/core/capacidades.py`. Existencias conserva matriz y capacidad actuales; solo se amplía su contrato con el query param.

### 1.2 Contrato técnico exacto

#### `GET /api/v1/inventario/ambito`

- Sin query ni body.
- Respuesta 200, objeto:

```json
{
  "sedes": [{"sede_id": 1, "sede_nombre": "Sede Central"}],
  "departamentos": [
    {"departamento_id": 1, "departamento_nombre": "Operaciones", "sede_id": 1}
  ]
}
```

- Administrador: todas las sedes activas de su institución y departamentos activos con sede asignada a una sede de esa institución.
- Bodeguero con sede asignada: solo su sede si está activa y departamentos activos asociados a esa sede. Sin sede asignada, 409 con mensaje de sede no asignada y sin fallback.
- Solicitante y Superadmin: 403; sesión ausente/no válida: 401; capacidad institucional `inventario` apagada: 403.
- No devuelve institución seleccionable, usuarios, tickets, productos, stock ni agregados. Los departamentos sin sede no forman opciones.
- El orden será determinista: sedes por `(nombre, sede_id)` y departamentos por `(nombre_dep, departamento_id)`.
- La ruta usa la operación de matriz para autorización y gating; la identidad y tenant se resuelven en el flujo estándar de dependencias.

#### `GET /api/v1/inventario/existencias`

- Conserva `q`, `categoria_id`, `departamento_id`, `solo_criticos` y el response model vigente. Añade `sede_id: int | None = None`.
- `sede_id` se incorpora a `condicion_stock` antes del `outerjoin` con `StockSede`: `condicion_stock = and_(..., StockSede.sede_id == sede_id)`. Si `sede_id` está presente, agregar `StockSede.stock_sede_id.is_not(None)` en el `WHERE`, degradando efectivamente el `outerjoin` a INNER. **No** ejecutar `db.get(Sede, sede_id)` ni otro lookup previo; un id ausente del esquema del actor (incluido el de otro tenant) produce 200 con `[]` como filtro de lista.
- Para Administrador, sede válida dentro de la institución filtra a esa sede; sede fuera/inexistente en el tenant es 200/`[]`. Para Bodeguero y Solicitante, el predicado `sede_rol` ya restringe la fila; su propia sede produce el filtro normal y otra sede da 200/`[]` por intersección. Identidad operativa sin asignación (Bodeguero/Solicitante) sigue 409 desde `sede_del_alcance_por_rol`.
- `departamento_id` mantiene su validación actual: `validar_departamento_en_alcance` genera 403 en el harness cuando la fila existe y pertenece a institución distinta; entre esquemas tenant una fila ajena no es visible y cae en departamento inexistente → 200/`[]`. Departamento inexistente, sin sede o de otra sede de la misma institución → 200/`[]`.
- Si ambos filtros se envían, intersectar sede solicitada y sede del departamento en `condicion_stock`; selección incoherente → 200/`[]`. La UI previene esa llamada limpiando departamento incompatible al cambiar sede.
- `stock_total`, `sedes[]` y `es_critico` se construyen después de aplicar ambos predicados, por lo que con `sede_id` reflejan solo el saldo de esa sede. Con ninguno de los filtros organizacionales se conserva `outerjoin` y aparecen productos sin saldo con `sedes: []`, total 0. Con sede/departamento la degradación a INNER los oculta.
- La franja se deriva de la respuesta cargada (catálogo, con stock y críticos) y se vuelve a calcular tras cada llamada filtrada; al no enviar `sede_id` ni `departamento_id`, representa el agregado permitido por rol.
- Código de errores: 401 sesión; 403 rol/capacidad, y `departamento_id` de institución distinta cuando el recurso es visible en el esquema de ejecución; 409 rol de sede operativa sin asignación. IDs de sede/departamento ausentes del tenant no se distinguen: 200/`[]`.
- Esto no modifica el endpoint de recurso `GET /inventario/stock?sede_id=…`, cuyo contrato 011 conserva el 404 para recurso inexistente/ajeno.

### 1.3 Consultas de servicio y ámbito

- `obtener_ambito_inventario` deriva institución con `alcance_institucional`; para Bodeguero obtiene sede mediante `sede_del_alcance_por_rol` (incluye 409 si falta). Administrador consulta opciones del tenant. Bodeguero consulta opciones restringidas a su `sede_id` asignado. Todas las proyecciones solo seleccionan IDs, nombres, estado y asociación sede-departamento; filtros de `activo` se aplican en SQL.
- La sede asignada de Bodeguero puede estar inactiva: en ese caso la respuesta de ámbito entrega las listas vacías (la opción inactiva se excluye conforme a spec D-5); no se revela ni se elige otra sede. El endpoint de existencias mantiene el ámbito operativo existente. Si la implementación descubre que `sede_del_alcance_por_rol` ya no puede consultar sede inactiva debido al predicado activo, detenerse y reportar incompatibilidad antes de alterar esa semántica fuera de la spec.
- En `listar_existencias`, primero conservar `sede_rol`, institución y resolución departamental actual. Agregar restricciones de sede a `condicion_stock`; aplicar `stock_sede_id.is_not(None)` cuando cualquiera de los filtros organizacionales restringe a una sede. Criticidad conserva `_es_producto_critico`, con `sedes` ya limitada a la respuesta.
- Evitar el patrón de `/inventario/stock`: allí se consulta un recurso individual de sede y se hace lookup para 404. Aquí sede es parámetro de filtro de lista, y la consulta debe preservar 200/`[]`.

### 1.4 Matriz y suites heredadas

- La matriz pasa de 60 a 61 entradas: una ruta nueva exclusiva de Administrador+Bodeguero; no cambia roles de ninguna ruta existente.
- En `backend/tests/api/test_ciclo_vida_autorizacion_014.py`, actualizar explícitamente a 61 las aserciones absolutas `test_matriz_tiene_exactamente_60_operaciones_tras_014` y `test_openapi_tiene_60_operaciones_tras_014`. Registrar el cambio en evidencia como ampliación de 014 por Feature 018, no como reescritura silenciosa.
- En `backend/tests/api/test_permisos.py`, preservar la referencia histórica independiente `MATRIZ_ESPERADA` de 55 y su `len == 55`; agregar una referencia aditiva independiente para la nueva operación, como patrón de `test_permisos_012.py`.
- Ampliar contrato/capacidad en `backend/tests/api/test_capacidades_gating_012.py` y los seams de igualdad entre rutas OpenAPI/matriz. Las transcripciones históricas 008/010/012/013/014 se conservan salvo las dos aserciones absolutas mencionadas y la extensión independiente nueva.
- Prueba 403 de departamento de otra institución: puede afirmarse en SQLite/harness en `backend/tests/api/test_ambito_institucional.py` (el fixture comparte esquema); **no** crear test gated PostgreSQL esperando 403. En PostgreSQL cross-tenant la entidad no existe en el esquema del actor y el resultado es 200/`[]`.

### 1.5 Frontend

- En `frontend/src/app/shared/interfaces/index.ts`, declarar tipos de opciones de sede/departamento y respuesta de ámbito 1:1 con DTO.
- En `frontend/src/app/features/inventario/services/inventario.service.ts`, añadir `obtenerAmbitoInventario()` y ampliar `obtenerExistencias(filtros?)` para query params opcionales `sede_id` y `departamento_id` (mantener query typing español). No inyectar ni importar `AdministracionService`.
- En `frontend/src/app/core/auth/roles.ts`, añadir `puedeVerFiltrosInventario(rol)` true solo para Administrador/Bodeguero. En `roles.spec.ts` cubrir esos dos, Solicitante, Superadmin, null y desconocido. Es visibilidad; servidor sigue autorizando.
- En `inventario.component.ts`, agregar signals de opciones de ámbito, `sedeSeleccionada`, `departamentoSeleccionado`, estados de carga/error de ámbito y selección disponible; `computed()` para departamentos filtrados por sede y `hayFiltros`; la franja se calcula del resultado server-side actual. La carga inicial combina categoría, ámbito cuando helper lo permita, y existencias actuales. Bodeguero sin sede/ámbito 409 presenta mensaje y desactiva filtros organizacionales; existencias mantienen el resultado/error de su lectura. Administrador/Solicitante conservan carga de existencias de acuerdo con sus permisos.
- Cada cambio organizacional llama a `obtenerExistencias` con todos los filtros organizacionales activos; texto/categoría/críticos permanecen coherentes con la estrategia existente (si son cliente, se aplican al conjunto organizacional ya cargado; no se envían si el contrato de spec no les exige servidor). Si sede cambia, limpiar departamento incompatible. Limpiar filtros restablece todo y solicita el agregado permitido por rol.
- En `.html`, selectores nativos `<select>` con labels accesibles, clases Tailwind y focus visible; solo Administrador ve sede; Administrador/Bodeguero ven departamento; nota literal de D-3 solo Bodeguero. Selectores no están en DOM para Solicitante/Superadmin. No usar CSS inline ni crear componente compartido.
- En `inventario.component.spec.ts`, cubrir requests HTTP/params, carga/error/409, perfiles de rol, nota literal solo Bodeguero, coordinación sede-departamento, métricas, vacíos, filtros combinados y limpieza.

### 1.6 Alternativas técnicas

- **Sede dentro de `condicion_stock`/outerjoin más condición de existencia** (elegida): mantiene 200/`[]` para filtro sin fila visible en tenant y calcula agregados a partir de la sede seleccionada. **Descartado:** `db.get(Sede, sede_id)` antes de query; no distingue cross-schema y produciría 404 incompatibles con spec.
- **Nueva lectura de ámbito de inventario** (elegida): DTO mínimo, roles específicos y gating existente `inventario`. **Descartado:** consumir `AdministracionService`/`GET /organizacion/*`, porque el Bodeguero recibe 403 y crea dependencia entre dominios.
- **Reusar capacidad `inventario`** (elegida): coincide con lectura de existencias y conjunto cerrado de capacidades. **Descartado:** ampliar catálogo de capacidades o usar `gestion_organizacional`, que abriría una dependencia/permisión distinta.
- **Mantener saldo sede compartido** (elegida): el filtro departamental localiza la sede, sin calcular consumo departamental. **Descartado:** sumar stock por departamento o duplicar saldos, expresamente fuera de alcance y contrario a Feature 011.

## 2. Archivos previstos y responsabilidad

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/inventario_schema.py` | DTOs mínimos de ámbito (sedes/departamentos con asociación) en Pydantic v2. | AC-4, AC-8, AC-9 |
| `backend/app/services/inventario_service.py` | `obtener_ambito_inventario`; ampliar `listar_existencias` con `sede_id`, alcance y filtro dentro de `condicion_stock`, INNER efectivo, totales/criticidad limitados. | AC-1…AC-4, AC-6, AC-8 |
| `backend/app/api/v1/endpoints/inventario.py` | GET ámbito, query `sede_id`, response models/status/OpenAPI, dependencias de matriz y capacidad. | AC-1, AC-3, AC-4, AC-8, AC-9 |
| `backend/app/core/permisos.py` | Una entrada aditiva Admin+Bodeguero; total 61 sin cambios en roles de operaciones previas. | AC-8 |
| `backend/app/core/capacidades.py` | Asociar GET ámbito con `inventario`. | AC-8 |
| `backend/tests/api/test_filtros_inventario_018.py` | Contratos HTTP, response codes, filtros y casos de rol/ámbito. | AC-1…AC-4, AC-6, AC-8, AC-9 |
| `backend/tests/services/test_filtros_inventario_018.py` | Consultas de opciones y regla de `condicion_stock`, agregados y productos sin stock. | AC-1…AC-4, AC-6 |
| `backend/tests/api/test_ambito_institucional.py` | Afirmar 403 departamental cross-institution en el harness SQLite donde ambas instituciones son visibles. | AC-4 |
| `backend/tests/api/test_ciclo_vida_autorizacion_014.py` | Ampliar a 61 las dos aserciones absolutas de matriz/OpenAPI, con registro explícito de ampliación Feature 014. | AC-8, AC-9 |
| `backend/tests/api/test_permisos.py` | Mantener referencia histórica de 55; agregar expectativa aditiva independiente de nueva operación. | AC-8 |
| `backend/tests/api/test_capacidades_gating_012.py` | Gating `inventario` y 403 con capacidad deshabilitada para nueva operación y existencias. | AC-8 |
| Otros tests `test_permisos_*.py`, OpenAPI y `test_gobierno_lecturas_017.py` | Mantener baselines históricos; extender comparación aditiva donde sea necesaria sin debilitar asserts. | AC-8, AC-9 |
| `frontend/src/app/shared/interfaces/index.ts` | Tipos respuesta de ámbito y filtros de existencias. | AC-1…AC-4, AC-8 |
| `frontend/src/app/core/auth/roles.ts` / `roles.spec.ts` | Helper `puedeVerFiltrosInventario` y tabla de permisos visual probada. | AC-5, AC-8, AC-9 |
| `frontend/src/app/features/inventario/services/inventario.service.ts` | Consumir GET ámbito y `GET existencias` con params; sin dependencia de `AdministracionService`. | AC-1…AC-4, AC-7 |
| `frontend/src/app/features/inventario/inventario.component.ts` / `.html` / `.spec.ts` | Signals/computed, selectores por rol, nota Bodeguero, combinación/limpieza, carga/errors/indicadores/empty states. | AC-1…AC-7, AC-9 |
| `docs/spec/stack.md` | Al cierre, documentar operación/params aditivos, matriz y gating como extensión de contrato siguiendo precedente 011/014. | AC-8, AC-9/cierre |
| `docs/spec/roadmap.md` | Al cierre, crear fila 018 en índice con estado apropiado y enlaces spec/plan/tasks. | AC-9/cierre |
| `MEMORY.md`, `spec.md`, evidencia de feature | Registrar decisiones y resultados, evidencia AC por AC y extensión explícita de Feature 014. | AC-1…AC-9/cierre |

## 3. Estrategia de pruebas

### Backend TDD — SQLite / `pytest`

- Primero tests HTTP en `test_filtros_inventario_018.py` para GET ámbito (200, roles, 401/403/409, capacidad) y existencias con `sede_id` (valid, inexistente/ajeno, Bodeguero/Solicitante, combinations, `[]`).
- Tests del servicio verifican consulta de opciones por activo/institución/sede y que los filtros de sede/departamento formen `condicion_stock` antes del `outerjoin`; products without stock are included only when there are no organizational filters.
- Usar harness SQLite para un `departamento_id` de otra institución visible y afirmar 403; no generalizar esto a PostgreSQL.
- Añadir/adaptar matriz/OpenAPI/gating primero: 61 entradas, una nueva referencia Admin+Bodeguero, anteriores no alteradas, capacidad `inventario`, 403 al apagarla. En `test_permisos.py` la base 55 queda histórica e inmutable; la nueva operación se prueba como suma aparte.
- Adaptar las dos aserciones absolutas en tests 014 de 60 a 61; dejar constancia de que la 014 se amplía explícitamente por 018.
- Ejecutar `cd backend && pytest` tras cada grupo y verificar `/openapi.json` contra matriz y el contrato publicado.

### PostgreSQL 16 gated

- Con `POSTGRES_TEST_URL`, validar esquema tenant real: opciones solo del tenant, IDs entre tenants no visibles y filtro de sede ajena/inexistente de lista con 200/`[]`; no esperar 403 de `departamento_id` de otro tenant ni de sede en esquema distinto.
- Ejecutar suites gated existentes de aislamiento de sede (`test_aislamiento_sede_011.py`) intactas: su 404 se refiere al recurso `/inventario/stock`, no al filtro de lista.
- Comprobar consulta real de joins, coincidencia con SQLite en agregados y que los tests no usen `apt_erp` como base desechable.

### Frontend

- Con `CHROME_BIN` apuntando a Edge: `npx ng test --watch=false --browsers=ChromeHeadless`; nunca `npm test` watch.
- `roles.spec.ts`: solo Admin/Bodeguero verdaderos; demás roles/null/unknown falsos.
- `inventario.component.spec.ts`: HTTP de ámbito, params `sede_id`/`departamento_id`, nota literal Bodeguero únicamente, hide sede selector Bodeguero, opciones compatibles al cambiar sede, sin sede 409, métricas para sede y agregado, sin-stock/empty/error, combinación y limpiar.
- `cd frontend && npx ng build` debe completar con presupuestos de producción.

### Integración y recorrido

- Revisar `/openapi.json`, igualdad entre operaciones públicas y matriz (61), capacidad de ámbito y 401/403/409.
- Recorrido 4200 funcional con identidad real Admin/Bodeguero/Solicitante: filtros de sede y departamento, stock/criticidad/franja coherentes, nota, cambio de filtros, limpieza y `[]`; no requiere escrituras de negocio, pero cualquier escritura real hecha durante la verificación debe contrastarse con PostgreSQL y revertirse solo con autorización.
- Para 8080: `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d frontend`; comprobar humo de vista/flujo básico y ruta Angular sobre build reconstruido.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Lookup de sede previo causa 404 o revela incorrectamente identidad cross-tenant | Incorporar `sede_id` dentro de `condicion_stock`; gated multi-schema espera 200/`[]`; no `db.get(Sede)` previo. |
| Confundir filtro de lista con endpoint de recurso | Mantener el 404 de `/inventario/stock` y documentar explícitamente 200/`[]` de `/inventario/existencias`. |
| Departamento aparenta saldo propio | Misma consulta por sede y nota literal Bodeguero; test de departamentos con sede común. |
| Sede/departamento incompatibles | `computed` de opciones dependientes y limpiar departamento en cambio de sede; assertion de que no se envía par incompatible. |
| Se cambian roles históricos al introducir ruta | Snapshot independiente + comparación aditiva, 60→61, asserts de permisos preexistentes. |
| Gating accidentalmente omitido | Probar MAPA_OPERACION_CAPACIDAD y 403 con capacidad `inventario` apagada. |
| Franja representa agregado distinto al listado | Calcularla sobre la respuesta cargada tras cada filtro organizacional y probar transición sede↔global. |
| Test gated espera 403 por ID cross-schema | 403 de recurso visible solo en SQLite harness; PostgreSQL cross-schema prueba 200/`[]`. |
| Bodeguero sin sede | Endpoint de ámbito y existencias 409; UI muestra mensaje sin fallback. |
| 8080 sirve build viejo | Rebuild frontend obligatorio antes del smoke test. |

## 5. Cobertura AC → partes

| AC | Cobertura técnica principal |
|---|---|
| AC-1 | `sede_id` en service/router + indicadores del componente; sedes válidas y sin filtros de sede/departamento. |
| AC-2 | Filtro departamental por sede compartida + nota literal condicionada a Bodeguero. |
| AC-3 | `sede_id` códigos de lista y comportamiento por rol; gated cross-schema 200/`[]`. |
| AC-4 | GET ámbito con opciones del Bodeguero, departamento fuera de alcance/institución, ausencia de sede y UI. |
| AC-5 | `puedeVerFiltrosInventario`, selectors dependientes y combinación coherente. |
| AC-6 | Outerjoin sin filtros vs. INNER efectivo con filtros; estados vacíos en template. |
| AC-7 | Query de filtros organizacionales + cliente existente; limpieza total y agregados. |
| AC-8 | Matriz 61, roles preservados, gating inventario, 403, OpenAPI y helper de visibilidad. |
| AC-9 | pytest SQLite + PostgreSQL gated, ng test/build, OpenAPI, recorridos 4200 y 8080, evidencia/cierre documental. |

## 6. Cierre

La ejecución no cambia entidades, columnas, DDL ni versión de esquema. El cierre actualiza `stack.md`, fila 018 de `roadmap.md`, `MEMORY.md` y evidencia AC en `spec.md`; las dos expectativas absolutas de 014 se registran como ampliadas a 61. No cerrar roadmap sin suites, OpenAPI y ambos recorridos conforme a AGENTS.md §8.5–§8.7.
