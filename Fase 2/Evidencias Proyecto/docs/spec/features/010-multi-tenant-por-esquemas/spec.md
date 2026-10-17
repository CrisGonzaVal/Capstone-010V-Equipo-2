# Feature 010: Multi-tenant por esquemas PostgreSQL

**Estado:** `[ ]` No iniciada  
**Release:** 2.0 — Sprint 5  
**Tipo:** Aislamiento multiinstitución y aprovisionamiento

## 1. Problema

Las Features 008 y 009 separan lógicamente los datos mediante `institucion_id`, filtros de servidor y claves compuestas, pero todas las instituciones siguen compartiendo las mismas tablas. El requisito de separación se satisface con un esquema PostgreSQL independiente por institución, dentro de una sola base física `apt_erp`. La identidad local debe resolverse desde el esquema global de control antes de consultar datos de negocio. La base actual contiene datos de cuatro instituciones que deben repartirse sin reinicializar ni perderlos.

## 2. Objetivo

Separar los datos operativos por esquema tenant, resolver de forma segura el esquema para cada petición autenticada, habilitar el aprovisionamiento mínimo desde el portal de control y conservar la operación global atribuida del Superadmin, Clerk y los contratos funcionales existentes.

## 3. Alcance

### Dentro

- Un esquema PostgreSQL tenant por institución dentro de `apt_erp`, atendido mediante el pool existente.
- Un esquema global de control con el registro de instituciones, el mapa correo-esquema de todos los usuarios locales y la identidad local del Superadmin.
- Resolución exclusiva por correo primario verificado obtenido tras validar la identidad Clerk; el cliente no selecciona el tenant.
- Aislamiento de todas las operaciones de negocio a su esquema tenant.
- Portal mínimo `/control`: ruta y protección por rol, pantalla de autenticación para Superadmin y formulario para solicitar el alta de una institución con su primer Administrador.
- Aprovisionamiento del esquema tenant, estructura de datos, catálogos requeridos, usuario inicial y asociación de identidad; los fallos no dejan un tenant operativo parcial.
- Migración de los datos actuales de `apt_erp` a un esquema por institución, preservando identificadores, relaciones, stock, tickets y auditoría.
- Versionado del DDL por esquema y visión global atribuida del Superadmin, incluyendo las lecturas analíticas existentes.
- Compatibilidad de la suite SQLite mediante un contexto lógico único de prueba y comprobación real de aislamiento/esquemas mediante pruebas PostgreSQL 16.
- Dejar documentado que el cambio de ubicación de catálogos invierte la norma vigente de `stack.md`, y que la evolución deberá justificarse y aprobarse allí antes de implementar, conforme a AGENTS.md §7.

### Fuera

- Crear una base física, instancia, conexión o pool por institución.
- Cambiar Clerk, emitir JWT propios, incluir el tenant en el token, confiar en cabeceras/parámetros del cliente o permitir varios tenants por usuario local.
- Selector de tenant para usuarios limitados.
- CRUD completo de instituciones, usuarios y permisos, y pantallas de gestión correspondientes; se reserva a Feature 012. Solo se incluye el alta mínima inicial del tenant descrita en esta feature.
- Escrituras del Superadmin de catálogo, stock o tickets dentro de una institución como operaciones de negocio. Cualquier corrección dentro de un tenant se atribuye a una operación administrativa, no a una operación de negocio del Superadmin.
- Modelo organizacional de sedes, stock por sede y encargado de departamento; corresponde a Feature 011.
- Reescribir el ciclo de vida de tickets, catálogo, informes o notificaciones.
- Eliminar datos operativos, ejecutar semilla destructiva sobre la base migrada o reiniciar el volumen.
- Alta de tenant por cliente sin autorización de Superadmin.

## 4. Decisiones

### D-1 — Un esquema PostgreSQL por institución y selección de tenant confiable

Cada institución tiene un esquema tenant distinto en `apt_erp`; se mantiene una conexión y un pool compartidos. El esquema efectivo de cada petición de negocio es una función exclusiva del correo primario verificado, resuelto en control. Ninguna entrada del cliente ni el reuso de una conexión del pool puede cambiar ese esquema efectivo. La propiedad exigida es observable: una identidad limitada solo puede leer o modificar su tenant, incluso con conexiones reutilizadas; el mecanismo técnico se define en el plan.

**Por qué:** satisface el requisito de separación sin administrar bases o pools por tenant. La garantía se expresa como comportamiento comprobable, sin acoplarla a un mecanismo de selección concreto.

### D-2 — Control como esquema global con modelo 3NF completo

