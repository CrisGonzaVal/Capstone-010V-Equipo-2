# Feature 006 — Plan Técnico

Spec: [`spec.md`](spec.md), aprobada. Este plan extiende el incremento ya implementado con la identidad local completa y su presentación en el layout; no modifica las doce entidades, la tabla `usuario` ni el DDL.

## 1. Flujo técnico

### Backend: resolver y devolver identidad local

La dependencia de autenticación continúa validando el JWT, consultando Clerk y vinculando el correo primario verificado con el usuario local existente. Mantener el resultado de esa resolución como usuario local más `sub` validado, sin persistir este último. El endpoint `GET /api/v1/auth/me` delega el enriquecimiento a la capa de `app/services/`: el servicio proyecta `usuario_id`, `nombre`, `apellido`, `correo` y el nombre de rol. El router solo recibe la identidad autenticada y la sesión inyectada, llama al servicio y devuelve el DTO.

Resolver el rol con SQLAlchemy ORM usando la relación `Usuario.rol` del usuario ya vinculado (carga explícita apropiada, por ejemplo `select(Usuario).options(joinedload(Usuario.rol))`), no SQL raw ni consultas interpoladas. El DTO Pydantic v2 declara los seis campos (`usuario_id`, `sub`, `nombre`, `apellido`, `correo`, `rol`) y no declara `rol_id`; se construye desde el resultado del servicio o valida con `model_validate()` si se devuelve una estructura compatible. Mantener `response_model`, `status_code=200` y el contrato 401 existente. Resolver inconsistencia de usuario/relación/rol como fallo de identidad no disponible conforme al comportamiento de autenticación establecido, sin exponer causas internas ni modificar filas.

### Frontend: cargar identidad una vez por sesión y mostrarla

`AutenticacionService` será el único dueño de la identidad frontend y expondrá señales para identidad y estado de carga/error. Durante su inicialización idempotente de Clerk, cuando exista sesión autenticada, realizará una única petición autenticada a `/api/v1/auth/me` y publicará la respuesta. No repetirá la petición en cada navegación: el layout y los consumidores leen la misma señal. Al no haber sesión o al cerrar sesión, limpiará la identidad de inmediato; también limpiará cualquier identidad anterior antes de iniciar una carga de nueva sesión. En error (incluido 401), conserva sesión Clerk según su propio estado, pero limpia identidad y expone estado no disponible; no fabrica atributos usando el perfil de Clerk.

El layout obtiene una vista derivada con `computed()`: nombre completo y correo en el panel lateral, `rol` en el header e inicial normalizada a mayúscula desde el nombre local para el avatar. Mientras se solicita `/auth/me`, el layout muestra un marcador de carga neutro; ante error o falta de identidad muestra el marcador neutro de no disponibilidad. El shell no muestra nombre, correo, rol ni avatar de usuario anteriores/ficticios en esos estados. Esto es solo presentación, no agrega autorización por rol ni altera guards, navegación o permisos.

### Pruebas y cierre

En backend, ampliar pruebas HTTP existentes de `/auth/me` para respuesta completa, rol legible y ausencia de `rol_id`; cubrir relación ausente/no resoluble según el contrato 401 y verificar OpenAPI. En frontend, probar el ciclo de carga, publicación, no repetición por navegación, logout/limpieza, error/401 y representación del layout sin datos ficticios, mediante el doble Clerk y HttpTestingController/mocks apropiados. Mantener TDD y ambas suites completas.

El recorrido manual de 4200 se amplía para verificar identidad visible real, rol y logout/limpieza. El humo 8080 se hace después de reconstruir y recrear el frontend y verifica los mismos elementos básicos y estado neutro. Se amplían los checks de cierre ya existentes: no crear una segunda tarea de recorrido ni duplicar el cierre documental.

## 2. Archivos que se crean o modifican

