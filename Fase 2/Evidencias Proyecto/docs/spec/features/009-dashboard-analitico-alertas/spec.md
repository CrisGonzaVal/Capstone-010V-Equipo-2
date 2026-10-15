# Feature 009: Dashboard analítico de stock crítico y log de alertas

**Estado:** borrador  
**Release:** 2.0 — Sprint 4  
**Tipo:** Consulta analítica y alertas de inventario

## 1. Problema

El dashboard actual presenta cifras de ejemplo para productos en stock, tickets activos, departamentos y alertas, además de una actividad reciente ficticia. No existe una lectura consolidada que permita a cada actor tomar decisiones a partir de los datos operativos reales, identificar departamentos con existencias críticas y consultar movimientos recientes de inventario.

Desde la Feature 008 los datos están particionados por institución. Cualquier métrica, alerta o actividad debe respetar ese aislamiento: Superadmin consulta el conjunto global con atribución institucional; los demás roles, solo su institución, y el Solicitante mantiene las restricciones de visibilidad propias de su rol para los datos que no son inventario.

## 2. Objetivo

Reemplazar las métricas y la actividad de muestra del dashboard por datos reales del sistema, presentar existencias críticas a nivel de departamento y ofrecer un log consultable de alertas derivado del estado actual del inventario, sin duplicar la auditoría inmutable de movimientos ni persistir alertas redundantes.

## 3. Alcance

### Dentro

- Sustituir los cuatro KPI de muestra por datos reales: unidades totales en stock, tickets activos, departamentos del ámbito y filas de inventario críticas.
- Mostrar movimientos reales de inventario en la sección «Actividad Reciente», ordenados del más reciente al más antiguo y solo para los roles autorizados por la matriz vigente.
- Retirar el placeholder «Estado de Sedes Descentralizadas», que no presenta datos reales.
- Exponer un único listado de filas departamento-producto actualmente críticas, denominado «log de alertas» y usado tanto por el KPI de alertas como por el listado visible.
- Aplicar el ámbito institucional en servidor: Superadmin ve datos globales, atribuidos a institución; Administrador, Bodeguero y Solicitante ven solo los datos de su institución.
- Mantener las limitaciones existentes del Solicitante para tickets, usuarios y demás datos; los KPIs no deben revelar tickets ajenos a su institución ni detalle personal innecesario.
- Permitir que todos los roles que ya acceden al dashboard consulten KPI y alertas conforme a sus ámbitos vigentes; la actividad de movimientos se limita a los roles autorizados actualmente y no amplía el permiso denegado al Solicitante.
- Conservar la definición de stock mínimo existente en cada producto y aplicarla a cada fila de inventario asociada a un departamento.
- Mantener el log de alertas como lectura derivada del inventario actual; no persistir eventos de alerta ni crear una entidad nueva para ello.
- Presentar estados útiles de carga, resultado vacío y fallo de consulta, sin volver a mostrar números de muestra como si fueran datos reales.
- Dejar el alcance institucional expresado de forma que una futura relación entre institución, sede y departamento pueda adoptarse sin cambiar el significado de esta funcionalidad; la entidad Sede no se incorpora aquí.

### Fuera

- Crear la entidad Sede o cambiar la relación actual entre institución y departamento; la gestión por sede se definirá en una feature posterior.
- Cambiar el modelo de datos existente o añadir tablas/columnas de alertas. La Feature 009 no requiere tabla nueva: las alertas se derivan de `inventario`, `producto` y `departamento`.
- Guardar historial de alertas ya resueltas, estados de lectura, acuse, asignación, notificación o ciclo de vida de alertas.
- Enviar notificaciones por correo, mensajería, push o procesos programados.
- Configurar umbrales distintos por departamento, institución o usuario, ni modificar `stock_minimo` desde el dashboard.
- Alterar el flujo de tickets, el despacho, la auditoría de movimientos o sus reglas transaccionales.
- Añadir filtros interactivos, exportación, vista comparativa entre instituciones, contrastes o rankings entre sedes, o periodos históricos al dashboard. La atribución institucional de cada registro global que ve Superadmin sí está dentro del alcance (AC-7); lo excluido es la comparación interactiva entre instituciones.
- Cambiar la autenticación Clerk, los roles existentes o reimplementar la política de permisos de las Features 007 y 008.

## 4. Actores