Control es el esquema global y conserva las mismas tablas 3NF que un tenant. Contiene una institución administrativa (por ejemplo, «CompuStock SaaS»), un departamento administrativo y sus filas `usuario` y `rol`; la identidad del Superadmin vive ahí. Se mantienen `usuario.departamento_id` y `departamento.institucion_id` como `NOT NULL`; no se requiere alterar el modelo de 12 entidades ni crear excepciones de nulabilidad. En control viven `institucion` como registro de fuente de verdad y el `rol` correspondiente al Superadmin. El mapa correo-esquema se mantiene junto con esa información global.

**Por qué:** la identidad global y la resolución previa al tenant necesitan existir fuera de los tenants, pero pueden representarse con las mismas relaciones 3NF existentes. Así se conserva el modelo y se evita crear una identidad o esquema de datos paralelo.

### D-3 — Conservar `institucion_id` y claves compuestas como defensa en profundidad

Las columnas `institucion_id`, claves únicas compuestas y FK compuestas introducidas por Feature 008 se conservan en cada tenant. Cada valor identifica la institución propietaria de ese esquema; la integridad se valida localmente. Las claves simples existentes también se conservan.

**Por qué:** el aislamiento de esquema constituye la primera frontera y las restricciones locales una segunda barrera ante errores de routing o datos importados; no convierten valores enviados por el cliente en autoridad.

### D-4 — DDL canónico idéntico por tenant, con catálogos replicados

Cada esquema tenant contiene las doce tablas del DDL canónico de `database/01_esquema.sql`, incluida su propia fila `institucion` espejo de la institución registrada en control. Se conservan las seis FK locales hacia `institucion` definidas por ese DDL; ninguna es cross-schema. En cada tenant se replican `rol`, `prioridad` y `estado_ticket` con sus valores funcionales requeridos. En control, además del esquema 3NF, vive el registro fuente de verdad de instituciones y el rol Superadmin. El DDL tenant es idéntico al canónico; esto no implica que las filas ni los catálogos de control y tenant sean los mismos.

Este reparto invierte la norma actual de `stack.md`, que desde Feature 008 deja `rol`, `prioridad` y `estado_ticket` globales y compartidos. La aprobación de los cambios de DDL/modelo y su justificación en `stack.md` es prerequisito de implementación según AGENTS.md §7; esta spec no modifica `stack.md`.

**Por qué:** el DDL idéntico conserva las FK y el modelo autocontenido en cada esquema sin referencias cross-schema. Replicar catálogos pequeños permite que las relaciones tenant sigan siendo locales; fijar control como fuente de verdad del registro institucional evita que el espejo local gobierne el ciclo de vida global.

### D-5 — Registro institucional de control y espejo tenant

El registro canónico de cada institución reside en control. Su fila `institucion` espejo se crea durante el aprovisionamiento y se mantiene al migrar; los datos operativos de cada tenant conservan la FK local a esa fila. Los cambios del registro global deben reflejarse en el tenant correspondiente, sin convertir la copia tenant en fuente de verdad ni añadir FK cross-schema.

**Por qué:** el routing y la administración global requieren una fuente única de registro; la copia local permite aplicar sin cambios el DDL canónico y satisfacer sus FK dentro de cada esquema.

### D-6 — Versionado independiente y denegación observable

Cada tenant registra la versión de estructura aplicada. La versión objetivo es la correspondiente al DDL requerido por la feature. Antes de una petición de negocio, si la versión registrada no coincide con la versión objetivo, el tenant no se enruta y la petición se deniega; una versión ausente, futura o incompleta también falla cerrada. El aprovisionamiento solo termina como exitoso si registra esa versión objetivo tras completar y verificar la estructura.

**Por qué:** un valor de versión solo sirve como control de seguridad si determina el comportamiento observable de enrutamiento, no si es meramente informativo. El formato y mecanismo exactos se concretan en el plan.

### D-7 — Aprovisionamiento mínimo por Superadmin

El portal `/control` permite que Superadmin solicite el alta de una institución y su primer Administrador. El nombre del esquema tenant se deriva determinísticamente del identificador canónico de institución mediante una regla estable, única y normalizada; el algoritmo exacto se fijará en el plan y debe detectar/rechazar colisiones. El correo del primer Administrador debe existir previamente como usuario de Clerk. Si no existe, el alta falla explícitamente y no deja un tenant operativo. El alta exitosa crea registro en control, esquema, DDL canónico, espejo institucional, catálogos tenant, usuario inicial, mapa correo-esquema y versión objetivo. Un fallo no deja recursos parcialmente utilizables; un reintento no duplica ni destruye datos preexistentes.

