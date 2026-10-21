# Feature 014: Ciclo de vida del catálogo

**Estado:** aprobada y cerrada (20/Oct/2026)  
**Release:** 2.0 — backlog posterior al Sprint 6  
**Tipo:** Gobierno del catálogo institucional

## 1. Problema

La Feature 002 entregó consulta del catálogo y la 008 lo aisló por institución. El catálogo permite consultar productos y categorías, y crear productos como Administrador Institucional, pero no permite retirar ni reactivar productos o categorías existentes. Los artículos obsoletos permanecen disponibles para operaciones nuevas.

El borrado físico no es seguro: los productos pueden estar referenciados por stock por sede, movimientos de inventario y detalles de tickets, incluidos tickets cerrados o anulados. La 014 trata exclusivamente del ciclo de vida de registros existentes; no incorpora alta, edición ni CRUD de categorías.

**Mecanismo existente verificado:** no se encontró campo `activo`, estado equivalente ni operación de desactivación para `producto` o `categoria`; el DDL vigente tampoco declara esos campos. Esto no se confunde con los estados lógicos de sede/departamento o los registros de control.

## 2. Objetivo

Permitir al Administrador Institucional desactivar y reactivar productos y categorías existentes, conservando las referencias e historial de negocio, impidiendo usos operativos incompatibles y haciendo visible la vigencia en la vista actual de inventario.

## 3. Actores

- **Administrador Institucional:** gestiona el ciclo de vida del catálogo de su tenant y consulta su historial.
- **Bodeguero / Encargado de Suministros:** mantiene la operación de inventario y despacho conforme a las reglas de stock y tickets descritas en esta spec; no cambia la vigencia del catálogo ni consulta su historial.
- **Solicitante (Funcionario):** consulta productos disponibles y solicita productos mediante tickets; no cambia la vigencia ni consulta su historial.
- **Superadmin:** no opera ni consulta datos de negocio de los tenants; se conserva la denegación vigente desde la 017.

## 4. Alcance

### Dentro

- Estado binario reversible `activo`/`inactivo` para productos y categorías existentes.
- Desactivación y reactivación de producto/categoría por Administrador Institucional, con reglas de dependencia y de saldo.
- Motivo libre obligatorio de hasta 500 caracteres e historial inmutable de transiciones, consultable solo por Administrador de su tenant.
- Filtrado de productos y categorías inactivos en consultas y selectores operativos, sin ocultarlos en referencias históricas ni en la gestión administrativa.
- Reglas de compatibilidad con tickets nuevos/editados, tickets abiertos, movimientos, existencias y alertas del dashboard.
- La vista de inventario actual se divide en pestañas: gestión de categorías/productos y lista operativa de productos/existencias con filtros. La pestaña de gestión solo es visible para Administrador Institucional; comprobable con pruebas de Angular.
- Contratos de operación, autorización y aislamiento institucional; entradas nuevas y aditivas a la matriz central, sin cambiar las entradas existentes.
- Cambio de DDL y versionado de esquema descritos en §9 como prerrequisito de implementación, con justificación formal en `stack.md` durante la fase de plan.

### Fuera

- Alta, edición o CRUD de categorías; queda para una feature futura.
- Edición de productos; queda para una feature futura. El alta existente de producto se conserva, todo producto creado nace `activo` y el alta en categoría inactiva se rechaza con 409.
- Borrado físico de productos, categorías o referencias, stock, movimientos, tickets o historial.
- Cambio automático de stock, liquidación o transferencia de existencias como parte de una transición de catálogo.
- Modificación de los datos históricos de tickets y movimientos.
- Vista nueva de administración de catálogo separada de la vista actual de inventario.
- Gestión de proveedores, compras, reposición automática o auditoría general del catálogo.
- Cambio de Clerk, de las entradas existentes de la matriz central o de las capacidades institucionales vigentes.

## 5. Decisiones

### D-1 — Baja lógica; referencias y registros históricos se conservan

Desactivar un producto o categoría cambia su vigencia sin borrar ni modificar filas de stock, movimientos o detalles de tickets. Los identificadores y las relaciones permanecen estables; el historial de tickets y movimientos anteriores continúa resolviendo los datos de producto y categoría.

**Por qué:** `constitucion.md` §4.2 requiere trazabilidad absoluta de stock. Las Features 011 y 013 conservan hechos de negocio referenciados; el borrado físico destruiría evidencia o dejaría referencias rotas.

### D-2 — Mutación e historial reservados al Administrador Institucional

Solo el Administrador Institucional puede solicitar cambios de vigencia y consultar el historial, dentro de su tenant. La autorización por rol de la matriz central y el gating adicional de capacidad `catalogo` se aplican independientemente. Bodeguero, Solicitante y Superadmin no pueden mutar; solo el Administrador obtiene lectura de historial.

**Por qué:** la matriz vigente reserva la escritura de catálogo al Administrador y la 012 separa autorización de rol de disponibilidad funcional. Ninguna vista o guard sustituye autorización backend.