- **Superadmin**: consulta KPI, stock crítico y actividad en todas las instituciones, con cada registro atribuido a su institución; los agregados no fusionan registros homónimos entre instituciones.
- **Administrador Institucional (`Administrador`)**: consulta métricas, alertas y movimientos de la institución derivada de su departamento.
- **Bodeguero**: consulta métricas, alertas y movimientos de la institución derivada de su departamento.
- **Solicitante**: consulta KPI y alertas de inventario de su institución; no ve actividad de movimientos, cuyo acceso permanece denegado por la matriz vigente. Los conteos de tickets no revelan tickets ni información de usuarios fuera de los permisos actuales. No obtiene nuevas capacidades de gestión.

## 5. Decisiones

### D-1 — Stock crítico evaluado por fila de departamento

Una fila de inventario es crítica si `stock_actual <= producto.stock_minimo`. La comparación se realiza por cada pareja departamento-producto, no sobre la suma del producto en toda la institución. La igualdad con el mínimo es crítica; una fila con stock cero también lo es cuando el mínimo es cero. Un producto sin fila de inventario no constituye una alerta departamental.

**Por qué:** la consulta debe señalar dónde está el déficit, incluso cuando el stock de otros departamentos haga que el agregado institucional parezca suficiente. Esta definición reutiliza el umbral de dominio ya existente (`producto.stock_minimo`) y el vínculo operativo actual de inventario con departamento.

### D-2 — Log de alertas como vista derivada, sin persistencia

El log representa las filas de inventario que cumplen actualmente la regla de criticidad. Una fila entra en la vista al quedar bajo o en el mínimo y deja de aparecer cuando una entrada u otra operación deja su stock sobre el mínimo. No se crea tabla de alertas ni se almacena un evento separado.

**Por qué:** `movimiento_inventario` ya conserva de forma inmutable la auditoría de cada cambio de stock. Persistir además alertas que reflejan el mismo estado duplicaría información y exigiría resolver transiciones, deduplicación y cierre; el roadmap pide un log consultable, no un historial de notificaciones.

### D-3 — Ámbito analítico idéntico al aislamiento institucional existente

El servidor aplica el ámbito autenticado en todas las lecturas analíticas. Superadmin tiene lectura global y cada registro de inventario/actividad incluye atribución institucional suficiente para distinguir datos. Administrador, Bodeguero y Solicitante quedan limitados a su institución derivada; el ámbito no se acepta como autorización desde parámetros del cliente. Los datos de tickets respetan adicionalmente el alcance por rol vigente, incluido que Solicitante solo cuenta sus propios tickets cuando corresponda.

**Por qué:** el dashboard no puede ser una vía alternativa para eludir el aislamiento de la Feature 008 ni las restricciones de tickets de la 007. La presentación de Angular informa y organiza, pero la autorización es responsabilidad del servidor.

### D-4 — Cuatro KPI con significado explícito

Los KPI quedan definidos así:

1. **Unidades en Stock:** suma de unidades `stock_actual` de las filas de inventario dentro del ámbito aplicable. La etiqueta visible exacta es «Unidades en Stock» y no implica conteo de productos distintos.
2. **Tickets activos:** tickets del ámbito cuyo `estado_ticket.nombre` no es exactamente «Cerrado»; cada ticket se cuenta una vez. Para Solicitante, solo se consideran sus propios tickets. Los agregados globales de Superadmin no fusionan registros entre instituciones; la actividad y cada fila de detalle sí llevan la atribución institucional correspondiente.
3. **Departamentos:** cantidad de registros de departamento (cada PK cuenta una vez) pertenecientes al ámbito, incluidos los que no tienen filas de inventario. Para Superadmin, cuenta todos los registros globales; departamentos homónimos de instituciones distintas cuentan por separado.
4. **Alertas de stock:** cantidad de filas departamento-producto críticas según D-1; una pareja crítica en dos departamentos cuenta como dos alertas.

Los conteos sin filas devuelven cero. Las métricas se calculan sobre datos reales en cada consulta y no se presentan valores ficticios.

**Por qué:** se preservan las cuatro tarjetas que ya comunica la interfaz, aclarando la etiqueta, unidades y reglas de conteo para que su resultado sea verificable y no dependa de interpretaciones del cliente.

### D-5 — Actividad reciente basada en auditoría de movimientos