**Por qué:** un nombre reproducible es condición para idempotencia; verificar previamente la existencia en Clerk evita crear un usuario local imposible de autenticar con la autoridad de identidad vigente. El portal se limita al camino mínimo de autenticación y aprovisionamiento, dejando la administración completa a Feature 012.

### D-8 — Migrar datos actuales y poblar el mapa completo de identidades

La migración particiona los datos operativos por cada `institucion_id` a su esquema tenant. La institución se toma de las tablas que la almacenan o se deriva por relaciones para las que no la almacenan directamente: `usuario` deriva por `departamento`; `movimiento_inventario` por `inventario`; las demás tablas que sí llevan `institucion_id` usan ese valor. La fila `institucion` se copia como espejo a su tenant y su fuente de verdad permanece en control. `rol`, `prioridad` y `estado_ticket` se replican en cada tenant. Control conserva la fila de Superadmin y el mapa idempotente `correo → esquema` de todos los usuarios migrados, no solo Superadmin. Se preservan IDs, relaciones, usuarios, tickets, detalles, stock, movimientos y secuencias. Si una fila no puede asignarse inequívocamente, la migración aborta sin cambios e identifica el problema. No se usa la semilla destructiva ni se borra el volumen.

**Por qué:** las filas de identidad preexistentes deben poder resolver tenant antes de consultar sus tablas locales. La distribución relacional conserva datos y relaciones sin inventar ámbitos; la regla fail-closed evita migraciones ambiguas o pérdida de datos.

### D-9 — Agregado global completo y de instante único

Las lecturas globales autorizadas del Superadmin recorren los tenants registrados y atribuyen cada fila a su institución, sin fusionar homónimos. La agregación se ejecuta en una sola transacción de lectura de PostgreSQL, por lo que representa un único instante consistente. Si algún tenant requerido no es accesible, no está en versión objetivo o impide completar esa transacción, la lectura global falla explícitamente y no presenta un agregado parcial.

**Por qué:** una transacción común es viable porque los esquemas comparten la misma base y evita consolidar estados observados en instantes distintos. La respuesta completa o fallida evita métricas globales engañosas.

### D-10 — SQLite para suite ordinaria y PostgreSQL 16 para garantías multi-esquema

Las pruebas ordinarias pueden usar SQLite en memoria con un contexto lógico único, sin simular esquemas. La seguridad observable del routing, el aislamiento con conexiones reutilizadas, las FK y las transacciones globales entre esquemas se verifican en pruebas contra PostgreSQL 16.

**Por qué:** SQLite no reproduce namespaces ni semántica transaccional/esquemas PostgreSQL; las garantías que dependen de estas capacidades necesitan evidencia en el motor objetivo.

## 5. Reglas del flujo

### Resolución de identidad y tenant

1. La petición presenta el Bearer vigente de Clerk.
2. El backend valida el token conforme a Feature 006 y obtiene de Clerk el correo primario verificado.
3. Control resuelve el correo a una identidad local. Los roles limitados obtienen su tenant; Superadmin obtiene usuario y rol de control, sin tenant operativo por defecto.
4. Para roles limitados, solo se permite la operación si el tenant tiene exactamente la versión objetivo; la identidad y el esquema efectivo provienen exclusivamente de la resolución en control.
5. Un correo desconocido, duplicado, inactivo, sin asignación o con tenant no preparado/versionado incorrectamente se deniega. No hay caída a otro tenant o esquema predeterminado.
6. Ningún parámetro, cuerpo, cabecera, claim no confiable ni reutilización de conexión puede cambiar el esquema efectivo.

### Portal mínimo y aprovisionamiento

- La ruta `/control` permite autenticación únicamente a Superadmin; cualquier rol distinto de Superadmin no puede acceder.
- La pantalla de alta solicita institución y correo del primer Administrador. La operación requiere autorización Superadmin en servidor.
- El correo debe existir previamente en Clerk y se registra en control y en el tenant. Un alta sin identidad Clerk existente falla explícitamente sin tenant operativo.
- El tenant queda operativo únicamente cuando existen estructura canónica, espejo de institución, catálogos, usuario inicial, mapa de identidad y versión objetivo.
- El nombre de esquema es determinista a partir del identificador institucional; colisiones se rechazan sin sobrescribir esquemas ajenos.
- El CRUD de instituciones, usuarios y permisos no forma parte del portal de esta feature y queda para Feature 012.

### Migración de `apt_erp`

