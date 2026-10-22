# Feature 011: Modelo organizacional

> **Nota de vigencia (19/Oct/2026):** este documento describe la feature tal como
> se cerró. Las migraciones que cita (`database/migraciones/*`) y el constructor
> `03_construir_tenants_011.sql` se retiraron del repo en la consolidación de la
> base: hoy `database/` solo tiene `01_esquema.sql` y `02_datos_semilla.sql`, y la
> base se reconstruye con `docker compose down -v` + `up -d`. La evidencia y las
> decisiones siguen siendo válidas; los nombres de archivos citados son
> históricos. Los tests gated citados (`test_migracion_modelo_organizacional_011.py`,
> etc.) se consolidaron en `test_instalacion_limpia_postgres.py`; los casos de
> migración se retiraron junto con los scripts.

**Fecha:** 17/Oct/2026  
**Estado:** cerrada (17/Oct/2026) — cierre formal confirmado tras recorrido en 4200 (escritura real) y 8080 (imagen reconstruida); validación reviewer: VEREDICTO APROBADO  
**Release:** 2.0 — Sprint 5  
**Tipo:** Evolución del modelo organizacional e inventario

## 1. Problema

El inventario actual se registra por departamento: cada fila de `inventario` identifica un producto y un departamento, con unicidad `(departamento_id, producto_id)`. Por ello, un mismo producto puede tener varias cantidades departamentales y no existe un saldo físico único por sede. La operación no puede representar directamente una bodega compartida por los departamentos de una sede ni resolver de forma consistente el stock que debe atender un ticket.

La Feature 010 aísla cada institución en su propio esquema PostgreSQL. La evolución debe conservar esa frontera: cada sede, departamento y saldo pertenece al tenant de su institución, sin referencias cross-schema.

## 2. Objetivo y alcance

Introducir sedes institucionales, sustituir el inventario departamental por existencias por sede, asignar cada departamento a exactamente una sede, asignar cada Bodeguero a exactamente una sede y permitir gestionar mediante API varios encargados de departamento. Se preservan la trazabilidad histórica y la consistencia del flujo de tickets y despachos.

### Dentro

- Entidad de dominio `sede` dentro del tenant de una institución.
- Entidad de dominio de stock por sede e insumo, que sustituye el inventario operativo por departamento. El total institucional se deriva como suma de los saldos de sus sedes.
- Una unidad de stock por sede, común para todos los departamentos de esa sede.
- Asignación operativa de cada departamento a una sede; la referencia `departamento.sede_id` es nullable para permitir estados incompletos, pero las operaciones dependientes requieren sede.
- Asignación operativa de cada Bodeguero a una sede; la referencia `usuario.sede_id` es nullable, pero las operaciones de stock del Bodeguero requieren sede.
- Relación muchos-a-muchos `departamento_encargado`: uno o más usuarios con rol Solicitante pueden ser encargados de un departamento y pertenecen al mismo departamento. La relación admite cero filas durante estados incompletos; el objetivo organizacional es al menos un encargado por departamento.
- API para gestionar asociaciones y retiros de encargados, y las operaciones mínimas de API indispensables para asignar departamentos/Bodegueros a sedes. No incluye vista administrativa.
- Consultas de existencias según ámbito: Solicitante por departamento/sede, Bodeguero por su sede, Administrador Institucional por institución y Superadmin con lectura global atribuida.
- Preparación de los cuatro tenants actuales con sedes y consolidación íntegra de saldos departamentales, preservando exactamente el total por producto y todo el historial previo.
- Verificación efectiva de que la capa de aplicación no expone ni permite usar sedes de otro tenant.
- Revisión explícita en el plan de la superación de la norma vigente de `stack.md` que afirma que no se elimina ni fusiona entidad de dominio, y propuesta de texto justificativo para su aprobación antes de implementar.

### Fuera

- Interfaz administrativa para sedes, departamentos, usuarios o encargados; corresponde a Feature 012.
- CRUD completo de sedes y departamentos. Esta feature solo incluye API mínima para asignar departamentos y Bodegueros a sedes, y para asociar encargados.
- Transferencias de stock entre sedes, varias bodegas por sede, lotes/series, inventarios físicos/cíclicos, reservas, compras o reposición automática.
- Lectura o escritura cross-tenant. La lectura global de Superadmin se limita a consultas autorizadas y conserva atribución institucional; no habilita escritura en tenants.
- Modificación, eliminación o reescritura de movimientos históricos.
- Cambios a Clerk o emisión de JWT propios.

