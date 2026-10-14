# Feature 007: Control de acceso por roles y retiro de credenciales locales

**Estado:** Cerrada y verificada  
**Release:** 2.0 — Sprint 3  
**Tipo:** Autorización y saneamiento de credenciales

## 1. Problema

La Feature 006 incorporó Clerk como autoridad de autenticación y expone el rol local
resuelto en la identidad autenticada. Sin embargo, dicho rol todavía es informativo:
las rutas de negocio permiten acceso a cualquier usuario con sesión y los permisos
no se verifican al invocar directamente la API. Esto deja expuestas operaciones
administrativas, de bodega y de solicitud a identidades que no deberían utilizarlas.

Además, el campo `usuario.password` conserva credenciales de texto plano que no se
usan desde la integración con Clerk. Mantenerlas en el esquema, semilla y contratos
de usuario crea una copia innecesaria y riesgosa.

## 2. Objetivo

Autorizar las operaciones y vistas de Compustock ERP según el rol local de la identidad
autenticada, tanto en la navegación como en las solicitudes directas a la API; denegar
el acceso no permitido con una respuesta comprensible. Retirar el campo de contraseña
local del modelo funcional y de las bases, preservando los demás datos existentes.

## 3. Alcance

### Dentro

- Roles presentes en la semilla: `Superadmin`, `Administrador`, `Bodeguero` y
  `Solicitante`. Se mantienen como roles distintos; `Admin` es solo una abreviatura
  documental de `Administrador`, no un alias ni una normalización runtime.
- Aplicar la política de roles a las rutas de Angular y a las operaciones de negocio
  de backend. La política no confía en que la interfaz o el guard oculten operaciones.
- Acceso global del Superadmin. Administrador y Bodeguero quedan limitados a su propia
  institución para tickets, inventario y movimientos; Solicitante consulta el inventario
  de su institución derivada de su departamento.
- Acceso del Administrador a usuarios y departamentos de su institución; sus lecturas de
  instituciones se limitan a la propia.
- Acceso de Bodeguero a dashboard, inventario y gestión operativa de tickets, incluido
  Kanban, cambios de estado y despacho, limitado a su institución.
- Acceso de Solicitante a dashboard, consulta de inventario/catálogo y creación y
  consulta únicamente de sus propios tickets. No administra usuarios, cambia estados
  ni despacha.
- El catálogo de productos/categorías y `stock_total` en `GET /tickets/catalogos` son
  globales en 007; el particionamiento institucional se implementa en 008.
- Restricción de `POST /usuarios/`: Administrador solo puede asignar `Bodeguero` o
  `Solicitante`; Superadmin puede asignar cualquiera de los cuatro roles.
- Denegación de navegación o solicitud de negocio a identidades con rol distinto al
  requerido, sin alterar el flujo de autenticación Clerk existente.
- Retiro de `usuario.password` de la definición de esquema, datos semilla, modelo
  funcional, contrato de creación de usuario y fixtures/pruebas que lo envían o
  requieren.
- Migración SQL reproducible para eliminar la columna de bases existentes sin perder
  las demás filas ni datos. Las nuevas instalaciones se crean desde el esquema y la
  semilla ya sin ese campo.

### Fuera

- Particionamiento lógico completo del SaaS, incluido el particionamiento del catálogo
  y stock, y aprovisionamiento/gestión del ciclo de vida de instituciones. Los límites
  operativos institucionales expresamente definidos en 007 sí están dentro.
- Gestión completa del ciclo de vida de usuarios (edición, borrado y aprovisionamiento)
  y cambios a la autoridad Clerk. La autorización de la creación existente y la
  restricción del rol asignable por Administrador sí son alcance de 007.
- Permisos granulares configurables por institución o usuario; esta entrega usa roles
  de catálogo.
- Cambios de interfaz ajenos a navegación/denegación por rol, como rediseños o nuevas
  capacidades operativas.
- Borrado de usuarios, migración de contraseñas a hashes o autenticación local como
  alternativa a Clerk.

## 4. Actores

- **Superadmin**: administrador global; accede a las áreas permitidas a los roles
  administrativos y puede consultar/modificar datos de cualquier institución.
- **Administrador Institucional (`Administrador`)**: gestiona usuarios y catálogos, y
  accede a las áreas concedidas, limitado a su institución en los datos operativos.
