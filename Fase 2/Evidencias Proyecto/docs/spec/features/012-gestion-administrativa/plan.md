# Feature 012 — Plan técnico

Spec: [`spec.md`](spec.md). La spec está aprobada por el usuario; este plan concreta su implementación sin alterar alcance. No se añaden dependencias.

## 1. Prerrequisito bloqueante: justificación en `stack.md`

Antes de modificar modelos, DDL, migraciones o routing, el usuario/coordinador debe incorporar y aprobar el siguiente texto en `docs/spec/stack.md`. T1 registra esta propuesta y queda bloqueada hasta aprobación explícita. El planner no edita `stack.md` en esta fase.

> #### Gestión del ciclo de vida institucional y capacidades funcionales (Feature 012)
>
> La Feature 012 agrega `control.institucion.activo` como estado de ciclo de vida del registro institucional canónico. La fila de control es la fuente de verdad; `mapa_usuario_esquema.activo` conserva exclusivamente el significado de asociación local correo-esquema y no se reutiliza para suspender una institución. La resolución de identidad consulta `control.institucion.activo` antes de comprobar versión o seleccionar el tenant: una institución inactiva no resuelve a su esquema y las operaciones de negocio de sus identidades locales deniegan con 401. Reactivar restaura el routing solo si el tenant ya cumple la versión objetivo. La desactivación no borra la institución, el tenant, sus mapas, datos ni historial.
>
> La Feature 012 incorpora además `funcion_institucion`, estructura auxiliar únicamente en `control`, con una fila por pareja `(institucion_id, funcion)`, FK local a la institución, estado `habilitada` explícito y unicidad de la pareja. No es entidad de dominio, permiso de usuario, capacidad de rol ni catálogo configurable. El conjunto cerrado de identificadores es `catalogo`, `inventario`, `tickets`, `kanban`, `dashboard` y `gestion_organizacional`; no se crea una tabla de catálogo ni se infiere disponibilidad a partir de roles o datos existentes. Las capacidades deshabilitadas se aplican como gating backend 403 adicional a la matriz central, que permanece como autoridad independiente de rol. La fila de capacidad no concede permisos ni elimina información al deshabilitar.
>
> En instalaciones nuevas, `database/01_esquema.sql`, `database/02_datos_semilla.sql` cuando corresponda y `database/03_construir_tenants_011.sql` (o su constructor vigente) deben crear el atributo/auxiliar solo en control y aprovisionar para cada institución las seis capacidades inicialmente habilitadas. En instalaciones existentes, una migración operacional idempotente bajo `database/migraciones/` añade `activo` con valor inicial compatible, crea las seis filas habilitadas por institución y eleva la versión de control/tenants conforme al procedimiento aprobado, sin semilla destructiva ni pérdida de datos. El espejo tenant de `institucion` permanece limitado a `institucion_id` y `nombre`; `activo` y `funcion_institucion` nunca se copian al tenant.
>
> **Por qué:** el estado canónico permite suspender y reactivar una institución en el punto global que precede al routing, sin confundir institución con asociación individual. La tabla auxiliar hace persistente y auditable la disponibilidad de las seis funciones por tenant, separándola de autorización por rol y del modelo de negocio. Ambos cambios se justifican como ampliación del esquema de control y estructuras auxiliares, no como nuevas entidades de dominio tenant; deben existir en el DDL, modelo, aprovisionamiento, migración y routing antes de habilitar su uso.

**Alternativa descartada:** alterar `mapa_usuario_esquema.activo`, copiar banderas al espejo tenant o inferir capacidades dinámicamente. Esas opciones mezclan ciclos de vida o duplican autoridad y no satisfacen el modelo aprobado de control como única fuente de verdad.

## 2. Enfoque técnico por capa

### DDL, persistencia y migración

