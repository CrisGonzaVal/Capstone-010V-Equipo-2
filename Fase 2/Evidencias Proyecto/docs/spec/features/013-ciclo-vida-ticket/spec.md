# Feature 013: Ciclo de vida del ticket

> **Nota de vigencia (19/Oct/2026):** este documento describe la feature tal como
> se cerró. Las migraciones que cita (`database/migraciones/*`) se retiraron del
> repo en la consolidación de la base: hoy `database/` solo tiene
> `01_esquema.sql` y `02_datos_semilla.sql`, y la base se reconstruye con
> `docker compose down -v` + `up -d`. La evidencia y las decisiones siguen siendo
> válidas; los nombres de archivos citados son históricos. Los tests gated
> citados (`test_ciclo_vida_ticket_postgres_013.py` y sus casos de migración)
> conservan solo las pruebas de instalación limpia y del token de versión; los
> casos de migración se retiraron junto con los scripts.

**Estado:** aprobada y cerrada (19/Oct/2026) — con las enmiendas incorporadas: D-4/AC-26 (terminalidad por nombre en cualquier catálogo) y AC-18 (403 de matriz vs 404 de ocultamiento)  
**Release:** 2.0 — Sprint 6
**Tipo:** Evolución del ciclo de vida del ticket y auditoría

## 1. Problema

El flujo de tickets cubre el camino feliz —emitir, mover por el tablero, despachar— pero no
admite los desvíos reales de la operación diaria:

- **No se puede cancelar un ticket.** Una solicitud emitida por error o que dejó de necesitarse
  solo avanza o queda estancada en `Pendiente`; contamina el tablero, infla el conteo de tickets
  activos del dashboard y nadie puede retirarla con una explicación.
- **No hay rechazo.** Bodega o el Administrador no pueden declinar una solicitud dejando constancia
  del motivo; la única "negativa" disponible es no tocar el ticket.
- **No se puede editar.** Un asunto mal escrito o una cantidad equivocada obligan a emitir un
  ticket nuevo y abandonar el anterior, duplicando la cola.
- **No hay auditoría del ciclo de vida.** El ticket guarda solo su estado actual (y `fecha_cierre`
  cuando se cierra por despacho); nadie puede responder "¿quién movió este ticket, cuándo y por
  qué?". La Feature 005 declaró además que no persiste la autoría del despacho.
- **La vista de detalle está fuera de alcance desde la Feature 004:** los ítems, las cantidades
  entregadas, el historial y el contexto completo del ticket no son visibles en ninguna parte; la
  tarjeta muestra solo lo necesario para mover la columna.

## 2. Objetivo

Incorporar un único estado terminal `Anulado` que absorba la anulación del Solicitante y el
rechazo de Bodega/Administrador —ambos con motivo obligatorio—; permitir editar el ticket
mientras está en `Pendiente`; registrar cada transición en un historial inmutable (quién, cuándo,
de qué estado a qué estado y por qué); y habilitar la vista de detalle del ticket, sin debilitar
la reserva del cierre por despacho (Feature 005) ni el significado de `fecha_cierre`
(Feature 004).

## 3. Alcance

### Dentro

- Estado terminal nuevo `Anulado` en el catálogo `estado_ticket` (replicado por tenant desde la
  010), presente en **toda** instalación: estructura y semilla de instalación nueva, constructor
  de tenants y migración operacional idempotente bajo `database/migraciones/` con token de
  versión `013.1`.
- Anulación de ticket con motivo obligatorio, operada por el dueño Solicitante y por el
  Administrador de la institución.
- Rechazo de ticket con motivo obligatorio, operado por el Bodeguero y por el Administrador.
- Ambas operaciones admitidas desde `Pendiente` y `EnRevision` (ambos inclusive).
- Edición de asunto, descripción, prioridad e ítems detallados mientras el ticket está en
  `Pendiente`, operada por el dueño Solicitante y por el Administrador.
- Historial de transiciones del ticket: fila por transición con actor, marca de tiempo, estado de
  origen, estado de destino y motivo; toda mutación de estado lo registra.
- Vista de detalle del ticket (cabecera, ítems con cantidades, fechas e historial) y todas las
  acciones del ciclo de vida disponibles según estado y rol: transiciones del flujo lineal,
  edición, anulación y rechazo (D-14).
- Tablero Kanban de solo lectura: sin botones de "avanzar"/"retroceder" (derogados de la 004
  en su capa de UI); cada tarjeta ofrece una acción "Gestionar" que abre la vista de detalle
  del ticket, y el tablero añade la columna `Anulado` (D-14).
- Reglas de flujo actualizadas: `Cerrado` y `Anulado` son los dos estados terminales, reconocidos
  por nombre; `Anulado` queda fuera de la secuencia lineal del cambio de estado.
- Ajuste requerido del KPI de "tickets activos" del dashboard (Feature 009) para excluir el
  estado nuevo.
- Contrato de API y matriz de permisos **aditiva** para las operaciones nuevas, con el patrón de
  ocultamiento y códigos de las Features 007/008/011/012.

### Fuera

- Reabrir tickets en `Cerrado` o `Anulado`: ambos son terminales por nombre canónico y no
  admiten salida en ningún catálogo (D-4); la terminalidad no depende de la posición en el
  catálogo.
- Anular o rechazar desde `EnCurso`: el único cierre válido en `EnCurso` sigue siendo el
  despacho transaccional de la Feature 005.
- Editar tickets fuera de `Pendiente`, o editar el estado, el solicitante, la sede instantánea o
  la institución de un ticket.
- Borrado físico de tickets o del historial, y reescritura de filas del historial.
- Migración o reconstrucción de las transiciones ocurridas antes de esta feature.
- Notificaciones, informes, aprobación multi-ronda o flujos con más de un aprobador.
- Operar transiciones, edición, anulación o rechazo desde el tablero Kanban: el tablero es de
  solo lectura (su única acción es abrir el detalle); toda mutación del ciclo de vida se opera
  en la vista de detalle (D-14).
- CRUD del catálogo de estados; cambios a Clerk, a la matriz previa (solo se agregan filas) o al
  despacho de la 005.

## 4. Decisiones

### D-1 — Un único estado terminal nuevo, `Anulado`, compartido por anulación y rechazo

La anulación del Solicitante y el rechazo de Bodega/Administrador llevan al **mismo** estado
`Anulado`; lo que distingue un caso del otro es el actor y el motivo registrados en el historial,
no una fila de catálogo aparte.

**Por qué:** dos estados terminales equivalentes partirían el tablero, el catálogo y los conteos
en dos vocabularios para el mismo significado ("este ticket no se va a despachar"), repitiendo
exactamente la divergencia de vocabulario que la Feature 004 eliminó. El motivo es un dato de la
transición, no una etapa del flujo.

