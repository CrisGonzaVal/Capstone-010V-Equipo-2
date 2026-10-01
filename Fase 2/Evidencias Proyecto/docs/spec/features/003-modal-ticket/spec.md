?# Feature 003: Modal de Crear Ticket y Persistencia Transaccional de Ítems

**Estado:** En curso
**Release:** 1.0 — Sprint 1
**Tipo:** Valor de negocio (primera escritura end-to-end del ciclo de abastecimiento)

## 1. Problema

El ciclo de abastecimiento arranca con el Actor **Solicitante** emitiendo un requerimiento
justificado para su departamento (`constitucion.md:13`). Hoy ese primer paso no existe en la
interfaz, y el endpoint que lo debería sostener responde con errores de infraestructura.
Seis huecos concretos, verificados en el código:

- **El botón "+ Crear Ticket" es un control muerto.**
  `frontend/src/app/features/tickets/tickets.component.html:9-14` no tiene `(click)`. Es
  exactamente el defecto que la Feature 002 corrigió en el inventario: un control que no
  hace nada promete una capacidad que no existe.
- **El tablero es de mentira.** `tickets.component.ts:43-100` es un `signal` con 4 columnas
  y 6 tarjetas escritas a mano, y sus nombres de estado (`INGRESADO`, `EN PREPARACIÓN`,
  `DESPACHADO`, `ENTREGADO`) **no coinciden** con los de `estado_ticket` (`Pendiente`,
  `EnRevision`, `EnCurso`, `Cerrado`).
- **`POST /api/v1/tickets/` responde 500 ante una FK inválida.** Es H-1 de la Feature 001,
  sigue vivo a propósito y lo fijan dos tests: `tests/api/test_smoke.py:152` y
  `tests/api/test_transaccion_ticket.py:27`.
- **`TicketCrear` no valida nada.** `backend/app/schemas/ticket_schema.py:9-30`: `asunto`
  sin `max_length` contra un `VARCHAR(150) NOT NULL`, `detalles` admite lista vacía (un
  ticket sin ningún ítem) y `cantidad_solicitada` admite `0` y negativos, que el DDL
  rechaza con `detalle_cantidad_solicitada_ck CHECK (cantidad_solicitada > 0)`
  (`database/01_esquema.sql:215`). Los tres caminos terminan en **500 en vez de 422**.
- **No hay ningún endpoint de `prioridad` ni de `estado_ticket`.** Cualquier formulario
  tendría que codificar ids, que es la deuda H-2: `ESTADO_CERRADO_ID = 4` en
  `ticket_service.py:14` resultó ser falso y está documentado como tal.
- **No hay un solo formulario reactivo en el proyecto.** `grep` de `ReactiveFormsModule`,
  `FormGroup`, `formControlName` y `ngModel` en `frontend/src/app` → 0 coincidencias. El
  primer formulario se construye desde cero.

## 2. Objetivo

Que el solicitante emita un ticket con sus ítems detallados desde la interfaz, y que el
alta sea **transaccional y con errores honestos**: 422 por entrada inválida y 404 por
referencia inexistente, nunca 500.

## 3. Alcance

### Dentro

- **Backend — endpoint nuevo** `GET /api/v1/tickets/catalogos`: read model con los cuatro
  catálogos que el formulario necesita (prioridades, estados, productos, solicitantes) (§5).
- **Backend — validaciones de entrada** en `TicketCrear` y `DetalleTicketCrear`, que
  devuelven 422 y espejan los CHECK del DDL.
- **Backend — corrección de H-1 en tickets**: `crear_ticket` valida las 4 referencias
  antes del primer `add()` y responde **404** con mensaje, en vez de dejar que la FK
  reviente con 500. Se agrega el `rollback()` explícito que hoy no existe en el service.
- **Backend — calidad de las 3 rutas de tickets**: `status_code` y `description`
  explícitos, como exige `AGENTS.md` §6.
- **Frontend — `URL_API` a `shared/`**: corrige la violación de `AC-10` de la Feature 001
  que ya está en `HEAD` (D-2).