| Archivo | Responsabilidad | AC |
|---|---|---|
| `backend/app/schemas/auth_schema.py` | Ampliar `IdentidadAutenticadaRespuesta` con nombre, apellido, correo local y `rol`; excluir `rol_id`. | AC-8, AC-11, AC-13 |
| `backend/app/services/auth_service.py` | Enriquecer la identidad autenticada con los campos locales y el nombre de rol mediante ORM y la relación Usuario–Rol. | AC-8, AC-9, AC-12, AC-13 |
| `backend/app/api/v1/endpoints/auth.py` | Delegar `/auth/me` al servicio manteniendo router delgado, respuesta/código explícitos y 401 documentado. | AC-8, AC-9, AC-11 |
| `backend/tests/api/test_auth.py` | Probar el DTO completo, datos de usuario/rol, no exposición de `rol_id`, errores de resolución, OpenAPI y autenticación existente. | AC-8, AC-9, AC-11, AC-13 |
| `frontend/src/app/core/services/auth.service.ts` | Cargar identidad una vez por inicialización/sesión, exponer estado con signals, limpiar ante logout/nueva sesión/error y no usar datos del perfil Clerk como sustituto. | AC-1, AC-8, AC-9, AC-13, AC-16 |
| `frontend/src/app/core/services/auth.service.spec.ts` | Tests de petición única, señal de identidad, estados de carga/error y limpieza en cambio/logout de sesión. | AC-13, AC-16 |
| `frontend/src/app/app.component.ts` | Derivar los campos de presentación desde el estado del servicio con `computed()`; sin lógica de autorización. | AC-16 |
| `frontend/src/app/app.component.html` | Reemplazar identidad quemada por identidad resuelta y marcadores neutros de carga/no disponibilidad; mostrar nombre, correo, rol e inicial según spec. | AC-16 |
| `frontend/src/app/app.component.spec.ts` | Comprobar presentación de identidad real, avatar, estados neutros y ausencia de datos ficticios/supuestos. | AC-13, AC-16 |
| `frontend/src/testing/clerk-falso.ts` | Ampliar solo si hace falta simular transiciones de sesión para pruebas deterministas; no alterar su contrato público sin prueba asociada. | AC-13, AC-16 |
| `docs/spec/features/006-autenticacion-clerk/tasks.md` | Continuar desde T14, asociar tareas nuevas y ampliar trazabilidad/cierre existentes. | AC-13…AC-16 |
| `docs/spec/features/006-autenticacion-clerk/spec.md` | Al cierre, registrar evidencia por AC-16 y los AC ampliados sin cambiar requisitos. | AC-13…AC-16 |
| `docs/spec/stack.md`, `docs/spec/roadmap.md`, `MEMORY.md` | Solo en el cierre ya previsto: documentar estado/evidencia y marcar roadmap únicamente tras verificar todos los AC y ambos puertos. | AC-15 |

No se modifica el modelo, DDL, semilla ni la estructura de identidad Clerk existente. Las rutas operativas siguen protegidas por la dependencia agregada y la visualización no convierte el rol en política de autorización.

## 3. Decisiones técnicas y alternativas

### 3.1 Servicio Angular centraliza carga de identidad

La llamada a `/auth/me` pertenece a `AutenticacionService`, junto con la sesión Clerk. La inicialización idempotente solicita la identidad una vez al establecer/recuperar la sesión; el estado queda disponible como `signal` para el layout y otros consumidores. Las actualizaciones posteriores de sesión deben evitar reutilizar identidad de un usuario anterior: al detectar una sesión distinta, borrar primero el estado y resolver de nuevo. Las navegaciones no disparan llamadas; solo inicialización/cambio efectivo de sesión.

**Alternativa descartada:** llamar al endpoint desde el layout cada vez que se crea o navega el componente, porque duplica tráfico y dispersa el dueño del ciclo de identidad. Tampoco se usa perfil Clerk como fuente alternativa: el contrato exige campos locales vinculados.

### 3.2 Estado de identidad separado del estado de sesión

Mantener explícitos los estados de identidad (`cargando`, `disponible`, `no disponible`) y la identidad nullable, derivados/publicados por señales; el estado de sesión Clerk sigue siendo fuente separada. Inicio de carga borra el valor anterior; logout/no-session borra valor y cancela o invalida respuestas pendientes para evitar que una respuesta tardía repueble una sesión cerrada. Un fallo de `/auth/me` da identidad nula y estado neutro de error; no inventa nombre, correo, rol ni inicial.

**Alternativa descartada:** rellenar con valores constantes o claims/perfil de Clerk, que se confundirían con la identidad local real; también se descarta usar solo `estaAutenticado` para inferir identidad, pues una sesión Clerk puede existir aunque el vínculo local devuelva 401.

### 3.3 Servicio backend para enriquecer DTO y consulta ORM

La consulta de identidad local y rol reside en `app/services/`, nunca en el endpoint. Recibe el usuario vinculado y la `Session` inyectada; lee usuario y `rol.nombre_rol` mediante relación ORM. Puede cargar la relación en la consulta con `joinedload` (o estrategia ORM equivalente compatible con el modelo existente), evitando una consulta N+1. Construye una estructura de salida explícita con `rol` como texto; no incluye `rol_id`. Se conserva `IdentidadAutenticadaRespuesta` como contrato y Pydantic v2.

**Alternativa descartada:** SQL raw, consulta de rol en el router o exponer la relación completa/`rol_id`. Lo primero infringe convenciones; lo segundo mezcla transporte y negocio; lo tercero amplía el contrato innecesariamente y la spec lo excluye.

### 3.4 TDD y verificación sin dependencias nuevas

Usar pytest con las fixtures SQLite en memoria actuales, poblando vínculo usuario/rol para pruebas de `/auth/me`, y Angular `ng test` con la infraestructura existente de HttpClient/mocks. No agregar paquetes: el alcance se cubre con FastAPI, SQLAlchemy, Pydantic, Angular y harness ya instalados. Ejecutar ambas suites completas tras integrar cada lado.