### D-2 — `Anulado` entra al catálogo replicado por tenant, con presencia obligatoria en toda instalación

El estado nuevo debe existir en la estructura y la semilla de instalación nueva, en el
constructor de tenants (cada esquema tenant recibe el catálogo completo) y en una migración
operacional idempotente bajo `database/migraciones/` para bases existentes, que eleva el token
de versión de control y tenants a `013.1` con el mismo procedimiento de las 011/012.

**Por qué:** desde la Feature 010 el catálogo de estados es local a cada tenant y el
enrutamiento exige igualdad exacta de versión. Un estado presente en unas instalaciones y no en
otras produciría comportamientos distintos (un tenant sin `Anulado` rechazaría las anulaciones)
y rompería el control de versión que protege ese desajuste.

### D-3 — Anulación y rechazo solo desde `Pendiente` y `EnRevision`

Hasta `EnRevision` el ticket es una intención sin preparación física. Desde `EnCurso` el ticket
representa material en preparación y su único cierre válido es el despacho transaccional de la
005, que rebaja stock y audita en la misma transacción.

**Por qué:** permitir un cierre sin despacho desde `EnCurso` dejaría el ticket terminado sin la
salida de inventario correspondiente, contra `constitucion.md` §3 (Consistencia Transaccional);
la 005 reservó exactamente ese paso para impedirlo.

### D-4 — `Anulado` queda fuera de la secuencia lineal; los terminales se reconocen por nombre

La 004 gobierna el flujo por ordinalidad (un paso entre contiguos; el último estado del catálogo
es terminal). Con `Anulado` añadido al final del catálogo, la regla ordinal convertiría a
`Cerrado` en estado no-terminal y habilitaría, según el catálogo, el paso contiguo `Cerrado →
Anulado` (canónico) o una transición de salida desde `Cerrado` (catálogo degenerado). Esta
feature declara, **en interpretación literal de esta decisión**: `Cerrado` y `Anulado` son los
dos estados terminales, reconocidos por su **nombre canónico** (misma resolución que el cierre
de la 004, D-3) y **nunca** por su posición en el catálogo; ninguno de los dos admite
**ninguna** transición de salida vía `PATCH /estado`, en **cualquier** catálogo (409); el
cambio de estado tampoco puede llevar **a** `Anulado` (409 con detalle que dirige a la operación
de anulación o rechazo correspondiente); el 409 de salida desde `Cerrado` declara que el cierre
es definitivo y que el despacho transaccional de la 005 es el único camino a él; y `Anulado`
solo se alcanza por anulación o rechazo, que exigen motivo.

**Derogación adicional de la 004 (patrón que la propia 004 usó con la 005, y que esta spec ya
usa en D-14 para la UI):** la regla de terminalidad **ordinal** del D-2 de
`004-tablero-kanban/spec.md` ("el último estado del orden del catálogo es terminal") y su
comportamiento de salida/retroceso desde el último estado quedan **sustituidos**, en el dominio
del ciclo de vida de tickets, por la resolución por nombre canónico: `Cerrado` es terminal
aunque no sea el último del catálogo, y ningún otro estado lo es por ocupar la última
posición. En consecuencia, el caso degenerado del test de la 004
`test_reentrar_en_cerrado_conserva_la_fecha_original` (`backend/tests/api/test_tablero_kanban.py`),
que exige que un `Cerrado` que no es el último del catálogo admita salida (`Cerrado → Archivado`
= 200), **queda derogado**: esa misma petición responde hoy 409. La 004 permanece sin editar
como registro histórico de su release; esta enmienda regula el comportamiento vigente.

**Por qué:** conserva el flujo lineal vigente para los cuatro estados operativos, deroga solo lo
imprescindible de la 004 y no depende de la posición del estado en el catálogo. La terminalidad
ordinal, aplicada al catálogo canónico (`…, Cerrado, Anulado`), dejaba a `Cerrado` con salida
hacia atrás (`Cerrado → EnCurso`, un paso) y permitía que un ticket **ya despachado** volviera a
un estado despachable para despacharse de nuevo —doble rebaja de stock—, rompiendo la reserva de
cierre de la 005 y `constitucion.md` §3 (Consistencia Transaccional).

### D-5 — La anulación no sella `fecha_cierre` ni toca stock; el historial es la fuente de verdad del ciclo de vida

`fecha_cierre` conserva su significado vigente (004 D-3/D-4): cierre por despacho/estado
`Cerrado`. Un ticket anulado queda con `fecha_cierre` **nula**; la fecha de su anulación se
registra en la fila del historial (actor, instante y motivo), que pasa a ser la fuente de verdad
del ciclo de vida completo del ticket. La anulación no escribe movimientos de inventario.

**Por qué:** sellar `fecha_cierre` en una anulación haría que "fecha de cierre" signifique dos
cosas —entregado vs. cancelado—, rompería la regla "todo ticket en `Cerrado` tiene fecha" y
deformara cualquier lectura que derive de esa columna. Agregar una segunda columna de fecha al
ticket sería redundante con el historial, que ya registra el instante exacto de cada transición.
Y no hay movimiento que auditar porque la anulación no mueve stock (`constitucion.md` §2 cubre
los cambios de inventario; aquí no los hay).

### D-6 — Motivo obligatorio, no vacío y de longitud acotada

Anulación y rechazo exigen un motivo de longitud máxima acotada (la misma escala de la
descripción del ticket). Sin motivo válido no se escribe nada; el motivo se persiste en la fila
del historial de esa misma transición.

**Por qué:** el motivo es la única distinción sustantiva entre anulación y rechazo para el
futuro lector del historial, y un ticket descartado sin explicación rompe la trazabilidad del
negocio (¿por qué no se despachó?).

### D-7 — Dos operaciones de API, no una genérica

`anulación` (dueño Solicitante y Administrador) y `rechazo` (Bodeguero y Administrador) son
operaciones distintas hacia el mismo estado.

**Por qué:** los conjuntos de roles autorizados difieren —el Bodeguero no "anula" y el
Solicitante no "rechaza"—; con una sola operación la matriz tendría que conceder todos los roles
juntos o perder la distinción, y el contrato público perdería el significado de cada acción. Que
el estado sea compartido no obliga a compartir la operación.

### D-8 — Autorización por la matriz aditiva y ocultamiento 404, como en 007/008/011/012