- **Frontend — tipos**: `Prioridad` y `EstadoTicket` en `shared/interfaces/index.ts`.
- **Frontend — modal reactivo**: solicitante, prioridad, estado, asunto, descripción y un
  `FormArray` de ítems (producto + cantidad), con mensajes de error por campo, tres
  estados distinguibles y aviso de éxito con el `ticket_id` creado.
- **Frontend — `(click)`** en el botón que hoy está muerto, y el `FormArray` con al menos
  una fila de detalle.
- **Frontend — tests**: `tickets.component.spec.ts`, el primero del dominio.
- **Documentación**: `roadmap.md`, `stack.md` (read model de catálogos), `MEMORY.md` y
  `AGENTS.md` §5 (los dos puertos).

### Fuera

- **El tablero Kanban.** Sigue con datos de muestra. Es H-3 y se resuelve en la Feature 004,
  que además corregirá `ESTADO_CERRADO_ID` (`tickets.component.ts:22-35` ya remite a
  ella).
- **`PATCH /tickets/{ticket_id}/estado`.** No se toca, y tampoco el `ESTADO_CERRADO_ID = 4`
  que usa. Es de la Feature 004.
- **`listar_tickets`.** No declara `order_by` y serializa `detalles` con N+1, pero ningún
  cliente lo consume todavía. Arreglarlo aquí sería trabajo de la 004 sin caller que lo
  justifique.
- **Validación de stock al crear el ticket.** El stock se rebaja en el despacho, dentro de
  una transacción con el cambio de estado (`constitucion.md:18`); al solicitar no se toca
  `inventario`, así que esta feature ni puede escribir en esa tabla (`constitucion.md:17`).
- **Duplicados de producto en un mismo ticket.** El DDL no declara `UNIQUE (ticket_id,
  producto_id)`, así que la base los admite. Se resuelven **en el cliente**, sumando las
  cantidades, porque un selector que ya eligió "Resma Carta" dos veces es un error de
  UX, no una regla de negocio.
- **Autenticación real.** `get_current_user` lanza 501 y no lo usa ninguna ruta. El
  solicitante se elige a mano (D-3).
- **Filtro de solicitantes por rol.** `GET /usuarios/` devuelve los 10 usuarios de la
  semilla, incluidos los administrativos. Filtrar por rol es de la Feature 007.
- **CRUD de catálogo** y **`GET /inventario/movimientos`**, que son de las Features 004
  y 005.

## 4. Decisiones

### D-1 — Un endpoint de catálogos en el dominio de tickets

El formulario necesita cuatro catálogos y solo dos son del dominio de tickets. En vez de
que el componente de tickets importe los servicios de inventario y de usuarios, se expone
**un** endpoint, `GET /api/v1/tickets/catalogos`, que devuelve los cuatro juntos.

Por qué no importar entre features: `AC-10` de la Feature 001 dice "ninguna feature importa
otra" y la Feature 002 lo reforzó en su `AC-17`. Además `stack.md` §3 reserva `shared/`
para lo que puede usar cualquier feature, así que duplicar dentro de `TicketService` los
GET de otros dominios (y con ellos una copia de la URL) reintroduce justo el god-service
que la D-3 de la Feature 001 borró.

Por qué un endpoint y no cuatro: el formulario se abre una vez y necesita los cuatro a la
vez. Un solo round-trip en vez de cuatro es mejor de entrada, y la respuesta es un read
model deliberado, no un agregador accidental: `ticket_service` solo **lee** `Producto` y
`Usuario`, y ya dependía del dominio de productos por escritura (`DetalleTicket.producto_id`).

**Disparador para revisarlo:** si la 004 o la 009 necesitan estos mismos catálogos para
páginas que **no** son el formulario, el endpoint se reparte por recurso
(`/inventario/existencias` y `/usuarios/`) y el consumidor cruza features desde una capa
`core/data-access/` que se crea en ese momento.

### D-2 — `URL_API` se mueve a `shared/` para cumplir `AC-10` de verdad