- **Bodeguero**: opera inventario y flujo de tickets, incluyendo preparación y despacho,
  únicamente en su institución.
- **Solicitante**: consulta catálogo/inventario de su institución y gestiona la creación
  y consulta de sus propios tickets.

## 5. Decisiones

### D-1 — Los cuatro nombres de rol son identidades distintas

`Superadmin` y `Administrador` no se colapsan en un alias. `Admin` en el roadmap es una
abreviatura documental del rol local `Administrador`; no existe alias ni normalización
runtime. Se conservan los cuatro roles de la semilla.

### D-2 — La autorización se exige en cliente y servidor

Los guards mejoran la navegación, pero no constituyen una frontera de seguridad: un
usuario puede llamar la API sin usar Angular. Por ello, una operación no autorizada
queda denegada también por backend, manteniendo Clerk como requisito previo.

### D-3 — La matriz de permisos es explícita por operación

La política de permisos y el límite institucional se describen operación por operación
en la matriz siguiente. Superadmin tiene alcance global. Administrador y Bodeguero solo
operan tickets, inventario y movimientos de su institución; Administrador también queda
limitado en usuarios/departamentos y consulta de instituciones. Solicitante consulta
existencias de su institución. El catálogo maestro de productos/categorías y
`stock_total` de `GET /tickets/catalogos` permanecen globales en 007 porque el modelo no
asigna institución a producto/categoría y el agregado suma inventario de todas las sedes.
Ese `stock_total` no representa stock institucional. El particionamiento de catálogo y
stock pertenece a Feature 008. La autorización se aplica en backend incluso si la ruta
o el control de interfaz resulta accesible.

| Operación | Superadmin | Administrador | Bodeguero | Solicitante |
|---|---|---|---|---|
| `GET /auth/me` | ✅ | ✅ | ✅ | ✅ |
| `GET/POST /usuarios/` y catálogos de apoyo (`/roles`, `/departamentos`, `/instituciones`) | ✅; asigna cualquier rol | ✅; usuarios/departamentos acotados, roles compartidos, instituciones solo propia; solo asigna Bodeguero/Solicitante | ❌ 403 | ❌ 403 |
| `GET /inventario/categorias`, `/productos`, `/existencias`, `/stock` | ✅ | ✅; catálogo maestro compartido, existencias/stock propios | ✅; catálogo maestro compartido, existencias/stock propios | ✅ solo lectura; catálogo maestro compartido, existencias/stock propios |
| `POST /inventario/productos` | ✅ | ✅, catálogo compartido | ❌ 403 | ❌ 403 |
| `GET /inventario/movimientos` y `POST /inventario/movimientos` | ✅ | ✅, solo inventario propio | ✅, solo inventario propio | ❌ 403 |
| `GET /tickets/catalogos` | ✅; productos y stock globales; solicitantes globales | ✅; productos y `stock_total` globales, solicitantes de institución propia | ✅; productos y `stock_total` globales, solicitantes de institución propia | ✅; productos y `stock_total` globales; solicitantes solo su identidad |
| `GET /tickets/` | ✅ | ✅, tickets de institución propia | ✅, tickets de institución propia | ✅, solo propios |
| `POST /tickets/` | ✅; elige solicitante con `usuario_id` obligatorio | ✅; elige solicitante con `usuario_id` obligatorio dentro de su institución | ✅; elige solicitante con `usuario_id` obligatorio dentro de su institución | ✅; siempre a su nombre, no puede elegir a otro |
| `POST /tickets/{id}/despacho` y `PATCH /tickets/{id}/estado` | ✅ | ✅, tickets e inventario propios | ✅, tickets e inventario propios | ❌ 403 |

Las solicitudes con parámetros `departamento_id` de otra institución para
`/inventario/existencias` o `/stock` responden 403 para los roles limitados; no se
silencia ni se aplica un filtro alternativo. Los catálogos de prioridad/estado y roles
son compartidos.

### D-4 — Límites institucionales desde 007

