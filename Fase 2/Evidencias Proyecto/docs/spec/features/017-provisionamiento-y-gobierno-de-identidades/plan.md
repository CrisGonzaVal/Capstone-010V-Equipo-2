# Feature 017 — Plan técnico

Spec: [`spec.md`](spec.md). La spec aprobada por el usuario es la fuente de verdad; este plan concreta el CÓMO sin ampliar ni reinterpretar su alcance. No se agregan dependencias: `httpx` ya forma parte del backend.

## 1. Prerrequisito bloqueante: justificación y aprobación en `stack.md`

Antes de modificar modelos, DDL, semilla o aprovisionamiento, el usuario/coordinador debe incorporar y aprobar en `docs/spec/stack.md` §2 una justificación que cubra explícitamente **los dos cambios auxiliares de control**:

1. columnas `estado_invitacion`, `invitacion_id` y timestamps relevantes en `control.mapa_usuario_esquema`;
2. tabla auxiliar de motivos/constancias en `control`, incluido su propósito, campos, relaciones locales y clasificación fuera de las 15 entidades de dominio.

La aprobación no crea entidad tenant ni cambia relaciones/nulabilidades del modelo de dominio. La tabla no obtiene endpoint lector en 017. La instalación se recrea con `01_esquema.sql` y `02_datos_semilla.sql`; no hay migraciones. T1 deja el prerrequisito trazable y bloquea toda tarea estructural hasta aprobación explícita. El planner propone/incorpora el texto documental en la fase de cierre junto al coordinator; no se presupone que la aprobación de la spec sea aprobación de estructura.

## 2. Arquitectura de la solución por capas

### Frontera Clerk

- Extender `backend/app/core/security.py` con operaciones HTTP del Backend API: búsqueda puntual por correo para distinguir identidad existente/invitación pendiente y creación/revocación de invitaciones. Reutilizar `httpx.Client`, `CLERK_SECRET_KEY` y el transporte `httpx.BaseTransport` inyectable ya disponible; no usar `clerk-sdk-python` ni crear usuarios por `POST /v1/users`. `ignore_existing` se fija explícitamente según el flujo de alta/reenvío y nunca se interpreta como permiso para duplicar identidades.
- Normalizar el correo en los límites de creación/autenticación con `strip` y minúsculas. La comparación con Clerk usa la misma forma normalizada; el correo primario verificado retornado por Clerk también se normaliza antes del vínculo local. No se renombra una asociación si Clerk cambia después su correo.
- Clasificar resultados externos en errores del servicio: identidad existente → vínculo local aceptado sin invitación; invitación pendiente → reutilizar estado pendiente sin crear otra; creación nueva → guardar `id`, URL y expiración solo en el flujo de respuesta; errores de red/429/5xx o payload inesperado → 503 sin crear estado local. El “already invited”/`ignore_existing` de Clerk se resuelve puntualmente, sin sustituir el ID persistido ni emitir una URL en caso de conflicto. Pruebas usan transporte simulado y no hacen llamadas reales.
- En reenvío, intentar primero revocar la invitación pendiente persistida, luego crear una nueva. Si la creación falla, preservar el registro previo y guardar constancia del fallo; no declarar activa la invitación anterior. Una revocación confirmada por Compustock cambia estado a `revocada`; no inferir revocación externa.

### Persistencia, modelos y DDL

- Extender el modelo auxiliar de `MapaUsuarioEsquema` con estado de invitación, ID externa y timestamps definidos por la spec. Estados persistidos: `pendiente`, `aceptada`, `revocada`, `expirada`; `expirada` se deriva del vencimiento guardado. Asociación local `activo` permanece separada. La ausencia de mapa y los estados legados/desconocidos se proyectan como `no disponible`, nunca como `aceptada` ni `incompleto`.
- Añadir un modelo auxiliar de control para los motivos/constancias: actor, usuario objetivo nullable, institución, acción, código/texto de motivo, fecha/hora, identificador idempotente y los campos requeridos para constancias; la compensación fallida incluye `invitacion_id` pero nunca URL. Mantener sin endpoint lector.
- Actualizar `database/01_esquema.sql` en las tablas control canónicas y `database/02_datos_semilla.sql` en guardia, proyección de usuarios/mapeo y valores iniciales consistentes. Los nuevos campos no se copian a los tenants. Preservar los checks de instalación limpia y el prefijo/orden funcional de los dos scripts. No crear migraciones ni un tercer script.
- Los cambios SQL de `database/` quedan condicionados a aprobación previa en `stack.md`; validación gated contra PostgreSQL 16 comprueba catálogo real, restricciones, instalación limpia, concurrencia y paridad control/tenant.

