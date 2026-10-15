# Feature 009 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario y el reviewer (AC-1…AC-16, D-1…D-7). Este plan define la implementación técnica y sus evidencias; no amplía ni altera requisitos. No se añaden dependencias.

## 1. Enfoque técnico

### API analítica y elección de router

Crear un router de dominio `dashboard` y exponer **una sola lectura consolidada**:

| Método y ruta | Query params | Éxito | Autorización |
|---|---|---|---|
| `GET /api/v1/dashboard/` | Ninguno | `200`, `DashboardAnaliticoRespuesta` | Todos los roles para KPI/alertas; movimientos incluidos únicamente para Superadmin, Administrador y Bodeguero. Solicitante obtiene su dashboard permitido sin actividad de movimientos. |

El router se agrega al router v1 protegido por `get_current_user` en `api.py`. No se altera `/inventario/movimientos`: la matriz vigente conserva su 403 para Solicitante. Se recomienda separar el dashboard de `/inventario` porque el contrato consolida métricas de inventario, tickets y departamentos; ubicarlo bajo inventario sugeriría pertenencia funcional exclusiva y mezclaría la lectura analítica con los endpoints operativos. La consolidación evita una cascada de peticiones independientes y da una sola carga coherente al dashboard.

El contrato es único para todos los roles permitidos. Para Solicitante, `actividad_movimientos` se devuelve como lista vacía, distinguible como sección no disponible mediante un booleano `actividad_disponible: false`; para los otros roles es `true` aun si la lista está vacía. No se hace una llamada HTTP a `GET /inventario/movimientos` desde el dashboard. El permiso de `GET /api/v1/dashboard/` se declara explícitamente para los cuatro roles; las lecturas internas por rol se componen como read model y no representan un permiso nuevo sobre otros endpoints.

**Alternativa descartada:** pedir por separado inventario, tickets, departamentos y movimientos desde Angular. Eso incrementaría el número de viajes, permitiría estados parciales e incoherencias temporales entre KPI y alertas y haría que el cliente replicara las reglas de ámbito. También se descarta alojar la consolidación en `/inventario`, por no representar tickets y departamentos como responsabilidad exclusiva de inventario.

### Matriz central de permisos y ámbito

Añadir a `MATRIZ_PERMISOS` exactamente `("GET", "/api/v1/dashboard/")` con el conjunto `_TODOS` (Superadmin, Administrador, Bodeguero y Solicitante). No agregar una entrada para movimientos ni cambiar la existente: `GET /api/v1/inventario/movimientos` sigue permitido solo a `_INVENTARIO_Y_TICKETS` (Superadmin, Administrador, Bodeguero). La superficie de la ruta dashboard no concede a Solicitante acceso general al historial de movimientos.

El servicio resuelve el ámbito una sola vez con `ambito_service.alcance_institucional(db, identidad)`; `None` significa Superadmin global únicamente. Para los roles limitados, un ámbito irresoluble conserva 403. Reutilizar `filtrar_por_institucion` o aplicar equivalentes ORM/Core en cada lectura para productos/inventario/departamentos/movimientos. La institución se deriva de Departamento, y no se acepta un ámbito desde query/body/header. Para tickets se reutiliza la regla existente: Solicitante se restringe a sus `usuario_id`; Administrador/Bodeguero a tickets de su institución; Superadmin global.

La actividad se añade al read model consolidado solo tras identificar la capacidad de rol, con la regla exacta derivada de `permisos.nombre_rol_de(identidad)`: Solicitante no recibe filas ni provoca una consulta de movimientos; los otros tres roles las reciben filtradas por ámbito. La dependencia de ruta autentica y autoriza el acceso a la lectura consolidada; el control explícito en el servicio gobierna qué sección de datos se ensambla, sin sustituir la política central.

**Alternativa descartada:** autorizar los cuatro roles en el endpoint de historial existente o descargar el historial y ocultarlo en Angular. La primera modifica un permiso previo expresamente conservado; la segunda expone datos a quien puede invocar la API directamente.

### Servicio de dominio y composición de datos

Crear `dashboard_service.py` para `obtener_dashboard_analitico(db, identidad)`, que calcula el ámbito y ensambla un DTO. Mantener lógica SQL, agregación y autorización de filas en servicio; el router solo valida identidad/DB, delega y devuelve el resultado.

