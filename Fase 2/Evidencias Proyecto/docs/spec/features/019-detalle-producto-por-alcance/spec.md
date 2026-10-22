# Feature 019: Detalle de producto por alcance

**Estado:** Cerrada (22/Oct/2026)  
**Release:** 2.0 — backlog posterior al Sprint 6  
**Tipo:** Consulta de inventario

## 1. Problema

La vista «Existencias» y la gestión del catálogo muestran filas resumidas, pero no ofrecen una superficie dedicada para consultar en un mismo lugar los datos del producto y su stock desglosado conforme al ámbito del usuario. Esto dificulta interpretar el total, el mínimo y la criticidad de un producto, y no permite abrir el mismo detalle desde cualquiera de las dos listas pertinentes.

## 2. Objetivo

Ofrecer un detalle de producto de solo lectura, accesible desde «Existencias» para todos los roles autorizados y desde «Gestión del catálogo» para el Administrador, que muestre los datos del catálogo y el stock por sede estrictamente limitado al ámbito del rol.

## 3. Actores

- **Administrador Institucional:** consulta cualquier producto de su institución, incluidos los inactivos y los asociados a una categoría inactiva; ve el stock de todas las sedes de su institución.
- **Bodeguero / Encargado de Suministros:** consulta únicamente productos activos asociados a categorías activas; ve exclusivamente el stock de su sede asignada.
- **Solicitante (Funcionario):** consulta únicamente productos activos asociados a categorías activas; ve exclusivamente el stock de la sede de su departamento.
- **Superadmin:** no tiene acceso a la lectura de negocio y recibe 403 por la matriz de permisos.

## 4. Alcance

### Dentro

- Vista de detalle de solo lectura con nombre, descripción, unidad de medida, mínimo, categoría y estado de categoría/producto; total, criticidad y desglose de existencia por sede. Los identificadores forman parte del contrato de API, no son campos que la vista deba presentar.
- Entrada al detalle al seleccionar el nombre del producto en la tabla «Existencias» de `/inventario`, para Administrador, Bodeguero y Solicitante.
- Entrada al detalle al seleccionar el nombre en «Gestión del catálogo», solo para Administrador, incluyendo productos inactivos y productos con categoría inactiva.
- Un endpoint dedicado para obtener los datos del producto y su existencia, con autorización, gating y ámbito por rol en servidor.
- Estados de carga, error, recurso no encontrado, reintento y resultado sin filas de stock.
- Detalle sin heredar filtros seleccionados en la lista: prevalece el ámbito completo establecido para el rol.
- Al volver, se restaura la pestaña de origen («Existencias» o «Gestión»).

### Fuera

- Movimientos, historial de stock o ciclo de vida del producto; acciones de creación, edición, activación/desactivación o cualquier otra escritura.
- Enlaces desde dashboard, tickets, ítems de ticket u otras superficies no indicadas en «Dentro».
- Cambios al contrato o a los filtros de la lista de existencias y de gestión del catálogo.
- Cambios de modelo/DDL, versión de esquema, autenticación, capacidades existentes o semántica de saldo por departamento.
- Lectura de negocio para Superadmin.

## 5. Decisiones

### D-1 — Detalle dedicado, de solo lectura

La consulta se ofrece mediante una lectura dedicada de producto y existencias. La vista no incorpora movimientos, historial, acciones de escritura ni controles del ciclo de vida.

**Por qué:** el objetivo es explicar la información resumida de las listas sin ampliar esta feature al gobierno del producto o a la auditoría de stock.

### D-2 — Dos entradas explícitas y sin enlaces adicionales

El detalle se abre desde el nombre del producto en «Existencias» para todos los roles con acceso a esa lista, y desde el nombre en «Gestión del catálogo» solo para el Administrador. La lista de gestión incluye productos inactivos; no se enlaza desde dashboard ni desde ítems de ticket.

**Por qué:** estas son las dos superficies que presentan el producto como recurso de inventario/catálogo. Limitar las entradas evita convertir referencias de otras funcionalidades en nuevas vías de navegación o acceso.

### D-3 — Ámbito efectivo del detalle completo, independiente de filtros de lista

El detalle no hereda filtros de sede o departamento seleccionados en la lista. Administrador ve todas las filas `stock_sede` de su institución; Bodeguero solo las filas de su sede asignada; Solicitante solo las filas de la sede de su departamento. Se incluyen filas de sedes inactivas, igual que en las listas actuales. Una sede asignada inactiva sigue siendo resoluble y produce respuesta 200 con esa sede; para Bodeguero o Solicitante sin sede resoluble (`None`), la consulta responde 409.

