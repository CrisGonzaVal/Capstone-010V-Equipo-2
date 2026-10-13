---
description: SDD · Genera el plan técnico de una spec aprobada
agent: planner
---

Lee `docs/spec/constitucion.md`, `docs/spec/stack.md`, `AGENTS.md` y `docs/spec/features/$1/spec.md`. Usa la skill `sdd-workflow`.
NO escribas código.

Genera `docs/spec/features/$1/plan.md` con: archivos que se crean o modifican y la responsabilidad de cada uno, decisiones técnicas justificadas (con su alternativa descartada), estrategia de tests (`pytest` en backend, `ng test` en frontend) y qué AC cubre cada parte.

Todo debe respetar la constitución, `stack.md` y las convenciones de AGENTS.md §6. Si la spec no está aprobada o tiene dudas abiertas (`[NECESITA ACLARACIÓN]`), para y avísame.
