---
description: SDD · Valida la spec AC por AC (tests + chrome-devtools + recorrido manual)
agent: build
---

Recorre `docs/spec/features/$1/spec.md` requisito por requisito. Para cada AC indica qué test lo cubre y el resultado de ejecutarlo (`pytest` en backend, `ng test` en frontend).

Los AC de interfaz que las suites no cubren, verifícalos con el MCP chrome-devtools (consola sin errores y vista móvil de 375 px); si el MCP no está disponible, márcalos como verificación manual pendiente en 4200 y 8080 (AGENTS.md §8.5-§8.6).

Si algún AC no está cubierto o falla, dilo claramente. NO arregles nada todavía. Después comprueba los criterios de finalización y dame un veredicto en la primera línea:

- `VEREDICTO: APROBADO`
- `VEREDICTO: CAMBIOS NECESARIOS`
