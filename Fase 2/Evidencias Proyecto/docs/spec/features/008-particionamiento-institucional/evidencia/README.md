# Feature 008 — Evidencia de la enmienda AC-11 (autoatribución de tickets)

Spec: [`../spec.md`](../spec.md) · Tareas: [`../tasks.md`](../tasks.md)
Recorrido completo, capturas y contraste en BD: [`../../003-modal-ticket/evidencia/README.md`](../../003-modal-ticket/evidencia/README.md)
(ejecutado el **2026-10-22**).

Esta evidencia cubre **solo** la AC-11 reescrita por la enmienda; la evidencia histórica del
resto de la 008 no se altera.

## AC-11 — Aislamiento institucional al crear tickets

- **Atribución ignorada:** `pytest` SQLite **1405 passed / 77 skipped / 0 failed**; gated
  PostgreSQL 16 **1482 passed / 0 skipped / 0 failed**. Tests reales:
  `test_tickets_institucional.py::test_solicitante_ignora_usuario_ajeno_y_conserva_autoatribucion`,
  `test_tickets_alcance.py::test_administrador_ignora_solicitante_de_otra_institucion_y_atribuye_a_sesion` (el
  `usuario_id` ajeno se ignora, ya no hay 404 por usuario),
  `test_tickets_alcance.py::test_roles_autorizados_atienden_la_identidad_de_sesion`.
- **Anclas institucionales:** `test_tickets_institucional.py::test_crear_ticket_puebla_institucion_en_ticket_y_detalle`
  (ticket y detalle con la institución de la sesión). En el recorrido real, `ticket 11` y
  `ticket 12` quedaron con `institucion_id INST-001` en cabecera y detalle (usuarios 13 y 11,
  ambos de INST-001).
- **404 por producto ajeno conservado:** `test_tickets_institucional.py::test_crear_ticket_con_producto_ajeno_404_sin_parcial`
  (404 y ninguna fila parcial). La descripción de `POST /tickets/` en `/openapi.json` mantiene
  ese 404 por producto ajeno y aclara que `usuario_id` no produce 404.
- **Matriz intacta:** `/openapi.json` publica **62** operaciones `/api/v1`, igual que
  `app.core.permisos.MATRIZ_PERMISOS` (62); Superadmin sigue sin `POST /tickets/` (403).
- **Recorrido 4200:** altas reales de Administrador y Solicitante con body sin `usuario_id` →
  **201**, autoría y sede de la identidad de sesión (capturas en la carpeta de la 003).
- **Humo 8080:** imagen reconstruida (`main-QNRFXFUT.js`), modal con el campo informativo; sin
  escrituras de negocio.

## Hallazgos

Sin defectos. Persiste el aviso preexistente de accesibilidad de campos sin `id`/`name`.