El servicio reutiliza `inventario_service.es_stock_critico(stock_actual, stock_minimo)` para obtener la lista de filas críticas. Esta función existente acepta valores de una fila, que es exactamente la unidad de criticidad de D-1; no reutilizar `listar_existencias(solo_criticos=True)` porque esa respuesta calcula criticidad sobre el agregado por producto y no corresponde al criterio de Feature 009. Extraer, si hace falta, un query/read helper puro en el servicio de inventario o dashboard que exponga las filas con `inventario_id`, producto, departamento, institución, `stock_actual` y `stock_minimo`, y use el predicado común.

Para mantener consistencia entre KPI de alertas y listado, formar una única lista `alertas` y derivar `total_alertas = len(alertas)`. El KPI de unidades es la suma global o institucional de `Inventario.stock_actual`; Superadmin obtiene **un solo escalar global agregado**. La observación del reviewer queda resuelta así: la “no fusión” de AC-7 aplica a filas/listados con identidad propia —alertas y actividad, cada una atribuida a institución— y no al escalar del KPI «Unidades en Stock», que por D-4 #1 es una suma única global para Superadmin. Departamentos se cuentan por registros/PK, sin depender de filas de inventario. Para todos los KPI sin filas el resultado es cero.

Los tickets activos se cuentan con join a `EstadoTicket` y condición `EstadoTicket.nombre != "Cerrado"` (comparación literal sensible a mayúsculas y sin normalización). Aplicar el alcance vigente por rol: global para Superadmin; join ticket→usuario→departamento e institución para Administrador/Bodeguero; `Ticket.usuario_id == identidad.usuario.usuario_id` para Solicitante. No exponer asunto, usuario ni detalle de tickets en el DTO de dashboard.

Los movimientos autorizados se consultan con la misma proyección enriquecida que `listar_movimientos`: `movimiento_inventario → inventario → producto + departamento + institución`, orden `fecha_movimiento DESC, movimiento_id DESC`, y un límite fijo de 10 filas. El límite solo afecta a la actividad reciente, no al KPI ni al historial existente. La institución global y cada respuesta se proyectan explícitamente, manteniendo productos homónimos separados por su `producto_id` e institución.

No cambiar `listar_movimientos()` ni su respuesta pública: permanece sin paginación y con el contrato de historial intacto. No se crea entidad, tabla, columna ni migración.

**Alternativa descartada:** calcular los KPI y criticos en Angular a partir de `/inventario/existencias`, `/stock`, `/tickets/` y movimientos. Los clientes no son frontera de ámbito, no poseen un conjunto de datos común suficiente (departamentos sin inventario) y podrían aplicar la regla de stock equivocado. También se descarta una consulta crítica por producto agregado porque ocultaría departamentos deficitarios que compensan stock de otra ubicación.

### Contrato DTO consolidado

Agregar schemas Pydantic v2 en `dashboard_schema.py`, sin `from_attributes` para las proyecciones multi-tabla/agregadas. Todos los campos de la API están en `snake_case`; los campos nullable expresan ausencia real de atribución solo si el dato no puede resolverse (caso legado inconsistente, que debe tratarse conforme al ámbito/errores y no usarse para degradar a global).

Contrato de éxito propuesto:

```text
DashboardAnaliticoRespuesta
  kpi: DashboardKpiRespuesta
    unidades_en_stock: int
    tickets_activos: int
    total_departamentos: int
    total_alertas: int
  alertas: list[AlertaStockRespuesta]
    inventario_id: int
    producto_id: int
    producto_nombre: str
    departamento_id: int
    departamento_nombre: str
    stock_actual: int
    stock_minimo: int
    institucion_id: str | null
    institucion_nombre: str | null
  actividad_disponible: bool
  actividad_movimientos: list[MovimientoDashboardRespuesta]
    movimiento_id: int
    tipo_movimiento: str
    cantidad: int
    fecha_movimiento: datetime
    producto_id: int
    producto_nombre: str
    departamento_id: int
    departamento_nombre: str
    ubicacion: str | null
    institucion_id: str | null
    institucion_nombre: str | null
```

Para roles limitados, toda fila de alerta/movimiento pertenece a la institución del actor; `institucion_id` puede acompañar la respuesta por consistencia, pero la UI solo requiere distinguir atribución global. Para Superadmin los dos campos institucionales de cada fila son obligatorios en términos de resultado y llevan el ID y nombre legible; no agrupar alertas por nombre ni combinar movimientos de productos homónimos. El escalar `kpi.unidades_en_stock` de Superadmin sí es la suma global única, no una serie por institución. Tickets y departamentos son métricas agregadas y no se exponen como registros de detalle en este contrato.

