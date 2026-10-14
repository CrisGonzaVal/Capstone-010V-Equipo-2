# Feature 004: Tablero Kanban operativo con columnas por estados

**Estado:** aprobada
**Release:** 1.0 — Sprint 2
**Tipo:** Valor de negocio (operación diaria del bodeguero)

## 1. Problema

El actor **Bodeguero** necesita supervisar el flujo de tickets y moverlos por sus etapas
(`constitucion.md:12`), pero hoy el tablero es una vitrina falsa y el cambio de estado es
inutilizable desde la interfaz. Cinco huecos verificados:

- **El tablero no muestra tickets reales.** Las cuatro columnas y sus tarjetas están
  escritas a mano, y sus nombres de estado (`INGRESADO`, `EN PREPARACIÓN`, `DESPACHADO`,
  `ENTREGADO`) no coinciden con los del catálogo real (`Pendiente`, `EnRevision`,
  `EnCurso`, `Cerrado`). La vista promete una capacidad que no tiene.
- **Nada de la interfaz cambia estados.** La operación de cambio de estado existe en el
  backend, pero ningún control la invoca: un ticket nacido en `Pendiente` se queda ahí
  para siempre salvo que alguien consuma la API a mano.
- **El cambio de estado no valida nada.** Acepta cualquier número como estado — incluso
  uno que no existe — y también saltos del flujo (de `Pendiente` directo a `Cerrado`).
  Silenciosamente, no por error.
- **El cierre depende de un id fijo (4).** Decidir si un ticket se cierra se resuelve
  comparando contra la constante `ESTADO_CERRADO_ID = 4`, que no tiene garantía de que el
  catálogo la respete: si el orden de los estados cambia, los tickets se cierran sin sellar
  fecha. Deuda documentada desde la Feature 001 y heredada por la 003.
- **Tres vocabularios de estados conviven en el proyecto** (catálogo real, datos de prueba
  y tablero de muestra), así que ni los usuarios ni el código se ponen de acuerdo en cómo
  se llama cada etapa.

## 2. Objetivo

Que el tablero muestre **tickets reales, agrupados por los estados reales del catálogo**, y
que el bodeguero pueda moverlos por su flujo con botones que solo ofrecen transiciones
válidas — con errores honestos y sin depender de ids numéricos fijos.

## 3. Alcance

### Dentro

- **Columnas reales**: una columna por cada estado del catálogo, en el orden del flujo,
  visibles siempre aunque no tengan tickets, con su contador.
- **Tarjetas reales**: tickets agrupados por su estado, con asunto, prioridad, solicitante,
  fecha de creación y, si la tienen, fecha de cierre.
- **Transiciones con botones**: avanzar / retroceder un paso por tarjeta, ofreciendo solo
  las transiciones válidas según el flujo.
- **Reglas de transición en el backend**: validar que el estado y el ticket existen y que
  la transición respeta el flujo lineal; rechazar lo demás con errores identificables
  (recurso inexistente / conflicto).
- **Cierre por nombre canónico**: sellar la fecha de cierre cuando el ticket entra al
  estado llamado `"Cerrado"` (sin distinguir mayúsculas), no al comparar un id fijo; todo
  ticket cerrado queda con fecha.
- **Filtros del tablero**: por prioridad y búsqueda de texto en el asunto, aplicados a
  todas las columnas y contadores.
- **Sincronización de la vista**: al aceptarse una transición la tarjeta cambia de columna;
  al crearse un ticket desde el modal aparece en el tablero; ante un rechazo el tablero se
  reconsulta para reflejar el estado real.
- **`listar_tickets`**: orden explícito por `fecha_creacion` descendente y carga de
  `detalles` sin consulta por fila (N+1), tal como lo delegó la 003
  (`003-modal-ticket/spec.md:75-77`); el tablero es su primer consumidor (AC-27).
