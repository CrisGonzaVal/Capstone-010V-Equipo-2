# Feature 008: Particionamiento lógico de datos por institución (SaaS multiinstitución)

**Estado:** Cerrada y verificada
**Release:** 2.0 — Sprint 4
**Tipo:** Aislamiento de datos multiinstitución

> **Enmienda posterior al cierre (22/Oct/2026):** la Feature 008 permanece cerrada y
> verificada. Esta enmienda acotada actualiza únicamente la semántica de `usuario_id`
> en el alta de tickets para armonizarla con la autoatribución aprobada en las Features
> 003 y 007; no reabre el particionamiento ni modifica la matriz de permisos.

## 1. Problema

Feature 007 ya limita usuarios, departamentos, tickets e inventario operativo por la institución derivada del usuario autenticado. Sin embargo, el esquema y algunas lecturas aún comparten catálogo y métricas de stock: `categoria` y `producto` carecen de pertenencia institucional, `GET /inventario/categorias` y `/productos` son globales, y `GET /tickets/catalogos` suma stock de distintas instituciones. Por tanto, la base admite varias instituciones nominales, pero no conjuntos independientes de catálogo, stock y flujo para instituciones realmente aisladas.

La semilla ya contiene cuatro instituciones con usuarios y departamentos de prueba, pero el catálogo maestro actualmente es único. La semilla puede conservar las cuatro; para demostrar independencia, al menos dos deben tener catálogo y existencias diferenciables, incluidos nombres homónimos deliberados. La frontera de seguridad debe ser el servidor: ocultar datos en Angular no impide que un cliente invoque directamente la API.

## 2. Objetivo

Habilitar varias instituciones reales en una misma base y hacer que cada institución disponga de su catálogo y existencias, mientras usuarios autenticados solo consultan y operan los datos de su ámbito. Superadmin conserva lectura global; los roles limitados continúan derivados de su institución local conforme a Feature 007.

## 3. Alcance

### Dentro

- Separar el catálogo de categorías y productos por institución, incluyendo los productos seleccionables en tickets.
- Aislar existencias y sus agregados por institución, departamento y producto institucional.
- Aplicar el ámbito en todos los endpoints actuales que leen o modifican usuarios, departamentos, instituciones, categorías, productos, existencias, movimientos, catálogos de tickets, tickets y detalles relacionados.
- Mantener el catálogo de roles, prioridades y estados del flujo como catálogos globales compartidos.
- Preservar el ámbito por usuario: Administrador, Bodeguero y Solicitante obtienen su institución desde su departamento; Solicitante conserva además la propiedad de sus tickets. Superadmin tiene lectura global.
- Permitir que Superadmin supervise datos de todas las instituciones en las lecturas globales autorizadas.
- Asegurar que las referencias entre tickets, detalles, productos y existencias sean consistentes con la institución del ticket antes de crear o despachar.
- Poblar datos de prueba de al menos dos instituciones con catálogos y existencias diferenciables para comprobar aislamiento; mantener datos reproducibles.
- Incorporar una migración SQL reproducible e idempotente para bases existentes, preservando datos y relaciones en lugar de reinicializar la base.
- Justificar en `stack.md` la evolución del modelo relacional actualmente descrito como 12 entidades 3NF y la estrategia de pertenencia institucional.

### Fuera

- Una identidad Clerk vinculada simultáneamente a varias instituciones, selector de institución activa o cambio de institución para roles limitados.
- Aprovisionamiento, edición o eliminación del ciclo de vida de instituciones y sedes, salvo los datos mínimos necesarios para la semilla de QA.
- Modificar la autenticación Clerk o los cuatro roles. Se exceptúa únicamente el ajuste puntual de permisos de escritura de catálogo/stock/tickets por institución decidido aquí; el resto de la matriz de Feature 007 no se reabre.
- Catálogos independientes por institución de roles, prioridades y estados de ticket.
- Reescritura del flujo de tickets/despacho, reglas de stock crítico o auditoría de movimientos, más allá de las validaciones interinstitucionales necesarias para el aislamiento.
- Separación física de bases de datos o infraestructura multi-región; esta entrega establece aislamiento lógico en la base compartida.
- Cambios a métricas del dashboard de Feature 009.

## 4. Actores

- **Superadmin**: identidad global; puede consultar datos de varias instituciones según las operaciones autorizadas y compararlos. No escribe catálogo, stock ni tickets de una institución concreta. No requiere selector de institución en esta entrega.
- **Administrador Institucional (`Administrador`)**: opera el catálogo y los datos de usuarios/inventario/tickets de la institución de su departamento; no puede consultar ni asignar datos de otra institución.
- **Bodeguero**: opera inventario, movimientos y tickets de la institución de su departamento.
- **Solicitante**: consulta catálogo y disponibilidad de su institución y solo gestiona sus propios tickets.

## 5. Decisiones

### D-1 — Catálogo de categorías y productos por institución

Cada categoría y producto pertenece a una única institución. No hay catálogo maestro compartido entre instituciones. Los nombres o descripciones iguales en dos instituciones representan registros independientes y sus identificadores no permiten acceso cruzado.

**Por qué:** la Feature 007 dejó expresamente el catálogo global como excepción temporal y asignó su particionamiento a esta entrega. Un catálogo compartido revelaría definiciones y modificaciones entre instituciones, y no satisface el aislamiento requerido. Las categorías y productos globales no se retienen como alternativa de fallback.

### D-2 — Existencias institucionales derivadas de departamento

Una existencia pertenece al ámbito de la institución de su departamento, y su producto debe pertenecer a esa misma institución. Las lecturas, agregados, filtros y mutaciones de inventario solo consideran existencias del ámbito; el stock de una institución no se agrega ni se usa para completar stock de otra.

