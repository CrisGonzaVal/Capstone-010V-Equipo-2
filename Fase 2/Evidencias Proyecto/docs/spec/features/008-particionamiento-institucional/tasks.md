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