- **Documentación**: cierre de la fila 004 en el roadmap y corrección de la lista cerrada
  de textos que convierten el id 4 en requisito: comentarios de
  `database/02_datos_semilla.sql`, la nota de `backend/tests/conftest.py`, el comentario de
  `frontend/src/app/features/tickets/tickets.component.ts` y `MEMORY.md` (donde además se
  afirma que la semilla no asigna ids, siendo falso: `02_datos_semilla.sql:223-227` los
  inserta explícitos). Las specs históricas 001 y 003 quedan intactas: son registro, no
  norma (AC-25).

### Fuera

- **Drag & drop**: mover tarjetas arrastrando. Esta versión usa solo botones.
- **Refresco automático**: sin consultas periódicas ni en tiempo real; el tablero se
  actualiza al cargar, al transicionar, al crear y al filtrar.
- **Vista de detalle del ticket**: hacer clic para ver ítems o descripción completa.
- **Permisos por rol**: hasta la Feature 007 todos pueden transicionar (la autenticación es
  decorativa).
  *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
  (Clerk) y la autorización por roles se implementó en la Feature 007.*
- **CRUD de estados**: el catálogo de estados es de solo lectura; no se agregan ni editan
  etapas desde la interfaz.
- **Reabrir tickets cerrados**: el estado terminal no admite retroceso (en el catálogo
  canónico, `Cerrado`).
- **Filtro por solicitante, departamento o sede**: se ve todo el sistema.
- **Despacho con rebaja de stock y auditoría**: es la Feature 005.
- **Modificaciones al formulario de alta**: el formulario de la Feature 003 sigue
  funcionando igual (mismos campos y validaciones). Lo único que cambia relacionado con el
  alta está en el backend: un ticket que nace en `Cerrado` sella su fecha de cierre
  (AC-17), y el ticket recién creado se refleja en el tablero.
- **Concurrencia multiusuario**: sin control de versión; si dos usuarios transicionan el
  mismo ticket casi a la vez, gana la última escritura (límite declarado en §7).
- **Paginación y volúmenes grandes**: el tablero carga el conjunto completo de tickets
  (límite declarado en §7).

## 4. Decisiones

### D-1 — Las columnas salen del catálogo, nunca de nombres escritos a mano

El vocabulario del tablero es el del catálogo de estados y su orden es el orden del flujo.
Ese orden —`estado_id` ascendente— es el mismo que `stack.md` §2 (líneas 128-130) declara
contrato para las listas del catálogo; esta feature lo adopta explícitamente como orden de
columnas y como regla de transición. Si mañana el catálogo cambia
de nombre o agrega una etapa, el tablero la refleja sin reescritura. Esto elimina la
divergencia entre las tres fuentes de vocabulario actuales.

### D-2 — Flujo lineal de un paso, con el último estado como terminal

Las transiciones solo van entre estados contiguos del flujo, en cualquier dirección de un
paso, y el **último estado del orden del catálogo es terminal**: su tarjeta no ofrece
ningún control — ni avanzar (no hay siguiente) ni retroceder (los tickets cerrados no se
reabren). En el catálogo canónico eso es exactamente `Pendiente ↔ EnRevision ↔ EnCurso →
Cerrado`. Saltar estados, retroceder desde el terminal o pedir el estado que el ticket ya
tiene se rechazan: el tablero jamás ofrece esas opciones, y rechazarlas evita sellar fechas
dos veces o cerrar por error. La regla la impone el backend para **toda** llamada, no solo
la que llega del tablero.

### D-3 — El estado final se reconoce por su nombre, no por su id

El sistema determina "¿este estado es el cierre?" buscándolo por su nombre canónico
`"Cerrado"` en el catálogo, **sin distinguir mayúsculas de minúsculas** (`Cerrado`,
`CERRADO` y `cerrado` equivalen; así los datos de prueba existentes siguen siendo válidos
mientras se los alinea al nombre canónico). Así se elimina la dependencia del id 4:
reordenar o recrear el catálogo no rompe el sellado de fechas. Si el ticket vuelve a entrar
en `Cerrado` —solo alcanzable con catálogo degenerado—, la fecha ya sellada se conserva:
nunca se sobrescribe. Corrige la deuda H-2 y sus comentarios obsoletos.

