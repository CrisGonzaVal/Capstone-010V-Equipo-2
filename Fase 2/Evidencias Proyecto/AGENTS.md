# AGENTS.md — Compustock ERP

## 0. Alcance de Trabajo (regla de mayor prioridad)

**Este directorio es el único territorio de trabajo.**

- Toda lectura, escritura, edición, búsqueda, análisis o ejecución ocurre dentro de `Fase 2/Evidencias Proyecto/` (la carpeta donde vive este archivo). Nada fuera.
- **Única excepción: los comandos de git.** `git status`, `git diff`, `git log`, `git show`, `git add`, `git commit` pueden ejecutarse sobre el repositorio completo, porque la raíz del repo está por encima. Aun así, al reportar resultados de git, **enfócate solo en los cambios de este proyecto** e ignora lo que ocurra en otras fases.
- **No leas, listes ni explores las fases anteriores o posteriores.** `../../Fase 1/`, `../../Fase 3/` y cualquier otra carpeta hermana están **fu de alcance**. No abras archivos `.docx`, `.pdf`, diagramas, prototipos ni prototipos UI/UX de otras fases, aunque aparezcan listados en `git status`.
- Si una tarea parece requerir un archivo fuera de este directorio, **pide permiso antes**. No lo asumas.
- Solo sales de aquí si el usuario lo dice explícitamente ("revisa la Fase 1", "mira el prototype de UX", etc.).

> El repositorio git que contiene este proyecto también incluye `Fase 1/` y `Fase 3/`. Eso es un hecho del repo, no una invitación a leerlas.

## 1. Misión y Propósito
Compustock ERP es un sistema web para la administración centralizada, trazabilidad y abastecimiento de insumos de ofimática, orientado a resolver el desabastecimiento en sedes descentralizadas mediante un flujo guiado de tickets y control de inventario físico.

## 2. Actores del Sistema
- **Superadmin**: Administrador global del SaaS; aprovisiona instituciones/sedes y audita métricas del sistema.
- **Administrador Institucional**: Gestiona usuarios, departamentos y el catálogo maestro de categorías e insumos.
- **Bodeguero / Encargado de Suministros**: Gestiona stock físico, supervisa el tablero Kanban y despacha pedidos aprobados rebajando el inventario.
- **Solicitante (Funcionario)**: Consulta disponibilidad de insumos en tiempo real y emite tickets de requerimiento justificados para su departamento.

## 3. Stack Tecnológico (estado actual)
- **Frontend**: Angular 18.2+ (Standalone Components, Signals, TypeScript 5.5, Tailwind CSS 3.4).
- **Backend**: FastAPI + Uvicorn (Python 3.10+, Pydantic v2, SQLAlchemy 2.0 con psycopg2 — síncrono, pydantic-settings).
- **Base de Datos**: PostgreSQL 16 (Docker Compose: puerto local 5433, contenedor expone 5432; base por defecto `apt_erp`).
- **Autenticación**: decorativa por ahora — JWT local HS256 con `SECRET_KEY` (config en `backend/app/core/config.py`). Clerk NO está implementado aún; se evalúa en Release 2.0.
- **Entorno local**: Docker Compose levanta `db`, `backend` (puerto 8000) y `frontend` (puerto 8080).

## 4. Estructura del Espacio de Trabajo
Las rutas son relativas a la raíz de `Fase 2/Evidencias Proyecto/` (donde vive este archivo). Arquitectura definida en `docs/spec/stack.md`:
- `docs/spec/` — Documentación viva de Spec-Driven Development (única fuente de verdad): `constitucion.md`, `roadmap.md`, `stack.md`.
- `docs/spec/features/` — Especificaciones por incremento (`spec.md`, `plan.md`, `tasks.md`).
- `backend/` — API REST FastAPI: `app/main.py`, `app/core/` (`config.py`, `security.py`), `app/db/database.py`, `app/models/` (por entidad), `app/schemas/` (DTOs), `app/services/` (lógica ACID), `app/api/dependencies.py`, `app/api/v1/api.py`, `app/api/v1/endpoints/` (auth, usuarios, inventario, tickets) y `tests/` (pytest).
- `frontend/` — Aplicación web Angular: `src/app/core/` (guards, interceptors, services), `src/app/shared/` (components, interfaces, pipes), `src/app/features/` (dashboard, inventario, tickets — cada una con `routes.ts` y `services/`) y `src/assets/`.
- `database/` — Scripts SQL. El prefijo numérico **es funcional**, no decorativo: `docker-compose.yml` monta esta carpeta en `/docker-entrypoint-initdb.d` y PostgreSQL los ejecuta **en orden alfabético** al crear el volumen. `01_esquema.sql` (DDL) debe correr antes que `02_datos_semilla.sql` (TRUNCATE + INSERT), o la semilla trunca tablas inexistentes y el arranque aborta con `ON_ERROR_STOP=1`. No cambies un nombre sin revisar el orden.
- `.agents/skills/` — Skills del proyecto (ver §9). `opencode.json` y `skills-lock.json` configuran tooling.