### D-3 — Sin borrado físico

No existe operación de borrado físico, aunque un registro parezca no tener referencias.

**Por qué:** una política única evita carreras entre comprobación y borrado, mantiene la integridad de referencias y permite conservar trazabilidad futura.

### D-4 — Ciclo binario reversible

Producto y categoría tienen únicamente los estados `activo` e `inactivo`. Ambos pueden transitar en cualquier dirección; no hay estados terminales. Producto nuevo nace `activo`. Repetir una operación para el estado ya persistido es idempotente: responde 200 con el recurso en su estado actual, no exige motivo y no crea una transición de historial.

**Por qué:** la reactivación debe restaurar el uso sin recrear entidades ni referencias. El historial documenta las transiciones reales, no reintentos sin cambio.

### D-5 — No se desactiva una categoría con productos activos

Desactivar una categoría responde 409 si existe al menos un producto activo vinculado. Para resolverlo, cada producto activo de la categoría debe desactivarse primero; cada uno debe cumplir la condición de saldo cero de D-6. Después de desactivar todos sus productos, puede desactivarse la categoría. Los productos inactivos conservan su categoría y no se reasignan ni eliminan. Reactivar la categoría no reactiva ninguno de sus productos.

No puede existir producto activo en categoría inactiva: si la categoría está inactiva, reactivar cualquiera de sus productos responde 409. Para reanudarlo, primero se reactiva la categoría y luego el producto, sujeto a las precondiciones restantes.

**Por qué:** `producto.categoria_id` es obligatorio y la categoría sigue siendo necesaria para interpretar datos actuales e históricos. La dependencia protege la coherencia operativa y evita artículos activos bajo una clasificación retirada.

### D-6 — La baja de producto exige saldo cero en `stock_sede`

Desactivar un producto responde 409 si cualquiera de sus filas vigentes en `stock_sede` tiene saldo positivo. El Administrador debe liquidar todo el saldo mediante movimientos de inventario auditados y reintentar. No tener filas en `stock_sede` equivale a saldo cero. El criterio se mide exclusivamente en `stock_sede`; las filas legadas congeladas de `inventario` no son saldo operativo ni participan en esta precondición. La transición de catálogo nunca altera saldos ni crea movimientos.

La comprobación de saldo y el cambio de estado deben ser atómicos frente a escrituras concurrentes: no se acepta una carrera que permita desactivar el producto mientras una operación concurrente crea saldo positivo. La operación de movimientos y la transición deben coordinarse con aislamiento/bloqueo suficiente para serializar el resultado; si la precondición deja de cumplirse, la transición responde 409 sin mutación.

**Por qué:** el saldo físico vigente es por sede (`stock_sede`, Feature 011); todo cambio debe quedar auditado. `inventario` es legado congelado. La atomicidad evita una ventana entre verificar cero y marcar inactivo, siguiendo el principio de concurrencia de Feature 005.

### D-7 — Visibilidad según superficie; historia preservada

Producto inactivo y cualquier producto cuya categoría esté inactiva se excluyen de `GET /inventario/existencias`, de los listados operativos del catálogo, de las consultas de disponibilidad y de los selectores de producto para crear tickets. Las categorías inactivas se excluyen de filtros/selectores operativos. Por tanto, un producto inactivo no se puede solicitar en un ticket nuevo.

En edición de un ticket `Pendiente`, se puede conservar un ítem que ya referencia un producto inactivo, pero no añadir un producto inactivo nuevo ni reemplazar el ítem por uno inactivo. El despacho de tickets ya abiertos sigue el flujo vigente sin regla especial de catálogo; si el saldo es cero, se aplica el resultado vigente por stock insuficiente, sin que la baja cambie el ticket.

Los movimientos nuevos sobre un producto inactivo responden 409. No se impone regla especial a consultas de movimientos previos: historial de movimientos y detalles/historiales de tickets anteriores siguen resolviendo producto y categoría aunque estén inactivos.

El dashboard de la 009 excluye productos inactivos (y productos cuya categoría esté inactiva) tanto del cálculo de stock crítico como del listado/conteo de alertas. Los listados operativos existentes permanecen filtrados para todos los roles, incluido el Administrador. La vista de inventario se presenta en dos pestañas: «Gestión del catálogo» reúne la gestión de categorías y productos, y «Existencias» contiene la lista operativa y sus filtros. La pestaña de gestión solo se muestra al Administrador y se alimenta exclusivamente del listado de gestión nuevo; los roles no Administradores no ven el conmutador ni una pestaña de gestión vacía o bloqueada, y conservan directamente la vista operativa.

**Decisiones de presentación:** al entrar, la pestaña seleccionada por defecto es «Existencias», por ser la superficie operativa común a todos los roles. Para Bodeguero y Solicitante no se renderiza el conmutador; se muestra solo esa vista operativa, igual que antes.

