# Feature 017: Provisionamiento y gobierno de identidades

**Estado:** borrador  
**Release:** 2.0 — Sprint 6  
**Tipo:** Identidad federada, ciclo de vida administrativo y control SaaS

## 1. Problema

La gestión administrativa de la Feature 012 solo admite identidades que ya existen en Clerk, no conserva un estado persistido de invitación ni registra los motivos de cambios de usuarios. Además, el alta inicial de institución no puede invitar al primer Administrador. El Superadmin comparte lecturas de negocio con usuarios institucionales, aunque su responsabilidad es gobernar el servicio SaaS sin inspeccionar la actividad interna de las instituciones.

## 2. Objetivo

Permitir invitaciones de identidad federada desde los flujos autorizados, gobernar Administradores institucionales y sus estados, registrar justificaciones para mutaciones definidas y reservar al Superadmin una superficie SaaS sin lecturas de negocio. El estado de invitación será una proyección persistida; no habrá sincronización viva por fila. La bitácora visible se difiere a la Feature 018.

## 3. Alcance

### Dentro

- Invitación Clerk iniciada por backend al alta de usuario y al aprovisionar el Administrador inicial de institución.
- Alta local inmediata; la identidad autenticada sigue dependiendo de Clerk y la autorización del rol/asociación local.
- Si el correo ya existe en Clerk, creación solo local asociada a esa identidad, sin enviar invitación.
- Estado persistido de invitación, actualización idempotente de aceptación en primer login y estado separado de asociación local activa/inactiva.
- Reenvío mediante una invitación nueva y copia de URL solo en la respuesta inmediata de alta/reenvío.
- CRUD de Administradores por Superadmin a través de control; CRUD local de Bodegueros/Solicitantes por Administrador dentro de su tenant.
- Motivos obligatorios para las mutaciones enumeradas en D-7 y persistencia auxiliar en control.
- Métricas técnicas por institución, con distinción entre cifras conocidas y no disponibles.
- Retiro del Superadmin de todas las lecturas de negocio enumeradas en D-9, tanto en UI como en matriz/backend.
- Listado mínimo por institución de Administradores visible para Superadmin, exclusivamente para gobernar sus cuentas.

### Fuera

- Clerk Organizations, roles/permisos Clerk, creación directa de usuarios mediante `POST /v1/users`, registro público, sign-up propio o autenticación local.
- Exponer URLs de invitación en listados, dashboard o persistencia de motivos.
- Edición de correo local, credenciales, borrado físico de usuarios o identidades Clerk.
- Consulta viva puntual o masiva del estado de invitación en Clerk, incluyendo en listados; posible alcance de Feature 018 junto a la bitácora.
- Bitácora visible/paginada en 017; la tabla de motivos se conserva para su posible lectura en 018.
- Visibilidad de usuarios institucionales distintos de Administradores, atributos no mínimos de Administradores, tickets, inventario, movimientos o actividad operacional por Superadmin.
- Polling, webhooks, notificaciones adicionales, informes exportables o comparaciones/rankings de negocio.
- Cambios a capacidades funcionales por institución no requeridos para este alcance.

## 4. Decisiones

### D-1 — Invitación por Clerk y alta local

El backend crea invitaciones mediante Clerk Backend API (`POST /v1/invitations`), nunca crea directamente cuentas Clerk. Si la identidad ya existe en Clerk, se crea solo la asociación local y el estado persistido nace `aceptada`. Se normaliza el correo quitando espacios al inicio/final y convirtiéndolo a minúsculas, tanto al crear asociaciones como al resolver el correo primario verificado en autenticación. Si Clerk cambia posteriormente el correo primario, la asociación anterior no se renombra automáticamente: el acceso no resuelve hasta una reconciliación administrativa explícita; el cambio de correo queda fuera de 017.

Antes de crear una asociación tenant, se rechaza con **409** si el correo normalizado ya está mapeado a la identidad global de control/Superadmin. Un correo con invitación Clerk pendiente y sin usuario local puede recibir asociación tenant nueva usando la invitación existente como evidencia de identidad no materializada: no se crea otra invitación y el estado persistido queda `pendiente`; si Clerk informa identidad existente, queda `aceptada`.

**Por qué:** preserva Clerk como autoridad y evita asociar una identidad global de control a datos tenant o generar identidades duplicadas.

### D-2 — Dos confirmaciones locales y recuperación verificable

El alta sigue el orden: validar, solicitar invitación cuando proceda, confirmar usuario tenant y luego mapa control. Se conservan dos confirmaciones locales, sin transacción distribuida. Si falla el commit tenant, se intenta revocar la invitación recién creada; si también falla la revocación, se persiste en el registro auxiliar de motivos/constancias una acción `compensacion_invitacion_fallida`, con institución, correo normalizado, `invitacion_id`, instante y resultado del intento. No contiene el enlace. El error de alta informa que requiere reconciliación; Superadmin localiza la invitación huérfana en el dashboard de Clerk por `invitacion_id` y puede revocarla manualmente.

Si el commit tenant tuvo éxito y el mapa no, el endpoint responde **503** con identificador local del usuario y error recuperable; no declara alta completa. En el reintento del mismo alta, un usuario local con correo normalizado y sin mapa se reconoce como operación incompleta y se completa el mapa y el motivo de invitación asociado; no se responde 400 por duplicado ni se vuelve a invitar. Si el mapa ya existe, se responde **409** por duplicado. El alta institucional aplica estas reglas al primer Administrador.

**Por qué:** Clerk y los esquemas locales no comparten transacción; el reintento debe reparar el único estado parcial sin crear entidades o invitaciones adicionales.

### D-3 — Estado persistido, no lectura viva

El mapa de control guarda `estado_invitacion` (`pendiente`, `aceptada`, `revocada`, `expirada`), `invitacion_id` y timestamps relevantes. `expirada` se deriva únicamente del timestamp de expiración persistido. `revocada` se registra solo cuando Compustock ejecuta una revocación propia (compensación o acción administrativa); no se presume revocación manual externa. En el primer login exitoso con correo primario verificado y asociación activa, una escritura condicional cambia `pendiente` a `aceptada`; es idempotente y dos peticiones concurrentes no fallan ni revierten el estado. Un estado terminal no vuelve a `pendiente` por login.