El Solicitante solo opera sus propios tickets; Administrador y Bodeguero, los de su institución.
Un ticket inexistente y uno fuera del alcance del rol responden **404 idéntico**, sin revelar
existencia (mismo patrón que el verificado alcance de ticket vigente). El ocultamiento 404
aplica solo a un rol **concedido en la operación** pero fuera del alcance del recurso; una
operación no concedida al rol —p. ej. el Solicitante en `rechazo`— responde **403** según la
matriz, evaluada antes de mirar el recurso y sin revelar si este existe. Superadmin **no opera**
tickets: 403 en toda escritura (anulación, rechazo, edición), y lectura de detalle e historial
con su alcance global actual, igual que su lectura vigente de la lista de tickets. Las
operaciones nuevas se agregan a la matriz (una operación ausente no concede a nadie) y quedan
sujetas al gating de capacidades por institución de la 012.

**Por qué:** consistencia con la matriz y los códigos ya establecidos; la 012 excluyó al
Superadmin de la operación de tickets solo por UI/guard, y esta feature no cambia eso: su
frontera sigue siendo la matriz.

### D-9 — Edición completa, solo en `Pendiente`, con validación íntegra antes de escribir

Campos editables: asunto, descripción, prioridad y el **conjunto completo** de ítems detallados
(reemplazo del conjunto, con las mismas validaciones del alta: productos de la institución,
cantidades positivas, al menos un ítem). Autores: el dueño Solicitante y el Administrador de la
institución. Fuera de `Pendiente` → 409 sin cambios; una validación fallida no escribe nada, ni
cabecera ni ítems parciales. No se editan el estado, el solicitante, la sede instantánea ni la
institución.

**Por qué:** en `Pendiente` el ticket todavía no fue revisado ni preparado; editar después
cambiaría la base sobre la que Bodega ya trabajó. El Administrador comparte la edición porque
administra la institución y debe poder corregir una solicitud mal emitida por cualquiera de ella;
el Bodeguero no la recibe: su rol interviene en la preparación y el despacho, no en el contenido
de la solicitud.

### D-10 — Historial de transiciones inmutable que registra toda transición desde esta feature

Estructura nueva de historial con una fila por transición: ticket, estado de origen, estado de
destino, actor, marca de tiempo y motivo. Toda mutación de estado lo registra: el alta crea la
fila de creación; el cambio de estado de la 004, el despacho de la 005 y la anulación/rechazo de
esta feature, cada una con su fila. El historial es de solo lectura por API: sin operación de
edición, borrado o reescritura. Las transiciones anteriores a esta feature **no se migran ni
reconstruyen**.

**Por qué:** la Trazabilidad Absoluta exige poder responder quién, cuándo, de qué a qué y por
qué; el cambio de estado y su fila de historial ocurren en la misma transacción
(`constitucion.md` §3). No se reconstruyen transiciones pasadas porque no existe registro
persistido de su actor ni de su estado anterior —la 005 declaró expresamente que no persiste
autoría— y fabricar esas filas inventaría trazabilidad: las instalaciones existentes empiezan con
el historial de cada ticket vacío o desde su primera transición posterior, sin datos ficticios.

### D-11 — Un ticket nuevo no puede nacer en `Anulado`

La alta de la 003 permite elegir estado inicial; `Anulado` queda excluido de esa elección y se
rechaza si llega. `Cerrado` sigue admitido con su sellado de fecha (004 AC-17), intacto.

**Por qué:** un ticket nacido anulado no tiene quién lo anulara ni por qué; su historia
arrancaría mintiendo y sin el motivo que D-6 exige a toda anulación.

### D-12 — El KPI de "tickets activos" del dashboard excluye también `Anulado`

La fórmula vigente de la 009 cuenta como activo todo ticket cuyo estado no es exactamente
`Cerrado`; con el estado nuevo, un ticket anulado se contaría como activo para siempre. La regla
pasa a excluir **ambos** nombres canónicos (`Cerrado` y `Anulado`), sin ids fijos, conservando
el ámbito por rol.

**Por qué:** un KPI que presenta como pendiente de atención un ticket que nunca se despachará
deforma el indicador con que el negocio decide. Cambiar la fórmula es requisito de esta feature,
no un refactor opcional.

### D-13 — La vista de detalle sustituye el "fuera de alcance" de la 004

El detalle muestra la cabecera (asunto, prioridad, solicitante y departamento, sede, fechas de
creación y —si existe— de cierre), los ítems con cantidades solicitadas y entregadas, y el
historial completo. Las acciones (avanzar o retroceder en el flujo lineal, editar, anular,
rechazar) se ofrecen solo al rol autorizado y solo en los estados que las admiten; el tablero
no ofrece ninguna mutación (D-14).

**Por qué:** la 004 dejó el detalle fuera de alcance porque las tarjetas bastaban para mover el
flujo; el ciclo de vida completo —motivo, autoría, ítems— no se puede operar ni auditar sin esa
vista.

### D-14 — El tablero Kanban pasa a solo lectura; la acción "Gestionar" abre el detalle

El tablero deja de ofrecer los botones "avanzar"/"retroceder" de la Feature 004: sus tarjetas
son informativas (incluida la nueva columna `Anulado`) y cada una ofrece una única acción —
"Gestionar"— que abre la vista de detalle del ticket, donde viven **todas** las operaciones del
ciclo de vida: las transiciones del flujo lineal (invocando `PATCH /tickets/{id}/estado`), la
edición en `Pendiente`, la anulación y el rechazo con motivo. El backend de transiciones **no
cambia**: `PATCH /estado` conserva íntegro su contrato de la 004/005; lo único que cambia es
el punto de invocación. **Deróganse parcialmente, en su capa de UI,** los AC-9, AC-10, AC-12,
AC-19 y AC-20 de `004-tablero-kanban/spec.md` (transiciones por botón en el tablero y su
feedback 409/404 en el tablero), y del D-2 de esa spec se deroga que "su tarjeta no ofrece
ningún control" como regla del tablero —hoy ninguna tarjeta ofrece controles—, conservándose
su regla de backend (flujo lineal de un paso, terminal por nombre); del D-7 se deroga el
movimiento y la reconsulta de la tarjeta en el tablero, trasladándose la exigencia de mensaje
accesible, sin doble envío y con reconsulta a la vista de detalle (AC-24).

**Por qué:** con el detalle disponible, el ciclo de vida completo no cabe en una tarjeta;
concentrar todas las mutaciones en una sola vista evita dos superficies de escritura con reglas
distintas, hace que el tablero sea seguro para quien solo supervisa la cola y reduce el riesgo
de una transición accidental desde el tablero. Decisión del usuario incorporada antes del plan.

**Derogación parcial de la 004 (patrón que la propia 004 usó con la 005):** los AC y
decisiones de UI listados quedan derogados solo en lo que exigía controles de transición en el
tablero; sus reglas de backend —flujo lineal, orden de validación ticket→estado→flujo, sellado
de `fecha_cierre` y cierre reservado al despacho— permanecen intactas y ahora se verifican
desde la vista de detalle.

## 5. Reglas del flujo