La actividad del Solicitante es `actividad_disponible: false` con `actividad_movimientos: []`. Para roles autorizados es `true`, incluso cuando no haya movimientos, en cuyo caso la lista vacía significa ausencia de registros. Este valor de presentación no otorga autorización sobre `GET /inventario/movimientos`.

Documentar en OpenAPI `200`, `401` y `403`; el endpoint no recibe query params. El 403 incluye rol no autorizado si la matriz se restringe más adelante y ámbito irresoluble para rol limitado. Mantener `status_code` explícito y una descripción que documente el rol Solicitante sin actividad, la regla crítica por fila, el desempate y el límite fijo de actividad.

### Frontend Angular

Crear `DashboardService` de feature con `obtenerDashboard(): Observable<DashboardAnalitico>` consultando solamente `GET ${URL_API}/dashboard/`. Los tipos TypeScript 1:1 con Pydantic se incorporan a `shared/interfaces/index.ts`, porque los DTO compartidos representan contratos de API y ya viven en ese índice. No extender AutenticacionService ni reutilizar servicios de inventario/tickets para disparar más llamadas.

Modificar `dashboard.component.ts` y su template. El componente carga una vez en su inicialización, guarda estado remoto en `signal()` (`cargando`, `datos`, `mensajeError`) y expone valores derivados con `computed()` cuando faciliten la plantilla. Seguir el patrón de estado y mensajes recuperables de InventarioComponent/TicketsComponent. Incluir acción de reintento si el error reemplaza los datos cargados. No usar datos de muestra en carga, error ni resultado vacío.

Reemplazar las cuatro tarjetas por la etiqueta exacta «Unidades en Stock», «Tickets Activos», «Departamentos» y «Alertas de Stock» con datos del DTO. Retirar por completo la tarjeta placeholder «Estado de Sedes Descentralizadas». Añadir el único listado de alertas actual y la sección Actividad Reciente con filas de movimientos. Si `actividad_disponible` es falso, no pintar la sección de actividad ni mostrar mensaje que sugiera que Solicitante debería ver historial; el servidor sigue imponiendo 403 al endpoint de movimientos existente. Si es verdadera y la lista es vacía, presentar un vacío explícito.

Usar clases Tailwind y markup accesible con estados visibles (texto/`role="alert"` para errores; encabezados y etiquetas con nombre). No introducir componente compartido nuevo: cada sección es específica del dashboard y por ahora tiene un único consumidor. La ruta y guard del dashboard permanecen con acceso a los cuatro roles.

**Alternativa descartada:** esconder actividad exclusivamente en frontend por `rol` mientras se llama al endpoint histórico. Además de romper la pantalla por el 403 esperado, produciría tráfico denegado y ocultaría una violación de contrato en vez de respetar la matriz.

## 2. Archivos previstos y responsabilidad

