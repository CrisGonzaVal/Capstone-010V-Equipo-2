---
description: "SDD · Entrevista y genera la spec de una feature nueva (uso: /sdd-spec 004-nombre idea inicial)"
agent: planner
---

NO escribas código en ningún momento. Lee `docs/spec/constitucion.md`, `docs/spec/stack.md`, `docs/spec/roadmap.md` y `MEMORY.md`, y usa la skill `sdd-workflow`.

Carpeta de la spec: `docs/spec/features/$1/`
Idea inicial (el texto que va después del nombre de la carpeta): $ARGUMENTS

Tu trabajo:

1. Hazme preguntas de UNA en UNA para eliminar ambigüedades (casos límite, errores, qué queda fuera de esta versión). Máximo 5 preguntas.
2. Con mis respuestas, genera `docs/spec/features/$1/spec.md` con la estructura de las specs existentes (Problema, Objetivo, Alcance Dentro/Fuera, Decisiones D-n, Contrato de la API o Reglas del flujo si aplica, Criterios de aceptación numerados AC-n, Restricciones) y `**Estado:** borrador`.
3. Solo el QUÉ y el POR QUÉ: nada de stack, arquitectura ni nombres de archivos. Las dudas que no resuelvas en la entrevista, márcalas con `[NECESITA ACLARACIÓN]`.

Si $1 no sigue el patrón NNN-nombre o choca con una feature existente del roadmap, dilo antes de escribir.
