# Feature 007: Control de acceso por roles y retiro de credenciales locales

**Estado:** Cerrada y verificada  
**Release:** 2.0 — Sprint 3  
**Tipo:** Autorización y saneamiento de credenciales

> **Enmienda posterior al cierre (22/Oct/2026):** la Feature 007 permanece cerrada y
> verificada. Esta enmienda posterior solo ajusta presentación/contrato de alta de ticket;
> no cambia la matriz de roles, DDL, dependencias ni permisos por operación.

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

La fila de `POST /tickets/` conserva la matriz aprobada, con la semántica de
autoatribución establecida por la enmienda posterior de 22/Oct/2026; los roles permitidos
no cambian.

**Transcripción histórica:** la fila de `POST /tickets/` refleja la regla posterior de
autoatribución de la enmienda de 22/Oct/2026; no hubo cambio de roles permitidos.

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
| `POST /tickets/` | ❌ 403 desde Feature 008/017 | ✅; autoatribución de sesión, `usuario_id` opcional e ignorado si se envía | ✅; autoatribución de sesión, `usuario_id` opcional e ignorado si se envía | ✅; siempre a su nombre, `usuario_id` opcional e ignorado si se envía |

> **Nota de enmienda:** esta fila mantiene los permisos preexistentes, pero su semántica
> de atribución sustituye la decisión histórica de elegir solicitante en D-3.
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

### Enmienda D-8 — Todo ticket queda atribuido a la identidad autenticada

Para cada rol autorizado a ejecutar `POST /tickets/` según la matriz vigente, el servidor
establece `usuario_id` con la identidad autenticada, sin aceptar selección de solicitante.
El campo de payload `usuario_id` pasa a opcional y cualquier valor recibido se ignora
silenciosamente: omitirlo no es 422, enviar otro valor no es 403, y un valor inexistente o
ajeno no produce 404 por usuario. La regla de pertenencia institucional ahora se aplica a
la identidad del actor/autor, no a un usuario seleccionado; la matriz de permisos no se
abre a roles nuevos ni a operaciones antes denegadas.

**Por qué:** la autoría debe corresponder a la sesión que realiza la acción. El selector
contradice esa regla para Administrador/Bodeguero y era redundante para Solicitante, a
quien el servidor ya autoatribuía.

### Enmienda D-9 — El formulario identifica al autor sin permitir elegirlo

La UI de creación no presenta selector ni control editable `usuario_id`; muestra como
información no editable el nombre, apellido y correo de `AutenticacionService.identidad()`
(respuesta `/auth/me`). Esa identidad no contiene departamento, por lo que no se añade una
consulta adicional ni se afirma que el campo muestre el nombre departamental. El catálogo
`solicitantes` se conserva para listados y detalle, aunque deje de poblar selector de alta.

**Por qué:** interfaz y contrato deben expresar la misma autoría inmutable y evitar una
opción visual que el servidor no debe honrar.

### Enmienda D-10 — El ámbito organizacional del alta sigue a la identidad

El ticket se ancla a institución y departamento de la identidad de sesión; su instantánea
de sede sale del `departamento.sede_id` de esa identidad. Si el departamento no tiene sede,
el alta responde 409 sin fallback, también para Administrador o Bodeguero; si tiene sede,
se crea usando esa sede. La semilla vigente tiene departamentos con sede para todos sus
Administradores y Bodegueros de roles 2 y 3 (usuarios 1, 3, 4, 10 y 6, 7, 12); los
Bodegueros 6, 7 y 12 tienen además asignación de usuario a sede, pero esa asignación no
sustituye la regla de sede del departamento del alta. Superadmin conserva el 403 de la
matriz actual de Feature 008/017.