**Por qué:** inventario ya depende de departamento, que tiene `institucion_id`; conservar ese vínculo evita duplicar un ámbito contradictorio en cada fila. La restricción producto-existencia debe hacer imposible asociar inventario de una institución con producto de otra.

### D-3 — Contexto limitado y separación de lectura/escritura global

Cada Administrador, Bodeguero y Solicitante conserva una única institución efectiva derivada de `usuario → departamento → institucion`. No existe selección de institución activa para esos roles. Superadmin tiene lectura global, pero no puede escribir catálogo, stock ni tickets de una institución concreta; esas escrituras corresponden al Administrador de esa institución, y las demás operaciones siguen la matriz 007. Este es un ajuste puntual de permisos de 007, no una reapertura del resto de la matriz. Las lecturas globales no requieren selector para demostrar la revisión multiinstitucional.

**Por qué:** Feature 007 estableció que el usuario local tiene un departamento obligatorio y que Superadmin es global. Separar su lectura global de las escrituras operativas evita cambios institucionales sin contexto y reserva la administración de cada catálogo/stock/ticket a su Administrador responsable. La selección multiinstitución exigiría una relación usuario-institución y una nueva política de contexto que no se deduce del sistema actual.

### D-4 — El servidor aplica todos los filtros institucionales

La institución se obtiene de la identidad autenticada local; no se acepta `institucion_id` del cliente como prueba de autorización. La aplicación filtra consultas antes de responder y valida referencias antes de mutar. Un parámetro de departamento ajeno mantiene la denegación 403 de 007; un recurso existente ajeno al ámbito no se distingue del inexistente en operaciones de objeto, y responde 404. El ámbito no resoluble para rol limitado responde 403. La denegación no deja mutaciones.

**Por qué:** Angular es navegación y no frontera de seguridad (007, D-2); no confiar en identificadores provistos por cliente previene enumeración y referencias cruzadas.

### D-5 — Catálogos de flujo compartidos

`rol`, `prioridad` y `estado_ticket` siguen siendo globales. Institución, departamento, usuario, categoría, producto, inventario, movimiento, ticket y detalle forman parte de datos aislados directa o transitivamente. El esquema podrá necesitar nuevas columnas institucionales o claves/relaciones compuestas para asegurar pertenencia consistente, pero el diseño concreto se decide en el plan y debe justificarse en `stack.md` antes de modificar el modelo.

**Por qué:** roles y estados/prioridades describen políticas y flujo comunes, sin datos operativos de una institución. La entidad categoría/producto e inventario sí representan catálogo/stock propios; ticket y su detalle heredan el ámbito por sus relaciones y requieren que referencias de producto pertenezcan a ese ámbito.

### D-6 — Migración sin pérdida y datos legados

La migración debe asignar datos existentes a su institución mediante relaciones ya persistidas, conservar identificadores, usuarios, tickets, detalles, stock y movimientos, y evitar consolidar o borrar instituciones. Si un producto o categoría legado está referenciado por datos de más de una institución y su pertenencia no puede inferirse sin ambigüedad, la migración aborta antes de aplicar cambios destructivos, informa explícitamente qué registro es ambiguo y requiere que el operador corrija manualmente los datos antes de reintentar. No se reasigna automáticamente ni se pierde información.

**Por qué:** las tablas legadas de categoría y producto no tienen institución. La relación directa entre ambos tampoco determina por sí sola a qué institución pertenece un producto compartido históricamente; debe revisarse el uso de detalles e inventarios y documentarse el procedimiento de asignación. La regla de abortar y solicitar corrección manual evita pérdida o reasignación automática y permite reintentar tras corregir los datos. El principio de trazabilidad prohíbe borrar o reasignar auditoría silenciosamente.

## 6. Reglas del flujo y ámbito de datos

### Pertenencia funcional

| Entidad/datos | Ámbito requerido |
|---|---|
| `institucion`, `departamento`, `usuario` | Los datos de objeto se aíslan por institución; Administrador, Bodeguero y Solicitante solo consultan usuarios de su ámbito. Superadmin conserva lectura global de usuarios conforme a su matriz. |
| `categoria`, `producto` | Una institución por registro; catálogo aislado. |
| `inventario` | Institución del departamento; producto de la misma institución. |
| `movimiento_inventario` | Institución del inventario asociado; registro de auditoría inmutable. |
| `ticket`, `detalle_ticket` | Institución del usuario de sesión que crea/ticket; cada producto del detalle debe pertenecer a ella. `usuario_id` del payload se ignora, incluso si identifica otro usuario/institución. |
| `rol`, `prioridad`, `estado_ticket` | Globales y compartidos. |

No se acepta un ticket que cruce instituciones por `producto_id`: `usuario_id` del payload no determina el solicitante y se ignora conforme a la enmienda D-7. El ticket y sus detalles se anclan a la institución de la identidad de sesión; cada producto del detalle debe pertenecer a esa institución. Al despachar, el inventario que se rebaja debe pertenecer a la misma institución que el ticket y el producto de su detalle. La operación conserva atomicidad: rebaja, detalle entregado, cierre y movimientos se confirman juntos o se revierten juntos.

### Alcance por rol

