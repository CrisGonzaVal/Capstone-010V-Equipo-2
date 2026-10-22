# Feature 007 — Evidencia de la enmienda de autoatribución (AC-18…AC-20)

Spec: [`../spec.md`](../spec.md) · Tareas: [`../tasks.md`](../tasks.md)
Recorrido completo, capturas y contraste en BD: [`../../003-modal-ticket/evidencia/README.md`](../../003-modal-ticket/evidencia/README.md)
(la enmienda es transversal a 003/007/008 y se ejecutó una sola vez, el **2026-10-22**).

Esta evidencia cubre **solo** los AC de la enmienda; no reescribe la evidencia histórica de
cierre de la 007.

## AC-18 — Atribución incondicional

- **Backend:** `pytest` SQLite **1405 passed / 77 skipped / 0 failed**; gated PostgreSQL 16
  **1482 passed / 0 skipped / 0 failed** (bases temporales desechables; `apt_erp` intacta en
  `014.1`). Tests reales: `test_tickets_alcance.py::test_roles_autorizados_atienden_la_identidad_de_sesion`
  (Administrador/Bodeguero/Solicitante con `usuario_id` omitido, propio, ajeno e inexistente →
  201 y autoría de sesión), `::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`,
  `::test_administrador_crea_para_solicitante_propio_201`, `::test_solicitante_crea_y_se_atribuye_su_identidad`;
  `test_tickets_institucional.py::test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion`
  (sin 404 por usuario), `test_tickets_alcance.py::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion`;
  `test_modal_ticket.py::test_ticket_con_usuario_inexistente_se_ignora_y_atiende_a_la_sesion`.
  Superadmin conserva 403 y la matriz sigue en **62** operaciones (`/openapi.json`: 62 rutas `/api/v1`).
- **Contrato:** `TicketCrear.required = prioridad_id, estado_id, asunto, detalles` (sin
  `usuario_id`); `usuario_id` es `anyOf[integer,null]` documentado como ignorado; `POST /tickets/`
  no documenta 404 por usuario.
- **4200:** el POST real del Administrador (`ticket 11`, usuario 13) y de la Solicitante
  (`ticket 12`, usuario 11) viajó **sin `usuario_id`** y respondió **201**.

## AC-19 — Presentación del autor y catálogo

- **Frontend:** `ng test` **470 SUCCESS / 0 FAILED** (Edge 155, `CHROME_BIN`). En
  `tickets.component.spec.ts` la identidad se presenta en solo lectura, no existe `<select>` ni
  control editable `usuario_id` y el body no incluye ese campo.
- **4200:** el modal mostró «Solicitante (sesión)» con nombre y correo de la identidad
  (Administrador QA014 y Paula Rojas en cada sesión) y **sin selector**; `GET /tickets/catalogos`
  siguió respondiendo con `solicitantes` para listados/detalle.
- **8080:** tras `docker compose build frontend` + `up -d`, 8080 sirve **`main-QNRFXFUT.js`**
  (antes `main-KWQKKL6Q.js`), el modal abre con el campo informativo y la navegación básica responde.

## AC-20 — Herencia del ámbito y sede

- **Backend:** `test_tickets_alcance.py::test_departamento_sin_sede_responde_409_sin_ticket_detalle_ni_historial`
  y `test_ticket_sede_011.py::test_crear_ticket_sin_sede_de_departamento_afecta_a_todos_los_roles_creadores`
  (409 sin escritura); `::test_crear_ticket_almacena_la_sede_del_departamento` (con sede → 201).
- **4200 + BD:** Administrador (usuario 13, Dirección) → `ticket 11` con `sede_id 1`;
  Solicitante (usuario 11, Biblioteca) → `ticket 12` con `sede_id 2`; ambos con
  `institucion_id INST-001`. No se usó `usuario.sede_id` como sustituto.

## Hallazgos

Sin defectos de la enmienda. Persiste el aviso preexistente de accesibilidad de campos sin
`id`/`name` en los formularios (no introducido por este cambio).
