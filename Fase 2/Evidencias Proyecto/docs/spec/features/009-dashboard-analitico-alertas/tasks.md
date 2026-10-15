# Feature 009 — Tareas

Spec: [`spec.md`](spec.md) · Plan: [`plan.md`](plan.md)

> Ejecutar en orden. Las tareas son acotadas a sesiones de implementación; primero se escriben pruebas observables (TDD) y después se implementan los contratos necesarios. Si el código contradice la spec aprobada o requiere modelo, migración, persistencia de alertas o ampliar permisos del Solicitante, detenerse y consultar.

## Tareas de implementación

- [x] **T1 — Especificar pruebas HTTP de contrato, permisos y casos base**
  - Archivos: `backend/tests/api/test_dashboard_analitico.py` (nuevo), `backend/tests/api/test_permisos_endpoints.py`.
  - Escribir primero casos rojos para GET consolidado, response model/status, sin datos, roles permitidos, Solicitante sin actividad y mantenimiento de 403 en `/inventario/movimientos`; ampliar matriz independiente de referencia.
  - **AC:** AC-10, AC-13, AC-14.
  - **Verificación:** las pruebas nuevas fallan solo por la ruta/contrato todavía inexistentes (no por imports, fixture inválido ni errores de sintaxis).
  - **Hecho cuando:** el conjunto rojo fija ruta, roles, 200/401/403 y el no cambio del permiso vigente de movimientos.

- [x] **T2 — Probar primero reglas de KPI y filas críticas**
  - Archivos: `backend/tests/api/test_dashboard_analitico.py`.
  - Cubrir unidades totales, tickets excluidos solo por nombre literal «Cerrado», departamentos contados por PK incluso sin inventario, filas críticas M-1/M/M+1/min=0, homónimos y ausencia de producto sin inventario.
  - **AC:** AC-1, AC-2, AC-3, AC-4.
  - **Verificación:** pytest rojo por ausencia del servicio/endpoint, con fixtures válidas y expectativas observables por HTTP.
  - **Hecho cuando:** cada borde del conteo está representado por datos semilla diferenciables sin IDs fijos.

- [x] **T3 — Probar primero aislamiento, atribución y cambio de umbral sin alertas persistidas**
  - Archivos: `backend/tests/api/test_dashboard_analitico.py`, `backend/tests/conftest.py` solo si se requieren fixtures reutilizables adicionales.
  - Cubrir dos instituciones, homónimos, filtros de los cuatro roles, ámbito irresoluble 403, lista KPI-alertas idéntica, cruce del umbral por movimiento real y conteo/auditoría sin filas de alerta duplicadas. Comprobar que el escalar global de unidades puede sumar instituciones, y que filas de alerta/actividad conservan atribución.
  - **AC:** AC-5, AC-7, AC-8, AC-11, AC-12, AC-13.
  - **Verificación:** casos rojos con assertions contra respuesta HTTP y conteos auditables; ninguna prueba depende de que SQLite acredite una constraint PostgreSQL no relacionada.
  - **Hecho cuando:** todas las garantías multiinstitución y de ausencia de persistencia tienen una expectativa reproducible.

- [x] **T4 — Probar primero actividad, límite, orden y permiso de Solicitante**
  - Archivos: `backend/tests/api/test_dashboard_analitico.py`.
  - Sembrar movimientos con fechas iguales/distintas y dos instituciones. Verificar los diez más recientes en orden fecha DESC/id DESC, campos de ubicación/institución y 403 directo de Solicitante al historial existente.
  - **AC:** AC-6, AC-7, AC-10.
  - **Verificación:** pytest rojo por endpoint ausente, no por fecha o fixture; prueba directa de movimientos conserva 403 en estado actual.
  - **Hecho cuando:** hay asserts de límite, orden determinista y no exposición a Solicitante.