La secuencia lineal de la 004 se conserva para los estados operativos; `Anulado` queda fuera de
ella y solo se alcanza por anulación o rechazo con motivo. La terminalidad de `Cerrado` y
`Anulado` se resuelve **por nombre canónico**, no por ordinalidad del catálogo (D-4): ninguno de
los dos admite salida en ningún catálogo. Estas transiciones se operan
**exclusivamente desde la vista de detalle** (D-14), que invoca `PATCH /estado`; el tablero de
solo lectura no las invoca:

| Desde | Avanzar (cambio de estado) | Retroceder (cambio de estado) | Anular | Rechazar |
|---|---|---|---|---|
| Pendiente | EnRevision | — (es el primero) | Sí, con motivo | Sí, con motivo |
| EnRevision | EnCurso | Pendiente | Sí, con motivo | Sí, con motivo |
| EnCurso | Cerrado (solo vía despacho de la 005) | EnRevision | No (409) | No (409) |
| Cerrado | — (terminal por nombre, en cualquier catálogo) | — (terminal, sin salida: 409) | No (409) | No (409) |
| Anulado | — (terminal) | — (terminal) | — (terminal) | — (terminal) |

Invariantes y orden de validación (extiende el D-8 de la 004):

1. El cambio de estado jamás lleva a `Anulado`, ni sale de `Anulado` ni de `Cerrado`: 409 en
   cualquiera de esos casos y **en cualquier catálogo**, porque la terminalidad se resuelve por
   nombre canónico y no por posición (D-4). El detalle desde `Anulado` dirige a la operación de
   anulación o rechazo correspondiente; el detalle desde `Cerrado` declara que el cierre es
   definitivo y que el despacho de la 005 es el único camino a él.
2. Ante anulación o rechazo el orden es: (1) el ticket existe y está en el alcance del rol →
   **404** (inexistente y ajeno, idénticos); (2) el estado actual admite la operación → **409**;
   (3) el motivo es válido → **422**. Para el cambio de estado se conserva el orden de la 004:
   ticket/alcance (404), estado pedido (404), flujo (409).
3. Ningún rechazo deja escritura parcial: el cambio de estado + su fila de historial, y la
   edición de cabecera + sus ítems, son operaciones atómicas (una sola o ninguna).
4. `Anulado` no sella `fecha_cierre` y no escribe stock ni movimientos; `Cerrado` sigue
   sellando `fecha_cierre` por todos los caminos vigentes (004/005 intactos).
5. Un ticket en `Anulado` no es despachable (409, estado no elegible, ya cubierto por la 005);
   un ticket en `Cerrado` tampoco puede volver a un estado despachable, porque no admite salida
   (invariante 1): no hay camino a una segunda rebaja de stock.

## 6. Contrato de la API

Todas las operaciones son nuevas y aditivas en la matriz central; conservan el patrón vigente
de respuestas, evaluadas en este orden: 401 sesión ausente; 403 rol sin permiso en la matriz de
la operación (o capacidad institucional deshabilitada, 012), resuelto **antes** de
inspeccionar el recurso; 404 inexistente o fuera de alcance del rol concedido (idénticos);
409 conflicto de precondición/flujo; 422 entrada inválida.

### `POST /api/v1/tickets/{ticket_id}/anulacion`

Éxito: **200** con el ticket en `Anulado`, sin `fecha_cierre` y con su historial ya registrando
la transición. Payload: motivo obligatorio. Actores: el dueño Solicitante y el Administrador de
la institución. 409 si el estado actual no admite la operación (EnCurso, Cerrado o ya Anulado)
o si el catálogo del tenant no contiene el estado `Anulado`; 422 si el motivo falta, está vacío
o excede la longitud.

### `POST /api/v1/tickets/{ticket_id}/rechazo`

Mismo contrato, códigos y payload que la anulación; actores: el Bodeguero y el Administrador.

### `PUT /api/v1/tickets/{ticket_id}`

Edición del ticket en `Pendiente` con payload equivalente al de alta (asunto, descripción,
prioridad e ítems detallados completos). Éxito: **200** con el ticket actualizado y su nuevo
conjunto de detalles. 409 si el ticket no está en `Pendiente`; 404 por referencia inexistente o
ajena; 422 por forma inválida. Actores: el dueño Solicitante y el Administrador.

### `GET /api/v1/tickets/{ticket_id}`

Detalle del ticket: cabecera, ítems con cantidades y fechas. **200**; 404 inexistente o fuera de
alcance. Legible por los cuatro roles con su alcance vigente (Solicitante: los suyos;
Administrador y Bodeguero: su institución; Superadmin: global).

### `GET /api/v1/tickets/{ticket_id}/historial`

Lista de transiciones del ticket con estado de origen y destino, actor, marca de tiempo y
motivo, en orden determinista (más reciente primero, con desempate estable). **200**, lista
vacía si no hay transiciones; 404 inexistente o fuera de alcance; operación de solo lectura sin
variantes de escritura.

### `PATCH /api/v1/tickets/{ticket_id}/estado` — incorporación vigente

Conserva su contrato de la 004/005 e incorpora: cualquier petición cuyo destino sea `Anulado` o
cuyo origen sea `Anulado` responde **409** con detalle que dirige a la operación de anulación o
rechazo, sin modificar el ticket; y cualquier petición cuyo origen sea `Cerrado` responde
**409** con un detalle que declare que el cierre es definitivo y que el despacho transaccional
de la 005 es el único camino a `Cerrado`, sin modificar el ticket — **en cualquier catálogo**,
porque la terminalidad se resuelve por nombre canónico y no por posición (D-4, sustituyendo el
comportamiento ordinal de la 004). Sigue siendo el mecanismo de transición del flujo lineal de
los cuatro estados operativos, pero ahora se invoca **desde la vista de detalle** (D-14): el
tablero de solo lectura no lo invoca y su contrato no cambia.

## 7. Criterios de aceptación

### Reglas de flujo y estados