La sección «Actividad Reciente» presenta movimientos de inventario existentes, con tipo, cantidad, fecha, producto, departamento y atribución institucional para el alcance global. Se ordenan por fecha descendente y, ante empate, por identificador descendente. Solo la consultan Superadmin, Administrador y Bodeguero, conforme a la matriz vigente; Solicitante no accede a esta actividad. La lista se limita a una cantidad reciente fija, definida en el contrato de consulta durante la planificación; no es un historial editable ni sustituye la consulta de auditoría.

**Por qué:** los movimientos son la fuente auditable e inmutable de entradas y salidas. Los tickets son otro flujo con semántica y autorización distintas; mezclarlos produciría un registro heterogéneo y duplicaría decisiones sobre eventos y campos que no son movimientos de stock.

### D-6 — Sin tabla nueva ni cambio del modelo relacional

La feature no añade entidades, tablas, columnas ni relaciones. El log de alertas se obtiene combinando las filas actuales de inventario con su producto, departamento e institución; la actividad procede de `movimiento_inventario` y sus relaciones ya existentes.

**Por qué:** ambos resultados son proyecciones de datos presentes. No existe un requisito de conservar alertas resueltas ni de crear una configuración nueva que justifique alterar el modelo vigente de 12 entidades 3NF.

### D-7 — La futura Sede no se anticipa en esta entrega

La unidad de localización analítica de esta feature es el departamento, de acuerdo con el modelo vigente. La futura entidad Sede y la gestión exclusiva por sede quedan fuera; la evolución deberá mantener la capacidad de identificar dónde está la fila crítica y volver a validar el ámbito y el significado del KPI.

**Por qué:** todavía no existe una decisión aprobada de modelo ni contrato para Sede. Añadirla anticipadamente impediría delimitar con certeza las relaciones, permisos y reglas de gestión de esa futura feature. Este documento no presupone cómo se implementará.

## 6. Reglas del flujo y ámbito de datos

### Reglas de lectura analítica

- Todos los datos del dashboard se derivan de registros persistidos; no hay valores predeterminados de demostración que se presenten como métricas.
- Los agregados de stock usan filas de `inventario` dentro del ámbito; no se suman datos de otra institución para usuarios limitados.
- Los críticos son filas de inventario con `stock_actual <= producto.stock_minimo`. Los productos sin inventario no generan alerta.
- El total KPI de alertas cuenta filas, no productos únicos. El listado identifica el departamento, producto, stock actual, stock mínimo e institución cuando aplique.
- El KPI de departamentos cuenta registros por su identidad (PK), incluidos departamentos sin inventario; homónimos de instituciones distintas cuentan separadamente.
- El KPI de tickets activos cuenta únicamente tickets cuyo `estado_ticket.nombre` no es exactamente «Cerrado». La consulta respeta el ámbito de tickets por rol.
- La actividad reciente incluye únicamente movimientos de inventario persistidos, no altas/cambios de tickets ni registros fabricados a partir del estado actual. Solicitante no la consulta porque su permiso vigente para `GET /inventario/movimientos` es denegado.
- La falta de datos produce listas vacías y métricas cero. Un fallo de lectura se comunica como error recuperable y no se sustituye por datos de muestra.

### Ámbito por rol

| Rol | KPI y alertas de inventario | Tickets activos | Actividad de movimientos |
|---|---|---|---|
| Superadmin | Globales; los registros no se fusionan entre instituciones | Global, agregado | Global, cada movimiento atribuido a institución |
| Administrador | Solo su institución | Tickets de su institución | Solo su institución |
| Bodeguero | Solo su institución | Tickets de su institución | Solo su institución |
| Solicitante | Solo su institución | Solo sus propios tickets | No disponible; conserva la denegación vigente |

Para roles limitados, un ámbito institucional que no pueda resolverse se deniega con 403 conforme a 007/008; nunca se interpreta como global. No se aceptan `institucion_id` ni departamento proporcionados por el cliente como autoridad para ampliar lecturas. Los permisos efectivos de cada operación analítica se incorporan a la matriz central; estar autenticado o ver la ruta en Angular no sustituye dicha autorización.

### Persistencia y trazabilidad