- **Superadmin**: lectura global en operaciones autorizadas por la matriz 007. No escribe catálogo, stock ni tickets de una institución concreta; estas escrituras corresponden al Administrador de dicha institución. Las demás escrituras siguen sujetas a la matriz 007, cuyo resto no se modifica. Las lecturas y agregados globales deben atribuir cada dato a su institución.
- **Administrador**: catálogo, usuarios, departamentos, instituciones consultables, tickets e inventario propios; creación de producto/categoría debe asociarse exclusivamente a su institución. Un ID ajeno no amplía el ámbito.
- **Bodeguero**: consulta y mutación de inventario/movimientos/tickets propios; no administra catálogo ni usuarios más allá de lo permitido por la matriz vigente.
- **Solicitante**: productos, categorías y disponibilidad de su institución; sus propios tickets. Las categorías/productos no relacionados con su institución no aparecen.

### Operaciones existentes afectadas

El aislamiento se debe verificar en `GET /usuarios/`, `POST /usuarios/`, catálogos auxiliares, `GET/POST /inventario/productos`, `GET /inventario/categorias`, `/inventario/existencias`, `/inventario/stock`, `/inventario/movimientos`, `/tickets/catalogos`, `/tickets/`, `POST /tickets/`, `PATCH /tickets/{ticket_id}/estado` y despacho. `GET /auth/me` devuelve la institución efectiva de Administrador, Bodeguero y Solicitante; para Superadmin declara explícitamente que no tiene institución efectiva. Esa respuesta informa contexto de UI, no sustituye autorización servidor.

## 7. Criterios de aceptación

### Datos y modelo

- **AC-1** Una instalación nueva puede conservar las cuatro instituciones de semilla existentes y contiene al menos dos instituciones con departamentos, usuarios, categorías, productos, inventarios, movimientos y tickets asociados de forma consistente. En esas dos instituciones existe al menos una categoría y un producto con exactamente el mismo nombre en ambas; son registros independientes y el stock de cada producto es independiente.
  - **Verificado:** chequeo reproducible de instalación nueva (base temporal `compustock_newinstall_check`; `docker exec -i compustock_db psql ... < database\01_esquema.sql` + `02_datos_semilla.sql` + `98_` + `99_`): 4 instituciones; INST-001 (7 usuarios, 6 categorías, 10 productos, 10 inventario, 10 movimientos, 8 tickets) e INST-002 (1 usuario, 4 categorías, 4 productos, 4 inventario, 4 movimientos, 2 tickets); 0 referencias cruzadas. Homónimos con IDs y stock distintos: «Resma Carta 75g A4» (producto 1/11, stock 50/12), «Toner HP 26A Negro» (2/12, 18/9), «Folder Manila Carta» (3/14, 200/60). En código: `test_cobertura_ac_008.py::test_homonimos_son_registros_independientes_con_stock_propio` y `test_modelo_particionamiento.py::test_relaciones_intrainstitucionales_persisten` (487 passed, 5 skipped).
- **AC-2** Categorías y productos tienen pertenencia institucional inequívoca. Las consultas de catálogo de una institución devuelven sus registros y no los de otra; las relaciones inválidas entre producto y categoría o inventario y producto son rechazadas y no quedan persistidas.
  - **Verificado:** PostgreSQL 16 `test_migracion_postgres.py::test_esquema_nuevo_rechaza_referencias_cruzadas_entre_instituciones` (FK compuestas `producto_categoria_institucion_fk`, `inventario_producto_institucion_fk`, etc.; tras cada rechazo los conteos quedan en 2 productos / 0 inventario / 0 detalle) y `test_esquema_nuevo_exige_institucion_not_null`; modelo `test_modelo_particionamiento.py::test_modelo_declara_claves_compuestas_institucionales`, `test_producto_con_categoria_ajena_es_rechazado`; HTTP `test_ambito_institucional.py::test_categorias_y_productos_son_institucionales`. (487 passed, 5 skipped; 492 passed con `POSTGRES_TEST_URL`.)
- **AC-3** `rol`, `prioridad` y `estado_ticket` siguen compartidos por todas las instituciones y su contrato funcional existente permanece disponible.
  - **Verificado:** `test_cobertura_ac_008.py::test_catalogos_de_flujo_son_compartidos_por_ambas_instituciones` (prioridades/estados idénticos para INST01 e INST02; los cuatro roles presentes) y `test_ambito_institucional.py::test_roles_son_compartidos_para_el_administrador`. (487 passed, 5 skipped.)
- **AC-4** Si se intenta persistir un detalle de ticket cuyo producto pertenece a una institución distinta de la del ticket, la operación se rechaza —por restricción de integridad o validación del servicio— y no deja ticket/detalle parcial. Si se intenta persistir inventario cuyo producto pertenece a institución distinta de la del departamento, la operación también se rechaza y no deja inventario parcial.
  - **Verificado:** `test_modelo_particionamiento.py::test_detalle_con_producto_ajeno_es_rechazado`, `test_detalle_con_ticket_ajeno_es_rechazado`, `test_inventario_con_producto_ajeno_es_rechazado`, `test_inventario_con_departamento_ajeno_es_rechazado`; y sobre PostgreSQL 16 `test_migracion_postgres.py::test_esquema_nuevo_rechaza_referencias_cruzadas_entre_instituciones` (asserts de cero filas persistidas) + `test_esquema_nuevo_exige_institucion_not_null`. (487 passed, 5 skipped; 492 passed con `POSTGRES_TEST_URL`.)

### Aislamiento de lecturas

- **AC-5** DADA una identidad Administrador, Bodeguero o Solicitante vinculada a INST-A, CUANDO consulta categorías, productos o catálogos de tickets, ENTONCES solo recibe categorías/productos de INST-A, independientemente de IDs o filtros enviados por el cliente.
  - **Verificado:** `test_cobertura_ac_008.py::test_parametro_institucion_del_cliente_no_amplia_el_alcance`, `test_filtro_por_categoria_ajena_no_expone_catalogo_ajeno`, `test_rol_limitado_por_objeto_ajeno_siempre_oculta[Administrador|Bodeguero|Solicitante]`; `test_ambito_institucional.py::test_catalogo_no_incluye_productos_de_otra_institucion`. (487 passed, 5 skipped.)