**Por qué:** el contexto efectivo se deriva del usuario local y no puede seleccionarse en
el cuerpo. `_sede_vigente_de_solicitante` sigue tomando la sede del departamento del
usuario autor.

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
8. Solicitante solo consulta tickets propios. Al crear, todo rol autorizado queda
   atribuido a su identidad autenticada: `usuario_id` es opcional y, si se envía, se
   ignora sin error. La institución y sede del ticket se derivan de esa identidad; una
   sede departamental ausente conserva el 409 de Feature 011. Superadmin continúa sin
   permiso para el alta. En `GET /tickets/catalogos`, `solicitantes` se conserva según el
   alcance vigente del rol; la lista no constituye autoridad de autoría.
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
  recibe solo tickets propios. CUANDO un rol autorizado ejecuta `POST /tickets/`,
  ENTONCES el ticket se atribuye a la identidad autenticada, con payload `usuario_id`
  opcional e ignorado si se envía, sin 422/403 ni 404 por ese campo incluso si su valor
  es inexistente o ajeno. Administrador y Bodeguero crean bajo su propia identidad y el
  ámbito institucional/sede se deriva de ella; Superadmin conserva 403 conforme a la
  matriz. No se permite elegir otro autor. Si el departamento de sesión carece de sede,
  el alta conserva 409; con sede, usa esa sede. Si Solicitante invoca `PATCH /tickets/{id}/estado` o
  `POST /tickets/{id}/despacho`, recibe 403 por falta de permiso general. Si una
  operación de ticket permitida intenta acceder a un ticket existente de otro usuario,
  recibe 404 igual que para un id inexistente y no modifica datos. Esta formulación de
  autoatribución reemplaza la decisión histórica de conservar `TicketCrear` obligatorio
  para otros roles y permitirles elegir solicitante.
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
  otros roles se conserva la lista de lectura dentro del alcance aplicable. La lista no
  alimenta la autoría del alta (enmienda D-9); Superadmin sigue sin permiso a la operación.
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
  tickets, compatibilidad aditiva de `TicketCrear` (`usuario_id` opcional e ignorado para
  todos los roles autorizados), alcance
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
| AC-6 | Evidencia vigente tras la enmienda (Actualización 22/Oct/2026: reescritura ejecutada): `test_tickets_alcance.py::test_solicitante_lista_solo_sus_tickets`, `::test_solicitante_crea_y_se_atribuye_su_identidad`, `::test_roles_autorizados_atienden_la_identidad_de_sesion` (payload con `usuario_id` omitido, propio, ajeno e inexistente → 201 y autoría de sesión), `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`, `::test_administrador_crea_para_solicitante_propio_201`; más PATCH/despacho ajenos (`::test_administrador_patch_ticket_ajeno_404_sin_mutar`, `::test_bodeguero_despacho_ticket_ajeno_404_sin_mutar`) y permisos. |
| AC-7 | `test_permisos_endpoints.py::test_rol_sin_permiso_recibe_403` (Bodeguero en usuarios/productos → 403); `test_ambito_institucional.py::test_bodeguero_ajeno_existencias_solo_su_institucion`, `::test_movimientos_bodeguero_solo_su_institucion`, `::test_registrar_movimiento_en_inventario_ajeno_responde_403_sin_mutar`; `test_tickets_alcance.py::test_bodeguero_lista_solo_su_institucion`, `::test_bodeguero_despacho_propio_200_sigue_transaccional`. |
| AC-8 | `test_ambito_institucional.py::test_administrador_existencias_acota_a_su_institucion`, `::test_superadmin_existencias_es_global`, `::test_existencias_departamento_ajeno_responde_403`, `::test_rol_limitado_sin_institucion_resoluble_responde_403`, `::test_instituciones_administrador_solo_la_propia`, `::test_usuarios_administrador_solo_su_institucion`; `test_tickets_alcance.py::test_administrador_lista_solo_su_institucion`; `ambito_service.py` deriva `usuario → departamento → institución` y 403 si no resuelve. |
| AC-9 | `test_permisos.py::test_matriz_cubre_exactamente_las_operaciones_de_d3`, `::test_sin_sesion_responde_401`, `::test_denegacion_autenticada_es_403_y_no_401`, `::test_dependencia_concede_o_deniega_segun_matriz` (parametrizado por operación/rol); `test_permisos_endpoints.py::test_inventario_de_rutas_igual_a_la_matriz_d3`, `::test_denegacion_no_muta_datos`; `test_tickets_alcance.py::test_catalogo_solicitante_solo_su_identidad`, `::test_catalogo_productos_y_stock_siguen_globales`. La semántica de `solicitantes` del catálogo es consulta, no selección para alta (enmienda). |
| AC-10 | `test_rol_asignable_usuarios.py::test_administrador_crea_usuario_con_rol_permitido`, `::test_administrador_no_puede_asignar_rol_prohibido` (403 sin creación), `::test_superadmin_puede_asignar_cualquiera_de_los_cuatro_roles`; regla en `usuario_service.py`, no en el router. |
| AC-11 | `database/01_esquema.sql` y `database/02_datos_semilla.sql` sin columna/valores `password` (10 usuarios de semilla intactos); comentario de autenticación "decorativa" de la semilla y docstring de `TicketDespacho` corregidos; verificado contra PostgreSQL 16 real (T7). |
| AC-12 | `test_retiro_password.py` (3 tests): `Usuario` sin columna, `UsuarioCrear` sin campo, `UsuarioRespuesta` sin publicar `password`; grep de runtime sin dependencia de `usuario.password`. |
| AC-13 | `database/99_migracion_retiro_password.sql` (`ALTER TABLE usuario DROP COLUMN IF EXISTS password`). Verificado en vivo (T13) sobre `compustock_db`/`apt_erp`: la tabla `usuario` queda con `usuario_id, nombre, apellido, correo, departamento_id, rol_id` (sin `password`); **12 usuarios y 10 tickets intactos**; segunda ejecución con `ON_ERROR_STOP=1` → `NOTICE: column "password" ... does not exist, skipping`, exit 0 (idempotente); instalación limpia verificada en T8. |
| AC-14 | `/auth/me` en vivo (Bearer real) → 200 con `IdentidadAutenticadaRespuesta`; autorización y operaciones de usuario corren sin consultar `password`; recorrido funcional 4200 (T12) con sesiones Clerk reales por rol. |
| AC-15 | Backend `pytest` **1405 passed / 77 skipped / 0 failed** (gated PG16 **1482 / 0 skipped / 0 failed**); frontend `ng test` **470 SUCCESS / 0 FAILED** (guards, espera de identidad/rol, acceso denegado y capacidades); OpenAPI en vivo publica `HTTPBearer` y 401/403 por operación (`test_permisos_endpoints.py::test_openapi_*`). Cobertura vigente de autoatribución del alta: `test_tickets_alcance.py::test_roles_autorizados_atienden_la_identidad_de_sesion`, `::test_solicitante_crea_y_se_atribuye_su_identidad`, `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`, `::test_administrador_crea_para_solicitante_propio_201`, y los de propiedad/403 (PATCH/despacho ajenos); UI en `tickets.component.spec.ts`. Actualización 22/Oct/2026: reescritura ejecutada; ver AC-18–AC-20. |
| AC-16 | Migración PostgreSQL verificada en vivo con conservación de conteos/IDs y repetición segura (AC-13); `pytest` 377 y `ng test` 140 verdes. |
| AC-17 | Este cierre: evidencia por AC, contrato `/openapi.json` (HTTPBearer + 401/403) comprobado en vivo, recorridos 4200 (funcional, escrituras reales) y 8080 (humo sobre imagen reconstruida `sha256:3862981…`, ruta directa `/acceso-denegado` → 200), y grep §8.7 sobre `AGENTS.md`/`MEMORY.md`/`.agents/skills/` con correcciones aplicadas. |