- Añadir `activo BOOLEAN NOT NULL DEFAULT TRUE` a `control.institucion` únicamente. El `Institucion` ORM es compartido por el contexto lógico y los esquemas tenant, por lo que el atributo debe ser nullable/ignorado en lectura tenant según el diseño ORM, o mapearse en un modelo de control separado si SQLAlchemy exige columna presente en cada esquema. **Resolverlo en T2 inspeccionando metadatos y constructor**: la spec exige control-only y espejo tenant con dos campos; no se puede añadir silenciosamente `activo` a los tenants. Preferencia técnica: modelo explícito de control para institución canónica y mantener el modelo tenant reflejando la tabla espejo, si es necesario para evitar que `Base.metadata.create_all()` imponga la columna en todos los tenants.
- Crear modelo auxiliar `FuncionInstitucion` en `control`, clave primaria compuesta `(institucion_id, funcion)`, `habilitada BOOLEAN NOT NULL`, FK local a `control.institucion` y `CHECK` o validación equivalente para los seis literales. La aplicación valida el conjunto cerrado y no permite CRUD de catálogo de capacidades.
- Actualizar `database/01_esquema.sql`: añadir `control.institucion.activo` y `control.funcion_institucion`; mantener intacta la fila tenant `institucion` con solo `institucion_id` y `nombre`.
- Actualizar `database/02_datos_semilla.sql` solo si el mecanismo de seed requiere filas explícitas: preservar su guardia fail-closed antes del `TRUNCATE` y generar exactamente seis capacidades habilitadas para cada institución de prueba. No crear tablas/capacidades por separado del DDL canónico.
- Actualizar `database/03_construir_tenants_011.sql` (constructor actual de instalaciones limpias) para usar control con `activo` y sembrar capacidades por institución sin agregarlas a la plantilla tenant. Conservar orden initdb y constructor después de seed.
- Añadir migración operacional idempotente en `database/migraciones/003_migracion_gestion_administrativa_012.sql` siguiendo la ubicación y ejecución explícita de 001/002, fuera del montaje initdb. La migración debe verificar estado/versiones preexistentes, añadir `activo` a control sin cambiar el espejo, crear tabla auxiliar, poblar seis funciones habilitadas por cada institución, y actualizar `version_esquema` a `012.1` únicamente al terminar validaciones. Es transaccional, no destructiva y no ejecuta `02_`.
- Cambiar `VERSION_ESQUEMA_OBJETIVO` de `011.1` a `012.1`. El control y cada tenant deben portar versión compatible; la versión se escribe al final del cambio validado. No usar `search_path` para elegir tenants.
- Integrar los modelos en `backend/app/models/__init__.py` y metadata, pero evitar generar la estructura de control en tenants por `create_all` indiscriminado. El patrón actual de `control_service._provisionar_tenant_postgres` deriva tablas desde `Base.metadata` excluyendo solo `MapaUsuarioEsquema`; debe excluir también los nuevos modelos exclusivamente de control.

**Alternativa descartada:** introducir `activo` en la tabla espejo del tenant o `funcion_institucion` en cada tenant. D-1/D-2/D-6 establecen control como fuente única y espejo limitado; replicar estado permitiría divergencias y violaría la spec.

### Resolución de tenant y gating de capacidades

- Extender `tenant_service.resolver_tenant_por_correo` para leer el mapa activo y luego consultar `Institucion.activo` en la sesión de control; si la institución está inactiva, levantar el error de resolución antes de abrir o validar la sesión tenant. `resolver_contexto_solicitud` debe preservar al Superadmin en control y aplicar el estado solamente a identidades locales tenant. Normalizar una institución inactiva a identidad no resoluble **401**, incluso con token Clerk válido previamente.
- Componer el gating con `requiere_operacion`, sin cambiar `MATRIZ_PERMISOS`: el endpoint pasa primero por autenticación/rol de la operación existente y luego por una dependencia adicional que consulta la capacidad asociada usando el contexto tenant resuelto. Denegar 403 si el rol carece de permiso o la capacidad está apagada. No convertir capacidad en rol ni condicionar permisos en la matriz. Para rutas organizacionales nuevas y existentes, la administración institucional se asocia con `gestion_organizacional`; sus seis operaciones de la 011 conservan contrato y roles, aunque el backend aplica gating adicional.
- Centralizar el mapeo operación-capacidad en backend (dependencia/configuración explícita, no una lista duplicada en routers). Asociaciones previstas: rutas de catálogo → `catalogo`; inventario/movimientos → `inventario`; `/tickets/` creación/consulta → `tickets`; operaciones Kanban estado/despacho → `kanban`; dashboard tenant → `dashboard`; `/organizacion/*` y CRUD administrativo → `gestion_organizacional`. `GET /auth/me`, `/control/*` y operaciones Superadmin SaaS no quedan gated por capacidades tenant.
- La administración de instituciones y capacidades se ejecuta con sesiones de control. Dashboard global recorre instituciones: activas con lectura tenant en transacción global consistente, inactivas como filas identificadas sin métricas actuales; una activa inaccesible/version incompatible hace fallar todo el agregado. Las capacidades se consultan en control y se inicializan al aprovisionar tenant.
- La actualización del registro canónico aplica a la fila `control.institucion` y sincroniza en tenant solo `institucion_id` y `nombre`. La escritura de espejo no copiará ni rechazará por otros atributos existentes exclusivamente en control. Desactivación/reactivación no elimina ni altera mapas, esquema o historial.