La institución de Administrador, Bodeguero y Solicitante se determina mediante
`usuario.departamento_id` → `departamento.institucion_id`. Administrador y Bodeguero
solo leen/operan inventario, movimientos y tickets de esa institución. El Administrador
además limita usuarios/departamentos a la misma institución e instituciones consultadas
a la propia. Solicitante solo consulta inventario de su institución y sus propios
tickets. En lecturas de `/inventario/existencias` y `/stock`, `departamento_id` ajeno
responde 403, no se filtra silenciosamente.

El catálogo maestro de producto/categoría no tiene pertenencia institucional en el
esquema y permanece compartido. `stock_total` en el catálogo de tickets también es un
agregado global de todas las sedes, no un valor institucional. Feature 008 definirá el
particionamiento lógico integral y el alcance institucional definitivo del catálogo y
stock.

Si Administrador, Bodeguero o Solicitante carecen de departamento o no se puede resolver
su institución, las operaciones que requieren ese ámbito responden HTTP 403. Nunca se
concede alcance global ni se omite el filtro. Superadmin es el único rol global.

### D-5 — Denegación de permiso y ocultación de ticket ajeno

Una sesión ausente o no válida mantiene el comportamiento de autenticación existente
(401). Una identidad autenticada sin permiso general para la operación recibe 403. Si
una operación de ticket permitida para el rol busca un ticket inexistente o un ticket
ajeno al Solicitante, responde 404 en ambos casos para no revelar su existencia. En
Angular, una ruta no permitida muestra estado dedicado de acceso denegado y no redirige
a login ni ejecuta la operación.

### D-6 — La asignación de rol respeta la autoridad del creador

En `POST /usuarios/`, Superadmin puede asignar cualquiera de los cuatro roles.
Administrador solo puede asignar `Bodeguero` o `Solicitante`; si intenta asignar
`Superadmin` o `Administrador`, la API responde 403 y no crea el usuario. La regla no
cambia el contrato de `TicketCrear`; la gestión completa de usuarios queda fuera.

### D-7 — La contraseña local se elimina, no se sustituye

Clerk es la única autoridad de autenticación; no se conserva ni se crea un hash local.
La columna deja de formar parte de los registros de usuario y se retira mediante una
migración reproducible, ya que alterar solamente el DDL no actualizaría bases
previamente inicializadas.

## 6. Reglas del flujo

1. La identidad debe autenticarse con Clerk y vincularse al usuario local conforme a
   Feature 006.
2. La autorización obtiene el rol local; valores desconocidos, ausentes o no resolubles
   no conceden permisos.
3. En Angular, una navegación de negocio requiere sesión. Si el rol no está permitido,
   la ruta no se activa y se presenta el estado de acceso denegado.
4. En backend, cada operación compara rol y acción antes de ejecutar lecturas o
   mutaciones. La denegación no cambia datos.
5. Para Administrador, Bodeguero y Solicitante, las operaciones con datos
   institucionales requieren resolver su institución desde el departamento; si falla,
   responden 403. Solo Superadmin tiene alcance global.
6. Administrador y Bodeguero acceden a tickets, inventario y movimientos solo de su
   institución. Administrador también limita usuarios/departamentos a esa institución.
   Solicitante consulta inventario de su institución y solo sus tickets. Los parámetros
   de departamento ajeno en `/inventario/existencias` o `/stock` responden 403.
7. El catálogo de productos/categorías y `stock_total` en `/tickets/catalogos` son
   globales en 007; el total agrega todas las sedes y no se presenta como stock
   institucional. El particionamiento corresponde a 008.
8. Solicitante solo consulta tickets propios. Al crear, el backend atribuye el ticket a
   su identidad autenticada e ignora/rechaza cualquier `usuario_id` alternativo. En
   cambio, Administrador, Bodeguero y Superadmin conservan el contrato existente:
   `usuario_id` sigue obligatorio y pueden elegir al solicitante, sujeto al límite
   institucional para Administrador/Bodeguero. Este comportamiento no cambia el contrato
   `TicketCrear` para esos roles. En los catálogos del Solicitante, `solicitantes` solo
   contiene su propia identidad.
9. Un Solicitante sin permiso general para PATCH estado o despacho recibe 403. En
   operaciones de ticket permitidas, un ticket ajeno e inexistente responden ambos 404.
10. En `POST /usuarios/`, Administrador solo asigna Bodeguero o Solicitante; Superadmin
    puede asignar cualquiera de los roles. La restricción no implica especificar alta o
    edición completa de usuarios.