- Se crea/bootstrappea control sobre la base existente de forma idempotente, sin alterar ni truncar datos operativos.
- Las filas se distribuyen según `institucion_id`, salvo `usuario` (por `departamento`) y `movimiento_inventario` (por `inventario`), que lo derivan relacionalmente.
- Control conserva el registro fuente de instituciones y el rol/identidad Superadmin; cada tenant recibe la fila espejo `institucion`, así como `rol`, `prioridad` y `estado_ticket`.
- Se puebla idempotentemente en control el mapa correo-esquema de todos los usuarios migrados.
- Una fila sin institución inequívoca aborta sin cambios y reporta el registro/relación problemática.
- Se preservan IDs, relaciones, stock, tickets, detalles, movimientos y secuencias; se excluye la semilla destructiva.
- La idempotencia se determina comparando la versión registrada de cada tenant con la versión objetivo. Un estado parcial no declara éxito y permite recuperación sin pérdida.

### Superadmin

- Superadmin administra el registro de instituciones, sus usuarios, permisos y restricciones, y puede crear Administradores. En esta feature, el único flujo de portal entregado es solicitar el alta inicial; el CRUD completo es de Feature 012.
- Superadmin no escribe catálogo, stock ni tickets como operación de negocio dentro de un tenant, conforme a la matriz de permisos de Feature 008. Una lectura o corrección administrativa dentro del tenant debe quedar atribuida como operación administrativa.
- Las lecturas globales mantienen atribución institucional y se ejecutan en una sola transacción consistente. Cualquier tenant requerido incompatible o inaccesible hace fallar la lectura completa.

## 6. Criterios de aceptación

### Routing y aislamiento

- **AC-1** DADO dos usuarios con correos verificados asignados a esquemas distintos, CUANDO cada uno realiza una petición autenticada, ENTONCES control resuelve el correo antes del acceso de negocio y la operación se ejecuta únicamente en el esquema asignado.
  - **Evidencia:** resolución y sesión de negocio derivadas del correo — `backend/tests/api/test_control_instituciones_010.py::test_tenant_en_version_objetivo_resuelve_su_esquema` y `::test_contexto_de_solicitud_resuelve_el_tenant_del_correo`; gated PostgreSQL `backend/tests/test_control_postgres_010.py::test_sesion_tenant_por_ejecucion_no_filtra_entre_conexiones_reutilizadas`, `backend/tests/test_integracion_multitenant_010.py::test_get_db_negocio_abre_la_sesion_del_tenant` y `::test_resolver_usuario_local_encuentra_usuario_de_tenant`.
- **AC-2** DADO un correo inexistente, duplicado, sin asignación o asociado a un tenant no preparado, CUANDO intenta acceder a una ruta protegida, ENTONCES la petición se deniega sin consultar datos de otro tenant ni caer a un esquema predeterminado.
  - **Evidencia:** denegación en cerrado sin fallback — `backend/tests/api/test_control_instituciones_010.py::test_correo_no_mapeado_no_resuelve_tenant`, `::test_tenant_no_preparado_no_enruta`, `::test_version_incompatible_deniega_enrutamiento`; gated `backend/tests/test_integracion_multitenant_010.py::test_get_db_negocio_deniega_correo_sin_mapa` (HTTP 403 sin mapa).
- **AC-3** DADO un usuario asignado a Tenant A, CUANDO envía Tenant B por parámetro, cuerpo, cabecera o claim no confiable, ENTONCES el esquema efectivo sigue siendo A o la petición se rechaza; nunca lee ni modifica B.
  - **Evidencia:** no existe canal de tenant en el cliente — `resolver_contexto_solicitud(sesion, correo)` y `get_db_negocio` derivan el esquema solo del correo verificado (`backend/tests/api/test_control_instituciones_010.py::test_contexto_de_solicitud_resuelve_el_tenant_del_correo`); el DTO de alta no expone `nombre_esquema`/`version`/`rol`/`estado` (`::test_openapi_dto_de_entrada_no_recibe_valores_de_servidor`); el esquema es por ejecución, no por conexión (`backend/tests/test_control_postgres_010.py::test_sesion_tenant_por_ejecucion_no_filtra_entre_conexiones_reutilizadas`). **Inyección adversarial por los cuatro canales (cierre del hueco que dejó T14).** SQLite (`backend/tests/api/test_aislamiento_tenant_010.py`): query `::test_query_adversarial_no_contamina_la_resolucion`, cabecera `::test_cabeceras_adversarias_no_contaminan_la_resolucion`, cuerpo `::test_cuerpo_de_negocio_no_puede_fijar_otra_institucion` (la fila se ancla a la identidad, no al `institucion_id` enviado; nada se escribe en B) y `::test_dto_de_control_rechaza_campos_de_tenant` (`extra="forbid"` → 422), claim `::test_claim_adversario_del_token_no_cambia_la_resolucion` (JWT real con claims `institucion_id`/`nombre_esquema`/`tenant` de B; la identidad sale del correo verificado de A). Gated PostgreSQL con dos esquemas reales (`backend/tests/test_integracion_multitenant_010.py`, `get_db_negocio` resolviendo de verdad): `::test_tenant_adversario_por_query_no_contamina`, `::test_tenant_adversario_por_cabecera_no_contamina`, `::test_tenant_adversario_por_cuerpo_no_escribe_otro_tenant` (stock y auditoría de B intactos), `::test_tenant_adversario_por_claim_no_cambia_resolucion`.
