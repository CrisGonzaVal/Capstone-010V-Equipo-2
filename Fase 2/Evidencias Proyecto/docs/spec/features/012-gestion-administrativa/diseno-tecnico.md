# Feature 012 — Diseño técnico cerrado (T2)

Spec: [`spec.md`](spec.md) · Plan: [`plan.md`](plan.md) · Tareas: [`tasks.md`](tasks.md)

Este documento cierra, **antes de implementar**, las decisiones que el plan dejó
explícitamente abiertas a inspección (§2/§3/§6): el contrato de rutas, los DTOs,
la asociación capacidad↔operación y —sobre todo— el diseño ORM que impide que
`control.institucion.activo` se filtre al espejo tenant. Se apoya en inspección
real de `backend/app/models/`, `backend/app/core/permisos.py`,
`backend/app/services/{control,tenant,global,ambito}_service.py`,
`backend/app/api/dependencies.py`, `database/01_esquema.sql` y
`database/03_construir_tenants_011.sql`.

> **Estado:** T1 (justificación en `stack.md`) se dio por aprobada. Esta es la
> fase de diseño + pruebas rojas de T2. No implementa comportamiento.

## 1. Contrato de rutas `/control` (Superadmin)

Todas bajo `/api/v1/control`, autenticación Clerk y autorización por la matriz
central (solo `Superadmin`). `response_model`, `status_code` y errores explícitos
en cada operación (AGENTS §6, AC-13). El cliente **nunca** aporta esquema,
versión, rol, estado de institución ni capacidad de rol.

| Método | Ruta | Operación matriz | Éxito | Errores | DTO respuesta |
|---|---|---|---|---|---|
| POST | `/api/v1/control/instituciones/` | ya existente | 201 | 401/403/409/422/503 | `InstitucionAltaControlRespuesta` (ya existe) |
| GET | `/api/v1/control/instituciones/` | nueva | 200 | 401/403 | `list[InstitucionControlRespuesta]` |
| GET | `/api/v1/control/instituciones/{institucion_id}` | nueva | 200 | 401/403/404 | `InstitucionControlRespuesta` |
| PUT | `/api/v1/control/instituciones/{institucion_id}` | nueva | 200 | 401/403/404/409/422 | `InstitucionControlRespuesta` |
| PATCH | `/api/v1/control/instituciones/{institucion_id}/estado` | nueva | 200 | 401/403/404/409 | `InstitucionEstadoRespuesta` |
| GET | `/api/v1/control/dashboard` | nueva | 200 | 401/403/409/503 | `DashboardSaaSRespuesta` |
| GET | `/api/v1/control/instituciones/{institucion_id}/capacidades` | nueva | 200 | 401/403/404 | `list[CapacidadRespuesta]` |
| PUT | `/api/v1/control/instituciones/{institucion_id}/capacidades/{funcion}` | nueva | 200 | 401/403/404/422 | `CapacidadRespuesta` |

Decisiones:

- **`activo` es parte del ciclo de vida institucional** y se administra por
  `PATCH .../estado` con cuerpo `{"activo": bool}` (idempotente; reactivar = el
  mismo endpoint con `true`). No se crea un endpoint separado de reactivación:
  «desactivar/reactivar» son el mismo campo, y el contrato lo refleja (D-2).
- **`PUT` de institución** modifica los atributos canónicos (`nombre`, `rut`,
  `direccion`) y **sincroniza el espejo tenant solo con `institucion_id`+`nombre`**
  (D-1). Un atributo que no forme parte de esa pareja permanece exclusivamente en
  control y **no** causa rechazo ni se copia.
- **`{funcion}` inválida** (fuera de los seis identificadores cerrados) → **422**
  (validación de payload). Institución inexistente → **404**. Un cambio de
  capacidad no borra datos ni historial.