- **AC-6** DADO stock para el mismo nombre de producto en INST-A e INST-B, CUANDO un usuario de INST-A consulta `/inventario/existencias`, `/inventario/stock` o `GET /tickets/catalogos`, ENTONCES el stock, departamentos, agregados y marca crítica corresponden exclusivamente a INST-A; ningún valor de INST-B influye en los resultados.
  - **Verificado:** `test_cobertura_ac_008.py::test_homonimos_son_registros_independientes_con_stock_propio` (mismo nombre «Cuaderno linedado», stock 50 de INST01 vs 5 de INST02); `test_ambito_institucional.py::test_administrador_existencias_acota_a_su_institucion`, `test_bodeguero_ajeno_existencias_solo_su_institucion`, `test_solicitante_existencias_solo_su_institucion`, `test_stock_administrador_solo_su_institucion`; `test_tickets_institucional.py::test_catalogos_solicitante_solo_su_institucion`, `test_catalogos_bodeguero_ajeno_no_suma_stock_propio`; `test_tickets_alcance.py::test_catalogo_productos_y_stock_son_institucionales`. (487 passed, 5 skipped.)
- **AC-7** Las lecturas de usuarios, departamentos, instituciones, tickets, movimientos y datos anidados mantienen el aislamiento definido en Feature 007. Los detalles de ticket no exponen nombres ni identificadores de productos de otra institución; Solicitante sigue limitado a sus tickets. `PATCH /tickets/{ticket_id}/estado` devuelve 404 si el ticket pertenece a otra institución para Administrador, Bodeguero o Solicitante, igual que si no existe, y no cambia su estado.
  - **Verificado:** `test_ambito_institucional.py::test_usuarios_administrador_solo_su_institucion`, `test_departamentos_administrador_solo_su_institucion`, `test_instituciones_administrador_solo_la_propia`, `test_movimientos_bodeguero_solo_su_institucion`; `test_tickets_alcance.py::test_solicitante_lista_solo_sus_tickets`, `test_administrador_patch_ticket_ajeno_404_sin_mutar`, `test_administrador_patch_ticket_inexistente_404`; `test_tickets_institucional.py::test_patch_ticket_ajeno_404_sin_cambiar`. (487 passed, 5 skipped.)
- **AC-8** DADO que existen datos para INST-A e INST-B, CUANDO Superadmin invoca una lectura global autorizada de inventario/catálogo, ENTONCES la respuesta contiene registros atribuibles explícitamente a ambas instituciones (separados o etiquetados); el stock de INST-A no aparece dentro de los registros atribuidos a INST-B.
  - **Verificado:** `test_ambito_institucional.py::test_superadmin_existencias_es_global_y_atribuye_institucion`, `test_superadmin_categorias_y_productos_atribuyen_institucion`, `test_superadmin_stock_es_global`; `test_cobertura_ac_008.py::test_homonimos_son_registros_independientes_con_stock_propio` (atribución `institucion_id` INST01/INST02 sin mezclar totales); `test_tickets_institucional.py::test_catalogos_superadmin_global_atribuye_institucion`. (487 passed, 5 skipped.)
- **AC-9** Un identificador de categoría/producto ajeno no habilita lectura, asignación, alta de ticket ni mutación. El acceso por objeto en `GET /inventario/productos/{producto_id}`, `GET /inventario/categorias/{categoria_id}`, `PATCH /tickets/{ticket_id}/estado` y `POST /tickets/{ticket_id}/despacho` responde 404 para recurso ajeno, igual que para uno inexistente, conforme a la ocultación 007. Un departamento ajeno en operaciones de lista/creación responde 403. Al crear ticket válido cuyo producto es ajeno, `POST /tickets/` responde 404 para ocultar ese producto, sin crear ticket ni detalle parcial.
  - **Verificado:** `test_ambito_institucional.py::test_producto_ajeno_responde_404_igual_que_inexistente`, `test_categoria_ajena_responde_404_igual_que_inexistente`, `test_crear_producto_con_categoria_ajena_responde_404_sin_persistir`, `test_existencias_departamento_ajeno_responde_403`, `test_stock_departamento_ajeno_responde_403`; `test_cobertura_ac_008.py::test_rol_limitado_por_objeto_ajeno_siempre_oculta` (GET por producto ajeno devuelve mismo 404 que ID inexistente); `test_tickets_institucional.py::test_crear_ticket_con_producto_ajeno_404_sin_parcial`, `test_patch_ticket_ajeno_404_sin_cambiar`; `test_tickets_alcance.py::test_bodeguero_despacho_ticket_ajeno_404_sin_mutar`. (487 passed, 5 skipped.)

### Aislamiento de escrituras y transacciones

- **AC-10** Administrador no puede asociar producto/categoría/usuario a una institución distinta a la suya ni crear inventario para departamento ajeno; cada denegación deja la base sin cambios. Superadmin recibe 403 al intentar crear/modificar catálogo, stock o tickets de una institución concreta; el Administrador de esa institución sí puede realizar las operaciones autorizadas por la matriz.
  - **Verificado:** `test_permisos_008.py::test_superadmin_deja_de_escribir_catalogo_stock_y_tickets`, `test_superadmin_no_muta_catalogo_stock_ni_tickets`, `test_administrador_conserva_las_escrituras_institucionales` y `test_operacion_ajustada_concede_o_deniega_por_rol` parametrizado (p. ej. `POST /inventario/productos` → Superadmin 403 / Administrador 200 / Bodeguero-Solicitante 403); `test_ambito_institucional.py::test_crear_producto_con_categoria_ajena_responde_404_sin_persistir`, `test_crear_producto_propio_queda_en_la_institucion_del_usuario`; `test_permisos_endpoints.py::test_rol_sin_permiso_recibe_403[...]`. (487 passed, 5 skipped.)
