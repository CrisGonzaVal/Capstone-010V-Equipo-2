# Feature 019 — Tareas

Spec: [`spec.md`](spec.md) · Plan: [`plan.md`](plan.md)

> Ejecutar en orden de dependencia y con TDD: pruebas nuevas primero (rojo por comportamiento ausente), implementación después (verde), sin debilitar regresiones. La spec aprobada es fuente de verdad. La consulta solo lee `stock_sede`; el 409 de sede operativa no resoluble precede a cualquier inspección del producto. Matriz 61→62 es una ampliación documentada de 014/018.

## Backend

- [x] **T1 — Fijar primero las pruebas rojas del detalle, ámbito y precedencia.**
  - **Archivos:** nuevo `backend/tests/api/test_detalle_producto_019.py`; se reutiliza `mundo` desde `test_filtros_inventario_018.py`, `dos_instituciones`, `cliente_de_rol`/`sembrar_contexto_capacidades` de `_soporte_ciclo_vida_catalogo_014.py`, y `cliente`/`sesion`/`SIN_AUTENTICAR` de `_soporte_sede_011.py`.
  - Añadir antes de producción casos HTTP de respuesta exacta y suma; orden de sedes; sede inactiva incluida; Administrador con productos/categorías inactivos; operativos con activos únicamente; productos sin stock; rol/tenant limitado; filtros de lista sin efecto; 401/403 matriz/capacidad/institución/409/404 en precedencia; 404 indistinguible; id 0/negativo, no entero 422; Superadmin; y operación sin escritura. La sede `None` debe dar 409 aun con producto inexistente/ajeno/retirado.
  - Mantener el mundo existente sin mover el fixture: importarlo desde el test 018 para evitar refactor a sus consumidores; confirmar que pytest lo descubre y que no hay colisión de nombre/alcance antes de seguir.
  - **AC:** AC-1…AC-7, AC-10…AC-13.
  - **Hecho cuando:** nuevas pruebas fallan por ruta/DTO/servicio ausentes con causas explícitas; no por `ImportError`, setup defectuoso ni cambio de fixtures heredados. **[pytest SQLite]**

- [x] **T2 — Fijar expectativa independiente de autorización, gating y contrato 62.**
  - **Archivos:** `backend/tests/api/test_detalle_producto_019.py`, `backend/tests/api/test_ciclo_vida_autorizacion_014.py`, `backend/tests/api/test_filtros_inventario_018.py`.
  - Transcribir de la spec, no de `MATRIZ_PERMISOS`, una única operación GET para Administrador/Bodeguero/Solicitante; fijar capacidad `inventario`, exclusión de Superadmin, OpenAPI 200/401/403/404/409/422 y cardinalidad 62. Ampliar a 62 los dos asserts absolutos en 014 y a 62 los asserts absolutos en 018, con comentario/diagnóstico que identifique la ampliación por Feature 019; conservar los baselines históricos de roles.
  - **AC:** AC-4, AC-10, AC-11, AC-13.
  - **Hecho cuando:** expectativas nuevas están rojas por operación ausente; las aserciones previas documentan exactamente 61→62 sin cambiar ninguna transcripción histórica ni suprimir pruebas. **[pytest SQLite]**

- [x] **T3 — Añadir DTO exacto y registro aditivo de permiso/capacidad.**
  - **Archivos:** `backend/app/schemas/inventario_schema.py`, `backend/app/core/permisos.py`, `backend/app/core/capacidades.py`.
  - Definir `ProductoDetalleRespuesta` con los 13 campos exactos de §8 y `sedes: List[SedeExistenciaRespuesta]`, sin `from_attributes`. Agregar exactamente la operación `GET /api/v1/inventario/existencias/{producto_id}` con `_LECTURA_NEGOCIO`; asociarla solo a `inventario`. No variar roles ni capacidades de operaciones previas.
  - **AC:** AC-1, AC-4, AC-10…AC-12.
  - **Hecho cuando:** tests de campos exactos, roles y capacidad pasan; matriz queda en 62 y su única clave nueva es el GET especificado; permanecen rojos los casos que requieren endpoint/servicio. **[pytest SQLite]**