- **Dashboard SaaS**: recorre instituciones; las activas se agregan sobre lectura
  tenant en transacción consistente; las inactivas se listan con estado y **sin**
  métricas actuales y no provocan fallo; una activa inaccesible/incompatible hace
  fallar el agregado **completo** (nunca parcial). 409/503 documentados para esa
  frontera (D-5).
- El router sigue delgado: la lógica vive en `app/services/` (AGENTS §6).

### 1.1 DTOs de control (Pydantic v2, `extra="forbid"`)

En `backend/app/schemas/control_schema.py` (se amplía):

- `InstitucionControlRespuesta`: `institucion_id`, `nombre`, `rut`, `direccion`,
  `activo`, `nombre_esquema` (derivado, informativo). El estado persistido se
  publica (`activo`).
- `InstitucionEdicion`: `nombre` (obligatorio), `rut`/`direccion` opcionales;
  `extra="forbid"`. No admite `activo`, esquema ni versión.
- `InstitucionEstado`: `activo: bool`; `extra="forbid"`.
- `InstitucionEstadoRespuesta`: `institucion_id`, `activo`.
- `CapacidadRespuesta`: `funcion` (uno de los seis IDs), `habilitada: bool`.
- `CapacidadActualizar`: `habilitada: bool`; `extra="forbid"`.
- `DashboardSaaSRespuesta`: `total_instituciones_activas`, y
  `instituciones: list[InstitucionMetricasRespuesta]` con `institucion_id`,
  `nombre`, `activo`, `sedes`, y `usuarios_por_rol: dict[str,int]`.

### 1.2 Contrato Admin Institucional (nuevas operaciones organizacionales)

El CRUD organizacional de la 011 existe parcialmente (6 operaciones). Lo que
**falta** para AC-6…AC-11: alta/edición/baja lógica de sede y departamento, y
edición/estado de usuario local. Se fijan así (todas en el router
`organizacion`/`usuarios`, sesión `get_db_negocio`):

| Método | Ruta | Operación matriz | Éxito | Errores |
|---|---|---|---|---|
| POST | `/api/v1/organizacion/sedes` | nueva | 201 | 401/403/409/422 |
| PUT | `/api/v1/organizacion/sedes/{sede_id}` | nueva | 200 | 401/403/404/422 |
| PATCH | `/api/v1/organizacion/sedes/{sede_id}/estado` | nueva | 200 | 401/403/404/409 |
| GET | `/api/v1/organizacion/departamentos` | nueva | 200 | 401/403 |
| POST | `/api/v1/organizacion/departamentos` | nueva | 201 | 401/403/409/422 |
| PUT | `/api/v1/organizacion/departamentos/{departamento_id}` | nueva | 200 | 401/403/404/422 |
| PATCH | `/api/v1/organizacion/departamentos/{departamento_id}/estado` | nueva | 200 | 401/403/404/409 |
| PUT | `/api/v1/usuarios/{usuario_id}` | nueva | 200 | 401/403/404/422 |
| PATCH | `/api/v1/usuarios/{usuario_id}/estado` | nueva | 200 | 401/403/404/409 |

- Roles de matriz: `/organizacion/*` → `{Administrador}` (consistente con
  `_ORGANIZACION` de la 011); `/usuarios/*` → `{Superadmin, Administrador}`
  (consistente con las entradas `_ADMINISTRATIVOS` ya existentes de `/usuarios/`).
- **Estado del usuario local** = `mapa_usuario_esquema.activo` (D-3: «desactivar
  la asociación local impide que el correo resuelva al tenant»), **no** una
  columna nueva en `usuario`.
- **CLERK:** el alta/edición valida la existencia del correo con la costura
  `obtener_verificador_correo_clerk` ya existente; no crea ni modifica
  identidades Clerk.

#### 1.2.1 Reglas cerradas en T7 (desactivación e idempotencia)

El estado lógico se administra por `PATCH .../estado` con `{"activo": bool}`,
**idempotente** (repetir el estado actual devuelve 200 sin cambio). La
desactivación es **determinista**: si dejaría dependencias activas incompatibles
responde **409** con motivo concreto y no cambia el estado; si las referencias se
pueden preservar, desactiva.