## 3. Requisitos funcionales y decisiones

### D-1 — Sede pertenece a una institución y vive en su tenant

Cada sede pertenece a exactamente una institución. Su identidad y datos son locales al esquema tenant de esa institución; nombres repetidos en instituciones distintas son registros distintos. La capa de aplicación debe aplicar este ámbito en todas las operaciones de sede.

**Por qué:** la institución sigue siendo la frontera multi-tenant de Feature 010. El aislamiento por esquema no exime de verificar que la API resuelve y usa el tenant correcto.

### D-2 — Stock por sede sustituye el inventario departamental

La entidad operativa de stock por sede e insumo sustituye a `inventario` como ubicación del saldo vigente. Se consolida el stock departamental actual hacia la sede asignada a cada departamento. No se conserva un saldo institucional o departamental paralelo.

La nueva unicidad operativa es una fila por `(sede_id, producto_id)`. `departamento_id` deja de ser parte de la identidad del saldo vigente. `inventario.ubicacion` se deprecia como atributo de saldo y no se copia automáticamente a `sede.direccion`; solo se conserva como dato legado. La dirección de una sede se registra por su propio dato organizacional, no se infiere de ubicaciones de estantes.

Las filas históricas de `inventario` referenciadas por `movimiento_inventario.inventario_id` se conservan como registros legados inmutables, junto con sus identificadores y relaciones. No se redirigen ni se borran las FK históricas. El stock vigente se consulta y modifica exclusivamente en la entidad por sede. Los movimientos nuevos de negocio y de consolidación usan una nueva referencia nullable `movimiento_inventario.stock_sede_id`; `inventario_id` admite NULL para esos movimientos nuevos, mientras las filas y valores de `inventario_id` de los movimientos históricos y su FK permanecen intactos. No se reescribe ningún movimiento histórico.

**Por qué:** la sede, no cada departamento, es la ubicación de la bodega común. Mantener filas antiguas evita romper la cadena de auditoría, mientras la referencia nueva permite auditar operaciones actuales sobre la nueva granularidad sin invalidar los movimientos existentes.

### D-3 — Ampliación y superación explícita del modelo de doce entidades

`sede` y la entidad de stock por sede son nuevas entidades de dominio; con las doce entidades canónicas actuales, el modelo de dominio pasa a catorce. `departamento_encargado` es una tabla puente auxiliar de asociación, análoga en naturaleza auxiliar a `mapa_usuario_esquema`, y no se cuenta como entidad de dominio. El saldo operativo departamental de `inventario` queda sustituido; las filas legadas referenciadas por auditoría se conservan. Se incorporan las columnas `departamento.sede_id` (nullable), `usuario.sede_id` (nullable, para Bodeguero) y `ticket.sede_id` (instantánea nullable para compatibilidad con tickets legados), además de `movimiento_inventario.stock_sede_id` nullable. Los tickets nuevos siempre almacenan su sede al crearse.

El plan debe incluir, como prerrequisito de implementación, la declaración explícita de que queda superada la afirmación de `stack.md` §“Multi-tenant por esquemas PostgreSQL” según la cual ninguna entidad se elimina, fusiona o reasigna. La justificación propuesta debe cubrir: sustitución de granularidad departamental por sede; entidades de dominio y tabla auxiliar; claves y unicidades nuevas; las columnas `departamento.sede_id`, `usuario.sede_id`, `ticket.sede_id` y `movimiento_inventario.stock_sede_id`; conservación de filas legadas/FK y movimientos; reconciliación exacta de saldos; y total institucional derivado sin saldo duplicado. La aprobación de esta actualización de `stack.md` precede a cualquier implementación de modelos, DDL o migraciones.

**Por qué:** el modelo debe reflejar la bodega física compartida y no puede fingir que permanece inalterado. Las columnas nullable preservan compatibilidad de registros existentes; las precondiciones operativas impiden usar asignaciones ausentes. La aprobación previa mantiene coherencia entre norma y estructura ejecutable.

### D-4 — Encargado de departamento no es Bodeguero

“Encargado de departamento” nombra exclusivamente a un usuario Solicitante asociado a un departamento mediante `departamento_encargado`; admite varios por departamento y debe pertenecer al mismo departamento. No se usará “Encargado” a secas. Este concepto es distinto de “Bodeguero / Encargado de Suministros”, actor responsable de operar stock físico según la constitución.