**Alternativas descartadas:** cambiar la matriz para representar capacidad, porque mezcla rol con disponibilidad; aplicar solo guard Angular, porque la API directa la eludiría; consultar versión antes que `activo`, porque la institución suspendida no debe enrutar ni revelar detalles de estado tenant.

### API, servicios y permisos

- Mantener `backend/app/api/v1/endpoints/control.py` como router delgado `/control`; ampliar contrato de aprovisionamiento existente y agregar operaciones para consultar/editar instituciones, métricas SaaS y capacidades. Definir `response_model`, `status_code`, 401/403/404/409/422/503 explícitos y documentación OpenAPI. Los identificadores de rutas/contratos se fijan contra la spec y la matriz en T2 antes de implementar.
- Crear/expandir DTOs Pydantic v2 en `control_schema.py` u otro schema de control: alta/edición/estado institución, dashboard con institución atribuida, lista/actualización de capacidad; `extra="forbid"` para no aceptar esquema/tenant/rol/estado de capacidad fuera de contrato. La respuesta institucional incluye estado persistido y sus atributos canónicos; la salida de capacidades usa exactamente los seis IDs cerrados.
- Extender `control_service.py` o separar servicios de control SaaS si crece su responsabilidad: aprovisionamiento, CRUD lógico, sincronización control/espejo, capacidades y agregación. Las reglas de conflicto y transacciones quedan en services, nunca en endpoint.
- Extender el servicio organizacional existente para CRUD de sedes/departamentos/usuarios y estado lógico, reusando las reglas de 011 (asignación de sede, ámbito por tenant, encargados), `ambito_service`, ocultación 404 y conflictos 409 cuando existan dependencias incompatibles. Los servicios transaccionan mutaciones y rechazan estados futuros incoherentes.
- Las identidades locales se validan contra Clerk con la costura `obtener_verificador_correo_clerk` ya existente; la feature no crea ni modifica Clerk. Al activar/desactivar usuario, mantener coherente su fila de tenant y `mapa_usuario_esquema.activo` para el correo. No tocar el ciclo de identidad Clerk.
- La matriz actual contiene **28 operaciones tras Feature 011**. Añadir solo rutas administrativas nuevas y declararlas explícitamente: operaciones Superadmin limitadas al control (CRUD/consulta de institución, dashboard SaaS, lectura/actualización de capacidades) y operaciones Admin institucional para CRUD organizacional. No modificar ni reescribir los permisos de las 28 entradas existentes; particularmente, Superadmin conserva las denegaciones vigentes de escritura de negocio. Las 6 operaciones organizacionales 011 existentes no se duplican.
- El contrato de API existente de CRUD organizacional de 011 se extiende sin reinterpretar reglas ya especificadas; nuevas rutas deben usar `get_db_negocio` para objetos tenant y `get_db`/contexto control para operaciones SaaS.

**Alternativa descartada:** concentrar consulta/SQL y validación en routers o reutilizar el endpoint de alta para mutaciones genéricas; se pierde separación de capas y autorización explícita por operación.

### Frontend Angular

- Extender `frontend/src/app/features/control/` con dashboard global, listado/detalle/formulario de institución y pantalla de capacidades. Mantener rutas lazy-loaded y `ControlSuperadminGuard`; el portal de control no monta layout operativo tenant ni permite escoger esquema.
- Ampliar `ControlService` para contratos de control, consumiendo tipos 1:1 desde `shared/interfaces/index.ts`. Componentes standalone con `inject()`, `signal()` para estado de carga/formulario/error y `computed()` para métricas derivadas solo de datos entregados por API; Tailwind en templates, nombres de dominio en español.
- Añadir área administrativa dentro de `features/administracion/` con vistas para sedes, departamentos, usuarios y encargados, y servicios Angular que reusen las rutas organizacionales existentes de 011 y las nuevas operaciones de CRUD. Formularios limitan las sedes/departamentos/usuarios a los datos devueltos del tenant; no envían esquema ni institución como autoridad.
- Implementar ocultación y guard de `/tickets` para Superadmin exclusivamente en navegación/UI. Una nueva lista de roles de ruta excluye Superadmin y lo conserva para Administrador/Bodeguero/Solicitante que ya estaban autorizados. No editar `MATRIZ_PERMISOS` para esta exclusión. La navegación deja de mostrar `/tickets` para Superadmin y mantiene `/control`.
- Agregar lectura de capacidades a la presentación/navegación (preferiblemente identidad/configuración de capacidades obtenida del endpoint control/tenant correspondiente); capacidad deshabilitada oculta disponibilidad visual, pero los 403 backend siguen siendo autoridad. No inferir disponibilidad por rol ni replicar la matriz del servidor.