### D-4 — Todo ticket en `Cerrado` tiene fecha de cierre, por el camino que sea

No solo la transición sella fecha: un ticket **nacido** en `Cerrado` (el alta de la Feature
003 permite elegir estado inicial) también debe quedar con fecha. Si no, la trazabilidad
del ciclo de vida del propio ticket queda rota en un caso que la propia interfaz permite
producir.

### D-5 — La tarjeta muestra lo necesario para decidir sin abrir nada

Asunto, prioridad, solicitante, fecha de creación y — si el ticket tiene fecha de cierre —
esa fecha. Es lo mínimo para que el bodeguero juzgue si toca avanzar o retroceder. Los ítems
detallados son de una futura vista de detalle (fuera de alcance). Si un ticket trae fecha
de cierre en una columna que no es la de cierre —dato inconsistente tras reordenar el
catálogo—, la tarjeta la muestra igual: el tablero refleja, no corrige.

### D-6 — Filtros de prioridad y búsqueda por asunto

El bodeguero con muchas solicitudes necesita aislar lo urgente (`Alta`) o localizar un
ticket por fragmento de asunto. La búsqueda **no distingue mayúsculas ni acentos**
(`revision` encuentra `Revisión`), `%` y `_` se buscan como texto literal (no como
comodines), y un texto vacío o de solo espacios cuenta como "sin búsqueda". Los dos filtros se combinan en **intersección**: con ambos activos solo se
muestran los tickets que cumplen los dos. Los filtros son sobre el conjunto ya cargado,
afectan a **todas** las columnas y a sus contadores, y tienen valor por defecto que muestra
todo.

### D-7 — Mover solo si el backend acepta; si no, alerta y reconsulta

La tarjeta se mueve únicamente cuando la operación tiene éxito: la interfaz no adelanta
movimientos que puedan revertirse. Si el backend **no acepta la operación por cualquier
motivo** — 404 (ticket o estado inexistente), 409 (transición fuera del flujo), 500 o
ausencia de respuesta (red caída, timeout) —, la tarjeta permanece, se muestra un mensaje
accesible y el tablero se vuelve a consultar para reflejar la verdad del servidor —
incluido el caso en que otro usuario ya movió ese ticket.

### D-8 — Orden de validación: ticket, estado y recién el flujo

Ante una petición de cambio de estado, el sistema valida en este orden: (1) que el ticket
exista (404), (2) que el estado pedido exista en el catálogo (404), (3) que la transición
respete el flujo (409). Con ese orden, un 404 siempre significa "lo que pediste no está" y
un 409 siempre "está, pero no corresponde", sin ambigüedad cuando concurren varios
problemas en la misma petición. Referenciada en AC-13, AC-14 y AC-15.

## 5. Reglas del flujo

La regla general es **ordinal** y sale del catálogo: avanzar es pasar al estado siguiente
del orden y retroceder al anterior; el primero no tiene retroceso y el último (terminal) no
tiene ningún control. La tabla siguiente muestra esa regla aplicada al catálogo canónico de
la semilla — es un ejemplo, no una lista cerrada de estados:

| Desde | Avanzar a | Retroceder a |
|---|---|---|
| Pendiente | EnRevision | — (es el primero) |
| EnRevision | EnCurso | Pendiente |
| EnCurso | Cerrado | EnRevision |
| Cerrado | — (terminal) | — (terminal) |

Cualquier otra combinación (saltos, retroceso desde el terminal, estado actual repetido,
estado inexistente) se rechaza sin modificar el ticket (D-2, D-8).

## 6. Criterios de aceptación

### Columnas, tarjetas y filtros

- [x] **AC-1** El sistema DEBE mostrar una columna por cada estado del catálogo, en el orden
      del flujo, incluidas las que no tienen tickets.