- [x] **AC-1** DADO QUE un ticket propio del Solicitante está en `Pendiente` o `EnRevision`,
      CUANDO el Solicitante lo anula con motivo válido, ENTONCES responde 200, el ticket queda
      en `Anulado` con `fecha_cierre` nula, su stock y sus movimientos quedan intactos, y el
      historial registra una fila con el actor, la marca de tiempo, `EnRevision/Pendiente →
      Anulado` y el motivo literal.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_flujo_013.py` — `test_anulacion_desde_pendiente_responde_200_con_historial_ac_1` y `test_anulacion_desde_en_revision_tambien_es_200_ac_1`; recorrido 4200 con escritura real: `evidencia/README.md` §3.1 #2 (ticket 13 → `Anulado`, `fecha_cierre` NULL, stock/movimientos intactos y fila con motivo literal, todo verificado por SQL).
- [x] **AC-2** SI el ticket está en `EnCurso`, `Cerrado` o ya en `Anulado`, ENTONCES la
      anulación responde 409 y no modifica el ticket ni agrega filas al historial.
  - **Evidencia:** `test_ciclo_vida_flujo_013.py::test_anulacion_desde_estado_inadmisible_responde_409_sin_efectos_ac_2`; recorrido `evidencia/README.md` §3.3 #12–#14 (409 desde `EnCurso`/`Cerrado`/`Anulado`, sin filas nuevas por SQL).
- [x] **AC-3** DADO QUE un ticket de la institución está en `Pendiente` o `EnRevision`,
      CUANDO un Bodeguero o el Administrador lo rechaza con motivo válido, ENTONCES responde 200
      con el ticket en `Anulado` y el historial registrando actor y motivo; SI el estado actual
      no admite el rechazo, ENTONCES responde 409 sin efectos.
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_rechazo_por_bodeguero_desde_pendiente_es_200_ac_3`, `test_rechazo_por_administrador_desde_en_revision_es_200_ac_3` y `test_rechazo_desde_en_curso_responde_409_sin_efectos_ac_3`; recorrido `evidencia/README.md` §3.1 #7 (rechazo del Bodeguero con motivo literal → `Anulado`) y §3.3 #15.
- [x] **AC-4** MIENTRAS un ticket esté en `Anulado`, NINGUNA operación puede sacarlo de ese
      estado; el cambio de estado hacia `Anulado` o desde `Anulado` responde 409 con un detalle
      que dirija a la operación correspondiente, y el estado nuevo es terminal también para el
      flujo lineal (sin avanzar ni retroceder). La misma imposibilidad de salida aplica a
      `Cerrado` en cualquier catálogo (AC-26).
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_patch_estado_no_lleva_a_anulado_y_dirige_a_la_operacion_ac_4`, `test_patch_estado_no_sale_de_anulado_ac_4` y `test_alta_en_anulado_responde_409_sin_ticket_d11` (D-11); recorrido `evidencia/README.md` §3.3 #16, #17 y #20. La salida desde `Cerrado` en cualquier catálogo queda cubierta por el AC-26.
- [x] **AC-5** La transición `EnCurso → Cerrado` sigue reservada al despacho transaccional de
      la 005 con su 409 y su detalle literal intactos; el despacho registra su transición en el
      historial; un ticket en `Anulado` no se puede despachar (409, estado no elegible).
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_en_curso_a_cerrado_sigue_reservado_al_despacho_ac_5`, `test_despacho_registra_su_transicion_en_el_historial_ac_5` y `test_despacho_de_un_anulado_responde_409_sin_movimientos_ac_5`; recorrido `evidencia/README.md` §3.2 #10 (409 con el literal de la 005) y #11 (despacho con fila de historial y rebaja de stock).
- [x] **AC-6** DADO QUE un ticket queda en `Cerrado` por cualquier camino vigente (alta,
      cambio de estado o despacho), ENTONCES conserva `fecha_cierre` no nula; DADO QUE un ticket
      queda en `Anulado`, ENTONCES su `fecha_cierre` permanece nula y la anulación no escribe
      movimientos de inventario.
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_alta_en_cerrado_sella_fecha_cierre_ac_6` y `test_despacho_sella_fecha_cierre_ac_6`; recorrido `evidencia/README.md` §3.1 #2 (anulado con fecha NULL y stock/movimientos intactos por SQL) y §3.2 #11 (despacho con `fecha_cierre` sellada).
- [x] **AC-7** ANTE una anulación o un rechazo con varios problemas simultáneos, el orden de
      respuesta es 404 (ticket inexistente o fuera de alcance, con detalle idéntico), luego 409
      (estado actual inadmisible) y luego 422 (motivo inválido); el resultado no depende de la
      bandera de la petición.
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_orden_404_ante_422_con_ticket_inexistente_y_motivo_invalido_ac_7`, `test_orden_409_ante_422_con_estado_inadmisible_y_motivo_invalido_ac_7`, `test_422_de_motivo_invalido_no_modifica_nada_ac_7` y `test_409_de_estado_inadmisible_con_motivo_valido_ac_7`; recorrido `evidencia/README.md` §3.3 #18 (404 idéntico), #12 (409) y #19 (422 sin efectos por SQL).

### Motivo

- [x] **AC-8** SI el motivo de anulación o rechazo falta, está vacío o excede la longitud
      máxima, ENTONCES responde 422 sin modificar estado, fechas ni historial; CON un motivo
      válido, ENTONCES la fila del historial de esa transición contiene el motivo literal.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_motivo_013.py` (4 tests AC-8: `test_motivo_faltante_responde_422_ac_8`, `test_motivo_vacio_responde_422_ac_8`, `test_motivo_sobre_la_longitud_maxima_responde_422_ac_8`, `test_motivo_en_el_limite_maximo_es_aceptado_y_se_persiste_literal_ac_8`); recorrido `evidencia/README.md` §3.1 #2/#7 (motivos literales persistidos por SQL) y §3.3 #19 (422 sin efectos).

### Historial de transiciones

- [x] **AC-9** Toda mutación de estado registra exactamente una fila de historial: la creación
      del ticket (estado de origen nulo, destino = estado inicial, actor = creador), el cambio
      de estado de la 004, el despacho de la 005, la anulación y el rechazo. Cada fila expone
      ticket, estado de origen, estado de destino, actor, marca de tiempo y motivo (nulo cuando
      la operación no lo exige).
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_historial_013.py` — `test_alta_registra_fila_de_creacion_con_origen_nulo_ac_9`, `test_cambio_de_estado_suma_exactamente_una_fila_ac_9` y `test_anulacion_y_rechazo_suman_exactamente_una_fila_ac_9`; recorrido `evidencia/README.md` §3.1 #1/#4, §3.2 #9 (1 fila por PATCH) y #11 (fila del despacho).
- [x] **AC-10** El historial es de solo lectura: no existe operación pública de creación,
      edición o borrado de sus filas fuera de las transiciones mismas, y su lectura ordena de
      forma determinista (más reciente primero, desempate estable).
  - **Evidencia:** `test_ciclo_vida_historial_013.py` — `test_orden_mas_reciente_primero_con_desempate_por_id_ac_10` y `test_historial_no_expone_operaciones_de_escritura_ac_10` (el OpenAPI no publica variantes de escritura del historial); recorrido `evidencia/README.md` §3.1 #4 (orden `fecha_transicion DESC, id DESC`).