Los listados leen solo lo persistido y ninguna operación de listado llama a Clerk. No hay estado `incompleto`: la falta de mapa es el hecho recuperable descrito en D-2, y estados no reconocidos/legados se presentan como `no disponible` sin afirmar aceptación. El estado de asociación local se presenta por separado; aceptación nunca reactiva una asociación inactiva.

**Por qué:** evita N+1 y límites de tasa, y hace que la aceptación se funde en un login verificado, no en una consulta externa repetida.

### D-4 — Reenvío significa crear invitación nueva

El reenvío autorizado crea una invitación nueva con `POST /v1/invitations` e `ignore_existing` según el contrato aplicable de Clerk. Si existe una invitación anterior pendiente conocida, el sistema intenta revocarla primero mediante `POST /v1/invitations/{id}/revoke`; luego crea la nueva y persiste su ID/expiración. La respuesta exitosa entrega el nuevo enlace solo una vez. Como revocar+crear no es atómico, un fallo de creación puede dejar revocada la anterior; se conserva el registro persistido anterior y la constancia del fallo, y se responde error sin afirmar que la invitación previa sigue activa. Si Clerk responde “ya invitado”, se consulta únicamente en el flujo puntual de reenvío el resultado de la creación: no se sustituye el ID persistido ni se devuelve enlace; respuesta **409** indicando que existe invitación y que debe aceptarse o revocarse. Si la invitación expira entre la validación y el reenvío, se intenta crear la nueva; ante rechazo, **409** con instrucción de reintento y sin cambiar el estado persistido a `aceptada`.

Una invitación aceptada no se reenvía. `revocada` o `expirada` permite crear una nueva invitación. La misma operación de reenvío está disponible para Superadmin sobre Administradores vía control y para Administrador sobre Bodegueros/Solicitantes de su tenant vía ruta ordinaria. El reenvío no cambia `mapa_usuario_esquema.activo` ni reactiva una asociación inactiva. Para un usuario inactivo, la reactivación sigue siendo `PATCH .../estado` con `activo=true` y motivo; tras reactivarse, el Administrador puede llamar al reenvío ordinario, que crea la invitación nueva. Son dos operaciones distintas porque el servicio de estado no crea enlaces ni llama a Clerk, mientras `reenviar_invitacion` ya implementa la rotación Clerk sin alterar el estado local.

Ninguna operación de listado hace consultas Clerk.

**Por qué:** Clerk no ofrece endpoint de reenvío; crear una invitación nueva refleja su API real y explicita la ventana no atómica.

### D-5 — Motivos y dos confirmaciones para mutaciones

El catálogo de motivos es `cambio_funciones`, `reasignacion_organizacional`, `correccion_datos`, `termino_vinculo`, `seguridad_acceso` y `otro`. `otro` exige texto explicativo no vacío; todos los textos explicativos, incluido el de `otro`, admiten como máximo 500 caracteres. Para los demás códigos el texto es opcional. La validación de motivo precede cualquier mutación.

Para edición, baja o reactivación: primero se confirma en tenant el cambio de usuario (y en baja/reactivación el estado de mapa en el límite transaccional correspondiente), después se confirma en control el registro de motivo. Si la segunda confirmación falla, el cambio de negocio permanece aplicado, la operación responde **503** y se registra una constancia recuperable sin motivo completo; repetir la misma mutación con el mismo identificador idempotente completa el registro de motivo sin repetir el cambio de negocio. No se promete atomicidad entre tenant y control.

**Por qué:** conserva las dos confirmaciones requeridas y hace explícita la inconsistencia posible en vez de fingir reversión distribuida.

### D-6 — Persistencia auxiliar; lectura diferida

La estructura auxiliar en control registra actor, usuario objetivo cuando exista, institución, acción, motivo/código y texto, fecha/hora e identificador idempotente. También admite constancias de compensación de invitación fallida y de fallo de persistencia de motivo, distinguidas de una justificación administrativa. No registra enlaces. No existe endpoint de lectura en 017; la Feature 018 puede exponerla como bitácora y deberá definir retención antes de habilitar esa lectura.

**Por qué:** conserva evidencia recuperable y deja el historial visible fuera de esta entrega.

### D-7 — Operaciones con motivo y excepciones

El conjunto cerrado que exige motivo es: `PUT /api/v1/usuarios/{usuario_id}`, `PATCH /api/v1/usuarios/{usuario_id}/estado`, `PUT /api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}` y `PATCH /api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado`. La edición exige motivo solo si cambia efectivamente un atributo. Una baja/reactivación repetida sin cambio es idempotente y no exige ni registra motivo. `PUT /api/v1/organizacion/usuarios/{usuario_id}/sede` queda expresamente fuera de motivos en 017: es una reasignación de sede organizacional ya protegida por el contrato 011/012, y el catálogo de motivos no obliga a etiquetar toda operación de reasignación; incorporarla requeriría cambio de requisito.

Una institución no puede quedar sin Administrador activo: la baja por Superadmin o por el propio Administrador que dejaría cero Administradores activos responde **409**, incluye el motivo del bloqueo y no cambia usuario, mapa ni tabla de motivos.

**Por qué:** define exhaustivamente qué acciones se justifican y protege la continuidad administrativa institucional.

### D-8 — Gobierno técnico y taxonomía única de tenant

El dashboard SaaS muestra el conteo de instituciones, conteos técnicos conocidos de Administradores activos/inactivos y usuarios activos por rol solo donde sean visibles según el ámbito, sedes y departamentos, estado institucional, estado técnico y versión persistida/objetivo. La taxonomía es:

- `operativo`: institución activa, esquema enrutable y versión exactamente compatible; se muestran conteos técnicos consultados.
- `no enrutable`: institución inactiva, o activa cuya resolución de esquema falla por metadatos/routing; no se consulta el tenant y los conteos se muestran como no disponibles (institución inactiva se sigue listando y contando en institución total, pero no se dan conteos de su tenant).
- `no disponible`: institución activa y resoluble cuyo tenant no responde o tiene versión ausente, ilegible o incompatible; no se muestran conteos como fiables y se marcan no disponibles.

Las instituciones inactivas no muestran conteos técnicos conocidos. El conjunto no duplica “usuarios por rol” y “Administradores”: métricas únicas son total de instituciones, total de Administradores activos/inactivos en tenants operativos, total de usuarios activos por cada rol no privilegiado en tenants operativos, sedes y departamentos por institución, más conteos agregados `conocidos` y `no_disponibles`. Los conteos incluyen solo asociaciones locales activas; Administradores inactivos se reportan en su métrica separada. Superadmin no recibe conteos personales ni detalle de negocio.

**Por qué:** evita tratar la inaccesibilidad como cero y unifica el estado de tenant para UI, API y criterios.

### D-9 — Superadmin sin lectura de negocio

La única superficie de Superadmin es `/control/*` más la gestión de Administradores institucionales. Se deniega en UI y en matriz/backend toda lectura de negocio de: `GET /api/v1/dashboard/`; `GET /api/v1/tickets/`, detalle de ticket e historial de transiciones; `GET /api/v1/inventario/movimientos`; lecturas de categorías, productos, existencias y stock; y las demás operaciones de escritura de negocio permanecen denegadas según matriz vigente. No puede leer detalle de negocio desde ningún endpoint tenant. Los roles de negocio conservan sus permisos y ámbitos.

**Por qué:** el rol Superadmin gobierna SaaS y no debe inspeccionar contenido operacional institucional.

### D-10 — Contrato de gestión Superadmin y rutas ordinarias

Las rutas de control aceptan institución como ID de recurso; el servidor valida su registro en control y deriva tenant/esquema exclusivamente desde ahí. El cliente nunca selecciona esquema. Contratos nuevos:

| Operación | Entrada | Éxito | Errores relevantes |
|---|---|---|---|
| `GET /api/v1/control/instituciones/{institucion_id}/usuarios/` | Sin cuerpo | `200` `AdministradorListadoControlRespuesta[]`: `usuario_id`, `nombre`, `apellido`, `correo`, `activo`, `estado_invitacion` | `401`, `403`, `404`, `503` |
| `POST /api/v1/control/instituciones/{institucion_id}/usuarios/` | `UsuarioCrear` (sin esquema) | `201` `UsuarioInvitacionRespuesta`, URL solo en esta respuesta | `401`, `403`, `404`, `409`, `422`, `503` |
| `PUT /api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}` | `UsuarioEditar` + motivo | `200` `UsuarioRespuesta` | `401`, `403`, `404`, `409`, `422`, `503` |
| `PATCH /api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/estado` | `UsuarioEstado` + motivo | `200` `UsuarioRespuesta` | `401`, `403`, `404`, `409`, `422`, `503` |
| `POST /api/v1/control/instituciones/{institucion_id}/usuarios/{usuario_id}/invitacion/reenvio` | Sin cuerpo | `200` `UsuarioInvitacionRespuesta`, URL solo en esta respuesta | `401`, `403`, `404`, `409`, `422`, `503` |
| `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio` | Sin cuerpo | `200` `UsuarioInvitacionRespuesta`, URL solo en esta respuesta | `401`, `403`, `404`, `409`, `422`, `503` |

La ruta de reenvío ordinaria la usa el Administrador únicamente sobre Bodegueros/Solicitantes de su tenant; Superadmin recibe **403** antes de lectura en todas las rutas ordinarias de `/api/v1/usuarios/`. Las rutas de control de reenvío las usa solo Superadmin y solo sobre Administradores. Reenvío requiere asociación activa; para asociación inactiva se usa primero la reactivación motivada por `PATCH .../estado` y luego el reenvío, cada uno con su propia respuesta/efecto. Los nombres de DTO son etiquetas contractuales; sus campos completos se fijarán en el plan. El listado de control solo incluye Administradores y sus cinco campos mínimos arriba.

**Por qué:** separa la gestión global limitada de la API tenant y hace verificables autoridad y exposición mínima.

### D-11 — Compatibilidad histórica explícita

Esta feature supersede las normas concretas enumeradas en §9. Las specs previas permanecen sin edición como registro histórico; su norma anterior no gobierna los comportamientos aquí modificados.

**Por qué:** mantiene trazabilidad sin permitir contratos contradictorios.

## 5. Reglas del flujo

1. Normalizar correo (trim + minúsculas); validar duplicados, identidad control, estado de institución y alcance antes de invitar.
2. Si dos altas concurrentes usan el mismo correo normalizado, la unicidad del mapa/usuario elige una: una puede crear y la otra recibe **409**, salvo el caso recuperable de usuario tenant sin mapa, que completa asociación conforme a D-2.
3. Alta concurrente con reenvío: `ignore_existing` no habilita duplicar identidad; si Clerk informa invitación existente, el reenvío responde 409 y conserva el ID persistido. Si una invitación nueva se crea pero persiste un ID diferente concurrentemente, prevalece el último commit válido del mapa y la invitación no referenciada se trata como huérfana con compensación/constancia.
4. Alta: emitir invitación solo si Clerk no indica invitación pendiente ni identidad existente; confirmar tenant y luego control. Reintento repara usuario local sin mapa.
5. Primer login verificado: transición condicional idempotente `pendiente → aceptada`; dos logins simultáneos dejan el estado aceptado y el login autenticado no falla por doble actualización.
6. Listados nunca llaman a Clerk. Expiración deriva del timestamp almacenado; revocada solo refleja acción propia registrada.
7. Reenvío crea invitación nueva: Superadmin usa la ruta de control para Administradores y Administrador usa `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio` para Bodegueros/Solicitantes propios. Intenta revocar la pendiente anterior cuando sea posible; no promete conservarla activa si crear falla. Requiere asociación activa. Reactivar una asociación inactiva es una operación distinta: `PATCH .../estado` con `activo=true` y motivo; después se puede reenviar.
8. Mutaciones con motivo siguen D-5 y D-7; fallo al confirmar motivo responde 503 con constancia/idempotencia.
9. Baja de último Administrador activo bloqueada con 409 para Superadmin y auto-baja.
10. La ruta Superadmin de control valida institución en control, deriva esquema en servidor y limita el resultado a Administradores. Ruta ordinaria de usuarios invocada por Superadmin responde 403.
11. Dashboard técnico usa únicamente la taxonomía de D-8; no consulta tickets, productos, existencias ni movimientos.

