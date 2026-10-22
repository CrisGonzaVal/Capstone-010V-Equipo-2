# Feature 010 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada por el usuario y apta según QA (AC-1…AC-18, D-1…D-10). Este plan concreta la implementación sin cambiar el alcance. No se propone agregar dependencias.

## 1. Enfoque técnico

### Prerrequisito: evolución justificada en `stack.md`

Antes de tocar modelos, DDL, configuración de persistencia o migraciones, actualizar `docs/spec/stack.md` y obtener aprobación conforme a AGENTS.md §7. La justificación debe cubrir como mínimo:

1. La convivencia del esquema global de control y esquemas tenant en una base, conservando las doce entidades 3NF, `usuario.departamento_id NOT NULL` y `departamento.institucion_id NOT NULL`.
2. La réplica local de `institucion`, con registro canónico solo en control y FK tenant-locales, sin FK cross-schema.
3. El cambio de ubicación de `rol`, `prioridad` y `estado_ticket`: de catálogos globales compartidos (norma actual posterior a Feature 008) a réplicas por tenant; el rol Superadmin permanece en control.
4. La tabla global de resolución `correo → esquema`, sus restricciones de unicidad, la tabla de versión por tenant y la regla de denegación si la versión no coincide.
5. El esquema efectivo por ejecución SQLAlchemy, la independencia frente al pool y el alcance de la sesión global/tenant.
6. El control de inicialización de Docker para que `02_datos_semilla.sql` no trunque datos multi-tenant ni migraciones existentes.
7. El proceso de migración en sitio, transaccional/idempotente, la copia y derivación de relaciones y el plan de recuperación ante fallo.
8. El bootstrap de control con institución/departamento administrativos, usuario y rol Superadmin manteniendo nulabilidades actuales.

**Alternativa descartada:** implementar primero el DDL o el cambio de modelos y documentar después; AGENTS §7 prohíbe alterar el modelo de 12 entidades sin justificación aprobada en `stack.md`.

### Resolución y selección segura de esquema

La autenticación Clerk y la resolución del correo primario verificado en control preceden a cualquier sesión de negocio. La dependencia de identidad resuelve un contexto inmutable de solicitud: identidad local, rol, nombre de tenant validado y versión comprobada. Ningún campo enviado por el cliente participa en su construcción.

Para persistencia se elige `schema_translate_map` de SQLAlchemy, aplicado al contexto/ejecución de cada sesión, con identificadores de esquema procedentes únicamente del registro de control y validados contra una allowlist de nombres generados. El modelo usa un esquema lógico común traducido al esquema tenant correspondiente; las operaciones de control usan un contexto de control separado. El `schema_translate_map` no se muta en el `Engine` compartido ni se comparte una `Session` entre solicitudes.

**Alternativa descartada: `search_path`.** Cambiar `search_path` con estado de sesión/conexión deja contexto mutable asociado a la conexión y expuesto a filtración al reciclarla; limpiar en `finally` puede fallar ante excepciones, rollback o desconexión. `schema_translate_map` mantiene la elección en la ejecución ORM/Core y evita que el estado de la conexión del pool sea autoridad de tenant.

Al terminar cada petición se cierra la `Session` y su transacción; la conexión se devuelve al pool sin ningún `SET search_path` ni estado de tenant persistente. Las operaciones que ejecuten SQL fuera del ORM no pueden seleccionar tablas por un nombre controlado por cliente y quedan fuera de la ruta de acceso a tablas tenant. La prueba PostgreSQL debe reutilizar conexiones deliberadamente alternando identidades y comprobar que nunca conserva esquema anterior.

**AC:** AC-1…AC-5, AC-12, AC-16, AC-17.  
**Evidencia:** pruebas de dependencia/servicio y PostgreSQL gated de alternancia de tenant en conexiones reutilizadas, incluyendo parámetros adversariales y objetos con IDs iguales.

### Control y contrato de tablas globales