- [x] **AC-2** DADO QUE existen tickets, EL SISTEMA DEBE agrupar cada uno en la columna de su
      estado actual, ordenados dentro de la columna por fecha de creación (más reciente
      primero; en empate, el de mayor `ticket_id`).
- [x] **AC-3** Cada columna DEBE mostrar el conteo de tarjetas que contiene después de
      aplicar los filtros.
- [x] **AC-4** Cada tarjeta DEBE mostrar asunto, prioridad, solicitante y fecha de creación;
      SI el ticket tiene fecha de cierre, ENTONCES DEBE mostrarla también.
- [x] **AC-5** SI una columna queda sin tickets — esté vacía o tras filtrar —, ENTONCES DEBE
      mostrar un mensaje de vacío diferenciable del estado de error.
- [x] **AC-6** MIENTRAS el filtro de prioridad esté activo, EL SISTEMA DEBE mostrar en todas
      las columnas solo los tickets de esa prioridad; el valor por defecto DEBE ser "todas".
- [x] **AC-7** MIENTRAS haya texto en la búsqueda —sin contar vacío o solo espacios—, EL
      SISTEMA DEBE filtrar por asunto sin distinguir mayúsculas ni acentos ni tratar `%` y
      `_` como comodines, DEBE surtir efecto en columnas y contadores, y SI también hay
      filtro de prioridad, ENTONCES solo se muestran los que cumplen ambos (intersección,
      D-6).
- [x] **AC-8** DADO QUE el usuario crea un ticket desde el modal, ENTONCES el tablero DEBE
      reflejarlo sin recargar la página; SI hay filtros activos que no lo admiten, ENTONCES
      no se muestra (los filtros rigen siempre, D-6).
- [x] **AC-27** `GET /tickets/` DEBE responder con orden explícito por `fecha_creacion`
      descendente y sin una consulta por fila al cargar `detalles` (carga de colección en
      una sola consulta); pruebas de backend fijan ambas cosas.

### Transiciones

- [x] **AC-9** DADO QUE el usuario pulsa "avanzar" en una tarjeta, ENTONCES el ticket DEBE
      pasar al estado siguiente del flujo y la tarjeta DEBE aparecer en esa columna.
      **Derogada parcialmente por la Feature 005:** la transición `EnCurso→Cerrado` queda
      reservada al despacho transaccional; ver `005-despacho-transaccional/spec.md`.
- [x] **AC-10** DADO QUE el usuario pulsa "retroceder" en una tarjeta, ENTONCES el ticket
      DEBE pasar al estado anterior del flujo y la tarjeta DEBE aparecer en esa columna.
- [x] **AC-11** SI un ticket está en el estado terminal —el último del orden del catálogo;
      en el canónico, `Cerrado`—, ENTONCES su tarjeta NO DEBE ofrecer ningún control de
      transición (D-2).
- [x] **AC-12** El tablero NO DEBE ofrecer transiciones inválidas: sin "avanzar" en el
      último estado, sin "retroceder" en el primero y sin saltos de más de un paso.
- [x] **AC-13** SI la transición solicitada sale del flujo lineal, retrocede desde el
      estado terminal o pide el estado que el ticket ya tiene, ENTONCES el sistema DEBE
      rechazarla con conflicto (409), NO DEBE modificar el ticket ni su fecha.
- [x] **AC-14** SI el `estado` pedido no existe en el catálogo, ENTONCES el sistema DEBE
      responder recurso inexistente (404) nombrando la referencia, sin modificar el ticket.
- [x] **AC-15** SI el ticket no existe, ENTONCES el sistema DEBE responder 404. La
      validación del ticket precede a la del estado y a la del flujo (D-8).
- [x] **AC-16** DADO QUE una transición válida lleva el ticket a `Cerrado`, ENTONCES el
      sistema DEBE sellar su fecha de cierre en esa misma operación, conservando la fecha
      si ya existía: nunca se sobrescribe (D-3).