**Por qué:** separar consultas de uso futuro de las referencias históricas evita nuevas solicitudes o movimientos incompatibles sin perder evidencia. La integración en la vista de inventario satisface la administración sin duplicar una superficie ni cambiar el acceso operativo vigente.

### D-8 — Motivo libre e historiales de transiciones del catálogo

Todo cambio real de estado de producto o categoría requiere motivo de texto libre obligatorio, no vacío ni compuesto solo por espacios, con longitud máxima de 500 caracteres. No se usa el catálogo de motivos de la 017. El estado y exactamente una transición en la tabla de historial correspondiente, con actor, instante, recurso, estado anterior, estado nuevo y motivo, deben persistirse juntos o no persistirse.

El historial se compone de **dos tablas de hechos de transición**: una asociada exclusivamente a producto y otra exclusivamente a categoría. Cada fila referencia directamente un único recurso del tipo correspondiente, evitando una FK polimórfica ambigua. Ambas tablas son inmutables, solo lectura por API y visibles únicamente al Administrador Institucional de su tenant; no existen operaciones independientes de alta, edición o borrado.

Las dos tablas constituyen **dos entidades de dominio**, la 16.ª (historial de transición de producto) y la 17.ª (historial de transición de categoría); no son estructuras auxiliares. Cada una registra un hecho de negocio con actor, fecha, motivo y estado origen/destino, participa en relaciones reales con su recurso y es legible mediante API. Antes de planificar su implementación, la justificación formal de ambas entidades y sus relaciones debe incorporarse y aprobarse en `docs/spec/stack.md` conforme a AGENTS.md §7. Esta spec fija el qué y el porqué; la actualización de `stack.md` corresponde a la fase de plan.

Ambas tablas tendrán paridad estructural en `control` y en cada esquema tenant, siguiendo el precedente de `historial_transicion_ticket` (013). Así, el modelo de dominio pasa de 15 a **17 entidades**.

**Por qué:** la disponibilidad del catálogo afecta solicitudes e inventario; reconstruir quién cambió cada recurso, cuándo y por qué garantiza explicabilidad. Separar las tablas por tipo hace verificables sus referencias y evita relaciones polimórficas no comprobables mediante FK.

### D-9 — Operaciones y precedencia de validación

Las operaciones de transición expresan el estado destino (`activo` o `inactivo`) para el recurso indicado; éxito devuelve el recurso con su estado persistido. Una transición efectiva responde 200 y registra exactamente una transición de historial; una repetición idempotente responde 200, devuelve el estado actual y no exige ni registra transición. La lectura del historial es una operación independiente, solo de lectura y limitada al Administrador de su tenant.

El orden de validación para mutaciones es: (1) autenticación, 401; (2) matriz de permisos de rol, 403; (3) capacidad `catalogo`, 403; (4) existencia y pertenencia tenant, recurso inexistente/ajeno con 404 idéntico; (5) si el destino ya es el estado actual, devolver 200 idempotente sin motivo, precondiciones ni transición; (6) validar motivo, 422; (7) evaluar precondiciones de negocio, 409. Así una baja repetida de producto ya inactivo sigue siendo idempotente aunque, después de la baja, haya aparecido saldo positivo. Toda denegación o fallo en pasos 1–4, 6–7 deja estado e historiales intactos.

Para leer historial se aplica autenticación → matriz (solo Administrador) → capacidad `catalogo` → existencia/pertenencia del recurso (404 oculto) → respuesta ordenada determinísticamente. Un rol no autorizado recibe 403 antes de consultar el recurso, sin revelar si existe.

**Por qué:** reproduce el patrón de autorización y ocultamiento de la 013, incorpora el gating de la 012 y evita que un reintento idempotente quede bloqueado por datos que solo son relevantes para una transición real.

## 6. Reglas del flujo

