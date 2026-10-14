# Feature 007 — Tasks

**Spec:** [`spec.md`](spec.md) · **Plan:** [`plan.md`](plan.md)

Tareas en orden de dependencia; cada bloque debe mantener TDD para comportamiento observable. No marcar una tarea sin satisfacer `Hecho cuando:` y registrar evidencia concreta. Máximo 15 tareas. `[!]` significa bloqueada e indica el impedimento.

Verificación habitual:
- Backend: `cd backend && .venv\\Scripts\\python.exe -m pytest`
- Frontend: `$env:CHROME_BIN = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`
- Migración: PostgreSQL 16 real; los tests SQLite en memoria no acreditan ejecución/idempotencia del DDL PostgreSQL.

---

## Bloque A — backend-authz

### T1 — Fijar política central y dependencia de autorización (AC-1, AC-9, AC-15)

- [x] Antes de implementación, escribir pruebas de dependencia para cada rol conocido, rol desconocido/ausente, autenticación ausente/inválida, rol no autorizado y autorizado; definir literal exacto de los cuatro roles y matriz operacional central conforme a D-3. Añadir la dependencia de rol basada en `get_current_user`; preservar 401 y hacer 403 para denegación autenticada. No introducir alias `Admin`.

**Hecho cuando:** pruebas prueban 401 sin sesión, 403 con sesión sin permiso, permiso concedido solo al rol/método de la matriz y rechazo de rol ausente/desconocido; la identidad Clerk se resuelve una sola vez por solicitud y pytest pasa.

### T2 — Proteger las 18 operaciones y verificar contrato HTTP/OpenAPI (AC-7…AC-10, AC-15)

- [x] Aplicar permiso explícito a todas las operaciones de la matriz D-3 (18 endpoints, incluida `/auth/me` ya autenticada y las rutas/catálogos de apoyo); añadir tests parametrizados por operación/rol para permisos y denegaciones. Declarar códigos/documentación 401/403 pertinentes y verificar `/openapi.json`; mantener health/docs públicos.

**Hecho cuando:** el inventario de rutas contrastado con la matriz no deja operaciones sin prueba/autorización; pruebas HTTP validan allow/deny por rol y `/openapi.json` refleja autenticación y errores aplicables sin alterar los contratos de respuesta existentes.

### T3 — Imponer ámbito institucional en servicios de usuarios e inventario (AC-7…AC-9, AC-15)

- [x] Escribir pruebas cruzadas de dos instituciones para Administrador, Bodeguero, Solicitante y Superadmin; aplicar derivación `usuario → departamento → institución` en `usuario_service` e `inventario_service`. Cubrir listados, existencias/stock, movimientos, institución propia, parámetro `departamento_id` ajeno con 403, relación ausente/no resoluble con 403, catálogo categoría/producto compartido y catálogo de solicitantes según rol.

**Hecho cuando:** ningún rol limitado puede leer/modificar datos institucionales ajenos ni obtiene alcance global ante vínculo faltante; Superadmin conserva alcance global; tests demuestran catálogo maestro global y filtros correctos de solicitantes.

### T4 — Imponer propiedad, atribución y ámbito institucional en tickets (AC-6…AC-9, AC-15)

- [x] Escribir pruebas de listado propio, ticket ajeno e inexistente ambos 404 para operaciones permitidas, 403 general para acciones prohibidas, creación atribuida al Solicitante aunque envíe otro `usuario_id`, y contrato `TicketCrear` con `usuario_id` obligatorio para los otros roles. Aplicar filtros al listar, validar institución de solicitantes para Administrador/Bodeguero y comprobar ámbito antes de PATCH/despacho, sin romper la transacción de despacho.

**Hecho cuando:** tests cubren lectura y mutación por id sin fuga entre instituciones, id ajeno/no existente ocultos para Solicitante, denegación sin cambios de filas y atribución correcta; tests de despacho transaccional existentes y nuevos siguen verdes.

### T5 — Restringir rol asignable en alta de usuario (AC-8, AC-10, AC-15)

- [x] Probar `POST /usuarios/` para Administrador con Bodeguero/Solicitante y con Superadmin/Administrador; verificar 403 y cero creación para los dos roles prohibidos. Probar Superadmin con los cuatro roles y límite institucional del Administrador; implementar la regla en servicio, no en el router.

**Hecho cuando:** tests HTTP/servicio verifican altas permitidas, denegaciones 403 sin mutación y no regresión del contrato de creación salvo retiro de contraseña en T7.

## Bloque B — base de datos y retiro de password

### T6 — Añadir cobertura y eliminar contraseña de modelo/contrato/fixtures (AC-12, AC-14, AC-15)

