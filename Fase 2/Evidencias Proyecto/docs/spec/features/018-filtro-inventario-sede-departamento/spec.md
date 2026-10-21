# Feature 018: Filtros de existencias por sede y departamento

**Estado:** Cerrada (21/Oct/2026)  
**Release:** 2.0 — backlog posterior al Sprint 6  
**Tipo:** Mejora de consulta de inventario

## 1. Problema

La pestaña «Existencias» de `/inventario` muestra el catálogo y el stock agregado del ámbito permitido, pero no permite filtrar por sede. El Administrador Institucional necesita acotar la lectura a una sede; el Bodeguero necesita seleccionar un departamento de su sede para confirmar/acotar la vista a esa ubicación física.

El stock operativo tiene granularidad por sede, nunca por departamento. El filtro departamental existente resuelve la sede asignada, pero además hace que desaparezcan de la respuesta los productos sin fila de stock para esa sede. Para el Bodeguero, elegir un departamento de su sede no particiona ni atribuye el saldo: solo confirma/acota la consulta a su sede y oculta productos sin saldo allí. El backend actual no acepta todavía `sede_id`, y el Bodeguero no puede consultar las lecturas organizacionales existentes para obtener opciones de selector. La franja actual de indicadores resume el catálogo cargado, por lo que deberá corresponder al resultado de la sede cuando se filtre por sede.

## 2. Objetivo

Permitir al Administrador filtrar existencias por sede y departamento, y al Bodeguero seleccionar un departamento de su sede con una explicación visible de que el stock sigue siendo compartido por la sede. Añadir las opciones mínimas de ámbito necesarias para los selectores y el filtro `sede_id`, manteniendo el stock por sede, los límites server-side y resultados, criticidad e indicadores coherentes con el ámbito seleccionado.

## 3. Actores

- **Administrador Institucional:** puede consultar la lectura de ámbito y recibe sedes/departamentos activos de su institución; puede filtrar existencias por `sede_id` o `departamento_id` dentro de la institución.
- **Bodeguero / Encargado de Suministros:** puede consultar la lectura de ámbito y recibe únicamente su sede asignada y sus departamentos activos; no puede seleccionar otra sede. Puede seleccionar un departamento de su sede, con la nota visible de D-3; la API sigue limitando las existencias a su sede.
- **Solicitante (Funcionario):** conserva la lectura de existencias actualmente permitida, pero no recibe la nueva lectura de ámbito ni ve los nuevos selectores.
- **Superadmin:** no puede consultar existencias ni la nueva lectura de ámbito; ambas solicitudes responden 403.

## 4. Alcance

### Dentro

- Selectores de sede y departamento en la pestaña «Existencias» para Administrador; para Bodeguero se muestra solo selector de departamento, limitado a su sede.
- Parámetro aditivo `sede_id` en `GET /inventario/existencias`, combinable con el parámetro existente `departamento_id`.
- Operación nueva de lectura mínima de ámbito para Administrador y Bodeguero, con semántica definida en D-6 y §7.
- Opciones de selector con asociaciones departamento→sede para filtrar departamentos al elegir sede.
- Comportamiento explícito para departamentos sin sede, sedes/departamentos inactivos y Bodeguero sin sede.
- Combinación de filtros organizacionales con búsqueda por texto, categoría, criticidad y «Limpiar filtros».
- Pruebas `pytest` SQLite y gated PostgreSQL 16, pruebas de Angular, contrato OpenAPI y recorridos 4200/8080 reconstruido.

### Fuera

- Crear, modificar o exponer saldo por departamento; `stock_sede` sigue siendo la fuente única del saldo operativo.
- Agrupar productos en secciones por sede o departamento, o presentar el saldo como perteneciente en exclusiva a un departamento.
- Cambiar tickets, consumo, movimientos, despacho o autenticación Clerk.
- Cambiar el permiso/roles de cualquier operación existente o retirar una operación de la matriz. La lectura de ámbito nueva y el parámetro `sede_id` de existencias son aditivos.
- Cambiar el modelo de datos o añadir paquetes.

## 5. Decisiones

### D-1 — Selectores, no agrupación

La lista permanece en su presentación actual y se acota mediante desplegables. No se crean secciones ni subtotales de agrupación.

**Por qué:** la necesidad es filtrar la consulta; la agrupación visual podría sugerir saldos independientes que el modelo no posee.

### D-2 — Departamento significa sede asignada