Hoy `features/tickets/services/ticket.service.ts:6` y
`features/administracion/services/usuario.service.ts:6` importan `URL_API` desde
`features/inventario/services/inventario.service`. Eso **ya viola** `AC-10` de la Feature
001, que se marcó `[x]` solo con la evidencia de que existían 4 chunks de rutas
(`001-reestructuracion-modular/tasks.md:226`), sin grepear imports cruzados.

La constante es configuración, no lógica de negocio: no le pertenece a la feature de
inventario ni a ninguna otra. Pasa a `shared/config/url-api.ts` con el mismo nombre de
exportación (`URL_API`) para no producir ruido en el diff, y los **cuatro** sitios que la
importan pasan a leerla de ahí: los tres servicios (`inventario`, `administracion`,
`tickets`) y `inventario.component.spec.ts`, que hoy la toma de `./services/inventario.service`
— un import que no cruza features pero que se rompe igual al mover la constante, así que se
actualiza en la misma jugada. Se actualiza la línea correspondiente de `stack.md` §3.

Se corrige en esta feature porque la 003 es la primera que necesita shared para algo real:
si se dejara, la deuda crecería con cada archivo que importe la URL desde inventario.

### D-3 — El solicitante se elige de un `<select>`, no de una constante

`get_current_user` lanza `501 Not Implemented` y ninguna ruta lo usa: la autenticación es
decorativa hasta la Feature 006. No hay "usuario actual" que resolver, así que el formulario
expone el solicitante en un desplegable poblado con los 10 usuarios de la semilla, mostrando
apellido, nombre y correo. No se persiste preferencia: el desplegable arranca vacío y el
usuario lo elige cada vez.

La alternativa —una constante con el id de un solicitante de demo— es menos código pero se
rompe en cuanto cambie la semilla, que es el mismo error que H-2 en otra capa.

### D-4 — El estado inicial es el primero del catálogo, no el que se llama "Pendiente"

El `<select>` de estado arranca en la primera entrada que devuelve el catálogo, que con el
orden por `estado_id` es `Pendiente`. Se elige por posición y no comparando el string
`"Pendiente"` por dos razones: si mañana el catálogo se llama distinto, el formulario sigue
funcionando; y no se duplica en el cliente una verdad que ya vive en el backend.

En un despliegue con autenticación real este campo deja de ser elegible y lo asigna el
sistema. Para la demostración del Hito 1 queda editable a propósito: poder arrancar un
ticket en cualquier estado deja ver el `PATCH /tickets/{id}/estado` funcionando en vivo.

### D-5 — Las validaciones de entrada van en el schema Pydantic

| Campo | Regla | Espeja |
|---|---|---|
| `TicketCrear.asunto` | `min_length=3`, `max_length=150` | `ticket.asunto VARCHAR(150) NOT NULL` |
| `TicketCrear.detalles` | `min_length=1` | regla de negocio: un ticket sin ítems no es un requerimiento |
| `DetalleTicketCrear.cantidad_solicitada` | `gt=0` | `detalle_cantidad_solicitada_ck` |

FastAPI convierte esas tres en **422** automáticamente, con el detalle por campo que el
formulario necesita para pintar el error bajo el input correcto. No hace falta escribirlas
a mano en el service: la validación de forma es del schema, la de existencia es del service
(D-6). La separación no es arbitraria — es la que ya usa `crear_producto` con su categoría.

### D-6 — Referencia inexistente → 404, prevalidada antes del primer `add()`

`crear_ticket` inserta a ciegas: si el `producto_id` no existe, la FK viola y la petición
muere con 500. Se valida `Usuario`, `Prioridad`, `EstadoTicket` y **todos** los `Producto`
antes de la primera escritura, y se responde **404** con mensaje que dice qué referencia
falló, siguiendo el precedente de `crear_producto` en la Feature 002 (`inventario_service.py`,
D-8 de su spec).

Prevalidar en vez de dejar que la FK reviente tiene una consecuencia que se documenta en
`tasks.md`: el ticket huérfano pasa a ser **imposible por construcción**, y el `rollback()`
pasa a ser la red de seguridad para fallos de base, no el mecanismo que impide el huérfano.
El `rollback()` explícito se agrega igual, con `try/except`, porque hoy `crear_ticket`
no lo tiene y `constitucion.md:18` exige reversión completa ante cualquier fallo.