- [x] **T4 — Implementar servicio de lectura por ámbito y agregado.**
  - **Archivos:** `backend/app/services/inventario_service.py`; `backend/tests/api/test_detalle_producto_019.py`.
  - Implementar `obtener_detalle_producto`: resolver institución y sede operativa antes del recurso; 409 si la sede es `None`; 404 oculto para inexistente/ajeno/retirado operativo; Administrador conserva inactivos. Seleccionar producto/categoría y stock mediante `select()` y joins explícitos, con `.mappings()` y predicados del tenant/rol. Incluir sedes inactivas, ordenar `(sede_nombre, sede_id)`, devolver producto con `sedes=[]`/total 0 si es visible sin filas, calcular total y `_es_producto_critico` solo con las sedes devueltas. No leer `inventario` ni `Sede.activo` como exclusión.
  - **AC:** AC-1…AC-7, AC-9, AC-12.
  - **Hecho cuando:** pruebas API ejercitando servicio prueban suma, orden, inactivos, vacío/criticidad, aislamiento institucional en harness y precedencia de 409/404; el servicio no muta ni consulta saldo legado. **[pytest SQLite]**

- [x] **T5 — Publicar endpoint y cerrar contrato OpenAPI backend.**
  - **Archivos:** `backend/app/api/v1/endpoints/inventario.py`, tests de T1/T2.
  - Publicar ruta exacta con `response_model`, `status_code=200`, summary/description y `Depends(requiere_operacion(...))` + `Depends(requiere_capacidad(...))`. Documentar usando `respuestas_de_autorizacion()`, `respuesta_recurso_oculto()` y `respuesta_conflicto()`; conectar al servicio sin reglas de negocio en router. Verificar la precedencia observable: 401 → 403 matriz → 403 capacidad → 403 institución → 409 sede → 404 producto → 200, además de 422 path no entero.
  - **AC:** AC-4, AC-5, AC-10…AC-12.
  - **Hecho cuando:** pytest verifica todas las respuestas/gating y `/openapi.json` expone exactamente 62 operaciones protegidas por matriz, igualdad exacta ruta-operación y respuestas pactadas. **[pytest SQLite + OpenAPI]**

- [x] **T6 — Acreditar aislamiento tenant con PostgreSQL 16 gated.**
  - **Archivos:** nuevo módulo gated de Feature 019 bajo `backend/tests/`.
  - Probar tenant A frente a tenant B con productos homónimos/IDs y stocks controlados por esquema; la respuesta de A no contiene datos del otro tenant. Usar base/tenant temporal desechable con guardia fail-closed. Ejecutar con `$env:POSTGRES_TEST_URL = "postgresql://postgres:postgres@localhost:5433/postgres"`; no tocar `apt_erp`.
  - **AC:** AC-2, AC-13.
  - **Hecho cuando:** el test gated pasa con PostgreSQL 16 real, no se salta por falta de variable, la base temporal se elimina y `apt_erp` permanece intacta. **[PostgreSQL gated obligatorio]**

## Frontend

- [x] **T7 — Escribir primero tests rojos del cliente HTTP y del componente detalle.**
  - **Archivos:** nuevo `frontend/src/app/features/inventario/producto-detalle.component.spec.ts`; tests de `InventarioService` existentes o nuevos en su suite correspondiente.
  - Fijar endpoint GET y el tipo de respuesta; parámetro positivo válido; cero, negativo y no entero no envían petición; estados loading/error/403/404/409/red/servidor/422 y reintento sin loop; vacío válido; datos inactivos visibles para Admin sin controles; retorno a Existencias y a Gestión. Cubrir valores/códigos vía mocks HTTP y `ActivatedRoute.paramMap` según patrón de `ticket-detalle.component.spec.ts`.
  - **AC:** AC-1, AC-3, AC-6, AC-8…AC-10, AC-13.
  - **Hecho cuando:** pruebas fallan por ausencia de contrato/componente, no por imports o compilación; los fallos distinguen cada caso del requisito. **[ng test]**