- **AC-11 — Aislamiento institucional al crear tickets (reemplaza el criterio histórico por la enmienda del 22/Oct/2026).** DADO un usuario autenticado con permiso vigente para crear tickets, CUANDO envía una solicitud válida con `usuario_id` omitido, propio, ajeno o inexistente, ENTONCES el valor de ese campo se ignora siempre y el ticket se atribuye a la identidad de sesión; `ticket.institucion_id` y `detalle_ticket.institucion_id` corresponden a la institución de esa identidad. CUANDO cualquiera de los productos del detalle pertenece a otra institución, ENTONCES `POST /tickets/` responde 404 y no deja ticket ni detalles parciales. Se conserva la ocultación 404 del producto ajeno, y no se altera la matriz de permisos.
  - **Evidencia (observada 22/Oct/2026):** `test_tickets_institucional.py::test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion` y `test_tickets_alcance.py::test_roles_autorizados_atienden_la_identidad_de_sesion` (el `usuario_id` ajeno se ignora) junto con `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`; anclas institucionales en `test_tickets_institucional.py::test_crear_ticket_puebla_institucion_en_ticket_y_detalle` y en el recorrido real (tickets 11 y 12 con `institucion_id INST-001` en cabecera y detalle, usuarios 13 y 11). 404 de producto ajeno conservado en `::test_crear_ticket_con_producto_ajeno_404_sin_parcial`; matriz intacta en **62** operaciones y Superadmin 403. Suites: SQLite **1405 passed / 77 skipped / 0 failed**, gated PostgreSQL 16 **1482 passed / 0 skipped / 0 failed**. Evidencia: [`evidencia/README.md`](evidencia/README.md).
- **AC-12** El despacho de un ticket de INST-A solo rebaja stock de INST-A y genera movimientos asociados a sus inventarios. Ante referencia cruzada, falta de stock o fallo transaccional, no cambia stock, detalle, ticket ni auditoría parcialmente.
  - **Verificado:** `test_tickets_institucional.py::test_despacho_producto_cruzado_409_sin_efectos`, `test_despacho_inventario_cruzado_409_sin_efectos`, `test_despacho_falta_stock_409_sin_efectos`, `test_despacho_valido_actualiza_stock_entrega_estado_y_auditoria`, `test_despacho_revierte_todo_si_el_commit_falla`. (487 passed, 5 skipped.)
- **AC-13** Las operaciones de movimiento de stock validan la institución del inventario antes de modificar cantidades; ningún movimiento de un usuario limitado cambia stock ajeno y los cambios exitosos conservan auditoría absoluta.
  - **Verificado:** `test_ambito_institucional.py::test_registrar_movimiento_en_inventario_ajeno_responde_403_sin_mutar` (403 y sin mutar stock/auditoría) y `test_registrar_movimiento_en_inventario_propio_responde_201` (201 con fila de auditoría). (487 passed, 5 skipped.)

### Migración y contrato

- **AC-14** La migración desde el esquema legado conserva instituciones, usuarios, departamentos, tickets, detalles, inventarios, movimientos e identificadores existentes. La regla para asignar categorías/productos legados queda documentada como comentario SQL en la propia migración y explicada en `plan.md`. Si un registro está asociado a más de una institución y su pertenencia es ambigua, la migración aborta antes de aplicar cambios destructivos, identifica explícitamente el registro en el mensaje de error y no pierde ni reasigna datos. Tras la corrección manual por el operador, puede reintentarse la migración.
  - **Verificado:** PostgreSQL 16 `test_migracion_postgres.py::test_migracion_preserva_filas_ids_y_agrega_constraints` y `test_migracion_aborta_ambiguedad_sin_cambios_y_reintenta_tras_corregir` (aborta nombrando el producto ambiguo, rollback completo sin columnas/constraints/filas, corrección manual y reintento exitoso). Sobre la base real `apt_erp`: la migración abortó con `008 migracion ABORTADA por ambiguedad institucional ... Ambiguos -> producto 4 referenciado por [INST-001, INST-002]; producto 9 referenciado por [INST-001, INST-003]`; corrección manual documentada vía psql (`UPDATE ticket SET usuario_id=6 WHERE ticket_id=3`, `UPDATE ticket SET usuario_id=5 WHERE ticket_id=5`) y reintento exitoso (`NOTICE: 008: migracion completada. Pertenencia institucional aplicada sin perdida de datos.`); conteos y IDs intactos (4/10/12/10/10/10/10/10/10; PK 1..N cada tabla). La regla de asignación está documentada en la cabecera de `database/98_migracion_particionamiento_institucional.sql` y en `plan.md` §1/§4.
- **AC-15** La migración es reproducible e idempotente: una segunda ejecución o ejecución sobre una base ya migrada termina sin duplicar, borrar ni alterar datos operativos adicionales.
  - **Verificado:** `test_migracion_postgres.py::test_migracion_segunda_ejecucion_es_idempotente` (mismos conteos y pertenencia; una sola `departamento_institucion_uk`). Base real `apt_erp`: segunda ejecución de `98_` → `NOTICE: 008: la base ya esta particionada (categoria.institucion_id existe). Migracion omitida (no-op).`; en instalación nueva (base temporal) `98_` también fue no-op sobre el esquema ya particionado de `01_esquema.sql`. (487 passed, 5 skipped; 492 passed con `POSTGRES_TEST_URL`.)