- [x] **AC-17** DADO QUE un ticket queda en `Cerrado` por cualquier camino (alta directa o
      transición), ENTONCES DEBE tener fecha de cierre (D-4).
- [x] **AC-18** El sistema DEBE determinar el estado final por su nombre canónico `"Cerrado"`
      —sin distinguir mayúsculas—, de modo que cambiar el orden o los ids del catálogo NO
      DEBA romper el sellado de fechas (D-3).

### Feedback de la interfaz

- [x] **AC-19** DADO QUE el backend acepta la transición, ENTONCES la tarjeta DEBE moverse y
      los contadores actualizarse sin recargar la página, con el control deshabilitado
      mientras la operación está en curso (sin doble envío).
- [x] **AC-20** SI el backend no acepta la operación — 404, 409 u otro fallo, incluida la
      ausencia de respuesta —, ENTONCES la tarjeta NO DEBE moverse, DEBE mostrarse un
      mensaje accesible (`role="alert"`) y el tablero DEBE reconsultarse para reflejar el
      estado real del servidor.

### Verificación

- [x] **AC-21** La suite de pruebas del backend y la del frontend quedan en verde, incluidos
      los casos nuevos de transiciones válidas, rechazadas y sellado de fecha.
- [x] **AC-22** El proyecto compila para producción.
- [x] **AC-23** El tablero se recorre en el navegador contra el backend real: agrupa tickets
      existentes, se avanza y retrocede un ticket con escritura real, y un rechazo (409) se
      provoca con dos pestañas sobre un ticket en `EnRevision`: la primera pulsa "avanzar"
      (estado real: `EnCurso`) y la segunda, sin recargar, pulsa "retroceder" (envía
      `Pendiente` contra el estado real `EnCurso` → salto → 409), mostrando la alerta sin
      mover la tarjeta. Sin esto la feature no está cerrada (`AGENTS.md` §8.5).
- [x] **AC-24** La recorrida se hace en los dos puertos del frontend, tras reconstruir la
      imagen, para que 8080 refleje la feature (`AGENTS.md` §8.6).
- [x] **AC-25** Coherencia documental: fila de la 004 cerrada en `roadmap.md`, `MEMORY.md`
      actualizado, y `grep -rn "ESTADO_CERRADO_ID" backend frontend database MEMORY.md` → 0
      coincidencias: la constante, sus comentarios en backend/semilla/frontend y su mención
      en `MEMORY.md` desaparecen (`AGENTS.md` §8.7). `docs/spec/` queda fuera del grep: las
      specs 001 y 003 son registro histórico.
- [x] **AC-26** `git diff` sin cambios estructurales en el modelo de datos ni en los datos
      de los scripts de base (`01_esquema.sql` y los INSERT de `02_datos_semilla.sql`
      intactos): la feature no cambia el esquema (`AGENTS.md` §7) ni agrega dependencias
      nuevas. Reescribir comentarios de la semilla sí está permitido (AC-25): no es
      estructura.

### Evidencia de verificación (2026-10-13)