11. La migración de contraseña elimina únicamente la columna obsoleta y deja inalterados
    usuarios, relaciones, roles y demás atributos.

## 7. Criterios de aceptación

### Roles y navegación

- **AC-1** DADO QUE la identidad tiene uno de los cuatro roles (`Superadmin`,
  `Administrador`, `Bodeguero`, `Solicitante`), ENTONCES se reconoce de forma
  diferenciada. `Admin` es solo abreviatura documental de `Administrador`, sin alias ni
  normalización runtime. Un rol ausente/desconocido no concede acceso.
- **AC-2** DADO QUE una persona autenticada navega a una sección permitida por su
  matriz, ENTONCES la ruta se activa; si no está permitida, no se activa y aparece el
  estado dedicado de acceso denegado, sin cerrar sesión ni redirigir a login.
- **AC-3** `Superadmin` y `Administrador` pueden acceder a dashboard, inventario,
  tickets y administración, conforme al límite institucional de AC-8. `Bodeguero` puede
  acceder a dashboard, inventario y operaciones de tickets, sin administración y solo
  sobre su institución. `Solicitante` puede acceder a dashboard, consulta de inventario,
  catálogo y creación/consulta de sus tickets, pero no a administración, Kanban, cambio
  de estado ni despacho.
- **AC-4** DADO QUE no existe sesión Clerk válida, CUANDO se intenta entrar a una ruta
  de negocio, ENTONCES se conserva la redirección existente a `/login` con retorno; la
  política de roles no suplanta ni debilita la autenticación.
- **AC-5** La tabla de rutas de interfaz es: `dashboard` (Superadmin, Administrador,
  Bodeguero, Solicitante), `inventario` (los cuatro, con alcance institucional según
  AC-8), `tickets` (los cuatro, con capacidades según AC-3/AC-6/AC-7) y
  `administracion` (Superadmin y Administrador). `/` conserva su redirección a
  `dashboard`, `/login` queda fuera del guard y `/health` sigue público sin cambio.

### Autorización de API y propiedad

- **AC-6** DADO QUE el rol es `Solicitante`, CUANDO ejecuta `GET /tickets/`, ENTONCES
  recibe solo tickets propios. CUANDO ejecuta `POST /tickets/`, ENTONCES el ticket se
  atribuye a su identidad autenticada y no puede elegir otro solicitante. Administrador,
  Bodeguero y Superadmin conservan `TicketCrear` vigente: `usuario_id` obligatorio y
  elección del solicitante, limitada a su institución para Administrador/Bodeguero.
  Si Solicitante invoca `PATCH /tickets/{id}/estado` o
  `POST /tickets/{id}/despacho`, recibe 403 por falta de permiso general. Si una
  operación de ticket permitida intenta acceder a un ticket existente de otro usuario,
  recibe 404 igual que para un id inexistente y no modifica datos.
- **AC-7** DADO QUE el rol es `Bodeguero`, ENTONCES puede listar, actualizar estado y
  despachar tickets, y leer/operar inventario y movimientos, solo dentro de su
  institución. Si intenta administrar usuarios o crear productos, backend responde 403.
- **AC-8** DADO QUE el rol es `Superadmin`, ENTONCES tiene alcance global para las
  operaciones permitidas. DADO QUE el rol es `Administrador` o `Bodeguero`, sus
  operaciones institucionales de tickets, inventario y movimientos se limitan a su
  institución; Administrador limita también usuarios/departamentos y solo consulta su
  institución en `/instituciones`. Solicitante consulta existencias de su institución y
  tickets propios. Un `departamento_id` ajeno en `/inventario/existencias` o `/stock`
  responde 403. Si la institución de Administrador, Bodeguero o Solicitante no se puede
  resolver para una operación institucional, responde 403. Solo Superadmin es global.
- **AC-9** La matriz de D-3 es el contrato backend por operación. Sesión ausente/no
  válida responde 401; rol sin permiso general responde 403. Para una operación de
  ticket permitida, ticket ajeno a Solicitante e id inexistente responden 404. En
  `/tickets/catalogos`, productos/categorías y `stock_total` son globales para todos los
  roles autorizados; `stock_total` suma todas las sedes y no se presenta como dato
  institucional. `solicitantes` para Solicitante contiene únicamente su identidad; para
  otros roles, solo solicitantes seleccionables dentro del alcance aplicable
  (global para Superadmin, institución propia para Administrador/Bodeguero).