**Por qué:** el selector de la lista acota una búsqueda puntual, mientras que el detalle representa el ámbito íntegro autorizado del producto para el rol. Espejar las listas conserva su semántica actual y el estado activo de una sede no revoca una asignación ni cambia el ámbito.

### D-4 — Visibilidad de productos según rol y conservación administrativa

Administrador puede consultar cualquier producto perteneciente a su institución, aunque el producto o su categoría estén inactivos. Bodeguero y Solicitante solo pueden consultar productos activos cuya categoría también esté activa. Un producto inexistente, de otra institución o retirado para un rol operativo responde 404 con el mismo resultado observable, una vez superadas las comprobaciones anteriores de autorización y resolución del ámbito.

**Por qué:** respeta la separación de la Feature 014 entre vistas de gestión que conservan registros inactivos y consultas operativas que solo ofrecen productos vigentes; el 404 evita revelar recursos fuera del alcance.

### D-5 — Saldo desde `stock_sede` y criticidad limitada al ámbito

El total se calcula sumando exclusivamente todas las filas `stock_sede` incluidas en el ámbito del actor, sin filtrar por `Sede.activo`; por tanto una sede inactiva aparece en el desglose y sus saldos contribuyen al total y a la criticidad. `es_critico` es verdadero cuando alguna sede visible tiene saldo menor o igual al mínimo; si no hay filas visibles, se evalúa saldo cero frente al mínimo, como `_es_producto_critico`. Nunca se utilizan las filas legadas de `inventario`.

**Por qué:** desde la Feature 011 el saldo operativo tiene granularidad física por sede y `stock_sede` es su fuente única. Evaluar criticidad sobre sedes ocultas expondría o confundiría información que el usuario no puede consultar.

### D-6 — Una nueva lectura aditiva bajo la capacidad `inventario`

La operación nueva se incorpora de forma aditiva a la matriz central para Administrador, Bodeguero y Solicitante, y se somete únicamente al gating de capacidad institucional `inventario`. No se exige además `catalogo`, aunque la entrada de Gestión del catálogo esté visible para Administrador; con `catalogo` habilitada e `inventario` deshabilitada, esa lista permanece visible y la apertura del detalle recibe 403. No se cambia ninguna operación o permiso existente. Superadmin queda fuera de la operación.

**Por qué:** `requiere_capacidad` asocia una operación a una capacidad; esta lectura presenta existencias y datos de catálogo operativo y sigue la capacidad de inventario ya vigente. La gestión del ciclo de vida del catálogo continúa separada bajo `catalogo`.

### D-7 — Sin stock visible equivale a detalle válido con saldo cero

Si el producto es visible para el rol pero no existen filas de stock dentro de su ámbito, la consulta responde 200, con `sedes: []` y `stock_total: 0`; la UI distingue este resultado de un error o de un producto inexistente. En ese caso `es_critico` se calcula con saldo cero frente a `stock_minimo`, incluso si no hay sede devuelta.

**Por qué:** la ausencia de saldo en la sede del usuario no invalida el producto ni debe ocultar el catálogo. La Feature 018 establece también que los productos sin saldo pueden representarse en cero cuando no hay filtros organizacionales restrictivos.

### D-8 — Ruta y retorno a la procedencia

La ruta Angular es `path: ':productoId'` dentro de `frontend/src/app/features/inventario/inventario.routes.ts`, espejo de la ruta `:ticketId` de tickets, y el componente se denomina `producto-detalle.component`. Queda bajo la sección `/inventario`, ya protegida por `AutenticacionGuard` y `RolGuard` con `ROLES_INVENTARIO`. El enlace de retorno restaura la pestaña desde la que se llegó; si un Administrador abrió desde Gestión, vuelve a Gestión.

**Por qué:** mantener la ruta dentro del área de inventario conserva las protecciones ya definidas y el retorno contextual evita perder la ubicación de trabajo del usuario.

## 6. Reglas del flujo