### Servicios y límites de transacción

- `usuario_service.py` conserva altas tenant ordinarias y aplica validación del rol/ámbito existente; incorpora la orquestación de invitación y recuperación de usuario tenant sin mapa. `organizacion_service.py` conserva PUT/PATCH tenant y agrega motivos/idempotencia a las mutaciones especificadas.
- `control_service.py` recibe la superficie de gobierno por institución y administra altas de Administrador, listado mínimo, edición, estado, reenvío, dashboard técnico, motivos y constancias. Las rutas de control reciben ID institucional, verifican registro en control, derivan nombre de esquema en servidor mediante `tenant_service.nombre_esquema_para_institucion` y abren sesión tenant con `crear_sesion_esquema`; nunca se acepta esquema del cliente. El aprovisionamiento existente del primer Administrador aplica la misma secuencia de invitación, commits y compensación antes de declarar la institución operativa.
- Normalizar fallos de apertura/lectura/escritura de sesión tenant en las cinco operaciones de control D-10 y en dashboard a 503 y documentarlos en OpenAPI. Mantener intactos errores de dominio 404/409/422 y autorización 401/403; la clasificación del dashboard conserva el 200 con `no disponible` según D-8.
- La ruta ordinaria `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio` se monta en `usuarios.py`, llama `usuario_service.reenviar_invitacion` con la sesión del tenant y la de control, devuelve el DTO reutilizado `UsuarioInvitacionRespuesta` y se autoriza únicamente a `Administrador` para objetivos Bodeguero/Solicitante de su tenant. La entrada de `permisos.py` es explícita y no amplía permisos de las otras rutas ordinarias; Superadmin obtiene 403 en toda `/api/v1/usuarios/`. La ruta control equivalente sigue siendo solo Superadmin y limitada a Administradores.
- Alta con invitación: validar rol/ámbito/institución/correo/duplicados antes de invitar; pedir invitación cuando no exista identidad o invitación previa; confirmar usuario tenant y luego mapa/constancia en control en dos commits separados. Si falla commit tenant, revocar invitación recién creada; si revocación también falla, persistir `compensacion_invitacion_fallida` con `invitacion_id`. Si tenant commit tuvo éxito y mapa falla, responder 503 con identificador local; retry completa mapa/motivo sin invitar ni duplicar.
- Mutación con motivo: solo para las cuatro rutas cerradas de D-7 (PUT/PATCH usuarios tenant y equivalentes de control); validar código/texto antes de tocar negocio; confirmar cambio tenant y estado local aplicable, luego confirmar motivo en control. Ante fallo de segunda confirmación, responder 503 y registrar constancia recuperable; retry con el mismo identificador idempotente completa el motivo sin repetir la mutación. No prometer atomicidad distribuida ni compensar un cambio tenant confirmado. Reasignación de sede queda fuera; estados repetidos sin cambio no exigen ni generan motivo.
- Una asociación inactiva no puede reenviar: el Administrador usa primero `PATCH /api/v1/usuarios/{usuario_id}/estado` con `activo=true` y motivo, recibe la confirmación de esa mutación y después llama `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio`. Son operaciones separadas: el estado/reactivación persiste su motivo en control y el reenvío hace rotación Clerk, persiste ID/expiración y devuelve su enlace inmediato; reenviar no activa ni altera `mapa_usuario_esquema.activo`.
- Bloquear baja (incluida auto-baja) si deja cero Administradores activos: evaluar y serializar bajo transacción/locking compatible con PostgreSQL; responder 409 antes de cambiar usuario, mapa o motivo. Las carreras concurrentes se prueban gated.
- Aplicar la misma guarda de continuidad a una edición vía control que cambiaría de Administrador a Bodeguero/Solicitante cuando la degradación dejaría cero Administradores activos; 409 antes de escribir usuario o motivo. No bloquear ediciones que preservan el rol ni degradaciones cuando queda otro Administrador activo.
- `auth_service.py` al resolver el login obtiene el correo primario verificado normalizado y, con asociación activa, invoca escritura condicional en control `pendiente → aceptada`. La actualización no falla por carrera, es idempotente, no reactiva asociaciones inactivas y no transforma estados terminales.
- Reintento de aprovisionamiento institucional tras commit tenant y fallo de confirmación control: detectar el esquema determinista ya existente, validar que contiene la institución espejo, versión y Administrador inicial compatibles, y completar el registro/mapa de control sin repetir Clerk, crear esquema, duplicar usuario ni sobrescribir datos incompatibles. Un resto parcial que no cumpla esas precondiciones queda en error recuperable/503 y requiere reconciliación, nunca se declara operativo.
- `_completar_alta_sin_mapa` debe recuperar el registro de motivo/constancia correspondiente al alta original además de completar el mapa. Reutilizar solo una clave idempotente persistida y correlacionable con la invitación; si la clave necesaria no existe o no puede recuperarse, no inventar una y devolver 503 recuperable.
- `tenant_service.py`/dependencias se usan para confirmar la resolución del tenant sin confiar en `institucion_id` o esquema del cliente. En endpoints control la sesión tenant se resuelve por el registro de control, no por el contexto tenant del Superadmin.