- No se inserta, actualiza ni elimina un registro de alerta al cambiar stock.
- Cada variación de stock continúa registrándose exclusivamente mediante la auditoría existente `movimiento_inventario`, conforme a la Constitución.
- Si una actualización de stock deja una fila por debajo o sobre el umbral, la siguiente lectura refleja ese estado actual; no se reconstruye una transición histórica de alerta.

## 7. Criterios de aceptación

### Datos y métricas

- **AC-1** DADO un conjunto de filas de inventario persistidas dentro del ámbito, CUANDO se consulta el dashboard, ENTONCES la tarjeta lleva exactamente la etiqueta «Unidades en Stock» y muestra la suma de `stock_actual` de esas filas, sin incluir otras instituciones para roles limitados; si no hay filas, muestra cero.
  - **Verificado:** Backend HTTP `tests/api/test_dashboard_analitico.py::test_kpi_unidades_en_stock_suma_solo_las_filas_del_ambito` (INSTA 30 = 9+10+11+0; INSTB 3, sin fuga de ámbito) y `::test_superadmin_unidades_en_stock_es_un_escalar_global_unico` (`unidades_en_stock` es `int` 33, escalar global único); `::test_dashboard_sin_datos_devuelve_ceros_y_listas_vacias` (cero sin filas). Servicio `tests/services/test_dashboard_service.py::test_unidades_en_stock_suma_solo_el_ambito` (30/3/33) y `::test_sin_datos_devuelve_ceros_y_listas_vacias`. Frontend `dashboard.component.spec.ts` «AC-1: las cuatro tarjetas usan sus etiquetas exactas» (incluye «Unidades en Stock») y «AC-1: muestra los valores numéricos del DTO». Comandos: `pytest` 540 passed / 0 failed / 5 skipped; `ng test` 172 SUCCESS / 0 FAILED.
- **AC-2** DADO que existen tickets con varios valores de estado, CUANDO se consulta el KPI de tickets activos, ENTONCES cuenta una vez cada ticket visible cuyo `estado_ticket.nombre` no sea exactamente «Cerrado» y excluye los que sí tengan ese nombre, sin depender de ID fijo. Para Solicitante cuenta solo los tickets propios; sin tickets visibles devuelve cero.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_kpi_tickets_activos_excluye_solo_el_nombre_literal_cerrado` (INSTA = 4: excluye solo el nombre exacto «Cerrado»; «cerrado»/«CERRADO»/«Cancelado»/«EnCurso» cuentan) y `::test_kpi_tickets_activos_solicitante_cuenta_solo_los_propios` (Solicitante = 2, solo los propios). Servicio `tests/services/test_dashboard_service.py::test_tickets_activos_excluye_solo_el_nombre_literal`. El conteo se hace en SQL (`select(count())` con join a `EstadoTicket` y `nombre != "Cerrado"`), sin id fijo.
- **AC-3** DADO que existen departamentos, incluidos departamentos sin inventario y departamentos homónimos en instituciones distintas, CUANDO se consulta el dashboard, ENTONCES el KPI cuenta cada registro de departamento por su PK dentro del ámbito; los roles limitados cuentan su institución y Superadmin todos los registros globales, incluidos homónimos por separado.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_kpi_departamentos_cuenta_por_pk_incluido_sin_inventario` (INSTA = 4, incluye «Sin Inventario» vacío) y `::test_kpi_departamentos_superadmin_cuenta_homonimos_por_separado` (global = 5, «Operaciones» de INSTA e INSTB contadas aparte). Servicio `tests/services/test_dashboard_service.py::test_departamentos_cuenta_por_pk_incluido_sin_inventario` (4 y 5).
- **AC-4** DADO un producto con stock mínimo M y filas de inventario en distintos departamentos, CUANDO una fila tiene stock igual o menor que M, ENTONCES esa fila aparece como crítica aunque otras filas eleven el total institucional por encima de M; una fila con stock mayor que M no aparece y un producto sin filas no genera alerta.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_alertas_marca_igual_o_menor_al_minimo_y_excluye_m_mas_1` (críticas: Papel Bond 9 y 10, Insumo Cero 0; M+1=11 fuera), `::test_alerta_incluye_minimo_cero_con_stock_cero`, `::test_producto_sin_inventario_no_genera_alerta` y `::test_alerta_expone_los_campos_del_contrato`. Servicio `tests/services/test_dashboard_service.py::test_alertas_por_fila_y_kpi_igual_al_listado`. Criticidad por fila vía `inventario_service.es_stock_critico` (no el agregado por producto).
- **AC-5** DADO que el ámbito contiene filas críticas, CUANDO se consulta el KPI o el listado llamado «log de alertas», ENTONCES ambos usan el mismo y único conjunto de filas departamento-producto críticas; el KPI cuenta sus filas (no productos únicos) y el listado identifica departamento, producto, stock actual y mínimo. Una fila que deja de cumplir la regla desaparece del listado en la lectura siguiente.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_kpi_total_alertas_es_el_mismo_conjunto_que_el_listado` (`total_alertas == len(alertas)`: global 4, INSTA 3; mismo y único conjunto) y `::test_cruce_de_umbral_por_movimiento_real_no_persiste_alertas` (la fila entra/sale del listado al cruzar el umbral: 3 → 2 → 3). Servicio `tests/services/test_dashboard_service.py::test_alertas_por_fila_y_kpi_igual_al_listado`. Cada fila identifica producto, departamento, stock actual y mínimo.