**Alternativa descartada:** formularios monolíticos en la vista existente o confiar en botones ocultos; las vistas por dominio mantienen responsabilidades y la autorización real sigue en backend.

## 3. Archivos previstos y responsabilidades

Los grupos de archivos se ajustan en cada tarea tras inspeccionar el árbol real, sin alterar el alcance.

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Incorporar y aprobar el texto formal de los cambios de modelo control-only. Bloqueante de DDL/modelos. | AC-1, AC-2, AC-5, AC-13 |
| `database/01_esquema.sql` | `control.institucion.activo`, `control.funcion_institucion`; espejo tenant limitado a `institucion_id`+`nombre`. | AC-1, AC-2, AC-5, AC-13 |
| `database/02_datos_semilla.sql` | Capacidades iniciales explícitas si corresponde, guardia fail-closed y sin alterar semilla destructiva. | AC-5, AC-13 |
| `database/03_construir_tenants_011.sql` o constructor vigente | Propagar las estructuras/filas de control para instalación nueva, no copiar extras al tenant. | AC-1, AC-2, AC-5, AC-13 |
| `database/migraciones/003_migracion_gestion_administrativa_012.sql` | Migración operacional explícita, idempotente, no destructiva, transición a `012.1`. | AC-1, AC-2, AC-5, AC-13, AC-14 |
| `backend/app/models/control.py` o modelo control dedicado, `models/__init__.py`, `models/institucion.py` | Mapear activo canónico y tabla auxiliar, registrar metadata y separar modelo del espejo tenant si hace falta. | AC-1, AC-2, AC-5 |
| `backend/app/core/config.py`, `backend/app/services/control_service.py`, `tenant_service.py`, `global_service.py` | Versión `012.1`, estado activo previo al routing, capacidades, aprovisionamiento, CRUD/sincronización y dashboard global. | AC-1…AC-5, AC-13 |
| `backend/app/api/dependencies.py`, `backend/app/core/permisos.py` | Componer gating adicional, declarar nuevas operaciones administrativas; conservar intactas las entradas existentes. | AC-1…AC-5, AC-13 |
| `backend/app/schemas/control_schema.py`, schemas organizacionales nuevos | DTOs de institución, capacidades, métricas SaaS y CRUD organizacional; entradas estrictas. | AC-1…AC-13 |
| `backend/app/services/organizacion_service.py` y servicios de control | Lógica CRUD, aislamiento, dependencias, 404/409, Clerk existente, espejo y control de capacidades. | AC-1…AC-13 |
| `backend/app/api/v1/endpoints/control.py`, `organizacion.py`, `api.py` | Rutas delgadas, respuestas explícitas, operación de matriz, capacidades y OpenAPI. | AC-1…AC-13 |
| `backend/tests/` | Tests SQLite de reglas/contratos y PostgreSQL gated de schemas, migración, routing, gating y aislamiento. | AC-1…AC-5, AC-11…AC-14 |
| `frontend/src/app/features/control/`, `app.routes.ts` | Dashboard SaaS, CRUD institución, funciones por tenant, servicios, rutas y guard existentes. | AC-1…AC-5 |
| `frontend/src/app/features/administracion/` | Vistas de sedes/departamentos/usuarios/encargados y servicios administrativos. | AC-6…AC-12 |
| `frontend/src/app/core/auth/roles.ts`, `core/guards/`, `app.component.ts/html` | Excluir Superadmin de navegación/guard `/tickets`; acceso a control y navegación administrativa. | AC-3 |
| `frontend/src/app/shared/interfaces/index.ts` y specs Angular | Tipos espejo de DTOs y pruebas de renderizado/estados/rutas/403 y capacidades. | AC-3…AC-12 |
| `docs/spec/features/012-gestion-administrativa/spec.md`, `tasks.md`, `MEMORY.md`, `docs/spec/roadmap.md` | Registrar evidencia por AC y cierre solo tras verificaciones AGENTS §8.5–§8.7. | AC-14 |

