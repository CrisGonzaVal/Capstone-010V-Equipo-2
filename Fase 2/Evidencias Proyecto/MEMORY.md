# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…005 cerradas. **005 (despacho transaccional) CERRADA** (13/Oct/2026): **28 AC en verde**, `pytest` 140 passed + 1 warning preexistente (`StarletteDeprecationWarning` de `starlette.testclient`), `ng test` 69 SUCCESS. Recorrido funcional en 4200 con despacho real persistido en PostgreSQL (verificado por `SELECT`) y humo en 8080 tras reconstruir y recrear la imagen. Despacho atómico y concurrencia `FOR UPDATE` (200/409) verificados contra PostgreSQL 16.14 real.
- 005 entregó: `POST /tickets/{ticket_id}/despacho` (payload `{usuario_id}`) que rebaja stock, fija `cantidad_entregada`, cierra el ticket y crea una `SALIDA` por detalle en una sola transacción; `GET /inventario/movimientos` (read model con producto/departamento/ubicación, orden `fecha DESC, id DESC`, solo lectura); y el `PATCH /tickets/{id}/estado` rechaza con 409 el cierre manual `EnCurso→Cerrado` dirigiendo al despacho. El Kanban ya no ofrece ese avance.
- 003 entregó: `GET /tickets/catalogos` (4 catálogos), 404 prevalidados, 422 de Pydantic, modal nativo `<dialog>`. 004: sellado por nombre con un solo commit, `ESTADO_CERRADO_ID` eliminado.
- **Backend 140 tests** (todos en verde), **frontend 69 tests**, build de producción OK. Estructura alineada con `docs/spec/stack.md`.
- **Agentes en frontmatter V2 nativo** (13/Oct/2026): los 4 usan `permissions` (lista `action`/`resource`/`effect`, con `shell` y `subagent`). Pendiente menor: `opencode.json` conserva el `mcp` en forma V1.

## Decisiones de la 005 (D-1…D-12)
- **D-1**: solo se despacha desde `EnCurso` y se cierra en `Cerrado`, ambos resueltos **por nombre** (menor `estado_id` ante duplicados), nunca por ids fijos. Ese par queda reservado en el PATCH (D-12).
- **D-2/D-3**: despacho completo (entrega `cantidad_solicitada`); una insuficiencia cancela todo el despacho.
- **D-4**: `usuario_id` se valida (existe) pero **no se persiste**: `movimiento_inventario` no tiene columna de actor. Ni la respuesta ni el historial afirman autoría.
- **D-9**: la operación bloquea la fila del ticket con `select(...).with_for_update()` al inicio; la segunda petición espera y, tras el commit, ve `Cerrado` y recibe 409.
- **D-5/D-7**: se exige exactamente una fila de inventario por producto; varias líneas del mismo producto validan el total agregado y dejan un movimiento por línea.
- **D-6**: observación literal `Despacho ticket_id={id}; detalle_id={id}; producto_id={id}` (cabe en VARCHAR(250)).
- **D-10/D-11**: ticket sin detalles → 409; producto no resoluble → 409 de integridad, no 404.

## Aprendizajes y errores a evitar
- **Cierre = verificación, no marcado** (AGENTS.md §8.5): tests verdes no cierran una feature; hacen falta los dos puertos (4200 funcional + 8080 de humo).
- **8080 sirve un build congelado**: hay que `docker compose build frontend` + `up -d --force-recreate frontend` (un `up` sin recreación deja el contenedor viejo; buildx exporta manifest con atestaciones). El backend sí se actualiza solo (`./backend/app` montado + `--reload`).
- **SQLite ignora `FOR UPDATE`**: la suite en memoria no prueba el bloqueo de fila; AC-12 se verificó con dos sesiones reales sobre PostgreSQL 16.
- **`db.close()` revierte**: el `rollback()` explícito de `crear_ticket` es redundante con el `get_db` actual; se conserva por constitución.
- `loc` de FastAPI: `at(-2)` es el índice de fila, `at(-1)` el campo; `['body','asunto']` no tiene fila.
- **PowerShell**: `&&` no es separador válido (usar `;`); `Set-Content -Encoding utf8` sobre un `.md` UTF-8 dejó mojibake (editar con la herramienta de edición); `Get-Content -Raw | docker exec` destruye acentos (usar `cmd /c "... < archivo.sql"`).
- **Karma**: arranca en watch y esta máquina solo tiene Edge: fijar `CHROME_BIN` y usar `--watch=false --browsers=ChromeHeadless`.
- Los CHECK del DDL no existen en SQLite: un 422 verde prueba el schema, no la base.

## Próximos pasos
- **Feature 006** (Sprint 3): integración de Clerk en Angular y validación JWT en FastAPI. **007**: guards por rol y permisos. La autenticación sigue decorativa hasta entonces.