- [x] **T5 — Definir contrato Pydantic del dashboard**
  - Archivos: `backend/app/schemas/dashboard_schema.py` (nuevo).
  - Implementar DTOs de KPI, fila crítica, movimiento resumido y respuesta consolidada según el plan; tipos explícitos, sin `from_attributes` para datos agregados, listas vacías válidas y nombres en español.
  - **AC:** AC-1, AC-5, AC-6, AC-7, AC-13.
  - **Verificación:** pruebas de serialización/schema y OpenAPI apuntan a los campos y tipos esperados; ningún campo de ticket personal se expone.
  - **Hecho cuando:** el contrato Pydantic representa todas las secciones, institución por fila y `actividad_disponible`.

- [x] **T6 — Implementar el servicio agregado, ámbito y read models**
  - Archivos: `backend/app/services/dashboard_service.py` (nuevo), `backend/app/services/ambito_service.py` y `inventario_service.py` solo si se justifica helper compartible.
  - Implementar `obtener_dashboard_analitico()` con queries SQLAlchemy ORM/Core: resolver ámbito con helper existente; sumar stock; contar tickets por estado literal y alcance vigente; contar departamentos por PK; construir una sola lista crítica con regla por fila; actividad opcional y limitada a 10 para roles autorizados; atribución institucional por fila para Superadmin. Reutilizar `es_stock_critico`; no cambiar endpoints actuales ni persistir alertas.
  - **AC:** AC-1…AC-12.
  - **Verificación:** ejecutar pruebas HTTP T1–T4, probar sin datos/ámbito irresoluble/homónimos y comparar conteo KPI de alertas con la lista. Inspección de queries confirma que el servicio no descarga tickets completos ni tiene n+1 por filas.
  - **Hecho cuando:** la suite de casos de servicio/end-to-end queda verde y no hay SQL raw, lógica de negocio en routers ni lecturas globales por fallo de ámbito.

- [x] **T7 — Publicar endpoint protegido y registrar la operación de matriz**
  - Archivos: `backend/app/api/v1/endpoints/dashboard.py` (nuevo), `backend/app/api/v1/api.py`, `backend/app/core/permisos.py`.
  - Añadir `GET /api/v1/dashboard/`, `DashboardAnaliticoRespuesta`, `200` explícito, descripción OpenAPI, 401/403 documentados y dependencia `requiere_operacion`. Agregar solo la operación dashboard para `_TODOS`; conservar sin cambios la entrada de `GET /api/v1/inventario/movimientos` (Solicitante excluido). Router delgado; delega al servicio.
  - **AC:** AC-8, AC-10, AC-11, AC-13, AC-14.
  - **Verificación:** `pytest` de endpoint/matriz/roles; inspeccionar `/openapi.json` con 200, response model, parámetros inexistentes, 401/403; invocar historial como Solicitante y confirmar 403.
  - **Hecho cuando:** el conjunto de rutas reales y la matriz de referencia independiente coinciden y todos los casos de autorización pasan.

- [x] **T8 — Añadir tipos TypeScript y servicio HTTP tipado**
  - Archivos: `frontend/src/app/shared/interfaces/index.ts`, `frontend/src/app/features/dashboard/services/dashboard.service.ts` (nuevo), `frontend/src/app/features/dashboard/services/dashboard.service.spec.ts` (nuevo).
  - Reflejar el DTO Pydantic en interfaces TypeScript `snake_case` y crear una llamada única `obtenerDashboard()` al endpoint; no enviar institución/departamento ni reutilizar historial de movimientos.
  - **AC:** AC-7, AC-8, AC-13, AC-15.
  - **Verificación:** `HttpTestingController` verifica método/URL/respuesta, ausencia de params, headers de ámbito y body; respuesta con datos se transmite íntegra.
  - **Hecho cuando:** prueba del servicio pasa y tipos reflejan el schema backend sin alias/campos inferidos.

