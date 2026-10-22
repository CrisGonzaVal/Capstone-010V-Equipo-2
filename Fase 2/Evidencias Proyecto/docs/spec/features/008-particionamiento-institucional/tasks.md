# Feature 008 — Tareas

Spec: [`spec.md`](spec.md) · Plan: [`plan.md`](plan.md)

> Ejecutar en orden. Las tareas de cierre permanecen sin marcar hasta obtener evidencia real. Cualquier conflicto entre el código y la spec aprobada detiene la implementación y se consulta; no se reduce el alcance de los AC.

## Tareas de implementación

- [x] **T1 — Justificar evolución del modelo en stack.md**
  - Archivos: `docs/spec/stack.md`.
  - Documentar pertenencia institucional, relaciones compuestas y compatibilidad del modelo vigente de 12 entidades antes de alterar modelos/DDL.
  - **AC:** AC-1…AC-4, AC-14, AC-20.
  - **Verificación:** revisión de stack confirma justificación concreta, sin autorizar entidades/cambios no incluidos en la spec.
  - **Hecho cuando:** la sección explica las claves/referencias y la razón del cambio, lista para implementar DDL/modelos.

- [x] **T2 — Definir modelos y DDL de instalación nueva**
  - Archivos: `backend/app/models/producto.py`, `inventario.py`, `ticket.py`, `institucion.py`, registro de modelos si aplica; `database/01_esquema.sql`.
  - Mapear institución en categoría/producto; conservar PK actuales y establecer restricciones/relaciones compuestas para categoría-producto, departamento-inventario-producto y usuario-ticket-detalle-producto.
  - **AC:** AC-2, AC-4, AC-14, AC-20.
  - **Verificación:** `pytest` de persistencia/modelos y creación completa del esquema PostgreSQL 16; inserciones cruzadas rechazadas.
  - **Hecho cuando:** esquema limpio crea constraints correctas y las relaciones inválidas fallan sin datos parciales.

- [x] **T3 — Implementar migración institucional idempotente**
  - Archivos: `database/98_migracion_particionamiento_institucional.sql` (nuevo).
  - Detectar ambigüedad antes de DDL destructivo; abortar identificando entidad/ID; permitir corrección manual y reintento; preservar IDs y filas. Documentar en comentarios el comando `psql ... -v ON_ERROR_STOP=1` y validaciones.
  - **AC:** AC-14, AC-15, AC-18, AC-20.
  - **Verificación:** correr sobre snapshot PostgreSQL 16 legado válido, ejecutar dos veces; caso ambiguo con rollback, corrección manual y reintento exitoso. Comparar IDs/conteos/datos operativos antes/después.
  - **Hecho cuando:** las tres rutas (normal, segunda ejecución, ambigua corregida) están documentadas con salida y comparación de datos, sin reset de volumen.

- [x] **T4 — Actualizar semilla reproducible multiinstitución**
  - Archivos: `database/02_datos_semilla.sql`.
  - Mantener las cuatro instituciones; poblar al menos dos con departamentos, usuarios, catálogo, stock, movimientos y tickets; sembrar categoría/producto homónimos con IDs y stocks distintos, respetando nuevas constraints y secuencias.
  - **AC:** AC-1, AC-3, AC-20.
  - **Verificación:** instalación nueva PostgreSQL 16 con `01` y `02`; consultas de integridad y conteos por institución; segunda ejecución de seed solo en entorno de QA autorizado produce datos reproducibles.
  - **Hecho cuando:** las dos instituciones tienen relaciones completas, homónimos independientes, stock diferenciable y los catálogos de flujo siguen compartidos.

- [x] **T5 — Extender ámbito institucional y ajustar permisos**
  - Archivos: `backend/app/services/ambito_service.py`, `backend/app/core/permisos.py`, tests de permisos/ámbito.
  - Crear helpers compartidos para resolución/validación de pertenencia y actualizar solo escrituras de catálogo, stock/movimientos y tickets: Superadmin solo lectura global; Administrador de la institución autorizado. Mantener 007 en las demás operaciones.
  - **AC:** AC-5, AC-7…AC-10, AC-13, AC-16, AC-18.
  - **Verificación:** `pytest` parametrizado por rol confirma matriz puntual, 401/403, ámbito irresoluble 403, recursos ajenos ocultos donde aplica y cero mutaciones al denegar.
  - **Hecho cuando:** matriz central y helpers tienen cobertura de todos los permisos afectados y ninguna operación no especificada de 007 cambia.