`departamento_id` identifica una sede a consultar, no una partición de stock departamental. Varios departamentos de una sede resuelven el mismo stock físico. Debido al contrato actual del filtro departamental, solo aparecen productos con fila de stock en esa sede; productos sin saldo en ella desaparecen de la respuesta.

**Por qué:** desde la Feature 011 la granularidad del stock es `(sede, producto)`. El filtro departamental sirve para seleccionar la ubicación física asociada y no representa consumo o posesión departamental.

### D-3 — Nota obligatoria para el selector de Bodeguero

El Bodeguero conserva el selector de departamento, limitado a departamentos de su sede, y no se renderiza para él un selector de sede. Junto al selector se presenta literalmente la nota: **«El stock es compartido por la sede. Elegir un departamento no divide ni cambia el saldo; solo muestra productos con stock en esta sede.»**

La selección departamental no particiona el saldo ni modifica su valor: limita el resultado a productos con existencia registrada en la sede del departamento, ocultando productos que no tengan fila de stock en esa sede. Los departamentos de una sede común dan el mismo resultado de stock.

**Por qué:** la selección responde a la necesidad de explorar por departamento sin afirmar una granularidad inexistente; la nota previene una interpretación financiera/operativa falsa del saldo compartido.

### D-4 — Interacción entre sede y departamento

En la vista del Administrador, elegir sede acota las opciones de departamento a los departamentos activos asociados con esa sede. Si cambia la sede, una selección departamental incompatible se limpia y no se envía. La interfaz no permite una combinación de `sede_id` y `departamento_id` que se asocien a sedes distintas. Si ambos filtros son coherentes, se envían juntos; el backend aplica ambos. El Bodeguero no tiene selector de sede y sus opciones departamentales ya están restringidas a la sede asignada.

**Por qué:** evita consultas incoherentes y garantiza que la UI no dependa de una respuesta accidentalmente vacía para corregir sus selecciones.

### D-5 — Opciones vigentes y departamentos sin sede

La lectura de ámbito y los selectores ofrecen únicamente sedes activas y departamentos activos con sede asignada. Los departamentos activos sin sede no aparecen como opciones; la vista no ofrece un filtro que no pueda resolverse a una ubicación física. Una sede inactiva puede seguir siendo indicada manualmente al endpoint por un cliente autorizado y el servidor aplica `sede_id` a sus existencias; que la UI la omita no altera el contrato del backend.

**Por qué:** las opciones son para filtrar inventario operativo vigente. La nulabilidad de `departamento.sede_id` permite estados organizacionales incompletos, no una sede implícita. El filtrado API sigue siendo independiente de la disponibilidad del selector.

### D-6 — Lectura mínima de ámbito y permiso aditivo

Se añade una sola operación GET de solo lectura para `Administrador` y `Bodeguero`, gateada por la capacidad institucional `inventario`. Su respuesta contiene únicamente opciones para filtrar: sedes con `sede_id` y nombre, y departamentos con `departamento_id`, nombre y el `sede_id` asociado (para que la UI pueda acotar departamentos sin consultar `/organizacion/departamentos`). Solo incluye filas activas y departamentos con sede asignada.

Para Administrador, la operación devuelve las sedes y departamentos elegibles de su institución. Para Bodeguero con sede asignada, devuelve exclusivamente su sede y departamentos de esa sede. Para Bodeguero sin sede asignada, responde **409 Conflict** con error claro; no ofrece un ámbito alternativo ni una sede por defecto. No incluye usuarios, tickets, existencias, stock, saldos agregados ni registros de otra institución/sede. La ruta exacta y el nombre concreto del DTO se deciden en `plan.md`.

La nueva operación solo abastece filtros y no sustituye autorización de `GET /inventario/existencias`. La entrada de permisos de lectura de ámbito es aditiva: `GET` de la nueva ruta, roles Administrador+Bodeguero; ninguna operación existente cambia sus roles o se retira. El gating de `inventario` se evalúa además de la matriz.

**Por qué:** Bodeguero no tiene acceso a lecturas administrativas y su sesión no incluye `sede_id`. Un contrato mínimo específico aporta opciones seguras sin abrir otras lecturas ni datos de negocio. El gating conserva la disponibilidad funcional por institución vigente para el inventario.

### D-7 — Contrato de existencias aditivo y agregados coherentes