### Enmienda posterior al cierre: autoría de alta de tickets — 22/Oct/2026

#### Problema

El selector de solicitante permitía emitir tickets a nombre de otra persona, incongruente
con la identidad que inicia sesión. Para Solicitante ya era ineficaz porque el backend
sobreescribía el valor con su propia identidad; para Administrador y Bodeguero habilitaba
una autoría ajena.

#### Qué cambia

El backend autoatribuye incondicionalmente a la identidad autenticada en todos los roles
que ya están autorizados a crear tickets. `usuario_id` pasa a opcional: se acepta payload
sin ese campo y se ignora cualquier valor enviado, sin 422/403 ni 404 por referencia de
usuario. La UI sustituye el selector por un campo informativo no editable con nombre,
apellido y correo de la identidad de sesión; `/auth/me` no incluye departamento, por lo
que no se muestra ni se consulta de forma adicional.

#### Qué no cambia

No cambia la matriz de permisos ni se concede `POST /tickets/` a Superadmin, que conserva
403 según Feature 008/017. El catálogo `solicitantes` sigue en `GET /tickets/catalogos`
para listados/detalle; solo deja de poblar selector de creación. No cambia el resto de
`crear_ticket`: productos, prioridad, estado, transacción, detalles, historial y validación
de sede. La institución y sede se derivan de la identidad de sesión; sin sede en su
departamento el alta responde 409, con sede procede si las demás reglas se cumplen.

#### Por qué una enmienda

Es un ajuste posterior de contrato de autoría y presentación de un flujo ya cerrado; no
amplía ni redistribuye permisos y no requiere DDL ni dependencias. Se conserva la evidencia
de cierre original, marcando para reescritura únicamente las afirmaciones que el nuevo
contrato invalida.

#### Criterios de aceptación de la enmienda (AC-18–AC-20)