- [x] **T8 — Añadir interface y método HTTP del detalle.**
  - **Archivos:** `frontend/src/app/shared/interfaces/index.ts`, `frontend/src/app/features/inventario/services/inventario.service.ts` y sus tests.
  - Declarar `ProductoDetalle` como contrato exacto con sedes reutilizadas y añadir `obtenerDetalleProducto(productoId)` GET a `/inventario/existencias/${productoId}`. Sin parámetros cliente de institución/sede y sin nuevos paquetes.
  - **AC:** AC-1, AC-2, AC-10, AC-13.
  - **Hecho cuando:** test HTTP afirma método, URL, tipo esperado y ausencia de filtros de ámbito; tipos compilan y suite del servicio pasa. **[ng test]**

- [x] **T9 — Implementar ruta, detalle, estados accesibles y retorno contextual.**
  - **Archivos:** `frontend/src/app/features/inventario/inventario.routes.ts`, nuevos `producto-detalle.component.ts` y `.html`.
  - Agregar `:productoId` como ruta hija. Crear componente standalone OnPush con `ActivatedRoute.paramMap`, `RouterLink`, signals, `HttpErrorResponse` mapeado a mensajes específicos, carga/reintento y empty state distinto de 404. Mostrar datos del §8 excepto IDs que la spec excluye de presentación; mostrar estados inactivos legibles sin acciones. Para `?tab=gestion`, volver a `/inventario?tab=gestion`; en otro caso volver a `/inventario`. Solo Tailwind; sin `styles: []`.
  - **AC:** AC-1, AC-3, AC-6, AC-8…AC-10, AC-13.
  - **Hecho cuando:** pruebas de T7 pasan para render, errores, invalidación local sin request, vacío, read-only y cada retorno contextual; `ng build` compila ruta lazy sin advertencias de presupuesto. **[ng test + ng build]**

- [x] **T10 — Añadir enlaces en listas y restauración real de pestaña.**
  - **Archivos:** `frontend/src/app/features/inventario/inventario.component.ts`, `.html`, `.spec.ts`.
  - Importar `RouterLink`; hacer enlazable el nombre de producto tanto en Existencias como en Gestión. La URL de Gestión lleva `?tab=gestion`; Existencias omite query. Leer query param `tab` al entrar al padre y activar Gestión solo cuando `gestionVisible()` y el valor sea `gestion`; mantener la carga actual de Gestión condicionada a `gestionVisible()`. Configurar `provideRouter([])` en los tests y verificar URL/enlace de origen para ambas superficies y roles.
  - **AC:** AC-8, AC-9, AC-13.
  - **Hecho cuando:** pruebas verifican destino con id y query apropiados, retorno abre la pestaña correcta, los roles no Admin no renderizan el enlace Gestión ni hacen GET de gestión, y todas las pruebas heredadas siguen verdes. **[ng test]**

## Verificación e integración

- [x] **T11 — Ejecutar suites completas, OpenAPI y build de producción.**
  - **Archivos:** verificación; correcciones solo si un test descubre defecto conforme al plan.
  - Ejecutar `cd backend && pytest`; ejecutar suites gated con `POSTGRES_TEST_URL`; configurar `$env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"` y correr `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`; ejecutar `cd frontend && npx ng build`. Inspeccionar `/openapi.json`, matriz, capability map, 200 y errores documentados. Nunca usar `npm test`.
  - **AC:** AC-1…AC-13.
  - **Hecho cuando:** pytest SQLite, gated PG16 sin skips por variable ausente, Angular tests y build quedan en verde; cardinalidad 62 y contrato/matriz coinciden exactamente. **[pytest + PostgreSQL gated + ng test + ng build]**