## 6. Criterios de aceptación

### Invitación, estados y recuperación

- **AC-1** DADO un Administrador que da de alta un Bodeguero/Solicitante sin identidad ni invitación Clerk, ENTONCES el correo se normaliza con trim y minúsculas, se crea invitación, usuario tenant y mapa en ese orden y se entrega estado `pendiente` con URL solo en respuesta. Fallo de validación/Clerk no crea usuario local.
  - **Evidencia:** `backend/tests/test_frontera_clerk_017.py` (27 tests: normalización, búsqueda identidad/invitación, creación con `ignore_existing`, conflicto, errores de red/429/5xx/payload, y los dos casos nuevos que fijan la forma real del listado de invitaciones); `test_provisionamiento_identidades_017.py` (`test_alta_persiste_el_correo_normalizado`, `test_fallo_de_la_frontera_clerk_no_crea_usuario_local`, `test_validacion_fallida_no_crea_usuario_local`); `test_gobierno_administradores_017.py::test_alta_sin_identidad_crea_invitacion_y_estado_pendiente`. Recorrido 4200 con escritura real (`evidencia/README.md` §3.1 #3 y §3.3 #13): alta de correo nuevo → **201** con `url_invitacion` y mapa `pendiente` verificado por SQL; el alta duplicada con el mismo correo sucio responde **409** sin segunda fila (§3.3 #25).
- **AC-2** DADO correo existente en Clerk, invitación pendiente sin usuario local, mapa inactivo de la misma institución o usuario tenant sin mapa, CUANDO se intenta el alta/recuperación, ENTONCES respectivamente: identidad existente crea asociación `aceptada` sin invitación; invitación pendiente crea asociación `pendiente` sin nueva invitación; mapa inactivo no se reactiva mediante alta ni reenvío, sino mediante `PATCH /api/v1/usuarios/{usuario_id}/estado` (o su ruta control equivalente) con `activo=true` y motivo; después de esa reactivación, el reenvío autorizado crea invitación nueva; usuario local sin mapa completa asociación/motivo en reintento en vez de devolver duplicado. Correo mapeado a otra institución devuelve 409 sin mutación. Correo de Superadmin/control devuelve 409.
  - **Evidencia:** `test_gobierno_administradores_017.py` (`test_alta_con_identidad_existente_no_invita`, `test_alta_reutiliza_invitacion_pendiente_sin_crear_otra`, `test_fallo_del_mapa_responde_503_y_el_reintento_completa`); `test_provisionamiento_identidades_017.py::test_reintento_de_usuario_local_sin_mapa_completa_la_asociacion`; `test_gobierno_correcciones_017.py` (`test_reenvio_ordinario_de_asociacion_inactiva_responde_409_sin_reactivar`, `test_reactivacion_motivada_y_reenvio_son_operaciones_separadas`, `test_control_reenvio_de_asociacion_inactiva_responde_409`). Recorrido `evidencia/README.md` §3.3 #14 (identidad preexistente → `aceptada` y `url_invitacion=null`), #19 (reenvío sobre inactiva → **409**), #20–#21 (reactivación motivada y **después** reenvío con URL nueva) y §3.4 #28 (alta institucional con identidad preexistente → `aceptada` sin invitación).
- **AC-3** DADO alta institucional con primer Administrador, CUANDO Clerk o una escritura local falla, ENTONCES la institución solo se informa operativa tras completar el flujo; si falla la escritura tenant se intenta revocar invitación y si la revocación falla se persiste constancia con `invitacion_id`, sin URL. Si falla mapa después del commit tenant, responde 503 recuperable y el reintento completa el mapa sin duplicar usuario/invitación.
  - **Evidencia:** `test_gobierno_administradores_017.py` (`test_fallo_tenant_revoca_la_invitacion`, `test_fallo_de_revocacion_persiste_constancia_con_invitacion_id`, `test_fallo_del_mapa_responde_503_y_el_reintento_completa`); gated `test_correcciones_postgres_017.py` (`test_reintento_completa_control_sin_duplicar_tenant_usuario_ni_invitacion`, `test_reintento_con_esquema_incompatible_responde_503_recuperable`). Recorrido `evidencia/README.md` §3.1 #3 (INST-017: **201** `estado="operativa"` con mapa `pendiente` e `invitacion_id`, 17 tablas en el esquema nuevo) y §3.4 #28 (INST-018 con identidad preexistente: sin invitación ni URL).
- **AC-4** DADO primer login con correo primario verificado y asociación activa, ENTONCES una escritura condicional persiste `aceptada`; dos peticiones simultáneas producen un único estado final aceptado, sin error observable ni reactivación de mapa inactivo.
  - **Evidencia:** `backend/tests/test_aceptacion_invitacion_017.py` (8 tests: transición, idempotencia, estados terminales, mapa inactivo, sin mapa, correo no verificado, correo normalizado y dos logins); gated `test_aceptacion_invitacion_postgres_017.py::test_dos_primeros_logins_concurrentes_dejan_un_unico_aceptada` y `::test_mapa_inactivo_conserva_inactividad_y_pendiente`. Recorrido `evidencia/README.md` §3.2: el invitado acepta el enlace real en Clerk y el primer `GET /auth/me` deja `estado_invitacion=aceptada` con `invitacion_aceptada_en=2026-10-20 06:03:59.814823`, que el segundo login **no** reescribe (mismo timestamp por SQL).
- **AC-5** DADO cualquier listado tenant o control, ENTONCES muestra únicamente estado persistido, estado local activo/inactivo, y nunca contiene URL ni consulta Clerk; estados permitidos son pendiente/aceptada/revocada/expirada y `no disponible` para legado/desconocido. Expirada deriva del timestamp. Ningún listado invoca Clerk.
  - **Evidencia:** `test_gobierno_identidades_017.py` (`test_mapa_declara_la_proyeccion_persistida_de_invitacion`, `test_mapa_legado_sin_estado_se_proyecta_como_no_disponible`, `test_proyeccion_conserva_los_cuatro_estados_y_descarta_desconocidos`, `test_listado_minimo_de_administradores_expone_estado_sin_url`); `test_provisionamiento_identidades_017.py::test_listado_de_usuarios_no_expone_la_url_de_invitacion`; `test_gobierno_administradores_017.py::test_listado_control_solo_administradores_y_sin_clerk`; specs `usuarios.component.spec.ts` y `administradores-control.component.spec.ts` (estados y ausencia de URL). Recorrido `evidencia/README.md` §3.1 #4 (cinco campos, pendiente), §3.3 #15 (JSON sin la cadena `url`) y §3.3 #27 (vinculo inactivo y `estado_invitacion=pendiente` mostrados por separado).
- **AC-6** DADO Administrador que reenvía a Bodeguero/Solicitante propio mediante `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio`, o Superadmin que reenvía a Administrador mediante la ruta control D-10, ENTONCES se aplican las mismas reglas Clerk: requiere asociación local activa, intenta revocar la anterior y crea una nueva, entregando URL solo en respuesta exitosa. Si creación falla tras revocación, responde error y mantiene evidencia/constancia, sin afirmar que la anterior sigue activa. Si Clerk responde “ya invitado”, responde 409 sin cambiar ID ni entregar enlace; aceptada responde 409; expirada entre validación y creación responde 409 sin marcar aceptada. Asociación inactiva responde 409 y debe reactivarse primero con `PATCH .../estado` y motivo; reactivación y reenvío son operaciones distintas.
  - **Evidencia:** `test_gobierno_correcciones_017.py` (reenvío ordinario: rotación y URL única, autorización por rol, 404 ajeno, 403 objetivo Administrador, 409 aceptada/conflicto/inactiva, reactivación→reenvío separadas, contrato OpenAPI); `test_gobierno_administradores_017.py` (`test_reenvio_crea_invitacion_nueva_y_actualiza_el_mapa`, `test_reenvio_de_invitacion_aceptada_responde_409`, `test_reenvio_con_conflicto_no_cambia_el_id_persistido`); `test_frontera_clerk_017.py` (`test_crear_invitacion_ya_invitado_es_conflicto_de_dominio`, `test_crear_invitacion_respeta_ignore_existing_explicito`). Recorrido `evidencia/README.md` §3.1 #6 y §3.3 #17/#21 (el `invitacion_id` rota y la URL viaja solo en la respuesta), #19 (**409** con la inactiva), #20–#21 (dos operaciones separadas).
- **AC-7** DADO alta/reenvío concurrente para el mismo correo, ENTONCES solo una identidad local/mapeo prevalece; la otra solicitud responde 409 o completa específicamente un usuario local sin mapa. No se crean dos invitaciones activas conocidas; toda invitación no referenciada por carrera queda con constancia y `invitacion_id` localizable.
  - **Evidencia:** `test_provisionamiento_identidades_017.py::test_dos_altas_del_mismo_correo_normalizado_producen_409` (una crea, la otra 409, una sola fila); `test_gobierno_administradores_017.py::test_fallo_de_revocacion_persiste_constancia_con_invitacion_id` (invitación huérfana localizable); gated `test_dashboard_tecnico_postgres_017.py::test_unicidad_concurrente_del_mapa` y `test_correcciones_postgres_017.py::test_bajas_concurrentes_de_administradores_nunca_dejan_cero_activos`. Recorrido `evidencia/README.md` §3.3 #25 (alta duplicada con el mismo correo normalizado → **409** sin segunda fila).

### Mutaciones, motivos y rutas

- **AC-8** DADO Superadmin, ENTONCES las cinco operaciones de control previas de D-10 son accesibles solo mediante control y con los DTO/códigos de éxito y errores enumerados. Esquema no es entrada. Un ID de institución inexistente responde 404; rol no autorizado 403; sesión ausente 401. En `GET` el resultado contiene únicamente los cinco campos mínimos y solo Administradores. Superadmin en cualquier ruta ordinaria `/api/v1/usuarios/`, incluida `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio`, recibe 403 sin lectura.
  - **Evidencia:** `test_gobierno_administradores_017.py` (`test_control_institucion_inexistente_responde_404`, `test_control_alta_rechaza_rol_no_administrador`, `test_control_no_gestiona_usuarios_que_no_son_administradores`, `test_control_edicion_y_estado_motivados`, `test_superadmin_recibe_403_en_usuarios_ordinarios`); `tests/api/test_gobierno_lecturas_017.py` (matriz, contrato y 403 real de Superadmin); `test_gobierno_correcciones_017.py` (`test_reenvio_ordinario_solo_lo_autoriza_el_administrador`, `test_reenvio_ordinario_deniega_otros_roles_sin_mutar`, `test_control_permite_degradar_si_queda_otro_administrador_activo`). Recorrido `evidencia/README.md` §3.1 #4–#10 y §3.3 #26. OpenAPI vivo con las seis operaciones (§4 de la evidencia).
- **AC-9** DADO Administrador institucional, ENTONCES `GET/POST /api/v1/usuarios/` y operaciones CRUD ordinarias quedan limitadas a su tenant; puede reenviar invitaciones solo a Bodegueros/Solicitantes activos de su tenant mediante la ruta D-10 ordinaria. Superadmin gestiona Administradores únicamente mediante control. Roles distintos o usuario objetivo ajeno/incompatible reciben 403/404 según el contrato, sin mutación.
  - **Evidencia:** `test_gobierno_correcciones_017.py` (`test_reenvio_ordinario_rechaza_objetivo_ajeno_con_404`, `test_reenvio_ordinario_rechaza_objetivo_administrador_con_403`, `test_reenvio_ordinario_deniega_otros_roles_sin_mutar` parametrizado); `test_gobierno_administradores_017.py::test_superadmin_recibe_403_en_usuarios_ordinarios`; `tests/api/test_gobierno_lecturas_017.py` (roles de negocio preservados). Recorrido `evidencia/README.md` §3.3 #13–#27: el Administrador de INST-017 opera solo su tenant (altas, edición, baja/reactivación y reenvío con 200/409/422) y recibe **403** en la ruta de control (#26).
- **AC-10** DADO edición efectiva o baja/reactivación en el conjunto cerrado D-7, ENTONCES requiere código válido y texto explicativo ≤500 caracteres; `otro` requiere texto no vacío de hasta 500. Entrada inválida responde 422 sin cambio. Reasignación de sede no requiere motivo en 017. Operación idempotente no requiere motivo ni genera registro.
  - **Evidencia:** `test_gobierno_identidades_017.py` (`test_motivo_mutacion_acepta_catalogo_cerrado_y_texto_opcional`, `test_motivo_mutacion_rechaza_codigo_invalido_y_otro_sin_texto`); `test_gobierno_administradores_017.py` (`test_edicion_efectiva_sin_motivo_responde_422_sin_mutar`, `test_estado_repetido_no_exige_ni_genera_motivo`); specs `usuarios.component.spec.ts` (motivo `otro` vacío y >500 sin envío). Recorrido `evidencia/README.md` §3.1 #5, §3.3 #16, #24 (**422** con `otro` en blanco) y #27; los seis motivos persistidos llevan código y texto literales.
- **AC-11** DADO mutación con motivo aceptada, ENTONCES su fila persistida incluye actor, objetivo, institución, acción, código, texto aclaratorio (incluido el de `otro`), fecha/hora e idempotencia. Si falla la confirmación control tras cambio tenant, responde 503 y deja constancia; reintento con el mismo identificador completa el motivo sin repetir cambio. No existe endpoint lector en 017.
  - **Evidencia:** `test_gobierno_administradores_017.py` (`test_edicion_efectiva_con_motivo_persiste_justificacion`, `test_fallo_de_la_segunda_confirmacion_responde_503_y_el_reintento_completa`); `test_gobierno_identidades_017.py` (`test_registro_declara_campos_de_evidencia_y_clave_idempotente`, `test_registro_persiste_una_constancia_de_compensacion`, `test_registro_rechaza_clave_idempotente_repetida`); `test_gobierno_correcciones_017.py` (`test_fallo_de_mapa_deja_evidencia_con_clave_e_invitacion`, `test_reintento_con_invitacion_pendiente_sin_evidencia_responde_503`). Recorrido `evidencia/README.md` §3.5: **6** filas en `control.registro_motivo_constancia` con actor, correo objetivo, institución, acción, código, texto, fecha e `clave_idempotente`, y ninguna URL; no existe endpoint de lectura (OpenAPI, §4).
- **AC-12** DADO baja que dejaría cero Administradores activos, incluida la auto-baja, ENTONCES responde 409 con motivo explícito y no modifica usuario, mapa ni registro de motivo. Si queda al menos uno, baja lógica impide routing sin borrar identidad Clerk o historial.
  - **Evidencia:** `test_gobierno_administradores_017.py::test_baja_del_ultimo_administrador_responde_409_sin_mutar`; `test_gobierno_correcciones_017.py` (`test_control_no_degrada_al_ultimo_administrador_activo`, `test_control_permite_degradar_si_queda_otro_administrador_activo`); gated `test_correcciones_postgres_017.py::test_bajas_concurrentes_de_administradores_nunca_dejan_cero_activos` (resultados exactos `["409","ok"]`, una sola asociación activa). Recorrido `evidencia/README.md` §3.1 #7 (control → **409**) y §3.3 #22/#23 (auto-baja y degradación → **409**), con usuario, mapa y motivos verificados **sin** cambios por SQL.

### Gobierno, retirada de lecturas y verificación

- **AC-13** DADO GET `/api/v1/control/dashboard`, ENTONCES métricas únicas y conteos se ajustan a D-8: solo asociaciones activas en conteos por rol; Administradores inactivos se reportan separadamente; institución inactiva no presenta conteos tenant; totales identifican cantidades conocidas y no disponibles. No contiene datos personales, negocio o motivos.
  - **Evidencia:** `test_dashboard_tecnico_017.py` (`test_conteos_por_rol_solo_asociaciones_activas_y_administradores_separados`, `test_dto_tecnico_no_expone_datos_personales_ni_de_negocio`, `test_http_dashboard_publica_taxonomia_y_agregados`); gated `test_dashboard_tecnico_postgres_017.py::test_taxonomia_y_agregados_conocidos_no_disponibles`. Recorrido `evidencia/README.md` §3.1 #2 (4 instituciones `operativo`, `total_administradores_activos=4`/`inactivos=0`, `usuarios_por_rol={"Solicitante":5,"Bodeguero":3}`, `conteos_conocidos=4`, `conteos_no_disponibles=0`, sin correos ni datos de negocio) y §3.4 #30 (6 instituciones, la administrativa `CTRL-SAAS` fuera del conteo).
- **AC-14** DADO instituciones de las tres clases de D-8, ENTONCES operativo muestra conteos y versión; no enrutable y no disponible muestran conteos tenant como no disponibles, distinguiendo estado institucional/routing de fallo o incompatibilidad del tenant. Instituciones inactivas se listan y cuentan en total de instituciones, sin métricas tenant. No se consultan datos de negocio para clasificar.
  - **Evidencia:** `test_dashboard_tecnico_017.py` (`test_taxonomia_operativo_no_enrutable_y_no_disponible`, `test_no_enrutable_no_abre_el_tenant`, `test_tenant_que_no_responde_es_no_disponible_nunca_cero`); gated `test_dashboard_tecnico_postgres_017.py` (`test_taxonomia_y_agregados_conocidos_no_disponibles`, `test_clasificacion_no_consulta_datos_de_negocio` — el dashboard sigue operativo tras eliminar tickets/catálogo/stock/movimientos del tenant). Recorrido `evidencia/README.md` §3.1 #2 y §3.4 #30: las seis instituciones reales se clasifican `operativo` con `version_objetivo = version_persistida = "013.1"`; las clases `no enrutable`/`no disponible` se ejercitan en los tests gated con esquemas temporales.
- **AC-15** DADO Superadmin y cualquiera de estas operaciones: `GET /dashboard/`; `GET /tickets/`; detalle de ticket; historial de transiciones; `GET /inventario/movimientos`; lecturas de categorías, productos, existencias o stock, ENTONCES cada una responde 403 en backend/matriz y no devuelve datos. UI no ofrece ni permite activar `/dashboard/`, `/tickets/` o `/inventario/`; solo `/control/*` y gestión de Administradores. Otros roles conservan su matriz vigente.
  - **Evidencia:** `backend/tests/api/test_gobierno_lecturas_017.py` (73 tests: las 11 operaciones de D-9 con 403 real y sin datos, roles institucionales preservados, matriz y 55 operaciones); specs `frontend/src/app/core/guards/superficies-retiradas.spec.ts` (router real: `/dashboard`, `/inventario`, `/tickets`, `/administracion` → `/acceso-denegado`), `app.routes.spec.ts`, `app.component.spec.ts` y `roles.spec.ts`; recorrido `evidencia/README.md` §3.1 #9 (las cinco lecturas → **403** literal) y §8.1 (el bundle de 8080 sirve el mapa de rutas con `/control` y Administradores).
- **AC-16** DADO dos operaciones simultáneas de primer login con una asociación pendiente, ENTONCES ambas finalizan autenticadas sin error por carrera y el estado persistido queda `aceptada` una sola vez; una asociación inactiva permanece inactiva.
  - **Evidencia:** gated `backend/tests/test_aceptacion_invitacion_postgres_017.py` (barrera que sincroniza dos primeros logins: ambos **200**, mapa `aceptada` una sola vez con timestamp único; con `activo=False` el login responde **401** y el mapa queda inactivo/`pendiente`); `test_aceptacion_invitacion_017.py::test_dos_logins_consecutivos_dejan_una_sola_aceptacion`. Recorrido `evidencia/README.md` §3.2 (dos `GET /auth/me` consecutivos: mismo `invitacion_aceptada_en`, sin reescritura).
- **AC-17** DADO el contrato de rutas nuevas, ENTONCES pruebas de contrato verifican método, ruta, DTO, código de éxito, seguridad y 401/403/404/409/422/503 que aplique; una comparación automatizada confirma que cada operación retirada de AC-15 está denegada en la matriz para Superadmin.
  - **Evidencia:** `backend/tests/api/test_gobierno_lecturas_017.py` (transcribe `OPERACIONES_RETIRADAS_017`, fija las seis rutas D-10 —método, `response_model`, éxito y respuestas publicadas— y compara el conjunto de operaciones v1 de `/openapi.json` con `MATRIZ_PERMISOS`); `test_gobierno_correcciones_017.py` (`test_openapi_publica_el_reenvio_ordinario_con_su_contrato`, `test_openapi_documenta_503_en_el_dashboard`). Recorrido `evidencia/README.md` §4: el backend vivo publica **55** operaciones v1 (57 con `/` y `/health`) y las seis D-10 con sus códigos.
- **AC-18** DADO pruebas de instalación limpia PostgreSQL, ENTONCES existen la estructura auxiliar de motivos/constancias y las columnas de invitación nuevas en mapa de control, y la aprobación previa de `stack.md` cubre ambas modificaciones; pruebas verifican unicidad concurrente, reintentos tenant/mapa, doble login y bloqueo del último Administrador. Pruebas de frontend verifican listado mínimo, estados persistidos y denegación de las superficies retiradas.
  - **Evidencia:** `backend/tests/test_instalacion_limpia_postgres.py` (20 tablas de control, 17 por tenant y `test_estructura_de_invitacion_y_motivos_vive_solo_en_control`: columnas/`CHECK`/FK/unicidad solo en `control`, estados sembrados `aceptada` y ausencia total de los auxiliares en cada tenant); `test_gobierno_identidades_017.py` (metadata tenant sin la tabla auxiliar); gated `test_dashboard_tecnico_postgres_017.py` (unicidad concurrente, reintento tenant/mapa), `test_aceptacion_invitacion_postgres_017.py` (doble login) y `test_correcciones_postgres_017.py` (último Administrador, reintento del alta); aprobación en `docs/spec/stack.md` §2 (T1). Frontend: `usuarios.component.spec.ts`, `administradores-control.component.spec.ts`, `dashboard-saas.component.spec.ts`, `control.routes.spec.ts` y `superficies-retiradas.spec.ts`. Recorrido `evidencia/README.md` §1: reset verificado con los conteos y la estructura reales (20/17, cuatro columnas nuevas, `registro_motivo_constancia` vacía, ningún auxiliar en los tenants, versión `013.1`, semilla `aceptada`).

## 7. Riesgos y limitaciones

- La aceptación se marca en primer login; una persona que acepta sin iniciar sesión puede seguir apareciendo pendiente. No hay sincronización instantánea.
- Clerk puede limitar invitaciones a 100 por hora; picos pueden producir 429 y obligar a reintentar.
- Dominios/orígenes y URL de redirección permitidos deben estar configurados en Clerk; una configuración incorrecta impide alta/reenvío.
- La canonicalización local de correo no puede corregir un cambio del correo primario Clerk; requiere reconciliación explícita fuera de 017.
- Las altas/reenvíos concurrentes pueden dejar una invitación externa huérfana; se registra `invitacion_id` y el Superadmin debe reconciliarla.
- La identidad global de control no puede invitarse a un tenant; se responde 409.
- Bloquear la baja del último Administrador puede impedir la rotación de responsables hasta crear/activar otro Administrador.
- El límite de dos confirmaciones permite estados parciales; constancias e idempotencia permiten recuperarlos pero no dan atomicidad distribuida.
- Clerk no tiene operación de reenvío; revocar+crear puede dejar la invitación anterior revocada si la creación nueva falla.
- La revocación manual requiere acceso al dashboard de Clerk y búsqueda por `invitacion_id`.
- La tabla de motivos/constancias debe conservarse si Feature 018 la expone; su retención y acceso se definirán antes de dicha exposición.
- El dashboard técnico atraviesa tenants activos; el coste aumenta con instituciones. Errores se reflejan como no disponibles, no como cero.
- Cambios de estructura requieren recrear el volumen según el procedimiento del proyecto; hacerlo elimina datos locales no respaldados.

## 8. Restricciones

- Clerk permanece como única autoridad de autenticación; solo backend usa secreto Clerk. No crear usuarios directamente, ni usar Clerk Organizations, roles Clerk o `clerk-sdk-python`.
- Listados nunca llaman a Clerk. Consulta puntual de estado Clerk queda fuera de 017, incluso si se evalúa para 018.
- No exponer secretos, tokens ni enlaces en listados, motivos, dashboard o logs persistidos.
- Rol local determina autorización. La invitación/aceptación no concede permisos.
- Tenant se resuelve en servidor; el cliente nunca escoge esquema.
- Lógica de negocio en servicios, matriz backend como frontera, DTOs Pydantic v2, frontend standalone con Signals/Tailwind; no SQL raw ni dependencias sin aprobación en plan.
- El modelo conserva 15 entidades de dominio + `departamento_encargado`; las columnas nuevas de `control.mapa_usuario_esquema` y la tabla auxiliar de motivos/constancias no son entidades tenant. La aprobación previa en `stack.md` debe cubrir **ambos cambios de estructura** antes de implementar.
- No se altera auditoría inmutable de inventario ni historial de transiciones de tickets.
- Política operativa de Clerk —límite de 100 invitaciones/hora, configuración de URL de redirección/orígenes permitidos y acceso manual al dashboard para revocar mediante `invitacion_id`— no se configura ni administra desde Compustock en 017.

## 9. Relación con especificaciones previas

Las specs 007, 010, 012 y 009 permanecen intactas como registro histórico. Solo las reglas explícitamente listadas aquí quedan supersedidas:

- **Feature 012 §3 «Fuera», literal:** «Crear, invitar, modificar credenciales o eliminar identidades en Clerk; la gestión de usuarios de esta feature administra identidades locales ya existentes en Clerk y su vinculación local.» Se supersede únicamente la prohibición de invitar: 017 permite enviar invitaciones, pero mantiene prohibida la creación directa de usuarios y la gestión de credenciales.
- **Feature 012 AC-8, literal:** «El alta y edición consumen las reglas de vinculación local con Clerk de Feature 011/contrato vigente, sin crear ni modificar identidades Clerk.» Queda supersedido en cuanto a alta: puede crear una invitación Clerk; no crea/modifica directamente una identidad Clerk.
- **Feature 012 §5 paso 9, literal:** «El alta de usuario local requiere identidad Clerk preexistente; la edición local no cambia credenciales ni identidad de Clerk.» La exigencia de identidad preexistente queda supersedida; aplica el flujo de invitación o identidad ya existente de D-1.
- **Feature 010 D-7, literal:** «El correo del primer Administrador debe existir previamente como usuario de Clerk. Si no existe, el alta falla explícitamente y no deja un tenant operativo.» Queda supersedida por la invitación inicial definida en D-1/D-2.
- **Feature 007 AC-3, literal:** «`Superadmin` y `Administrador` pueden acceder a dashboard, inventario, tickets y administración, conforme al límite institucional de AC-8.» Para Superadmin queda supersedida toda lectura de dashboard/inventario/tickets; permanece administración SaaS y gestión de Administradores.
- **Feature 007 AC-5, literal:** «La tabla de rutas de interfaz es: `dashboard` (Superadmin, Administrador, Bodeguero, Solicitante), `inventario` (los cuatro, con alcance institucional según AC-8), `tickets` (los cuatro, con capacidades según AC-3/AC-6/AC-7) y `administracion` (Superadmin y Administrador).» Para Superadmin quedan retiradas las rutas dashboard, inventario y tickets.
- **Feature 012 D-5, literal:** «Solo las instituciones activas son requeridas para el agregado; una activa inaccesible o incompatible causa error completo, no parcial.» Queda supersedida por D-8: conteos conocidos frente a no disponibles.
- **Feature 012 AC-4, literal:** «Una institución activa requerida inaccesible o incompatible causa error explícito sin presentar agregado parcial.» Queda supersedida por la taxonomía D-8, que devuelve agregados con conteos conocidos/no disponibles en vez de fallo completo.
- **Feature 012 §5 paso 6, literal:** «solo una falla de institución activa requerida produce error explícito, nunca un resultado parcial.» Queda supersedida por D-8 y AC-14.
- **Feature 009 D-3/AC-7 y Feature 007 D-3/AC-8:** alcance global de lectura Superadmin en datos operativos queda supersedido solo para las operaciones listadas en D-9; no se amplía ni altera el alcance de los demás roles.

La Feature 018 podrá definir una lectura de bitácora y una consulta puntual del estado Clerk; ninguna queda implícita en 017.

## 10. Decisiones confirmadas durante la aclaración

- Se mantienen dos confirmaciones locales; último Administrador activo no puede darse de baja.
- El Superadmin no accede a lecturas de negocio y solo ve el listado mínimo de Administradores por institución.
- Invitaciones listadas reflejan estado persistido; no hay lecturas Clerk por fila.
- Reenvío crea invitación nueva; la operación Clerk no es atómica con la revocación previa.
- Motivos aplican solo al conjunto cerrado D-7; reasignación de sede queda fuera.
- La bitácora visible y cualquier consulta puntual de estado Clerk se reservan para posible Feature 018.