### Actividad y alertas

- **AC-6** DADO que existen movimientos de inventario y consulta un rol autorizado, CUANDO se presenta «Actividad Reciente», ENTONCES muestra movimientos reales con fecha, tipo, cantidad, producto y departamento, ordenados por fecha descendente y por identificador descendente ante empate, y no incluye entradas ficticias ni eventos de ticket. Una identidad Solicitante recibe 403 si intenta consultar directamente la actividad, conforme al permiso vigente.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_actividad_limita_a_diez_y_ordena_descendente` (12 sembrados → 10 más recientes, `fecha DESC` y desempate `id DESC`) y `::test_actividad_desempata_por_id_descendente_ante_fechas_iguales` (fechas iguales → orden por `movimiento_id` descendente); 403 vigente de Solicitante al historial en `::test_movimientos_sigue_denegado_a_solicitante`. Servicio `tests/services/test_dashboard_service.py::test_actividad_ordena_por_fecha_y_id_descendente_con_limite`. Actividad solo desde movimientos persistidos (sin tickets ni entradas ficticias).
- **AC-7** DADO que Superadmin consulta el dashboard con datos de al menos dos instituciones, CUANDO se muestran alertas y movimientos, ENTONCES cada fila de alerta y movimiento lleva la atribución institucional correspondiente y los agregados no fusionan productos homónimos ni stock entre instituciones; el dashboard no ofrece comparación, contraste ni ranking entre instituciones.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_alertas_homonimos_se_atribuyen_por_institucion` (Papel Bond de INSTA e INSTB conserva `producto_id` e institución propios), `::test_superadmin_filas_de_alertas_y_actividad_conservan_atribucion` (`institucion_id`/`institucion_nombre` en cada fila de alerta y actividad global) y `::test_actividad_expone_campos_ubicacion_y_atribucion`. El KPI de unidades del Superadmin es un escalar único (`::test_superadmin_unidades_en_stock_es_un_escalar_global_unico`), sin serie por institución. Frontend `dashboard.component.spec.ts` «AC-7: cada alerta global conserva su institución». No hay elemento de comparación/ranking entre instituciones en el template.
- **AC-8** DADO que Administrador, Bodeguero o Solicitante de INST-A consultan KPI o alertas, CUANDO existen datos también en INST-B, ENTONCES ningún KPI, alerta o dato derivado incluye filas de INST-B. Administrador y Bodeguero tampoco ven movimientos de INST-B; Solicitante no obtiene actividad de movimientos. Un parámetro de institución enviado por el cliente no amplía resultados.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_rol_limitado_solo_ve_su_institucion_y_el_parametro_ajeno_se_ignora` (parametrizado Admin/Bodeguero/Solicitante: la respuesta con `?institucion_id=INSTB` es idéntica a la petición sin parámetro; cifras de INSTA 30/3/4 y ninguna fila de INSTB), `::test_kpi_unidades_en_stock_suma_solo_las_filas_del_ambito` y `::test_actividad_de_rol_limitado_no_incluye_otra_institucion`. Servicio `tests/services/test_dashboard_service.py::test_unidades_en_stock_suma_solo_el_ambito`. Frontend `dashboard.component.spec.ts` «AC-8: no envía institución ni parámetros de ámbito» y `dashboard.service.spec.ts` (sin params/headers/body de ámbito).
- **AC-9** DADO que una lectura analítica de tickets se realiza como Solicitante, CUANDO existen tickets de otras personas de su misma institución, ENTONCES el KPI no cuenta esos tickets; Administrador y Bodeguero cuentan tickets de su institución y Superadmin cuenta el conjunto global.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_kpi_tickets_activos_solicitante_cuenta_solo_los_propios` (Solicitante INSTA = 2, solo sus tickets, no los de otro solicitante de la misma institución). El alcance de tickets replica la regla vigente (Admin/Bodeguero por institución vía `ticket → usuario → departamento`, Superadmin global; `dashboard_service._contar_tickets_activos`). Servicio `tests/services/test_dashboard_service.py::test_tickets_activos_solicitante_cuenta_solo_los_propios`.
- **AC-10** DADO que Solicitante consulta el dashboard, CUANDO la interfaz presenta sus secciones, ENTONCES muestra sus KPI y alertas institucionales pero no presenta actividad de movimientos ni invoca una lectura que amplíe el permiso actualmente denegado en `GET /inventario/movimientos`; una invocación directa a dicha operación responde 403.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_dashboard_solicitante_no_expone_actividad` (200 con `actividad_disponible=false` y `actividad_movimientos=[]`), `::test_solicitante_sin_actividad_y_403_en_el_historial` (dashboard 200 + `GET /inventario/movimientos` 403 directo) y `::test_movimientos_sigue_denegado_a_solicitante` (403, sin regresión). Frontend `dashboard.component.spec.ts` «AC-10: el Solicitante no ve actividad y no consulta el historial» (no renderiza «Actividad Reciente» y `httpMock.expectNone('/inventario/movimientos')`).
- **AC-11** DADO un usuario de rol limitado cuyo ámbito institucional no se resuelve, CUANDO consulta una operación analítica, ENTONCES el servidor responde 403 y no devuelve resultados globales.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_ambito_irresoluble_responde_403` (parametrizado Administrador/Bodeguero/Solicitante sin departamento resoluble → 403, nunca global). Servicio `tests/services/test_dashboard_service.py::test_ambito_irresoluble_responde_403` (los tres roles limitados). Denegación vía `ambito_service.alcance_institucional` (el mismo mecanismo 007/008).