- **AC-4** DADO IDs primarios iguales en dos tenants y una conexión reutilizada por el pool, CUANDO peticiones sucesivas autenticadas de usuarios distintos operan sobre ellos, ENTONCES cada resultado corresponde exclusivamente al esquema derivado del correo resuelto y no hay filtración o escritura cruzada.
  - **Evidencia:** gated `backend/tests/test_control_postgres_010.py::test_sesion_tenant_por_ejecucion_no_filtra_entre_conexiones_reutilizadas` (mismo `institucion_id` en dos esquemas, alternancia 3× sobre conexiones del pool, `search_path` limpio) y `backend/tests/test_integracion_multitenant_010.py::test_get_db_negocio_abre_la_sesion_del_tenant` / `::test_resolver_usuario_local_encuentra_usuario_de_tenant`.
- **AC-5** DADO una relación o escritura incompatible dentro de un tenant, CUANDO se intenta persistir, ENTONCES se conservan las FK locales y restricciones compuestas de Feature 008 y la base rechaza la inconsistencia.
  - **Evidencia:** gated `backend/tests/test_control_postgres_010.py::test_ddl_tenant_tiene_seis_fk_locales_sin_cross_schema` (las seis FK a `institucion` son locales, ninguna cross-schema) y `::test_mapa_mantiene_unicidad_y_fk_local_en_postgres` (unicidad de `correo` + FK local rechazan filas incoherentes); el DDL legado de `backend/tests/test_migracion_multitenant_010.py` (`DDL_LEGADO`) conserva las claves compuestas de Feature 008.

### Control, portal y aprovisionamiento

- **AC-6** DADO la base existente sin esquema de control inicializado, CUANDO se ejecuta el bootstrap de control una o más veces, ENTONCES existe el esquema global con su estructura requerida, institución/departamento administrativos, usuario y rol Superadmin, sin modificar datos operativos, y las ejecuciones repetidas no duplican ni alteran los registros existentes.
  - **Evidencia:** SQLite `backend/tests/test_control_modelo_010.py::test_bootstrap_control_crea_estructura_administrativa`, `::test_bootstrap_control_es_idempotente`; gated `backend/tests/test_bootstrap_control_postgres_010.py::test_bootstrap_control_es_idempotente_y_no_toca_negocio`, `::test_bootstrap_control_conserva_nulabilidades_del_modelo`; ejecución real sobre `apt_erp` (T9): `control` con las doce tablas + `mapa_usuario_esquema`, institución/departamento/usuario/rol Superadmin, datos operativos intactos.
- **AC-7** DADO un Superadmin autenticado que abre `/control`, CUANDO solicita el alta con datos válidos y un correo de Administrador existente en Clerk, ENTONCES puede completar autenticación/acceso al portal y solicitar el aprovisionamiento; un rol no Superadmin no puede acceder. Al completar el alta existe un tenant con DDL canónico, espejo de institución, catálogos, usuario inicial, mapa correo-esquema y versión objetivo, y ese Administrador puede autenticarse y queda limitado al tenant.
  - **Evidencia (automatizada):** backend `backend/tests/api/test_aprovisionamiento_010.py::test_alta_con_correo_clerk_existente_crea_tenant_operativo`, `::test_alta_deja_un_tenant_resoluble_por_su_administrador`; contrato `/openapi.json` `backend/tests/api/test_control_instituciones_010.py::test_openapi_publica_el_alta_con_201_y_seguridad`; portal Angular `frontend/src/app/core/guards/control-superadmin.guard.spec.ts`, `frontend/src/app/features/control/control-login.component.spec.ts`, `frontend/src/app/features/control/alta-institucion.component.spec.ts`. **Registrado en T15 (recorrido contra PostgreSQL y Clerk reales):** la institución de prueba `INST-TEST-010` quedó aprovisionada (`tenant_inst_test_010_e4b81830`, 12 tablas + `version_esquema`, espejo, catálogos, usuario `admin.cfsnorte@cfsnorte.cl` y mapa, `version=010.1`); `/control` renderiza la pantalla de alta/login (`ng serve` 4200, Edge headless) y el Superadmin autenticado en Clerk ejecutó el alta contra la base real; el Administrador resultante, con sesión Clerk real, ve **solo su tenant** (`/tickets/`=`[]`, `/inventario/categorias`=`[]`, `/inventario/productos`=`[]`), mientras el Superadmin ve el agregado global (`/inventario/categorias`=**11**). **Pendiente de cierre visual (T15/T16):** captura de pantallas en el navegador del usuario; el subagente no disponía del MCP `chrome-devtools`, por lo que el flujo se verificó vía API real + Edge headless.