El Administrador Institucional puede asociar o retirar encargados mediante API. La función de encargado no añade un privilegio ni cambia el rol Solicitante: su capacidad de consulta y emisión de tickets sigue sujeta a ese rol y a su departamento. La API valida rol y pertenencia al asociar; permite limpiar asociaciones incompatibles. Las consultas de encargados muestran solo asociaciones vigentes compatibles con un usuario existente, de rol Solicitante y perteneciente al departamento asociado. No se requieren triggers.

**Por qué:** la tabla puente representa la pluralidad y evita confundir responsabilidad departamental de solicitud con operación de bodega. La asociación administrativa es el punto de validación y las lecturas filtran relaciones obsoletas sin conceder capacidad adicional.

### D-5 — Asignaciones, ámbitos y sede inicial

`departamento.sede_id` y `usuario.sede_id` son nullable. Operativamente, cada departamento debe tener exactamente una sede para consultar stock o crear tickets, y cada Bodeguero debe tener exactamente una sede para operar existencias; si falta, la operación dependiente se deniega con error claro, sin fallback. El Administrador Institucional gestiona ambas asignaciones mediante la API mínima de esta feature.

Para que un tenant nuevo aprovisionado tras la Feature 011 nazca operativo, el aprovisionamiento de Feature 010 crea automáticamente una sede inicial llamada “Sede Central” en el esquema del tenant. Esto es bootstrap de datos organizacionales, no CRUD de sedes; el alta/edición/eliminación administrativa de sedes corresponde a Feature 012.

El Solicitante consulta disponibilidad de su departamento, que corresponde a la bodega única de la sede asignada al departamento. El Bodeguero consulta y opera existencias de su `usuario.sede_id`. El Administrador Institucional consulta existencias de todas las sedes de su institución y gestiona las asignaciones mínimas; no obtiene CRUD de sedes. Superadmin conserva solo lectura global autorizada y atribuida por institución, sin escritura de negocio en tenants.

Al crear un ticket se almacena en `ticket.sede_id` una instantánea de la sede vigente del departamento. El despacho usa esa sede almacenada, nunca vuelve a derivarla de la asignación actual del departamento. Reasignar el departamento afecta a tickets futuros; tickets abiertos y cerrados conservan la instantánea y los movimientos históricos. Cada operación de stock conserva la sede afectada en el movimiento correspondiente.

**Por qué:** la instantánea evita que cambios organizacionales posteriores redirijan tickets ya emitidos. La sede inicial permite operar tenants recién aprovisionados sin anticipar la UI CRUD de Feature 012.

### D-6 — Criticidad y contratos consolidados

El stock mínimo y la función de criticidad se evalúan por insumo y sede sobre el saldo físico de esa sede. Las consultas de `GET /inventario/existencias` exponen obligatoriamente sede y saldo. `GET /dashboard/` aplica las mismas fórmulas de KPI de Feature 009 sobre la nueva granularidad por sede: los KPI mantienen su semántica consolidada institucional, pero se calculan a partir de saldos por sede, sin conservar ni consultar cifras departamentales. Los tests de Feature 009 se actualizan para verificar esta misma semántica sobre el modelo nuevo, manteniendo atribución de filas/alertas a sede e institución donde corresponda.

**Por qué:** la alerta operativa identifica la bodega física que puede abastecer. Reutilizar las fórmulas de KPI evita cambiar su significado, mientras la nueva fuente de datos refleja exclusivamente el stock por sede.

### D-7 — Preparación determinista, cuadre exacto y auditoría inmutable

La preparación de tenants existentes usa este reparto fijo de sedes:

| Institución | Sedes creadas |
|---|---:|
| INST-001 | 2 |
| INST-002 | 3 |
| INST-003 | 4 |
| INST-004 | 2 |

Las sedes se ordenan por su identificador estable y los departamentos por `departamento_id` ascendente. El departamento de índice `i` (iniciando en cero) se asigna a la sede de índice `i mod N`, donde `N` es el número fijado para la institución. Esta regla produce la misma asignación en cada ejecución.

Antes de preparar cada tenant se mide, por `producto_id`, el total de referencia como la suma de las filas departamentales actuales de `inventario`. Para cada par `(sede, producto)`, el saldo inicial nuevo es exactamente igual a la suma de los movimientos nuevos de consolidación de tipo `ENTRADA` registrados contra esa fila. Después de preparar, por cada producto la suma de todos los saldos por sede debe ser exactamente igual al total de referencia medido antes. Las filas legadas de `inventario` y sus datos no cambian. Si cualquier igualdad no se cumple, la preparación aborta y no se declara exitosa.