1. La API evalúa las denegaciones en este orden: **401** (sesión ausente/inválida) → **403** por matriz de permisos → **403** por capacidad `inventario` → **403** por institución no resoluble (`alcance_institucional`) → **409** por sede operativa no resoluble → **404** por recurso inexistente, ajeno o retirado para rol operativo → **200**. La resolución de sede ocurre antes de buscar el producto, igual que en las lecturas existentes; así, un rol operativo sin sede resoluble recibe 409 incluso para un identificador inexistente, ajeno o retirado, sin revelar información del producto.
2. Para cualquier rol, las filas de `stock_sede` de sedes inactivas no se excluyen. Si la sede asignada al Bodeguero o la sede departamental del Solicitante está inactiva pero asignada, se resuelve normalmente y el resultado es 200 con esa sede.
3. La ruta de detalle es hija de inventario y usa `:productoId`; permanece bajo `AutenticacionGuard` + `RolGuard` con `ROLES_INVENTARIO`. Las entradas permitidas son los nombres de producto de Existencias (todos los roles autorizados) y de Gestión (solo Administrador).
4. Estados de UI diferenciados y accesibles: carga; error de red/servidor con reintento; 403 (incluida capacidad deshabilitada) con mensaje y reintento; 404; 409; error de parámetro inválido; respuesta válida sin filas (`200`, `sedes: []`) representada como vacío legible, distinto de error y 404. Los datos inactivos visibles para Administrador se identifican y no presentan controles de modificación.
5. Si `productoId` no es un entero positivo (cero, negativo o no entero), la UI no emite la petición y presenta error controlado. Si se invoca directamente el endpoint con un valor no entero, FastAPI responde 422 por coerción de tipo; cero y negativos no identifican un producto válido y el endpoint devuelve 404 después de las comprobaciones previas de alcance que correspondan.
6. «Volver al inventario» conserva la pestaña de procedencia: Existencias o Gestión; al volver desde un detalle abierto por Administrador en Gestión se activa Gestión.

## 7. Criterios de aceptación

- **AC-1 — Datos presentables del producto y stock agregado.** DADO un producto visible para el actor, CUANDO abre su detalle, ENTONCES la vista presenta nombre, descripción, unidad de medida, mínimo, categoría y estado de categoría/producto, total, criticidad y desglose por sede con nombre y saldo. El contrato incluye además los identificadores definidos en §8, pero `producto_id` e `institucion_id` no son campos que la UI deba pintar. El total equivale a la suma de las sedes devueltas.
  - **Evidencia:** `backend/tests/api/test_detalle_producto_019.py::test_detalle_responde_200_con_los_campos_exactos_del_contrato`, `::test_detalle_total_es_la_suma_de_las_sedes_devueltas`, `::test_dto_del_detalle_declara_exactamente_los_campos_del_contrato`; `frontend/src/app/features/inventario/producto-detalle.component.spec.ts` → *«anuncia la carga y después presenta el producto y el desglose por sede (AC-1)»* y *«no presenta producto_id ni institucion_id aunque formen parte del contrato (AC-1/§8)»*. **Recorrido 4200** (no test): `evidencia/README.md` §3.1 (Resma: total 50, Sede Providencia 50) y **humo 8080**: §7.3.

- **AC-2 — Ámbito institucional por rol y aislamiento tenant.** DADO un producto de una institución, CUANDO consulta el Administrador de esa institución, ENTONCES recibe existencias de todas sus sedes; si la institución no tiene sedes, recibe `sedes: []`. CUANDO consultan Bodeguero o Solicitante, ENTONCES cada cual recibe únicamente la sede asignada al Bodeguero o la sede del departamento del Solicitante. Ninguna respuesta incluye saldos de otra institución o sedes fuera del ámbito. Una sede inactiva sí se incluye; si es la sede asignada a un rol operativo, la respuesta es 200.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_administrador_ve_todas_las_sedes_de_su_institucion`, `::test_detalle_bodeguero_solo_ve_su_sede_asignada`, `::test_detalle_solicitante_solo_ve_la_sede_de_su_departamento`, `::test_detalle_incluye_las_filas_de_sedes_inactivas`, `::test_detalle_bodeguero_con_sede_inactiva_responde_200`, `::test_detalle_de_una_institucion_sin_sedes_devuelve_vacio`. **Gated PostgreSQL 16:** `backend/tests/test_detalle_producto_postgres_019.py::test_detalle_de_producto_no_mezcla_tenants_ajenos`. **Recorrido 4200** (no test): `evidencia/README.md` §3.3/§3.4 (Bodeguero y Solicitante solo Sede Maipu).

- **AC-3 — Productos activos e inactivos.** DADO un producto activo con categoría activa, ENTONCES Administrador, Bodeguero y Solicitante autorizados pueden leerlo dentro de su ámbito. DADO un producto inactivo (con categoría activa o inactiva) o asociado a categoría inactiva, ENTONCES el Administrador de su institución lo puede consultar, mientras Bodeguero y Solicitante reciben 404. Para los roles operativos, un producto ajeno/inexistente y uno retirado responden 404 indistinguible. No se exige un caso de producto activo bajo categoría inactiva, pues contradice el invariante de la Feature 014.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_producto_activo_es_visible_para_los_tres_roles`, `::test_detalle_administrador_lee_un_producto_inactivo`, `::test_detalle_administrador_lee_un_producto_de_categoria_inactiva`, `::test_detalle_operativo_no_ve_productos_ni_categorias_inactivos`, `::test_detalle_operativo_no_distingue_inexistente_ajeno_ni_retirado`, `::test_detalle_administrador_oculta_un_producto_de_otra_institucion`. UI: `producto-detalle.component.spec.ts` → *«indica el producto y la categoría inactivos sin controles de escritura (AC-3/AC-10)»*. **Recorrido 4200** (no test): `evidencia/README.md` §3.2 (Admin lee el inactivo 7) y §3.3 (Bodeguero recibe 404); **8080**: §7.3.