### Schemas, endpoints, permisos y dashboard

- Añadir DTOs Pydantic v2 con `ConfigDict(extra="forbid")` donde corresponda: listado mínimo de Administradores, entradas/salidas de control, respuestas de alta/reenvío que contienen URL solo de forma inmediata, mutaciones tenant/control que incluyen motivo e identificador idempotente. El contrato del listado expone únicamente los cinco campos acordados; no incluir enlace ni consultar Clerk.
- `usuarios.py` conserva rutas ordinarias tenant y añade motivo al contrato de las mutaciones indicadas, más `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio` (200 `UsuarioInvitacionRespuesta`, 401/403/404/409/422/503). La ruta valida que usuario esté en tenant del Administrador y sea Bodeguero/Solicitante activo; la URL solo aparece en la respuesta inmediata. Para inactivo se exige reactivación motivada primero, en request separada. Superadmin recibe 403 antes de lectura en `/api/v1/usuarios/`. `control.py` conserva las cinco operaciones de gestión de Administradores D-10 y el dashboard, con response_model, status_code, errores de sesión/tenant 503 explícitos en OpenAPI. Los routers delegan reglas y persistencia a servicios.
- `permisos.py` actualiza explícitamente la matriz para retirar Superadmin de todas las lecturas de negocio de AC-15, preservando los permisos de los otros roles, y habilita las nuevas operaciones control solo a Superadmin. Añade la entrada `POST /api/v1/usuarios/{usuario_id}/invitacion/reenvio` exclusivamente para Administrador; las demás rutas ordinarias de `/usuarios/` siguen solo Administrador y las cinco rutas de gobierno D-10 solo Superadmin. Mantener gating de capacidades como dimensión separada, adicional a la matriz; no inventar capacidades nuevas.
- El dashboard técnico se implementa como `GET /api/v1/control/dashboard` y DTO de control. Enumerar instituciones desde control; clasificar: `operativo` si activa, enrutable y versión exacta; `no enrutable` si inactiva o resolución de metadatos/routing falla (no abrir tenant); `no disponible` si activa/resoluble pero tenant no responde o su versión falta/es ilegible/incompatible. Solo `operativo` expone conteos; agregar cantidades conocidos/no disponibles y evitar presentar un cero cuando los datos no están disponibles. Contabilizar Administradores activos/inactivos por separado y usuarios activos por rol no privilegiado, solo asociaciones locales activas; incluir sedes/departamentos por institución. No consultar tickets, catálogo, stock ni movimientos, y no exponer datos personales. Reutilizar sesiones de tenant derivadas en servidor y consultas tipadas ORM/Core; no SQL raw.
- Retirar acceso de Superadmin a `GET /dashboard/`, lecturas de tickets e inventario especificadas, tanto en backend/matriz como en `roles.ts`, guard, `app.routes.ts` y navegación. La identidad Superadmin mantiene el portal `/control` y gestión de Administradores, no rutas operativas.

### Frontend