- [x] **T12 — Recorrido funcional en 4200 con datos autorizados.**
  - **Archivos:** evidencia reproducible del cierre.
  - Recorrer con Administrador Existencias→detalle→volver y Gestión→detalle inactivo→volver a Gestión; recorrer Bodeguero y Solicitante desde Existencias; verificar datos, stock por alcance, sede inactiva, estados, empty/error/retry, tabs y ausencia de escrituras. Para requisitos de lectura, no inventar una escritura de negocio: cumplir AGENTS.md §8.6 registrando recorrido funcional contra datos QA reales; si se requiere preparación con escritura, usar operación normal autorizada, contrastarla con PostgreSQL y registrar estado previo/posterior. No alterar stock mediante SQL directo.
  - **AC:** AC-1…AC-10, AC-13.
  - **Hecho cuando:** recorrido documenta roles, dos orígenes y restauración de pestaña en 4200, API responde según contrato y no queda modificación no autorizada de datos QA. **[4200, recorrido funcional]**

- [x] **T13 — Reconstruir y hacer humo en 8080.**
  - **Archivos:** imagen frontend reconstruida y evidencia de cierre.
  - Ejecutar `docker compose -f docker-compose.yml build frontend` y luego `docker compose -f docker-compose.yml up -d frontend`; comprobar deep link `/inventario/:productoId`, carga básica, retorno por pestaña y bundle nuevo en 8080.
  - **AC:** AC-13.
  - **Hecho cuando:** 8080 refleja la imagen reconstruida (no bundle previo), deep link Angular responde y el smoke del detalle queda registrado. **[8080 tras rebuild obligatorio]**

## Cierre

- [x] **T14 — Evidencia AC, stack, roadmap, memoria y coherencia documental.**
  - **Archivos:** `docs/spec/features/019-detalle-producto-por-alcance/spec.md` §7, `docs/spec/stack.md`, `docs/spec/roadmap.md`, `MEMORY.md`, `AGENTS.md`, `.agents/skills/` (grep de lectura), y este `tasks.md`.
  - Marcar evidencia verificable para cada AC de §7 y actualizar su estado solo tras cumplir la política de cierre. Registrar en `stack.md` contrato de detalle, roles, capacidad `inventario`, coexistencia con el GET solo-catálogos bajo `catalogo`, matriz 61→62, consulta acotada y ausencia de DDL/versionado. Actualizar fila/estado de 019 en roadmap; actualizar `MEMORY.md` con resultado, decisiones y error a evitar sin exceder el límite. Hacer grep de coherencia de rutas/afirmaciones sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/`; corregir solo referencias obsoletas si las hubiera y dentro de permisos documentales aprobados.
  - Comprobar que todas las tareas previas están `[x]`, que spec §7 incluye evidencia por AC, tests están verdes y se verificaron ambos puertos conforme a AGENTS.md §8.5/§8.6. No cerrar roadmap si falla cualquiera.
  - **AC:** AC-1…AC-13, cierre.
  - **Hecho cuando:** documentos coherentes; cada AC tiene evidencia reproducible; `stack.md`, `roadmap.md` y `MEMORY.md` reflejan el resultado; grep no encuentra citas/rutas obsoletas; tareas de cierre marcadas solo después de comprobar todos los gates. **[cierre documental]**

## Matriz de trazabilidad AC ↔ tareas

| AC | Tareas |
|---|---|
| AC-1 | T1, T3–T5, T7–T9, T11–T12, T14 |
| AC-2 | T1, T4, T6, T8, T11–T12, T14 |
| AC-3 | T1, T4, T7, T9, T11–T12, T14 |
| AC-4 | T1–T5, T11–T12, T14 |
| AC-5 | T1, T4–T5, T11–T12, T14 |
| AC-6 | T1, T4, T7, T9, T11–T12, T14 |
| AC-7 | T1, T3–T4, T11–T12, T14 |
| AC-8 | T7, T9–T10, T11–T12, T14 |
| AC-9 | T7, T9–T10, T11–T12, T14 |
| AC-10 | T1–T3, T5, T7–T9, T11–T12, T14 |
| AC-11 | T2–T3, T5, T11, T14 |
| AC-12 | T3–T5, T11, T14 |
| AC-13 | T1–T2, T5–T14 |