- [x] **T6 — Filtrar catálogos, inventario, movimientos y usuarios**
  - Archivos: `backend/app/services/inventario_service.py`, `usuario_service.py`, `backend/app/api/v1/endpoints/inventario.py`, `usuarios.py`, schemas de producto/inventario si se requiere atribución.
  - Aplicar ámbito antes de listar/serializar; productos/categorías por institución, stock por departamento-institución, movimientos por inventario, agregados globales atribuibles por institución; validaciones en creación de producto/inventario y movimiento.
  - **AC:** AC-2, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-13, AC-16.
  - **Verificación:** `pytest` de endpoints por A/B y roles; objeto ajeno vs inexistente; parámetros de departamento ajeno 403; comprobación de no persistencia.
  - **Hecho cuando:** ningún endpoint presenta datos B a usuario limitado de A y Superadmin identifica cada lectura global por institución.

- [x] **T7 — Aislar tickets, referencias y despacho**
  - Archivos: `backend/app/services/ticket_service.py`, `backend/app/api/v1/endpoints/tickets.py`, schemas ticket afectados.
  - Acotar productos/stock de `/tickets/catalogos`, validar solicitante/productos en creación, ticket ajeno en objeto/estado y relaciones de inventario/producto/ticket antes de despacho; preservar atomicidad, `FOR UPDATE` y auditoría.
  - **AC:** AC-3, AC-4, AC-6, AC-7, AC-9, AC-11, AC-12, AC-16.
  - **Verificación:** `pytest` de alta y despacho válido/cruzado, falta de stock y fallo transaccional; confirmar sin cambios de ticket, detalle, inventario o movimientos cuando se rechaza.
  - **Hecho cuando:** cruces responden códigos estipulados y el despacho válido modifica stock, entrega, estado y auditoría en una sola transacción.

- [x] **T8 — Exponer institución efectiva en /auth/me y documentar OpenAPI**
  - Archivos: `backend/app/services/auth_service.py`, `backend/app/schemas/auth_schema.py`, `backend/app/api/v1/endpoints/auth.py`, pruebas de auth/contrato.
  - Añadir institución derivada para roles limitados y explícitamente nula para Superadmin; mantenerla informativa, nunca entrada de autorización. Actualizar descripciones y respuestas OpenAPI afectadas.
  - **AC:** AC-16, AC-17.
  - **Verificación:** `pytest` para Administrador/Bodeguero/Solicitante/Superadmin; inspección automatizada de `/openapi.json` para response models, status y 401/403/404.
  - **Hecho cuando:** contrato observado coincide con schema para los cuatro roles y Clerk permanece intacto.

- [x] **T9 — Completar tests backend en SQLite y PostgreSQL 16**
  - Archivos: `backend/tests/conftest.py`, `backend/tests/api/test_ambito_institucional.py`, tests API existentes/nuevos para permisos, tickets, inventario y migración.
  - Expandir fixtures a dos instituciones y cuatro roles. Mantener SQLite para suite funcional y aislar tests PostgreSQL para FKs/constraints/migración; no añadir dependencia sin análisis aprobado.
  - **AC:** AC-1…AC-18, AC-20.
  - **Verificación:** `pytest` suite completa verde; PostgreSQL real confirma restricciones y migración; reportar específicamente limitaciones que SQLite no verifica.
  - **Hecho cuando:** tests cubren lecturas, agregados, todas las referencias cruzadas, denegación sin mutación, idempotencia y rollback de ambigüedad.

- [x] **T10 — Actualizar tipos y vistas Angular para contexto institucional**
  - Archivos: `frontend/src/app/shared/interfaces/index.ts`, `frontend/src/app/core/services/auth.service.ts`, features inventario/tickets/dashboard y templates afectados.
  - Consumir el campo de `/auth/me`; mostrar contexto institucional limitado y contexto global de Superadmin; asegurar que vistas limitadas presentan solo las respuestas aisladas del servidor. No crear selector ni tratar el contexto como seguridad.
  - **AC:** AC-8, AC-17, AC-19.
  - **Verificación:** specs de componentes/servicios para contexto A/B y Superadmin; revisión de servicios HTTP para que no envíen institución como autorización.
  - **Hecho cuando:** tipo TypeScript refleja exactamente el DTO backend y la UI evidencia institución efectiva o contexto global sin selector.