### Persistencia, contrato y cliente

- **AC-12** DADO un movimiento de stock que hace que una fila cruce hacia o desde el umbral crítico, CUANDO se consulta el log, ENTONCES este refleja el estado actual según D-1 sin crear ni alterar una fila de alerta; los movimientos de auditoría permanecen inmutables y sin duplicación.
  - **Verificado:** Backend `tests/api/test_dashboard_analitico.py::test_cruce_de_umbral_por_movimiento_real_no_persiste_alertas`: la fila Papel Bond/Operaciones (9, mín. 10) sale del log con una ENTRADA real de 5 (14) y reaparece con una SALIDA de 5 (9); el conteo de filas por tabla crece exactamente +2 y solo en `movimiento_inventario`; `total_alertas` 3 → 2 → 3. `::test_no_existe_tabla_ni_columna_de_alertas` recorre `Base.metadata` y confirma que ninguna tabla/columna contiene «alerta». El log es una lectura derivada; no hay tabla ni migración de alertas.
- **AC-13** La Feature 009 no crea tabla, entidad ni columna de alertas; el único log se deriva de `inventario`, `producto`, `departamento` e institución y la actividad autorizada procede de los movimientos existentes. No se requiere migración de datos para instalar la feature.
  - **Verificado:** No se creó ninguna tabla/columna/entidad nueva ni archivo en `database/` (la Feature 009 no toca el modelo de 12 entidades). Backend `tests/api/test_dashboard_analitico.py::test_no_existe_tabla_ni_columna_de_alertas` (metadata ORM sin «alerta») y `::test_dashboard_consolidado_responde_200_con_el_contrato`/`::test_openapi_del_dashboard_declara_200_y_response_model` (DTO `DashboardAnaliticoRespuesta` con las cuatro secciones). Contrato publicado verificado por consola sobre `app.openapi()`: `GET /api/v1/dashboard/` presente, `200` → `DashboardAnaliticoRespuesta`, respuestas `200/401/403`, `parameters: []`. Frontend `dashboard.service.spec.ts` transmite íntegra la respuesta consolidada.
