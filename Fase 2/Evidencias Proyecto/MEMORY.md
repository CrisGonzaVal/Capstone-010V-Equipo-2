# MEMORY.md — Diario del Proyecto
Memoria entre sesiones. Máximo ~50 líneas: resume lo útil y elimina lo que ya no aporte.

## Estado actual
- Features 000…**019 cerradas**; la **019** el **22/Oct/2026**, la **018** el **21/Oct/2026**, la **014** y la **017** el **20/Oct/2026**, la 013 el **19/Oct/2026**.
- **019 (detalle de producto por alcance):** lectura aditiva `GET /inventario/existencias/{producto_id}` (producto + stock por sede acotado al rol) y ruta Angular `:productoId` con retorno `?tab=gestion`; matriz **61 → 62**. Cierre: `pytest` SQLite **1391/77/0**, gated PG16 **1468/0/0** (`apt_erp` intacta en `014.1`, 22 tablas, 4 tenants), `ng test` **446**, `ng build` limpio (`main-D6GKPODP.js`); recorrido 4200 y humo 8080 con imagen reconstruida; evidencia en `019-detalle-producto-por-alcance/evidencia/README.md`.
- **018:** `sede_id` aditivo en existencias (**200/`[]`** para id ajeno), lectura `GET /inventario/ambito` bajo `inventario` y nota de stock compartido del Bodeguero; matriz 60→61. Cierre: pytest 1339/76/0, gated 1415/0, `ng test` 419, bundle `main-7QF7T5XQ.js`. **014:** `activo` reversible e historiales de producto/categoría (16.ª/17.ª entidades), gating `catalogo`, matriz 55→60. **017:** invitaciones Clerk persistidas y gobierno de Administradores, matriz 55.
- **Enmienda T-17 de la 012 (22/Oct/2026):** `/administracion` se presenta como pestañas ARIA (`tablist`, 4 `tab`, `tabpanel` con `aria-labelledby`, flechas circulares y `tabindex` roving) sin tocar `administracion.routes.ts`, guards, backend ni contratos; **la 012 sigue cerrada**. `ng test` **466** (20 casos nuevos en `administracion-nav.component.spec.ts`), `ng build` limpio (`main-KWQKKL6Q.js`); recorrido 4200 y humo 8080 en `012-gestion-administrativa/evidencia/README.md` §«Enmienda T-17» (capturas 19–28).
- **Base consolidada:** `database/` tiene solo `01_esquema.sql` (control 22 tablas + 19 por tenant) y `02_datos_semilla.sql` (`014.1` con guardia fail-closed). Sin migraciones: reset = `down -v` + `up -d`.
- **Entorno local (22/Oct/2026, rama `ricardo`):** Python 3.12 + `backend/.venv` (`requirements.txt` + `requirements-dev.txt`), `frontend/node_modules`, `.env` desde `env.example` (claves Clerk vacías) y stack Docker reconstruido con volumen QA recreado: `pytest` 1405/77. Puerto 8080 estaba tomado por un `httpd` local (PID 4228, requirió UAC para detenerlo).
- **Enmienda de autoatribución de tickets (22/Oct/2026) — cerrada:** `TicketCrear.usuario_id` es opcional e ignorado; el alta atribuye siempre a la identidad de sesión (sin 404/422 por usuario) y ancla ticket/detalle a la institución de sesión con el orden institución → productos (404 ajeno) → sede del departamento (409). El modal muestra «Solicitante (sesión)» en solo lectura sin selector y el body omite `usuario_id`; `TicketDespacho.usuario_id` sigue obligatorio. Suites: `pytest` SQLite **1403/77/0**, gated PG16 **1480/0/0** (`apt_erp` intacta en `014.1`), `ng test` **470**, `ng build` limpio (`main-QNRFXFUT.js`, antes `main-KWQKKL6Q.js`); 4200 con altas reales de Administrador y Solicitante; humo 8080 reconstruido. Evidencia en `003-modal-ticket/evidencia/README.md` (referenciada desde 007 y 008).

## Feature 019 — decisiones clave
- **Ámbito completo, sin heredar filtros:** el detalle ignora sede/departamento de la lista; Admin todas las sedes de su institución, Bodeguero su sede asignada, Solicitante la sede de su departamento. El cliente no elige ámbito.
- **Sedes inactivas incluidas:** no se filtra `Sede.activo`; sus filas aparecen y suman, y una sede asignada inactiva responde **200**.
- **Precedencia:** 401 → 403 matriz → 403 capacidad → 403 institución → **409** sede no resoluble → **404** producto → 200. La sede se resuelve **antes** del producto (409 con id inexistente, ajeno o retirado).
- **Capacidad `inventario`, no `catalogo`:** coexiste con `GET /inventario/productos/{id}` (solo catálogo). Con `catalogo` sí e `inventario` no, Gestión sigue visible y el detalle da 403.
- **Agregado del ámbito:** `stock_total` = suma de las sedes devueltas; `es_critico` solo con esas sedes (vacío = saldo 0). `stock_sede` es la única fuente; nunca el `inventario` legado.
- **Retorno `?tab=gestion`:** solo para el Administrador que llega desde Gestión; el query param es navegación, no autorización (`gestionVisible()` manda).