Se añade `sede_id` como parámetro opcional a `GET /inventario/existencias`; no cambia el modelo de respuesta. Sin `sede_id` **ni** `departamento_id`, `stock_total`, `es_critico` y los indicadores representan el ámbito completo permitido por rol (todas las sedes de la institución para Administrador; la sede asignada para Bodeguero y Solicitante). Con `sede_id` válido, la respuesta contiene solo esa sede y los productos de ella; `stock_total` equivale al saldo de la sede, `es_critico` se calcula sobre ese saldo y la franja de indicadores se recalcula desde esos resultados. El indicador de productos sin stock/stock crítico se interpreta, respectivamente, dentro del resultado cargado, no como total institucional oculto por el filtro. Un filtro `departamento_id` sin `sede_id` acota también a la sede del departamento.

Para `departamento_id`, se conserva la semántica existente: valida institución; otro departamento de la misma institución pero de otra sede, un departamento inexistente o uno sin sede producen **200 con lista vacía**; un departamento de otra institución produce **403**. El `outerjoin` se restringe a la sede y el endpoint omite productos sin fila de stock cuando se especifica departamento. Si se combina con `sede_id`, el departamento debe pertenecer a esa sede; un par incoherente responde **200 con lista vacía** en servidor, aunque la interfaz evita enviarlo.

Un `sede_id` existente en el ámbito institucional del actor filtra por esa sede. Un `sede_id` que no existe en el esquema/ámbito del actor responde **200 con lista vacía**: entre esquemas tenant separados el servidor no distingue el identificador ajeno de uno inexistente. Esto no supera el 404 del AC-3 de Feature 011: allí se consulta un recurso (`GET /inventario/stock?sede_id=…`) y aquí se aplica un parámetro de filtro a una lista. Para Bodeguero, un `sede_id` distinto de su sede asignada responde **200 con lista vacía** por la intersección con su alcance de stock. Para Solicitante, su propia sede filtra normalmente; una sede distinta de la sede de su departamento responde **200 con lista vacía** por la misma intersección de ámbito. Sin filtro `sede_id` ni `departamento_id`, los productos de catálogo sin saldo permanecen visibles con `sedes: []`, `stock_total: 0` y criticidad calculada conforme a la regla vigente. La capacidad `inventario` apagada deniega la consulta con **403**.

**Por qué:** el stock y la criticidad son propios de la sede consultada; los totales y las tarjetas resumen deben describir la misma lista filtrada. El contrato explícito de códigos evita ocultar con semánticas inconsistentes los identificadores inválidos o fuera de ámbito.

### D-8 — Visibilidad por capacidad de rol

La interfaz decide visibilidad mediante un helper `puede*` de rol en `frontend/src/app/core/auth/roles.ts`, con pruebas propias. Administrador y Bodeguero ven filtros apropiados; Solicitante y Superadmin no los ven. Este helper es solo presentación: la API mantiene autorización y gating.

**Por qué:** mantiene una fuente central de reglas de visibilidad de UI y el patrón probado por las capacidades existentes, sin duplicar condiciones de rol en plantillas.

## 6. Reglas del flujo

1. Clerk autentica y el servidor resuelve el tenant. El cliente no selecciona institución ni esquema.
2. La lectura de ámbito ofrece al Administrador opciones activas de su institución y al Bodeguero solo su sede activa y departamentos activos de ella. Sin sede asignada para Bodeguero, responde 409 y la UI informa que no tiene sede asignada y deja los filtros organizacionales/listado de existencias en estado no disponible; no inventa una sede.
3. Administrador puede filtrar por sede, departamento o ambos coherentes. Cambiar sede acota departamentos y limpia uno incompatible. Bodeguero no ve selector de sede, ve selector departamental y la nota literal de D-3.
4. `sede_id` filtra la respuesta al saldo de esa sede; totales, criticidad y franja de indicadores corresponden a esa misma respuesta. Sin `sede_id` ni `departamento_id`, se mantiene el agregado permitido por rol.
5. `departamento_id` selecciona la sede del departamento, pero no separa stock departamental. Productos sin fila de stock en la sede se omiten. Departamentos distintos de una sede común generan el mismo saldo.
6. Texto, categoría y críticos se combinan con los filtros organizacionales. «Limpiar filtros» restablece todos los filtros visibles y recupera el agregado permitido por rol.
7. Sin filtros organizacionales, productos sin saldo aparecen en cero con `sedes: []`. Con `sede_id` o `departamento_id`, los productos sin fila de saldo en la sede filtrada desaparecen; si no quedan filas, la vista indica «Ningún insumo coincide con los filtros aplicados», no «El catálogo no tiene insumos cargados».
8. Sede/departamento de otra institución no se incluyen en opciones. La API aplica los códigos y ámbitos de D-7 incluso si el cliente manipula la petición.
9. Capacidad `inventario` apagada da 403 en la lectura de ámbito y en las existencias, independientemente de los roles permitidos por matriz.