- **AC-4 — Precedencia de autorización y recurso inexistente/ajeno.** DADO una sesión ausente o inválida, CUANDO solicita el detalle, ENTONCES recibe 401. DADO Superadmin, ENTONCES recibe 403 por matriz antes de inspeccionar el producto. DADO una identidad admitida cuya institución no pueda resolverse, ENTONCES `alcance_institucional` responde 403 antes de mirar el producto. DADO un rol autorizado con capacidad habilitada y sede resoluble, CUANDO el identificador no corresponde a producto visible de su institución/ámbito, ENTONCES recibe 404 idéntico para inexistente y ajeno; para roles operativos también es idéntico al producto retirado.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_sin_sesion_responde_401`, `::test_detalle_superadmin_responde_403_por_matriz`, `::test_detalle_con_institucion_no_resoluble_responde_403`, `::test_detalle_operativo_no_distingue_inexistente_ajeno_ni_retirado`. **Recorrido 4200** (no test): `evidencia/README.md` §4, tabla API por rol (sin token 401; Superadmin 403 incluso con id inexistente o no entero).

- **AC-5 — Sede operativa no resoluble y precedencia sobre 404.** DADO un Bodeguero sin sede asignada (`None`) o un Solicitante cuyo departamento no tiene sede resoluble (`None`), CUANDO solicita el detalle incluso con un identificador inexistente, ajeno o retirado, ENTONCES recibe 409 antes de buscar el producto, sin sede alternativa ni ampliación de alcance. Una asignación a sede inactiva no es no resoluble y debe devolver 200 si el producto es visible.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_bodeguero_sin_sede_responde_409_antes_de_mirar_el_producto`, `::test_detalle_solicitante_sin_sede_departamental_responde_409`, `::test_detalle_bodeguero_con_sede_inactiva_responde_200`. UI: `producto-detalle.component.spec.ts` → *«presenta el 409 de sede no resoluble como alerta y permite reintentar (AC-10)»*. **Matiz de evidencia:** el 409 con sesión real no se reprodujo en 4200 por falta de credencial de la cuenta con `sede_id` nulo (`evidencia/README.md` §5.3); queda cubierto por `pytest` y por el gated de la 018.