El bootstrap crea en el esquema global de control las doce tablas canónicas y las estructuras auxiliares requeridas. El registro de instituciones es canónico allí. La fila `institucion` de una institución existe también en su tenant como espejo. `rol`, `prioridad` y `estado_ticket` se siembran/reconcilian en cada tenant; en control se conserva `rol` con el rol Superadmin. El departamento administrativo y usuario Superadmin satisfacen las FK obligatorias del modelo.

#### Mapa correo-esquema

Estructura nueva `mapa_usuario_esquema` en control:

| Columna | Tipo/propiedad lógica | Regla |
|---|---|---|
| `correo` | correo primario verificado, normalizado igual que el local | PK/único; una identidad local no puede apuntar a más de un esquema |
| `institucion_id` | ID canónico de institución | FK al registro de control |
| `nombre_esquema` | nombre PostgreSQL determinado por la regla estable del plan | único y generado/validado en servidor |
| `activo` | booleano | solo asociaciones activas resuelven solicitudes |

El mapa puede incluir la identidad Superadmin asociada al esquema de control para que todas las identidades locales tengan resolución inequívoca. La identidad/rol Superadmin se consulta en control y nunca se enruta como usuario tenant. No se permite que una institución tenant use el nombre reservado al esquema de control.

#### Versión tenant

En cada esquema tenant se crea `version_esquema` con exactamente una fila vigente:

| Columna | Tipo/propiedad lógica | Regla |
|---|---|---|
| `version_id` | clave primaria | una fila de estado por tenant |
| `version` | texto no vacío | token de versión objetivo, inicialmente `010.1` |
| `actualizada_en` | timestamp | instante de último registro exitoso |

La versión objetivo se declara como una constante de despliegue `VERSION_ESQUEMA_OBJETIVO = "010.1"`, compartida por el código que resuelve y el procedimiento de migración; se incrementa en cambios posteriores de DDL/migración. Solo bootstrap, migración y aprovisionamiento escriben esta fila, y únicamente al final de la transacción/verificación correspondiente. El middleware/dependencia de sesión compara igualdad exacta antes de entregar un contexto tenant. Diferente, ausente, duplicada, futura o ilegible implica denegación cerrada; no hay fallback.

**Alternativa descartada:** inferir la preparación por existencia de tablas o ejecutar migraciones implícitamente en cada petición, porque no identifica una versión compatible ni da una condición estable de enrutamiento.

**AC:** AC-6, AC-10…AC-13, AC-16.  
**Evidencia:** tests de ausencia, igualdad, discrepancia, estado parcial y rol de escritor; versión permanece anterior si falla cualquier cambio.

### Nombre determinista de esquema

Usar prefijo reservado `tenant_` y slug ASCII minúsculo del `institucion_id` canónico: transliterar a ASCII, convertir secuencias no alfanuméricas a `_`, recortar `_`, limitar el slug a 50 caracteres y anexar sufijo estable de 8 caracteres hexadecimales derivado del SHA-256 del ID canónico normalizado. El resultado máximo queda por debajo del límite de identificadores PostgreSQL. Rechazar IDs vacíos, esquema reservado, nombres fuera de allowlist o colisión de nombre con otro `institucion_id`; nunca truncar silenciosamente el hash. El mismo procedimiento se usa en bootstrap, migración y aprovisionamiento.

**Por qué:** slug legible más sufijo determinista evita colisiones por transliteración/recorte y produce un nombre idempotente sin aceptar un identificador de esquema desde el cliente.

**AC:** AC-7, AC-8, AC-10, AC-11, AC-13.

### Migración de la base existente

La migración se implementa como script operacional versionado y ejecutable explícitamente con `psql` y `ON_ERROR_STOP=1` contra respaldo/ventana de mantenimiento. Se elige SQL en `database/` por consistencia con `98_`/`99_`, auditabilidad y ejecución única controlada; la alternativa de servicio de aplicación se descarta porque ampliaría privilegios y expondría una transformación destructiva de datos a solicitudes ordinarias. **No fijar aún el nombre `97_` ni ubicar el archivo bajo el montaje de initdb:** el requisito es que Docker no lo ejecute automáticamente. Antes de elegir ruta/nombre, inspeccionar `docker-compose.yml` y los scripts de initdb; preferir un archivo operacional fuera del glob/montaje de initdb, sin renombrar `98_`/`99_` ni alterar el orden funcional existente. Si no puede mantenerse fuera del initdb, parar y pedir decisión en vez de añadir un SQL que falle en instalación limpia.