> **Fuera de alcance**: `../../Fase 1/` y `../../Fase 3/` existen en el mismo repositorio pero **no se leen** (ver §0). No son fuente de verdad para este trabajo.

> **Nota de migración**: el código actual está en fase de migración a esta estructura, que es la normativa desde hoy.

## 5. Comandos de Operación
- Levantar infraestructura local: `docker compose -f docker-compose.yml up -d`
- Backend dev server: `cd backend && uvicorn app.main:app --reload --port 8000`
- Frontend dev server: `cd frontend && npm start` (puerto 4200)
- Backend tests (suite activa desde la Feature 001, Fase C):
  ```
  cd backend
  python -m venv .venv && .venv\Scripts\activate
  pip install -r requirements.txt -r requirements-dev.txt
  pytest
  ```
  La suite corre sobre SQLite en memoria, asi que no necesita el contenedor `db`.
  Ojo: `backend/.dockerignore` excluye `tests/` y `requirements-dev.txt`, asi que
  los tests **no** viven dentro de la imagen; hay que correrlos desde el host.
- Frontend tests (configurado):
  ```
  cd frontend
  npx ng test --watch=false --browsers=ChromeHeadless
  ```
  **No usar `npm test` a secas**: Karma arranca en modo watch y el comando se queda
  esperando. Además esta máquina no tiene Chrome, solo Edge, así que hay que
  apuntar el launcher antes:
  ```
  $env:CHROME_BIN = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
  ```
- Frontend lint (meta — no configurado aún): `cd frontend && ng lint`

## 6. Convenciones de Código
- **Idioma — identificadores en español (aplica a backend y frontend):**
  - Variables, parámetros, funciones, métodos, clases, campos de interfaces y type aliases se escriben **en español**.
  - **No se renombran**: nombres de archivo y carpetas (los de `docs/spec/stack.md`), tablas y columnas de BD (§7), ni APIs de terceros (`BaseModel`, `ConfigDict`, `BaseSettings`, `Column`, `relationship`, `FastAPI`, `APIRouter`, `Depends`, `HTTPException`, `signal`, `computed`, `inject`, `input`, `output`, `CanActivateFn`, `HttpInterceptorFn`, `loadComponent`, `loadChildren`).
  - **Excepción Angular**: los sufijos estructurales (`Component`, `Service`, `Guard`, `Interceptor`, `Pipe`, `Routes`) se conservan porque son vocabulario del framework. Se españoliza el dominio: `auth.service.ts` exporta `AutenticacionService`, no `AuthService`.
  - Origen: Feature 001 (`docs/spec/features/001-reestructuracion-modular/spec.md` §4).
- **Backend**:
  - Nombres de funciones y variables en `snake_case`.
  - Toda ruta REST debe declarar `response_model`, `status_code` explícito y documentación OpenAPI.
  - La lógica de negocio reside en `app/services/`, nunca directamente en los controladores de ruta (`app/api/v1/endpoints/`).
  - **Solo sintaxis Pydantic v2**: prohibido `class Config:` — usar `model_config = ConfigDict(...)` (o `SettingsConfigDict` en `BaseSettings`). Usar `model_validate()` en lugar de `from_orm()`.
  - La `Session` se inyecta con `Depends(get_db)`; nunca se instancia a mano en un endpoint.
  - No escribir SQL raw: utilizar consultas tipadas mediante SQLAlchemy ORM o Core.
- **Frontend**:
  - Componentes, servicios e interfaces en `kebab-case.ts`.
  - Sin uso de `NgModule`: arquitectura 100% Standalone con `inject()` para inyección de dependencias.
  - Gestión de estado reactivo mediante `computed()` y `signal()`.
  - Nada de CSS quemado en templates ni `styles: []` en componentes: solo clases de Tailwind.