## 4. Estrategia de pruebas

### Backend SQLite (`pytest` ordinario)

- TDD sobre interfaz pública: pruebas primero para CRUD/control, permisos, 401/403/404/409/422, exclusión de espejo y DTO/OpenAPI; luego implementación.
- Comprobar con fixtures que control distingue activo institucional de activo del mapa, seis capacidades persisten por par, IDs inválidos no se aceptan y deshabilitar no elimina datos.
- Pruebas de dependencia para la composición rol + capacidad: rol sin permiso 403; rol autorizado con capacidad apagada 403 sin mutación; capacidad activa devuelve comportamiento normal; endpoints no asociados a capacidad no se bloquean.
- Pruebas de routing: institución inactiva produce 401 para asociación tenant incluso con token previamente válido, sin consulta de versión ni fallback; reactivación restablece acceso solo con versión objetivo.
- CRUD tenant verifica 404 indistinguible para ID inexistente/ajeno, 409 por dependencias incompatibles, estado lógico y reglas 011; la costura de verificación Clerk se simula, sin red real.
- Verificar `/openapi.json`: response_model, status y errores por operación, seguridad y matriz con solo operaciones nuevas añadidas; aserción de no cambio de las entradas de matriz de 011.

### PostgreSQL gated (`POSTGRES_TEST_URL`)

- Obligatorio para cierre; verificar `control.institucion.activo` y `funcion_institucion` solo en control, PK/FK/checks, seis capacidades únicas por institución, y ausencia de esas capacidades en espejo/tenant.
- Probar migración en snapshot PostgreSQL 16 de una instalación 011.1: IDs/datos/tenant maps intactos, capacidades habilitadas inicialmente, reejecución sin cambios y fallo preflight/transacción sin marcar versión parcial.
- Constructor/initdb temporal: `01 → 02 → 03`, tenant generado con espejo exacto de dos campos, control con activo/capacidades y `version_esquema=012.1`; semilla existente debe abortar antes de truncado según guardia.
- Alternar usuarios activos/inactivos e instituciones activa/inactiva sobre conexiones reusadas; verificar que routing deniega antes de sesión negocio y no filtra tenant.
- Probar gating con llamadas directas HTTP por cada grupo de capacidad, asegurando 403 y estado sin mutación; al habilitar, solo roles permitidos por matriz acceden. Incluir `/tickets` y `/organizacion/*` y capacidad de catálogo/inventario/dashboard.
- Probar dashboard SaaS con homónimos, institución inactiva y activa incompatible: atribución inequívoca, inactiva sin métricas actuales, y fallo completo/no parcial por activa inaccesible. Verificar consistencia temporal con el patrón `global_service.lectura_global` de REPEATABLE READ.

### Frontend

- `ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` apuntando a Edge conforme AGENTS §5. Tests de renderizado/estado para vistas control (AC-4/5) y administración (AC-6…10), errores y estado inactivo (AC-11); tests de navegación `/tickets` para Superadmin denegado y roles de negocio permitidos (AC-3).
- Probar formularios/servicios con DTOs contractuales, sin tenant introducido por cliente; el gating visual no sustituye tests API 403.
- Ejecutar `ng build` de producción. No instalar paquetes.

### Riesgos y recorridos

| Riesgo | Verificación / mitigación |
|---|---|
| ORM compartido añade `activo` al espejo tenant | Resolver durante diseño de modelo; test PostgreSQL compara columnas exactas y espejo `institucion_id`+`nombre`; separar modelo canónico/control si el metadata común lo requiere. |
| Migración o constructor crea capacidades duplicadas o estado parcial | PK de par, transacción/checkpoint, tests gated de segunda ejecución, falla inyectada y comparación de filas/versiones. |
| Institución inactiva se enruta por consultar solo el mapa | Test directo `tenant_service` y API con Clerk válido; exigir lookup canónico en control antes de tenant/version. |
| Gating confundido con rol o no aplicado a API directa | Tests de matriz sin modificaciones, HTTP por capacidad deshabilitada, 403 sin mutación y rol autorizado tras habilitación. |
| Agregado global oculta tenant activo fallido o incluye métricas de inactivos | PostgreSQL gated con homónimos, estado inactivo y versión inaccesible; resultado completo o error, nunca parcial. |
| CRUD deja referencias activas inconsistentes | Tests de dependencias organizacionales y 409 en servicio; no borrar historial. |
| UI de 8080 no corresponde al código actual | Rebuild obligatorio y humo posterior; 4200 es el recorrido funcional con escritura real. |