- **AC-10** En `POST /usuarios/`, Administrador puede crear usuarios con rol
  `Bodeguero` o `Solicitante`; si intenta asignar `Superadmin` o `Administrador`, recibe
  HTTP 403 y no se crea usuario. Superadmin puede asignar cualquiera de los cuatro
  roles. La autorización no cambia el contrato de creación para Superadmin en otros
  aspectos y no amplía el alcance a edición/gestión completa de usuarios.

### Retiro de contraseña local y coherencia

- **AC-11** En una instalación nueva, el esquema no declara `usuario.password` y la
  semilla inserta usuarios sin columna ni valores de contraseña. Los comentarios de la
  semilla no afirman que la autenticación sea decorativa ni que la contraseña se migre
  posteriormente. El docstring de `TicketDespacho` no califica la autenticación como
  decorativa y el de `role.guard.ts` no lo describe como inerte ni pospone su política
  de roles a una implementación futura.
- **AC-12** El modelo funcional y el contrato de creación de usuario no declaran ni
  requieren contraseña; las pruebas/fixtures crean usuarios sin contraseña y no
  transmiten credenciales locales. Ninguna ruta de autenticación consulta esa columna.
- **AC-13** DADA una base existente con usuarios y columna `usuario.password`, CUANDO se
  ejecuta la migración SQL versionada, ENTONCES la columna se elimina, preservando
  usuarios, claves/relaciones y demás tablas; repetirla o ejecutarla sobre una base ya
  actualizada no causa pérdida adicional ni falla por ausencia previa de la columna.
- **AC-14** Después de la migración, Clerk, `/auth/me`, autorización y operaciones de
  usuario funcionan sin consultar ni depender de `usuario.password`.

### Verificación y cierre

- **AC-15** Las pruebas backend comprueban permisos permitidos/denegados por rol y
  operación, 401/403/404, ausencia de mutación ante denegación, propiedad y atribución de
  tickets, conservación del contrato `TicketCrear` para los demás roles, alcance
  institucional de Administrador/Bodeguero/Solicitante, restricción de roles asignables,
  filtro de solicitantes, stock de catálogo global y 403 si no se resuelve institución.
  Las pruebas frontend cubren guards, espera de identidad/rol y acceso denegado; las
  pruebas de contrato describen las denegaciones pertinentes.
- **AC-16** La verificación de migración demuestra que conserva usuarios y relaciones,
  elimina `usuario.password` y se puede aplicar nuevamente con seguridad. `pytest` y
  `ng test` permanecen verdes.
- **AC-17** El cierre registra evidencia verificable por AC, revisa el contrato de API
  y realiza recorridos en 4200 y 8080, reconstruyendo frontend antes de comprobarlo.
  Conforme a AGENTS.md §8.7, revisa `AGENTS.md`, `MEMORY.md` y `.agents/skills/` para
  actualizar referencias obsoletas; AC-11 cubre los comentarios/docstrings identificados.

### Evidencia de verificación al cierre

Suites finales (T13): backend `pytest` → **377 passed, 2 warnings**; frontend
`ng test --watch=false --browsers=ChromeHeadless` (Edge 155) → **140 SUCCESS**; build de
producción frontend OK (T11, 320.55 kB) y reconstruido en la imagen `sha256:3862981…` que
sirve el 8080.