1. Clerk autentica la identidad; el servidor resuelve el tenant. El cliente no selecciona institución ni esquema.
2. Solo Administrador Institucional muta ciclo de vida y lee historial. Matriz central y capacidad `catalogo` se evalúan por separado; entradas de permisos nuevas son aditivas y las entradas existentes permanecen intactas.
3. El alta vigente de producto solo crea en categoría activa; intentar crear en categoría inactiva responde 409 sin escritura. El producto creado nace activo.
4. Para una mutación se aplica el orden de D-9. Si el recurso ya está en el destino, responde 200 sin exigir motivo ni verificar precondiciones, y sin transición de historial.
5. Para una transición real, el motivo es obligatorio, libre, no vacío/no solo espacios y de hasta 500 caracteres. El cambio de estado y la transición de historial son atómicos.
6. Desactivar producto requiere que todos sus saldos en `stock_sede` sean cero; `inventario` legado no cuenta. El chequeo y transición se coordinan frente a movimientos concurrentes. El cambio de catálogo no altera stock.
7. Desactivar categoría requiere que todos sus productos estén inactivos. Por D-6, cada producto que se desactive primero debe tener saldo cero. Baja de categoría y alta/reactivación de producto se serializan para preservar la invariante, comprobando vigencia dentro de la misma transacción con bloqueo suficiente.
8. Reactivar producto requiere categoría activa. Reactivar categoría no reactiva productos. No hay cascada automática en ninguna dirección.
9. Consultas operativas de catálogo/existencias y selectores omiten productos inactivos o con categoría inactiva; filtros/selectores operativos omiten categorías inactivas. No se pueden añadir productos inactivos nuevos a tickets, pero una edición de ticket `Pendiente` puede conservar el ítem inactivo existente solo si su `producto_id` ya figura en los detalles actuales.
10. `POST /inventario/movimientos` sobre producto inactivo devuelve 409. Tickets ya abiertos siguen su flujo vigente; el despacho no tiene excepción y el stock cero resulta en el fallo vigente de stock insuficiente.
11. Dashboard 009 excluye inactivos del stock crítico y alertas. Los detalles e historiales previos de tickets y movimientos continúan resolviendo producto y categoría.
12. La sección de ciclo de vida de la vista actual se alimenta del listado de gestión para Administrador, que devuelve productos y categorías activos e inactivos con su estado; los listados operativos permanecen filtrados.

## 7. Contrato de las operaciones (semántica)

- La mutación expresa el estado destino del producto o categoría y devuelve **200** con el recurso y estado persistidos, tanto para una transición efectiva como para una repetición idempotente. La idempotencia no exige motivo ni agrega historial.
- El historial se consulta por recurso, en solo lectura, orden más reciente primero con desempate estable. Solo Administrador Institucional tiene permiso de lectura.
- El listado de gestión para Administrador devuelve productos y categorías de su tenant, activos e inactivos, con estado incluido. La sección administrativa de la vista de inventario se alimenta de ese listado y no de los listados operativos filtrados.
- Códigos y precedencia de validación son los definidos en D-9; las rutas y payloads concretos se fijan en el plan técnico, sin cambiar esta semántica.

## 8. Criterios de aceptación