- **AC-14** El contrato de lectura analítica documenta respuestas de éxito, autenticación/autorización y errores relevantes; las operaciones aparecen en el OpenAPI y en la matriz central de permisos. Sesión inválida conserva 401, rol no autorizado 403 y ámbito no resoluble 403; la consulta de movimientos por Solicitante conserva su 403 vigente.
  - **Verificado:** Contrato por consola (`app.openapi()`): `GET /api/v1/dashboard/` con `summary` «Consultar el dashboard analitico consolidado», respuestas `200/401/403` (con descripción), `200` → `#/components/schemas/DashboardAnaliticoRespuesta`, `parameters: []` y `security: [{'HTTPBearer': []}]`. Backend `tests/api/test_dashboard_analitico.py::test_openapi_del_dashboard_declara_200_y_response_model`, `::test_dashboard_sin_sesion_responde_401` (401) y `::test_dashboard_permite_a_los_cuatro_roles` (200). Matriz central por consola: 21 operaciones; `GET /api/v1/dashboard/` = {Superadmin, Administrador, Bodeguero, Solicitante}; `GET /api/v1/inventario/movimientos` = {Superadmin, Administrador, Bodeguero} (Solicitante ausente). Contrastado por `tests/api/test_permisos_endpoints.py::test_inventario_de_rutas_igual_a_la_matriz_d3`, `::test_operacion_dashboard_declarada_para_los_cuatro_roles`, `tests/api/test_permisos.py::test_matriz_cubre_exactamente_las_operaciones_de_d3` y `tests/api/test_permisos_008.py::test_matriz_central_es_la_esperada_para_008` (007/008 verdes).
- **AC-15** DADO que se abre el dashboard autenticado, CUANDO termina la carga, ENTONCES KPI, alertas y actividad autorizada se alimentan de datos reales, se retira el placeholder «Estado de Sedes Descentralizadas» y no se presentan cifras ficticias; durante la carga se identifica el estado pendiente, sin datos se muestran ceros/listas vacías y ante fallo se informa un error recuperable.
  - **Verificado:** Frontend `dashboard.component.spec.ts` (172 SUCCESS / 0 FAILED en `ng test --watch=false --browsers=ChromeHeadless` con Edge): «pide el dashboard una sola vez al inicializar», «retira el placeholder «Estado de Sedes Descentralizadas»», «no presenta cifras ni actividad de ejemplo», «lista las alertas…», «muestra la Actividad Reciente con movimientos y su atribución», «durante la carga identifica el estado pendiente» (`role="status"`), «sin datos muestra ceros y vacíos explícitos», «ante fallo informa un error recuperable con acción de reintento» (`[role="alert"]` + botón «Reintentar») y «el reintento vuelve a pedir el dashboard y limpia el error». `dashboard.service.spec.ts` fija la lectura tipada. `npx ng build` compila limpio (chunk `dashboard-component`).
- **AC-16** La Feature 009 solo se declara cerrada cuando todas las tareas de `tasks.md`, incluidos los checks de cierre, están `[x]`; todos los AC de esta spec están verificados con evidencia; `pytest` y `ng test` están verdes; se documentaron el recorrido funcional en 4200 y el humo en 8080 tras reconstruir la imagen conforme a `AGENTS.md` §8.5; y se revisó la coherencia documental conforme a §8.7.
  - **Verificado:** Cierre integral de la Feature 009. (1) Las 15 tareas de `tasks.md` (T1–T15) están `[x]`, incluidos los checks de cierre. (2) Los 16 AC de §7 tienen evidencia concreta (AC-1…AC-15 en §7; recuento abajo). (3) `pytest` backend completo: **540 passed, 0 failed, 5 skipped** (los 5 skipped son los gated PostgreSQL; ejecutados aparte con `POSTGRES_TEST_URL` → **5 passed**). (4) `ng test` frontend completo (Edge, `--watch=false --browsers=ChromeHeadless`): **172 SUCCESS, 0 FAILED**; `ng build` de producción limpio. (5) Recorrido funcional en **4200** con los cuatro roles contra la BD real: Administrador 626/5/7/3, Superadmin 646/5/10/3 (escalar global + atribución institucional por fila, homónimos sin fundir, sin comparación entre instituciones), Bodeguero 626/5/7/3, Solicitante 626/0/7/3 **sin** sección «Actividad Reciente» y con `GET /api/v1/inventario/movimientos` → **403**. (6) Imagen del frontend **reconstruida** (`docker compose build frontend` + `up -d frontend`) → `sha256:11a287959b12…` (pre-feature 008: `cfdd5de4…`); humo en **8080** confirma el dashboard de la 009 con bundles nuevos (`main-A4LYVLW7.js`, `chunk-S2G2JRYD.js`) y `try_files` de nginx OK. (7) Contrato en `/openapi.json`: `GET /api/v1/dashboard/` → `DashboardAnaliticoRespuesta`, respuestas 200/401/403, sin query params; matriz central de **21 operaciones** (`GET /dashboard/` → 4 roles; `GET /inventario/movimientos` sin cambios, Solicitante excluido). (8) Coherencia documental revisada conforme a §8.7 (grep en `AGENTS.md`, `MEMORY.md`, `docs/spec/` y `.agents/skills/`): sin referencias obsoletas tras retirar el placeholder; la futura Sede no se anticipó.