- **Sede:** 409 si hay departamentos activos asignados a ella o Bodegueros
  asignados; si no, desactiva.
- **Departamento:** 409 si tiene usuarios vinculados; si no, desactiva.
- **Usuario:** 409 si es encargado de algún departamento (asociación vigente); si
  no, desactiva su vinculación local (`mapa_usuario_esquema.activo`).

DTOs de salida (T7): `SedeRespuesta` (con `activo`), `SedeEstadoRespuesta`,
`DepartamentoRespuesta` (con `sede_id` y `activo`), `DepartamentoEstadoRespuesta`,
`UsuarioRespuesta` (reutilizado en `PUT /usuarios/{usuario_id}`) y
`UsuarioEstadoRespuesta`. El `PUT /usuarios/{usuario_id}` **no** admite `correo`
(es la clave de identidad local): solo `nombre`, `apellido`, `departamento_id` y
`rol_id`.

> **HALLAZGO (reportado, no resuelto en T2):** AC-6 (estado activo/inactivo por
> sede) y AC-11 (desactivación lógica de **sede** y **departamento**) exigen un
> atributo de estado en `sede` y `departamento`, que hoy **no existe** en el DDL
> tenant (`01_esquema.sql`, `03_construir_tenants_011.sql`) ni en los modelos
> (`models/sede.py`). Es un cambio de modelo/DDL **tenant** que la justificación
> aprobada en `stack.md` (sección 012, control-only: `control.institucion.activo`
> + `funcion_institucion`) **no cubre**. Antes de T7, o bien `stack.md` incorpora
> la ampliación `sede.activo`/`departamento.activo` (tenant), o bien AC-6/AC-11 se
> reinterpretan. T2 **no** edita spec/plan/stack.md; se eleva al coordinador.

## 2. Asociación capacidad ↔ operación (mapa central)

Se centraliza en un módulo nuevo `backend/app/core/capacidades.py` (nunca una
lista duplicada en routers, plan §2). Contrato público fijado por T2:

```python
CAPACIDADES: frozenset[str]  # los seis IDs cerrados
MAPA_OPERACION_CAPACIDAD: dict[tuple[str, str], str]
def capacidad_de_operacion(metodo: str, ruta: str) -> str | None
```

Asociaciones (ruta → capacidad):

- `catalogo` (consulta/gestión del catálogo institucional):
  `GET /inventario/categorias`, `GET /inventario/categorias/{categoria_id}`,
  `GET /inventario/productos`, `GET /inventario/productos/{producto_id}`,
  `POST /inventario/productos`.
- `inventario` (existencias y movimientos):
  `GET /inventario/existencias`, `GET /inventario/stock`,
  `GET /inventario/movimientos`, `POST /inventario/movimientos`.
- `tickets` (creación y gestión del flujo):
  `GET /tickets/catalogos`, `GET /tickets/`, `POST /tickets/`.
- `kanban` (tablero operativo estado/despacho):
  `POST /tickets/{ticket_id}/despacho`, `PATCH /tickets/{ticket_id}/estado`.
- `dashboard` (dashboard analítico del tenant): `GET /dashboard/`.
- `gestion_organizacional` (sedes, departamentos, usuarios, encargados): todas
  las rutas `/organizacion/*` (las 6 de la 011 + las nuevas) y todas las
  `/usuarios/*` (existentes + nuevas de edición/estado).

**Sin gating de capacidad** (devuelven `None`): `GET /auth/me` y todas las rutas
`/control/*` (Superadmin SaaS). El gating es una **condición adicional** a la
matriz (rol sin permiso → 403 por matriz; capacidad apagada → 403 adicional sin
mutación), nunca un cambio de la matriz (D-6, AC-5).