- [x] **AC-1 — Conservación de referencias y ausencia de borrado.** DADO un producto o categoría referenciado por stock, movimientos o detalles de tickets, CUANDO cambia a inactivo, ENTONCES no se borra ni altera ninguna referencia, saldo, movimiento o dato de ticket. No existe operación de borrado físico.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_catalogo_estado_014.py` — `test_baja_conserva_referencias_stock_movimientos_y_tickets_ac_1` y `test_no_existe_operacion_de_borrado_fisico_ac_1`; OpenAPI sin `DELETE`; recorrido `evidencia/README.md` §4 (producto, `stock_sede`, `movimiento_inventario` y `detalle_ticket` sin borrados; la baja solo añade historial).
- [x] **AC-2 — Autorización, gating y aislamiento.** DADO cada operación nueva, ENTONCES el Administrador Institucional de su tenant es el único autorizado; Bodeguero, Solicitante y Superadmin reciben 403 para mutación e historial. Un rol sin permiso recibe 403 antes de inspeccionar el recurso. Capacidad `catalogo` deshabilitada devuelve 403 sin mutación. Un recurso inexistente y uno de otro tenant responden 404 idéntico para un rol autorizado. Las entradas existentes de la matriz no cambian y las nuevas son aditivas.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_autorizacion_014.py` — `test_matriz_declara_las_cinco_operaciones_exclusivas_del_administrador_ac_2`, `test_matriz_conserva_las_operaciones_previas_intactas_ac_2`, `test_matriz_tiene_exactamente_60_operaciones_tras_014`, `test_capacidad_catalogo_asociada_a_las_cinco_operaciones_ac_2`, `test_sin_sesion_responde_401_ac_2`, `test_mutacion_de_rol_no_administrador_recibe_403_antes_del_recurso`, `test_recurso_ajeno_e_inexistente_responden_404_identico_ac_2` y `test_capacidad_catalogo_apagada_bloquea_las_cinco_operaciones_sin_mutar_ac_2`; recorrido `evidencia/README.md` §3.6 (P46–P58: 403 por rol, 404 idéntico ajeno/inexistente).
- [x] **AC-3 — Fallos sin efectos y precedencia.** DADO un intento de transición, CUANDO falla autenticación, permiso, capacidad, pertenencia, validación de motivo o precondición, ENTONCES aplica el código ordenado de D-9 y no cambia estado, stock, movimientos ni historial. En particular, 404 de ámbito precede al motivo inválido; motivo inválido responde 422 antes de evaluar precondiciones que darían 409.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_404_de_ambito_precede_al_motivo_invalido_ac_3`, `test_404_de_categoria_oculta_antes_del_motivo_ac_3`, `test_motivo_invalido_precede_a_la_precondicion_409_ac_3`, `test_orden_observable_de_validacion_ac_3` y `test_fallo_de_autorizacion_no_escribe_estado_ni_historial_ac_3`; recorrido `evidencia/README.md` §3.1 (P10–P12) y §3.2–§3.4 (P19, P23, P32, P33, P40, P41: 409/422 sin escritura).
- [x] **AC-4 — Inactivos excluidos de operaciones y existencias.** DADO un producto inactivo o asociado a una categoría inactiva, CUANDO un rol operativo consulta catálogo, disponibilidad o `GET /inventario/existencias`, ENTONCES el producto no aparece; las categorías inactivas tampoco aparecen en filtros/selectores operativos. DADO historial de ticket/movimiento anterior, ENTONCES el producto y categoría siguen resolviéndose en esa referencia histórica.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_operativas_014.py` — `test_existencias_excluye_producto_inactivo_y_categoria_inactiva_ac_4`, `test_listados_operativos_excluyen_inactivos_para_todos_los_roles_ac_4`, `test_catalogos_de_ticket_excluyen_producto_inactivo_ac_4` y `test_referencias_historicas_siguen_resolviendo_inactivos_ac_4`; `backend/tests/services/test_ciclo_vida_operativas_servicio_014.py` (filtro conjunto en existencias, catálogo, stock por sede y catálogos de ticket); recorrido `evidencia/README.md` §3.1 P16/P17, §3.4 P38/P42, §5 U8/U9.
- [x] **AC-5 — Dependencia de categoría y creación.** DADO una categoría con al menos un producto activo, CUANDO el Administrador intenta desactivarla, ENTONCES recibe 409 y no se modifica categoría ni historial. Una categoría sin productos puede desactivarse libremente; equivalentemente, la condición de que todos sus productos estén inactivos se cumple vacíamente. Cuando todos sus productos están inactivos, la categoría se puede desactivar y sus referencias se conservan. Reactivar la categoría no reactiva sus productos. DADO una categoría inactiva, CUANDO se intenta reactivar un producto o crear uno nuevo en ella, ENTONCES responde 409 sin cambio, historial ni escritura de producto; al reactivar primero la categoría, reactivar producto puede proceder si cumple las demás precondiciones.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_baja_categoria_con_producto_activo_responde_409_ac_5`, `test_baja_categoria_sin_productos_procede_ac_5`, `test_baja_categoria_con_todos_sus_productos_inactivos_y_sin_cascada_ac_5`, `test_reactivacion_producto_bajo_categoria_activa_procede_ac_5` y `test_reactivacion_producto_bajo_categoria_inactiva_responde_409_ac_5`; `test_alta_en_categoria_inactiva_responde_409_sin_escritura_ac_13`; recorrido `evidencia/README.md` §3.3 (P23, P31–P35: 409, baja, reactivación en orden y sin cascada).
- [x] **AC-6 — Saldo cero y concurrencia.** DADO un producto con saldo positivo en cualquier `stock_sede`, CUANDO se intenta desactivar, ENTONCES responde 409 y no cambia producto, stock, movimientos ni historial. DADO todos los saldos por sede iguales a cero o sin filas, ENTONCES puede desactivarse. Las filas legadas de `inventario` no afectan el resultado. DADO una operación concurrente de stock, ENTONCES no puede intercalarse con la desactivación para producir un producto inactivo con saldo positivo: se serializa/rechaza una de las operaciones de forma verificable en PostgreSQL 16.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_baja_producto_con_saldo_positivo_responde_409_sin_efectos_ac_6`, `test_baja_producto_sin_filas_de_stock_procede_ac_6`, `test_baja_producto_con_saldos_en_cero_procede_ac_6` y `test_inventario_legado_positivo_no_impide_la_baja_ac_6`; gated `backend/tests/test_ciclo_vida_catalogo_postgres_014.py::test_escenario_concurrente_baja_de_producto_frente_a_entrada_de_stock_ac_6` (4 anillos, ambos órdenes) y `test_rollback_de_una_entrada_no_confirmada_deja_la_baja_proceder`; recorrido `evidencia/README.md` §3.2 (P19–P21).
- [x] **AC-7 — Motivo e historial en transición efectiva.** DADO una transición real de producto o categoría, CUANDO falta el motivo, está vacío, solo contiene espacios o excede 500 caracteres, ENTONCES responde 422 sin cambios. CON motivo válido de hasta 500 caracteres, ENTONCES responde 200 y persiste exactamente una transición inmutable en la tabla correspondiente, con actor, instante, recurso, estado anterior/nuevo y motivo, en la misma operación que el estado. El motivo es texto libre, no un código del catálogo 017.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_motivo_invalido_responde_422_sin_cambios_ac_7` (parametrizado: ausente, vacío, solo espacios, >500) y `test_motivo_de_500_caracteres_se_persiste_exacto_ac_7`; `test_ciclo_vida_catalogo_014.py::test_motivo_de_500_caracteres_se_persiste_literal` y `test_fallo_al_escribir_el_historial_revierte_el_estado`; recorrido `evidencia/README.md` §3.1 (P04/P05/P08/P15) y §5 U4/U6.
- [x] **AC-8 — Idempotencia sin motivo ni precondiciones.** DADO producto o categoría ya en el estado destino, CUANDO el Administrador repite la operación con motivo ausente o inválido, y aun si hoy incumple una precondición que correspondería a una transición efectiva (p. ej. producto inactivo con saldo positivo), ENTONCES responde 200 con el recurso en el estado actual, no cambia nada y no crea historial. La verificación de estado actual precede motivo y precondiciones.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_repeticion_idempotente_responde_200_sin_motivo_ni_historial_ac_8` y `test_idempotencia_no_evalua_la_precondicion_de_saldo_ac_8`; `test_ciclo_vida_catalogo_014.py::test_repeticion_idempotente_no_exige_motivo_ni_escribe_historial` y `test_idempotencia_no_evalua_la_precondicion_de_saldo`; recorrido `evidencia/README.md` §3.1 (P06/P07/P09: 200 sin fila nueva).
- [x] **AC-9 — Tickets, movimientos y despacho.** DADO un producto inactivo, CUANDO se intenta añadirlo en alta o edición de ticket, ENTONCES responde 409 (producto existente pero no disponible) y no hay escritura parcial, salvo la conservación delimitada a continuación. DADO edición de ticket `Pendiente`, CUANDO el `producto_id` inactivo ya figura en los detalles actuales del mismo ticket, ENTONCES se permite conservar el ítem y modificar su cantidad; CUANDO el producto inactivo no figura ya en esos detalles, ENTONCES se rechaza añadirlo con 409. DADO `POST /inventario/movimientos` sobre producto inactivo, ENTONCES responde 409 sin cambios. DADO ticket abierto previo al retiro, ENTONCES su despacho sigue el flujo vigente sin regla especial de catálogo; con saldo cero falla conforme al error vigente por stock insuficiente y no se alteran datos parcialmente.
  - **Evidencia:** `test_ciclo_vida_operativas_014.py` — `test_movimiento_sobre_producto_inactivo_responde_409_sin_cambios_ac_9`, `test_alta_de_ticket_con_producto_inactivo_responde_409_sin_escritura_ac_9`, `test_edicion_pendiente_conserva_inactivo_existente_y_cambia_cantidad_ac_9`, `test_edicion_pendiente_rechaza_inactivo_no_presente_ac_9` y `test_despacho_abierto_con_saldo_cero_conserva_el_error_vigente_ac_9`; servicio homónimo en `test_ciclo_vida_operativas_servicio_014.py`; `frontend/.../ticket-detalle.component.spec.ts` (conserva/cantidad, no ofrece en línea nueva, 409 visible) y `tickets.component.spec.ts` («alta sin productos inactivos (AC-4, AC-9)»); recorrido `evidencia/README.md` §3.4 (P22, P39–P45) y §5 U8/U9.