Todos los movimientos históricos y sus referencias a filas legadas de inventario permanecen intactos: no se actualizan, eliminan ni reasignan. La consolidación se registra mediante movimientos nuevos de tipo `ENTRADA`, asociados por `stock_sede_id` a las filas por sede y con observación que identifica tenant, producto y operación de consolidación. Los movimientos legados conservan `inventario_id`; para movimientos nuevos, `stock_sede_id` es la referencia de auditoría y `inventario_id` queda nulo. El saldo consolidado se inicializa por esos movimientos y debe satisfacer las igualdades de reconciliación anteriores.

**Por qué:** el total previo por producto ofrece una referencia externa y no circular. La asignación round-robin es reproducible; los movimientos nuevos documentan la consolidación sin alterar el historial inmutable.

## 4. Reglas del flujo

1. Clerk autentica al usuario y Feature 010 resuelve el tenant; ningún parámetro, cuerpo o cabecera del cliente puede cambiarlo.
2. Sede, departamento, usuario, producto, ticket y saldo que participan en una operación deben pertenecer al tenant resuelto.
3. Un departamento debe tener una sede para consultar stock o crear tickets que requieran disponibilidad. Si no la tiene, la API responde **409** con error claro y no usa sede por defecto. La preparación garantiza asignación a todos los departamentos de INST-001..004.
4. El Solicitante consulta el stock de su departamento/sede. Ser encargado de departamento no amplía el ámbito ni añade permisos; la API de encargados valida compatibilidad al asociar y las consultas excluyen relaciones incompatibles vigentes.
5. El Bodeguero opera exclusivamente la sede asignada a su usuario. Sin sede asignada, las operaciones dependientes se deniegan con **409**.
6. El Administrador Institucional consulta todas las sedes de su institución y, mediante API, asigna departamentos a sedes, Bodegueros a sedes y encargados de departamento. No administra sedes con CRUD en esta feature.
7. Superadmin mantiene las lecturas globales existentes con atribución institucional y consistencia completa; no escribe en inventario, sedes, departamentos ni usuarios de tenants.
8. Al crear un ticket, se copia la sede vigente del departamento a `ticket.sede_id`. Si no tiene sede, el alta se rechaza con **409**. El despacho usa siempre la instantánea de sede del ticket, aunque el departamento se haya reasignado; tickets futuros usan la asignación vigente al momento de su creación. Los tickets legados sin instantánea no se despachan hasta que una migración les asigne sede de forma explícita y verificable.
9. El despacho verifica saldo suficiente en la sede almacenada en el ticket, descuenta stock, registra un movimiento nuevo mediante `stock_sede_id` y cambia el estado del ticket en una transacción atómica. Stock insuficiente causa **409** sin cambios parciales.
10. La preparación de INST-001..004 usa el número fijo de sedes de D-7 y la regla round-robin determinista; mide antes los totales por producto, consolida, registra movimientos nuevos de consolidación y comprueba las igualdades de reconciliación. No modifica filas ni movimientos legados.
11. La semilla fail-closed conserva su protección. En instalación limpia, el DDL canónico de control y la estructura tenant incluyen las entidades/columnas de esta feature antes de sembrar datos; `01_esquema.sql` corre antes que `02_datos_semilla.sql`. La semilla crea INST-001..004 y las sedes QA fijadas en D-7; no se usa para migrar una base existente.
12. Un identificador de sede inexistente o ajeno al tenant se oculta como **404**, conforme al patrón de Feature 008. Una sesión ausente devuelve **401**; un rol autenticado no autorizado devuelve **403**. Asociaciones incompatibles o duplicadas devuelven **409**; payloads mal formados o con campos inválidos devuelven **422**.

## 5. Criterios de aceptación