Dependencia nueva `app.api.dependencies.requiere_capacidad(metodo, ruta)`: se
**declara en cada router** sobre las rutas que el mapa asocia a una capacidad
(T8), depende de `get_contexto_capacidad` y de `get_db` (control), resuelve la
capacidad de la institución del contexto y **403** si está apagada. No se aplica
sobre `/control/*` ni `/auth/me`.

Seam `app.api.dependencies.get_contexto_capacidad` (T8): resuelve el contexto
tenant de forma **tolerante** vía `tenant_service.resolver_contexto_solicitud`
contra la sesión de control. Si el contexto no resuelve (cualquier `ErrorTenant`,
incluida `ErrorInstitucionInactiva`) devuelve `None` y el gating se omite: la
denegación de routing (401/403) la sigue aplicando `get_db_negocio` con su propia
precedencia, de modo que el gating **nunca adelanta ni sustituye** ese fallo. El
gating solo actúa cuando hay tenant resuelto (`institucion_id` no nulo), que es
exactamente el caso en que la operación de negocio se ejecutaría. La identidad
global (Superadmin) devuelve `institucion_id=None` y tampoco se gatea.

> **Nota de sobrecarga (T8):** el gating añade un número **fijo** de consultas por
> petición a las rutas asociadas (resolución del contexto: identidad global +
> mapa de tenant), que no crece con el tamaño del resultado. La prueba de no-N+1
> de `/tickets` refleja ese sobrecarga fijo.

> **Hallazgo (T8):** el diseño §1.2 listaba `409` entre los errores de
> `POST /organizacion/departamentos`; la implementación de T7 no tiene regla de
> conflicto en el alta de departamento (no hay unicidad de nombre como en sede),
> así que el endpoint documenta 401/403/404/422 y no 409. Se registra para no
> presentar un contrato inexistente.
>
> **Hallazgo/defecto cerrado (T12):** el listado `GET /usuarios/` no publicaba
> `activo` ni `sede_id`, de modo que la vista de usuarios (T10) quedaba en
> "Estado no informado" y no exhibía la asignación (AC-8/AC-9). Además, al ser una
> operación de la Feature 007 previa al enrutamiento por tenant, usaba la sesión de
> **control** (`get_db`): en PostgreSQL real las tablas de negocio viven en el
> tenant, no en `control`, así que el listado no podía leer la sede del usuario ni
> resolver su institucion de forma correcta. T12 corrige ambos: `UsuarioRespuesta`
> expone `sede_id`/`activo` (lógica en `usuario_service.listar_usuarios`) y el
> endpoint lee el tenant con `get_db_negocio` y el mapa con `get_db`. No cambia el
> nombre del `response_model` (`UsuarioRespuesta`), por lo que el contrato de las
> operaciones previas se mantiene aditivo.
>
> **Hallazgo/defecto cerrado (T13):** el alta `POST /usuarios/` usaba la sesión de
> **control** (`get_db`) para la validación de rol/departamento y la creación de la
> fila local. En PostgreSQL real el usuario, los roles y los departamentos viven en
> el esquema de su institución, no en `control`, así que un Administrador de tenant
> recibía **403** (rol/departamento inexistentes en control) aunque la matriz lo
> autorizara. El endpoint pasa a usar `get_db_negocio` (tenant) para la validación
> y el INSERT, y `get_db` (control) para el mapa `mapa_usuario_esquema`; la lógica
> en `usuario_service.crear_usuario` recibe ambas sesiones (`db` tenant,
> `db_control` control). No cambia la ruta, los roles de la matriz, ni el
> `response_model`; es un cambio de sesión, aditivo en contrato. Regresión gated:
> `test_gestion_administrativa_http_postgres_012.py::test_alta_usuario_por_admin_de_tenant_persiste_en_su_esquema`
> (rojo sin el fix, verde con él). Frontend: `AdministracionService.crearUsuario` y
> el formulario de alta de `usuarios.component.ts` (con su sede opcional para un
> Bodeguero), cubiertos por los casos AC-8/AC-9 de `usuarios.component.spec.ts`.