- [x] **AC-11** DADO QUE un cambio de estado (o una anulación/rechazo) se acepta, ENTONCES el
      ticket y su fila de historial quedan persistidos juntos: si la fila no puede registrarse,
      el estado no cambia (y viceversa), sin efectos parciales.
  - **Evidencia:** `test_ciclo_vida_historial_013.py` — `test_transicion_aceptada_persiste_estado_y_fila_juntos_ac_11` y `test_si_la_fila_no_puede_registrarse_el_estado_no_cambia_ac_11` (inserción de historial forzada a fallar).
- [x] **AC-12** El historial NO contiene filas inventadas para transiciones ocurridas antes de
      esta feature: un ticket creado antes de la 013 sin transiciones posteriores muestra su
      historial vacío (o solo las filas de sus transiciones reales posteriores); no se migra ni
      se reconstruye autoría o motivo de transacciones pasadas.
  - **Evidencia:** `test_ciclo_vida_historial_013.py` — `test_ticket_legado_sin_transiciones_muestra_historial_vacio_ac_12` y `test_anulacion_de_legado_no_inventa_fila_de_creacion_ac_12`; gated `test_ciclo_vida_ticket_postgres_013.py::test_instalacion_nueva_no_siembra_historial_fabricado`; en el recorrido los tickets 6–12 pre-013 siguen sin filas inventadas (`evidencia/README.md` §3.4: 8 filas, solo del recorrido).

### Edición en Pendiente

- [x] **AC-13** DADO QUE un ticket propio del Solicitante (o de su institución, para el
      Administrador) está en `Pendiente`, CUANDO se edita con payload válido, ENTONCES responde
      200 con asunto, descripción, prioridad y detalles reflejados tal como se enviaron, con el
      conjunto de ítems reemplazado por completo; el estado, el solicitante, la sede y la
      institución no cambian.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_edicion_013.py` — `test_edicion_en_pendiente_reemplaza_cabecera_y_detalles_ac_13` y `test_edicion_conserva_estado_solicitante_sede_e_institucion_ac_13`; recorrido `evidencia/README.md` §3.1 #6 (PUT del ticket 14: ítems previos borrados, cabecera nueva y estado/sede/solicitante intactos por SQL).
- [x] **AC-14** SI el ticket no está en `Pendiente`, ENTONCES la edición responde 409 y no
      modifica cabecera ni detalles.
  - **Evidencia:** `test_ciclo_vida_edicion_013.py::test_edicion_fuera_de_pendiente_responde_409_sin_efectos_ac_14`; recorrido `evidencia/README.md` §3.3 #21 (PUT sobre ticket `Anulado` → 409).
- [x] **AC-15** SI la edición trae una referencia inválida (prioridad o producto inexistente,
      producto de otra institución, cantidad no positiva, detalles vacíos), ENTONCES responde
      404 o 422 según el caso y **no** escribe ni la cabecera ni ningún detalle: la validación
      completa del payload precede a la primera escritura (sin detalles parciales).
  - **Evidencia:** `test_ciclo_vida_edicion_013.py` (5 tests AC-15, todos con aserción de ausencia de escritura parcial): `test_edicion_con_prioridad_inexistente_responde_404_sin_escritura_ac_15`, `test_edicion_con_producto_inexistente_responde_404_sin_escritura_ac_15`, `test_edicion_con_producto_ajeno_responde_404_ocultado_sin_escritura_ac_15`, `test_edicion_con_cantidad_no_positiva_responde_422_sin_escritura_ac_15`, `test_edicion_con_detalles_vacios_responde_422_sin_escritura_ac_15`.
- [x] **AC-16** El Bodeguero y el Superadmin no pueden editar tickets (403); el Solicitante solo
      los suyos y el Administrador solo los de su institución; un ticket ajeno responde 404
      idéntico al inexistente.
  - **Evidencia:** `test_ciclo_vida_edicion_013.py` — `test_bodeguero_y_superadmin_no_pueden_editar_ac_16`, `test_solicitante_no_edita_ticket_ajeno_y_el_404_es_identico_ac_16`, `test_administrador_de_otra_institucion_edita_con_404_ocultado_ac_16` y `test_administrador_edita_tickets_de_su_institucion_ac_16`.

### Autorización

- [x] **AC-17** Las operaciones nuevas se declaran en la matriz central con exactamente estos
      roles: anulación (Solicitante, Administrador), rechazo (Bodeguero, Administrador), edición
      (Solicitante, Administrador), lectura de detalle e historial (los cuatro roles); el
      Superadmin obtiene 403 en toda escritura de ticket y una operación ausente de la matriz no
      concede permiso a nadie.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_autorizacion_013.py` (12 tests AC-17): matriz exacta (`test_matriz_tiene_exactamente_49_operaciones_ac_17`, `test_matriz_conserva_las_44_operaciones_previas_intactas_ac_17`, `test_matriz_declara_las_cinco_operaciones_con_los_roles_exactos_ac_17`), Superadmin sin escritura (`test_superadmin_no_obtiene_ninguna_escritura_nueva_ac_17`, `test_superadmin_obtiene_403_en_toda_escritura_nueva_ac_17`) y gating (`test_capacidad_kanban_apagada_bloquea_anulacion_y_rechazo_sin_mutar_ac_17`, `test_capacidad_tickets_apagada_bloquea_edicion_detalle_e_historial_ac_17`); contrato vivo: `/openapi.json` con **49 operaciones** v1 (51 totales con `GET /` y `/health`), las 5 nuevas aditivas con 401/403/404 (+409/422 en escrituras) — `evidencia/README.md` §4.
- [x] **AC-18** La autorización resuelve en dos pasos, y ninguno revela existencia: (a) SI la
      operación no concede el rol —p. ej. un Solicitante que intenta rechazar, o el Superadmin
      que intenta escribir—, ENTONCES responde 403 por la matriz (AC-17), **antes** de
      inspeccionar el recurso y sin indicar si el ticket existe; (b) DADO QUE el rol sí está
      concedido en la operación pero el ticket está fuera de su alcance —un Solicitante sobre
      un ticket ajeno en anulación o edición, o un Administrador/Bodeguero de otra
      institución—, ENTONCES la respuesta es 404 con detalle idéntico al de un ticket
      inexistente, sin revelar existencia por ninguna vía (lista, detalle, historial o
      mensajes de error).
  - **Evidencia:** `test_ciclo_vida_autorizacion_013.py` — `test_operar_ticket_ajeno_responde_404_identico_ac_18` (el caso `[rechazo]` se ejercita con el Administrador de la otra institución: tras la enmienda, un rol sin la operación —Solicitante en rechazo— recibe 403 matriz, no 404), `test_leer_ajeno_responde_404_identico_ac_18`, `test_rol_sin_permiso_de_escritura_recibe_403_ac_17` y `test_superadmin_obtiene_403_en_toda_escritura_nueva_ac_17`; recorrido `evidencia/README.md` §3.3 #18 (404 con detalle idéntico), #22 y #23 (403 sin mirar el recurso).