Los nombres de archivo son técnicos y no alteran el alcance funcional aprobado.

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/dashboard_schema.py` (nuevo) | DTOs Pydantic v2 del KPI, alertas, movimientos y respuesta consolidada, sin entidad ORM fingida para agregados. | AC-1…AC-7, AC-13 |
| `backend/app/services/dashboard_service.py` (nuevo) | Componer KPI, lista única de críticos, actividades autorizadas, filtros de ámbito y atribución global; aplicar límite de actividad. | AC-1…AC-12 |
| `backend/app/api/v1/endpoints/dashboard.py` (nuevo) | Ruta GET del dashboard, dependencia por operación, response model, status/documentación OpenAPI y delegación. | AC-8…AC-14 |
| `backend/app/api/v1/api.py` | Registrar el router analítico en el router de negocio protegido. | AC-13 |
| `backend/app/core/permisos.py` | Añadir exclusivamente `GET /api/v1/dashboard/` para `_TODOS`; no alterar `GET /inventario/movimientos`. | AC-8…AC-11, AC-14 |
| `backend/app/services/ambito_service.py` | Preferir reutilización directa de `alcance_institucional` y helpers existentes; modificar solo si una abstracción general necesaria se demuestra compartible y no altera las reglas 007/008. | AC-8, AC-11 |
| `backend/app/services/inventario_service.py` | Reutilizar `es_stock_critico`; solo extraer helper de read model si evita duplicar una consulta/filtro y mantiene intactos contratos existentes. | AC-4, AC-5, AC-12 |
| `backend/tests/api/test_dashboard_analitico.py` (nuevo) | Contrato HTTP, KPI, alertas, actividad, ámbito por rol, 403 y prueba de no persistencia de alertas. | AC-1…AC-14 |
| `backend/tests/api/test_permisos_endpoints.py` | Actualizar matriz de referencia independiente, operación de éxito/denegación y OpenAPI para total de rutas actualizado. | AC-13, AC-14 |
| `backend/tests/conftest.py` (solo si hace falta) | Extender fixtures reutilizables de instituciones, roles, departamentos y tickets sin cambiar datos/base compartidos de pruebas no relacionadas. | AC-1…AC-12 |
| `frontend/src/app/shared/interfaces/index.ts` | Interfaces TypeScript espejo del contrato Pydantic. | AC-1…AC-8, AC-13 |
| `frontend/src/app/features/dashboard/services/dashboard.service.ts` (nuevo) | Una petición HTTP tipada al endpoint consolidado. | AC-13, AC-15 |
| `frontend/src/app/features/dashboard/dashboard.component.ts` | Carga, señales de estado y presentación derivada; no decide ámbito ni autorización. | AC-1…AC-10, AC-15 |
| `frontend/src/app/features/dashboard/dashboard.component.html` | KPI reales, alertas, actividad autorizada, estados vacíos/carga/error y retiro de placeholder. | AC-1…AC-10, AC-15 |
| `frontend/src/app/features/dashboard/dashboard.component.spec.ts` (nuevo) | Contrato visual, cuatro tarjetas, retiro placeholder, rol Solicitante, carga/vacío/error y atribución. | AC-1…AC-10, AC-15 |
| `frontend/src/app/features/dashboard/services/dashboard.service.spec.ts` (nuevo) | URL/método/tipo, una sola lectura, respuesta consolidada y ausencia de ámbito enviado por cliente. | AC-8, AC-13, AC-15 |
| `docs/spec/features/009-dashboard-analitico-alertas/spec.md` | En cierre, consignar evidencia AC por AC sin modificar requisitos aprobados. | AC-1…AC-16 |
| `docs/spec/features/009-dashboard-analitico-alertas/tasks.md`, `MEMORY.md`, `docs/spec/roadmap.md` | Marcar tareas/evidencias, memoria y estado del roadmap únicamente con cierre verificado. | AC-16 |

Si durante implementación aparece que hacen falta cambios de modelo, migración, una tabla de alerta o una modificación de la semántica aprobada, detenerse: no forman parte de la spec ni están cubiertos por el plan. No instalar paquetes.

## 3. Estrategia de pruebas e integración

### Backend — pytest

1. **Servicio y read model vía HTTP:** probar solo el seam HTTP (`TestClient`), siguiendo el patrón de `tests/api/`; el fixture SQL puede preparar filas, pero los resultados se asertan a través del endpoint. Verificar nombres/campos del DTO y lista vacía donde corresponda.
2. **KPI:** casos con suma de unidades, stock cero, tickets en estados no cerrados/cerrado literal, departamentos sin inventario, IDs distintos con nombres homónimos y ámbito global/institucional. Asegurar que el conteo de departamento incluye solo la PK y cada PK una vez.
3. **Críticos y log único:** stock `M-1`, `M`, `M+1` y mínimo cero; múltiples departamentos para mismo producto; agregar filas y comprobar que KPI equivale exactamente a `len(alertas)`. Mutar stock en una operación real de movimiento y consultar antes/después; comprobar que no se crea tabla/fila de alerta y que la cantidad de registros de movimiento solo cambia por el movimiento esperado.
4. **Roles y aislamiento:** cuatro roles por HTTP. Solicitante puede consultar el dashboard, obtiene KPI/alertas propios del ámbito y `actividad_disponible=false`, lista vacía; petición directa a `/inventario/movimientos` sigue 403. Superadmin recibe actividad/alertas de ambas instituciones con `institucion_id` y nombre; sus agregados no mezclan objetos por homónimo y el KPI de unidades es un escalar global único. Administrador/Bodeguero reciben solo su institución. Para rol limitado sin departamento/ámbito resoluble, dashboard responde 403, nunca global.
5. **Matriz y auth:** extender prueba de inventario de operaciones, contrastando router real con matriz de referencia independiente. Comprobar autorización 200/403 por rol y 401 de sesión ausente/inválida; el movimiento conserva su conjunto vigente de roles. Revisar `/openapi.json`: ruta, `response_model`, `200`, `401`, `403`, ausencia de parámetros query y documentación de actividad/no permiso Solicitante.
6. **Suite completa:** ejecutar `cd backend && pytest`. Suite ordinaria corre SQLite en memoria y no requiere `db`; cualquier caso que dependa de PostgreSQL debe quedar explícitamente gated con `POSTGRES_TEST_URL`, pero esta feature no modifica constraints ni necesita una prueba PostgreSQL obligatoria.

### Frontend — ng test

1. `DashboardService`: `HttpTestingController` comprueba una sola petición `GET /api/v1/dashboard/`, sin `institucion_id`, encabezado de ámbito ni body; respuesta tipada se entrega sin recomputar agregados.
2. `DashboardComponent`: montar mediante respuestas controladas y verificar valores/títulos exactos de cuatro KPI, lista de alertas, movimientos y atribución global. Confirmar que no aparece «Estado de Sedes Descentralizadas» ni datos hardcodeados.
3. Solicitante: doble de `AutenticacionService.identidad` con rol Solicitante y DTO con `actividad_disponible=false`; sección de actividad no se renderiza y no hay una petición a `/inventario/movimientos`.
4. Estados: durante pendiente se ve carga; respuesta vacía muestra ceros/listas vacías; fallo presenta alerta y permite reintento sin restaurar cifras ficticias.
5. Ejecutar con Edge mediante `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"` y `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`. No usar `npm test` a secas.