Los dos tests que fijan el 500 se migran a 404 **conservando todas sus aserciones de
atomicidad**: que no quede ticket creado y que el stock no se mueva.

### D-7 — El modal es un `<dialog>` nativo, sin dependencias nuevas

No hay `@angular/cdk` ni `@angular/material` en `package.json`, y `AGENTS.md` §7 prohíbe
agregar paquetes sin análisis previo. El elemento `<dialog>` con `showModal()` da foco
atrapado, cierre con `Esc` y `::backdrop` sin instalar nada, que es todo lo que el modal
necesita. El `--webkit-` que Safari pidió durante años ya no aplica: el soporte es general.

`@angular/forms@^18.2.0` **ya está declarado** en `package.json:17`, así que
`ReactiveFormsModule` no requiere instalar nada: es el primer uso, no una dependencia nueva.

## 5. Contrato de la API

### `GET /api/v1/tickets/catalogos`

`response_model=CatalogosTicketRespuesta` · `status_code=200` ·
resumen: "Consultar los catálogos que necesita el formulario de alta de ticket"

```python
class PrioridadRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prioridad_id: int
    nombre: str
    descripcion: str | None


class EstadoTicketRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    estado_id: int
    nombre: str
    descripcion: str | None


class ProductoCatalogoRespuesta(BaseModel):
    producto_id: int
    nombre: str
    unidad_medida: str | None
    categoria_nombre: str
    stock_total: int
    es_critico: bool


class SolicitanteRespuesta(BaseModel):
    usuario_id: int
    nombre: str
    apellido: str
    correo: str
    departamento_nombre: str


class CatalogosTicketRespuesta(BaseModel):
    prioridades: list[PrioridadRespuesta]
    estados: list[EstadoTicketRespuesta]
    productos: list[ProductoCatalogoRespuesta]
    solicitantes: list[SolicitanteRespuesta]
```

`PrioridadRespuesta` y `EstadoTicketRespuesta` llevan `from_attributes` porque son **una**
entidad cada una: Pydantic las lee del objeto ORM. `ProductoCatalogoRespuesta` y
`SolicitanteRespuesta` **no** lo llevan porque cruzan tablas (`producto` + `categoria`,
`usuario` + `departamento`) y sus campos `categoria_nombre` / `departamento_nombre` no
existen en la entidad: las arma el service, con el patrón de read model de `stack.md` §2.

`correo` es `str` y no `EmailStr` a propósito: el DTO es una proyección de lectura para un
desplegable, y no vale la pena arrastrar el validador de correo a un catálogo.

**Las cuatro listas salen siempre**, aunque estén vacías: el formulario distingue "no hay
catálogo" de "el backend no respondió", y una clave ausente no permite esa distinción.

**Orden:** `prioridades` por `prioridad_id` y `estados` por `estado_id`, porque en ambos
casos el id es el orden del flujo (Alta→Media→Baja; Pendiente→EnRevision→EnCurso→Cerrado) y
alfabéticamente quedarían Alta, Baja, Media. `productos` por `nombre` y luego `producto_id`.
`solicitantes` por `apellido`, `nombre` y `usuario_id`. Totalmente determinista.

**Ejemplo de respuesta** (con los datos de QA de `database/02_datos_semilla.sql`, recortado
a 2 productos y 2 solicitantes):