Para cierre, ejecutar `pytest` ordinario, suite gated PostgreSQL con `POSTGRES_TEST_URL`, `ng test`, `ng build`, inspección de `/openapi.json`, recorrido real en 4200 contra PostgreSQL (CRUD institucional/organizacional, suspender/reactivar, capacidades y gating), y `docker compose -f docker-compose.yml build frontend` + `up -d frontend` antes del recorrido de humo en 8080. Registrar únicamente evidencia observada en los AC; ejecutar grep de coherencia en `AGENTS.md`, `MEMORY.md` y `.agents/skills/`, actualizar `MEMORY.md` y marcar roadmap solo al completar AGENTS §8.5–§8.7.

## 5. Cobertura spec → plan

| AC | Partes y tarea prevista |
|---|---|
| AC-1 | Control CRUD, espejo limitado y DDL/migración: T1, T3, T5, T7, T10. |
| AC-2 | Activo canónico, routing y migración: T1, T3, T4, T5, T10. |
| AC-3 | Navegación/guard `/tickets` Superadmin y regresión roles negocio: T8, T9, T12. |
| AC-4 | Dashboard SaaS atribuido y fallo completo: T5, T6, T7, T10. |
| AC-5 | Seis capacidades y gating backend/UI: T1, T3, T4, T5, T6, T7, T8, T10. |
| AC-6 | UI sedes y reuso API/reglas 011: T7, T8, T9. |
| AC-7 | UI departamentos/sede: T7, T8, T9. |
| AC-8 | UI usuarios Clerk local: T7, T8, T9. |
| AC-9 | Bodeguero y sede: T7, T8, T9, T10. |
| AC-10 | UI y asociaciones encargados: T7, T8, T9. |
| AC-11 | Desactivación lógica/409 por dependencias y UI: T5, T7, T8, T9, T10. |
| AC-12 | Aislamiento tenant por servicios/migración y pruebas gated: T4, T7, T8, T10. |
| AC-13 | Matriz, OpenAPI, contratos y errores: T2, T6, T7, T10. |
| AC-14 | Suites, build, recorridos y evidencia: T10–T13. |

## 6. Condición de bloqueo

No iniciar cambios en `models`, `database`, routing o versiones hasta que el texto de la sección 1 esté incorporado y aprobado en `stack.md`. Si la inspección demuestra que la spec aprobada no puede satisfacerse —en especial modelo canónico de institución vs espejo tenant de dos columnas, o la definición de rutas/capacidades sin operación correspondiente— detener la tarea y elevar hallazgo; no ampliar la spec ni corregir el código de forma implícita.

## Enmienda T-17 (presentación): pestañas ARIA en administración — 22/Oct/2026

Esta enmienda posterior al cierre aplica AC-15…AC-19 de `spec.md` §6. Cambia solo la navegación y asociación accesible del panel administrativo. Las cuatro rutas hijas, sus guards, navegación por URL/deep links y el estado cerrado de la Feature 012 no se reabren. `administracion.routes.ts`, backend, servicios, contratos, matriz, datos y dependencias quedan fuera de la modificación.

### Decisiones técnicas