### Verificación de contrato y recorridos

- Consultar `/openapi.json` después de añadir ruta y revisar el diff/inventario de `MATRIZ_PERMISOS`; verificar en particular que no cambie el conjunto de lectura de `/inventario/movimientos`.
- En 4200, iniciar sesión con Superadmin, roles institucionales y Solicitante: comprobar números contra datos consultados, ámbito, homónimos atribuidos, críticos a nivel departamento y ausencia de actividad para Solicitante.
- Reconstruir y levantar frontend para 8080 (`docker compose -f docker-compose.yml build frontend` y luego `docker compose -f docker-compose.yml up -d frontend`) y hacer humo de la UI actualizada y flujo de carga básico. El backend mantiene su recarga por volumen.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Agregados y joins del dashboard elevan latencia a medida que crecen tickets/stock | Un contrato consolidado, proyecciones de columnas y filtros aplicados en SQL; limitar actividad a 10; verificar que métricas no descarguen colecciones completas a Python. Medir/inspeccionar consultas con fixture representativa. No introducir cache que vuelva obsoletas las alertas actuales. |
| Agregados Superadmin fusionan homónimos o se confunden con atribución de filas | La suma global de unidades es deliberadamente un escalar; filas de alerta y actividad incluyen IDs/nombres institucionales. Cubrir ambas semánticas en pytest con dos instituciones y homónimos. |
| KPI departamentos derivado de inventario omite departamentos vacíos | Contar `Departamento` directamente por PK dentro del ámbito, no agrupar las filas de inventario. Incluir departamento sin inventario en el fixture. |
| Stock crítico agregado difiere de criticidad por departamento | No reutilizar `ProductoExistencia.es_critico`/`solo_criticos` como definición de alertas; invocar predicado puro existente por cada fila de inventario. Probar igualdad y mínimos cero. |
| Solicitante recibe 403 por historial desde el dashboard | Endpoint consolidado omite lectura de movimientos para Solicitante y expresa `actividad_disponible=false`; template no muestra sección. Endpoint histórico sigue 403 y tiene test de regresión. |
| Cambio de matriz no coincide con operaciones expuestas o accidentalmente abre historial a Solicitante | Añadir solo el GET dashboard con `_TODOS`; mantener la matriz independiente de prueba y aserción exacta de rutas. Verificar roles efectivos sobre endpoint histórico sin cambios. |
| El nombre de estado o ID elegido cambia la cuenta de tickets cerrados | Comparar literal `EstadoTicket.nombre == "Cerrado"` para exclusión y probar variantes que no son exactamente ese nombre; no codificar `estado_id`. |
| Imagen Docker 8080 conserva build anterior o falla la ruta Angular | Cierre requiere reconstruir frontend y recrear contenedor antes del humo; registrar evidencia del build y vista servido. |
| La atribución institucional es nula por joins incompletos | joins internos conforme a FKs; tests Superadmin con dos instituciones afirman `institucion_id` y nombre por cada fila. Ámbito irresoluble de usuario limitado debe responder 403 en vez de emitir resultados globales. |
| Los estados de datos parciales vuelven a cifras ficticias | El componente consume el resultado consolidado como unidad; error vacía/retira datos anteriores y muestra error recuperable, nunca fallback de muestra. |