- **AC-6 — Producto sin filas de stock dentro del ámbito.** DADO un producto visible sin filas de `stock_sede` en el ámbito del rol, CUANDO se consulta, ENTONCES responde 200 con `sedes: []`, `stock_total: 0` y criticidad evaluada con saldo cero (`0 <= stock_minimo`, según `_es_producto_critico`). Los datos de una sede fuera del ámbito no aparecen ni afectan la criticidad.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_producto_sin_stock_responde_200_vacio`, `::test_detalle_sin_stock_en_el_ambito_no_hereda_sedes_de_fuera`. UI: `producto-detalle.component.spec.ts` → *«un 200 con sedes vacías renderiza un vacío legible, distinto de error y de 404 (AC-6/D-7)»* y *«presenta el 404 como alerta y lo distingue del vacío válido (AC-6/AC-10)»*. **Recorrido 4200** (no test): `evidencia/README.md` §3.3 (Resma para Bodeguero) y §3.5 (producto 11).

- **AC-7 — Criticidad por sede visible.** DADO un producto cuya respuesta devuelve al menos una sede, CUANDO se consulta, ENTONCES `es_critico` es verdadero si alguna sede devuelta tiene `stock_actual <= stock_minimo`, y falso si ninguna lo cumple; las filas de sedes inactivas forman parte de las sedes devueltas y se evalúan. El saldo de sedes fuera del ámbito no influye.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_criticidad_solo_considera_las_sedes_devueltas`, `::test_detalle_incluye_las_filas_de_sedes_inactivas`. UI: `producto-detalle.component.spec.ts` → *«marca la criticidad cuando alguna sede visible baja del mínimo (AC-1/AC-7)»*. **Recorrido 4200** (no test): `evidencia/README.md` §3.3 (Bodeguero: Bolígrafo 150 «Disponible», Resma 0 «Crítico»).

- **AC-8 — Navegación desde las dos listas.** DADO Administrador, Bodeguero o Solicitante en la tabla «Existencias», CUANDO selecciona el nombre de un producto, ENTONCES abre su detalle siempre que la institución tenga habilitada la capacidad `inventario`. DADO Administrador en «Gestión del catálogo», CUANDO selecciona el nombre de un producto activo o inactivo, ENTONCES intenta abrir el detalle correspondiente; Bodeguero y Solicitante no obtienen esa entrada en Gestión del catálogo. Si `catalogo` está habilitada e `inventario` deshabilitada, Gestión sigue visible y la apertura del detalle obtiene 403 según AC-10.
  - **Evidencia:** `frontend/src/app/features/inventario/inventario.component.spec.ts` → *«enlaza el nombre del producto en Existencias para ${rol} sin query de pestaña»* (Administrador/Bodeguero/Solicitante), *«el Administrador enlaza el nombre en Gestión con ?tab=gestion, incluido el inactivo»*, *«${rol} no tiene enlace de Gestión ni consulta el listado de gestión»*; ruta hija en `inventario.routes.ts`. **Recorrido 4200** (no test): `evidencia/README.md` §3.1/§3.2 y **8080**: §7.3 (enlaces y deep link).