> **Ajuste post-cierre (UX, D-6/AC-10) — rol del combo de alta:** descubierto en el
> recorrido visual de T13/T14. El **catálogo** `GET /usuarios/roles` sigue siendo
> **compartido** (D-5/AC-3): devuelve los cuatro roles a cualquier identidad porque
> la vista lo usa también para resolver el nombre del rol de cada usuario listado.
> Sin embargo, el **combo de rol del formulario de alta** ofrecía los cuatro a un
> Administrador, que en el backend solo puede asignar `Bodeguero`/`Solicitante`
> (`usuario_service._validar_rol_asignable` responde **403** —sin crear fila— ante
> `Superadmin`/`Administrador`; el Superadmin sí asigna los cuatro). Se alinea la
> interfaz **en el frontend** (`core/auth/roles.ts`: `ROLES_ASIGNABLES_ADMINISTRADOR`
> y `puedeAsignarRol`, computed sobre la identidad activa de `AutenticacionService`)
> en lugar de filtrar el endpoint: filtrar el catálogo rompería la resolución del
> nombre de rol de usuarios con rol no asignable (p. ej. otro Administrador del
> tenant) y tocaría el AC-3 de la 008, sin aportar autoridad —la frontera sigue en
> la API—. El **default** del alta pasa a ser el primer rol asignable (antes tomaba
> `roles[0]`, que podía ser no asignable). Cubierto por
> `usuarios.component.spec.ts` (Administrador → 2 opciones; Superadmin → 4; default
> asignable; recálculo al cambiar de identidad) y por `roles.spec.ts`
> (`puedeAsignarRol`). No se modifica la matriz, ni el contrato del endpoint, ni la
> semántica 403/409/422.

**Default sin fila (decisión T5):** el aprovisionamiento y la migración siembran
**siempre** las seis filas por institución, de modo que la ausencia de una fila
`funcion_institucion` no es una desactivación explícita. Siguiendo D-6 («no se
infiere el estado a partir de datos presentes»), una fila ausente se trata como
**habilitada**; la capacidad solo se deshabilita con `habilitada = False`
explícito. Mismo criterio para la institución canónica: la ausencia de fila
`InstitucionControl` no suspende; solo `activo = False` deniega. El servicio
`app.services.capacidad_service.capacidad_habilitada` es la única lectura del
estado de capacidad (nunca duplicada en routers).

## 3. Diseño ORM: `activo` canónico sin contaminar el espejo tenant

### 3.1 El problema (inspección real)

- El modelo `Institucion` (`models/institucion.py`) es **compartido**: lo usan la
  sesión de control (aprobación, `auth_service`) y las sesiones tenant
  (`dashboard_service` hace `JOIN` a `institucion`).
- El aprovisionamiento PostgreSQL (`control_service._provisionar_tenant_postgres`)
  crea el DDL tenant desde `Base.metadata.sorted_tables` excluyendo **solo**
  `MapaUsuarioEsquema`. Si `Institucion` recibiera `activo`, `create_all` lo
  impondría en **todos** los tenants y violaría D-1/plan §2.
- En SQLite (suite ordinaria) control y tenant comparten **una** tabla física:
  no hay namespaces, así que las lecturas del espejo y del canónico comparten
  tabla.

### 3.2 Decisión

**Separar el canónico de control del espejo tenant en dos modelos, en dos
`MetaData` distintos** (plan §2: «modelo explícito de control para institución
canónica y mantener el modelo tenant reflejando la tabla espejo»):

- **Espejo tenant** — `Institucion` se mantiene en `app/models/institucion.py`
  sobre `Base`, reducido a **exactamente** `institucion_id` + `nombre` (el
  espejo que el DDL tenant debe materializar). Sin `activo`.
