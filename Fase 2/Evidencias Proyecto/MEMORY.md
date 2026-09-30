# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Feature 002 (Catálogo + consulta de existencias) **implementada y verificada**: endpoint `GET /inventario/existencias` (read model armado en el service), 4 filtros, orden determinista, N+1 eliminado con `selectinload`, H-1 acotado a 404 en `crear_producto`, y la vista de inventario real (búsqueda, panel de categorías con conteos, filtro de críticos, tabla de 6 columnas con las sedes dentro de la celda).
- Backend: **43 tests** en verde sobre SQLite en memoria (25 de la Feature 001 sin reescribir + 18 nuevos). Frontend: **12 tests** en verde (4 + 8), build OK.
- Las tres rutas GET que ya existían conservan su JSON: lo único que cambió es el orden, ahora determinista. `/openapi.json` verificado contra la spec.
- **Pendiente de la Feature 002:** solo el recorrido visual manual de la vista (anotado `[!]` en su `tasks.md`), por eso su casilla en `roadmap.md` sigue abierta. Para cerrarlo: `docker compose up -d db backend` + `cd frontend && npm start` a 1366px o más.
- El 500 de `crear_ticket` por `producto_id` inexistente sigue vivo **a propósito**: es de la Feature 003, con su test de regresión esperando 500.
- Estructura alineada con `docs/spec/stack.md` (patrón de read model documentado en §2, Nota 2 revisada).

## Decisiones (y por qué)
- **El filtro de la vista vive en el cliente, no en el servidor** (D-1 de la 002). Los parámetros `q`, `categoria_id`, `departamento_id` y `solo_criticos` existen y se prueban en el endpoint porque son contrato público, pero la vista hace **una** consulta y filtra con `computed()`: los conteos del panel lateral solo son coherentes con filtro local. **Disparador para revertir:** cuando el catálogo supere ~500 filas por institución o entre multi-tenant, el filtro pasa al servidor con paginación.
- **Endpoint nuevo en vez de tocar `/stock`**: el contrato congelado por AC-2 de la Feature 001 queda intacto y los 25 casos previos siguen verdes sin reescribirlos.
- **Read model armado en el service, sin `from_attributes`**: el DTO cruza 4 tablas y agrega, así que Pydantic no puede leerlo del objeto ORM. Patrón documentado en `stack.md` §2.
- Capas backend: routers delgados → `app/services/` (transacciones ACID) → ORM.
- Frontend 100% Standalone: `inject()` en lugar de constructor, `signal()/computed()` en lugar de RxJS para estado local, `@if/@for` con `track`.
- No crear `shared/components/` ni `shared/pipes/` (revisado de nuevo en la 002): se crean cuando exista el **segundo** consumidor, no el primero.
- Kanban con datos de muestra (H-3): no inventar agrupamiento por `estado_id`. Se resolverá con catálogo de estados (Feature 004).
- `api.service.ts` eliminado (D-3 de la 001): repartido por feature para evitar god-service.
- `database/02_datos_semilla.sql` con datos de QA (10 filas por tabla): standalone, no altera el esquema 3NF.

## Aprendizajes y errores a evitar
- **La suite corre en SQLite, pero producción es PostgreSQL.** `ilike` se traduce distinto en cada motor, así que una consulta que dependa de funciones del motor se verifica además contra el `docker-compose`. En la 002 dio igual en los dos.
- `select()` estilo Core con columnas sueltas exige los **onclause explícitos**: sin entidad en el `FROM`, SQLAlchemy no puede deducir el join y lanza error.
- `dict` conserva el orden de inserción: el `ORDER BY` de SQL se propaga solo a `list(acumuladores.values())`, sin reordenar en Python.
- SQLAlchemy parte el SQL en varias líneas: para contar consultas con un listener hay que colapsar espacios (`" ".join(s.split())`) antes de comparar `" from producto"`, o el match nunca ocurre.
- `forkJoin` cancela la otra Observable cuando una falla: en tests, `httpMock.verify({ ignoreCancelled: true })`.
- SQLite requiere `PRAGMA foreign_keys=ON` para que las FKs provoquen la violación que dispara el `rollback`.
- Transacciones con hijos: usar `flush()` (no `commit()`) tras crear la cabecera para obtener el PK sin romper la atomicidad.
- Probar por el **seam HTTP** (`TestClient`), nunca consultando la BD directamente en los tests.
- Un fixture nuevo que se apoya en `datos_base` en vez de reemplazarlo no rompe la suite previa.
- `@if/@for` exige `track` obligatorio (no compila sin él).
- Sin ids fijos en fixtures: usar los ids generados (evita depender de secuencias de identidad).
- **Karma en Angular 18 arranca en modo watch y esta máquina no tiene Chrome.** El comando que funciona está en `AGENTS.md` §5; `npm test` a secas se cuelga.
- `.gitignore` ignoraba `venv/` pero no `.venv/`, que es lo que manda crear `AGENTS.md` §5.
- En PowerShell, `Get-Content -Raw | docker exec` mete el archivo por la codificación de la consola y destruye los acentos (`á` → `??`). Usar `cmd /c "... < archivo.sql"`, que copia bytes crudos.
- **`database/` se ejecuta en orden alfabético** (prefijo `01_`/`02_` obligatorio, `ON_ERROR_STOP=1`). Con los nombres previos la semilla corría antes del esquema y abortaba el arranque. Es el fallo que mata una demo en otra máquina: se ve solo con `down -v` + `up`.
- Recrear la base con `docker compose rm -f db` + `docker volume rm <volumen>` + `up -d db` deja todo listo solo. **Reinicia el backend después**: su pool de conexiones al volumen destruido lanza `server closed the connection unexpectedly` (500) en la primera petición.

## Próximos pasos
- Cerrar la Feature 002: hacer el recorrido visual de la vista y marcar la casilla en `roadmap.md`.
- Feature 003: Crear ticket con detalles + validaciones. Buen momento para mapear FK inválida a 400/422 (corregir el 500 de `crear_ticket`, justificado y acotado).
- Feature 004: Catálogo de estados + Kanban operativo por estados (resolver `estado_id` vs nombre). Aquí se corrige `ESTADO_CERRADO_ID`.
- Feature 005: Despacho transaccional con rebaja automática de stock + auditoría, y `GET /inventario/movimientos`.
- Feature 006: Aplicar guards/interceptor a rutas + login/JWT real (mantener autenticación decorativa hasta entonces).