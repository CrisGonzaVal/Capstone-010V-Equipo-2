# MEMORY.md � Diario del Proyecto
Memoria entre sesiones. M�ximo ~50 l�neas: resume lo �til y elimina lo que ya no aporte.

## Estado actual
- Features 000, 001 y 002 cerradas. **Feature 003 (modal de ticket) CERRADA** (01/Oct/2026).
- **004 (Tablero Kanban operativo) CERRADA** (13/Oct/2026): **27 AC en verde**, `pytest` 95 passed + 1 warning preexistente, `ng test` 63. Recorrido funcional en 4200 con escritura real en PostgreSQL (verificada por `SELECT`) y de humo en 8080 tras reconstruir y recrear la imagen de producción. Flujo lineal (404/409 en orden D-8), sellado por nombre con un solo commit: todo **decidido por nombre, sin ids fijos**; `ESTADO_CERRADO_ID` eliminado (0 coincidencias). Los comandos SDD rutean a los subagentes (`planner`, `reviewer`, `implementer`) salvo `/sdd-status` (built-in `plan`); con modelos free el riesgo es la cuota, y el `planner` es el rol más pesado.
- 003 entregada: `GET /tickets/catalogos` (4 cat�logos en un endpoint), 404 prevalidados antes de escribir, 422 de Pydantic, y el modal nativo `<dialog>` con signals + `FormArray`. Evidencia en su `tasks.md` �8.
- **Backend 95 tests** (todos en verde, 16 de la 004), **frontend 63 tests**, build de producci�n OK. Recorrido en 4200 (funcional, con escritura real) y en 8080 (tras reconstruir la imagen).
- Estructura alineada con `docs/spec/stack.md`.
- **Agentes migrados a frontmatter V2 nativo** (13/Oct/2026): los 4 usan `permissions` (lista ordenada `action`/`resource`/`effect`, con `shell` y `subagent` en vez de `bash` y `task`) y los `/sdd-*` usan `agent:` + `subagent:`. Ya no queda `permission:`, `bash:`, `task:` ni `subtask:` en `.opencode/`. V2 traducia el frontmatter V1 solo, asi que esto es explicito, no un arreglo. Pendiente: `opencode.json` conserva el `mcp` en forma V1 (le falta `mcp.servers` y el `disabled` inverso).

## Decisiones de la 003 (D-1�D-7)
- **D-1**: un �nico `GET /tickets/catalogos`, no 4 endpoints. `/usuarios/` no sirve: devuelve usuarios con rol, no solo solicitantes.
- **D-2**: `URL_API` se movi� a `shared/config/url-api.ts`. `AC-10` de la 001 dec�a "nada fuera de `shared/`" y estaba incumplido en los hechos.
- **D-3**: el solicitante es un `<select>`, no un campo de texto libre.
- **D-4**: estado inicial = `catalogos.estados[0]`, nunca comparando strings. El orden del endpoint es por `estado_id`, y en la semilla el alfab�tico dar�a otro.
- **D-5**: el 422 lo produce el schema Pydantic, no los CHECK del DDL (SQLite no los tiene).
- **D-6**: usuario, prioridad, estado y **todos** los productos se validan antes del primer `add()`, con 404 nombrando la referencia.
- **D-7**: `NonNullableFormBuilder` + `FormArray`; los duplicados de producto se suman en el cliente (es UX, no regla de negocio: `detalle_ticket` no declara `UNIQUE`).
- Los `db.query()` que quedan en `listar_tickets()` y `actualizar_estado_ticket()` son preexistentes; todo c�digo nuevo usa `select()`.

## Aprendizajes y errores a evitar
- **Una feature no est� cerrada hasta que 8080 la refleja.** 4200 es el recorrido funcional; 8080 sirve un build congelado en la imagen y hay que reconstruirlo. El backend s� se actualiza solo (`./backend/app` montado + `--reload`), el frontend no. Ver `AGENTS.md` �8.6.
- **`docker compose up -d` no recrea el contenedor** si el tag `latest` apunta a un image ID distinto al del contenedor vivo (buildx exporta un manifest list con atestaciones). Para que 8080 sirva la imagen reconstruida hace falta `docker compose up -d --force-recreate frontend`; sin eso el recorrido de cierre valida una vista vieja y da un falso negativo.
- **El dev server de 4200 (`npm start`) no sobrevive a un arranque nuevo de sesión**, y `-WindowStyle Hidden` se traga la salida: lanzarlo con salida redirigida a un log temporal para poder ver el error si no llega a escuchar.
- **`db.close()` revierte.** El `rollback()` expl�cito de `crear_ticket` es redundante con el `get_db` actual, y no hay test que pueda probarlo desde el seam HTTP (borrarlo deja la suite en verde). Se conserva por constituci�n. Lo que impide el ticket hu�rfano es la prevalidaci�n, que no escribe.
- `loc` de FastAPI: `at(-2)` es el �ndice de fila y `at(-1)` el campo. `['body','asunto']` es un caso aparte, sin fila.
- Para parsear el DOM de `msedge --dump-dom`, leerlo con `[System.IO.File]::ReadAllText`: `Get-Content -Raw` mete doble mojibake y rompe los acentos.
- En PowerShell, `Get-Content -Raw | docker exec` destruye los acentos. Usar `cmd /c "... < archivo.sql"`.
- En PowerShell, `Set-Content -Encoding utf8` sobre un `.md` que ya era UTF-8 deja `—` en los em dash: editar con la herramienta de edici�n, no reescribir el archivo entero.
- Los CHECK del DDL no existen en SQLite: un 422 verde demuestra que responde el schema, no que la base rechace.
- **Karma en Angular 18 arranca en modo watch y esta m�quina no tiene Chrome**: el comando est� en `AGENTS.md` �5. `.gitignore` ignoraba `venv/` pero no `.venv/`.
- **Un comando no hereda `build` por defecto**: cada `.opencode/commands/*.md` declara su `agent:`, y con `subagent` omitido solo abre sesion hija si ese agente es `mode: subagent`. Para forzarlo: `subagent: true` (siempre hijo) o `false` (siempre la sesion actual). Un comando con `agent:` cambia el agente de la sesion.
- **El MCP `postgres` se queda en el `opencode.json` del repo, no en la config global**: los companeros ya lo usan asi, y aunque estuviera en lo personal el del proyecto ganaria por prioridad. Ojo: su URL usa 5433 porque es el puerto publicado al host (`docker-compose.yml` mapea `5433:5432`); dentro de la red docker son 5432 y lo inyecta el compose. Por lo mismo, `backend/.env.example` fija `DB_PORT=5433` — `config.py` usa `localhost`, o sea arranque desde el host.

## Pr�ximos pasos
- **Feature 005 es el siguiente trabajo**: despacho transaccional con rebaja de stock, auditor�a y `GET /inventario/movimientos`.
- **Feature 006**: guards por rol e interceptor de auth. Autenticaci�n decorativa hasta entonces.