- [x] **AC-10 — Dashboard y alertas.** DADO productos activos e inactivos y categorías activas e inactivas, CUANDO se consulta el dashboard de la 009, ENTONCES productos inactivos o pertenecientes a categoría inactiva no contribuyen al stock crítico, conteo ni listado de alertas; las fórmulas y ámbitos del resto del dashboard se conservan.
  - **Evidencia:** `test_ciclo_vida_operativas_014.py::test_dashboard_excluye_inactivos_de_alertas_y_conteo_ac_10`; `test_ciclo_vida_operativas_servicio_014.py::test_dashboard_excluye_inactivos_de_alertas_y_conteo` y `test_dashboard_conserva_los_demas_kpi`; recorrido `evidencia/README.md` §3.5 (P27 → P30: `total_alertas` 3 → 1 sin mover `unidades_en_stock` ni `tickets_activos`).
- [x] **AC-11 — Interfaz de inventario en pestañas (enmienda de presentación posterior al cierre).** DADO un Administrador Institucional autenticado, CUANDO abre la vista de inventario, ENTONCES ve dos pestañas: «Gestión del catálogo», con categorías y productos activos/inactivos, estado visible, acciones de transición e historial; y «Existencias», con la lista operativa y sus filtros. La pestaña de gestión consume exclusivamente el listado de gestión. La pestaña seleccionada por defecto es «Existencias». `ng test` verifica renderizado, navegación entre pestañas, visibilidad por rol, envío de motivo, respuesta idempotente y estados 409/422/error. DADO Bodeguero o Solicitante, ENTONCES no ven conmutador ni pestaña de gestión, sino solo la vista operativa de Existencias, sin acciones de mutación. La autorización, endpoints, filtros y reglas de negocio permanecen sin cambios; no se crea una vista administrativa nueva.
  - **Evidencia:** `frontend/src/app/features/inventario/inventario.component.spec.ts` — bloques «sección de gestión por rol (AC-11)» y «sección de gestión del Administrador (AC-11/AC-15)» (renderizado, 200 idempotente, 409/422 visibles, motivo obligatorio, historial); `core/auth/roles.spec.ts` (`puedeGestionarCatalogo`); recorrido `evidencia/README.md` §5 U1–U7/U10 y humo 8080 §6.1 S1–S4, con capturas `4200-inventario-administrador-gestion.png`, `4200-historial-producto.png`, `4200-inventario-bodeguero-sin-gestion.png` y `8080-inventario-administrador-gestion.png`.