```json
{
  "prioridades": [
    { "prioridad_id": 1, "nombre": "Alta", "descripcion": "Necesario para operar en el corto plazo" },
    { "prioridad_id": 2, "nombre": "Media", "descripcion": "Requiere reposicion pero no bloquea la operacion" },
    { "prioridad_id": 3, "nombre": "Baja", "descripcion": "Puede esperar a la siguiente compra periodica" }
  ],
  "estados": [
    { "estado_id": 1, "nombre": "Pendiente", "descripcion": "Ticket creado, aun sin revision" },
    { "estado_id": 2, "nombre": "EnRevision", "descripcion": "Revisando justificacion y disponibilidad" }
  ],
  "productos": [
    { "producto_id": 5, "nombre": "Boligrota Bic Cristal", "unidad_medida": "UNIDAD",
      "categoria_nombre": "Escritura", "stock_total": 150, "es_critico": false },
    { "producto_id": 9, "nombre": "Grapadora Estandar", "unidad_medida": "UNIDAD",
      "categoria_nombre": "Equipos", "stock_total": 1, "es_critico": true }
  ],
  "solicitantes": [
    { "usuario_id": 5, "nombre": "Isabel", "apellido": "Contreras",
      "correo": "isabel.contreras@losalpes.cl", "departamento_nombre": "Docencia" },
    { "usuario_id": 1, "nombre": "Camila", "apellido": "Fernandez",
      "correo": "camila.fernandez@losalpes.cl", "departamento_nombre": "Direccion" }
  ]
}
```

Los dos primeros son los que salen con el orden por apellido: la lista de la semilla mezcla
dominios `@losalpes.cl` y `@cordillera.cl`, y también roles, así que el desplegable muestra
el departamento para que dos nombres parecidos no se confundan.

`stock_total` y `es_critico` se calculan con la **misma** `es_stock_critico()` que usa el
endpoint de existencias de la Feature 002, para que el catálogo y la tabla de inventario no
puedan discrepar. `stock_total` suma todas las sedes.

### `POST /api/v1/tickets/` — cambios

El contrato no cambia en su forma: los mismos campos, los mismos nombres, el mismo
`TicketRespuesta` de respuesta. Lo que cambia es qué se **rechaza**:

| Entrada | Antes | Ahora |
|---|---|---|
| `producto_id` inexistente | 500 | **404** con mensaje |
| `usuario_id`, `prioridad_id`, `estado_id` inexistente | 500 | **404** con mensaje |
| `asunto` de 1 o de 200 caracteres | 500 (o se guardaba truncado) | **422** por campo |
| `detalles: []` | 201, ticket sin ítems | **422** por campo |
| `cantidad_solicitada: 0` o negativa | 500 (CHECK del DDL) | **422** por campo |

Y un caso que **no** cambia, a propósito: pedir más de lo que hay en stock sigue siendo un
201. El stock se rebaja en el despacho (`constitucion.md:18`).

## 6. Criterios de aceptación

### Contrato y lógica de negocio

- [x] **AC-1** `GET /api/v1/tickets/catalogos` responde 200 con las cuatro listas
      presentes, y `/openapi.json` lo declara con su `response_model`.
- [x] **AC-2** `prioridades` viene ordenada por `prioridad_id` y `estados` por `estado_id`,
      de modo que el estado inicial del formulario sea el primero del flujo
      (`Pendiente`, no el alfabéticamente último).
- [x] **AC-3** Cada producto trae `categoria_nombre`, `stock_total` y `es_critico`, y
      `es_critico` sale de la **misma** `es_stock_critico()` que usa
      `GET /inventario/existencias`.
- [x] **AC-4** Cada solicitante trae nombre, apellido, correo y `departamento_nombre`.
- [x] **AC-5** Las cuatro listas salen **siempre**, aunque estén vacías; con la base vacía el
      endpoint responde 200 con `{"prioridades": [], "estados": [], "productos": [],
      "solicitantes": []}` y no 404 ni 500.
- [x] **AC-6** `POST /tickets/` con `producto_id` inexistente responde **404** con mensaje
      que nombre la referencia, no 500 (D-6).
- [x] **AC-7** `POST /tickets/` con `usuario_id`, `prioridad_id` o `estado_id` inexistente
      responde **404** en los tres casos.
- [x] **AC-8** Un 404 en cualquiera de las referencias **no deja ticket a medias**: la lista
      de tickets sigue igual y el stock de ningún producto se movió. Los dos tests de
      atomicidad de la Feature 001 se migran de 500 a 404 **conservando sus aserciones**.
