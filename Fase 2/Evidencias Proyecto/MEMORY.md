# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…009 implementadas; **008 y 009 CERRADAS** (veredicto APROBADO del reviewer). Backend `pytest`: **540 passed, 5 skipped, 0 failed** (SQLite; los 5 gated pasan con `POSTGRES_TEST_URL`). Frontend `ng test`: **172 SUCCESS, 0 failed**; `ng build` limpio. Matriz de permisos: **21 operaciones**.
- 009 entregó: `GET /api/v1/dashboard/` consolidado (`DashboardAnaliticoRespuesta`); `dashboard_service.obtener_dashboard_analitico`; router delgado + operación `_TODOS` en la matriz; frontend `DashboardService` + interfaces espejo; dashboard con datos reales. Recorrido 4200 con los 4 roles (Admin 626/5/7/3, Superadmin 646/5/10/3, Bodeguero 626/5/7/3, Solicitante 626/0/7/3 sin actividad y 403 en historial); humo 8080 sobre imagen reconstruida `sha256:11a287959b12…` (008: `cfdd5de4…`).
- 008 entregó: `institucion_id` en catálogo e inventario/ticket/detalle; claves compuestas en `01_esquema.sql`; migración `98_…` fail-closed idempotente aplicada a la base real; semilla multiinstitución con homónimos; filtros de ámbito; `/auth/me` con institución efectiva (quedó en 20 operaciones; 009 la llevó a 21).
- 007: roles sin alias, autorización cliente+servidor, matriz central, `ambito_service`, `RolGuard` + `/acceso-denegado`, retiro de `usuario.password`. 006: Clerk. 005: despacho transaccional. 003/004: catálogos/kanban.

## Decisiones de la 009
- D-3: un único endpoint consolidado; autorización por operación `_TODOS` en la matriz; el filtrado por rol vive en el servicio y no concede permisos nuevos sobre otros endpoints.
- D-1/D-4: criticidad por **fila** de inventario (`stock_actual <= stock_minimo` por departamento-producto), no por agregado; `total_alertas == len(alertas)`.
- D-2/D-6: log de alertas **derivado**; sin tabla/columna/migración nueva; `movimiento_inventario` sigue siendo la auditoría inmutable.
- D-5: actividad = movimientos reales, orden `fecha DESC, id DESC`, límite fijo **10**; `actividad_disponible` es presentación (Solicitante `false`) y **no** amplía el 403 vigente del historial.
- D-4/D-7: Superadmin tiene `unidades_en_stock` como **escalar global único**, pero cada fila de alerta/actividad lleva atribución institucional (sin comparar/rankear instituciones); la futura Sede no se anticipó.
- Retiro del placeholder «Estado de Sedes Descentralizadas» y de las cifras de muestra; la institución por fila es parte del contrato.

## Aprendizajes y errores a evitar
- Read model consolidado: una consulta por sección (agregados en SQL) evita N+1; `from_attributes` no aplica a proyecciones multi-tabla/agregadas.
- Al añadir una operación a la matriz hay que actualizar también las **transcripciones independientes** de 007/008 (`test_permisos.py`, `test_permisos_008.py`) que asertan igualdad exacta.
- Al pasar un spec de rojo a verde, limpiar el docstring de «Fase ROJA»: quedó obsoleto y el reviewer lo marcó.
- Cierre = verificación (AGENTS §8.5): hacen falta los dos puertos; 8080 exige `docker compose build frontend` + `up -d`; el backend recarga solo.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida FK compuestas ni el `NOT NULL` del DDL.
- Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless` (nunca `npm test` a secas).

## Próximos pasos
- Roadmap tras la 009: **Hito 2** — despliegue en producción y entrega del proyecto de título. No quedan features `[ ]` en el índice de especificaciones.
- La rama `dev` con todo el trabajo de la 009 **no se ha commiteado** (decisión del usuario).