- [x] **AC-12 — Lectura de historial y ocultamiento.** DADO un Administrador autenticado y capacidad `catalogo` habilitada, CUANDO consulta el historial de un recurso de su tenant, ENTONCES obtiene sus transiciones en orden determinista con actor, instante, recurso, estado origen/destino y motivo. Recurso ajeno/inexistente devuelve 404 idéntico. Bodeguero, Solicitante y Superadmin reciben 403 antes de consultar el recurso. OpenAPI no expone alta, edición ni borrado de ninguna tabla de historial.
  - **Evidencia:** `test_ciclo_vida_autorizacion_014.py` — `test_historial_no_expone_escritura_ac_12`, `test_historial_y_gestion_reciben_403_para_no_administradores_ac_12_15`, `test_historial_devuelve_las_transiciones_recientes_primero_ac_12` y `test_historial_de_categoria_registra_solo_sus_transiciones_ac_12`; `test_ciclo_vida_catalogo_014.py::test_historial_de_producto_ordena_reciente_primero_y_resuelve_actor`; recorrido `evidencia/README.md` §3.1 P05/P15, §3.3 P36/P37, §3.6 P48/P51/P54/P57 y §5 U6; OpenAPI con solo `GET` en cada path de historial.
- [x] **AC-13 — Estado inicial y alta en categoría activa.** DADO una creación de producto mediante el alta vigente en categoría activa, ENTONCES el producto nace `activo`. DADO categoría inactiva, CUANDO se intenta crear producto, ENTONCES responde 409 sin escritura. Ningún cambio habilita creación de categoría ni edición de producto.
  - **Evidencia:** `test_ciclo_vida_catalogo_estado_014.py` — `test_producto_nuevo_nace_activo_ac_13` y `test_alta_en_categoria_inactiva_responde_409_sin_escritura_ac_13`; `test_ciclo_vida_catalogo_014.py::test_alta_de_producto_nace_activo_en_categoria_activa` y `test_alta_en_categoria_inactiva_responde_409_sin_escribir`; recorrido `evidencia/README.md` §3.1 P03 (201 con `activo:true`) y §3.3 P32 (409); OpenAPI sin `POST` de categorías ni `PUT` de producto.
- [x] **AC-14 — Contrato y versionado de esquema.** DADO las nuevas operaciones, CUANDO se inspecciona `/openapi.json`, ENTONCES cada una publica éxito y las clases de error que le aplican: mutaciones y lecturas de historial documentan autorización, recurso oculto (404), conflicto (409) y validación (422); el listado de gestión documenta éxito, autenticación (401) y autorización (403). DADO instalación limpia, ENTONCES la versión objetivo `014.1` y la estructura (columnas de estado y las dos tablas de historial) están presentes en `control`; las filas de productos y categorías con estado `activo` se verifican en cada tenant antes de admitir enrutamiento de negocio. El conteo pasa de 20 a **22 tablas en control** y de 17 a **19 tablas por tenant**. El arranque limpio y los tests gated de instalación verifican estructuras y conteos.
  - **Evidencia:** `test_ciclo_vida_autorizacion_014.py` — `test_openapi_publica_las_cinco_operaciones_ac_14`, `test_openapi_tiene_60_operaciones_tras_014`, `test_openapi_documenta_errores_de_mutaciones_e_historial_ac_14` y `test_openapi_documenta_gestion_con_401_y_403_ac_14`; gated `test_ciclo_vida_catalogo_postgres_014.py` — `test_el_codigo_apunta_a_la_version_014_1`, `test_instalacion_limpia_crea_22_tablas_en_control_y_19_por_tenant`, `test_instalacion_limpia_crea_estado_e_historiales_en_control_y_tenants`, `test_semilla_deja_productos_y_categorias_activos_en_cada_tenant` y `test_paridad_estructural_de_los_historiales_entre_control_y_tenant`; `test_esquema_postgres.py` y `test_instalacion_limpia_postgres.py`; recorrido `evidencia/README.md` §1 (22/19, `014.1`, historiales vacíos) y §3/§6 (60 operaciones).
