---
name: sdd-workflow
description: "Spec-Driven Development gate for this repo. Read docs/spec/constitucion.md and docs/spec/stack.md before writing any code; work from a feature folder's spec.md then plan.md then tasks.md; ask instead of assuming when certainty is under 80%. Use at the START of any implementation task in backend/ or frontend/, when picking up an unfinished task from tasks.md, or when a request is unclear enough that the design is not yet decided."
---

# Spec-Driven Development

Este proyecto sigue Spec-Driven Development. **`docs/spec/` es la unica fuente de verdad.** El codigo es consecuencia de la spec, nunca al reves.

## Rutas (verificadas en el repo)

| Que leer | Donde esta |
|---|---|
| Constitucion | `docs/spec/constitucion.md` |
| Stack y arquitectura | `docs/spec/stack.md` |
| Roadmap | `docs/spec/roadmap.md` |
| Features | `docs/spec/features/NNN-nombre-feature/` |

> Las rutas son relativas a la raiz de `Fase 2/Evidencias Proyecto/`, que es donde vive `AGENTS.md`.

**No existe** `docs/spec/constitution/tech-stack.md`. Si alguien te lo pide, las fuentes son `constitucion.md` + `stack.md`.

## Reglas

1. **Antes de escribir codigo, lee siempre `docs/spec/constitucion.md` y `docs/spec/stack.md`.** No de memoria. Ya cambiaron y van a cambiar.
2. **No escribas codigo en `backend/` o `frontend/` sin `spec.md` y `plan.md` aprobados** en `docs/spec/features/` (`AGENTS.md` §7). Documentacion y config no cuentan como "codigo" - solo `backend/` y `frontend/`.
3. **Ciclo de ejecucion en orden:** `spec.md` (que + criterios de aceptacion) → `plan.md` (como tecnicamente) → `tasks.md` (checklist) → codigo verificado con pruebas.
4. **Si una tarea de `tasks.md` esta incompleta, no asumas la solucion - pregunta.** Si la certeza de una decision es menor al 80%, preguntar es el comportamiento correcto, no una falla (`AGENTS.md` §8.4).
5. **Cuando generes el codigo, actualiza las casillas `[ ]` a `[x]`** en el `tasks.md` correspondiente, en el momento. No al final de la sesion, no "despues".
6. **No alteres el modelo de datos de 12 entidades (3NF)** sin justificacion aprobada en `docs/spec/stack.md`.
7. **No implementes Clerk** ni cambies el esquema de autenticacion. Sigue siendo JWT local HS256 decorativo.
8. **No agregues paquetes** a `requirements.txt` ni `package.json` sin analisis previo.
9. **No subas secretos ni `.env`.**

## Orden de lectura por tarea

```
1. docs/spec/constitucion.md        <- siempre
2. docs/spec/stack.md               <- siempre
3. docs/spec/features/<tu-feature>/tasks.md   <- la tarea que vas a ejecutar
4. El codigo que vas a tocar
5. Recien ahi: escribir
```

Si `docs/spec/features/` esta vacio y te piden una funcionalidad nueva, **el paso 3 es crear el feature folder** - `spec.md`, `plan.md`, `tasks.md` - y eso va antes que el codigo. No saltes directo a implementar.

## Prohibiciones que se aplican siempre

- SQL raw. Solo SQLAlchemy ORM o Core.
- Logica de negocio en los routers (`backend/app/api/v1/endpoints/`). Va en `backend/app/services/`.
- `@NgModule` en Angular. Todo standalone.
- Secretos, credenciales o `.env` en git.

## Skills a cargar segun la tarea

Esta skill decide **si** se puede escribir codigo. Las otras deciden **como**:

| Si la tarea toca... | Carga |
|---|---|
| `backend/**/*.py` | `fastapi-pydantic-v2` |
| `frontend/src/**` | `angular-standalone` |
| Componente o vista **nueva** | `angular-standalone` + `frontend-design` |
| Cualquier test nuevo | `tdd` - test primero, por la interfaz publica |
| Revision de UI existente | `web-design-guidelines` |
| `backend/app/models/**` o `database/*.sql` | detour: es cambio de modelo, necesita justificacion en `stack.md` primero |

## Cuando terminar una tarea

1. Marca `[ ]` → `[x]` en `tasks.md`.
2. Corre las pruebas: `cd backend && pytest` y `cd frontend && npx ng test --watch=false --browsers=ChromeHeadless` (el `npm test` a secas se cuelga en modo watch; ver `AGENTS.md` §5 para el `CHROME_BIN`).
3. Si la tarea resulto en una decision arquitectonica (un patron nuevo, un servicio nuevo, una excepcion a una regla), actualiza `stack.md` para que el proximo incremento no tenga que redescubrirlo.

## Cuando cerrar una feature

Los tests en verde **no** cierran una feature. Hace falta ademas el recorrido en los dos puertos del frontend, porque fallan cosas que ninguna suite detecta (`AGENTS.md` §8.5 y §8.6):

1. **4200** (`cd frontend && npm start`): recorrido funcional, incluida la escritura real contra la BD. Es la evidencia principal.
2. **8080**: exige reconstruir antes, o el recorrido comprueba una vista vieja y no dice nada:
   ```
   docker compose -f docker-compose.yml build frontend
   docker compose -f docker-compose.yml up -d frontend
   ```
   Recorrido de humo: la vista nueva esta y el flujo basico responde. Ahi se ejecutan el build de produccion con sus presupuestos, el `try_files` de nginx para rutas Angular y el cacheo de bundles con hash.

Ojo con la asimetria: **el backend se actualiza solo** (el contenedor monta `./backend/app` y corre `uvicorn --reload`), el frontend no. Una feature que solo toca Python no necesita reconstruir la imagen para probar su API, aunque 8080 siga mostrando el frontend viejo.
