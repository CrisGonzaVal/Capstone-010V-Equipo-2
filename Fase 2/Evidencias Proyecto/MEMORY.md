# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**018 cerradas**; la **018** el **21/Oct/2026**, la **014** y la **017** el **20/Oct/2026**, la 013 el **19/Oct/2026**.
- **014 (ciclo de vida del catálogo):** `activo` reversible en `producto`/`categoria` con baja lógica (sin borrado físico), transiciones con motivo libre ≤500 e historiales inmutables de producto y categoría (16.ª/17.ª entidades de dominio), listado de gestión solo Administrador, gating `catalogo` y matriz **55 → 60**. Suites de cierre: `pytest` SQLite **1290 passed / 70 skipped / 0 failed**; gated PostgreSQL 16 **70 passed / 0 failed**; `ng test` **396 SUCCESS** (392 al cierre + 4 de la enmienda de pestañas); `ng build` limpio. Versión **014.1**, **22/19** tablas. Recorrido 4200 con escritura real y humo 8080 con imagen reconstruida (`main-24CPLXSZ.js`, enmienda T17; antes `main-GVEDOJ7X.js`); evidencia en `docs/spec/features/014-ciclo-vida-catalogo/evidencia/README.md` (§10 = enmienda de pestañas).
- **017 (provisionamiento y gobierno de identidades):** invitaciones de Clerk desde el backend, gobierno de Administradores y bitácora de motivos. Cierre: `pytest` SQLite 1158/56/0, gated PG16 52/0, `ng test` 375, matriz 55. Evidencia en `017-provisionamiento-y-gobierno-de-identidades/evidencia/README.md`.
- **018 (filtros de existencias por sede y departamento):** `sede_id` aditivo en existencias, lectura nueva de ámbito y matriz **60 → 61**. Cierre: `pytest` SQLite **1339/76/0**, gated PG16 **1415/0/0** (`apt_erp` intacta), `ng test` **419**, `ng build` limpio (`main-7QF7T5XQ.js`); recorrido 4200 con escritura real y humo 8080 con imagen reconstruida. Evidencia en `018-filtro-inventario-sede-departamento/evidencia/README.md`.
- **Base consolidada:** `database/` tiene solo `01_esquema.sql` (control 22 tablas + 19 por tenant) y `02_datos_semilla.sql` (semilla + reparto + mapa + **`014.1`** con guardia fail-closed). Sin migraciones: reset = `down -v` + `up -d` (`reset-db.cmd`/`.ps1`).

## Feature 014 — decisiones clave
- **Invariante categoría-producto:** no puede existir producto activo bajo categoría inactiva. Baja de categoría → 409 si tiene productos activos; reactivar producto exige categoría activa; reactivar categoría no hace cascada (D-5/AC-5/AC-16).
- **Stock cero en `stock_sede`:** la baja de producto exige saldo cero solo en `stock_sede`; `inventario` es legado congelado y no cuenta (D-6). La transición no mueve stock ni crea movimientos.
- **Idempotencia sin motivo:** repetir el estado ya persistido responde **200** sin motivo, sin precondiciones y sin historial; precede a 422/409 (D-9/AC-8).
- **Dos historiales = 16.ª/17.ª entidad:** tablas separadas por recurso con FK reales, inmutables y solo lectura por API; paridad control/tenant como `historial_transicion_ticket` (D-8).
- **Precedencia y locks:** 401 → 403 matriz → 403 capacidad → 404 idéntico → 200 idempotente → 422 motivo → 409. Orden único `categoría → producto → stock_sede`.
- **Gating `catalogo`** (6 capacidades cerradas de la 012) con rol único `Administrador`; listados operativos filtran `producto.activo AND categoria.activo` para todos los roles, y la gestión usa `GET /inventario/gestion`.
- **Enmienda T17 (presentación):** inventario en pestañas «Existencias» (predeterminada, todos los roles) y «Gestión del catálogo» (solo Administrador; sin conmutador ni pestaña vacía para el resto). Panel inactivo fuera del DOM; `tablist/tab/tabpanel` con `tabindex` móvil y flechas. Servicio y backend intactos.

## Feature 018 — decisiones clave
- **Filtro organizacional server-side con `sede_id`:** parámetro aditivo de `GET /inventario/existencias` incorporado a `condicion_stock` **antes** del `outerjoin` (INNER efectivo cuando hay filtro) y sin `db.get(Sede, …)` previo: un id ajeno o inexistente responde **200/`[]`** y no revela otro tenant. No contradice el **404** de recurso de `GET /inventario/stock?sede_id=…` de la 011, que se conserva intacto.
- **Lectura de ámbito nueva:** `GET /api/v1/inventario/ambito` (Administrador+Bodeguero) gateada por la capacidad **ya existente** `inventario`; matriz **60 → 61** y las dos aserciones absolutas de la 014 ampliadas explícitamente. Sin cambios de modelo ni versión: sigue **17 entidades**, `014.1`, 22/19 tablas. Bodeguero sin sede → **409**; Solicitante/Superadmin → **403**.
- **Semántica «departamento = sede»:** no hay saldo departamental; `departamento_id` solo localiza la sede y omite productos sin fila de stock allí, de modo que dos departamentos de una sede dan el mismo saldo. Nota literal de stock compartido visible solo para el Bodeguero (sin selector de sede).
- **Franja de indicadores:** se recalcula sobre el resultado server-side al cambiar sede/departamento, pero **no** con texto/categoría/crítico (filtros de cliente). Es comportamiento heredado y está fijado por pruebas.