- AC-1: test `debe mostrar una columna por estado del catalogo, en orden, incluidas las vacias` (`tickets.component.spec.ts:616`); en navegador 4200 y 8080 aparecen las 4 columnas: Pendiente, EnRevision, EnCurso, Cerrado.
- AC-2: tests `...agrupar cada ticket...` y `...ordenar por fecha de creacion DESC y, en empate, por ticket_id DESC` (`tickets.component.spec.ts:632,645`); la API real devuelve el orden `[10,2,1,3,4,5,6,7,8,9]`.
- AC-3: test `...contar las tarjetas despues de filtrar...` (`tickets.component.spec.ts:718`); en 8080, filtrando `folders`, los conteos quedan 0/1/0/0.
- AC-4: test `...asunto, prioridad, solicitante y fechas...` (`tickets.component.spec.ts:659`); snapshot con prioridad, `#id`, asunto, `solicitante · departamento`, `Creado:` y `Cerrado:`.
- AC-5: test `debe diferenciar el vacio por filtros del vacio normal (AC-5)` (`tickets.component.spec.ts:804`): `Sin tickets en esta columna` vs `Ningún ticket coincide con los filtros`.
- AC-6: test `debe arrancar en "todas" y filtrar por prioridad (AC-6)` (`tickets.component.spec.ts:699`).
- AC-7: tests de búsqueda sin distinguir mayúsculas ni acentos, `%` y `_` literales, texto vacío o de solo espacios, e intersección (`tickets.component.spec.ts:736,761,775,787`).
- AC-8: tests `AC-8: el ticket creado aparece en el tablero sin recargar` y `...no aparece si los filtros no lo admiten` (`tickets.component.spec.ts:1013,1030`).
- AC-9: `test_avanzar_un_paso_pasa_al_siguiente_estado` (`test_tablero_kanban.py:156`); en el navegador, #10 pasó de `estado_id 2` a `3`, verificado con `SELECT` sobre la base.
- AC-10: `test_retroceder_un_paso_vuelve_al_estado_anterior` (`test_tablero_kanban.py:171`); #10 volvió de `3` a `2`, verificado con `SELECT` sobre la base.
- AC-11: test `AC-11: en el estado terminal no se ofrece ningun control` (`tickets.component.spec.ts:846`); tarjetas #7/#8/#9 en Cerrado sin controles.
- AC-12: tests `AC-12: en el primer estado no hay retroceso` y `...ids contiguos, sin saltos` (`tickets.component.spec.ts:837,915`).
- AC-13: `test_salto_de_estado_se_rechaza_con_409`, `...estado repetido...`, `...retroceso desde el terminal...` (`test_tablero_kanban.py:188,204,220`); API real: PATCH #6 Cerrado → 1 respondió 409.
- AC-14: `test_estado_inexistente_responde_404_sin_modificar` (`test_tablero_kanban.py:239`), con `estado` en el detalle.
- AC-15: `test_ticket_inexistente_responde_404` y `test_el_ticket_se_valida_antes_que_el_estado` (`test_tablero_kanban.py:263,273`, orden D-8).
- AC-16: `test_avanzar_a_cerrado_esta_reservado_al_despacho` verifica la política de cierre reservado introducida por la 005 (el cierre manual `EnCurso→Cerrado` responde 409); `test_reentrar_en_cerrado_conserva_la_fecha_original` conserva la fecha de cierre (`test_tablero_kanban.py`). La transición manual de la 004 fue derogada parcialmente por la Feature 005; el cierre operativo se verifica mediante despacho.
- AC-17: `test_crear_ticket_en_cerrado_sella_fecha_cierre` (`test_tablero_kanban.py:369`); en la semilla los tickets 7/8/9 están en Cerrado con `fecha_cierre` no nula.
- AC-18: `test_el_cierre_reservado_no_depende_del_id_del_estado` verifica que la reserva del cierre se resuelve por nombre, no por id fijo; `test_el_sellado_no_distingue_mayusculas` (`CERRADO`) conserva la comprobación de mayúsculas/minúsculas (`test_tablero_kanban.py`).
- AC-19: tests `AC-9/AC-19: moverSiguiente emite un PATCH y mueve la tarjeta sin recargar` (con `expectNone(RUTA_TICKETS)`) y `...control deshabilitado y no hay doble envio` (`tickets.component.spec.ts:860,899`).
- AC-20: tests de 409, 404 y sin respuesta (`tickets.component.spec.ts:944,978,996`); en navegador, dos pestañas sobre #10: primera avanzó (`2→3`), segunda sin recargar pidió retroceder y recibió 409; `role="alert"` mostró `Transicion invalida: el ticket esta en el estado 3 y se pidio 1...`, la base quedó en 3, la tarjeta no se movió y el tablero se reconsultó.
- AC-21: `pytest` → 95 passed, 1 warning preexistente de `starlette.testclient`; `ng test` → TOTAL: 63 SUCCESS.
- AC-22: `ng build` de producción compiló (inicial 312.80 kB, chunk lazy 65.38 kB) y 8080 sirvió `main-DJROJJG5.js` y chunks con hash de la imagen reconstruida.
- AC-23: recorrido completo en 4200 contra backend real: columnas/conteos, #10 avanzó (`2→3`) y retrocedió (`3→2`) comprobado con `SELECT`; 409 entre dos pestañas con alerta accesible, tarjeta inmóvil y reconsulta. Consola sin errores salvo el 409 intencional.
- AC-24: 8080 tras reconstruir y recrear imagen: las cuatro columnas renderizan (conteos 2/2/3/3), `try_files` de nginx responde en `/tickets` y el filtro de humo responde; consola limpia.
- AC-25: `grep -rn "ESTADO_CERRADO_ID"` en backend, frontend, database y MEMORY.md → 0; `MEMORY.md` actualizado y fila 004 cerrada en roadmap.
- AC-26: `git diff 6421d97..HEAD` vacío sobre `database/01_esquema.sql`, `backend/requirements.txt`, `frontend/package.json` y `package-lock.json`; `02_datos_semilla.sql` solo cambió líneas de comentario, ni un INSERT ni TRUNCATE tocado.
- AC-27: tests de `GET /tickets/` con orden `fecha_creacion DESC`, desempate `ticket_id DESC` y carga de detalles sin consultas por fila (T4); `pytest` completo: 95 passed.