- [x] Localizar todos los usos funcionales de `usuario.password`; actualizar primero fixtures y pruebas a usuarios sin credencial local, después retirar atributo de `Usuario` y campo requerido de `UsuarioCrear`. Mantener Clerk como única autoridad, y comprobar `/auth/me`/alta de usuario sin consultar contraseña.

**Hecho cuando:** suite backend no crea ni transmite contraseña local; schema/modelo no publican ese campo y grep de runtime/tests no deja dependencia de `usuario.password` (excepto asserts/documentación intencionales de su ausencia).

### T7 — Limpiar esquema inicial, semilla y comentarios obsoletos (AC-11, AC-12)

- [x] Retirar `password` de `database/01_esquema.sql` y de columnas/valores de usuarios en `database/02_datos_semilla.sql`; corregir comentarios obsoletos de autenticación de semilla y el docstring de `TicketDespacho`. Verificar cantidad/orden de columnas y conservación de los diez usuarios/relaciones de semilla.

**Hecho cuando:** grep de esquema/semilla/modelo/schema/tests no encuentra definición ni valor de contraseña; SQL inicial sigue siendo coherente (mismo número de valores por usuario) y los comentarios descritos por AC-11 están corregidos.

### T8 — Crear y verificar migración idempotente para volúmenes existentes (AC-13, AC-16)

- [x] Añadir script SQL versionado y posterior al orden de init, que retire solo `usuario.password` de forma idempotente. Documentar en el propio script el comando reproducible con `psql`/`docker exec` y `ON_ERROR_STOP=1` para base ya inicializada. Preparar PostgreSQL 16 con usuarios, tickets/relaciones y columna; ejecutar migración, comprobar columna ausente y todos los datos/relaciones preservados, repetir y comprobar éxito. Probar también una instalación limpia.

**Hecho cuando:** evidencia contra PostgreSQL 16 confirma conservación de conteos/IDs/relaciones, eliminación de columna, segunda ejecución sin error y aplicabilidad sin depender de `/docker-entrypoint-initdb.d` en volumen preexistente.

## Bloque C — frontend-guards

### T9 — Implementar RolGuard reactivo y denegación dedicada (AC-1, AC-2, AC-4, AC-15)

- [x] Escribir tests primero para identidad cargando, rol válido permitido, rol distinto, rol ausente/desconocido, sesión Clerk inexistente y denegación a vista dedicada sin login/logout. Implementar el guard sobre identidad local de `AutenticacionService`; esperar estado de identidad sin repetir `/auth/me`; crear/usar estado de acceso denegado accesible.

**Hecho cuando:** la suite frontend demuestra espera correcta, comparación exacta, no activación ante falta de permiso, permanencia de sesión y ausencia de redirección a login en 403 de navegación; guard auth sigue redirigiendo a `/login` con retorno sin sesión.

### T10 — Configurar rutas por rol y limitar capacidades UI (AC-2…AC-5, AC-15)

- [x] Probar y aplicar roles de ruta: dashboard e inventario para los cuatro; tickets para los cuatro con capacidades según rol; administración Superadmin/Administrador. Conservar `/`→dashboard, `/login` libre y `/health` público. Ocultar/desactivar para Solicitante operaciones Kanban/estado/despacho y acceso administrativo; no tratar controles UI como autorización API.

**Hecho cuando:** tests de rutas confirman sesión+rol en las cuatro áreas, capacidades por perfil sin alias, navegación a denegación dedicada, rutas públicas intactas y las acciones no autorizadas no se ofrecen al Solicitante.

## Bloque D — regresión y cierre

### T11 — Matriz integrada, OpenAPI y suites completas (AC-1…AC-16)

- [x] Ejecutar la matriz completa de pruebas de backend por operación/rol incluyendo 401/403/404, no mutación, ámbito, filtro de solicitantes, stock global y rol asignable; ejecutar suites completas `pytest` y `ng test` con Edge/ChromeHeadless, build de producción frontend y revisar `/openapi.json`. Ejecutar grep de credenciales local y confirmar que no se añadió dependencia.

**Hecho cuando:** ambas suites y build están verdes; OpenAPI y tests fijan denegaciones y contratos pertinentes; no hay credenciales/paquetes locales residuales ni regressions del flujo Clerk, tickets, inventario o despacho.

### T12 — Recorridos funcional y de humo con roles diferenciados (AC-2…AC-10, AC-14, AC-17)

- [x] En 4200, recorrer sesión Clerk con al menos un usuario de cada rol y comprobar navegación permitida/denegada, estado dedicado, intento directo API 403, límites institucionales, propiedad de tickets, creación por Solicitante y capacidades de Bodeguero/Administrador/Superadmin. Verificar escrituras reales y ausencia de cambios ante denegación. Reconstruir frontend (`docker compose -f docker-compose.yml build frontend`, luego `up -d frontend`) y repetir en 8080 un recorrido de humo con build nuevo; incluir ruta Angular directa y flujo básico.