- **AC-1 — Visibilidad de sede entre tenants vía API.** DADO dos tenants operativos, CUANDO se crea una sede en Tenant A y se consultan o usan sus identificadores desde una identidad de Tenant B, ENTONCES las operaciones de B no muestran ni permiten utilizar la sede de A y responden **404**, sin efectos en A ni B.
- **AC-2 — Sustitución y agregado de stock.** DADO un producto con filas departamentales previas, CUANDO se consolidan sus saldos en la entidad por sede, ENTONCES el stock vigente queda representado una vez por sede/producto, cada departamento aporta su saldo a la sede asignada y el total institucional se deriva de la suma por sede, sin saldo institucional independiente. Una prueba gated PostgreSQL verifica unicidad por sede/producto; las consultas y endpoints de existencias leen solo stock por sede y nunca exponen ni agregan las filas legadas de `inventario`.
- **AC-3 — Identificadores de sede inválidos o ajenos.** DADO una petición autenticada que envía un `sede_id` inexistente o perteneciente a otro tenant, CUANDO intenta asignar o consultar stock, ENTONCES la API responde **404** y no realiza mutación, consulta cruzada ni movimiento.
- **AC-4 — Encargados de departamento.** DADO un departamento, CUANDO el Administrador Institucional asocia uno o más usuarios como encargados mediante API, ENTONCES cada usuario existe, es Solicitante y pertenece al mismo departamento y tenant; se rechazan usuarios inexistentes/ajenos con **404** y asociaciones incompatibles o duplicadas con **409**. La tabla puente permite varios encargados y cero filas durante estados incompletos. Las consultas solo muestran asociaciones compatibles vigentes.
- **AC-5 — Administración de asignaciones por API.** DADO una petición para asociar/retirar un encargado, asignar departamento a sede o asignar Bodeguero a sede, CUANDO la ejecuta un Administrador Institucional del tenant, ENTONCES solo modifica la asociación solicitada dentro de su institución; sesión ausente devuelve **401**, rol no autorizado **403**, identificador inexistente/ajeno **404**, conflicto de asociación **409** y payload inválido **422**. No existe obligación de UI administrativa en esta feature.
- **AC-6 — Sede de departamento y ausencia de asignación.** DADO un departamento asignado a una sede, CUANDO un Solicitante consulta disponibilidad o crea un ticket, ENTONCES se usa exclusivamente el stock de esa sede. DADO un departamento sin sede, CUANDO intenta consultar stock o iniciar un flujo que requiere disponibilidad, ENTONCES recibe **409** con error claro y no se usa una sede por defecto.
- **AC-7 — Ámbito atribuible de Bodeguero.** DADO un Bodeguero autenticado con una sede asignada, CUANDO consulta o modifica existencias, ENTONCES solo puede operar en esa sede; un `sede_id` distinto o ajeno se rechaza con **404** sin efecto. Sin sede asignada, las operaciones se deniegan con **409**.
- **AC-8 — Ámbito del Administrador y Superadmin.** DADO un Administrador Institucional, CUANDO consulta existencias, ENTONCES obtiene todas las sedes de su institución y ninguna de otro tenant. DADO un Superadmin, CUANDO realiza una lectura global ya autorizada, ENTONCES recibe filas atribuidas a cada institución y no obtiene permiso de escritura sobre datos de negocio tenant; los intentos no autorizados reciben **403**.
- **AC-9 — Instantánea de sede en ticket, despacho y auditoría.** DADO un departamento asignado a una sede, CUANDO se crea un ticket, ENTONCES `ticket.sede_id` almacena la sede vigente en ese instante. Si el departamento cambia de sede después, el ticket abierto se despacha desde la sede almacenada y conserva esa instantánea; los tickets futuros almacenan la nueva sede. El despacho rebaja solo ese stock, registra movimiento mediante `stock_sede_id` y cambia el estado atómicamente. Ante fallo no persisten cambios parciales.
- **AC-10 — Preparación exacta y auditoría legada.** DADO cada tenant INST-001..004, CUANDO se prepara, ENTONCES se crean respectivamente 2, 3, 4 y 2 sedes y se asignan departamentos con la regla determinista de D-7. Antes se mide por producto el total departamental; después, la suma por sede es exactamente igual. Cada saldo `(sede, producto)` equivale a la suma de sus movimientos de consolidación `ENTRADA`. Las filas legadas de inventario, sus FK y todos los movimientos históricos permanecen idénticos; discrepancia en cualquier igualdad aborta sin éxito.
- **AC-11 — Criticidad y compatibilidad analítica.** DADO existencias distintas por sede de un mismo producto, CUANDO se evalúa `stock_minimo`/criticidad, ENTONCES la alerta se calcula por saldo de sede. `GET /inventario/existencias` expone obligatoriamente sede y saldo. `GET /dashboard/` aplica las mismas fórmulas KPI de Feature 009 sobre la nueva granularidad de stock por sede, conserva semántica consolidada institucional y no consulta cifras departamentales legadas; sus tests se actualizan para esa fuente.
- **AC-12 — Estructura, versión, aprovisionamiento e instalación.** DADO la instalación limpia, los cuatro tenants actuales y un tenant nuevo aprovisionado, CUANDO se aplica la Feature 011, ENTONCES `control` y cada tenant reciben la estructura canónica/tenant actualizada y `version_esquema` pasa exactamente a **`011.1`** en control y los cuatro tenants existentes; solo se enrutan tenants con versión exacta. La semilla limpia crea INST-001..004 con sedes según D-7 y todos sus departamentos asignados. El aprovisionamiento de tenant nuevo crea automáticamente “Sede Central” para que nazca operativo, sin crear CRUD de sedes. Se preservan identidad, mapa de control y datos de otros tenants.
- **AC-13 — Semilla protegida y orden.** DADO un volumen existente con datos, mapas o versiones, CUANDO se intenta ejecutar la semilla destructiva, ENTONCES la guardia fail-closed aborta antes de truncar y no altera datos. En instalación limpia, `01_esquema.sql` crea antes de `02_datos_semilla.sql` la estructura necesaria para control y datos QA.
- **AC-14 — Contratos y cierre de verificación.** DADO que se valida la feature, CUANDO se revisa `/openapi.json` y las evidencias, ENTONCES cada operación nueva declara respuestas y seguridad conforme a la matriz central; tests ordinarios y gated PostgreSQL cubren integridad, migración y versionado. Si existe UI afectada, se verifica en 4200 y 8080 tras reconstrucción. Este criterio es de proceso de verificación y no añade comportamiento de negocio.