## Otras decisiones vigentes
- **017:** el estado de invitación vive en `control.mapa_usuario_esquema`; aceptación en el primer login; reenvío = revocar+crear; la URL se devuelve solo en la respuesta inmediata. Superadmin con 5+1 operaciones de control y **403** en lecturas de negocio (11+1 operaciones retiradas). Dashboard técnico con taxonomía `operativo`/`no enrutable`/`no disponible`.
- **013:** terminales `Cerrado`/`Anulado` por nombre canónico en cualquier catálogo (enmienda D-4/AC-26). `Anulado` no sella `fecha_cierre` ni toca stock; la matriz sin operación da **403** (AC-18).
- **012/011:** `control.institucion.activo` gobierna el routing; 6 capacidades en `funcion_institucion` (gating 403 adicional); `stock_sede` es la única fuente de saldo operativo.

## Aprendizajes y errores a evitar
- **Filtro de lista ≠ recurso:** `sede_id` en `/inventario/existencias` es un parámetro de filtro (**200/`[]`**), no un recurso (**404** de `/inventario/stock`). No añadir lookup previo de sede ni reutilizar aquel patrón; sin él, un id de otro tenant devuelve `[]` sin distinguirse de uno inexistente.
- Cierre = verificación (AGENTS §8.5–§8.7): los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo; grep de coherencia sobre AGENTS/MEMORY/skills.
- **Combos de rol espejo del backend:** ocultar un rol en el alta no basta; la edición debe usar la misma regla. Desde el 21/Oct/2026 el combo de edición de `/administracion/usuarios` usa `rolesEdicion` (`puedeAsignarRol` + rol actual no asignable visible y `Superadmin` siempre fuera), así que un Administrador no ve `Superadmin`; la API ya respondía 403. `ng test` 399.
- **Contratos externos:** la API real de Clerk `GET /v1/invitations` devuelve una lista desnuda, no `{"data":[…]}`; verificar contra la API real, no solo contra el fake.
- **La semilla limpia no crea al Superadmin:** `control.usuario` queda vacía y `ejecutar_bootstrap_control` no se invoca al arrancar; un clon nuevo no entra a `/control` (se ejecutó a mano en 017 y 014).
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas. Bugs que solo salen en PG: sesión de control vs tenant (012) y `DetachedInstanceError` del lector global (013: DTO eager dentro de la sesión de cada tenant). Bases desechables; `apt_erp` nunca se toca.
- Toda mutación de estado exige actor **persistido** (FK del historial): fixtures con la sonda sintética `9999` deben pasar a un usuario real.
- Edge: `CHROME_BIN` + `--watch=false --browsers=ChromeHeadless` (nunca `npm test`). PowerShell: `pg_dump` con `cmd /c`; `docker exec sh -c` con `$()` y comillas anidadas se rompe; `curl.exe` conserva backslashes (usar archivos de body).
- Clerk por HTTP sin navegador: dev browser + sign-in ticket BAPI + `Origin: localhost:4200` (el backend exige `azp`); código de prueba `424242` en la tarjeta prebuilt. Tokens ~60 s.
- `resolver_contexto_solicitud` sin `abrir_sesion_tenant` lee la versión de **control**: el gated debe cablear `abrir_sesion_tenant=crear_sesion_esquema`.
- Specs Angular: con `provideRouter([])` el click de un `routerLink` no actualiza `router.url`; probar el `href` con espía a `navigateByUrl`.
- **Carreras gated deterministas:** sincronizar solo el arranque (`Barrier`) no fija quién toma el lock; la sesión poseedora debe confirmar la adquisición (`threading.Event` tras el `SELECT … FOR UPDATE`) y esperar a que la contendiente bloquee antes de continuar. Si no, el planificador invierte el orden y produce un falso «lock ausente» intermitente (corregido en 014 T10).

## Próximos pasos
- Backlog posterior al Sprint 6: **015** informes PDF/Excel y **016** notificaciones in-app; candidata **019** (bitácora de motivos/constancias). **Hito 2:** 11/Dic/2026.
- Retirada de «ERP»/«Kanban» de textos visibles hecha como cambio directo sin spec, por decisión del usuario (exención puntual de AGENTS §7).
- **Diagramas de casos de uso regenerados (21/Oct/2026):** 5 HTML en `docs/diagramas/` y 5 PNG a 2x (viewBox×2) replicados como solo PNG en `../Evidencias Grupales/diagramas/`. Inventario canónico: 26 casos en 5 paquetes (Control SaaS 5, Administración 6, Inventario 4, Tickets 8, Informes/avisos 3); 015/016 marcados `PLAN · 015/016` con elipse discontinua. Superadmin limitado a control (sin lecturas de negocio, 017) y sin la ficticia «asignar encargado» (es A3). El general usa franja de actores + tarjetas de paquete, sin líneas de asociación: el detalle UML vive en los cuatro diagramas por actor.
- Hallazgo abierto: la semilla no trae Administrador `+clerk_test` (se mapea una identidad Clerk a un usuario local) y el bootstrap del Superadmin no se invoca al arrancar.
- Aviso de accesibilidad preexistente en el buscador operativo de inventario (input sin `id`/`name`), anotado para limpieza de UI.