**Observación de entorno:** el recorrido real modificó la semilla de la base de desarrollo: ticket #10 quedó en `estado_id 3` y ticket #6 en Cerrado con `fecha_cierre` sellada. No afecta la suite, que usa SQLite en memoria.

**Estado de cierre:** cerrada tras validación aprobada y evidencias AC-1…AC-27.

## 7. Restricciones

- `constitucion.md:17` (Trazabilidad): esta feature **no** cambia stock ni escribe en
  movimientos de inventario; el despacho es la Feature 005.
- `constitucion.md:18` (Consistencia Transaccional) exige atomicidad entre la rebaja de
  existencias y el cambio de estado en el despacho (Feature 005); esta feature aplica el
  mismo principio a su pareo: el cambio de estado y el sellado de la fecha de cierre DEBEN
  ocurrir en una sola operación atómica — o ambas cosas, o ninguna.
- `AGENTS.md` §7: sin dependencias nuevas (por eso drag & drop queda fuera) y sin cambios
  al modelo de 12 entidades.
- `AGENTS.md` §6: identificadores en español.
- Autenticación decorativa hasta la Feature 006/007: no se filtra por rol ni sede.
  *Nota posterior al cierre: la autenticación decorativa fue superada por la Feature 006
  (Clerk) y la autorización por roles se implementó en la Feature 007.*
- **Catálogo de estados degenerado**: si está vacío, el tablero muestra un estado de error
  visible (nunca columnas en blanco silencioso); si trae un número distinto de estados, el
  flujo ordinal se adapta sin casos especiales; y si falta el estado llamado `"Cerrado"`,
  el tablero sigue operando pero no se sellan fechas de cierre — configuración degradada
  que esta feature no corrige (el CRUD de estados está fuera de alcance); y si el nombre
  `"Cerrado"` aparece repetido, gana el de menor `estado_id` para sellar.
- **Concurrencia**: último-gana sin control de versión; agregarlo exigiría cambiar el modelo
  de datos (`AGENTS.md` §7) y AC-20 ya mitiga la vista obsoleta reconsultando.
- **Volumen**: sin paginación; el tablero asume el conjunto completo cargable de una vez
  (la semilla tiene 10 tickets). Si el volumen real lo exige, la paginación es una feature
  nueva.
- Con backend caído el tablero muestra un estado de error visible con reconsulta al
  recuperar, nunca una pantalla en blanco silenciosa.