| AC | Evidencia |
|---|---|
| AC-1 | Backend: `test_permisos.py::test_cuatro_roles_exactos_sin_alias_admin`, `::test_rol_desconocido_responde_403`, `::test_rol_ausente_responde_403`; literales sin alias en `backend/app/core/permisos.py` (`RolConocido`) y `frontend/src/app/core/auth/roles.ts`. Frontend: `role.guard.spec.ts::compara el rol exacto: \`Admin\` no es un alias de \`Administrador\``, `::deniega un rol ausente/desconocido`. |
| AC-2 | Frontend: `role.guard.spec.ts` (espera identidad, activa permitido, no activa rol distinto, `::ante denegación no redirige a login ni cierra la sesión`); `acceso-denegado.component.spec.ts` (estado dedicado, vuelve al dashboard sin enlazar a `/login`); `app.routes.spec.ts::expone el estado de acceso denegado sin exigir rol`. `RolGuard` en `frontend/src/app/core/guards/role.guard.ts` devuelve `RUTA_ACCESO_DENEGADO` sin activar la ruta. |
| AC-3 | `app.routes.spec.ts::permite dashboard, inventario y tickets a los cuatro roles (AC-5)`, `::restringe administración a Superadmin y Administrador (AC-3, AC-5)`; `tickets.component.spec.ts::oculta las operaciones de Kanban al Solicitante`, `::ofrece las operaciones de Kanban a Bodeguero, Administrador y Superadmin`. |
| AC-4 | `app.routes.spec.ts::protege las rutas de negocio con el guard de autenticación`, `::expone /login sin guard`; `AutenticacionGuard` conservado redirige a `/login` con retorno (regresión intacta desde 006). |
| AC-5 | `app.routes.spec.ts::conserva la redirección de la raíz a dashboard (AC-5)`, `::no expone ninguna ruta de registro`; `test_permisos_endpoints.py::test_rutas_publicas_no_exigen_sesion` (`/health`, `/docs`, `/openapi.json`). |
| AC-6 | `test_tickets_alcance.py::test_solicitante_lista_solo_sus_tickets`, `::test_solicitante_crea_y_se_atribuye_su_identidad`, `::test_otros_roles_conservan_usuario_id_obligatorio`, `::test_administrador_patch_ticket_ajeno_404_sin_mutar`, `::test_bodeguero_despacho_ticket_ajeno_404_sin_mutar`, `::test_administrador_patch_ticket_inexistente_404`; Solicitante en `PATCH .../estado` y `POST .../despacho` → 403 por `test_permisos_endpoints.py::test_rol_sin_permiso_recibe_403` (matriz `_INVENTARIO_Y_TICKETS`). |
| AC-7 | `test_permisos_endpoints.py::test_rol_sin_permiso_recibe_403` (Bodeguero en usuarios/productos → 403); `test_ambito_institucional.py::test_bodeguero_ajeno_existencias_solo_su_institucion`, `::test_movimientos_bodeguero_solo_su_institucion`, `::test_registrar_movimiento_en_inventario_ajeno_responde_403_sin_mutar`; `test_tickets_alcance.py::test_bodeguero_lista_solo_su_institucion`, `::test_bodeguero_despacho_propio_200_sigue_transaccional`. |
| AC-8 | `test_ambito_institucional.py::test_administrador_existencias_acota_a_su_institucion`, `::test_superadmin_existencias_es_global`, `::test_existencias_departamento_ajeno_responde_403`, `::test_rol_limitado_sin_institucion_resoluble_responde_403`, `::test_instituciones_administrador_solo_la_propia`, `::test_usuarios_administrador_solo_su_institucion`; `test_tickets_alcance.py::test_administrador_lista_solo_su_institucion`; `ambito_service.py` deriva `usuario → departamento → institución` y 403 si no resuelve. |
| AC-9 | `test_permisos.py::test_matriz_cubre_exactamente_las_operaciones_de_d3`, `::test_sin_sesion_responde_401`, `::test_denegacion_autenticada_es_403_y_no_401`, `::test_dependencia_concede_o_deniega_segun_matriz` (parametrizado por operación/rol); `test_permisos_endpoints.py::test_inventario_de_rutas_igual_a_la_matriz_d3`, `::test_denegacion_no_muta_datos`; `test_tickets_alcance.py::test_catalogo_solicitante_solo_su_identidad`, `::test_catalogo_productos_y_stock_siguen_globales`. |
| AC-10 | `test_rol_asignable_usuarios.py::test_administrador_crea_usuario_con_rol_permitido`, `::test_administrador_no_puede_asignar_rol_prohibido` (403 sin creación), `::test_superadmin_puede_asignar_cualquiera_de_los_cuatro_roles`; regla en `usuario_service.py`, no en el router. |
| AC-11 | `database/01_esquema.sql` y `database/02_datos_semilla.sql` sin columna/valores `password` (10 usuarios de semilla intactos); comentario de autenticación "decorativa" de la semilla y docstring de `TicketDespacho` corregidos; verificado contra PostgreSQL 16 real (T7). |
| AC-12 | `test_retiro_password.py` (3 tests): `Usuario` sin columna, `UsuarioCrear` sin campo, `UsuarioRespuesta` sin publicar `password`; grep de runtime sin dependencia de `usuario.password`. |
| AC-13 | `database/99_migracion_retiro_password.sql` (`ALTER TABLE usuario DROP COLUMN IF EXISTS password`). Verificado en vivo (T13) sobre `compustock_db`/`apt_erp`: la tabla `usuario` queda con `usuario_id, nombre, apellido, correo, departamento_id, rol_id` (sin `password`); **12 usuarios y 10 tickets intactos**; segunda ejecución con `ON_ERROR_STOP=1` → `NOTICE: column "password" ... does not exist, skipping`, exit 0 (idempotente); instalación limpia verificada en T8. |
| AC-14 | `/auth/me` en vivo (Bearer real) → 200 con `IdentidadAutenticadaRespuesta`; autorización y operaciones de usuario corren sin consultar `password`; recorrido funcional 4200 (T12) con sesiones Clerk reales por rol. |
| AC-15 | Backend `pytest` 377 passed; frontend `ng test` 140 SUCCESS (guards, espera de identidad/rol, acceso denegado y capacidades); OpenAPI en vivo publica `HTTPBearer` y 401/403 por operación (`test_permisos_endpoints.py::test_openapi_*`). |
| AC-16 | Migración PostgreSQL verificada en vivo con conservación de conteos/IDs y repetición segura (AC-13); `pytest` 377 y `ng test` 140 verdes. |
| AC-17 | Este cierre: evidencia por AC, contrato `/openapi.json` (HTTPBearer + 401/403) comprobado en vivo, recorridos 4200 (funcional, escrituras reales) y 8080 (humo sobre imagen reconstruida `sha256:3862981…`, ruta directa `/acceso-denegado` → 200), y grep §8.7 sobre `AGENTS.md`/`MEMORY.md`/`.agents/skills/` con correcciones aplicadas. |