## 7. Contrato semántico de operaciones nuevas/alteradas

### Lectura nueva de ámbito de inventario

- **Método y ruta:** GET; ruta exacta se decide en `plan.md`.
- **Roles:** Administrador y Bodeguero; Solicitante y Superadmin reciben 403.
- **Gating:** capacidad institucional `inventario`; apagada devuelve 403.
- **Administrador:** 200 con sedes activas y departamentos activos con sede asignada, todos de su institución.
- **Bodeguero con sede:** 200 con únicamente su sede y departamentos activos de esa sede.
- **Bodeguero sin sede:** 409, sin fallback ni opciones ajenas.
- **Campos mínimos:** ID/nombre de sede e ID/nombre/sede_id de departamento. Sin usuarios, tickets, stock ni otras instituciones/sedes.
- **Autenticación:** falta de sesión 401.

### `GET /inventario/existencias` (contrato ampliado aditivamente)

- Se conserva el permiso existente para los roles institucionales ya autorizados; Superadmin conserva 403. El gating existente de `inventario` aplica.
- Se añade el parámetro opcional `sede_id` y se conserva `departamento_id`.
- Sesión ausente: 401. Rol no autorizado o capacidad `inventario` apagada: 403.
- Administrador: `sede_id` existente en su institución filtra (200); identificador de sede fuera de su ámbito, incluido un id de otra institución en otro esquema, responde 200 con `[]` porque no existe en el ámbito consultado. Esto no cambia el 404 establecido por AC-3 de Feature 011 para `GET /inventario/stock?sede_id=…`, que consulta un recurso y no filtra una lista.
- Bodeguero: `sede_id` de su propia sede filtra; cualquier otra sede responde 200 con `[]` por la intersección con su alcance. Sin sede asignada, la lectura sigue respondiendo 409 conforme al comportamiento vigente.
- Solicitante: `sede_id` de la sede de su departamento filtra; una sede distinta responde 200 con `[]` por la intersección con su alcance. No se le habilitan selectores ni cambia su permiso.
- `departamento_id` inexistente, sin sede o de otra sede dentro de la misma institución: 200 con `[]`; departamento de otra institución: 403.
- Si ambos filtros se envían coherentemente, ambos se aplican. Departamento asociado a sede distinta del `sede_id`: 200 con `[]`; la UI no envía este caso.
- Sin filtro por `sede_id` ni `departamento_id`, producto sin existencias permanece en cero con `sedes: []`. Al filtrar por sede/departamento desaparecen productos sin fila de stock en esa sede.
- Con filtro por sede, `stock_total`, `es_critico` y franja de indicadores describen exclusivamente el saldo/resultado de esa sede.

## 8. Criterios de aceptación

- **AC-1 — Filtro de sede y coherencia de resultados para Administrador.** DADO un Administrador con existencias en más de una sede, CUANDO selecciona una sede válida de su institución, ENTONCES la lista contiene solo saldos de esa sede; cada `stock_total` es el saldo de esa sede, `es_critico` se calcula sobre ese saldo y la franja de indicadores (total de catálogo cargado, con existencias y críticos) se recalcula sobre la lista filtrada. DADO que no hay `sede_id` ni `departamento_id` seleccionados, ENTONCES esos valores describen el agregado de todas las sedes de su institución. Un `sede_id` que no existe en el ámbito consultado devuelve 200 con `[]` y no revela si existe en otro esquema tenant.
  - **Evidencia:** `backend/tests/api/test_filtros_inventario_018.py` cubre filtro de sede, totales/críticos y sede ajena; `frontend/src/app/features/inventario/inventario.component.spec.ts` verifica indicadores con y sin sede; recorrido 4200. Detalle por test en §10.