## 5. Cobertura de AC y evidencia esperada

| AC | Partes principales | Evidencia requerida al cierre |
|---|---|---|
| AC-1 | `dashboard_service`, esquema KPI, template | Pytest de suma dentro/fuera de ámbito y cero sin filas; test Angular verifica etiqueta exacta «Unidades en Stock» y valor. |
| AC-2 | conteo de tickets en `dashboard_service` | Pytest con estados varios, nombre literal «Cerrado», otro casing/nombre y alcance propio de Solicitante. |
| AC-3 | consulta directa de departamentos | Pytest incluye departamentos sin inventario, PK distintas con nombre homónimo, por institución y global. |
| AC-4 | query de filas críticas y predicado `es_stock_critico` | Pytest por fila en M-1/M/M+1, compensación de stock entre departamentos y producto sin inventario. |
| AC-5 | lista única `alertas` y KPI derivado `len(alertas)` | Pytest constata identidad del conjunto, el conteo de filas y la desaparición tras cruzar de vuelta el umbral. |
| AC-6 | proyección/orden de movimientos | Pytest por fecha DESC/id DESC para roles autorizados; no hay eventos ficticios/tickets y Solicitante directo recibe 403. |
| AC-7 | atribución global en filas y suma KPI global | Pytest dos instituciones y homónimos: cada alerta/movimiento tiene institución; agrega único escalar `unidades_en_stock`, sin comparación/ranking. |
| AC-8 | filtros de servicio y rol | Pytest por Administrador/Bodeguero/Solicitante, parámetros de ámbito adversariales; ninguna fila de B en respuestas limitadas. |
| AC-9 | filtro tickets según rol | Pytest con tickets de distintos usuarios en misma institución y globales; no se incluyen propios ajenos del Solicitante. |
| AC-10 | actividad consolidada y template por rol | Pytest respuesta Solicitud con actividad vacía/no disponible + 403 directo a historial; test Angular no renderiza actividad ni hace GET histórico. |
| AC-11 | resolución de ámbito | Pytest con rol limitado sin institución/departamento válido obtiene 403, sin contenido global. |
| AC-12 | lectura derivada y servicio de stock existente | Pytest mueve stock a ambos lados del mínimo, vuelve a consultar; no persiste alertas y auditoría cambia solo por movimiento real. |
| AC-13 | sin DDL/modelos; respuesta consolidada | Revisión de archivos/modelos/DDL y prueba OpenAPI de DTO exacto; no hay tabla/columna/migración nueva. |
| AC-14 | router, permisos, schemas y OpenAPI | Comparación de rutas API frente a matriz independiente, parametrización 401/403/200 y OpenAPI `GET /dashboard/`; `GET /inventario/movimientos` no cambia permisos. |
| AC-15 | componente, template, service y pruebas | Test frontend confirma carga, respuesta real simulada, vacío, error/reintento, etiqueta y placeholder ausente; recorrido visual en 4200/8080. |
| AC-16 | cierre | Todas las tareas y AC con evidencia, pytest/ng test verdes, contrato OpenAPI/matriz, recorridos 4200/8080, MEMORY y grep documental; roadmap solo tras satisfacer AGENTS §8.5. |

## 6. Cierre de feature

El plan no marca la feature como cerrada ni la fila de roadmap. Tras completar tareas:

1. `pytest` y frontend `ng test` en verde (Edge vía `CHROME_BIN`, `--watch=false --browsers=ChromeHeadless`).
2. AC en spec con evidencia, incluyendo contrato `/openapi.json`, lista de rutas contra matriz y el 403 vigente de Solicitante en actividad de movimientos.
3. Recorrido funcional en **4200** con datos reales y ámbitos Superadmin/limitados/Solicitante.
4. Ejecutar `docker compose -f docker-compose.yml build frontend`, después `docker compose -f docker-compose.yml up -d frontend`, y recorrer humo en **8080** sobre la imagen nueva.
5. Actualizar `MEMORY.md` al cerrar, y ejecutar grep de coherencia de rutas/estado según `AGENTS.md` §8.7.
6. Marcar roadmap `[x]` solo una vez satisfechas todas las verificaciones de `AGENTS.md` §8.5; la validación de cierre corresponde al flujo coordinador/reviewer.
