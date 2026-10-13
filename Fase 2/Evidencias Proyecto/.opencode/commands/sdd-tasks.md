---
description: SDD · Divide el plan en tareas pequeñas y verificables
agent: planner
---

A partir de `docs/spec/features/$1/spec.md` y `docs/spec/features/$1/plan.md`, genera `docs/spec/features/$1/tasks.md` siguiendo la skill `sdd-workflow`:

- Tareas en orden de dependencia, cada una con los AC que cubre.
- Cada una con una línea `Hecho cuando:` verificable.
- Checkboxes (`- [ ]`).
- Intenta que no sean más de 10-15: si salen más, propón dividir la spec.
- La última tarea debe ser el cierre: suites en verde + recorrido en 4200 y 8080 (AGENTS.md §8.5-§8.6) + actualización de `MEMORY.md`.
