# Feature 007 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada como fuente de requisitos (AC-1…AC-17). Este plan concreta la autorización de la identidad Clerk ya resuelta en Feature 006, la política institucional temporal de 007 y el retiro seguro de `usuario.password`; no cambia la autenticación ni añade particionamiento de catálogo/stock reservado a 008.

## 1. Enfoque técnico por componente

### Backend: identidad, permisos y ámbito institucional

Mantener `get_current_user` como dependencia agregada de autenticación: su resultado contiene el usuario SQLAlchemy vinculado y el `sub` Clerk verificado. Añadir una dependencia de autorización de rol en `backend/app/api/dependencies.py`, parametrizable con uno o varios roles permitidos, que dependa de `get_current_user` y reutilice esa identidad. La dependencia solo aplica el permiso general; si faltan credenciales o Clerk falla, continúa el 401 actual; identidad autenticada sin permiso obtiene 403. Rol faltante/desconocido nunca concede.

La política completa, centralizada y explícita por operación, vive en `backend/app/core/` como matriz de permisos de roles/rutas; los endpoints la declaran al aplicar la dependencia. No se usa un único permiso por router porque la matriz diferencia verbos, recursos y reglas especiales. Las reglas por objeto/institución se aplican en servicios antes de leer o mutar datos: se pasa la identidad ya resuelta (usuario local y rol) a servicios y se obtiene institución por `Usuario.departamento_id → Departamento.institucion_id`. Solo `Superadmin` omite el filtro. Un ámbito necesario sin resolver resulta en 403; no se transforma en alcance global.

Para entidades y colecciones, los servicios filtran en consulta ORM/Core tipado. Tickets: Administrador/Bodeguero por institución; Solicitante por `usuario_id`; un ticket ajeno/inexistente en operación permitida se oculta como 404. Inventario y movimientos: roles limitados por institución; cuando `departamento_id` explícito apunta a otra institución, 403. Catálogo maestro de categoría/producto conserva su lectura compartida; `GET /tickets/catalogos` conserva productos y `stock_total` global y filtra únicamente el conjunto de solicitantes según la matriz (Solicitante solo él mismo; Administrador/Bodeguero su institución; Superadmin global).

Para `POST /tickets/`, añadir identidad al servicio: Solicitante queda atribuido al usuario autenticado sin poder elegir otro; los demás roles conservan el DTO/contrato existente con `usuario_id` obligatorio, y Administrador/Bodeguero validan institución del solicitante. Para cambios de estado/despacho, después de autorización de rol comprobar ámbito del ticket y el inventario afectado dentro de la lógica transaccional existente; preservar atomicidad de Feature 005. Para `POST /usuarios/`, el servicio aplica la restricción del rol asignable por Administrador y el ámbito institucional de datos; Superadmin conserva libertad total de rol.

### Frontend: guards y estado de denegación

`AutenticacionService` conserva la señal de identidad ya cargada desde `/auth/me`; el `RolGuard` lee esa identidad mediante inyección, espera inicialización/carga según el estado expuesto y compara `rol` exacto (los cuatro literales; ningún alias `Admin`). Las rutas protegidas reciben datos explícitos de roles permitidos por sección/capacidad y combinan guard de sesión existente y guard de rol. `/login`, `/health` público y redirección raíz mantienen contrato vigente. La denegación retorna navegación a una vista/estado dedicado, no al login, no cierra sesión y no invoca la operación. Dashboard/inventario/tickets/administración siguen siendo lazy-loaded. La capa visual de tickets evita ofrecer capacidad operativa al Solicitante cuando aplique, pero la frontera de seguridad real permanece en API.

La ruta tickets distingue vista y capacidad sin inventar endpoints: los cuatro roles pueden entrar a tickets; solo Solicitante queda sin Kanban/cambios de estado/despacho según AC-3, AC-6 y AC-7. La implementación deberá resolver esto con rutas/metadata y controles de vista existentes, manteniendo los casos permitidos y usando el guard a nivel de ruta/capacidad. No se crearán datos de rol alternativos ni se inferirá permiso desde Clerk.

### Base de datos y retiro de contraseña