- [x] **T11 — Completar tests frontend y suites integradas**
  - Archivos: specs Angular existentes de auth, inventario, tickets y dashboard.
  - Añadir casos para identidad con institución/null, visualización y no mezcla de datos; conservar guards/capacidades de 007.
  - **AC:** AC-19, AC-21.
  - **Verificación:** `npx ng test --watch=false --browsers=ChromeHeadless` (Edge vía `CHROME_BIN` si aplica) y `pytest` completos en verde.
  - **Hecho cuando:** las dos suites pasan sin paquetes nuevos y los casos de UI cubren ámbito limitado y global.

## Checks de cierre

- [x] **T12 — Verificar contrato y evidencia AC-1…AC-18/AC-20**
  - Archivos: ninguno de código; registrar resultados en `spec.md` solo después de comprobación.
  - **AC:** AC-1…AC-18, AC-20.
  - **Verificación:** consolidar salida pytest, evidencia PostgreSQL 16 de migración y constraints, `/openapi.json`, comparaciones de no mutación, esquema nuevo y semilla. Marcar individualmente cada AC aplicable con evidencia concreta en `spec.md`.
  - **Hecho cuando:** todos esos AC tienen resultado reproducible vinculado a prueba/comando/recorrido; ningún AC se marca por inferencia.

- [x] **T13 — Suites y recorrido funcional en 4200 con escritura real**
  - Archivos: ninguno salvo evidencia en `spec.md`.
  - **AC:** AC-18, AC-19, AC-21.
  - **Verificación:** ejecutar `pytest` y `npx ng test --watch=false --browsers=ChromeHeadless`; recorrer en 4200 dos instituciones, lectura del catálogo/stock, alta de ticket y despacho real persistidos; probar Superadmin lectura global y denegación de escritura y capturar contexto `/auth/me`.
  - **Hecho cuando:** suites verdes y evidencia reproducible del flujo real en A/B y permisos, sin datos de B en sesión A.

- [x] **T14 — Reconstruir y recorrer humo en 8080**
  - Archivos: ninguno salvo evidencia en `spec.md`.
  - **AC:** AC-19, AC-21.
  - **Verificación:** ejecutar `docker compose -f docker-compose.yml build frontend` y después `docker compose -f docker-compose.yml up -d frontend`; comprobar la imagen reconstruida muestra contexto, rutas Angular y navegación básica.
  - **Hecho cuando:** el humo se realizó después de la reconstrucción y quedó anotado; no se usa una imagen previa como evidencia.

- [x] **T15 — Cierre documental, AC-21 y MEMORY.md**
  - Archivos: `docs/spec/features/008-particionamiento-institucional/spec.md`, `docs/spec/features/008-particionamiento-institucional/tasks.md`, `MEMORY.md`; revisar `AGENTS.md` y `.agents/skills/` (modificar solo `docs/spec/**` dentro de esta tarea de planner; cambios fuera corresponden al implementador/coordinador con permiso).
  - Grep de coherencia para referencias/rutas y estado del proyecto; actualizar memoria al completar. Registrar AC-19/AC-21 con los recorridos/suites y evidencia; no cambiar roadmap a cerrada hasta satisfacer AGENTS §8.
  - **AC:** AC-21.
  - **Verificación:** revisión de casillas/evidencias, grep documental registrado, memoria concisa y referencia a resultados de 4200/8080.
  - **Hecho cuando:** todas las tareas precedentes están `[x]`, cada AC está marcado con evidencia, ambas suites y los dos recorridos están verificados, y la documentación no contiene afirmaciones/rutas obsoletas.

---

## Enmienda de autoatribución de tickets (22/Oct/2026)

> Esta es la única lista ejecutable para el cambio transversal de las Features 003/007/008. Ejecutar estrictamente E22-1 → E22-2 → E22-3 → E22-4, sin paralelismo. Las secciones E22 de `003/tasks.md` y `007/tasks.md` son trazabilidad de AC, no duplicados de tareas. Tareas históricas T1…T15 no se renumeran.