- Extender `features/administracion/` existente: DTOs TS compartidos, servicios, listado local con estado de invitación persistido, formulario de alta con invitación, motivos para edición/estado y acción tenant de reenvío para Bodegueros/Solicitantes activos con copia de URL recibida solo en la respuesta actual; al navegar/recargar la URL desaparece. Para usuario inactivo mostrar primero reactivación motivada y luego reenvío como acción separada. Aceptada no ofrece reenvío. Mostrar `no disponible` para legado/desconocido y estado local por separado. No consultar Clerk desde navegador.
- Extender `features/control/` para panel técnico por institución y gestión de Administradores; el panel muestra clases/contadores conocidos frente a no disponibles, y los controles operan por ID institucional. El cliente no elige tenant/esquema. Ampliar mapeo de errores para 409/422/503 y reconciliación.
- Componentes Standalone con `inject()`, `signal()`/`computed()`, Tailwind y formularios accesibles; actualizar guards y rutas para que Superadmin no vea ni active dashboard/inventario/tickets. Mantener la navegación de los demás roles según la matriz vigente.

## 3. Decisiones técnicas justificadas

| Decisión | Elección y motivo | Alternativa descartada |
|---|---|---|
| D-2: confirmaciones y compensación | Dos commits locales ordenados: Clerk → tenant → control; compensar invitación si falla tenant; constancia con `invitacion_id` si revocación falla. Un fallo mapa tras tenant se recupera por retry. | Transacción distribuida/fingir atomicidad entre Clerk y PostgreSQL, técnicamente inexistente. |
| D-3: aceptar en primer login | `UPDATE` condicional solo si estado `pendiente` y mapa `activo`; el número de filas afectadas no es error. Mantener timestamps de transición y dejar asociación separada. | Leer Clerk en listado o guardar aceptación de forma no condicional; genera N+1, rate limits y carrera. |
| Correo | Función común de normalización `trim + lowercase` en alta, búsquedas locales/Clerk y correo verificado durante auth. No reescribir asociaciones por cambio posterior de correo. | Confiar en formato entrante o normalizar solo en UI, dejando duplicados por mayúsculas/espacios. |
| `ignore_existing` y conflicto Clerk | En alta primero determinar identidad/invitación existente; reusar estado cuando aplique. La respuesta “already invited” se interpreta como conflicto recuperable y no se inventa URL ni reemplaza ID. Reenvío intenta revocación propia y luego crea una nueva invitación; 409 no cambia referencia persistida. | Tratar cualquier 409 como éxito con un enlace desconocido o crear varias invitaciones. |
| Reenvío tenant y reactivación | `PATCH .../estado` con motivo reactiva vínculo local; en una llamada posterior, `POST /usuarios/{usuario_id}/invitacion/reenvio` rota Clerk y devuelve URL. El reenvío exige asociación activa y no cambia `activo`. | Hacer que PATCH de estado invoque Clerk/retorne enlace, o reenvío que reactive implícitamente: mezcla operaciones y no permite auditar el motivo separado. |
| Alta institucional parcialmente confirmada | Si esquema/tenant existen y control no tiene registro/mapa, validar restos y completar la etapa control sin recrear recursos ni volver a Clerk. | Ejecutar `CreateSchema` y aprovisionamiento desde cero: falla por esquema existente o duplica recursos. |
| Continuidad ante degradación de rol | Antes de confirmar un cambio de Administrador a rol no administrativo, comprobar que otro Administrador activo permanece; sin él, 409 sin edición/motivo. | Proteger solo PATCH estado, dejando evadir la regla por PUT de control. |
| Errores de tenant en control | Normalizar fallos de apertura/lectura/escritura de tenant en las cinco rutas D-10 y dashboard a 503 y documentarlo, sin ocultar 404/409/422 de dominio. | Propagar excepción de SQLAlchemy como 500 no documentado o colapsar errores funcionales a 503. |
| Reintento de alta sin mapa y registro asociado | Completar constancia/motivo de invitación junto con mapa al recuperar; requiere clave idempotente persistida que identifique el alta. Si no existe, 503 recuperable sin clave fabricada. | Crear una clave nueva y arriesgar dos registros para la misma operación o completar solo el mapa dejando AC-11 inconsistente. |
| Login Superadmin sin retorno | `resolverDestinoRetorno` conserva un retorno local válido; si no hay retorno válido, fallback `/control`. | Fallback `/dashboard`, que está denegado al Superadmin y produce acceso-denegado. |
| Tenant en rutas de control | Resolver institución en control y abrir con `crear_sesion_esquema(nombre_derivado_servidor)`. | Usar `get_db_negocio` del Superadmin (contexto global sin tenant), o aceptar esquema/institución tenant enviados por el cliente. |
| Dashboard técnico | Evaluar primero estado/routing; no abrir inactivas/no enrutables. Leer conteos solo para tenant con versión compatible; errores de lectura/versión son no disponibles, nunca cero. | Fallo total ante una institución no disponible (contradice D-8) o reportarla con métricas cero. |
| Motivo y persistencia | Validar conjunto cerrado de seis códigos y texto ≤500 (con `otro` no vacío) antes de la mutación; tabla auxiliar control con clave idempotente. Lectura diferida a 018. | Incluir bitácora paginada/endpoint lector en 017 o guardar motivos en entidad tenant. |
| Gating | Matriz define autorización por rol; capabilities ya existentes agregan un control independiente donde la operación tenga capacidad. Las operaciones SaaS control no se gatean por capacidades tenant. | Sustituir matriz por capabilities o agregar una séptima capacidad no aprobada. |
| Restricción de dependencias | HTTPX existente con transporte inyectable para Clerk. | `clerk-sdk-python` u otro paquete, innecesario y no analizado. |