Orden de fases (preflight completo antes de cualquier movimiento):

1. Comprobar versión PostgreSQL, permisos, estado esperado del esquema legado, disponibilidad de respaldo y ausencia de una ejecución incompatible concurrente.
2. Calcular para cada institución el nombre determinista; detectar colisiones, filas huérfanas/ambiguas y conflictos de correo/mapeo. Si hay una sola fila irresoluble, fallar antes de mutar.
3. Inicializar control idempotentemente; copiar allí el registro canónico de instituciones, la identidad/rol Superadmin y el mapa de **todos** los usuarios locales a sus tenants. Crear el departamento administrativo necesario sin cambiar nulabilidades.
4. Crear cada esquema tenant y ejecutar el DDL canónico equivalente a `01_esquema.sql`; copiar la institución local espejo y los catálogos `rol`, `prioridad`, `estado_ticket` necesarios para sus FKs.
5. Copiar tablas de cada institución preservando PK/FK: por `institucion_id` directo; `usuario` por `departamento`; `movimiento_inventario` por `inventario`. No duplicar Superadmin como usuario tenant. Restaurar/ajustar secuencias por esquema.
6. Verificar conteos, claves, referencias, secuencias, mapas, espejos y datos operativos por tenant. Insertar `version_esquema.version = '010.1'` al final de cada tenant validado.
7. Mantener la estructura y filas del esquema legado intactas durante la copia y verificación. El corte de routing se habilita únicamente tras validar todos los tenants; la limpieza/renombrado del esquema legado no es parte implícita de la copia y requiere paso explícito, respaldo y aprobación operacional. No declarar migración global exitosa en estado mixto.

Las operaciones DDL/DML de PostgreSQL se agrupan en transacciones por fase compatible. Como DDL PostgreSQL es transaccional, un fallo dentro de una fase revierte esa fase; para fallos entre fases, el legado se conserva, versiones de tenant actúan como checkpoints y el script se reejecuta por comparación de versión/estado verificado. No marcar tenant listo ni enrutable antes del último paso de verificación. Si se detectan objetos parciales sin versión objetivo, no limpiar automáticamente datos no reconocidos: abortar con esquema/objeto y procedimiento de recuperación; una reanudación solo reutiliza objetos cuya propiedad y contenido se verificaron.

**Alternativa descartada:** copiar/borrar todo en una única operación opaca o usar la semilla, porque los datos reales deben ser recuperables y `02_datos_semilla.sql` trunca tablas.

**AC:** AC-6, AC-10…AC-13, AC-16.  
**Evidencia:** ejecución en snapshot PostgreSQL legado, conteos y hashes/referencias antes-después, fallo inyectado, reanudación, segunda ejecución y caso ambiguo que falla sin cambios operativos.

### Docker, DDL canónico y semilla

`01_esquema.sql` conserva el DDL canónico de doce tablas para bootstrap/control y para construir cada tenant con sustitución segura del namespace; `02_datos_semilla.sql` conserva su carácter destructivo únicamente como semilla QA de instalación limpia. Ambos scripts iniciales no se usan para migración de base existente.

Para instalaciones nuevas, `01_` prepara el DDL canónico; `02_` se limita a instalación QA vacía o reset QA expresamente autorizado. Su `TRUNCATE` queda limitado a esquemas de QA identificados/permitidos y debe abortar antes del primer truncado si detecta datos, mapeos o versión que indiquen base existente. No inferir que la base es QA solo porque algún tenant carezca de versión. El bootstrap institucional del Superadmin y los fixtures QA deben tener procedencia/alcance distinguible para que el seed no pueda truncar el esquema control ni tenants provisionados. Los datos iniciales no se crean por scripts montados automáticamente en reinicios: initdb corre solo al crear volumen vacío.