- **AC-16** Los endpoints afectados mantienen autenticación y autorización de 007: sesión ausente/no válida 401, rol sin permiso general 403, ámbito irresoluble 403 y ocultación 404 de recursos ajenos. Para búsqueda por objeto, se aplica en `GET /inventario/productos/{producto_id}`, `GET /inventario/categorias/{categoria_id}`, `PATCH /tickets/{ticket_id}/estado` y `POST /tickets/{ticket_id}/despacho`; el producto ajeno enviado en `POST /tickets/` también responde 404. El `/openapi.json` documenta las respuestas relevantes; Clerk no cambia.
  - **Verificado:** `test_auth_me_institucion.py::test_openapi_documenta_404_en_rutas_afectadas[7 rutas]` (la parametrización cubre productos por objeto, categorías por objeto, `POST /inventario/productos`, `POST /inventario/movimientos`, `POST /tickets/`, despacho y cambio de estado), `test_openapi_documenta_409_en_operaciones_de_ticket[despacho|estado]`, `test_openapi_carga_sin_errores`; `test_permisos_endpoints.py::test_inventario_de_rutas_igual_a_la_matriz_d3` (20 operaciones reales igualan la matriz), `test_sin_bearer_responde_401`, `test_bearer_invalido_responde_401`, `test_rol_sin_permiso_recibe_403[...]` y `test_rol_con_permiso_recibe_exito[...]`; `test_ambito_institucional.py::test_rol_limitado_sin_institucion_resoluble_responde_403`. Contrato vivo `http://localhost:8000/openapi.json`: `get productos/{producto_id}` → 200,401,403,404,422; `get categorias/{categoria_id}` → 200,401,403,404,422; `patch tickets/{ticket_id}/estado` → 200,401,403,404,409,422; `post tickets/{ticket_id}/despacho` → 200,401,403,404,409,422; `post tickets/` → 201,401,403,404,422. Clerk sin cambios (`test_auth.py`). (487 passed, 5 skipped.)
- **AC-17** `GET /auth/me` devuelve la institución efectiva derivada para Administrador, Bodeguero y Solicitante; para Superadmin indica explícitamente institución efectiva nula/ausente y conserva su carácter global. La respuesta no permite al cliente seleccionar ni alterar el ámbito.
  - **Verificado:** `test_auth_me_institucion.py::test_auth_me_roles_limitados_exponen_institucion_derivada[Administrador|Bodeguero|Solicitante]`, `test_auth_me_superadmin_expone_institucion_nula_explicita`, `test_auth_me_deriva_la_institucion_de_cada_usuario_no_de_un_valor_fijo`, `test_auth_me_no_acepta_institucion_del_cliente`; `test_auth_me_institucion.py::test_openapi_auth_me_publica_institucion_opcional`. Contrato vivo `IdentidadAutenticadaRespuesta`: `institucion` es requerido y `anyOf` (`InstitucionEfectivaRespuesta` | null). (487 passed, 5 skipped.)
- **AC-18** Las pruebas del servidor prueban aislamiento por rol, al menos dos instituciones, lecturas, referencias cruzadas, denegación sin mutación y agregados locales/globales en PostgreSQL 16 para restricciones/migración que SQLite no pueda validar. La suite `pytest` queda verde.
  - **Verificado:** suite completa `cd backend && python -m pytest` (venv) → **487 passed, 5 skipped** en SQLite en memoria; con `$env:POSTGRES_TEST_URL="postgresql://postgres:postgres@localhost:5433/postgres"` → **492 passed** (los 5 tests de `backend/tests/test_migracion_postgres.py` corren sobre PostgreSQL 16 real: FK compuestas, `NOT NULL` del DDL, migración, idempotencia y rollback por ambigüedad). Fixtures `dos_instituciones` (dos instituciones y cuatro roles) y archivos `test_ambito_institucional*.py`, `test_tickets_institucional.py`, `test_tickets_alcance.py`, `test_permisos_008.py`, `test_auth_me_institucion.py`, `test_modelo_particionamiento.py`, `test_cobertura_ac_008.py`.

### Cliente y cierre