- **AC-18 — Atribución incondicional.** DADO Administrador o Bodeguero con permiso vigente, CUANDO crea un ticket sin `usuario_id` o incluye un valor propio, ajeno o inexistente, ENTONCES una solicitud válida responde **201** y `ticket.usuario_id` es el de la identidad de sesión; el valor enviado se ignora sin 422/403 ni 404 por ese campo. Institución y sede se derivan del usuario de sesión. Superadmin conserva 403 y la matriz no cambia.
  - *Evidencia (observada 22/Oct/2026):* `test_tickets_alcance.py::test_roles_autorizados_atienden_la_identidad_de_sesion` (Administrador/Bodeguero/Solicitante con `usuario_id` omitido, propio, ajeno e inexistente → 201 y autoría de sesión), `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`, `::test_administrador_crea_para_solicitante_propio_201`, `::test_solicitante_crea_y_se_atribuye_su_identidad`; `test_tickets_institucional.py::test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion` y `::test_crear_ticket_con_producto_ajeno_404_sin_parcial` (404 de producto conservado); `test_modal_ticket.py::test_ticket_con_usuario_inexistente_se_ignora_y_atiende_a_la_sesion`. Suites: SQLite **1405 passed / 77 skipped / 0 failed**, gated PostgreSQL 16 **1482 passed / 0 skipped / 0 failed**. Contrato: `TicketCrear.required` sin `usuario_id`, campo documentado como ignorado y `POST /tickets/` sin 404 por usuario; matriz **62** operaciones y Superadmin 403. Recorrido 4200: tickets 11 (usuario 13) y 12 (usuario 11) con body sin `usuario_id` → 201. Evidencia: [`evidencia/README.md`](evidencia/README.md).
- **AC-19 — Presentación del autor y catálogo.** DADO el modal de creación con identidad disponible, CUANDO presenta el autor, ENTONCES muestra en solo lectura nombre, apellido y correo de sesión; no hay selector ni control editable `usuario_id`, y el POST no requiere/envía ese campo. `GET /tickets/catalogos` conserva `solicitantes` para listados/detalle, pero no se usa como selector de autoría.
  - *Evidencia (observada 22/Oct/2026):* `tickets.component.spec.ts` cubre identidad visible en solo lectura, ausencia del selector y del control `usuario_id`, y body sin ese campo; `ng test` **470 SUCCESS / 0 FAILED** (Edge 155) y `ng build` limpio (`main-QNRFXFUT.js`). El catálogo `GET /tickets/catalogos` conserva `solicitantes` (`test_modal_ticket.py::test_catalogos_responde_200_con_las_cuatro_listas`, `::test_solicitantes_traen_departamento_y_orden_por_apellido`) y alimenta listados/detalle, no el alta. Recorrido 4200: campo «Solicitante (sesión)» con nombre y correo de la identidad, sin selector; POST sin `usuario_id`. Humo 8080 tras rebuild con el mismo campo. Evidencia: [`evidencia/README.md`](evidencia/README.md).
- **AC-20 — Herencia del ámbito y sede.** DADO Administrador o Bodeguero cuya identidad está vinculada a un departamento con sede, CUANDO crea un ticket válido, ENTONCES el ticket y su instantánea de sede corresponden al departamento autenticado. Si no hay sede asignada, responde 409 sin ticket ni detalle parcial. No se usa `usuario.sede_id` como sustituto de `departamento.sede_id`.
  - *Evidencia (observada 22/Oct/2026):* `test_tickets_alcance.py::test_departamento_sin_sede_responde_409_sin_ticket_detalle_ni_historial` y `test_ticket_sede_011.py::test_crear_ticket_sin_sede_de_departamento_afecta_a_todos_los_roles_creadores` (409 sin ticket ni detalle), frente a `test_ticket_sede_011.py::test_crear_ticket_almacena_la_sede_del_departamento` (201 con la sede del departamento). En 4200 y en BD: Administrador (usuario 13, Dirección) → ticket 11 con `sede_id 1`; Solicitante (usuario 11, Biblioteca) → ticket 12 con `sede_id 2`; sin usar `usuario.sede_id`. Evidencia: [`evidencia/README.md`](evidencia/README.md).

#### Evidencia anterior afectada

En AC-6, AC-15 y su tabla de evidencia queda obsoleto el test histórico del `usuario_id`
obligatorio (hoy eliminado); también cambia la expectativa de
`test_administrador_crea_para_solicitante_propio_201`. La evidencia de AC-9 que describe
`solicitantes` seleccionables se debe limitar al alcance del catálogo y no a la autoría del
POST. Los tests de permisos denegados, propiedad del listado y matriz permanecen válidos.
Toda evidencia nueva quedó reescrita tras la enmienda en la fase de implementación.

**Actualización 22/Oct/2026:** reescritura ejecutada; la evidencia observada de AC-18…AC-20
está en los propios AC y en [`evidencia/README.md`](evidencia/README.md).

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
- **Exposición de datos del catálogo o escalada de rol:** limitar el catálogo de lectura
  conforme al rol y restringir roles asignables por Administrador;
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