Para volúmenes existentes, la migración se aplica explícitamente con `psql` sobre backup y base real. Ningún script de migración preexistente se renombra ni cambia de orden funcional. El script nuevo no se coloca bajo un montaje ejecutado automáticamente por initdb salvo que se demuestre que es no-op seguro en instalación limpia y nunca pueda truncar/alterar datos; ubicación y orden exactos quedan sujetos a inspección de `docker-compose.yml` antes de crearlo.

El diseño final mantiene distinción estricta entre: (a) instalación vacía, donde DDL crea control y tenants de ejemplo y la seed QA usa un modo/alcance permitido explícitamente; (b) volumen ya inicializado, donde Docker no reejecuta scripts; y (c) migración explícita no destructiva, que nunca ejecuta seed. La semilla usa modo QA explícito para `TRUNCATE`; no se aceptan “auto-detecciones” que puedan interpretar datos reales como entorno descartable. Verificar y ajustar la instalación limpia con una base temporal antes de decidir el detalle del guard; si los scripts montados se ejecutan sin parámetros, el DDL debe establecer una señal segura y no manipulable de instalación limpia o la semilla destructiva debe salir del initdb automático.

**AC:** AC-6, AC-8, AC-10, AC-11, AC-13, AC-16.

### Aprovisionamiento mínimo: API y atomicidad

Operación propuesta:

| Método y ruta | Entrada | Éxito | Autorización |
|---|---|---|---|
| `POST /api/v1/control/instituciones/` | `InstitucionAltaControlCrear` | `201`, `InstitucionAltaControlRespuesta` | solo Superadmin mediante matriz central |

Entrada Pydantic v2: `institucion_id`, `nombre`, `rut` opcional, `direccion` opcional, `correo_administrador`, `nombre_administrador`, `apellido_administrador`, `departamento_nombre_administrativo` (no se recibe nombre de esquema, versión, rol ni estado). Respuesta: `institucion_id`, `nombre`, `correo_administrador`, `nombre_esquema`, `version_esquema`, `estado` (`operativa`) y mensaje. Schemas usan `ConfigDict` cuando aplique y validación moderna; no se exponen secretos Clerk.

El endpoint declara `response_model`, `status_code=201`, documentación de 401/403/409/422/503 y delega a `control_service`; inyecta `Session` con `Depends(get_db)`. La matriz añade explícitamente `("POST", "/api/v1/control/instituciones/")` para Superadmin. Duplicidad de ID/correo, conflicto con esquema existente o Clerk sin identidad da conflicto/validación explícita y ninguna mutación operativa.

Flujo de compensación:

1. Validar rol Superadmin, formato y correo Clerk existente antes de crear recursos tenant.
2. Calcular nombre de esquema servidor-side, reservar institución/correo en control bajo transacción y rechazar duplicidades.
3. Crear el esquema, tablas, espejo institucional y catálogos; insertar primer Administrador y su mapa.
4. Verificar relaciones/valores y escribir versión objetivo como último paso; solo entonces registrar `estado=operativa` y confirmar.
5. Ante error, rollback de transacción y compensación explícita para el esquema si el DDL transaccional no queda revertido por la forma de ejecución; eliminar solo objetos creados por esta solicitud y solo si siguen vacíos/propiedad verificada. Si la limpieza falla, marcar registro como no operativo y devolver error recuperable; el router nunca devuelve éxito ni el routing resuelve un tenant no operativo.

El email debe existir en Clerk antes del alta y no se crean cuentas ni credenciales. Se reutiliza el correo primario verificado del backend para la vinculación posterior.

**Alternativa descartada:** endpoint CRUD genérico o edición directa del esquema desde la UI; el alcance 010 es solo aprovisionamiento inicial, y cada mutación debe quedar bajo matriz/servicio.

**AC:** AC-7…AC-9, AC-13, AC-15, AC-17.