- **AC-19** En el flujo cliente de una institución recorrido en 4200, la UI no muestra catálogo ni stock de otra institución; el contexto institucional mostrado coincide con el valor recibido de `GET /auth/me`; la navegación y denegación por roles de 007 se conservan; y `ng test` termina en verde.
  - **Verificado:** T13. Suites: `cd backend && .venv\Scripts\python.exe -m pytest` → **487 passed, 5 skipped**; `$env:CHROME_BIN=…msedge.exe; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` → **153 SUCCESS** (Edge 155). Recorrido en **4200** sobre el entorno real (backend 8000 + `apt_erp`, dev server) con dos sesiones Clerk reales (autoridad Clerk, login interactivo de la UI prebuilt con verificación de dispositivo; sin JWT local). INST-002 (B) se pobló con catálogo propio: categoría 11 «Papeleria» y inventario 14 (depto `AtencionPrimaria`) creados por SQL —no existen endpoints de escritura de categoría/inventario—, insumo **13 «Resma Carta 75g A4»** homónimo del producto 1 de INST-001 creado vía `POST /inventario/productos` (**201**, `institucion_id: INST-002`) y stock 30 vía `POST /inventario/movimientos` ENTRADA (201). Aislamiento de lectura (API y UI): `GET /inventario/categorias` → solo categoría 11; `GET /inventario/productos` → solo producto 13; `GET /inventario/existencias` → 1 insumo stock 30; la vista `/inventario` de la sesión B muestra **1 insumo** (única sede `AtencionPrimaria`, stock 20 tras despacho) y ningún registro de INST-001. Alta de ticket y **despacho real persistido**: `POST /tickets/` → ticket **25** (solicitante felipe usuario 8, producto 13, cantidad 10); `PATCH /tickets/25/estado` 2→3; `POST /tickets/25/despacho` → estado 4 `Cerrado`, `cantidad_entregada` 10; verificado con `docker exec compustock_db psql` en `apt_erp`: `inventario 14 stock 30→20`, `movimiento_inventario 15 SALIDA 10 «Despacho ticket_id=25; detalle_id=26; producto_id=13»` y `14 ENTRADA 30`. Superadmin: `/auth/me` con `institucion: null`; `GET /inventario/productos` → 11 (INST-001: 10, INST-002: 1) con el homónimo atribuido a cada institución (id 1/INST-001 vs id 13/INST-002); `GET /inventario/existencias` → «Resma Carta 75g A4» stock **120 (INST-001) vs 20 (INST-002)** sin mezclar; `POST /inventario/productos` y `POST /tickets/` → **403** «Permiso insuficiente para la operacion» sin mutación. Contexto UI (`/auth/me` en pantalla): header de la sesión limitada muestra **«Rol: Administrador / Institución: Centro de Salud Familiar Norte»** y la global **«Rol: Superadmin / Institución: Todas las instituciones»**; navegación y denegación por roles de 007 intactas (RolGuard/RUTA_ACCESO_DENEGADO). Setup de las dos identidades: usuarios Clerk de prueba `+clerk_test` (Backend API, correo verificado); el Administrador de INST-002 se dio de alta con `POST /usuarios/` real (**201**, usuario_id 15) y el Superadmin de prueba se insertó en `usuario` por SQL como bootstrap (sin autoridad previa para el alta).
- **AC-20** El esquema y los datos semilla nuevos representan la pertenencia institucional; la migración de instalación existente no depende de borrar el volumen ni volver a ejecutar la semilla destructiva.
  - **Verificado:** instalación nueva reproducible (base temporal `compustock_newinstall_check`, `01_esquema.sql` + `02_datos_semilla.sql` + `98_` + `99_`): homónimos por institución con stock independiente y 0 referencias cruzadas (producto–categoría, inventario–producto, detalle–producto, ticket–usuario), y `98_`/`99_` no-op sobre el esquema ya particionado. Migración de la base **existente real `apt_erp`** aplicada por `psql` (`cmd.exe /c "docker exec -i compustock_db psql -U postgres -d apt_erp -v ON_ERROR_STOP=1 < database\98_migracion_particionamiento_institucional.sql"`), sin borrar el volumen y sin ejecutar `02_datos_semilla.sql`: conteos preservados (4 instituciones, 12 usuarios, 10 departamentos, 10 categorías, 10 productos, 10 inventario, 10 movimientos, 10 tickets, 10 detalles), PK intactas (1..N), `institucion_id NOT NULL` y las 9 constraints compuestas presentes, `stock_total` 626 sin cambios. Como salvaguarda previa a la migración in-place se creó el backup temporal `backup_apt_erp_pre008.sql`; se utilizó durante la migración y fue borrado tras el cierre aprobado de la Feature 008 (AC-21).
- **AC-21** La feature solo se declara cerrada cuando todas las casillas de `tasks.md`, incluidos los checks de cierre, están `[x]`; cada AC de esta spec está marcado como verificado con su evidencia; `pytest` y `ng test` están verdes; el recorrido funcional con escrituras reales en 4200 y el recorrido de humo en 8080 tras reconstruir la imagen están documentados; y se revisaron las referencias documentales conforme a `AGENTS.md` §8.5.
  - **Verificado (T15 — cierre documental):** T1–T15 de `tasks.md` en `[x]` (incluidos los checks de cierre). Suites al cierre: `cd backend && .venv\Scripts\python.exe -m pytest` → **487 passed, 5 skipped** (SQLite en memoria); `$env:POSTGRES_TEST_URL="postgresql://postgres:postgres@localhost:5433/postgres"` → **492 passed** (PostgreSQL 16 real); `$env:CHROME_BIN=…msedge.exe; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` → **153 SUCCESS**. Grep de coherencia (`AGENTS.md` §8.7) sobre `AGENTS.md`, `.agents/skills/**`, `MEMORY.md` y los comentarios que citan la matriz: sin rutas rotas; `AGENTS.md` no mencionaba el conteo de operaciones y las skills no asumían catálogo global ni escritura de catálogo por Superadmin; se corrigieron las afirmaciones «18 endpoints/operaciones» ya obsoletas por el ajuste de la 008 (matriz de **20** operaciones) en `MEMORY.md` y en los comentarios de `backend/app/core/permisos.py`, `backend/tests/api/test_permisos.py` y `backend/tests/api/test_permisos_endpoints.py`. `MEMORY.md` reescrito (§10): la 008 pasa a «Estado actual», decisiones D-1…D-6 y aprendizajes (aborte fail-closed de la migración, tests PostgreSQL gated con `POSTGRES_TEST_URL`, `NOT NULL` endurecido). `roadmap.md` **no** se toca (el coordinator lo marca tras la validación del reviewer). El backup temporal `backup_apt_erp_pre008.sql`, usado como salvaguarda previa a la migración in-place, se borró tras el cierre aprobado de la Feature 008 (AC-21).
  - **Verificado (T14 — humo 8080 tras reconstruir):** `docker compose -f docker-compose.yml build frontend` (build de producción Angular OK, sin errores de presupuesto; bundle inicial 321.01 kB / 90.66 kB transfer) y `docker compose -f docker-compose.yml up -d frontend` (contenedor `compustock_frontend` **recreado**). Imagen nueva `sha256:cfdd5de44bc9ad…` (antes `815cfac1e0c1`, pre-008). Servido por nginx: `/`, `/inventario`, `/tickets` → **200 `text/html`** (`try_files` SPA) y el `index.html` referencia los hashes del build nuevo (`main-FJRVOZX4.js`, `styles-KWVWMOF.css`); proxy `/api/v1/auth/me` → 401. Humo con chrome-devtools en `http://localhost:8080`: sesión Clerk existente válida (sin JWT local); `/dashboard` muestra header **«Rol: Superadmin · Institución: Todas las instituciones»** (coherente con `/auth/me` → `institucion: null`); `/inventario` (Catálogo de Insumos) y `/tickets` (Kanban) y `/administracion` cargan; consola **sin errores** (solo el aviso benigno de «Clerk development keys»). El header con institución limitada («Institución: <nombre>») quedó evidenciado en 4200 (T13, sesión INST-002).