- **AC-2 — Filtro por departamento y semántica de sede compartida.** DADO dos departamentos activos asociados a la misma sede, CUANDO Administrador o Bodeguero selecciona cualquiera, ENTONCES se consulta con su `departamento_id` y se muestran los mismos saldos físicos de esa sede, sin atribuirlos exclusivamente al departamento. Solo aparecen productos con fila de stock en esa sede. En la UI del Bodeguero se muestra literalmente: «El stock es compartido por la sede. Elegir un departamento no divide ni cambia el saldo; solo muestra productos con stock en esta sede.»; la nota no se muestra al Administrador.
  - **Evidencia:** `backend/tests/api/test_filtros_inventario_018.py` cubre el filtro departamental, respuesta vacía y agregación; `frontend/src/app/features/inventario/inventario.component.spec.ts` verifica query y nota literal exclusiva del Bodeguero; recorrido 4200. Detalle por test en §10.

- **AC-3 — Filtro `sede_id` y códigos de ámbito.** DADO un Administrador, CUANDO solicita `GET /inventario/existencias?sede_id=…`, ENTONCES sede existente de su institución devuelve 200 acotado a esa sede; un identificador que no existe en el esquema del actor —incluido uno de otra institución— devuelve 200 con lista vacía, sin inferir si existe fuera de ese tenant. Esto no supera el 404 del AC-3 de Feature 011 para `GET /inventario/stock?sede_id=…`: el endpoint 011 consulta un recurso, mientras aquí `sede_id` filtra una lista. DADO Bodeguero, su propia sede filtra y cualquier otra sede devuelve 200 con lista vacía. DADO Solicitante, su sede departamental filtra y una distinta devuelve 200 con lista vacía. Parámetros válidos se combinan con departamento; pareja incoherente devuelve 200 con lista vacía.
  - **Evidencia:** `backend/tests/api/test_filtros_inventario_018.py` prueba códigos/ámbitos con TestClient; `backend/tests/test_filtros_inventario_postgres_018.py` (gated PostgreSQL 16) valida aislamiento tenant; `backend/tests/schemas/test_dto_ambito_018.py` cubre el DTO de ámbito. OpenAPI publica `sede_id`; recorrido 4200. Detalle por test en §10.

- **AC-4 — Ámbito organizacional del Bodeguero y departamentos no autorizados.** DADO un Bodeguero con sede, CUANDO consulta la nueva lectura, ENTONCES recibe solo su sede y departamentos activos de ella; la UI no renderiza selector de sede. Para `GET /inventario/existencias`, `departamento_id` inexistente, sin sede o de otra sede de su institución responde 200 con lista vacía; departamento de otra institución responde 403. DADO un Bodeguero sin sede, ENTONCES la nueva lectura de ámbito y las existencias responden 409; la UI muestra el mensaje de sede no asignada y no presenta una selección sustituta.
  - **Evidencia:** `backend/tests/api/test_filtros_inventario_018.py` prueba respuesta de ámbito, sede ausente y los cuatro casos departamentales; `frontend/src/app/features/inventario/inventario.component.spec.ts` verifica ausencia del selector de sede, opciones y estado 409; recorrido 4200.

- **AC-5 — Selectores coherentes por sede y helper de rol.** DADO que Administrador elige sede A, CUANDO abre o actualiza el selector departamental, ENTONCES solo se ofrecen departamentos de sede A. Cambiar a sede B limpia selección incompatible; la UI nunca envía una pareja departamento/sede incoherente. El helper `puede*` de `roles.ts` permite selectores solo a Administrador/Bodeguero y las pruebas del helper verifican esos roles y la exclusión de Solicitante/Superadmin. El Bodeguero no ve selector de sede.
  - **Evidencia:** `frontend/src/app/core/auth/roles.spec.ts` para el helper y `frontend/src/app/features/inventario/inventario.component.spec.ts` para acotación, limpieza y query; recorrido 4200.

- **AC-6 — Estados vacíos según filtro organizacional.** DADO que un producto no tiene ninguna fila de stock, CUANDO no hay filtro de sede/departamento, ENTONCES aparece con `stock_total: 0`, `sedes: []` y criticidad vigente. DADO que ese producto no tiene fila de stock en la sede seleccionada o en la sede del departamento, ENTONCES desaparece. Si la consulta filtrada devuelve cero productos, la vista muestra «Ningún insumo coincide con los filtros aplicados»; si la consulta sin filtros devuelve un catálogo vacío, muestra «El catálogo no tiene insumos cargados». Carga y error conservan sus estados diferenciados.
  - **Evidencia:** `backend/tests/api/test_filtros_inventario_018.py` verifica resultado sin filtro vs. filtros sede/departamento; `inventario.component.spec.ts` comprueba los dos mensajes, carga y error; recorrido 4200.