- [x] **T9 — Probar primero la vista de dashboard y estados por rol**
  - Archivos: `frontend/src/app/features/dashboard/dashboard.component.spec.ts` (nuevo).
  - Crear casos de integración standalone con servicio simulado/HTTP testing para KPI/etiqueta exacta, alertas, actividad, placeholder ausente, carga, vacío, error/reintento, Superadmin atribuido y Solicitante sin movimientos ni llamada al endpoint de historial.
  - **AC:** AC-1, AC-5…AC-10, AC-15.
  - **Verificación:** test inicialmente rojo por template/componente aún con datos estáticos y sin service; fixture cubre identidad/roles en el formato del servicio de autenticación.
  - **Hecho cuando:** assertions del DOM y del número de peticiones fijan el comportamiento esperado sin depender de estilo frágil.

- [x] **T10 — Integrar componente y template Angular con datos reales**
  - Archivos: `frontend/src/app/features/dashboard/dashboard.component.ts`, `frontend/src/app/features/dashboard/dashboard.component.html`.
  - Cargar la respuesta consolidada con estado `signal()` para carga/datos/error, valores derivados `computed()` cuando corresponda y reintento. Reemplazar KPI; retirar placeholder de sedes; presentar lista única de alertas; representar actividad solo si `actividad_disponible`; conservar lista vacía explícita para roles autorizados; no mostrar muestras ni solicitudes de movimientos para Solicitante.
  - **AC:** AC-1, AC-5…AC-10, AC-15.
  - **Verificación:** pruebas de componente T9 pasan; template usa Tailwind, estructura accesible y errores con `role="alert"`; compilación Angular sin NgModule ni paquete nuevo.
  - **Hecho cuando:** dashboard responde a DTO y estados sin valores quemados, y no incluye el placeholder ni tráfico histórico para Solicitante.

- [x] **T11 — Ejecutar suites y consolidar pruebas de contrato/regresión**
  - Archivos: backend tests de dashboard/permisos y pruebas frontend del dashboard; fixtures solo si el descubrimiento exige arreglos estrictamente compartidos.
  - Ejecutar suites completas y ajustar únicamente fixtures/contratos afectados; comprobar no regresión en `/inventario/movimientos`, tickets, ámbitos existentes y rutas del dashboard.
  - **AC:** AC-1…AC-15.
  - **Verificación:** `cd backend && pytest`; Edge vía `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"`, luego `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`.
  - **Hecho cuando:** pytest y ng test completos terminan en verde, las pruebas gated PostgreSQL se reportan por separado si `POSTGRES_TEST_URL` está configurado y no quedan regresiones de matriz.

## Checks de cierre

- [x] **T12 — Revisar contrato y registrar evidencia AC-1…AC-15**
  - Archivos: `docs/spec/features/009-dashboard-analitico-alertas/spec.md` (solo evidencia, sin alterar requisitos).
  - Revisar `/openapi.json`, matriz, pytest, ng test, casos de dos instituciones, umbral, 403 Solicitante, no persistencia de alertas, placeholder y estado de error/vacío; registrar evidencia concreta por AC.
  - **AC:** AC-1…AC-15.
  - **Verificación:** evidencia vinculada a test/comando/respuesta/recorrido y no por inferencia; revisión explícita de que Superadmin tiene escalar global único, filas con atribución, departamentos sin inventario contados y movimientos no autorizados a Solicitante.
  - **Hecho cuando:** cada AC aplicable tiene evidencia comprobable y el contrato publicado coincide con DTO y permisos aprobados.