- **AC-8** DADO un alta con correo que no existe en Clerk o un fallo en cualquier etapa, CUANDO se informa el resultado, ENTONCES el fallo es explícito y no queda tenant operativo; ningún esquema ajeno se reutiliza, y un reintento válido no duplica ni destruye datos preexistentes.
  - **Evidencia (automatizada):** `backend/tests/api/test_aprovisionamiento_010.py::test_alta_con_correo_clerk_inexistente_falla_sin_tenant` (422), `::test_alta_con_frontera_clerk_caida_responde_503_sin_tenant` (503), `::test_alta_duplicada_por_institucion_id_responde_409_sin_mutar`, `::test_alta_con_correo_administrador_ya_mapeado_responde_409`, `::test_alta_con_usuario_local_ya_existente_compensa_sin_tenant`, `::test_colision_de_nombre_esquema_responde_409_sin_tenant_parcial`; reintento no destructivo `backend/tests/test_migracion_multitenant_010.py::test_migracion_segunda_ejecucion_es_idempotente`; UI `frontend/src/app/features/control/alta-institucion.component.spec.ts` (409/422/503 muestran el `detail` real y no fingen éxito). **Registrado en T15 (recorrido contra PostgreSQL y Clerk reales):** el alta con `INST-TEST-010` y correo Clerk existente quedó persistida y no se reintentó (daría 409); `POST` duplicado → **409** `la institucion ya esta registrada` y `POST` con `no.existe.9999@example.com` → **422** `el correo del Administrador no existe en Clerk`, **ambos sin mutación** (instituciones 5, mapa 15, sin esquema nuevo). **Pendiente de cierre visual (T15/T16):** captura de pantallas en el navegador del usuario.
- **AC-9** DADO una petición de aprovisionamiento de una identidad no autenticada o rol distinto de Superadmin, CUANDO se invoca la operación, ENTONCES se responde 401 o 403 conforme a la política vigente y no se crea institución, mapa ni esquema.
  - **Evidencia:** `backend/tests/api/test_control_instituciones_010.py::test_alta_sin_sesion_responde_401`, `::test_alta_rol_no_superadmin_responde_403`, `::test_alta_esta_declarada_solo_para_superadmin_en_la_matriz`; `backend/tests/api/test_permisos_010.py::test_alta_de_institucion_es_solo_para_superadmin`, `::test_alta_sin_sesion_responde_401`, `::test_alta_deniega_a_rol_no_superadmin`; `backend/tests/api/test_aprovisionamiento_010.py::test_alta_por_rol_limitado_deniega_y_no_crea_nada` (valida estado idéntico); errores 401/403 documentados en `/openapi.json` (`::test_openapi_alta_documenta_los_errores_declarados`).

### Migración y versionado

- **AC-10** DADO la base `apt_erp` actual con varias instituciones, CUANDO se migra, ENTONCES cada tenant recibe sus filas por `institucion_id`, excepto `usuario` asignado vía `departamento` y `movimiento_inventario` vía `inventario`; `institucion` se copia como espejo; `rol`, `prioridad` y `estado_ticket` se replican. Control conserva el registro institucional, la identidad Superadmin y un mapa correo-esquema para todos los usuarios locales migrados. Se preservan IDs, relaciones, stock, tickets, detalles, movimientos y secuencias. Una fila sin asignación inequívoca causa aborto sin cambios y se identifica; no se ejecuta semilla destructiva ni se elimina el volumen.
  - **Evidencia:** gated `backend/tests/test_migracion_multitenant_010.py::test_migracion_crea_control_y_tenants_versionados`, `::test_migracion_particiona_por_institucion_preservando_ids_y_relaciones`, `::test_migracion_control_mapea_todos_los_usuarios`, `::test_migracion_aborta_ante_fila_ambigua_sin_cambios`; ejecución real sobre `apt_erp` (T9): partición por institución (`usuario` vía `departamento`, `movimiento_inventario` vía `inventario`), IDs/secuencias preservados, mapa 14/14 usuarios, `public` intacto.