## 8. Restricciones

### Enmienda posterior al cierre: autoatribución de tickets — 22/Oct/2026

#### Problema

La AC-11 original exigía 404 ante un `usuario_id` de otra institución. La enmienda de autoatribución de la Feature 007 (AC-18…AC-20, 22/Oct/2026), alineada con 003, establece que todos los roles autorizados ignoran ese campo y crean el ticket con la identidad autenticada; por tanto, el 404 por solicitante ajeno dejó de ser observable y la regla quedó insostenible.

#### Qué cambia

Desaparece del contrato de alta el 404 por solicitante ajeno. `usuario_id` del payload se ignora siempre, conforme a AC-18…AC-20 de la 007: se omite o se envía, el ticket se atribuye a la identidad de sesión.

#### Qué no cambia

Se conserva intacto el 404 por producto ajeno de `_verificar_productos`: un producto de INST-B en un ticket de INST-A responde 404 y no deja ticket/detalles parciales. También se conservan las anclas `ticket.institucion_id` y `detalle_ticket.institucion_id` a la institución del usuario autenticado, el resto de AC-11 (referencias de producto, ausencia de escrituras parciales y semántica de ocultación) y la matriz de permisos.

#### Decisiones nuevas

- **D-7 — Prevalece la identidad de sesión sobre `usuario_id` del payload.** En toda alta autorizada se deriva la autoría y el ámbito institucional de la sesión, nunca del `usuario_id` recibido. No hay 404 por solicitante ajeno.
  - **Por qué:** aplica la autoatribución aprobada por 003/007; inspeccionar o rechazar el valor ignorado del payload contradiría ese contrato.
- **D-8 — La validación del producto ajeno permanece independiente.** Todo producto del detalle debe pertenecer a la institución de la sesión; producto de otra institución responde 404 sin persistencia parcial.
  - **Por qué:** la autoatribución redefine solo quién solicita; no relaja el aislamiento institucional de los productos ni la ocultación de recursos ajenos.

#### Criterio de aceptación enmendado

La AC-11 indicada en §7 sustituye íntegramente su formulación histórica. Su evidencia actual no se considera verificación de la nueva semántica. **A reescribir tras la enmienda, en implementación:** `test_crear_ticket_con_solicitante_ajeno_404_sin_parcial` y `test_administrador_crea_para_solicitante_de_otra_institucion_404_sin_mutar` deben dejar de exigir 404 y comprobar que el id ajeno se ignora, con autoría e institución de sesión. Actualizar también `test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion`, `test_administrador_crea_para_solicitante_propio_201` y `test_solicitante_crea_y_se_atribuye_su_identidad` para confirmar la regla para todos los roles autorizados. Conservar `test_crear_ticket_con_producto_ajeno_404_sin_parcial` como verificación del 404 de producto; conservar/confirmar `test_crear_ticket_puebla_institucion_en_ticket_y_detalle` para ambas anclas institucionales de sesión. No se marca ningún test nuevo como verificado en esta enmienda documental.

**Actualización 22/Oct/2026:** reescritura ejecutada; la evidencia observada de AC-11 está en
el AC (§7) y en [`evidencia/README.md`](evidencia/README.md).

#### Evidencia histórica afectada

La evidencia de rechazo por solicitante ajeno deja de ser vigente. Los tests que cubren identidad, producto ajeno y anclas institucionales se actualizarán o conservarán conforme a lo indicado en AC-11; no se declara verificación nueva ni se cambia el cierre original.

- Clerk permanece como autoridad única de autenticación; no se añade `institucion_id` confiable al token ni se acepta el ámbito declarado por el cliente como autorización.
- Se conservan literalmente los roles `Superadmin`, `Administrador`, `Bodeguero` y `Solicitante`; solo Superadmin tiene ámbito global. La matriz central de permisos de Feature 007 sigue siendo la fuente de autoridad por operación.
- La lógica de ámbito y las validaciones de pertenencia son del servidor. Guards, señales y selector visual, si existiera en el futuro, nunca constituyen seguridad.
- La institución de roles limitados continúa derivándose de departamento obligatorio. Si no se resuelve, la solicitud institucional se deniega con 403; nunca se degrada a global.
- Trazabilidad absoluta: toda variación de stock conserva su movimiento de auditoría. Consistencia ACID: despacho, stock, detalle, ticket y movimientos permanecen atómicos.
- La migración y el nuevo modelo requieren justificación aprobada en `docs/spec/stack.md` antes de implementarse; esta especificación no modifica dicho documento ni define la estructura técnica final.
