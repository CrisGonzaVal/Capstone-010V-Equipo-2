---
description: SDD · Nuevo requisito en una feature existente - primero la spec, luego el código
agent: planner
---

Nuevo requisito para la spec `docs/spec/features/$1/` (el texto que va después del nombre de la carpeta): $ARGUMENTS

NO toques código. Usa la skill `sdd-workflow`.

1. Actualiza `docs/spec/features/$1/spec.md`: nuevo AC (o cambio de uno existente) verificable, con sus casos límite y lo que queda fuera de alcance, y vuelve `**Estado:**` a `borrador` (un cambio invalida la aprobación anterior).
2. Indica qué partes de `plan.md` y `tasks.md` habría que cambiar después.
3. Muéstrame el diff de la spec y espera mi aprobación.