- **Base de Datos**:
  - Tablas y columnas en minúsculas en plural o singular consistente (`snake_case`).
  - Claves primarias obligatorias `SERIAL PRIMARY KEY` o `IDENTITY`.

## 7. Prohibiciones Estrictas ("No hagas")
- No escribas código en `backend/` o `frontend/` sin una especificación (`spec.md`) y plan (`plan.md`) aprobados en `docs/spec/features/`.
- No alteres el modelo de datos de 12 entidades (3NF) sin justificación aprobada en `docs/spec/stack.md`.
- No implementes Clerk ni cambies el esquema de autenticación hasta que el sistema de gestión esté operativo: la autenticación se mantiene decorativa (JWT local HS256).
- No instales paquetes en `package.json` o `requirements.txt` sin previo análisis de dependencias.
- No subas secretos, credenciales ni archivos `.env` al repositorio.
- **No leas ni modifiques nada fuera de `Fase 2/Evidencias Proyecto/`** — incluidas las fases hermanas. Los comandos de git son la única excepción (ver §0).

## 8. Flujo de Trabajo (Spec-Driven Development)
1. Leer `docs/spec/constitucion.md`, `docs/spec/roadmap.md` y `docs/spec/stack.md` antes de cada tarea.
2. Cada funcionalidad debe poseer su carpeta `docs/spec/features/NNN-nombre-feature/`.
3. Ciclo de ejecución: `spec.md` (Qué y Criterios) → `plan.md` (Cómo técnico) → `tasks.md` (Checklist de tareas) → Código verificado contra pruebas.
4. Si la certeza de una decisión es inferior al 80%, solicitar clarificación en lugar de asumir.
5. **Cierre de feature = verificación, no marcado.** Marcar `[x]` en `roadmap.md` solo después de: (a) `tasks.md` con todas sus casillas marcadas, incluidos los checks de "Cierre"; (b) `spec.md` §5 con cada AC marcado y **su evidencia de verificación**; (c) tests en verde.
6. **Mover o borrar un archivo no actualiza los `.md` que lo citan.** Al cerrar una feature, hacer un `grep` de coherencia sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/` para confirmar que ninguna ruta citada ni afirmación sobre el estado del proyecto quedó obsoleta. Una skill desactualizada es peor que un `.md` desactualizado: se carga sola e instruye al agente sobre código que ya no existe.

## 9. Skills del Proyecto
Las convenciones de §6 y el flujo de §8 están codificados como skills en `.agents/skills/`, con ejemplos de código antes/después. Cargar la que corresponda **antes** de escribir:

| Skill | Se activa cuando... |
|---|---|
| `sdd-workflow` | al iniciar cualquier implementación, o al retomar una tarea de `tasks.md` |
| `angular-standalone` | al crear, editar o revisar cualquier archivo bajo `frontend/src/` |
| `fastapi-pydantic-v2` | al crear, editar o revisar cualquier `.py` bajo `backend/` |
| `tdd` | al escribir cualquier test nuevo |
| `frontend-design` | al crear un componente o vista **nueva** (dirección visual) |
| `web-design-guidelines` | al auditar UI existente (accesibilidad, responsive) |

## 10. Memoria
- Al empezar, lee `MEMORY.md` para conocer el estado del proyecto y las decisiones tomadas.
- Al terminar una tarea, actualízalo: estado actual, decisiones importantes (con su porqué) y errores a evitar.
- Mantenlo breve (máximo ~50 líneas): resume o elimina lo que ya no aporte.
- Si algo se convierte en una regla permanente, propón moverlo a `AGENTS.md` en lugar de dejarlo en la memoria.
- No guardes nunca datos sensibles (claves, tokens, datos personales).

`MEMORY.md` es estado_y_decisiones, **no** norma. Si algo entra en `MEMORY.md` y ya no
depende de la feature en curso, su lugar es `AGENTS.md` (§6, §7) o `docs/spec/stack.md`.

## 11. Límites
✅ Siempre:
- Actualizar `MEMORY.md` al terminar cada tarea (§10).
- Leer `MEMORY.md` al empezar, antes de planificar.
- Mantener los tests en verde: `pytest` en `backend/` y `ng test` en `frontend/`.
- Verificar el contrato con `/openapi.json` tras tocar endpoints (AC-2).