### Portal Angular `/control`

Mantener la aplicación Angular existente; añadir un segmento lazy-loaded `/control` con rutas standalone. Definir guard de navegación `ControlSuperadminGuard` que espera la identidad ya resuelta por `AutenticacionService`, compara rol exacto `Superadmin` y redirige a acceso denegado para otros roles. El guard no es frontera de seguridad: el backend valida token y matriz siempre.

El portal tiene dos vistas mínimas: login con UI prebuilt de Clerk para una sesión Clerk válida y una pantalla protegida de alta de institución. La ruta de alta se carga perezosamente y ofrece campos acordes al DTO, estados `signal()` para carga/resultado/error, y `computed()` solo para valores derivados. Servicios, componentes standalone y guard usan `inject()`, no `NgModule` ni constructor DI; presentación solo Tailwind y nombres de dominio en español con sufijos Angular conservados. La navegación hacia `/control` con rol distinto nunca muestra la pantalla de alta; no se agrega CRUD general.

El interceptor Clerk existente presenta el Bearer. El frontend no envía `nombre_esquema`, tenant, versión ni rol como autoridad; el backend calcula y valida esos valores. La pantalla informa resultado operativo solo ante respuesta exitosa de la API.

**AC:** AC-7…AC-9, AC-15, AC-17.

**Alternativa descartada:** UI protegida solo por ocultación de menú o guard cliente como autorización; ambas se pueden eludir invocando directamente la API.

### Lecturas globales del Superadmin

Revisar cada operación global vigente (dashboard e inventario/lecturas autorizadas) para resolver el conjunto de tenants desde control, abrir sesiones con sus mapas por ejecución y adjuntar `institucion_id`/nombre a filas que identifican entidades. No ejecutar consultas tenant una por una en transacciones independientes: todas las lecturas que componen una respuesta global se agrupan en una transacción `REPEATABLE READ` en la misma conexión/base, para obtener snapshot único. Un error de acceso, versión o consulta en cualquier tenant revierte la transacción y devuelve error recuperable no parcial. No se agregan permisos de escritura a Superadmin.

**Alternativa descartada:** omitir tenants fallidos o mezclar transacciones con snapshots distintos, porque reportaría un consolidado aparentemente íntegro pero temporalmente inconsistente.

**AC:** AC-12, AC-14, AC-17.

## 2. Archivos previstos y responsabilidad