- [x] **E22-1 — Backend: pruebas rojas, schema, servicio y contrato**
  - **Archivos:** `backend/app/schemas/ticket_schema.py`, `backend/app/services/ticket_service.py`, `backend/app/api/v1/endpoints/tickets.py`; `backend/tests/api/test_tickets_alcance.py`, `test_tickets_institucional.py`, `test_modal_ticket.py`, `test_ticket_sede_011.py`, `test_transaccion_ticket.py` y demás tests de POST alta encontrados por grep.
  - **Primero rojo:** reemplazar el test histórico del `usuario_id` obligatorio (eliminado); reescribir `test_administrador_crea_para_solicitante_propio_201`, `test_solicitante_crea_y_se_atribuye_su_identidad`, `test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`, `test_departamento_sin_sede_ignora_usuario_sede_id_y_responde_409` y `test_ticket_guarda_la_sede_del_departamento_no_la_del_usuario`. Afirmar rol autorizado con `usuario_id` omitido, propio, ajeno e inexistente: 201 y autoría de la identidad autenticada; `ticket.institucion_id` y detalles se anclan a institución de sesión. Cubrir departamento sin sede → 409 y ninguna fila, y producto ajeno → 404 sin parcial.
  - **Implementación/orden obligatorio:** autoatribución incondicional primero (ignorar campo entrante); resolver institución del usuario de sesión; verificar prioridad/estado; verificar todos los productos para esa institución (404 producto ajeno intacto); resolver sede del departamento autenticado (409 si no resoluble); reglas restantes de estado inicial; escribir cabecera/detalles/historial transaccionalmente. No validar payload.usuario_id como referencia y no usar `usuario.sede_id` como fallback. Superadmin mantiene 403 por matriz.
  - Mantener `test_crear_ticket_con_producto_ajeno_404_sin_parcial` y `test_crear_ticket_puebla_institucion_en_ticket_y_detalle`; en `test_ticket_sede_011.py` actualizar exclusivamente altas, no despachos. `TicketDespacho.usuario_id` queda como contrato distinto y obligatorio.
  - **AC:** 003 AC-33/35; 007 AC-6 actualizado/18/20; 008 AC-11.
  - **Hecho cuando:** tests HTTP demuestran las cuatro variantes de payload sin 422/403/404 por usuario; autoría/institución son de sesión; sede ausente 409 sin ticket/detalle/historial; producto ajeno 404; OpenAPI declara optional/ignored y no 404 por usuario; matriz no varía.
  - **Comando:** `backend\.venv\Scripts\python.exe -m pytest backend\tests\api\test_tickets_alcance.py backend\tests\api\test_tickets_institucional.py backend\tests\api\test_modal_ticket.py backend\tests\api\test_ticket_sede_011.py backend\tests\api\test_transaccion_ticket.py -q`.

- [x] **E22-2 — Frontend: identidad informativa y body sin autor**
  - **Archivos:** `frontend/src/app/features/tickets/tickets.component.ts`, `.html`, `.spec.ts`, `frontend/src/app/shared/interfaces/index.ts`.
  - **Rojo:** retirar set `formulario.controls.usuario_id.setValue(5)`, expectativa `usuario_id` incluido en cuerpo, pruebas de selector y `solicitantes().length` como selector. Añadir cobertura de nombre/apellido/correo de identidad, ausencia de `<select>`/control editable y ausencia de llamada extra/departamento.
  - Implementar el campo de solo lectura desde `AutenticacionService.identidad()`. Contrato real de `IdentidadAutenticada`: `nombre`, `apellido`, `correo`, más `usuario_id`, `sub`, `rol`, `institucion`; **no** departamento. Omitir por completo `usuario_id` del cuerpo. Mantener `solicitantes` de `GET /tickets/catalogos` y sus usos de lectura.
  - **AC:** 003 AC-34/35; 007 AC-19; 008 AC-11.
  - **Hecho cuando:** tests del DOM y HTTP pasan y afirman el autor informativo correcto, no selector/control, body sin usuario_id, catálogo de lectura no retirado y el resto del formulario intacto.
  - **Comando:** `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless` (nunca `npm test`).