- [x] **AC-19** DADO QUE los cuatro roles consultan el detalle y el historial, ENTONCES cada
      uno recibe los tickets de su alcance vigente (Solicitante: propios; Administrador y
      Bodeguero: su institución; Superadmin: global); la lectura de detalle no concede al
      Superadmin ninguna capacidad de escritura.
  - **Evidencia:** `test_ciclo_vida_autorizacion_013.py` — `test_superadmin_lee_detalle_e_historial_ac_19`, `test_solicitante_lee_su_detalle_y_no_el_ajeno_ac_19` y `test_administrador_y_bodeguero_leen_el_detalle_de_su_institucion_ac_19` (más la verificación desechable contra BD real de T12: lector global 200 sin `DetachedInstanceError`); recorrido `evidencia/README.md` §3.1 #3–#4 (Solicitante) y §3.3 #24 (Superadmin global 200).

### Catálogo, instalación y versión

- [x] **AC-20** DADO una instalación nueva, ENTONCES el catálogo de estados incluye `Anulado`
      desde la estructura y la semilla, y el constructor de tenants lo replica en cada esquema;
      DADO una instalación existente, ENTONCES la migración operacional idempotente bajo
      `database/migraciones/` lo añade sin pérdida de datos, es re-ejecutable sin cambios y
      eleva el token de versión de control y de cada tenant existente a `013.1`.
  - **Evidencia:** gated `backend/tests/test_ciclo_vida_ticket_postgres_013.py` (7/7 en verde contra PG 16 sobre base desechable): `test_instalacion_nueva_replica_anulado_e_historial_en_control_y_tenants`, `test_instalacion_nueva_no_siembra_historial_fabricado`, `test_migracion_013_transiciona_012_1_preservando_datos_sin_fabricar_historial`, `test_migracion_013_es_idempotente`, `test_migracion_013_aborta_ante_estructura_parcial_sin_marcar_version`; estado real de `apt_erp` en `evidencia/README.md` §1 (versión `013.1`, quinta fila `Anulado`, respaldo previo `respaldos/apt_erp_pre_013.dump`).
- [x] **AC-21** Solo se enrutan tenants cuya versión es exactamente `013.1`; una versión
      distinta, ausente o duplicada deniega cerrado (patrón 010/011/012) y el catálogo
      replicado de todo tenant enrutado contiene el estado `Anulado` presente.
  - **Evidencia:** gated `test_ciclo_vida_ticket_postgres_013.py::test_tenant_en_012_1_deniega_con_el_objetivo_013_1` y `::test_el_codigo_apunta_a_la_version_013_1`; el recorrido entero operó sobre un tenant enrutado en `013.1` (`evidencia/README.md` §1).

### KPI del dashboard

- [x] **AC-22** El KPI de "tickets activos" del dashboard (009) excluye ahora los estados cuyo
      nombre canónico es `Cerrado` o `Anulado` (resolución por nombre, sin ids fijos): un
      ticket anulado no cuenta como activo para ningún rol; el resto de los KPI, el log de
      alertas y el ámbito por rol no cambian.
  - **Evidencia:** `backend/tests/api/test_ciclo_vida_dashboard_013.py` — `test_kpi_tickets_activos_excluye_anulado_por_nombre_ac_22`, `test_kpi_del_solicitante_no_cuenta_sus_anulados_ac_22` y `test_kpi_resto_del_dashboard_intacto_ac_22`; recorrido `evidencia/README.md` §3.3 #25 (`tickets_activos=3` para el Solicitante, contrastado con SQL por estado).

### Interfaz

- [x] **AC-23** DADO QUE un usuario autenticado accede al detalle de un ticket de su alcance,
      ENTONCES la vista muestra cabecera (asunto, prioridad, solicitante y departamento, sede y
      fechas), ítems con cantidades solicitadas y entregadas, y el historial completo; los
      estados vacíos y los errores son visibles y diferenciables.
  - **Evidencia:** `frontend/src/app/features/tickets/ticket-detalle.component.spec.ts` (27 specs, p. ej. `muestra cabecera con asunto, prioridad, estado, solicitante, departamento, sede y fechas`, `muestra los ítems con cantidades solicitadas y entregadas`, `muestra el historial completo con actor, de→a, instante y motivo`, `diferencia el historial vacío de un error`, `muestra un error accesible (role="alert") ante un 404 y permite reintentar`); `ng test` **323 SUCCESS** y `ng build` con chunk lazy `ticket-detalle-component` (T12); 4200 sirvió el chunk y 8080 lo sirve reconstruido (`evidencia/README.md` §1 y §8.2).
- [x] **AC-24** Toda mutación del ciclo de vida se opera desde la vista de detalle: avanzar o
      retroceder un paso en el flujo lineal según estado y rol; editar solo en `Pendiente` y
      solo para el dueño o el Administrador; anular (dueño/Administrador) y rechazar
      (Bodeguero/Administrador) solo en `Pendiente`/`EnRevision`, exigiendo motivo con
      confirmación previa; ninguna acción en `Cerrado` o `Anulado`. El tablero es de solo
      lectura: no ofrece controles de transición (ni de ninguna otra mutación); su única
      acción por tarjeta es "Gestionar", que abre el detalle del ticket, y añade la columna
      `Anulado` con sus tarjetas. Ante 404, 409 o 422 —al operar en el detalle o al abrir
      una tarjeta inexistente/ajena— se muestra un mensaje accesible (`role="alert"`), sin
      doble envío y reconsultando para reflejar el estado real del servidor.
  - **Evidencia:** `ticket-detalle.component.spec.ts` (acciones por estado/rol —p. ej. `Cerrado no ofrece ninguna acción y lo dice como estado terminal`—, `la confirmación exige motivo: vacío o en blanco no envía nada`, `no permite doble envío mientras el cambio de estado está en vuelo`, `muestra el 409 del servidor en un role="alert" y reconsulta la verdad del backend`) + `tickets.component.spec.ts` (`ofrece exactamente una acción «Gestionar» por tarjeta, sin controles de transición`, `surge del catálogo junto a las demás, con sus tarjetas`, `excluye Anulado de la elección de estado inicial`); humo 8080: `evidencia/README.md` §8.2 (chunk `TicketsComponent` con «Gestionar» y `TicketDetalleComponent` con «Historial de transiciones», servidos por HTTP).