- [x] **AC-15 — Listado de gestión para Administrador.** DADO un Administrador Institucional con capacidad `catalogo` habilitada, CUANDO consulta el listado de gestión, ENTONCES obtiene productos y categorías activos e inactivos de su tenant con su estado incluido. Bodeguero, Solicitante y Superadmin reciben 403; el ámbito tenant no se puede elegir desde el cliente. La sección administrativa de inventario se alimenta exclusivamente de este listado nuevo. Los listados operativos existentes siguen filtrados para todos los roles, incluido el Administrador.
  - **Evidencia:** `test_ciclo_vida_autorizacion_014.py::test_gestion_incluye_activos_e_inactivos_solo_para_administrador_ac_15` y `test_historial_y_gestion_reciben_403_para_no_administradores_ac_12_15`; `test_ciclo_vida_catalogo_014.py::test_gestion_incluye_activos_e_inactivos_del_tenant`; `test_ciclo_vida_operativas_servicio_014.py::test_listados_de_catalogo_excluyen_inactivos_para_administrador`; `inventario.component.spec.ts` («se alimenta solo de /gestion…»); recorrido `evidencia/README.md` §3.1 P02/P18 y §5 U2.
- [x] **AC-16 — Concurrencia categoría-producto.** DADO una operación concurrente de desactivación de categoría y alta/reactivación de un producto perteneciente a ella, ENTONCES las comprobaciones de vigencia y las escrituras se serializan dentro de transacciones coordinadas con bloqueo suficiente: no puede persistir una categoría inactiva con producto activo. Una operación puede completarse primero; la otra se acepta solo si la invariante sigue cumpliéndose, de lo contrario se rechaza sin cambios ni historial. Se verifica contra PostgreSQL 16.
  - **Evidencia:** gated `test_ciclo_vida_catalogo_postgres_014.py::test_escenario_concurrente_baja_de_categoria_frente_a_alta_de_producto_ac_16` y `test_escenario_concurrente_baja_de_categoria_frente_a_reactivacion_ac_16` (dos conexiones, `Barrier(2)`, 4 anillos con ambos órdenes de lock; invariante: nunca categoría inactiva con producto activo); bloque gated 014+013 en verde **26 passed / 0 failed** (T13; total gated del repo **70 passed**).

## 9. Restricciones y prerrequisitos de modelo/esquema

- `constitucion.md` §4.2: ningún cambio de stock ocurre sin movimiento inmutable; el ciclo de vida no toca stock ni crea movimientos.
- `constitucion.md` §4.3 aporta el principio de consistencia transaccional que sustenta la regla de esta feature: cambio de estado e historial se persisten juntos o ninguno.
- Feature 011: `stock_sede` es la fuente operativa vigente; `inventario` legado congelado no se usa para decidir si puede retirarse un producto.
- Features 002/008/012: catálogo aislado por institución; `catalogo` es gating adicional a la matriz, nunca permiso. El ámbito se deriva en servidor.
- Feature 013: autorización, orden de respuestas, motivo de hasta 500 caracteres, historial inmutable, atomía y códigos 401/403/404/409/422 siguen el patrón establecido, adaptado a las reglas aquí especificadas.
- La Feature 014 cambia el esquema: añade estados de vigencia a productos/categorías y dos tablas de historial. La versión objetivo avanza de `013.1` a **`014.1`**, coordinada con `VERSION_ESQUEMA_OBJETIVO`. DDL, inicialización y versionado mantienen paridad en `control` y todos los tenants; las tablas de historial deben existir en cada esquema tenant antes de enrutar solicitudes de negocio.
- Por el precedente de `historial_transicion_ticket`, ambas tablas nuevas de historial tienen paridad estructural en `control` y cada tenant, aunque el historial de control no contenga datos operativos. Con 20 tablas de control y 17 de negocio por tenant en la línea base, pasan a **22 tablas en control** y **19 en cada tenant**: cada historial se crea en control y en los esquemas tenant. El DDL de instalación limpia y su semilla inicializan productos y categorías existentes como activos, reparten datos y dejan una fila de versión `014.1` compatible en control y tenants. No se agrega una cadena de migraciones: según AGENTS.md §8, se reconstruye el volumen con `down -v` + `up -d`.
- Antes de implementar el cambio de modelo, el plan debe incluir como prerrequisito la justificación y aprobación formal en `docs/spec/stack.md` de columnas de estado y las entidades de historial 16.ª y 17.ª, sus relaciones verificables, paridad control/tenant e inmutabilidad. Esta fase no actualiza `stack.md`.
- El test gated de instalación limpia y los de estructura/paridad deben actualizar los conteos y verificar ambas tablas en control y tenants, estados iniciales, relaciones, aislamiento, versión `014.1` y denegación de routing ante versión incompatible. Al cierre se actualizan los conteos del modelo en `AGENTS.md` §7 y `MEMORY.md`, junto con la coherencia documental exigida por `AGENTS.md` §8.7; no en esta fase.
- La matriz central recibe únicamente entradas nuevas necesarias para operaciones de ciclo de vida e historial; sus entradas existentes y los roles que ya tienen quedan intactos.
- No se agregan paquetes. Cualquier prueba de UI de esta spec se ejecuta con `ng test`; pruebas de backend con `pytest` y semántica real de esquema/concurrencia con PostgreSQL 16 gated.