- [x] **E22-3 — Regresión completa e inventario de payloads**
  - **Archivos:** tests de alta de ticket encontrados con `grep -rn "usuario_id" backend/tests/api/` (incluidos `test_ticket_sede_011.py` y `test_transaccion_ticket.py`) y `tickets.component.spec.ts`.
  - Auditar cada `usuario_id` de petición HTTP para distinguir alta de ticket de despacho; los payloads `TicketDespacho.usuario_id` no se actualizan. Reescribir todas las aserciones incompatibles listadas en E22-1 y comprobar que ningún test de alta sigue esperando 404/obligatoriedad o atribución al payload. Mantener los dos tests explícitamente conservados en E22-1. Revisar `GET /tickets/catalogos`: responde la misma clave/lista `solicitantes`; su contrato no cambia. En `test_ticket_sede_011.py` adaptar el helper/casos de alta, incluida creación sin sede, pero conservar íntegros los POST de despacho y sus payloads.
  - **AC:** AC-33…AC-35; 007 AC-6/18–20; 008 AC-11.
  - **Hecho cuando:** grep completo queda inventariado; pruebas de autorización/matriz y Superadmin 403, producto ajeno 404, transacción, catálogo/listados/detalle, sede y despacho continúan verdes; no queda test heredado con expectativa obsoleta.
  - **Comandos:** `backend\.venv\Scripts\python.exe -m pytest`; `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless`.

- [x] **E22-4 — Verificación integrada, evidencia y memoria**
  - **Archivos:** evidencia de AC en las tres `spec.md` (solo tras verificación), `MEMORY.md`; inspección grep de `AGENTS.md`, `MEMORY.md`, `.agents/skills/`; roadmap condicional.
  - Ejecutar suite backend completa y pruebas gated PostgreSQL aplicables sin usar `apt_erp` como base temporal; suite frontend completa y build de producción; inspeccionar `/openapi.json`; realizar recorrido funcional 4200 con una identidad autorizada y alta real; reconstruir imagen frontend y humo en 8080 porque el modal cambia. Registrar separado qué demuestra cada puerto y evidencia observada por AC en 003/007/008. Actualizar `MEMORY.md`; roadmap solo se modifica si el coordinador confirma los gates y estado correspondiente.
  - **AC:** AC-33…AC-35; 007 AC-17/18–20; 008 AC-11.
  - **Hecho cuando:** ambas suites y build pasan; recorrido 4200 y humo 8080 posteriores a rebuild documentados; OpenAPI, AC y grep coherentes; memoria actualizada; ninguna casilla se marca como verificada sin resultado observado.
  - **Comandos:** `backend\.venv\Scripts\python.exe -m pytest`; `$env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"; backend\.venv\Scripts\python.exe -m pytest` (solo gated desechable configurado); `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless; npx ng build`; `docker compose -f docker-compose.yml build frontend` y `docker compose -f docker-compose.yml up -d frontend`.

### Cierre de enmienda

- [x] **E22-C1 — Suites y contrato.** **AC:** enmienda completa. **Hecho cuando:** SQLite y pruebas gated PostgreSQL aplicables pasan, `ng test` con Edge y build están verdes; `/openapi.json` refleja usuario opcional, matriz intacta y 404 por producto vigente.
- [x] **E22-C2 — Recorridos.** **AC:** 003 AC-34, 007 AC-19, 008 AC-11. **Hecho cuando:** 4200 confirma identidad/cuerpo sin `usuario_id` y alta real; 8080 confirma modal en build reconstruido/humo básico; evidencia distingue recorrido funcional y humo.
- [x] **E22-C3 — Evidencia, memoria y coherencia.** **AC:** 003 AC-33…35, 007 AC-17…20, 008 AC-11. **Hecho cuando:** evidencia observada queda bajo los AC afectados de las tres specs; `MEMORY.md` actualizado; grep de coherencia registrado; roadmap únicamente se cambia tras gates completos.


### Matriz de trazabilidad AC ↔ tareas

| AC de enmienda | Tareas |
|---|---|
| 003 AC-33 | E22-1, E22-3, E22-4, E22-C1, E22-C3 |
| 003 AC-34 | E22-2, E22-3, E22-4, E22-C2, E22-C3 |
| 003 AC-35 | E22-1…E22-4, E22-C1…C3 |
| 007 AC-6 actualizado | E22-1, E22-3, E22-4, E22-C1 |
| 007 AC-17/AC-18 | E22-1, E22-3, E22-4, E22-C1, E22-C3 |
| 007 AC-19 | E22-2, E22-3, E22-4, E22-C2, E22-C3 |
| 007 AC-20 | E22-1, E22-3, E22-4, E22-C1, E22-C3 |
| 008 AC-11 | E22-1…E22-4, E22-C1…C3 |