| Archivo / grupo | Responsabilidad | AC |
|---|---|---|
| `docs/spec/stack.md` | Prerrequisito de justificación descrito al inicio: control/tenants 3NF, catálogos, espejos, routing, mapa, versión, bootstrap y scripts antes de cambios. | AC-5…AC-14 |
| `backend/app/db/database.py`, `backend/app/api/dependencies.py` | Contexto SQLAlchemy por ejecución, sesiones de control/tenant separadas, cierre y no persistencia de esquema en pool. | AC-1…AC-6, AC-12, AC-16 |
| `backend/app/models/` y modelos de control/versionado | Mantener las doce entidades, mapear estructuras auxiliares aprobadas y tablas de control/versionado; FK y restricciones locales. | AC-5…AC-6, AC-10…AC-13 |
| `backend/app/core/config.py` | Versión objetivo y configuración de namespaces/control sin valores de tenant suministrados por cliente. | AC-6…AC-13 |
| `backend/app/services/control_service.py`, `tenant_service.py`, `auth_service.py` | Bootstrap/registro, resolución correo-esquema, validar versión, aprovisionar y componer compensaciones; servicios de negocio reciben identidad/esquema resueltos. | AC-1…AC-17 |
| `backend/app/core/permisos.py` | Añadir únicamente la operación de alta de institución a Superadmin; conservar demás matriz, especialmente denegación de escrituras de negocio. | AC-7…AC-9, AC-15, AC-17 |
| `backend/app/schemas/control_schema.py` | DTOs Pydantic v2 de entrada/salida de aprovisionamiento, sin aceptar esquema/versión/rol del cliente. | AC-7…AC-9, AC-15, AC-17 |
| `backend/app/api/v1/endpoints/control.py`, `backend/app/api/v1/api.py` | Ruta delgada, permisos, `response_model`, `status_code`, errores/OpenAPI y registro del router. | AC-7…AC-9, AC-15, AC-17 |
| Servicios de inventario, tickets, usuarios y dashboard | Reusar sesión/contexto tenant; convertir lecturas Superadmin autorizadas a multi-tenant atribuida y transacción consistente. | AC-1…AC-5, AC-12, AC-14, AC-17 |
| `database/01_esquema.sql`, `database/02_datos_semilla.sql` | DDL canónico compatible con control/tenant e instalación limpia; semilla de QA explícita y no aplicable a datos migrados/provisionados. | AC-6, AC-8, AC-10, AC-16 |
| Script operacional de migración multi-tenant en ubicación aprobada fuera de initdb automático | Migración explícita, transaccional por fase, preflight, partición, idempotencia por versión, preservación y recuperación; nombre y ubicación se fijan solo tras inspección de montaje/orden. | AC-6, AC-10…AC-13, AC-16 |
| `backend/tests/` (fixtures, API, servicios, PostgreSQL gated) | Pruebas TDD de contrato, routing/pool, versionado, migración, aprovisionamiento, errores, agregación global y regresiones. | AC-1…AC-18 |
| `frontend/src/app/app.routes.ts`, `frontend/src/app/core/guards/` | Registrar navegación lazy-loaded y guard exacto Superadmin. | AC-7, AC-9, AC-15 |
| `frontend/src/app/features/control/` (rutas, componentes, servicios y pruebas) | Login Clerk existente, alta mínima, estados reactivos y presentación Tailwind. | AC-7…AC-9, AC-15 |
| Interfaces de identidad y pruebas Angular existentes | Tipos de contexto global/tenant si el contrato cambia y regresión por rol. | AC-7, AC-15, AC-17 |
| `docs/spec/features/010-multi-tenant-por-esquemas/spec.md`, `tasks.md`, `MEMORY.md`, `docs/spec/roadmap.md` | Evidencia AC, checks/memoria/cierre y roadmap solo cuando todos los requisitos de AGENTS §8 estén satisfechos. | AC-18 |

Los archivos concretos se ajustan si el código revela responsabilidades adicionales, sin modificar alcance. No se añade paquete sin análisis y aprobación. Cualquier necesidad de cambiar el modelo aprobado, Clerk o las transacciones de la garantía global detiene implementación y vuelve a spec/plan.

## 3. Estrategia de pruebas

### TDD y SQLite ordinario

1. Escribir primero pruebas HTTP rojas para identidad resuelta, denegaciones 401/403, permisos, DTO/OpenAPI, bootstrap lógico, versionado y contrato de aprovisionamiento.
2. Usar SQLite de memoria con un contexto lógico único y fixtures de control/tenants representados sin namespaces. Estas pruebas acreditan contratos, reglas de negocio, servicios y no regresión, pero no aislamiento físico ni DDL multi-esquema.
3. Validar el contrato por `TestClient`: rutas, `response_model`, `status_code`, estados Clerk, rol Superadmin y respuestas de conflicto/error; inspeccionar `/openapi.json`.
4. Cubrir aprobación/denegación para todos los roles, correo desconocido/duplicado, datos cliente adversariales, versión ausente/incorrecta, creación Clerk inexistente y compensación sin dejar estado operativo.
5. Probar globales con datos identificables y homónimos, fallo de un tenant y propagación del error; aserción de que no se entrega agregado parcial.

### Pruebas gated PostgreSQL 16 (`POSTGRES_TEST_URL`)