## 6. Fuera de alcance

- Vista administrativa de sedes, departamentos, usuarios o encargados; corresponde a Feature 012.
- CRUD general de sedes; la Feature 011 expone solo la API mínima de asignaciones y el aprovisionamiento de “Sede Central” para tenants nuevos.
- Lecturas operativas que mezclen sedes de varios tenants, o escrituras cross-tenant. La única lectura global es la de Superadmin que ya esté autorizada y atribuida institucionalmente.
- Varios almacenes o ubicaciones con saldos separados dentro de una sede.
- Transferencias entre sedes y cambios generales del ciclo de vida de tickets/catálogo.
- Reescritura o eliminación de movimientos históricos.

## 7. Restricciones

- La institución y su esquema PostgreSQL siguen siendo la frontera tenant; el cliente no selecciona el tenant ni puede usar identificadores de otra institución.
- Operaciones nuevas se autorizan en la matriz central; los guards de frontend no sustituyen autorización del backend.
- Clerk sigue siendo la única autoridad de autenticación.
- El inventario operativo tiene granularidad sede/producto. Las filas legadas de `inventario` no se exponen por API ni alimentan consultas de existencias; los endpoints leen exclusivamente stock por sede. No coexisten saldos operativos independientes por departamento o a nivel institucional.
- `departamento.sede_id` y `usuario.sede_id` son nullable. La regla de exactamente una sede es operativa; si falta, se deniegan las operaciones dependientes sin fallback.
- Cada ticket nuevo almacena en `ticket.sede_id` la sede del departamento al momento de creación. El despacho usa esa instantánea, no la asignación departamental vigente al despachar; los cambios afectan tickets futuros.
- Las filas legadas de inventario referenciadas por movimientos históricos y todos esos movimientos se conservan sin reescritura. `movimiento_inventario.inventario_id` admite NULL para movimientos nuevos; sus valores históricos y la FK existente se mantienen intactos. La nueva referencia nullable `stock_sede_id` enlaza movimientos nuevos de negocio/consolidación, que dejan `inventario_id` nulo.
- Sede y stock por sede son entidades de dominio nuevas; `departamento_encargado` es auxiliar de asociación. El plan debe exigir aprobación de la actualización de `stack.md` que supera la regla de doce entidades y cubre sustitución, claves, columnas `departamento.sede_id`, `usuario.sede_id`, `ticket.sede_id`, `movimiento_inventario.stock_sede_id`, auditoría, reconciliación y agregación antes de implementar.
- Todo Bodeguero operativo debe tener exactamente una sede. El aprovisionamiento de tenant nuevo crea “Sede Central”; no equivale a CRUD, que queda en Feature 012.
- Los encargados de departamento son Solicitantes del mismo departamento. La API valida al asociar, limpia asociaciones incompatibles y filtra lecturas a asociaciones vigentes; no añade privilegios ni triggers.
- Superadmin tiene únicamente lectura global autorizada y atribuida institucionalmente; no adquiere escritura en tenants.
- La preparación usa reparto determinista INST-001→2, INST-002→3, INST-003→4, INST-004→2 y round-robin por `departamento_id`; conserva exactamente el total previo medido por producto y reconcilia cada saldo con movimientos nuevos `ENTRADA`. No reescribe ni borra auditoría histórica.
- `inventario.ubicacion` se conserva como dato legado y no se copia automáticamente a `sede.direccion`; no representa ubicación de stock nuevo.
- La criticidad se evalúa por sede. `GET /inventario/existencias` expone sede y saldo; `GET /dashboard/` aplica las mismas fórmulas de Feature 009 a stock por sede, mantiene los KPI consolidados y no usa saldos departamentales.
- `version_esquema` debe actualizarse en `control` y cada tenant existente al token **`011.1`**. El enrutamiento deniega versión ausente, incompleta o distinta de `011.1`.
- El DDL de instalación limpia respeta initdb alfabético (`01_esquema.sql` antes de `02_datos_semilla.sql`). La semilla mantiene guardia fail-closed y no migra volúmenes existentes.
- Las migraciones existentes son explícitas, transaccionales/idempotentes según el plan y no dependen de initdb ni de la semilla destructiva.
- Códigos HTTP: 401 sesión ausente/no válida; 403 rol sin permiso; 404 identificador inexistente o ajeno al tenant (ocultación); 409 precondición organizacional ausente o conflicto de asociación/stock; 422 payload inválido.
- SQLite no acredita semánticas multi-esquema ni restricciones propias de PostgreSQL; estas garantías se verifican contra PostgreSQL 16.