- **Canónico de control** — módulo nuevo `app/models/control_canonico.py` con un
  segundo declarativo `BaseControl = declarative_base()` (MetaData propio) que
  declara:
  - `InstitucionControl` → tabla `institucion`, columnas
    `institucion_id` (PK), `nombre`, `rut`, `direccion`, `activo BOOLEAN NOT NULL
    DEFAULT TRUE`.
  - `FuncionInstitucion` → tabla `funcion_institucion`, PK compuesta
    `(institucion_id, funcion)`, `habilitada BOOLEAN NOT NULL`, FK local a
    `institucion.institucion_id`.

**Por qué dos `MetaData`:** dos modelos con el mismo nombre de tabla y
`schema=None` no pueden convivir en un único `Base.metadata` (SQLAlchemy los
considera la misma tabla). Un `MetaData` separado para el canónico elimina la
colisión **sin** fijar `schema="control"` explícito (que rompería la suite SQLite,
donde no existe el esquema `control`).

### 3.3 Cómo se evita `activo` en el tenant (verificable)

1. `activo` vive **solo** en `BaseControl.metadata`, que **no** participa del
   `create_all` del tenant. `_provisionar_tenant_postgres` sigue creando el DDL
   tenant desde `Base.metadata` (que ya solo tiene el espejo de dos columnas);
   la única exclusión existente (`MapaUsuarioEsquema`) se conserva.
2. El espejo tenant se crea/inserta con el modelo `Institucion` de `Base`
   (`institucion_id`, `nombre`); el registro canónico se inserta con
   `InstitucionControl` en la sesión de control.
3. En **SQLite** (contexto lógico único) ambas clases resuelven a la misma tabla
   física; para que la tabla compartida sea **superset**, la instrumentación de
   pruebas creará primero `BaseControl.metadata` (con `activo`) y después
   `Base.metadata` (el espejo se salta por `checkfirst`). Así las lecturas tenant
   (`Institucion`, 2 columnas) y las de control (`InstitucionControl`) funcionan
   sin recrear tablas.
4. Verificación dedicada: prueba de espejo que compara **columnas exactas** del
   espejo tenant (`{institucion_id, nombre}`), la presencia de `activo` y
   `funcion_institucion` **solo** en `BaseControl`, y —gated— un test PostgreSQL
   que confirma `control.institucion.activo` presente y `tenant.institucion`
   con dos columnas, sin `funcion_institucion` en el tenant.

**Alternativa descartada:** una sola clase con `activo` y `deferred=True` — el
`create_all` seguiría imponiendo la columna en el tenant y la omisión
dependería de no acceder al atributo; frágil y no verificable por columnas.

### 3.4 Notas de implementación (T3)

- El módulo real es `backend/app/models/control_canonico.py` con
  `BaseControl = declarative_base()`, `InstitucionControl`, `FuncionInstitucion`
  y `CAPACIDADES`. La tabla `funcion_institucion` lleva `CHECK` de los seis
  literales derivado de `CAPACIDADES` (fuente única).
- En el **contexto lógico único** de SQLite el mapa (`Base`) y el canónico
  (`BaseControl`) son `MetaData` distintos, de modo que el orden de INSERT no se
  infiere de la FK: `control_service` hace `flush()` explícito de la institución
  antes de crear el mapa, y el harness de pruebas hace lo propio.
- La **inicialización de las seis capacidades** ocurre en el aprovisionamiento
  (`control_service._inicializar_capacidades`), tanto en el camino lógico como en
  el PostgreSQL; es parte del alta, no CRUD de catálogo (que sigue en T6).
- `sede.activo` y `departamento.activo` (tablas tenant) se añadieron tras la
  aprobación de usuario registrada en `stack.md`; cierran AC-6/AC-11 y la
  desactivación es lógica y reversible.

## 4. Resolución de identidad con institución inactiva