- [x] **AC-9** `asunto` de menos de 3 caracteres o de más de 150 responde **422**; un
      `detalles: []` responde **422**; `cantidad_solicitada` en `0` o negativa responde
      **422** (D-5).
- [x] **AC-10** Un ticket válido sigue respondiendo **201** con su cabecera y sus detalles,
      y `cantidad_entregada` arranca en `0` en cada ítem.
- [x] **AC-11** `POST /tickets/` no valida stock: pedir por sobre lo disponible sigue siendo
      201 y no toca `inventario` (`constitucion.md:17-18`).
- [x] **AC-12** Las 3 rutas de tickets declaran `status_code` y `description` explícitos
      (`AGENTS.md` §6), y las que ya los tenían no cambian de comportamiento.
- [x] **AC-13** `GET /tickets/` y `PATCH /tickets/{id}/estado` devuelven **el mismo JSON**
      que antes: esta feature no los toca.
- [x] **AC-14** `git diff` vacío en `backend/app/models/` y en `database/01_esquema.sql`
      (`AGENTS.md` §7). No hay ningún cambio de modelo.
- [x] **AC-15** El service sigue siendo delgado: `grep -rn "db.query\|db.get" app/api/`
      → sin cambios. Toda la lógica de negocio queda en `app/services/`.

### Frontend

- [x] **AC-16** El botón "+ Crear Ticket" abre el modal, y `grep` del template confirma que
      ya no queda ningún `(click)` sin manejador.
- [x] **AC-17** El modal pide `GET /tickets/catalogos` **una** vez al abrirse y con una sola
      llamada alimenta los cuatro desplegables; no consulta `/usuarios/` ni
      `/inventario/existencias`.
- [x] **AC-18** El formulario tiene solicitante, prioridad, estado, asunto, descripción y un
      `FormArray` de ítems con al menos una fila; cada ítem elige producto y cantidad.
- [x] **AC-19** No se puede enviar con el formulario inválido: el botón se deshabilita y los
      errores aparecen bajo el campo que los causa, leyendo el 422 del backend por campo.
- [x] **AC-20** Al crear, el modal se cierra y se avisa con el `ticket_id` asignado. El
      tablero **no** cambia: sigue con sus datos de muestra (H-3, Feature 004).
- [x] **AC-21** Un error del backend al guardar deja el modal abierto con el formulario
      intacto y un mensaje `role="alert"`; un error al cargar los catálogos muestra un
      estado de error distinguible del de guardado.
- [x] **AC-22** Cargar catálogos y guardar ticket tienen estados de carga separados, y en
      ambos el botón de enviar queda deshabilitado para evitar el doble envío.
- [x] **AC-23** `URL_API` vive en `shared/config/url-api.ts` y
      `grep -rn "inventario.service" frontend/src/app` → 0 coincidencias fuera de
      `inventario.service.ts` y `inventario.component.ts`. `AC-10` de la Feature 001 queda
      cumplido en los hechos, no solo en la casilla (D-2).
- [x] **AC-24** `shared/interfaces/index.ts` declara `Prioridad`, `EstadoTicket`,
      `ProductoCatalogo`, `Solicitante` y `CatalogosTicket` en `snake_case`, reflejando 1:1
      los schemas nuevos.
- [x] **AC-25** `grep` de `@NgModule`, `*ngIf`, `*ngFor` y `CommonModule` en
      `frontend/src/app` → 0, y `grep` de `style=` en `features/tickets` → 0. Solo clases
      de Tailwind (`AGENTS.md` §6).

### Verificación

- [x] **AC-26** `cd backend && pytest` en verde: los 43 casos previos más los nuevos. Cuatro de
      los previos **se reescribieron a propósito**, y el criterio no es "intactos" sino que no
      se tocara ninguno fuera de esos cuatro: `test_smoke.py` (1 caso) y
      `test_transaccion_ticket.py` (3 casos) fijaban el 500 del defecto que esta feature
      corrige, así que sus `status_code` pasaron a 404 conservando el resto de sus
      aserciones. Verificado con
      `grep -rn "responde_500|500_defecto|status_code == 500" backend/tests` → 0.