1. **Ruta activa derivada del Router, no de estado local.** Inyectar `Router` en `AdministracionNavComponent` y obtener el índice activo comparando `router.url` (sin query/fragmento) con cada ruta completa de `enlaces`, usando coincidencia exacta o prefijo seguido de `/`. Las rutas actuales son terminales; el prefijo delimitado conserva la semántica `routerLinkActive` no exacta para posibles segmentos anidados y evita falsos positivos entre rutas. La misma resolución determina `aria-selected`, `tabindex` y el `aria-labelledby` del panel. Se descarta mantener un signal que se actualice solo al hacer clic: no reflejaría deep links, navegación atrás/adelante ni cambios disparados desde fuera del componente. También se descarta consultar `ActivatedRoute` relativo, pues la barra necesita comparar las cuatro rutas hermanas completas.
2. **Enlaces auténticos y navegación con flechas.** Mantener cada `<a [routerLink]>` y la carga de navegación por clic. En `keydown`, atender únicamente `ArrowRight` y `ArrowLeft`, calcular el índice circular en el orden actual `enlaces` mediante módulo, ejecutar `preventDefault()` solo para esas teclas, enfocar el enlace de destino y dejar que su `routerLink` active la ruta. La activación/cambio de foco sigue el modelo de activación automática de tabs; no convertir los enlaces en botones ni interceptar clic central, menú contextual, Ctrl/Cmd+clic o apertura en pestaña nueva. Se descarta invocar `navigateByUrl` de forma independiente porque rompería la semántica nativa del enlace.
3. **Estado roving y focos estables.** En la lista, el enlace cuya ruta coincide tiene `aria-selected="true"` y `tabindex="0"`; los otros, `false` y `-1`. Mantener `id` estables por ruta: `pestana-administracion-sedes`, `pestana-administracion-departamentos`, `pestana-administracion-usuarios` y `pestana-administracion-encargados`. El panel único que envuelve el `<router-outlet>` lleva `role="tabpanel"`, `id="panel-administracion"` y `aria-labelledby` dirigido al ID activo. La ruta por defecto ya redirige a `sedes`, así que el estado inicial será resoluble; ante URL transitoria sin coincidencia se usa como fallback `sedes` sin modificar ni emitir navegación.
4. **Replicar patrón, no extraer componente compartido.** Replicar en el componente administrativo el pequeño patrón ARIA de inventario, adaptándolo a rutas. Inventario usa señales locales y botones porque intercambia paneles dentro de una vista; aquí la fuente de verdad debe seguir siendo el Router y enlaces reales. Extraer un componente común añadiría abstracción/configuración de callbacks de navegación y arriesgaría el componente/inventario ya cerrado y validado, sin que exista evidencia de un tercer consumidor. No modificar el inventario ni introducir helper compartido; encapsular la resolución de ruta/índice y el manejador de teclado en `AdministracionNavComponent`.
5. **Estilo coherente con inventario y Tailwind.** Tablist con `aria-label="Secciones de administración institucional"`, borde inferior gris y flex de pestañas. Enlaces con borde inferior de 2 px, `border-blue-600` + `text-blue-700` para activo y `border-transparent` + `text-slate-600` para inactivo; `hover:text-blue-700`, transición y foco visible `focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2`. Mantener únicamente clases Tailwind; no añadir CSS ni estilos inline. La presentación se alinea a inventario y sustituye el resaltado de bloque oscuro actual.

### Archivos previstos para la enmienda

| Archivo | Responsabilidad | AC |
|---|---|---|
| `frontend/src/app/features/administracion/administracion-nav.component.ts` | Resolver ruta/índice activo desde `Router.url`; conservar `enlaces`; exponer atributos/IDs estables y manejar flechas circulares con foco sobre el enlace real. | AC-15, AC-16, AC-18 |
| `frontend/src/app/features/administracion/administracion-nav.component.html` | Declarar tablist y cuatro enlaces-tab con ARIA, selección y tabindex de ruta; aplicar clases Tailwind alineadas a inventario y foco visible. | AC-15, AC-16 |
| `frontend/src/app/features/administracion/administracion.component.html` | Contener el `router-outlet` existente en el panel `tabpanel` y relacionarlo por `aria-labelledby` con la pestaña de la ruta actual, sin alterar contenido ni navegación. | AC-17, AC-18 |
| `frontend/src/app/features/administracion/administracion-nav.component.spec.ts` (nuevo) | Tests de integración de la navegación: las cuatro URLs, selección/atributos ARIA, foco/tabindex, flechas y wraparound; comprobar que los anchors mantienen `href` y el destino de ruta. | AC-15, AC-16, AC-18, AC-19 |
| `frontend/src/app/features/administracion/administracion.component.spec.ts` (nuevo, solo si el fixture aislado del layout resulta necesario) | Verificar relación `tabpanel` ↔ `aria-labelledby` para las cuatro rutas sin alterar las rutas hijas. Preferencia: cubrir este contrato en el test de navegación con el layout real y omitir este archivo redundante. | AC-17, AC-18, AC-19 |
| `frontend/src/app/features/administracion/{sedes,departamentos,usuarios,encargados}.component.spec.ts` (sin cambios previstos; solo adaptar una expectativa si se demuestra afectada) | Regresión de vistas. La inspección confirmó que prueban componentes aislados y no asertan el `<nav>` actual. | AC-18, AC-19 |
| `frontend/src/app/features/administracion/administracion.routes.spec.ts` (sin cambios previstos) | Regresión de destinos; no hay aserciones de markup nav y las rutas no se modifican. | AC-18, AC-19 |