En instalaciones nuevas, quitar columna y valores de `usuario.password` de `database/01_esquema.sql` y `database/02_datos_semilla.sql`; quitar el atributo de `Usuario` y de `UsuarioCrear`, y actualizar todos los tests/fixtures que lo exijan. Corregir comentarios obsoletos en semilla y docstrings señalados por AC-11.

Crear un script SQL versionado e idempotente bajo `database/` posterior a los scripts de inicialización (prefijo que garantice orden y nombre que identifique migración). Su única operación de esquema será `ALTER TABLE usuario DROP COLUMN IF EXISTS password`; no reinicializa ni actualiza filas. El directorio `/docker-entrypoint-initdb.d` solo se ejecuta con volumen nuevo, por lo que la migración debe aplicarse explícitamente a bases ya inicializadas: incluir instrucciones de operación reproducibles en la cabecera del script/tarea para ejecutar `psql` contra la BD existente con `ON_ERROR_STOP=1`, desde el host o `docker exec` al contenedor `db`, y verificar el catálogo antes/después. No se debe confiar en renombrar scripts de init ni en destruir volúmenes. Validar migración en PostgreSQL 16 con usuario y relaciones preexistentes, ejecutar segunda vez y confirmar preservación; SQLite no sustituye esa evidencia de DDL PostgreSQL.