- **AC-9 — Filtros de lista y retorno a pestaña de origen.** DADO que el Administrador tiene seleccionada una sede o el Bodeguero una selección de departamento en la lista, CUANDO abre el detalle, ENTONCES la respuesta ignora esos filtros y aplica el ámbito completo del rol definido en AC-2. DADO un usuario que llega desde Existencias o Gestión, CUANDO activa «Volver al inventario», ENTONCES retorna a la pestaña de procedencia; en particular, un Administrador que llega desde Gestión vuelve a Gestión.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_ignora_los_filtros_seleccionados_en_la_lista`. UI: `producto-detalle.component.spec.ts` → *«vuelve a /inventario (Existencias) cuando no hay pestaña de origen (AC-9)»* y *«vuelve a /inventario?tab=gestion cuando el detalle se abrió desde Gestión (AC-8/AC-9)»*; `inventario.component.spec.ts` → *«al entrar con ?tab=gestion el Administrador abre directamente Gestión (AC-9)»*, *«sin ?tab=gestion el Administrador sigue entrando por Existencias»* y *«el query param no concede Gestión a un rol que no la tiene»*. **Recorrido 4200** (no test): `evidencia/README.md` §3.1 (filtro Sede Providencia no viaja) y §3.2 (vuelta a `?tab=gestion`); **8080**: §7.3.

- **AC-10 — Estados de interfaz, vacío, error y parámetro inválido.** DADO la carga del detalle, un error de red/servidor, 403 por rol/capacidad (incluida capacidad `inventario` apagada al entrar desde Gestión), 404, 409 o 422, ENTONCES la UI muestra estados diferenciables y mensajes accesibles; ofrece reintento en errores recuperables, incluidos 403, red/servidor y 409, sin generar un bucle automático. DADO `200` con `sedes: []`, ENTONCES renderiza un estado vacío legible, distinto del error y del 404. DADO `productoId` cero, negativo o no entero, ENTONCES no emite petición y muestra error controlado; una llamada directa con valor no entero obtiene 422. DADO un producto inactivo o categoría inactiva visible al Administrador, ENTONCES el estado se indica claramente y no aparecen controles de modificación.
  - **Evidencia:** `producto-detalle.component.spec.ts`: carga, *«con productoId "…" no emite petición y muestra un error controlado (AC-10/§6.5)»*, 403 de capacidad con reintento sin bucle, 404, 409, fallo de red, 500, 422, vacío y estados inactivos sin escritura. Backend: `test_detalle_producto_019.py::test_detalle_con_id_no_entero_responde_422`, `::test_detalle_con_id_cero_o_negativo_responde_404`, `::test_detalle_con_capacidad_inventario_apagada_responde_403`, `::test_detalle_con_catalogo_habilitado_e_inventario_apagado_responde_403`. **Recorrido 4200** (no test): `evidencia/README.md` §3.5 y **8080**: §7.3.

- **AC-11 — Endpoint, autorización, gating y cardinalidad.** DADO la operación nueva, ENTONCES existe exactamente una entrada aditiva en la matriz para Administrador, Bodeguero y Solicitante, y la cardinalidad sube de 61 a **62**; las 61 operaciones previas conservan sus roles y Superadmin recibe 403. La operación está gateada solo por `inventario`: si está deshabilitada, los roles concedidos reciben 403 aunque `catalogo` esté habilitada. OpenAPI publica éxito 200 y las respuestas aplicables 401, 403, 404, 409 y 422. La publicación de `openapi.json` contiene exactamente 62 operaciones protegidas por matriz; las aserciones absolutas que hoy exigen 61 en `backend/tests/api/test_ciclo_vida_autorizacion_014.py` y `backend/tests/api/test_filtros_inventario_018.py` se amplían explícitamente y con documentación a 62, igual que la 018 amplió las que exigían 60.
  - **Evidencia:** `test_detalle_producto_019.py::test_matriz_declara_una_sola_operacion_de_detalle_para_los_tres_roles`, `::test_matriz_excluye_a_superadmin_de_la_operacion_de_detalle`, `::test_capacidad_inventario_asociada_a_la_operacion_de_detalle`, `::test_matriz_tiene_exactamente_62_operaciones_tras_019`, `::test_openapi_publica_la_operacion_de_detalle`, `::test_openapi_documenta_las_respuestas_del_detalle`. Aserciones absolutas ampliadas explícitamente a 62 en `backend/tests/api/test_ciclo_vida_autorizacion_014.py` (matriz y OpenAPI, con comentario de ampliación por la 019) y en `backend/tests/api/test_filtros_inventario_018.py` (nombre histórico `test_matriz_tiene_exactamente_61_operaciones_tras_018` conservado, contenido y diagnóstico a 62). Gating con `catalogo` habilitado: `::test_detalle_con_catalogo_habilitado_e_inventario_apagado_responde_403`. **Verificación real:** `/openapi.json` publica 62 operaciones bajo `/api/v1/`, claves idénticas a `MATRIZ_PERMISOS` (62).

- **AC-12 — Sin alteración de datos ni contrato ajeno.** DADO cualquier consulta de detalle, ENTONCES no modifica producto, categoría, existencias, movimientos ni historial; no existe ruta de escritura nueva, no se altera el DDL ni la versión `014.1`, y `stock_sede` sigue siendo la única fuente consultada de saldo. Coexiste sin reemplazar `GET /inventario/productos/{producto_id}` (capacidad `catalogo`, solo producto); este detalle nuevo usa `inventario` y retorna producto más stock.
  - **Evidencia:** `test_detalle_producto_019.py::test_detalle_no_modifica_ninguna_fila_ni_consulta_el_saldo_legado`, `::test_detalle_coexiste_con_la_lectura_de_catalogo_por_producto`. **Recorrido 4200** (no test): `evidencia/README.md` §3.6 (cero `POST/PATCH/PUT/DELETE` al backend) y §6 (`stock_sede` 10/534, `producto` 11/9 y `version_esquema` `014.1` sin cambios) más **8080** §7.3.

- **AC-13 — Verificación de UI, API y aislamiento PostgreSQL.** DADO la implementación de la feature, CUANDO se verifica, ENTONCES las pruebas backend cubren roles, ámbitos, precedencia de errores, gating, vacíos, sedes inactivas y criticidad; un test gated contra PostgreSQL 16 verifica el aislamiento por tenant exigido en AC-2; las pruebas Angular cubren servicio, render, navegación, retorno a pestaña de origen, estados y reintento; `/openapi.json` refleja el contrato y cardinalidad; y se realiza recorrido funcional en 4200 y recorrido de humo en 8080 con la imagen frontend reconstruida.
  - **Evidencia:** **Backend:** `backend/tests/api/test_detalle_producto_019.py` (37 pruebas) + **gated PostgreSQL 16** `backend/tests/test_detalle_producto_postgres_019.py::test_detalle_de_producto_no_mezcla_tenants_ajenos`. **Frontend:** `producto-detalle.component.spec.ts`, `inventario.component.spec.ts` y `services/inventario.service.spec.ts`. **Suites:** `pytest` SQLite **1391 passed / 77 skipped / 0 failed**; gated `POSTGRES_TEST_URL` **1468 passed / 0 skipped / 0 failed** (`apt_erp` intacta en `014.1`, 22 tablas, 4 tenants); `ng test` **446 SUCCESS / 0 FAILED**; `ng build` limpio; `/openapi.json` 62 operaciones. **Recorrido 4200** y **humo 8080** con imagen reconstruida (bundle `main-D6GKPODP.js` y chunk lazy `chunk-4MWF2NDY.js`) en `evidencia/README.md` §3–§7 (16 capturas).

## 8. Contrato de la API

### `GET /api/v1/inventario/existencias/{producto_id}`

- **Éxito:** 200 con un objeto de detalle de producto y stock por sede.
- **Respuesta:** `ProductoDetalleRespuesta`, con campos `producto_id`, `nombre`, `descripcion`, `unidad_medida`, `stock_minimo`, `categoria_id`, `categoria_nombre`, `categoria_activa`, `activo`, `institucion_id`, `stock_total`, `es_critico` y `sedes`. Cada elemento de `sedes` usa la forma de `SedeExistenciaRespuesta` con identificador, nombre de sede y existencia. El orden de `sedes` es determinista por `(sede_nombre, sede_id)` ascendente.
- **Presentación:** la vista muestra los datos descritos en AC-1; `producto_id` e `institucion_id` se mantienen en el contrato, pero no se presentan como campos de UI.
- **Roles de matriz:** Administrador, Bodeguero y Solicitante. Superadmin: 403.
- **Gating:** capacidad institucional `inventario`; deshabilitada: 403, también al abrir desde Gestión aunque `catalogo` esté habilitada. No se requiere `catalogo` para esta lectura.
- **Ámbito:** Administrador: todas las filas `stock_sede` de su institución. Bodeguero: su sede asignada. Solicitante: sede de su departamento. El cliente no elige ni amplía institución o sede. No se filtra por `Sede.activo`: las filas de sedes inactivas aparecen y suman. Una sede asignada inactiva se resuelve y produce 200.
- **Productos:** Administrador puede leer activos e inactivos, incluso con categoría inactiva; Bodeguero y Solicitante solo producto activo con categoría activa.
- **Precedencia de respuestas:** 401 → 403 por matriz → 403 por capacidad → 403 por institución no resoluble (`alcance_institucional`) → 409 por sede operativa no resoluble → 404 por recurso → 200. El alcance institucional y la sede se resuelven antes de buscar el producto; un rol operativo sin sede resoluble obtiene 409 también ante id inexistente, ajeno o retirado. El 409 no revela información del producto. `dependencies.respuestas_de_autorizacion()` documenta 401/403; `dependencies.respuesta_recurso_oculto()` documenta 404 y `dependencies.respuesta_conflicto()` documenta 409.
- **Errores de identificador:** un `producto_id` no entero enviado directamente recibe 422 por coerción de tipo. La UI no emite petición si `productoId` no es entero positivo. Cero o negativo no identifican un producto y, tras la precedencia de autorización/ámbito aplicable, responden 404.
- **Recurso oculto:** 404 para producto inexistente, ajeno o, en roles operativos, retirado; el detalle no distingue esos casos.
- **Sin existencias en el ámbito:** 200 con `sedes: []`, total cero y criticidad calculada con saldo cero frente al mínimo.
- **Solo lectura:** la operación no altera estado ni publica acciones de mutación.

### Navegación Angular

La ruta de detalle es `path: ':productoId'` dentro de `frontend/src/app/features/inventario/inventario.routes.ts`, espejo de `tickets.routes.ts` con `:ticketId`; el componente es `producto-detalle.component`. Está bajo `/inventario`, protegido por `AutenticacionGuard` y `RolGuard` con `ROLES_INVENTARIO`. El enlace de vuelta restaura la pestaña de entrada, Existencias o Gestión.

## 9. Restricciones, riesgos y premisas

- `stock_sede` es la fuente única de existencia operativa; las filas legadas de `inventario` no se leen ni suman.
- La criticidad se determina por saldo de cada sede visible (`stock_actual <= stock_minimo`), incluyendo filas de sedes inactivas; nunca por saldo agregado de sedes fuera del ámbito.
- El ámbito institucional y las asociaciones de sede se resuelven en servidor; la navegación Angular no constituye autorización. La precedencia de alcance puede devolver 409/403 antes de determinar si el producto existe.
- La nueva lectura usa `inventario`, no `catalogo`; si `catalogo` está habilitada y `inventario` no, la lista de Gestión puede estar visible, pero abrir el detalle responde 403. Coexiste con `GET /inventario/productos/{producto_id}`, capacidad `catalogo`, que devuelve solo el producto; el nuevo detalle usa `inventario` y devuelve producto más stock. El reparto de capacidades queda registrado en `stack.md` al cierre.
- No hay cambios de DDL, entidades, semillas ni versión de esquema: se mantiene `014.1`.
- Clerk continúa como única autoridad de autenticación; no se incorporan dependencias.
- La interfaz es solo lectura, usa los patrones visuales y de accesibilidad del detalle de ticket, y no añade acciones de ciclo de vida.
- Pruebas backend: `pytest`; pruebas frontend: `ng test`. La publicación del contrato se verifica en `/openapi.json`; el cierre exige recorridos en ambos puertos según `AGENTS.md`.

## 10. Estado y evidencia de verificación

Todos los AC quedaron **verificados** al cierre (22/Oct/2026). El detalle por prueba está en la
línea *Evidencia* de cada AC en §7; los archivos de prueba son
`backend/tests/api/test_detalle_producto_019.py` (37 pruebas),
`backend/tests/test_detalle_producto_postgres_019.py` (1 gated PostgreSQL 16),
`frontend/src/app/features/inventario/producto-detalle.component.spec.ts`,
`frontend/src/app/features/inventario/inventario.component.spec.ts` (enlaces y restauración de
pestaña) y `frontend/src/app/features/inventario/services/inventario.service.spec.ts`.

| Criterio | Estado | Alcance de la evidencia |
|---|---|---|
| AC-1 | Verificado | Contrato exacto, suma de sedes, orden y presentación sin IDs; recorrido 4200 y humo 8080. |
| AC-2 | Verificado | Ámbito por rol, sedes inactivas, institución sin sedes y aislamiento tenant gated PG16. |
| AC-3 | Verificado | Visibilidad activo/inactivo por rol y 404 indistinguible para operativos. |
| AC-4 | Verificado | Precedencia 401 → 403 matriz → 403 capacidad → 403 institución → 404. |
| AC-5 | Verificado | 409 de sede no resoluble antes del producto; sede inactiva asignada responde 200. |
| AC-6 | Verificado | 200 con `sedes: []`, total cero y criticidad con saldo cero. |
| AC-7 | Verificado | Criticidad solo sobre sedes devueltas, incluidas inactivas. |
| AC-8 | Verificado | Enlaces en Existencias (todos los roles) y en Gestión (solo Administrador). |
| AC-9 | Verificado | Detalle ignora filtros de lista y vuelve a la pestaña de origen (`?tab=gestion`). |
| AC-10 | Verificado | Estados de UI, reintento sin bucle, parámetro inválido y datos inactivos sin controles. |
| AC-11 | Verificado | Matriz/OpenAPI 61 → 62, gating `inventario` y respuestas 200/401/403/404/409/422. |
| AC-12 | Verificado | Solo lectura, `stock_sede` como fuente única, coexistencia con `/productos/{id}` y `014.1`. |
| AC-13 | Verificado | Suites completas, gated PG16, `ng test`, `ng build`, OpenAPI, 4200 y 8080 reconstruido. |

**Cierre:** `pytest` SQLite 1391 passed / 77 skipped / 0 failed; gated PostgreSQL 16 1468 passed /
0 skipped / 0 failed; `ng test` 446 SUCCESS / 0 FAILED; `ng build` limpio; `/openapi.json` con 62
operaciones; recorrido funcional en 4200 y humo en 8080 con la imagen reconstruida. La evidencia
reproducible, con capturas y datos QA de contraste, está en
[`evidencia/README.md`](evidencia/README.md).
