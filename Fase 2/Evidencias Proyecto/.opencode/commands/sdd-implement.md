---
description: "SDD · Implementa UNA tarea, tests primero (uso: /sdd-implement 004-nombre T3)"
agent: implementer
subagent: true
---

Implementa SOLO la tarea $2 de `docs/spec/features/$1/tasks.md`, siguiendo `docs/spec/features/$1/plan.md`, `docs/spec/features/$1/spec.md`, la constitución y la skill `sdd-workflow`.

1. Escribe primero los tests y comprueba que fallan.
2. Escribe el código hasta que pasen.
3. Ejecuta `python -m pytest` en `backend/` y `npx ng test --watch=false --browsers=ChromeHeadless` en `frontend/` (con `CHROME_BIN` a Edge; AGENTS.md §5) y muéstrame el resultado.
4. Marca $2 como hecha en `tasks.md` e indica qué AC cubre.

Después PÁRATE. No empieces la siguiente tarea.