- **AC-7 — Combinación y limpieza de filtros.** DADO filtros de sede/departamento, CUANDO se combinan con texto, categoría y «Solo stock crítico», ENTONCES se aplican simultáneamente. «Limpiar filtros» restablece filtros organizacionales y existentes; los indicadores regresan al agregado permitido por rol.
  - **Evidencia:** `frontend/src/app/features/inventario/inventario.component.spec.ts` cubre combinaciones, limpieza y métricas; recorrido 4200.

- **AC-8 — Roles, matriz, capacidad y OpenAPI.** DADO la nueva lectura, CUANDO se verifica autorización, ENTONCES aparece exactamente una nueva entrada en la matriz con Administrador+Bodeguero y la cardinalidad sube de 60 a **61**; todas las 60 operaciones previas mantienen exactamente sus roles y ninguna se retira. Solicitante/Superadmin reciben 403 en lectura de ámbito. Con capacidad `inventario` apagada, ambos roles autorizados reciben 403 en esa lectura y existencias. Superadmin conserva 403 en existencias. El contrato OpenAPI declara respuestas 200, 401, 403 y 409 aplicables para ámbito y el parámetro `sede_id` en existencias.
  - **Evidencia:** ampliar `backend/tests/api/test_ciclo_vida_autorizacion_014.py` (matriz 61 y 60 previas intactas), `backend/tests/api/test_permisos_*.py` (incluido el seam de referencia transcrita independientemente) y `backend/tests/api/test_capacidades_gating_012.py` (asociación a `inventario` y 403 apagado); nuevo `test_filtros_inventario_018.py` para roles/endpoints; OpenAPI. `roles.spec.ts` verifica helper y `inventario.component.spec.ts` la presentación.

- **AC-9 — Verificación funcional y de aislamiento.** DADO el cambio backend y frontend, CUANDO se cierra la feature, ENTONCES `pytest` SQLite verifica contrato/matriz/gating; pruebas gated PostgreSQL 16 verifican aislamiento por tenant y límites de ámbito, incluyendo que un id de sede de otro esquema resulte 200/`[]` en este filtro de lista; `ng test` verifica helper, selectores, métricas, nota y vacíos; `/openapi.json` refleja el contrato; recorridos funcionales en 4200 y de humo en 8080 reconstruido pasan. El resultado 200/`[]` de esta lista no contradice el 404 de Feature 011 AC-3, que prueba la consulta de un recurso por `/inventario/stock`.
  - **Evidencia:** `cd backend && pytest`; suite gated con `POSTGRES_TEST_URL` y tests de `test_filtros_inventario_018.py`; `npx ng test --watch=false --browsers=ChromeHeadless`; `/openapi.json`; recorrido 4200 y 8080 con frontend reconstruido.

## 9. Restricciones y cambios documentales de cierre

- `stock_sede` sigue como fuente única de stock; no hay saldo por departamento ni cambios de modelo de datos.
- La matriz solo recibe una operación nueva y aditiva para lectura de ámbito (Administrador+Bodeguero); ninguna operación existente cambia de roles ni se retira. La matriz pasa de 60 a 61 operaciones. La Feature 014 se amplía explícitamente, no se reescribe en silencio: sus aserciones absolutas de cardinalidad y OpenAPI, `test_matriz_tiene_exactamente_60_operaciones_tras_014` y `test_openapi_tiene_60_operaciones_tras_014` en `backend/tests/api/test_ciclo_vida_autorizacion_014.py`, se actualizan de 60 a 61 o se trasladan a una instantánea histórica; el plan fija la opción concreta antes de implementar.
- Se añade únicamente `sede_id` a `GET /inventario/existencias`; `departamento_id` conserva la semántica de esta spec. No se cambia el modelo de respuesta.
- La nueva lectura está gateada por capacidad `inventario`; esto no amplía capacidades ni cambia su catálogo cerrado.
- La operación nueva no concede al Bodeguero lecturas de sedes ajenas, departamentos de otra sede, usuarios, tickets ni stock/saldos de otras sedes. La autorización y el aislamiento efectivos permanecen en backend.
- Clerk permanece como autoridad de autenticación. No se agregan paquetes.
- Identificadores de dominio en español; Angular standalone, signals/computed y Tailwind; helper `puede*` central con pruebas.
- No se depende de `AdministracionService` ni de endpoints administrativos para obtener las opciones de inventario.
- Al cierre se actualiza `docs/spec/stack.md` con la operación y parámetro aditivos, la matriz/gating y el contrato, siguiendo el precedente de las Features 011/014; también se actualiza la fila de Feature 018 en `docs/spec/roadmap.md` y se mantiene coherencia documental.