## 8. Riesgos y mitigaciones

- **Confundir nombres de rol o asumir tres roles:** mantener explícitos los cuatro
  valores; `Admin` es abreviatura documental, no un alias runtime.
- **Permitir acceso vía llamada directa:** aplicar denegación de rol en backend,
  independientemente del guard.
- **Solicitante accede a ticket ajeno:** comprobar propiedad en operaciones permitidas y
  responder 404 igual que para ticket inexistente; operaciones no permitidas responden
  403.
- **Filtrado institucional incompleto:** aplicar límites derivados del usuario a
  inventario, movimientos y tickets para los roles limitados. No presentar el
  `stock_total` global de catálogo como institucional; catálogo/stock se particionan en
  008.
- **Exposición de solicitantes no seleccionables o escalada de rol:** filtrar catálogo
  del Solicitante a su propia identidad y restringir roles asignables por Administrador;
  verificar denegación 403.
- **Migración destructiva o no idempotente:** retirar solo la columna y probar
  preservación de datos y repetición segura antes de cerrar.
- **Matriz incompleta:** AC-9 exige matriz completa de operación/rol; no deducir permisos
  solo del nombre de una pantalla.

## 9. Restricciones y aclaraciones abiertas

- Clerk permanece como única autoridad de autenticación; la autorización usa el rol
  local ya resuelto en Feature 006.
- 007 implementa límites institucionales para Administrador, Bodeguero y Solicitante en
  datos operativos. El catálogo de productos/categorías y `stock_total` de
  `/tickets/catalogos` son globales; Feature 008 implementa el particionamiento integral
  del catálogo y stock.
- La institución se deriva del departamento obligatorio del usuario local. Si el
  vínculo no se resuelve para Administrador, Bodeguero o Solicitante en una operación
  institucional, se deniega con 403; no se eleva el alcance.
- La migración SQL versionada debe preservar los datos; su mecanismo y ubicación se
  resolverán en el plan técnico. No se permite descartar o reinicializar la base como
  sustituto de la migración.
- No se guardan secretos ni contraseñas reales en esta especificación.