## Decisiones vigentes (018/014/012/011)
- **018:** `sede_id` es filtro dentro de `condicion_stock` (antes del `outerjoin`, sin lookup previo) y no contradice el 404 de recurso de `/inventario/stock`. «departamento = sede»: no hay saldo departamental. Franja de indicadores solo server-side.
- **014:** nunca producto activo bajo categoría inactiva; baja de categoría → 409 si tiene activos; baja de producto exige saldo cero en `stock_sede`. Idempotencia sin motivo = 200 sin historial, precede a 422/409.
- **012/011:** `control.institucion.activo` gobierna el routing; 6 capacidades cerradas; `stock_sede` es la única fuente de saldo operativo. **013:** `Anulado` no sella `fecha_cierre` ni toca stock.

## Aprendizajes y errores a evitar
- **Filtro de lista ≠ recurso:** `sede_id` en `/inventario/existencias` responde 200/`[]`; no añadir lookup previo de sede.
- **Detalle ≠ producto:** el detalle nuevo usa `inventario` y devuelve stock; `/productos/{id}` sigue bajo `catalogo`. No unificar ni mover el gating.
- **Criticidad del detalle** se calcula sobre las sedes devueltas; `_es_producto_critico` con `sedes: []` evalúa 0 ≤ mínimo. Nunca sobre saldo fuera de ámbito.
- Cierre = verificación (AGENTS §8.5–§8.7): los dos puertos; 8080 exige `docker compose build frontend`; el backend recarga solo; grep de coherencia sobre AGENTS/MEMORY/skills.
- **Contratos externos:** la API real de Clerk `GET /v1/invitations` devuelve lista desnuda, no `{"data":[…]}`; verificar contra la API real.
- **La semilla limpia no crea al Superadmin:** `control.usuario` queda vacía y el bootstrap no se invoca al arrancar.
- Tests PostgreSQL **gated** (`POSTGRES_TEST_URL`); SQLite no valida esquemas/namespaces ni FK compuestas. Bases desechables; `apt_erp` nunca se toca.
- Toda mutación exige actor **persistido** (FK del historial); fixtures con sonda `9999` deben usar un usuario real.
- Edge: `CHROME_BIN` + `--watch=false --browsers=ChromeHeadless` (nunca `npm test`). PowerShell: `pg_dump` con `cmd /c`; `curl.exe` conserva backslashes (usar archivos de body).
- Clerk por HTTP sin navegador: dev browser + sign-in ticket BAPI + `Origin: localhost:4200` (exige `azp`); código de prueba `424242`. Tokens ~60 s.
- `resolver_contexto_solicitud` sin `abrir_sesion_tenant` lee la versión de **control**; el gated debe cablear `abrir_sesion_tenant=crear_sesion_esquema`.
- Specs Angular: con `provideRouter([])` el click de un `routerLink` no actualiza `router.url`; probar el `href` con espía a `navigateByUrl`.
- **Pestañas ARIA sobre Router:** derivar la pestaña activa de `Router.url` (sin query/fragmento) y activar el anchor destino con su propio `RouterLink` (`click()`), nunca con `navigateByUrl`: así se conservan href real, clic central y apertura en pestaña nueva.
- **Autoría del ticket = identidad de sesión:** no validar `usuario_id` del alta como referencia (no 404/422 por ese campo) ni usar `usuario.sede_id`; la sede sale de `departamento.sede_id` (409 si falta). El selector de solicitante no se reintroduce.
- **Carreras gated:** el `Barrier` de arranque no fija el orden del lock; la poseedora confirma la adquisición (`threading.Event`) y la contendiente espera a bloquear.

## Próximos pasos
- Backlog posterior al Sprint 6: **015** informes PDF/Excel y **016** notificaciones in-app. **Hito 2:** 11/Dic/2026.
- **Diagramas de casos de uso (21/Oct/2026):** 5 HTML en `docs/diagramas/` y 5 PNG a 2x; 26 casos en 5 paquetes; 015/016 marcados `PLAN`.
- **Modelo 4+1 (23/Oct/2026, rama `ricardo`):** 8 diagramas en `docs/diagramas/4+1-kruchten/` — lógica (2 clases + secuencia), procesos (2 actividades), desarrollo (componentes + paquetes) y física (despliegue) — con HTML + PNG @2x, `00-indice.html` y `README.md`; la vista de casos de uso sigue fuera, en `docs/diagramas/`.
- Hallazgo abierto: la semilla no trae Administrador `+clerk_test`. Aviso de accesibilidad preexistente en el buscador operativo de inventario (input sin `id`/`name`).