- Routing con dos o más esquemas, IDs coincidentes, correos diferentes, parámetros adversariales y alternancia de requests sobre conexiones físicamente reutilizadas.
- Confirmar `schema_translate_map` por ejecución, que la conexión devuelta no conserva `search_path` alterado ni contexto de tenant y que falla cerrado al eliminar/cambiar versión.
- Bootstrap de control repetido; validación de PK/FK locales, seis FK a `institucion`, ausencia de FK cross-schema, catálogos replicados y nombres colisionantes.
- Migración en snapshot legado con conteos/relaciones/secuencias; todos los correos mapeados; ambigüedad rollback; fallo entre fases y recuperación; segunda ejecución no destructiva con comparación versión objetivo.
- Aprovisionamiento real con Clerk simulado en su frontera externa (respuesta controlada; identidad existente/inexistente), creación del esquema y prueba de compensación tras fallos en cada fase.
- Transacción global `REPEATABLE READ`: mutación concurrente controlada no produce resultados de tenants de instantes distintos; tenant fallido impide resultado parcial.

Las pruebas PostgreSQL se marcan con el mecanismo gated existente y quedan omitidas de forma explícita cuando `POSTGRES_TEST_URL` no está configurado; el cierre requiere ejecutarlas. No se interpreta un `pytest` SQLite verde como evidencia AC-1/4/5/6/10/11/12/14/16.

### Frontend

- Tests standalone para guard: Superadmin accede, otros roles se redirigen/deniegan; sesión no resuelta espera a la identidad sin duplicar `/auth/me`.
- Test de login que confirma Clerk prebuilt y envío Bearer por interceptor existente, sin login local.
- Tests de formulario alta: validación, carga, éxito, errores de Clerk/duplicidad/fallo; el cliente no manda esquema ni versión y no simula éxito.
- `ng test --watch=false --browsers=ChromeHeadless` con launcher Edge conforme AGENTS; `ng build` producción.

### Contrato y recorridos

- Inspeccionar `/openapi.json`: operación POST nueva, DTO, `201`, 401/403/409/422/503 y matriz coincidente.
- Recorrido funcional en 4200 con Superadmin autenticado mediante Clerk, alta real en PostgreSQL y login posterior del Administrador tenant; intentar acceso `/control` como rol limitado.
- Reconstruir imagen con `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d frontend`; humo en 8080 de ruta Angular, guard, login/alta básica y build producción actual.

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Contexto tenant se fuga por pool | `schema_translate_map` por ejecución, sesiones cortas y separadas, sin cambiar `search_path`; test alternando identidades y conexión reutilizada PostgreSQL. |
| Esquema malicioso o aportado por cliente | El mapa de control es única fuente; nombre generado con regla, validado en allowlist y parametrización SQLAlchemy; no aceptar nombre de esquema en DTO/query/header. |
| Cambio parcial de DDL o migración | Backup, preflight completo, fases transaccionales, versión escrita al final, legado retenido para recuperación y estado mixto no enrutable. |
| `02_datos_semilla.sql` trunca datos reales | Seed explícita QA solo en instalación vacía/reset autorizado; no se ejecuta en migración; barrera antes de cualquier `TRUNCATE`. |
| Desacuerdo entre control y espejo `institucion` | Control como fuente canónica, actualización administrativa acompasada, reconciliación verificada; FK permanecen locales. |
| Catálogos dejan de estar globales | Justificar y aprobar en `stack.md` antes del DDL; clonar valores requeridos a tenants y mantener rol Superadmin en control. |
| Correo inexistente en Clerk deja alta sin acceso | Verificar identidad antes de reservar/esquema; respuesta explícita sin tenant operativo. |
| Nombre derivado colisiona o supera límite PostgreSQL | Sufijo hash estable, límites explícitos, constraint de unicidad y aborto sin sobrescritura. |
| Escritor global agrega permiso a operación de negocio | Añadir solo POST de alta a matriz; tests de regresión de escrituras de catálogo/stock/ticket. |
| Dashboard global mezcla snapshots o oculta tenant fallido | Una transacción `REPEATABLE READ` y error completo; tests de concurrencia y tenant fallido. |
| Guard Angular se confunde con autorización | API comprueba Clerk/matriz siempre; test HTTP directo por rol además de pruebas de ruta. |
| Instalación limpia Docker y migración usan el mismo flujo | Separar instalación vacía (01/02), initdb de volumen existente (no corre de nuevo) y script de migración explícita; prueba con base temporal y snapshot legado. |
| SQLite oculta incompatibilidad PostgreSQL | Matriz de pruebas gated requerida y condición explícita de cierre con `POSTGRES_TEST_URL`. |
| Frontend 8080 conserva imagen antigua | Reconstrucción obligatoria antes del smoke test. |

