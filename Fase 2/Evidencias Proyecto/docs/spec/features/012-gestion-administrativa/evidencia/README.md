# Feature 012 — Evidencia del recorrido real (T13)

Recorrido funcional en **4200** (`npm start`, dev server) contra el backend en
contenedor (`uvicorn --reload`, volumen `./backend/app`) y PostgreSQL **real**
(`compustock_db` / `apt_erp`). Base migrada a **012.1** con
`database/migraciones/003_migracion_gestion_administrativa_012.sql` (respaldo
previo `respaldos/apt_erp_pre_012.dump`; sin borrado de datos).

Sesiones Clerk (instancia dev) con las cuentas `+clerk_test` (código de
verificación fijo `424242`):

- Superadmin: `superadmin.test+clerk_test@example.com` (identidad global en `control`).
- Administrador institucional: `admin.cfsnorte+clerk_test@example.com` (INST-002).

## Estado de la base al iniciar

- `control.version_esquema = 012.1`; 4 instituciones; 6 capacidades habilitadas por
  institución; 4 esquemas `tenant_*`.

> **Nota sobre las capturas:** existen las capturas `01`–`18` **salvo `11`**, que se perdió
> por timeout durante el recorrido (T13). Su contenido (desactivación/reactivación de sede)
> quedó acreditado por la verificación SQL y por la captura `12` de conflicto 409; no
> invalida la evidencia del recorrido.

## Recorrido por rol

### Superadmin (portal `/control`)

| Vista / acción | Resultado observado | AC |
|---|---|---|
| Login Clerk | nav sin enlace `/tickets`; con `/control` y `/administracion` (`02-dashboard-superadmin-nav.png`) | AC-3 |
| Dashboard SaaS | 4 instituciones activas, atribución nombre+id, sedes y usuarios por rol (`03`) | AC-4 |
| Instituciones | listado con RUT/dirección canónicos y estado (`04`) | AC-1 |
| Editar INST-004 | nombre `Municipalidad de Talagante (verif 012)` persistido en `control.institucion` **y** en el espejo tenant (2 columnas); recargado (`05`) | AC-1 |
| Deactivar INST-002 | `control.institucion.activo=false`; tenant, mapas y datos intactos (`17`) | AC-2 |
| Reactivar INST-002 | vuelve a `Activo`; routing restaurado | AC-2 |
| Capacidades INST-002 | las 6 visibles; `kanban` deshabilitada y re-habilitada (`06`) | AC-5 |
| `/tickets` directo | redirige a `/acceso-denegado`, sin Kanban (`07`) | AC-3 |

### Administrador institucional (`/administracion`)

| Vista / acción | Resultado observado | AC |
|---|---|---|
| Dashboard | rol Administrador, institución CFS Norte; nav con Tickets y Administración (`08`) | — |
| Sedes | lista con estado activo/inactivo; crear `Sede QA 012` → `sede_id 4` (`09`,`10`) | AC-6 |
| Sede: editar | `Sede QA 012 Editada` persistido | AC-6 |
| Sede: desactivar/reactivar | `activo=false`→`true` persistido | AC-11 |
| Sede: desactivar con dependencias | **409** `No se puede desactivar la sede: hay departamentos activos asignados a ella; reasigne su sede antes` (`12`) | AC-11 |
| Departamentos | lista con sede asignada o "Sin sede asignada" (`13`) | AC-7 |
| Departamento: crear/asignar sede | `Depto QA 012` creado; sede limitada a las del tenant; `Sede 3` asignada | AC-7 |
| Departamento: desactivar con usuarios | **409** `No se puede desactivar el departamento: tiene usuarios vinculados; reasigne o desactive esos usuarios antes` | AC-11 |
| Departamento: desactivar/reactivar | `activo=false`→`true` | AC-11 |
| Usuarios | lista con rol/departamento/estado reales (`14`) | AC-8 |
| Usuario: editar (sin correo) | `Felipe Soto` editado y revertido; estado activo/inactivo con `mapa_usuario_esquema.activo` | AC-8/AC-11 |
| Usuario Bodeguero + sede | rol Bodeguero → "Sin sede" → asignar `Sede 2` → `usuario.sede_id=2` | AC-9 |
| Encargados | estado vacío; asociar `Felipe Soto`; retirar (`15`) | AC-10 |
| `/tickets` | ruta y Kanban accesibles (`16`) | AC-3 |

### Aislamiento y gating (API directa con token de INST-002)

| Petición | Resultado | AC |
|---|---|---|
| `PATCH /api/v1/tickets/1/estado` (kanban apagada) | **403** sin mutación | AC-5 |
| `PUT /api/v1/organizacion/departamentos/1/sede` (depto de INST-001) | **404** | AC-12 |
| `PUT /api/v1/usuarios/1` (usuario de INST-001) | **404** | AC-12 |
| `GET /api/v1/organizacion/sedes` | **200** (solo INST-002) | AC-1 |
| `PATCH /api/v1/tickets/1/estado` (kanban re-habilitada) | **404** (deja de ser 403 de gating) | AC-5 |
| `/auth/me`, `/organizacion/sedes`, `/usuarios/` con INST-002 inactiva | **401** (token Clerk vigente) | AC-2 |
| Mismos tres con INST-002 reactivada | **401 → 200** | AC-2 |

## Bugs encontrados y corregidos

1. **`GET /auth/me` roto para usuarios de tenant en PostgreSQL (corregido).**
   El endpoint resolvía la identidad con la sesión de **control** (`get_db`), pero
   un rol limitado vive en el esquema de **su** institución (Feature 010): la
   relectura del usuario y de la institución efectiva no encontraba fila y
   respondía **401**. Efecto: el frontend de cualquier usuario no‑Superadmin caía
   en "Identidad no disponible" y `/administracion` no era utilizable. La suite
   ordinaria (SQLite, contexto lógico único) no lo detectaba.
   **Fix:** `GET /auth/me` usa `get_db_negocio` (tenant resuelto; `control` para
   Superadmin). **Test de regresión gated:**
   `tests/test_gestion_administrativa_http_postgres_012.py::test_auth_me_resuelve_identidad_de_tenant`
   (rojo sin el fix, verde con él).

## Hallazgos no resueltos (reportados)

1. **`/control` aterriza en `/control/alta`** para un Superadmin autenticado (de
   Feature 010), no en el dashboard SaaS. Es decisión previa, no una regresión.

> **Corregido tras T13:** `POST /api/v1/usuarios/` usaba la sesión de **control** (`get_db`) y
> sobre PostgreSQL un Administrador de tenant recibía **403** al dar de alta un usuario local.
> Se corrigió usando `get_db_negocio` (tenant) + `get_db` (control) y se añadió el alta en la
> vista de usuarios (`AC-8`/`AC-9`), con regresión gated
> `test_gestion_administrativa_http_postgres_012.py::test_alta_usuario_por_admin_de_tenant_persiste_en_su_esquema`
> y `ng test` en **292 SUCCESS**. Misma clase de defecto que `/auth/me`.

## Datos de prueba residuales (creados solo por la app)

- INST-002: sede `Sede QA 012 Editada` (`sede_id 4`, activa) y departamento
  `Depto QA 012` (`departamento_id 9`, activo, sede 3). Sin borrado (la
  desactivación es lógica y no se elimina historial).
- INST-004: nombre editado a `Municipalidad de Talagante (verif 012)`.
- `felipe.soto@cfsnorte.cl`: atributos restaurados; `sede_id=2` residual (inerte
  para un Solicitante).