- **AC-11** DADO tenants cuya migración puede estar completa o parcial, CUANDO se vuelve a ejecutar, ENTONCES para cada tenant se compara su versión registrada con la versión objetivo; tenants ya en versión objetivo no duplican, truncan ni alteran datos operativos, y cualquier estado parcial no se declara exitoso ni pierde datos.
  - **Evidencia:** gated `backend/tests/test_migracion_multitenant_010.py::test_migracion_segunda_ejecucion_es_idempotente`, `::test_migracion_aborta_ante_tenant_preexistente_sin_version`; ejecución real sobre `apt_erp` (T9): segunda ejecución exit 0 sin cambios (hashes md5 idénticos antes/después, mapa 14, `version_esquema` 1 fila).
- **AC-12** DADO un tenant sin versión, con versión futura/incompleta o cuya versión registrada no coincide con la versión objetivo, CUANDO un usuario limitado solicita una operación de negocio, ENTONCES ese tenant no se enruta y la petición se deniega. Superadmin se resuelve en control y cualquier tenant requerido incompatible hace fallar explícitamente el agregado global.
  - **Evidencia:** `backend/tests/api/test_control_instituciones_010.py::test_tenant_no_preparado_no_enruta`, `::test_version_incompatible_deniega_enrutamiento`; `backend/tests/test_control_modelo_010.py::test_version_solo_acepta_igualdad_exacta`; gated `backend/tests/test_integracion_multitenant_010.py::test_dashboard_global_aborta_si_un_tenant_no_esta_en_version` (HTTP 503 sin agregado parcial).
- **AC-13** DADO una institución nueva solicitada o una institución existente migrada, CUANDO se verifica su tenant, ENTONCES su versión registrada coincide con la versión objetivo para que pueda considerarse operativo/enrutable; si no coincide, la petición de negocio se deniega. La migración inicial crea un tenant versionado por cada institución asignable.
  - **Evidencia:** `backend/tests/api/test_control_instituciones_010.py::test_tenant_en_version_objetivo_resuelve_su_esquema`; `backend/tests/api/test_aprovisionamiento_010.py::test_alta_con_correo_clerk_existente_crea_tenant_operativo` (`version_esquema == VERSION_ESQUEMA_OBJETIVO`), `::test_alta_deja_un_tenant_resoluble_por_su_administrador`; gated `backend/tests/test_migracion_multitenant_010.py::test_migracion_crea_control_y_tenants_versionados`; real `apt_erp` (T9): 4 tenants en `010.1`, una única fila de versión cada uno.

### Superadmin, compatibilidad y cierre

- **AC-14** DADO datos en al menos dos tenants, CUANDO Superadmin consulta dashboard o lecturas globales existentes, ENTONCES no requiere tenant operativo propio para esa lectura, todas las filas conservan su atribución, IDs/homónimos no se fusionan y la agregación se ejecuta en una transacción de lectura que refleja un único instante. Si algún tenant requerido no puede incluirse, falla completa sin presentar resultado parcial.
  - **Evidencia:** gated `backend/tests/test_integracion_multitenant_010.py::test_dashboard_global_agrega_homonimos_con_atribucion`, `::test_lectura_global_es_una_sola_transaccion_repeatable_read` (misma conexión, `REPEATABLE READ`, snapshot estable ante mutación concurrente), `::test_dashboard_global_aborta_si_un_tenant_no_esta_en_version`; SQLite `backend/tests/api/test_contexto_tenant_sqlite_010.py::test_tenants_registrados_deriva_del_mapa_y_excluye_control`, `::test_agregar_lista_global_sqlite_lee_una_sola_vez`.
- **AC-15** DADO que el portal mínimo de control está disponible, CUANDO Superadmin se autentica en `/control` y solicita el alta, ENTONCES puede usar ese flujo mínimo; un rol no Superadmin es denegado. La pantalla no ofrece CRUD completo de instituciones, usuarios ni permisos, reservado a Feature 012.
  - **Evidencia (automatizada):** `frontend/src/app/features/control/control.routes.spec.ts` (login público sin guard, alta protegida, sin rutas de CRUD), `frontend/src/app/core/guards/control-superadmin.guard.spec.ts` (Superadmin activa; Administrador/Bodeguero/Solicitante/`superadmin`/sin identidad redirigen a `/acceso-denegado` sin cerrar sesión), `frontend/src/app/features/control/control-login.component.spec.ts`, `frontend/src/app/features/control/alta-institucion.component.spec.ts`; `ng test` 198 SUCCESS. **Registrado en T15:** `/control` sirve (GET 200) y renderiza la pantalla de alta/login como Superadmin (Edge headless, perfil limpio) y el alta real se ejecutó contra PostgreSQL; la denegación de rol no Superadmin quedó cubierta por las specs Angular y por la observación en vivo de la sesión residual redirigida a `/acceso-denegado`. **Pendiente de cierre visual (T15/T16):** humo en 8080 tras rebuild y captura de pantallas en el navegador del usuario.