**Alternativa descartada:** añadir un cliente HTTP o biblioteca de estado para la identidad, innecesarios para una llamada y señales existentes; no se justifica dependencia nueva.

### 3.5 Recorridos integrados en cierre existente

Ampliar el recorrido T12 ya pendiente en 4200 y 8080 para identidad, sin duplicar tareas de cierre. 4200 cubre autenticación real contra Clerk y perfil local; 8080 requiere build y recreación previa del frontend y comprueba de humo los mismos elementos visibles. T13 mantiene el cierre documental/evidencia AC.

**Alternativa descartada:** crear recorridos duplicados o marcar la feature cerrada por suites automatizadas; contradice el procedimiento de cierre del proyecto.

## 4. Estrategia de pruebas y cobertura

- Backend, TDD: extender `backend/tests/api/test_auth.py` antes de implementación. Cubrir 200 con los seis campos y valores locales correctos; `rol` igual a `rol.nombre_rol`; ausencia de `rol_id`; fallo de identidad/relación sin exposición de causa; conservar 401 de Clerk y ausencia de vínculo; comprobar `/openapi.json` con contrato completo, `response_model`, 200 y 401. Correr `cd backend && .venv\\Scripts\\python.exe -m pytest`; objetivo de regresión: los 192 tests previos siguen verdes.
- Frontend, TDD: ampliar tests del servicio y layout antes de implementar. Cubrir identidad presente, petición única/no repetición por navegación, limpieza al logout y cambio de sesión, respuesta tardía tras logout, carga neutra, error/401 neutro, nombre completo/correo/rol/inicial, ausencia de textos ficticios y no inferencia de permisos. Usar `npx ng test --watch=false --browsers=ChromeHeadless` con `CHROME_BIN` configurado a Edge según AGENTS.md; los 100 tests actuales deben permanecer verdes.
- Build: ejecutar build de producción frontend para confirmar que el estado reactivo/layout no introduce regresiones.
- Cierre manual: ampliar T12 (no duplicar) con el usuario local real y rol mostrado en 4200, logout/estado sin sesión, y el humo equivalente en 8080 después de `docker compose -f docker-compose.yml build frontend` y recreación del servicio. No usar valores de secreto en evidencia.
- Cierre documental: ampliar T13 y la tabla AC→tasks; registrar evidencia de AC-16 solo tras verificaciones; actualizar `stack.md`, `MEMORY.md` y roadmap conforme al procedimiento existente.

## 5. Cobertura AC → pieza

| AC | Pieza principal |
|---|---|
| AC-1…AC-7 | Integración de sesión Clerk, validación/vínculo y recorrido real ya implementados; regresión en T12/T14–T15. |
| AC-8 | DTO extendido, servicio de identidad local/rol, endpoint delgado y prueba HTTP completa. |
| AC-9 | Servicio y pruebas de error mantienen 401/no modificación; frontend elimina identidad al fallar. |
| AC-10 | Router agregado protegido, regresión de suite existente. |
| AC-11 | OpenAPI del endpoint con DTO completo, respuesta/códigos explícitos y seguridad. |
| AC-12 | Revisión de diff confirma modelo/DDL intactos; consulta ORM y `rol` sin `rol_id`. |
| AC-13 | Suites TDD backend/frontend completas, incluyendo identidad y estados neutros. |
| AC-14 | Recorrido integrado de T12 ampliado con sesión/perfil y verificación 4200/8080. |
| AC-15 | T13 conserva evidencia por AC, actualizaciones documentales y cierre condicionado. |
| AC-16 | `AutenticacionService`, layout, tests del servicio/componente y recorridos T12 ampliados. |

## 6. Riesgos y mitigaciones

- **Identidad vieja tras logout o cambio de cuenta:** limpiar antes de resolver nueva sesión e invalidar respuestas pendientes; comprobarlo con tests deterministas.
- **Sesión Clerk sin vínculo local:** separar estado de sesión de disponibilidad de identidad; error/401 deja la sesión al SDK, pero presenta estado neutro y no identidad derivada del perfil Clerk.
- **Rol no cargado o relación no resoluble:** definirlo como fallo de identidad del endpoint, no mostrar rol vacío/supuesto; el test debe confirmar error controlado y ausencia de mutaciones.
- **Regresión de DTO/OpenAPI:** probar schema de respuesta y ausencia de `rol_id`, además del estado/código y seguridad existentes.
- **Lectura ORM adicional o SQL incorrecto:** seleccionar usuario vinculado y cargar relación con SQLAlchemy ORM; no usar SQL raw ni modificar modelos/DDL.
- **T12 ya ejecutado parcialmente o tests previos con autenticación real:** agregar los casos de identidad a la evidencia/tareas pendientes sin renumerar T1–T13 ni repetir innecesariamente la prueba de identidad Clerk.
- **Build 8080 congelado:** reconstruir y recrear frontend antes del smoke test; la vista previa no acredita el build nuevo.