## 10. Estado y evidencia de verificación

Todos los AC quedaron **verificados** al cierre (21/Oct/2026). Los nombres de test son reales
y viven en `backend/tests/api/test_filtros_inventario_018.py` (35 pruebas),
`backend/tests/schemas/test_dto_ambito_018.py` (13),
`backend/tests/test_filtros_inventario_postgres_018.py` (6 gated),
`frontend/src/app/core/auth/roles.spec.ts`,
`frontend/src/app/features/inventario/inventario.component.spec.ts` y
`frontend/src/app/features/inventario/services/inventario.service.spec.ts`. No se creó
`backend/tests/services/test_filtros_inventario_018.py`: el filtrado de lista, sus agregados y
la regla de `condicion_stock` se ejercen sobre el harness con `TestClient` (que atraviesa
ruta→servicio) y no por llamada directa al servicio.

| Criterio | Estado | Evidencia de verificación |
|---|---|---|
| AC-1 | Verificado | `test_filtros_inventario_018.py::test_existencias_con_sede_acotan_saldo_sedes_y_criticidad`, `::test_existencias_sin_filtro_mantienen_agregado_y_productos_sin_saldo`, `::test_existencias_sede_inexistente_responde_200_vacio` (saldo, `sedes` y `es_critico` por sede; agregado sin filtro; 200/`[]`). UI: `inventario.component.spec.ts` → *«al elegir una sede acota la consulta y recalcula la franja de indicadores»*. **Recorrido 4200** (no test): capturas `02-admin-sede-providencia.png` (franja 3/2/1) y `8080-02-admin-sede-filtrada.png`. |
| AC-2 | Verificado | Backend: `test_filtros_inventario_018.py::test_departamentos_de_la_misma_sede_devuelven_el_mismo_saldo` (dos departamentos de sede común → mismo saldo; productos sin fila desaparecen). UI: `inventario.component.spec.ts` → *«el Bodeguero no ve selector de sede, ve sus departamentos y la nota literal»* y *«la nota de stock compartido no se muestra al Administrador»*. **Recorrido 4200** (no test): capturas `03-admin-departamento-docencia.png` y `09-bodeguero-departamento-biblioteca.png`. |
| AC-3 | Verificado | Backend API: `test_filtros_inventario_018.py::test_existencias_sede_de_otra_institucion_responde_200_vacio`, `::test_existencias_bodeguero_filtra_su_sede_y_otra_sede_da_vacio`, `::test_existencias_solicitante_su_sede_filtra_y_otra_sede_da_vacio`, `::test_existencias_sede_y_departamento_incoherentes_responde_200_vacio`. **Gated PostgreSQL 16**: `test_filtros_inventario_postgres_018.py::test_sede_de_otro_tenant_devuelve_200_vacio_y_el_recurso_conserva_404` (filtro de lista → 200/`[]`; el recurso `/inventario/stock` conserva su 404 de 011) y `::test_filtro_propio_acota_saldo_y_sede_ajena_en_rol_operativo_da_vacio`. OpenAPI: `::test_openapi_publica_ambito_y_el_parametro_sede_id`. |
| AC-4 | Verificado | Backend API: `test_filtros_inventario_018.py::test_ambito_bodeguero_recibe_solo_su_sede_y_sus_departamentos`, `::test_ambito_bodeguero_sin_sede_responde_409`, `::test_existencias_departamento_no_resoluble_responde_200_vacio`, `::test_existencias_departamento_de_otra_institucion_responde_403` (harness SQLite), `::test_existencias_bodeguero_sin_sede_responde_409`. UI: `inventario.component.spec.ts` → *«el Administrador consulta el ámbito y ve sede y departamento con sus opciones»* y *«un 409 de ámbito sin sede deja la vista con aviso y sin filtros sustitutos»*. **Recorrido 4200/8080** (no test): capturas `08-bodeguero-nota-y-departamento.png` y `8080-03-bodeguero-departamento.png`; el 409 se contrastó por API con sesión real (`evidencia/README.md` §6.1). |
| AC-5 | Verificado | `roles.spec.ts` → *«puedeVerFiltrosInventario concede solo a Administrador y Bodeguero (AC-5/AC-8)»*, *«puedeVerFiltrosInventario no concede a alias, desconocido ni ausente (AC-5)»*, *«el Solicitante conserva la vista de inventario pero no sus filtros (AC-7)»*, *«el Superadmin sigue denegado en inventario y en sus filtros (AC-8)»*. UI: `inventario.component.spec.ts` → *«cambiar de sede limpia el departamento incompatible y acota sus opciones»*. **Recorrido 4200** (no test): captura `04-admin-cambio-sede-limpia-departamento.png`. |
| AC-6 | Verificado | Backend: `test_filtros_inventario_018.py::test_existencias_con_filtro_organizacional_oculta_productos_sin_saldo`. UI: `inventario.component.spec.ts` → *«con filtros organizacionales sin resultados muestra el vacío filtrado»*, *«debe distinguir el estado vacio del estado con filtros»*, *«debe mostrar un error si el backend no responde»*. **Recorrido 4200** (no test): captura `06-admin-vacio-filtrado.png`. |
| AC-7 | Verificado | UI: `inventario.component.spec.ts` → *«combina sede y departamento con texto, categoría y «Solo stock crítico»»* y *««Limpiar filtros» restablece los filtros organizacionales y los existentes»*. **Recorrido 4200** (no test): capturas `05-admin-combinacion-filtros.png` y `07-admin-limpiar-filtros.png`; `10-solicitante-sin-selectores.png`. |
| AC-8 | Verificado | Matriz 60→61: `backend/tests/api/test_ciclo_vida_autorizacion_014.py` (las dos aserciones absolutas `test_matriz_tiene_exactamente_60_operaciones_tras_014` y `test_openapi_tiene_60_operaciones_tras_014` quedaron en 61, con comentario de ampliación explícita por la 018). `test_filtros_inventario_018.py::test_matriz_declara_la_operacion_de_ambito_para_administrador_y_bodeguero`, `::test_matriz_conserva_las_operaciones_previas_intactas`, `::test_matriz_tiene_exactamente_61_operaciones_tras_018`, `::test_capacidad_inventario_asociada_a_la_operacion_de_ambito`, `::test_ambito_de_rol_no_autorizado_responde_403`, `::test_ambito_con_capacidad_inventario_apagada_responde_403`, `::test_openapi_publica_61_operaciones_tras_018`, `::test_openapi_documenta_respuestas_de_ambito_y_existencias`. Baseline histórico de 55 preservado en `backend/tests/api/test_permisos.py` con referencia aditiva; gating en `backend/tests/api/test_capacidades_gating_012.py`. **Matiz de evidencia:** el 403 por capacidad apagada en `/inventario/existencias` se acredita de forma indirecta —el mapa `inventario` de la 012 (línea `("GET", "/api/v1/inventario/existencias"): "inventario"`), el `requiere_capacidad` que encadena la ruta y la prueba directa de ámbito— y no por una aserción HTTP dedicada a existencias con la capacidad apagada; es comportamiento **previo a la 018** (ver `tasks.md` T9) y no una regresión de esta feature. UI: `roles.spec.ts` (helper) e `inventario.component.spec.ts` (presentación). |
| AC-9 | Verificado | **Suites:** `cd backend && python -m pytest -q` → **1339 passed / 76 skipped / 0 failed** (SQLite). Gated `POSTGRES_TEST_URL` → **1415 passed / 0 skipped / 0 failed** (`apt_erp` intacta: 5 instituciones, 4 esquemas `tenant_%`, `version_esquema 014.1` con la misma marca). `npx ng test --watch=false --browsers=ChromeHeadless` → **419 SUCCESS / 0 FAILED**; `npx ng build` limpio (`main-7QF7T5XQ.js`). **OpenAPI:** 61 operaciones v1, claves idénticas a `MATRIZ_PERMISOS`. **Recorrido funcional 4200** con escritura real (capturas `01`…`10`) y **humo 8080** tras `docker compose build frontend` (bundle `main-7QF7T5XQ.js`, capturas `8080-01`…`8080-04`), ambos en `docs/spec/features/018-filtro-inventario-sede-departamento/evidencia/README.md`. El 200/`[]` de la lista no contradice el 404 de 011 AC-3 (recurso `/inventario/stock`), verificado en el gated. |

La ruta/DTO exactos de la operación de ámbito se fijan en `plan.md`; no pueden alterar este contrato semántico ni la lista de campos mínimos. La operación publicada es `GET /api/v1/inventario/ambito` con `AmbitoInventarioRespuesta`.