## 4. Archivos previstos y responsabilidades

Las rutas se listan por responsabilidad para que cada tarea implemente un grupo acotado; cualquier ajuste exige respetar los AC y aprobación previa para cambios estructurales.

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` §2 | Justificar y aprobar columnas nuevas del mapa y tabla auxiliar de motivos/constancias antes de DDL/modelos. Tarea documental previa. | AC-18 |
| `database/01_esquema.sql`, `database/02_datos_semilla.sql` | Añadir columnas y tabla control; actualizar plantillas, guardia fail-closed, proyección de mapas y seed sin inventar tenant/migración. Recreate-only. | AC-1…AC-3, AC-7, AC-11, AC-18 |
| `backend/app/models/control.py`, `models/__init__.py` y modelo auxiliar de control | Mapear estado/timestamps de invitación y motivos/constancias sin exportarlos a tenants. | AC-1…AC-7, AC-11, AC-18 |
| `backend/app/core/security.py`, `core/config.py`, `api/dependencies.py` | API Clerk de invitación/revocación/búsqueda, normalización compartida, transporte inyectable, errores externos y settings existentes; sin SDK nuevo. | AC-1…AC-7 |
| `backend/app/schemas/usuario_schema.py`, `control_schema.py`, `auth_schema.py` | DTOs tenant/control, motivos, lista mínima, respuesta de invitación/link inmediato, métricas y estado de aceptación. Pydantic v2. | AC-1…AC-18 |
| `backend/app/services/usuario_service.py`, `control_service.py`, `organizacion_service.py`, `tenant_service.py`, `auth_service.py`, `ambito_service.py` | Orquestación invitación/reintentos incluido reenvío ordinario, recuperación de aprovisionamiento parcial, constancias, guarda ante degradación, fallos tenant y dashboard. | AC-1…AC-18 |
| `backend/app/api/v1/endpoints/usuarios.py`, `control.py`, `auth.py`, `dashboard.py` | Nueva ruta ordinaria de reenvío; contratos control explícitos, 503 documentado, sesión tenant derivada en servidor; auth marca aceptación; negocio Superadmin denegado. | AC-2…AC-18 |
| `backend/app/core/permisos.py` y `api/dependencies.py` | Matriz incluye reenvío tenant solo Administrador; D-10 solo Superadmin; denegaciones Superadmin de lecturas; fallos tenant traducidos/documentados como 503 en control/dashboard. Gating separado. | AC-8, AC-9, AC-15, AC-17 |
| `backend/tests/` (SQLite, transporte fake y PostgreSQL gated) | TDD HTTP/servicios; reenvío ordinario, recuperación alta institucional parcial, degradación último Admin, errores 503, idempotencia de constancia, carrera PG y OpenAPI/matriz. | AC-1…AC-18 |
| `frontend/src/app/shared/interfaces/`, `features/administracion/` y servicios | DTOs, motivos, alta/reenvío/link efímero tenant, estado persistido, reactivar→reenviar y lista local sin consultas externas. | AC-1…AC-12, AC-18 |
| `frontend/src/app/features/control/` | Dashboard técnico, gestión de Administradores por institución, métricas conocidas/no disponibles y errores. | AC-8, AC-13, AC-14, AC-18 |
| `frontend/src/app/core/auth/roles.ts`, guards, `app.routes.ts`, `features/auth/login.component.ts`, navegación y `features/dashboard/` | Login fallback a `/control` para Superadmin si no hay retorno local válido; ocultar y bloquear negocio, conservando retorno solicitado y roles restantes. | AC-15, AC-18 |
| Documentación de cierre | Evidencia AC se añade a `spec.md` y MEMORY/roadmap los gestiona coordinator; grep de coherencia en AGENTS/MEMORY/skills. No es cambio de requisito. | AC-18 |

## 5. Estrategia de pruebas

### Backend (`pytest`)

- **SQLite ordinario:** ejecutar `pytest`, TDD por interfaz de servicios/endpoints. Probar normalización, códigos/casos límite, DTOs, autorización, idempotencia y servicios de motivos con fallos de commit inyectados. Pruebas de Clerk usar `httpx.MockTransport`/`BaseTransport` fake o overrides de dependencias: crear invitación, identidad existente, invitación pendiente, 409/`ignore_existing`, 429/red/5xx, revocar, reenvío, no filtrar URL en listado y respuesta inmediata solamente.
- **Flujos de escritura:** cubrir orden validación → Clerk → tenant → control; compensación y constancia; retry de usuario tenant sin mapa sin invitar otra vez y completando constancia con clave idempotente existente; aprovisionamiento institucional con tenant/esquema/usuario ya creado y mapa/control ausente, recuperado sin recrear ni reinvitar; alta concurrente/correo duplicado; fallo mapa 503; mutación efectiva/idempotente, motivo válido/inválido, dos commits y reparación idempotente; baja último Administrador y degradación vía control sin mutar si deja cero activos.
- **Reenvío ordinario:** tests HTTP para método/DTO/status/OpenAPI y matriz Administrador-only; target propio Bodeguero/Solicitante activo, Superadmin/otros roles 403 y target ajeno 404; aceptada/inactiva/conflicto Clerk 409; conflicto conserva ID y URL solo respuesta. Probar reactivación motivada y reenvío como dos requests distintos.
- **Primer login:** autenticación resuelta con correo normalizado; transición condicional idempotente, estado terminal inmutable, asociación inactiva no reactivada. No provocar fallo de autenticación por dos escrituras simultáneas.
- **Contratos y permisos:** `/openapi.json` para método/ruta, response_model, status_code, security y respuestas 401/403/404/409/422/503 de D-10 y reenvío tenant. Comparar denegaciones Superadmin y conservar permisos restantes. Verificar 503 documentado ante fallos sesión/tenant en operaciones de control/dashboard.
- **PostgreSQL gated:** con `POSTGRES_TEST_URL`, usar bases temporales, nunca `apt_erp`; validar `01 → 02`, forma de control/tenant, columnas y tabla auxiliar solo control, constraints, lista/seed compatible, reintento de aprovisionamiento tras tenant commit y fallo control, unicidad, doble login, baja concurrente de dos administradores distintos (una operación 409, nunca cero Administradores activos), reintentos en dos sesiones, aislamiento por `schema_translate_map`, tenant no disponible/versión incompatible y dashboard. SQLite no sustituye estas pruebas.

### Frontend (`ng test`)

- Ejecutar `npx ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` apuntando a Edge según AGENTS §5. Servicios con `HttpTestingController`; verificar alta y reenvío tenant/control muestran URL solo en respuesta inmediata, copia, ausencia en listado/estado/dashboard, conflictos y anti doble envío.
- `UsuariosComponent` prueba acción reenvío solo para usuario activo, reactivación motivada y luego reenvío como operaciones distintas, sin exponer URL persistida. Login prueba Superadmin fallback `/control` y conserva retorno local válido; roles de negocio preservados y guards siguen denegando superficies Superadmin.
- Build de producción se valida como parte del rebuild de cierre (AGENTS §5); no agregar paquetes.

### Verificación del contrato y recorridos

- AC-17: extraer `/openapi.json` de app viva/TestClient y contrastar las cinco operaciones control y nueva ruta tenant con método/DTO/status/seguridad/roles/errores; confirmar 503 de sesión/tenant control/dashboard y comparación automatizada de operaciones AC-15.
- 4200: recorrido funcional de administrador local y Superadmin, persistiendo de verdad en PostgreSQL: invitación, aceptación en primer login, motivo, reenvío, listado sin URL, baja/409 último Admin, gestión control, dashboard técnico y rechazo de rutas de negocio.
- 8080: antes `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d frontend`; humo posterior verifica que el build servido es nuevo, control/usuarios visibles, rutas retiradas redirigen/deniegan y flujo básico de invitación/control responde.

## 6. Riesgos técnicos y mitigaciones

| Riesgo | Mitigación / evidencia |
|---|---|
| Clerk API cambia semántica/shape o rate limit 100/h | Acotar frontera HTTP, validar status/payload, no filtrar detalles sensibles; transporte fake prueba códigos y payloads relevantes; errores externos 503/409 recuperables. |
| URL o secreto se filtra en listado/log/motivo | DTO de lista allowlist de cinco campos; nunca persistir URL; tests de serialización y búsqueda; secretos solo configuración de backend. |
| Commit tenant/control parcial o invitación huérfana | Dos commits explícitos, compensación y constancia; retries idempotentes; gated PG sobre fallo de cada frontera. |
| Normalización diverge entre login y asociación | Compartir regla trim/minúsculas; pruebas de trim/case con Clerk y PostgreSQL; no reconciliar cambios posteriores de primary email. |
| Carrera por último Administrador | Bloqueo/serialización al contar y cambiar estado; prueba PG con transacciones concurrentes y aserción de al menos un activo. |
| Modelo/control DDL contaminan tenants | Separar modelos control-only/filtrado en metadata; test de `information_schema` contra todos los schemas. |
| Métricas indisponibles se presentan como cero | DTO expresa conocidos y no disponibles, taxonomía única; tests de tenant offline/version mismatch/inactivo; no consultar tenant si no enrutable. |
| Sesión del Superadmin se usa incorrectamente como tenant | `control_service` deriva mapa/esquema desde control y crea `crear_sesion_esquema`; test API multi-tenant gated. |
| Denegación UI sin denegación API, o matriz deja lectura | Pruebas directas API por operación y test automatizado de matriz/OpenAPI; guards solo reflejan UX. |
| Seed altera volumen con datos existentes | Mantener guardia fail-closed, reset destructivo documentado y prueba gated segunda semilla aborta sin cambios. |
| Producción 8080 sirve build anterior o rompe lazy routes | Rebuild obligatorio y smoke HTTP en puerto 8080, además de recorrido funcional 4200. |

## 7. Cobertura spec → plan

| AC | Partes/tareas previstas |
|---|---|
| AC-1…AC-3 | Frontera Clerk, persistencia y alta/compensación/reintento, incluido primer Admin y retry de tenant confirmado/control fallido; T2–T6, tareas correctivas y gated PG. |
| AC-4 | Auth/service escritura condicional; T5–T6 y PostgreSQL gated T7. |
| AC-5…AC-7 | DTOs/listados, reenvío de control/tenant, reactivación separada, normalización/concurrencia y presentación; T3–T6, T8–T9 y corrección tenant. |
| AC-8…AC-9 | Cinco rutas control y ruta ordinaria reenvío Administrador-only; T3–T6 y corrección tenant. |
| AC-10…AC-12 | Motivos, idempotencia y último Administrador; T3–T6 y T7. |
| AC-13…AC-14 | Taxonomía dashboard técnico y métricas; T6 y T7, UI T9. |
| AC-15 | Matriz/backend y rutas/navegación frontend; T6, T8–T9 y corrección de login Superadmin. |
| AC-16 | Carreras de primer login; T5–T7. |
| AC-17 | Contrato OpenAPI y transcripción de matriz; T6–T7 y bloque de cierre. |
| AC-18 | DDL/instalación limpia, pruebas UI, aprobación stack y evidencia final; T1–T3, T7–T10. |

## 8. Estimación de esfuerzo

Estimación orientativa para implementación (no condiciona criterios ni reduce pruebas): backend identidad/servicios/API **8–11 días-persona**; frontend **4–6 días-persona**; DDL/seed y pruebas PostgreSQL gated **2–3 días-persona**; integración, OpenAPI, recorridos, evidencia/documentación **2–3 días-persona**. Total aproximado **16–23 días-persona**. La coordinación puede recalibrar al conocer resultados de pruebas, sin dividir o recortar requisitos tácitamente.

## 9. Bloqueo de ejecución

No tocar modelos, DDL o semilla hasta la aprobación explícita de §1 en `stack.md`. El cambio de esquema se materializa solo en instalación limpia reconstruyendo el volumen QA con el procedimiento vigente; no se crean migraciones. Si una operación externa de Clerk no permite distinguir los estados requeridos por la spec o si la estructura actual no puede representar dos confirmaciones/reintentos sin violar AC, detener la tarea y elevar la pregunta al coordinator; no alterar el contrato por inferencia.