No se modifican `administracion.routes.ts`, `administracion.routes.spec.ts`, vistas hijas, `app.component.spec.ts` (solo cubre enlace global a `/administracion`), `inventario.component.*`, backend ni otros contratos. El test nuevo de navegación cubre tanto nav como panel con el layout real; solo si el harness no lo permite se justifica y añade un spec de layout separado.

### Orden TDD y estrategia de pruebas

1. Añadir primero pruebas rojas del componente de navegación y layout: iniciar cada URL hija y comprobar `role=tablist`, cuatro `role=tab`, exactamente una selección y tab stop, ID activo estable y `tabpanel` con `aria-labelledby` correcto. Verificar que cada tab sigue siendo `<a>` con destino `href`.
2. Añadir casos rojos de `ArrowRight`/`ArrowLeft`, wraparound en los dos extremos, `preventDefault` en las flechas soportadas, foco DOM en el enlace destino y actualización coherente tras cambio real de ruta. No prevenir comportamiento para otras teclas.
3. Implementar Router-based active route y atributos ARIA/IDs; añadir `keydown` con recorrido circular y foco, conservando `RouterLink`. Ejecutar los tests nuevos y toda la suite frontend; adaptar solo expectativas efectivamente rotas por el marcado.
4. Ejecutar `npx ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` configurado a Edge (no `npm test`) y `npx ng build`. Confirmar explícitamente `administracion.routes.ts` y `administracion.routes.spec.ts` sin cambios, las cuatro vistas existentes verdes y ausencia de cambios backend/contratos/dependencias.
5. Recorrer visual y con teclado las cuatro secciones en 4200; reconstruir frontend y hacer el humo 8080 descritos en tasks.md antes de marcar la enmienda terminada. Registrar evidencia observada, no anticipada.

### Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Cambiar el `<nav>`/clases/semántica rompe aserciones existentes o reduce cobertura de vistas. | Buscar aserciones de marcado existentes, añadir tests del componente nav dedicado y correr la suite Angular completa; no alterar los tests de las cuatro vistas salvo expectativa dependiente de marcado probada. |
| La ruta activa se calcula mal en deep links, navegación back/forward o ante coincidencias de prefijo. | Derivarla siempre de `Router.url`, limpiar query/fragmento y exigir coincidencia de segmento (`ruta` o `ruta + '/'`); probar cada destino y navegar realmente con `provideRouter`/harness. Mantener `administracion.routes.ts` intacto. |
| La flecha cambia estado/foco sin activar la ruta, o pierde el foco por el rerender. | Usar anchors existentes; enfocar el ID estable destino y dejar que su RouterLink procese click/activación; probar navegación y foco con Router real y wraparound en ambos sentidos. |
| `aria-labelledby` apunta a pestaña inexistente/incorrecta al cargar deep link o redirigir la raíz. | Compartir la única resolución de índice activo entre nav y panel (host/layout recibe Router o expone la selección), mantener IDs constantes derivados de ruta y comprobar la relación accesible en las cuatro rutas, incluida la redirección vacía a sedes. |
| Regresión de deep links/guards/rutas al modificar el layout. | No tocar `administracion.routes.ts`; validar `administracion.routes.spec.ts` y recorrido directo a cada hija, conservando guards y destinos. |

### Fuera de alcance de T-17

Sin cambios a rutas hijas, guard, deep links, backend, APIs/contratos, matriz central, DDL/datos, permisos/roles, servicios, Clerk, dependencias, navegación global `/administracion`, vistas de negocio o semántica de inventario. La enmienda no reabre el cierre ni los AC-1…AC-14 de la Feature 012.

### Trazabilidad de la enmienda

| AC de enmienda | Partes previstas |
|---|---|
| AC-15 | Router-based route active + tablist/tabs + `aria-selected`: `administracion-nav.component.ts/html`; test nav. |
| AC-16 | Teclas izquierda/derecha circulares, foco, `tabindex` y anchors: TS/HTML; tests teclado y href. |
| AC-17 | `tabpanel` y `aria-labelledby` enlazado a la pestaña activa: `administracion.component.html` y test layout/nav. |
| AC-18 | Integridad de las cuatro rutas/guards/deep links: no modificar `administracion.routes.ts`; tests existentes de rutas/vistas y pruebas nav con Router real. |
| AC-19 | Tests nuevos + regresión, build, 4200 y humo 8080 con evidencia: tareas E17-1…E17-4 y Cierre E17-C1…C4. |