`tenant_service.resolver_tenant_por_correo` pasa a consultar
`InstitucionControl.activo` **después** de resolver el mapa activo y **antes** de
comprobar `version_esquema`: si la institución es inactiva, levanta `ErrorTenant`
sin leer la versión del tenant. `resolver_contexto_solicitud` preserva al
Superadmin en control (identidad global) y aplica el estado solo a identidades
locales tenant. La capa HTTP normaliza una institución inactiva a **401**
(identidad local no resoluble), incluso con token Clerk previamente válido; la
reactivación restaura el routing solo con versión objetivo (D-2, AC-2).

## 5. Matriz central: las 28 entradas vigentes (referencia de no-modificación)

T2 **no** modifica ninguna de estas entradas; la prueba de no-regresión transcribe
la lista exacta (hoy en `MATRIZ_PERMISOS`):

```
GET    /api/v1/auth/me                                                   -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/usuarios/                                                 -> {Superadmin, Administrador}
POST   /api/v1/usuarios/                                                 -> {Superadmin, Administrador}
GET    /api/v1/usuarios/roles                                            -> {Superadmin, Administrador}
GET    /api/v1/usuarios/departamentos                                    -> {Superadmin, Administrador}
GET    /api/v1/usuarios/instituciones                                    -> {Superadmin, Administrador}
GET    /api/v1/inventario/categorias                                     -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/inventario/categorias/{categoria_id}                      -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/inventario/productos                                      -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/inventario/productos/{producto_id}                        -> {Superadmin, Administrador, Bodeguero, Solicitante}
POST   /api/v1/inventario/productos                                      -> {Administrador}
GET    /api/v1/inventario/existencias                                    -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/inventario/stock                                          -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/inventario/movimientos                                    -> {Superadmin, Administrador, Bodeguero}
POST   /api/v1/inventario/movimientos                                    -> {Administrador, Bodeguero}
GET    /api/v1/tickets/catalogos                                         -> {Superadmin, Administrador, Bodeguero, Solicitante}
GET    /api/v1/tickets/                                                  -> {Superadmin, Administrador, Bodeguero, Solicitante}
POST   /api/v1/tickets/                                                  -> {Administrador, Bodeguero, Solicitante}
POST   /api/v1/tickets/{ticket_id}/despacho                              -> {Administrador, Bodeguero}
PATCH  /api/v1/tickets/{ticket_id}/estado                                -> {Administrador, Bodeguero}
GET    /api/v1/dashboard/                                                -> {Superadmin, Administrador, Bodeguero, Solicitante}
POST   /api/v1/control/instituciones/                                    -> {Superadmin}
GET    /api/v1/organizacion/sedes                                        -> {Administrador}
PUT    /api/v1/organizacion/departamentos/{departamento_id}/sede         -> {Administrador}
PUT    /api/v1/organizacion/usuarios/{usuario_id}/sede                   -> {Administrador}
GET    /api/v1/organizacion/departamentos/{departamento_id}/encargados   -> {Administrador}
POST   /api/v1/organizacion/departamentos/{departamento_id}/encargados   -> {Administrador}
DELETE /api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id} -> {Administrador}
```

Total: **28**. Las operaciones nuevas de la 012 son aditivas (control SaaS y CRUD
organizacional) y no modifican roles de ninguna de las 28.

## 6. Pruebas rojas de T2 (fase TDD)

Escritas y en rojo por las ausencias previstas (T3+), nunca por import roto ni
sintaxis (patrón 010/011):

- `backend/tests/api/test_permisos_012.py` — matriz 012 (28 + nuevas) y no-regresión.
- `backend/tests/api/test_contrato_control_012.py` — `/openapi.json` de las rutas `/control`.
- `backend/tests/api/test_capacidades_gating_012.py` — mapa capacidad↔operación y gating 403.
- `backend/tests/api/test_institucion_inactiva_012.py` — institución inactiva → 401 antes de versión.
- `backend/tests/api/test_espejo_institucion_012.py` — espejo tenant de dos columnas y canónico control-only.
- `backend/tests/test_gestion_administrativa_postgres_012.py` — gated PostgreSQL: DDL/migración/nuevas columnas y capacidades.