- [x] **AC-25** Las suites de backend y frontend quedan en verde —incluidos los casos nuevos de
      flujo, autorización, historial, edición, migración (gated sobre PostgreSQL 16) y contrato
      `/openapi.json`— y el flujo se recorre en los dos puertos: 4200 con escritura real y 8080
      tras reconstruir la imagen (`AGENTS.md` §8.5–§8.6). Sin esto la feature no se cierra.
  - **Evidencia:** suites de cierre (T12): `pytest` SQLite **952 passed / 68 skipped / 0 failed**; gated PostgreSQL 16 **1020 passed / 0 skipped / 0 failed**; `ng test` **323 SUCCESS**; `ng build` limpio. Recorrido 4200 con escritura real: `evidencia/README.md` §3 (tickets 13–15 persistidos en `apt_erp`, migrada a `013.1`). Humo 8080 con imagen reconstruida: `evidencia/README.md` §8 (bundle `main-R6LIXDWJ.js`, `try_files` en `/tickets` y `/tickets/13`, API por proxy con token Clerk).

### Terminalidad por nombre (enmienda de D-4)

- [x] **AC-26** MIENTRAS un ticket esté en `Cerrado` o en `Anulado` —en el catálogo canónico o
      en **cualquier** catálogo degenerado—, NINGUNA operación de cambio de estado puede sacarlo
      de ese estado: `PATCH /estado` responde 409 sin modificar el ticket (el detalle de
      `Anulado` dirige a anulación/rechazo; el de `Cerrado`, a aceptar que el cierre es
      definitivo y que el despacho es el único camino a él). La reentrada en `Cerrado` es
      imposible: ninguna petición de cambio de estado puede llevar un ticket **a** `Cerrado`
      (el único camino vigente a ese estado sigue siendo el despacho transaccional de la 005),
      y, en consecuencia, un ticket ya despachado no puede volver a ningún estado despachable
      —imposible doble rebaja de stock—. Un catálogo en que `Cerrado` no sea el último estado
      no altera nada de esto (la terminalidad no depende de la posición).
  - **Evidencia:** `test_ciclo_vida_flujo_013.py` — `test_catalogo_degenerado_sin_salida_desde_cerrado_ac_26`, `test_catalogo_degenerado_sin_salida_desde_anulado_ac_26`, `test_reentrada_en_cerrado_es_imposible_en_catalogo_degenerado_ac_26` y `test_ticket_despachado_no_vuelve_a_un_estado_despachable_ac_26`; recorrido `evidencia/README.md` §3.3 #10 (409 con el literal del cierre reservado), #16 y #17 (catálogo canónico).

**Cerrada (19/Oct/2026):** AC-1…AC-26 en verde con la evidencia de arriba; `pytest` SQLite 952 passed/68 skipped/0 failed, gated PostgreSQL 16 1020 passed/0 skipped/0 failed, `ng test` 323 SUCCESS y `ng build` limpio; matriz/OpenAPI de **49 operaciones** v1; recorrido funcional en 4200 con escritura real (`evidencia/README.md` §3) y humo en 8080 con la imagen reconstruida (bundle `main-R6LIXDWJ.js`, §8). Enmiendas incorporadas durante la implementación: **D-4/AC-26** (la terminalidad por nombre canónico en cualquier catálogo sustituyó a la ordinal de la 004) y **AC-18** (un rol sin la operación en la matriz —p. ej. Solicitante en rechazo— recibe 403, no el 404 de ocultamiento).

## 8. Restricciones

- `constitucion.md` §2 (Trazabilidad Absoluta): el historial de transiciones es inmutable; la
  anulación no mueve stock y por lo tanto no genera movimientos de inventario — la auditoría de
  `movimiento_inventario` sigue cubriendo exclusivamente cambios de existencias.
- `constitucion.md` §3 (Consistencia Transaccional): el cambio de estado y su fila de
  historial son una sola operación; la edición de cabecera y de ítems es otra; ningún rechazo
  deja efectos parciales.
- `AGENTS.md` §7 (cambio de modelo justificado): esta feature **añade un estado al catálogo
  `estado_ticket`** y **crea una estructura de historial de transiciones de ticket**; la
  justificación de modelo correspondiente vivirá en `docs/spec/stack.md` como prerrequisito
  aprobado del plan, antes de tocar modelos, DDL o migraciones. Esta spec decide el qué y el
  porqué, no la implementación.
- `AGENTS.md` §6: identificadores en español (estructuras, columnas, operaciones y mensajes).
- Derogación parcial de la Feature 004, en el patrón que la propia 004 usó con la 005: quedan
  derogados **en su capa de UI** los AC-9, AC-10, AC-12, AC-19 y AC-20 de
  `004-tablero-kanban/spec.md` (transiciones por botón en el tablero y su feedback 409/404 en
  el tablero) y lo concerniente al tablero de sus D-2 (controles en la tarjeta) y D-7
  (movimiento y reconsulta de la tarjeta); el backend de `PATCH /estado` conserva intactos su
  orden de validación, el flujo lineal de un paso entre los cuatro estados operativos y el
  sellado de `fecha_cierre`, y la operación de transición se concentra en la vista de detalle
  (D-14).
- **Derogación adicional de la 004 (enmienda de D-4):** la regla de terminalidad **ordinal** de
  su D-2 y su §5 ("el último estado del orden del catálogo es terminal", con salida desde él en
  catálogos degenerados) quedan **sustituidos**, en el dominio del ciclo de vida de tickets, por
  la resolución por nombre canónico: `Cerrado` y `Anulado` son terminales por nombre y ninguno
  admite transición de salida vía `PATCH /estado` (409) en **cualquier** catálogo (AC-26). Su
  test degenerado `test_reentrar_en_cerrado_conserva_la_fecha_original`
  (`backend/tests/api/test_tablero_kanban.py`), que exige `Cerrado → Archivado` = 200 cuando
  `Cerrado` no es el último del catálogo, queda derogado: esa petición responde hoy 409. El
  resto de la 004 —flujo lineal entre operativos, orden de validación ticket→estado→flujo,
  sellado de `fecha_cierre` y cierre reservado al despacho (005)— permanece intacto. La 004 se
  conserva sin editar: es registro histórico de su release.
- `AGENTS.md` §7: sin dependencias nuevas; la matriz central de permisos solo recibe filas
  aditivas; el gating de capacidades por institución de la 012 se aplica a las operaciones
  nuevas sin modificar la matriz; Clerk sigue siendo la única autoridad de autenticación.
- El catálogo de estados permanece sin CRUD: `Anulado` se siembra, se construye por tenant y se
  migra; no se administra desde la interfaz.
- Concurrencia: se conserva el comportamiento vigente (última escritura gana en el cambio de
  estado; el despacho mantiene su bloqueo); el historial registra ambas transiciones si ambas
  se aceptaron en su momento.
- La migración operacional nunca usa la semilla destructiva y es verificable contra
  PostgreSQL 16; SQLite no acredita el token de versión ni la replicación por esquema.