## 2. Archivos que se crean o modifican

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/core/permisos.py` (nuevo) | Matriz explícita rol-operación y literales de roles, sin alias ni permisos implícitos. | AC-1, AC-7…AC-10 |
| `backend/app/api/dependencies.py` | Dependencia parametrizable de rol que conserva 401 de autenticación y deniega rol con 403. | AC-1, AC-9, AC-15 |
| `backend/app/api/v1/api.py` | Mantener seguridad agregada de sesión y declarar/registrar autorización por operación sin dejar rutas de negocio fuera. | AC-9, AC-15 |
| `backend/app/api/v1/endpoints/usuarios.py` | Inyectar identidad/autorización por ruta y transportar contexto al servicio. | AC-8…AC-10, AC-15 |
| `backend/app/api/v1/endpoints/inventario.py` | Permisos por operación y contexto de identidad a consultas/mutaciones. | AC-7…AC-9, AC-15 |
| `backend/app/api/v1/endpoints/tickets.py` | Permisos por operación y contexto de identidad a lectura, creación, estado y despacho. | AC-6…AC-9, AC-15 |
| `backend/app/services/usuario_service.py` | Límites institucionales y rol asignable; listados institucionales. | AC-8, AC-10, AC-15 |
| `backend/app/services/inventario_service.py` | Filtros por institución en stock/movimientos y denegación de departamento ajeno; catálogo compartido. | AC-7…AC-9, AC-15 |
| `backend/app/services/ticket_service.py` | Propiedad, filtros institucionales, atribución de solicitante y comprobación de ámbito previa a operación transaccional. | AC-6…AC-9, AC-15 |
| `backend/app/models/usuario.py` y `backend/app/models/institucion.py` | Eliminar atributo ORM `password`; corregir el `__init__.py` de modelos solo si el proyecto requiere registrar la matriz/dependencias nuevas (sin alterar entidades). | AC-8, AC-12, AC-14 |
| `backend/app/schemas/usuario_schema.py` | Quitar contraseña de `UsuarioCrear`; conservar los demás campos del contrato. | AC-12, AC-14 |
| `backend/app/schemas/ticket_schema.py` | Corregir docstring de `TicketDespacho` que califica autenticación como decorativa. | AC-11 |
| `backend/tests/conftest.py`, `backend/tests/api/*.py` y `backend/tests/` (nuevos tests de permisos/migración si aplica) | Fixtures sin contraseña y cobertura HTTP/servicios para matriz, filtros, propiedad, migración y OpenAPI/denegaciones. | AC-6…AC-16 |
| `frontend/src/app/core/guards/role.guard.ts` | Implementar comparación de rol local, espera de identidad y resultado de denegación. | AC-1…AC-5, AC-15 |
| `frontend/src/app/core/guards/role.guard.spec.ts` | Tests de roles exactos, estado de carga, rol inválido y navegación denegada. | AC-1…AC-5, AC-15 |
| `frontend/src/app/core/services/auth.service.ts` | Exponer estado de carga/identidad suficiente para que el guard espere sin repetir `/auth/me`. | AC-2, AC-4, AC-15 |
| `frontend/src/app/app.routes.ts` y rutas de features | Asociar rol(es) permitidos; conservar sesión, login, raíz y rutas públicas. | AC-2…AC-5, AC-15 |
| `frontend/src/app/features/` vistas/rutas existentes | Ocultar/desactivar capacidades operativas no autorizadas y presentar denegación dedicada donde corresponda. | AC-2, AC-3, AC-5, AC-15 |
| `frontend/src/app/features/` vista de acceso denegado (nueva si no existe) | Mensaje accesible de permiso insuficiente, sin cerrar sesión ni redirigir a login. | AC-2, AC-15 |
| `frontend/src/app/app.component.ts` / `.html` | Agregar navegación al estado dedicado sin cambiar el flujo de sesión o identidad existente. | AC-2, AC-4 |
| `frontend/src/app/app.routes.spec.ts`, specs frontend afectados y vista de tickets | Cubrir matriz de rutas, guard, estado de denegación, espera de identidad/rol y ocultación de controles operativos. | AC-1…AC-5, AC-15 |
| `database/01_esquema.sql` y `database/02_datos_semilla.sql` | Omitir `password` en instalación nueva y retirar comentarios falsos sobre autenticación. | AC-11, AC-12 |
| `database/03_migracion_retiro_password.sql` (nuevo; nombre final sujeto a orden alfabético) | Migración explícita, versionada e idempotente para base ya inicializada. | AC-13, AC-16 |
| `docs/spec/stack.md`, `docs/spec/roadmap.md`, `docs/spec/features/007-control-acceso-roles/spec.md`, `MEMORY.md`, `AGENTS.md`, `.agents/skills/**` | Solo en cierre: actualizar arquitectura/estado/evidencia, AC y referencias realmente obsoletas; roadmap únicamente tras verificación completa. | AC-11, AC-17 |

## Enmienda de autoatribución de tickets (22/Oct/2026)

> Plan de cambio posterior al cierre, limitado a AC-6 actualizado y AC-18…AC-20. La matriz de permisos y toda la autorización no relacionada con la atribución permanecen cerradas/intactas.

### Decisiones técnicas por capa

- **Schema:** `TicketCrear.usuario_id` se hace opcional. Si se recibe se ignora silenciosamente, incluso si es ajeno o inexistente; no se deja que FastAPI ni servicio lo conviertan en 422/403/404. Mantener `TicketDespacho.usuario_id` requerido porque es otro contrato y no forma parte de la enmienda.
- **Servicio y precedencia:** identidad ya autenticada y rol autorizado continúan siendo resueltos por los mecanismos existentes. En `crear_ticket`: 1) reemplazar incondicionalmente el usuario de entrada por `identidad.usuario.usuario_id`; 2) resolver institución efectiva de sesión y la institución de ese usuario; 3) validar prioridad/estado; 4) validar productos respecto de esa institución (404 por producto ajeno se mantiene); 5) resolver sede desde `departamento.sede_id` de la identidad (409 si no existe/no resoluble); 6) validar reglas restantes del estado inicial y escribir cabecera/detalles/historial transaccionalmente. Ninguna validación, consulta o autorización toma como fuente `payload.usuario_id`.
- **Identidades sin sede:** se aplica 409 a cualquier rol con permiso vigente cuyo departamento no tenga sede resoluble, incluyendo Administrador/Bodeguero; no fallback a `usuario.sede_id`. La semilla de `02_datos_semilla.sql` actualmente tiene sede departamental para Admin roles 2 (usuarios 1/3/4/10) y Bodeguero rol 3 (6/7/12); las sedes en `usuario.sede_id` de bodegueros 6/7/12 no sustituyen ese vínculo.
- **API y matriz:** sin cambio de ruta, permiso, rol autorizado, status exitoso ni contrato de listado. OpenAPI deberá anunciar `usuario_id` opcional/ignorado y no justificar 404 de solicitante payload. Superadmin mantiene 403.
- **Frontend aunque la feature 007 no era dueña original del modal:** su contrato exige UI congruente; el trabajo compartido se implementa en tickets: `AutenticacionService.identidad()` entrega `IdentidadAutenticada` con `nombre`, `apellido`, `correo` (también `usuario_id`, `sub`, `rol`, `institucion`), sin departamento. Se pinta nombre + apellido y correo como identificador, solo informativo; no llamada adicional. El formulario omite `usuario_id` del body; no usa el catálogo como autoridad. `solicitantes` se conserva en GET catálogo para listados/detalle.

### Archivos de la enmienda

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/ticket_schema.py` | Opcionalidad del campo de alta, manteniendo intacto DTO de despacho. | AC-6, AC-18 |
| `backend/app/services/ticket_service.py` | Autoatribución para los roles autorizados y ámbito de sesión; conservar productos/sede/ACID. | AC-6, AC-18, AC-20 |
| `backend/app/api/v1/endpoints/tickets.py` | Precisión documental en OpenAPI; sin cambio de matriz/ruta/status. | AC-6, AC-18 |
| `backend/tests/api/test_tickets_alcance.py`, `test_tickets_institucional.py`, `test_modal_ticket.py`, `test_ticket_sede_011.py`, `test_transaccion_ticket.py` y cualquier test de alta encontrado con grep | Reescribir expectativas antiguas de payload autor; mantener test de despacho y casos de producto ajeno. | AC-6, AC-18, AC-20 |
| `frontend/src/app/features/tickets/tickets.component.ts`, `.html`, `.spec.ts`, `frontend/src/app/shared/interfaces/index.ts` | Campo de autor informativo de identidad, sin selector/control, body omite usuario_id, contrato opcional. | AC-19 |

### TDD, orden y pruebas

La enmienda es un solo cambio transversal; `008/tasks.md` es el único orquestador con las tareas E22-1 backend → E22-2 frontend → E22-3 regresión → E22-4 verificación/cierre. Las secciones E22 de 003 y 007 enlazan esas tareas y registran su AC, no crean ejecución paralela.

1. **Rojo backend:** reemplazar el test histórico del `usuario_id` obligatorio (eliminado); actualizar `test_administrador_crea_para_solicitante_propio_201`, `test_solicitante_crea_y_se_atribuye_su_identidad`, `test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`. Afirmar ausencia/valor propio/ajeno/inexistente e identidad resultante. Cubrir Administrador y Bodeguero, autoría e institución/sede de sesión, 409 sin sede sin escrituras y producto ajeno 404.
2. **Verde servicio/schema y OpenAPI:** opcionalidad de entrada y orden de validaciones anterior a escritura; actualizar solo expectativas vencidas. Mantener intactos tests de matriz, Superadmin 403, propiedad/listado, PATCH/despacho 403 y aislamiento de otras operaciones.
3. **Rojo/verde Angular:** pruebas de `tickets.component.spec.ts`: eliminar `formulario.controls.usuario_id.setValue(5)`, expectativa de cuerpo con campo y expectativas del selector; añadir identidad visible y ausencia de selector/campo, y conservar catálogo de solicitantes para las vistas. No solicitar `/auth/me` desde modal: usar signal existente.
4. **Tests a conservar explícitamente:** `test_crear_ticket_con_producto_ajeno_404_sin_parcial`; `test_crear_ticket_puebla_institucion_en_ticket_y_detalle` (adaptar solo para afirmar anclas respecto de identidad); despacho sigue requiriendo el campo de actor propio de `TicketDespacho`.
5. **Verificación:** `pytest` SQLite y gated PG16 pertinente; frontend `ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` configurado a Edge. Inspeccionar `/openapi.json`. Nunca ejecutar `npm test`.

### Riesgos y alcance no tocado

| Riesgo | Mitigación |
|---|---|
| AC-11 de 008 sigue esperando 404 por usuario ajeno | La tarea transversal actualiza esas expectativas y confirma 404 para producto ajeno separado. |
| Pruebas heredadas afirman `usuario_id` obligatorio para Admin/Bodeguero | Buscar todos los POST de alta que mandan el campo; probar omisión y valores inválidos/ajenos ignorados, sin alterar payload de despacho. |
| Rol autorizado sin sede departamental | 409 de servicio previo a cualquier escritura; pruebas por rol y sin fallback a sede del usuario. |
| UI aún ofrece autor alternativo o desaparece el catálogo | Test DOM comprueba campo read-only y no-select; GET catálogo conserva `solicitantes`. |
| Evidencia de AC-6/15 describe semántica antigua | Reescritura de evidencia solo en implementación/cierre, no declarar verificación aquí. |

Sin cambios a la matriz, guards, autenticación Clerk, DDL/modelos, dependencias, catálogo `solicitantes` como read model, Superadmin 403, reglas de producto, prioridad/estado, transacción, historial o despacho.

### Trazabilidad de enmienda AC ↔ componentes

| AC | Componentes |
|---|---|
| AC-6 actualizado | schema, servicio, tests backend, OpenAPI; conserva autorización/propiedad/matriz |
| AC-18 | servicio, tests API por rol/institución y conservación de 404 por producto |
| AC-19 | UI compartida de tickets y tests Angular |
| AC-20 | servicio, tests de sede con/sin asignación y no mutación |

Los paths de documentación del cierre son condicionales a que la revisión encuentre referencias obsoletas o cambios de arquitectura permanentes; el implementador no altera requisitos aprobados, salvo registrar evidencia al cierre conforme al flujo SDD.

## 3. Decisiones técnicas

### 3.1 Dependencia de rol sobre la identidad Clerk local

La dependencia de autorización depende de `get_current_user`, no vuelve a validar Clerk ni consulta una identidad paralela. Recibe los roles permitidos como parámetro de fábrica/declaración y compara el nombre local exacto. La identidad inyectada al endpoint/servicio se obtiene de la misma dependencia para evitar doble resolución en una petición (FastAPI cachea dependencias equivalentes) y permite mantener la lógica HTTP ligera.

**Alternativa descartada:** validar rol dentro de cada endpoint de forma manual, porque duplica política y facilita omisiones; también se descarta reutilizar rol/claims de Clerk porque Feature 006 establece el rol local como fuente.

### 3.2 Matriz central por operación y filtros en servicios

Una matriz central expresa permisos por operación, con las excepciones específicas reflejadas en rutas/servicios. La dependencia aplica permiso general; los servicios aplican alcance de datos, atribución y ocultación 404 porque estas reglas necesitan entidad/contexto de base de datos y deben preceder a mutaciones.

**Alternativa descartada:** roles amplios por router o permisos por nombre de pantalla: no representan diferencias de método HTTP, filtrado, rol asignable y ticket ajeno exigidas por D-3.

### 3.3 Servicio recibe identidad, no solo `usuario_id`

Pasar `IdentidadAutenticada` a los servicios que operan con permisos/datos limitados; el servicio resuelve con ORM las relaciones departamento/institución y rol según sea necesario. No enviar flags de confianza (`es_superadmin`, institución elegida por cliente) desde frontend ni aceptar el `departamento_id` del solicitante como fuente de alcance.

**Alternativa descartada:** calcular institución en frontend/endpoint y pasarla como dato confiable, pues abre bypass y mezcla regla de dominio con transporte.

### 3.4 Filtros ORM sin alterar contrato de catálogo global

Aplicar filtros de institución usando joins explícitos por Departamento para inventario/movimientos/tickets/usuarios. Los filtros agregados se llevan a las consultas Core/ORM existentes; conservar `stock_total` global en `GET /tickets/catalogos` y `GET /inventario/existencias` salvo el filtro de departamento ya solicitado/regulado, sin presentar el agregado de catálogo como valor institucional. Departamentos ajenos explícitos dan 403, no una lista vacía.

**Alternativa descartada:** particionar producto/categoría o cambiar el significado de `stock_total` en esta entrega; eso contradice el límite aprobado que asigna ese trabajo a 008.

### 3.5 Migración SQL idempotente y aplicable a volumen existente

Mantener DDL base limpio para volúmenes nuevos y un script numerado posterior a `02_datos_semilla.sql`, con `DROP COLUMN IF EXISTS`, diseñado para ejecutar tanto manualmente en una instancia ya creada como en una instalación nueva si se invoca explícitamente. Incluir comando `docker exec ... psql ... -v ON_ERROR_STOP=1` en instrucciones del script/tarea. Verificar en PostgreSQL 16; tests SQLite cubren el resto del backend, no demuestran semántica del DDL PostgreSQL.

**Alternativa descartada:** modificar solo `01_esquema.sql`, que no se vuelve a ejecutar en volúmenes existentes; usar initdb para la migración, que tampoco se ejecuta en esos volúmenes; resetear volumen, que perdería datos y está expresamente prohibido.

### 3.6 Sin dependencia nueva; TDD y validación por ambas suites

Usar FastAPI `Depends`, SQLAlchemy ORM/Core tipado y el harness actual; Angular signals y guards standalone ya instalados. Backend: `pytest` con pruebas HTTP por roles y servicios; frontend: `ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` configurado a Edge en esta máquina. PostgreSQL 16 real para idempotencia y preservación de migración; `/openapi.json` para seguridad/status/contratos. No añadir paquetes.

**Alternativa descartada:** incorporar motor genérico de políticas/ACL o migrador nuevo, innecesario para la matriz fija de cuatro roles y sin justificación de dependencias.

## 4. Estrategia de integración y riesgos

Orden de integración: (1) tests backend de dependencia/matriz y 401/403; (2) contexto/ámbito institucional y pruebas de servicios; (3) atribución/propiedad/creación y transición/despacho conservando ACID; (4) retiro ORM/schema/fixtures y migración PostgreSQL; (5) guard y vistas Angular con tests; (6) regresión completa y contrato OpenAPI; (7) verificación manual 4200 y build/smoke 8080; (8) evidencia por AC y coherencia documental.

Riesgos principales: cobertura incompleta entre los 18 endpoints de D-3; fuga por rutas directas pese al guard; consultas de instituciones sin resolver tratadas erróneamente como globales; filtrar solo lista pero no mutación por id; que Solicitante seleccione `usuario_id` o enumere solicitantes ajenos; pérdida de atomicidad al añadir control pre-despacho; discrepancia PostgreSQL/SQLite; y falso resultado al probar 8080 sin reconstruir. Mitigación: pruebas parametrizadas para cada endpoint/rol, pruebas de no mutación, tests con instituciones/departamentos cruzados, pruebas PostgreSQL para migración, y cierre condicionado a evidencia real en los dos puertos.

## 5. Cobertura AC → piezas

| AC | Pieza principal |
|---|---|
| AC-1 | Literales/matriz backend y guard Angular exactos; pruebas de rol ausente/desconocido. |
| AC-2 | `RolGuard`, denegación dedicada, rutas y tests de navegación/espera. |
| AC-3 | Configuración de rutas/capacidades de dashboard, inventario y tickets/administración; pruebas por rol. |
| AC-4 | `AutenticacionGuard` conservado y regresión de redirección a login con retorno. |
| AC-5 | Tabla de rutas de UI, guard sesión+rol y prueba de rutas públicas/raíz. |
| AC-6 | Servicio/endpoints de tickets: propiedad, atribución, 403 general y 404 oculto. |
| AC-7 | Permisos Bodeguero, filtros institucionales, prohibición usuarios/productos y mutaciones no autorizadas. |
| AC-8 | Filtros de institución, resolución departamento/institución, parámetro ajeno y acceso global exclusivo. |
| AC-9 | Matriz backend completa, 401/403/404, catálogo global y filtro de solicitantes. |
| AC-10 | Regla de rol asignable en creación de usuario sin mutación al denegar. |
| AC-11 | DDL/semilla/docstrings corregidos. |
| AC-12 | Modelo, schema y fixtures sin contraseña; revisión de referencias/runtime. |
| AC-13 | Migración PostgreSQL idempotente con preservación de datos y relaciones. |
| AC-14 | Suite integrada sin consultas/uso de `usuario.password`; Clerk y operaciones funcionales. |
| AC-15 | Pruebas backend/frontend y OpenAPI de denegaciones. |
| AC-16 | Verificación de migración en PostgreSQL y suites completas verdes. |
| AC-17 | Evidencia por AC, OpenAPI, recorrido 4200 y 8080 reconstruido, grep de coherencia. |