- [x] **AC-27** `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` en
      verde con los 12 tests previos más los nuevos de `tickets.component.spec.ts`.
- [x] **AC-28** `cd frontend && npm run build` compila.
- [x] **AC-29** El modal se recorre en el navegador contra el backend real: se crea un
      ticket, aparece el aviso con su `ticket_id`, y `GET /tickets/` lo lista con sus
      detalles. Sin esto la feature no está cerrada (`AGENTS.md` §8.5).
- [x] **AC-30** El endpoint se ejecuta contra el **PostgreSQL 16** del `docker-compose`, no
      solo contra SQLite, porque `es_stock_critico` y los agregados de `stock_total` tienen
      que coincidir con lo que muestra la tabla de inventario.
- [x] **AC-31** Coherencia documental: `roadmap.md` con la fila de la 003, `stack.md` con el
      read model de catálogos y con la ubicación de `URL_API`, `MEMORY.md` actualizado,
      `AGENTS.md` §5 con la nota de los dos puertos, y `grep` de rutas `.md` rotas → 0.
- [x] **AC-32** La imagen del frontend queda reconstruida, para que `localhost:8080`
      sirva la misma vista que `localhost:4200` y no deje de reflejar la feature.
      Entender que 8080 no se actualiza solo es la mitad del AC: reconstruir **y**
      recorrer en los dos puertos es el criterio de cierre (`AGENTS.md` §8.5 y §8.6).

## 7. Restricciones

- `constitucion.md:17` (Trazabilidad Absolenta): esta feature **no** cambia stock, así que no
  toca `movimientos_inventario`. `registrar_movimiento` y sus tests quedan intactos.
- `constitucion.md:18` (Consistencia Transaccional): el alta del ticket y sus ítems van en
  **una** transacción. `crear_ticket` ya lo hace con `flush()` + `commit()`; lo que se agrega
  es el `rollback()` explícito ante un fallo de base. Honestidad sobre su alcance: con el
  `get_db` actual ese `rollback()` es **redundante de forma observable**, porque `get_db`
  hace `db.close()` en su `finally` y `close()` ya revierte (comprobado por mutación: borrar
  la línea deja los 79 tests en verde). Se conserva porque el método debe ser correcto por sí
  mismo y no gracias al cleanup de quien lo llama. Lo que **sí** hace imposible el ticket
  huérfano es la prevalidación de D-6, que no escribe nada, y eso es lo que verifica
  `AC-8`. Detalle en `plan.md` §4 y `tasks.md` §9.
- `AGENTS.md` §6: identificadores en español; solo `model_config = ConfigDict(...)`, nunca
  `class Config`; `Session` por `Depends(get_db)`; sin SQL raw; `status_code` y
  `response_model` explícitos en cada ruta.
- `AGENTS.md` §7: sin paquetes nuevos. `@angular/forms` ya está declarado. El modal usa
  `<dialog>` nativo, así que no hace falta `@angular/cdk`.
- `AGENTS.md` §7 y `AC-10` de la Feature 001: ninguna feature importa otra. Por eso los
  catálogos llegan por un endpoint del dominio de tickets (D-1) y `URL_API` vive en
  `shared/` (D-2).
- `stack.md` §2: el read model de los catálogos se arma en el service, sin `from_attributes`,
  con los onclause explícitos y el agregado resuelto sobre un conjunto acotado.
- La suite corre sobre **SQLite en memoria** con `PRAGMA foreign_keys=ON`. Ojo: los CHECKs
  del DDL **no existen en SQLite**, así que el test de `cantidad_solicitada` en verde
  demuestra que responde 422 por el schema de Pydantic, no que la base lo rechace. Por eso
  `AC-30` corre el endpoint contra PostgreSQL.
- Los tests se escriben por el **seam HTTP** (`TestClient`), nunca consultando la base
  directamente, y sin ids fijos: se usan los ids que devuelve `datos_base`.
- El fixture nuevo se apoya en `datos_base` y no lo reemplaza, para no romper los 43 casos
  que dependen de su forma.