## 8. Estado y evidencia de verificación

| Criterio | Estado | Evidencia |
|---|---|---|
| AC-1 | Verificado | `api/test_organizacion_011.py::test_listar_sedes_devuelve_solo_la_institucion_del_administrador`, `::test_asignacion_en_departamento_de_otra_institucion_responde_404`, `::test_listar_encargados_de_departamento_ajeno_responde_404`; `test_aislamiento_sede_011.py::test_sede_de_a_no_aparece_en_b_y_su_id_responde_404_sin_mutar` (gated, 2 tenants). |
| AC-2 | Verificado | `api/test_inventario_sede_011.py::test_existencias_exponen_sede_y_saldo`, `::test_producto_sin_stock_sede_aparece_en_cero`, `::test_stock_total_es_la_suma_de_las_sedes`, `::test_movimiento_nuevo_audita_por_stock_sede`; `models/test_modelo_sede_011.py::test_stock_sede_exige_unicidad_por_sede_y_producto`, `::test_stock_sede_rechaza_saldos_negativos`; `api/test_dashboard_sede_011.py::test_kpi_unidades_en_stock_suma_el_stock_por_sede`, `::test_kpi_sin_stock_por_sede_no_cuenta_el_legado`; gated `test_migracion_modelo_organizacional_011.py::test_migracion_011_exige_unicidad_y_stock_no_negativo`. |
| AC-3 | Verificado | `api/test_organizacion_011.py::test_asignacion_con_sede_ajena_o_inexistente_responde_404`; `api/test_inventario_sede_011.py::test_movimiento_con_stock_sede_inexistente_responde_404`; `models/test_modelo_sede_011.py::test_stock_sede_rechaza_producto_de_otra_institucion`; `test_aislamiento_sede_011.py::test_sede_de_a_no_aparece_en_b_y_su_id_responde_404_sin_mutar` (gated). |
| AC-4 | Verificado | `api/test_organizacion_011.py::test_encargados_multiples_del_mismo_departamento`, `::test_encargado_con_rol_distinto_responde_409`, `::test_encargado_de_otro_departamento_responde_409`, `::test_encargado_de_otra_institucion_responde_404`, `::test_encargado_inexistente_responde_404`, `::test_encargado_duplicado_responde_409`, `::test_retirar_encargado_deja_de_aparecer`; `models/test_modelo_sede_011.py::test_departamento_encargado_es_auxiliar_y_con_unicidad`, `::test_departamento_encargado_exige_referencias_existentes`. |
| AC-5 | Verificado | `api/test_organizacion_011.py::test_operaciones_de_organizacion_se_declaran_solo_para_administrador`, `::test_openapi_publica_las_operaciones_de_organizacion`, `::test_asignar_sede_a_departamento_persiste_y_responde`, `::test_asignar_sede_a_bodeguero_persiste_y_responde`, `::test_asignacion_sin_sesion_responde_401`, `::test_asignacion_con_rol_no_autorizado_responde_403`, `::test_asignacion_en_departamento_de_otra_institucion_responde_404`, `::test_asignacion_con_sede_ajena_o_inexistente_responde_404`, `::test_asignacion_con_payload_invalido_responde_422`. |
| AC-6 | Verificado | `api/test_ticket_sede_011.py::test_departamento_sin_sede_no_crea_ticket_responde_409`, `::test_crear_ticket_sin_sede_de_departamento_afecta_a_todos_los_roles_creadores`; `api/test_organizacion_011.py::test_asignar_sede_a_departamento_persiste_y_responde`. |
| AC-7 | Verificado | `api/test_inventario_sede_011.py::test_bodeguero_sin_sede_no_puede_mover_stock` (409), `::test_bodeguero_solo_opera_en_su_sede` (404), `::test_movimiento_con_saldo_insuficiente_responde_409_sin_auditoria`. |
| AC-8 | Verificado | `api/test_inventario_sede_011.py::test_administrador_ve_todas_las_sedes_de_su_institucion`, `::test_superadmin_conserva_lectura_global_atribuida`, `::test_superadmin_no_escribe_stock`, `::test_roles_sin_permiso_de_escritura_de_stock`; `test_lectura_global_tickets_011.py::test_lectura_global_de_tickets_responde_200_con_categoria`. |
| AC-9 | Verificado | `api/test_ticket_sede_011.py::test_crear_ticket_almacena_la_sede_del_departamento`, `::test_ticket_abierto_despacha_desde_la_sede_almacenada`, `::test_stock_insuficiente_en_la_sede_del_ticket_responde_409`, `::test_despacho_registra_movimiento_por_stock_sede`, `::test_ticket_legado_sin_sede_no_se_despacha`; gated `test_migracion_modelo_organizacional_011.py::test_migracion_011_asigna_sede_a_los_tickets_historicos`. Recorrido T13 en 4200: ticket con snapshot, reasignación y despacho real persistidos en `apt_erp` (011.1). |
| AC-10 | Verificado | gated `test_migracion_modelo_organizacional_011.py::test_migracion_011_crea_estructura_y_versiona`, `::test_migracion_011_reparte_departamentos_por_round_robin` (2/3/4/2), `::test_migracion_011_conserva_los_totales_por_producto` (cuadre), `::test_migracion_011_cada_saldo_equivale_a_sus_movimientos_de_consolidacion`, `::test_migracion_011_no_reescribe_auditoria_ni_inventario_legado`, `::test_migracion_011_es_idempotente`, `::test_migracion_011_aborta_ante_estado_parcial_sin_cambios` (4 tenants, PostgreSQL). |
| AC-11 | Verificado | `api/test_inventario_sede_011.py::test_solo_criticos_evalua_por_sede`; `api/test_dashboard_sede_011.py::test_alerta_por_sede_critica`, `::test_alerta_por_sede_en_el_borde_del_minimo`, `::test_actividad_reune_movimientos_historicos_y_nuevos`; `api/test_inventario_sede_011.py::test_existencias_exponen_sede_y_saldo`. Recorrido T14 en 8080: dashboard e inventario con sede visibles. |
| AC-12 | Verificado | `api/test_control_sede_011.py::test_version_objetivo_es_011_1`, `::test_tenant_con_la_version_anterior_no_es_objetivo`, `::test_tenant_en_version_011_1_es_objetivo`, `::test_aprovisionamiento_crea_la_sede_inicial`, `::test_aprovisionamiento_responde_la_version_011_1`; gated `test_aprovisionamiento_postgres_010.py::test_tenant_aprovisionado_recibe_sede_central_y_version_011_1`; gated `test_migracion_modelo_organizacional_011.py::test_migracion_011_crea_estructura_y_versiona` (control + 4 tenants a `011.1`). |
| AC-13 | Verificado | gated `test_migracion_modelo_organizacional_011.py::test_instalacion_limpia_crea_sedes_y_conserva_la_guardia` (`01_` antes de `02_`, guardia fail-closed antes del primer `TRUNCATE`). |
| AC-14 | Verificado | Suites: gated `pytest` **742 passed / 0 failed / 0 skipped**; SQLite **696 passed / 46 skipped**; `ng test` **198 SUCCESS**; `ng build` limpio. Matriz central: **28 operaciones**. Contrato `/openapi.json`: `api/test_organizacion_011.py::test_openapi_publica_las_operaciones_de_organizacion`, `::test_operaciones_de_organizacion_se_declaran_solo_para_administrador`. Recorridos: T13 (4200, escritura real) y T14 (8080, imagen reconstruida). Validación reviewer: VEREDICTO APROBADO. |