## 8. Verificación de cierre

La feature permanece abierta hasta completar y documentar todos estos puntos:

- [x] Todas las tareas de `tasks.md`, incluidas las de cierre, están marcadas `[x]` (T1–T15, incluidos los checks de cierre).
- [x] Cada AC de §7 contiene evidencia concreta de verificación (AC-1…AC-15 en §7 con test/comando/respuesta; AC-16 arriba con el resumen de cierre).
- [x] Suite backend completa `pytest` en verde: **540 passed, 0 failed, 5 skipped** (+ gated PostgreSQL **5 passed** con `POSTGRES_TEST_URL`).
- [x] Suite frontend `ng test` en verde: **172 SUCCESS, 0 FAILED** (Edge, `--watch=false --browsers=ChromeHeadless`); `ng build` limpio.
- [x] Recorrido funcional en puerto 4200 con datos reales y comprobaciones de ámbito: Administrador 626/5/7/3, Superadmin 646/5/10/3, Bodeguero 626/5/7/3, Solicitante 626/0/7/3; se confirmó que Solicitante **no** ve actividad de movimientos y recibe 403 en el historial.
- [x] Imagen frontend reconstruida (`docker compose -f docker-compose.yml build frontend` + `up -d frontend`) y humo en 8080: dashboard de la 009 con bundles nuevos (`main-A4LYVLW7.js`, `chunk-S2G2JRYD.js`) sobre la imagen `sha256:11a287959b12…`.
- [x] Contrato de las lecturas analíticas comprobado en `/openapi.json` (`DashboardAnaliticoRespuesta`, 200/401/403, sin query params) y permisos revisados en la matriz central de **21 operaciones**; Solicitante conserva **403** para la lectura de movimientos.
- [x] Cierre verificado conforme a `AGENTS.md` §8.5 (los dos puertos recorridos; 8080 sobre imagen reconstruida).
- [x] Coherencia documental revisada conforme a `AGENTS.md` §8.7; la futura Sede no se anticipó ni se contradijeron las reglas de Feature 008.

## 9. Restricciones

- Clerk sigue siendo la única autoridad de autenticación; no se emite ni acepta JWT local HS256.
- La autorización real es del servidor y se integra en la matriz central vigente; guards o elementos de interfaz nunca constituyen una frontera de seguridad.
- La institución de roles limitados se deriva del usuario autenticado y no se toma de entradas del cliente. Solo Superadmin tiene ámbito global.
- Se conservan los cuatro roles literales existentes y sus restricciones sobre tickets. La lectura analítica no concede capacidades de escritura ni amplía el acceso del Solicitante.
- No se crea persistencia de alertas; `movimiento_inventario` permanece como auditoría inmutable de stock.
- No se cambia el modelo de 12 entidades ni se incorpora Sede. Si una decisión de implementación posterior exige modificar modelo o esquema, la implementación debe detenerse y solicitar la justificación y aprobación documental requerida antes de continuar.
- La definición de criticidad se mantiene en el `stock_minimo` de producto vigente; esta feature no introduce umbrales configurables ni reglas de agregación institucional para determinar alertas departamentales.
- La planificación concreta los archivos, contrato técnico, cantidad de movimientos recientes y estrategias de prueba, sin alterar el qué ni el porqué aprobados aquí.