- [x] **T13 — Suites completas y recorrido funcional en 4200**
  - Archivos: ninguno salvo registrar evidencia en spec y actualizar `MEMORY.md` cuando se cierre.
  - Ejecutar suites completas; recorrer el dashboard real en 4200 con Superadmin, Administrador/Bodeguero y Solicitante; contrastar métricas/alertas con datos persistidos, asegurar atribución global, ámbito local, «Unidades en Stock», retiro placeholder y no actividad para Solicitante.
  - **AC:** AC-1…AC-12, AC-15, AC-16.
  - **Verificación:** evidencia de sesión/rol y consultas API/DB no sensibles, salida pytest/ng test y estados UI; verificar además la lectura directa 403 de movimientos para Solicitante.
  - **Hecho cuando:** recorrido funcional contra puerto 4200 y backend actual documenta los casos de rol/ámbito y su correspondencia con datos reales.

- [x] **T14 — Reconstruir frontend y ejecutar humo en 8080**
  - Archivos: ninguno salvo registrar evidencia en spec.
  - Ejecutar `docker compose -f docker-compose.yml build frontend` seguido de `docker compose -f docker-compose.yml up -d frontend`; comprobar build producción, ruta dashboard en nginx y flujo básico con build recién creado.
  - **AC:** AC-15, AC-16.
  - **Verificación:** comprobar que `index.html` y bundles corresponden a la imagen nueva, vista real, KPI/alertas visibles y navegación responde; no reutilizar imagen pre-feature.
  - **Hecho cuando:** la imagen reconstruida sirve el dashboard de la 009 y el humo queda documentado.

- [x] **T15 — Cierre documental, memoria y roadmap condicionado**
  - Archivos: `docs/spec/features/009-dashboard-analitico-alertas/spec.md`, `tasks.md`, `MEMORY.md`, `docs/spec/roadmap.md`; revisión de `AGENTS.md` y `.agents/skills/` según corresponda.
  - Actualizar evidencia AC, todas las casillas de tareas, MEMORY.md y grep de coherencia documental; revisar afirmaciones/rutas al cerrar. Solo marcar Feature 009 `[x]` en roadmap tras completar el resto de verificaciones exigidas por AGENTS §8.5 y recibir validación correspondiente.
  - **AC:** AC-16.
  - **Verificación:** verificar tareas previas `[x]`, evidencia de todos los AC, suites verdes, recorrido 4200/8080, OpenAPI/matriz y resultados de grep en alcance del proyecto.
  - **Hecho cuando:** feature declarada cerrada solo con evidencia integral; `roadmap.md` no se marca antes de cumplir todos los checks.

### Lista de cierre obligatoria

- [x] `pytest` backend completo verde: **540 passed, 0 failed, 5 skipped** (+ gated PostgreSQL **5 passed** con `POSTGRES_TEST_URL`).
- [x] `ng test` frontend completo verde usando Edge, `--watch=false --browsers=ChromeHeadless`: **172 SUCCESS, 0 FAILED**; `ng build` limpio.
- [x] Recorrido funcional en 4200 documentado con datos reales y roles/ámbitos: Administrador 626/5/7/3, Superadmin 646/5/10/3 (atribución multiinstitución), Bodeguero 626/5/7/3, Solicitante 626/0/7/3 sin actividad y 403 en historial.
- [x] Reconstrucción `docker compose -f docker-compose.yml build frontend` + `up -d frontend` y humo 8080 documentados (imagen nueva `sha256:11a287959b12…`; bundles `main-A4LYVLW7.js`/`chunk-S2G2JRYD.js`).
- [x] `/openapi.json` y matriz central revisados; Solicitante conserva 403 en movimientos (`GET /dashboard/` → 4 roles; matriz de 21 operaciones).
- [x] `MEMORY.md` actualizado al terminar la feature, sin superar ~50 líneas ni guardar datos sensibles.
- [x] Grep de coherencia documental en alcance conforme a `AGENTS.md` §8.7 (sin referencias obsoletas tras retirar el placeholder de Sedes).
- [x] `[ ]` → `[x]` en `roadmap.md` (Feature 009) tras cumplir las verificaciones de `AGENTS.md` §8.5 y la validación del reviewer; el coordinator/reviewer valida el cierre.