- **AC-16** DADO la suite ordinaria sobre SQLite en memoria, CUANDO se ejecuta `pytest`, ENTONCES corre usando un contexto lógico único sin afirmar aislamiento multi-esquema; las pruebas gated contra PostgreSQL 16 verifican routing, aislamiento con conexiones reutilizadas, bootstrap/migración y versionado.
  - **Evidencia:** `pytest` SQLite `601 passed, 33 skipped` (contexto lógico único, p. ej. `backend/tests/api/test_contexto_tenant_sqlite_010.py`); gated `POSTGRES_TEST_URL` `634 passed, 0 skipped` con `backend/tests/test_control_postgres_010.py`, `test_bootstrap_control_postgres_010.py`, `test_migracion_multitenant_010.py`, `test_integracion_multitenant_010.py` y `test_aprovisionamiento_postgres_010.py`.
- **AC-17** DADO una sesión ausente/inválida, rol sin permiso o tenant no resoluble/no compatible, CUANDO se consulta la API, ENTONCES se conservan las respuestas 401/403 apropiadas y la matriz central sigue siendo autoridad de autorización.
  - **Evidencia:** `backend/tests/api/test_permisos_010.py` (matriz central de 22 operaciones, exacta y sin relajar las 21 previas), `backend/tests/api/test_control_instituciones_010.py` (401/403 y OpenAPI documentado); `/openapi.json`: 20 rutas / 24 operaciones, con `POST /api/v1/control/instituciones/` publicando 201/401/403/409/422/503; `ng test` 198 SUCCESS. **Pendiente de registrar (T15):** recorrido real en 4200 (denegación por rol limitado).
- **AC-18** DADO el cierre de la Feature 010, CUANDO se solicita declararla cerrada, ENTONCES todas las tareas y AC tienen evidencia; pasan pytest y pruebas gated PostgreSQL, se verifica el contrato OpenAPI y los flujos tenant/globales y se cumple el cierre documental conforme a AGENTS.md §8.5–§8.7.
  - **Evidencia:** AC de cierre, respaldado únicamente por los checks siguientes: **T15** (suites finales + recorrido 4200), **T16** (rebuild y humo 8080), **T17** (revisión OpenAPI/matriz, grep documental y MEMORY) y **T18** (confirmación de cierre SDD). **Abierto:** no se declara cubierto hasta que T15–T18 queden completados.

## 7. Restricciones

- Clerk sigue siendo la única autoridad de autenticación; no se emite ni acepta JWT local HS256 y el correo se usa solo tras verificación de Clerk.
- El esquema efectivo es exclusivamente el resuelto en control a partir del correo verificado. Ninguna entrada del cliente ni conexión reutilizada puede alterarlo. Un fallo no degrada a global ni a un esquema predeterminado.
- La conexión y el pool siguen siendo únicos para `apt_erp`; no se crean bases físicas ni pools por institución.
- Identificadores de código y dominio siguen la convención española de AGENTS.md §6.
- Se conservan los roles literales y la matriz vigente; el aprovisionamiento requiere autorización explícita para Superadmin.
- Cada tenant conserva `institucion_id` y claves compuestas de Feature 008, con `institucion` local espejo y FK locales; no hay FK cross-schema.
- `institucion` es fuente de verdad en control; `rol` de Superadmin vive en control; `rol`, `prioridad` y `estado_ticket` se replican por tenant. Esta última distribución invierte la norma actual de `stack.md` y debe justificarse allí antes de implementar; esta spec no modifica dicho documento.
- La migración conserva datos reales, pobla el mapa correo-esquema de todos los usuarios y aborta sin cambios si alguna fila no puede asignarse inequívocamente. No borrar el volumen, ejecutar semilla destructiva ni truncar datos reales.
- La versión de tenant debe coincidir con la versión objetivo antes de enrutar solicitudes de negocio.
- Superadmin no realiza escrituras de negocio de catálogo, stock o tickets en tenants; intervenciones administrativas deben ser atribuibles como tales.
- Una lectura global requerida se realiza en una sola transacción consistente o falla sin exponer agregado parcial.
- SQLite no acredita aislamiento de esquemas ni semánticas propias de PostgreSQL; las garantías se verifican en PostgreSQL 16.
- La justificación y aprobación de cambios técnicos de estructura/modelo en `stack.md` es un prerrequisito externo a esta spec; no se modifica aquí.