**Hecho cuando:** evidencia separa 4200 funcional de 8080 humo, registra versión reconstruida, perfiles probados y respuestas/resultados observables sin incluir secretos.

### T13 — Registrar evidencia por AC y actualizar coherencia documental (AC-11…AC-17)

- [x] Solo tras completar verificaciones, registrar evidencia verificable para AC-1…AC-17 en `spec.md` sin alterar requisitos; actualizar `stack.md` si el patrón de autorización se convierte en norma, `MEMORY.md` y roadmap de acuerdo al estado real. Hacer grep de coherencia sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/` por rutas/afirmaciones obsoletas; corregir únicamente las referencias confirmadas. Incluir prueba de migración y OpenAPI en evidencia.

**Hecho cuando:** cada AC tiene evidencia concreta; `pytest`, `ng test`, `/openapi.json`, PostgreSQL migration test y recorridos 4200/8080 quedan documentados; documentación/grep son coherentes y roadmap solo pasa a cerrada cuando se cumplen AGENTS.md §8.5–§8.7.

---

## Cierre de feature (AC-17)

- [x] **C1 — Suites y build:** backend `pytest`, frontend `ng test --watch=false --browsers=ChromeHeadless` (Edge configurado) y build producción completan sin fallos.
  **Hecho cuando:** se adjuntan comandos y resultados finales. → `cd backend && .venv\Scripts\python.exe -m pytest` = **377 passed, 2 warnings**; `$env:CHROME_BIN=…msedge.exe; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` = **140 SUCCESS** (Edge 155); `ng build` OK (T11, 320.55 kB) reflejado en la imagen de producción reconstruida.
- [x] **C2 — Contrato API:** comprobar `/openapi.json`, seguridad bearer, rutas protegidas y respuestas 401/403 pertinentes.
  **Hecho cuando:** evidencia identifica las operaciones y esquemas revisados. → `/openapi.json` en vivo publica `HTTPBearer` (http/bearer) y cada operación de negocio exige bearer con 401 ("Credenciales ausentes o invalidas…") y 403 ("Identidad autenticada sin el rol requerido…"); `test_permisos_endpoints.py::test_openapi_*` fija el contrato.
- [x] **C3 — Migración PostgreSQL:** verificar instalación limpia y BD existente con segunda ejecución idempotente.
  **Hecho cuando:** usuarios/relaciones permanecen y columna está ausente en ambos escenarios. → En vivo sobre `compustock_db`/`apt_erp`: `usuario` sin `password` (`usuario_id, nombre, apellido, correo, departamento_id, rol_id`) con **12 usuarios/10 tickets** intactos; re-ejecución de `99_migracion_retiro_password.sql` con `ON_ERROR_STOP=1` → `NOTICE: column "password" … does not exist, skipping`, exit 0. Instalación limpia verificada en T8.
- [x] **C4 — Recorridos:** 4200 funcional con escrituras reales y 8080 tras build + `up -d` reconstruido.
  **Hecho cuando:** evidencia de ambos puertos y de perfiles/acciones queda registrada. → T12: 4200 funcional con 4 roles (Solicitante autoatribuido, 403/404, límite institucional del Admin, denegación sin escritura); 8080 humo sobre imagen `sha256:3862981…` (2026-10-14T16:02Z); T13 confirma ruta directa `/acceso-denegado` → 200.
- [x] **C5 — Coherencia y memoria:** grep §8.7; actualizar `MEMORY.md`, `stack.md` si procede y evidencia de spec; roadmap solo al cumplir todo lo anterior.
  **Hecho cuando:** no quedan referencias obsoletas y la documentación coincide con implementación verificada. → evidencia por AC en `spec.md`; `stack.md` §5 documenta el patrón de autorización; `MEMORY.md` actualizado a post-007; grep §8.7 corregido en `AGENTS.md` y `.agents/skills/`; `roadmap.md` 007 cerrada.

### Trazabilidad AC → tareas

| AC | Tareas |
|---|---|
| AC-1 | T1, T2, T9, T10, T11 |
| AC-2 | T9, T10, T12 |
| AC-3 | T10, T12 |
| AC-4 | T9, T10, T11 |
| AC-5 | T2, T10, T11 |
| AC-6 | T2, T4, T11, T12 |
| AC-7 | T2, T3, T4, T10, T11, T12 |
| AC-8 | T2, T3, T4, T5, T11, T12 |
| AC-9 | T1, T2, T3, T4, T11 |
| AC-10 | T2, T5, T11, T12 |
| AC-11 | T7, T13 |
| AC-12 | T6, T7, T11 |
| AC-13 | T8, T11, C3 |
| AC-14 | T6, T11, T12 |
| AC-15 | T1…T11 |
| AC-16 | T8, T11, C1, C3 |
| AC-17 | T12, T13, C1…C5 |