## 5. Cobertura AC por partes y evidencia requerida

| AC | Partes principales | Evidencia requerida al cierre |
|---|---|---|
| AC-1 | Dependencia de identidad, contexto `schema_translate_map` | Test PostgreSQL de dos correos/tenants y ruteo anterior a sesión negocio. |
| AC-2 | Resolución control y fallas cerradas | Pruebas de correo inexistente, duplicado, sin mapa/no preparado, sin consultas tenant ni fallback. |
| AC-3 | DTOs/routing y sesiones | Pruebas de parámetro/body/header/claim adversarial que no alteran resultado tenant. |
| AC-4 | Ciclo de sesión y pool | PostgreSQL alterna solicitudes con IDs repetidos en conexión física reutilizada sin fuga/ escritura cruzada. |
| AC-5 | DDL tenant y restricciones Feature 008 | PostgreSQL verifica FK locales/compuestas rechazan relaciones incoherentes y no hay FK cross-schema. |
| AC-6 | Bootstrap control y versionado | Dos ejecuciones sobre base existente dejan registros administrativos únicos e iguales, datos operativos intactos. |
| AC-7 | API y portal mínimo | Clerk Superadmin entra `/control`, `POST` crea institución tenant completa y Administrador accede limitado. |
| AC-8 | Verificador Clerk, compensaciones | Identidad no existente y fallos inyectados dan error sin tenant operativo ni daño a esquema previo. |
| AC-9 | Matriz central y endpoint | Pruebas HTTP 401/403 por falta de sesión/rol, y ninguna creación o mapeo. |
| AC-10 | Script operacional de migración | Snapshot legado particionado, usuarios + movimientos derivados correctamente, todos los correos mapeados y conteos/IDs preservados. |
| AC-11 | Marcador de versión y migración | Segunda ejecución compara cada tenant con `010.1`; ya aplicado no altera filas y parcial se recupera sin pérdida. |
| AC-12 | Resolución y globales | Versión ausente/diferente niega negocio; Superadmin obtiene fallo si tenant requerido no compatible. |
| AC-13 | Aprovisionamiento/migración | Cada tenant completo tiene versión objetivo exacta; tenant discrepante no se enruta. |
| AC-14 | Read models globales | PostgreSQL `REPEATABLE READ`, filas atribuidas, instante consistente y respuesta fallida/no parcial ante tenant inaccesible. |
| AC-15 | Rutas Angular `/control` | Test standalone confirma Superadmin ve login/alta permitida y rol limitado se bloquea; CRUD no presente. |
| AC-16 | Suite SQLite + PostgreSQL | `pytest` ordinario verde y ejecución gated PostgreSQL con pruebas enumeradas; no se atribuye evidencia de namespaces a SQLite. |
| AC-17 | Clerk, matriz, OpenAPI y versión | 401/403 según escenario, operación/documentación visibles y matriz central coherente. |
| AC-18 | Tareas/evidencia/cierre | Checklist completa, AC con pruebas/recorridos, suites, OpenAPI, 4200/8080, grep, MEMORY y reviewer. |

## 6. Cierre

No marcar feature ni roadmap como cerrados por completar implementación. El cierre exige todas las tareas, evidencia por AC, `pytest` ordinario y PostgreSQL gated, `ng test`, `ng build`, OpenAPI, recorrido funcional en 4200 y humo en 8080 tras rebuild, grep documental de AGENTS/MEMORY/skills y actualización de memoria. Registrar en `spec.md` solo evidencia observada y seguir AGENTS.md §8.5–§8.7.
