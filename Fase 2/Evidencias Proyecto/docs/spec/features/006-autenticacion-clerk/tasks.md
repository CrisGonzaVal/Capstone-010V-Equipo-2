# Feature 006 — Tasks

**Spec:** [`spec.md`](spec.md) · **Plan:** [`plan.md`](plan.md)

17 tareas en orden de dependencia; las tareas T1–T13 reflejan trabajo previo ya realizado y
T14–T16 amplían la identidad local y su presentación. T17 registra un cambio visual posterior
al cierre, pendiente de implementación. Cada tarea debe poder ejecutarse como
una unidad por el `@implementer`. Las tareas de comportamiento siguen TDD: primero test
observable, luego implementación. No marcar una tarea sin cumplir `Hecho cuando:` y dejar
evidencia concreta.

Leyenda: `[ ]` pendiente · `[x]` hecha y verificada · `[!]` bloqueada (motivo en la línea).

Verificación habitual:
- Backend: `cd backend && .venv\\Scripts\\python.exe -m pytest`
- Frontend: `$env:CHROME_BIN = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"; cd frontend && npx ng test --watch=false --browsers=ChromeHeadless`

---

## T1 — Confirmar e incorporar dependencias y configuración (AC-4…AC-6, AC-12, AC-14)

- [x] Revisar compatibilidad y fijar `@clerk/clerk-js` 6.x, `PyJWT[crypto]` y `httpx` en
  manifests/lockfiles con versiones exactas confirmadas al instalar. No usar
  `clerk-backend-api` porque no valida issuer/JWKS requeridos. Añadir settings Pydantic v2
  Clerk; retirar settings HS256 tras grep de uso; actualizar `backend/.env.example` sin
  valores reales y mapear variables Clerk desde `.env` raíz al backend por Compose. No
  existe `.env.example` raíz. Crear un único `environment.ts` versionable con
  `CLERK_PUBLISHABLE_KEY`; no añadir `fileReplacements`.

**Hecho cuando:** versiones exactas aparecen en manifests/lockfiles y son compatibles con
Angular 18.2/TS 5.5 y Python 3.10; `Settings` carga variables Clerk y no settings HS256;
Compose las pasa sin secretos hardcodeados; build compila con el único environment. El grep
previo encontró nombres HS256 solo en `config.py`, `backend/.env.example` y
`docker-compose.yml`; retirarlos de esos sitios tras confirmar que no hay otros usos.

**Evidencia T1 (hecha):** versiones exactas fijadas — `@clerk/clerk-js` **6.39.0** (npm,
`frontend/package.json` + `package-lock.json`), `PyJWT[crypto]` **2.15.1** y `httpx`
**0.28.1** (pip, `backend/requirements.txt`; transitivas `cryptography` 50.0.2, `cffi`,
`pycparser`), compatibles con Angular 18.2/TS 5.5 y Python 3.11 (≥3.10). `Settings`
carga `CLERK_PUBLISHABLE_KEY`/`CLERK_SECRET_KEY`/`CLERK_ISSUER` y ya no expone
`SECRET_KEY`/`ALGORITHM`/`ACCESS_TOKEN_EXPIRE_MINUTES` (verificado por import). Retiradas
las tres HS256 de `config.py`, `backend/.env.example` y `docker-compose.yml`, y de los
`.env` locales (gitignoreados) para no romper `BaseSettings(extra="forbid")`. Compose mapea
las tres Clerk con `${VAR:-}` sin secretos. Creado único `frontend/src/environments/environment.ts`
(publishable key pública; sin `fileReplacements`) que compila con `tsc` y no rompe
`npx ng build` (31 s). Comandos: `pip install "PyJWT[crypto]" httpx`;
`npm install @clerk/clerk-js@6.39.0`; `.venv\Scripts\python.exe -m pytest -q` → **140 passed**;
`npx tsc --noEmit … environment.ts` OK; `npx ng build` OK.

## T2 — Tests rojos para autenticación backend y vínculo (AC-5…AC-9, AC-11, AC-13)

- [x] Crear `backend/tests/api/test_auth.py` con fixture de par de claves, JWKS simulado y
  Backend API Clerk mockeado. Inyectar/overridear fuente JWKS y transporte Backend API.
  Escribir primero pruebas de aceptación JWT, firma/JWKS, `iss`, vigencia `exp`/`nbf`,
  allowlist de algoritmo, `azp` permitido para 4200/8080 (ausente/no permitido rechazado),
  sin requisito `aud`, `kid`/rotación/cache TTL, consulta de correo primario y verificación,
  vínculo local,
  correo ausente/no verificado/no coincidente, fallos Clerk como 401, `/auth/me`, esquema
  OpenAPI y protección de endpoints de negocio con/sin bearer.

**Hecho cuando:** las nuevas pruebas fallan por funcionalidad/contrato ausente o incorrecto,
no por imports/fixtures; no usan credenciales reales y el JWKS mock verifica una firma con
clave fixture.

**Evidencia T2 (hecha):** creado `backend/tests/api/test_auth.py` (38 casos, seam HTTP
`TestClient`). Par de claves RSA efímero + JWKS simulado generados en el test; auto-chequeo
en la fixture `par_de_claves` firma una sonda con la clave privada y la verifica con el JWK
(`jwt.decode` + `RSAAlgorithm.from_jwk`), de modo que el JWKS mock verifica una firma fixture
sin red ni credenciales. Transporte hacia `api.clerk.com` con `httpx.MockTransport`; JWKS y
transporte se inyectan por `app.dependency_overrides` sobre las costuras
`app.api.dependencies.obtener_fuente_jwks` (callable `fuente(issuer)->dict`) y
`obtener_transporte_clerk` (httpx.BaseTransport), documentadas en la cabecera del test.
Comandos: `cd backend; .venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q` →
**38 failed, 0 passed**; suite completa `.venv\Scripts\python.exe -m pytest -q` →
**140 passed, 38 failed** (los 38 rojos son exclusivamente de `test_auth.py`; la suite
legacy sigue verde). Motivo del rojo: funcionalidad ausente, no imports/colección —
1) `test_costura_inyectable_de_autenticacion_existe` → `pytest.fail` con los nombres de
costura faltantes (T4); 2) `/api/v1/auth/me` devuelve 404, así que los casos de token
(válido/firma/`iss`/`exp`/`nbf`/algoritmo/`azp`/`sin aud`), Clerk (correo primario y
verificación, vínculo, fallos 401) y `/auth/me` fallan al esperar 200/401; 3) `TTL` de
caché JWKS falla con `pytest.fail` por falta de `app.core.security.TTL_JWKS_SEGUNDOS`;
4) las rutas de negocio sin Bearer responden 200 (aún sin protección) y se espera 401;
5) `/openapi.json` no publica `securityScheme` bearer ni la operación `/auth/me`.

## T3 — Integración Clerk de backend y vínculo local (AC-5…AC-9, AC-12)

- [x] Implementar `core/security.py` mediante PyJWT/httpx: validar Bearer, firma, issuer,
  vigencia y `azp` con JWKS desde `{CLERK_ISSUER}/.well-known/jwks.json`; consultar usuario
  con `CLERK_SECRET_KEY`, identificar correo primario y verificar su estado. Resolver por
  SQLAlchemy ORM a `Usuario.correo`,
  exigir correo verificado y normalizar errores externos/locales a 401 sin filtrar causa.
  No persistir `sub`, no crear usuario y no escribir SQL raw. Resolver la capa service/auth
  respetando que no exista emisión HS256 alternativa.

**Hecho cuando:** pasan los tests de T2 para JWT válido y casos de identidad, la respuesta
contiene una identidad vinculada con `usuario_id` y `sub`, y el diff no toca modelos/DDL.

**Evidencia T3 (hecha):** creado `backend/app/core/security.py` (constante
`TTL_JWKS_SEGUNDOS=3600`, allowlist `RS256`, `AZP_PERMITIDOS` 4200/8080, margen de reloj,
cache JWKS por issuer con instantánea `deepcopy` y refresco único ante `kid` desconocido,
validación firma/`iss`/`exp`/`nbf`/`azp` sin exigir `aud`, consulta `GET
https://api.clerk.com/v1/users/{sub}` vía transporte inyectable y extracción de correo
primario verificado) y reescrito `backend/app/services/auth_service.py` como orquestador
`resolver_identidad` + vínculo ORM `vincular_usuario_por_correo` (se retiró el stub
`autenticar`; no queda emisión/aceptación HS256). Comando: `cd backend;
.venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q` → **29 passed, 9 failed** (los
9 rojos son exclusivamente de protección de rutas de negocio/OpenAPI de negocio, T6). Todos
los casos JWT (firma/`iss`/`exp`/`nbf`/algoritmo/`azp`/sin `aud`), JWKS (cache/kid/rotación/
TTL), Clerk/vínculo y `/auth/me` pasan. El diff solo toca `app/`; sin cambios en `models/`
ni `database/`.

## T4 — Dependencias FastAPI Bearer y DTO de identidad (AC-5, AC-8, AC-9, AC-11, AC-13)

- [x] Crear DTO Pydantic v2 `IdentidadAutenticadaRespuesta(usuario_id, sub)`; implementar
  `HTTPBearer(auto_error=False)` y dependencia HTTP bearer que publica security scheme y dependencia `get_current_user`
  que delega en integración/vínculo real. Eliminar stub 501. Añadir pruebas unitarias/HTTP
  de status y shape, incluyendo ausencia de Bearer y overrideable dependency.

**Hecho cuando:** los tests de DTO/dependencias comprueban el DTO mínimo, 401 sin token,
identidad resuelta y que la dependencia puede ser overrideada; no existe respuesta 501.

**Evidencia T4 (hecha):** creado el DTO Pydantic v2
`IdentidadAutenticadaRespuesta(usuario_id: int, sub: str)` en
`backend/app/schemas/auth_schema.py`. En `backend/app/api/dependencies.py` se añadió
`esquema_bearer = HTTPBearer(auto_error=False)`, las costuras overrideables
`obtener_fuente_jwks` (callable `fuente(issuer)->dict`) y `obtener_transporte_clerk`
(`httpx.BaseTransport`), y un `get_current_user` real que delega en
`auth_service.resolver_identidad` y devuelve `IdentidadAutenticada(usuario, sub)`; se
eliminó el stub 501. La credencial ausente se responde con `HTTPException(401)` explícito
(`WWW-Authenticate: Bearer`) y todo `ErrorAutenticacion` se normaliza a 401 sin causa
interna. Comando: `cd backend; .venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q`
→ **29 passed, 9 failed** (T6). `test_costura_inyectable_de_autenticacion_existe`,
`test_auth_me_sin_bearer_responde_401` (401, no 403) y el override de la dependencia en
`cliente_auth` pasan; sin respuesta 501.

## T5 — Endpoint de identidad `/auth/me` (AC-8, AC-9, AC-11, AC-13)

- [x] Crear `GET /api/v1/auth/me` en el router auth; declarar `response_model`, status 200,
  summary/description y errores 401. El endpoint solo consume la dependencia de usuario y
  `sub` validado, construye DTO y no contiene consultas ni lógica de autenticación.

**Hecho cuando:** test HTTP confirma 200 con `usuario_id` y `sub`, 401 para identidad no
válida y `/openapi.json` publica el contrato/documentación; router delgado. La ausencia de
credenciales usa `HTTPBearer(auto_error=False)` y error explícito 401, no el 403 por defecto.

**Evidencia T5 (hecha):** creado `backend/app/api/v1/endpoints/auth.py` con
`router = APIRouter(prefix="/auth")` y `GET /me` (`response_model=IdentidadAutenticadaRespuesta`,
`status_code=200`, `summary`/`description` y `responses={401: ...}`), endpoint delgado que solo
consume `Depends(get_current_user)` y arma el DTO. Registrado en `backend/app/api/v1/api.py`
antes de los routers de negocio (la protección del router agregado es T6 y no se aplicó en
esta corrida). Verificado vía `app.openapi()`: `securitySchemes` publica `HTTPBearer`;
`/api/v1/auth/me` exige el esquema y documenta `200`+`401`; `/health` sin `security`.
Comando: `cd backend; .venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q` →
**29 passed, 9 failed** (T6). Pasan `test_auth_me_devuelve_usuario_id_y_sub`,
`test_auth_me_sin_bearer_responde_401`, `test_auth_me_con_bearer_invalido_responde_401`,
`test_openapi_auth_me_documenta_200_y_401` y `test_openapi_salud_no_requiere_seguridad_y_publica_bearer`.

## T6 — Protección del router agregado y CORS (AC-9…AC-11, AC-13, AC-14)

- [x] Incorporar auth router y aplicar dependencia HTTP Bearer (`HTTPBearer(auto_error=False)`
  y error HTTP 401 explícito) al router
  agregado de negocio v1, conservando salud y documentación sin protección. No editar
  endpoints de tickets/inventario/usuarios para añadir auth. Ajustar CORS para los orígenes
  frontend 4200 y 8080 y permitir `Authorization` conforme al flujo Clerk. Añadir tests
  automatizados que recorran cada ruta de negocio existente sin token (401) y health/docs
  sin token (accesibles).

**Hecho cuando:** tests de protección demuestran el límite de rutas; `git diff` no contiene
cambios de autenticación en endpoints operativos; CORS acepta los orígenes requeridos.

**Evidencia T6 (hecha):** en `backend/app/api/v1/api.py` el router agregado se crea como
`APIRouter(dependencies=[Depends(dependencies.get_current_user)])`; FastAPI 0.142 propaga esas
dependencias a cada router incluido, así que `/auth/me`, `/usuarios/*`, `/inventario/*` y
`/tickets/*` exigen Bearer sin editar sus endpoints (`get_current_user` usa
`esquema_bearer = HTTPBearer(auto_error=False)` y levanta 401 explícito vía `_no_autorizado`).
Salud y documentación (`/health`, `/`, `/docs`, `/redoc`, `/openapi.json`) quedan en `app`,
fuera del router agregado y sin protección. CORS en `backend/app/main.py` restringe
`allow_origins` a `http://localhost:4200` y `http://localhost:8080`, con
`allow_headers=["Authorization", "Content-Type", "Accept"]` y `allow_methods=["*"]`. `git diff`
solo toca `app/api/v1/api.py` y `app/main.py`; el diff de `app/api/v1/endpoints/` está vacío
(no se alteró la lógica de tickets/inventario/usuarios). Comandos: `cd backend;
.venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q` → **38 passed** (incluye los 9
rojos de T6: 7 rutas de negocio sin Bearer→401, con Bearer válido→200 y OpenAPI de negocio
protegido). Suite completa `.venv\Scripts\python.exe -m pytest -q` → **59 passed, 119 failed**;
los 119 rojos son legacy que llaman a `/api/v1/*` sin token y reciben `401 "No autenticado"` —
rojo transitorio previsto; **T7** restaura la suite legacy con el override de la costura de
identidad en `conftest.py` (no se migró en esta corrida, según lo indicado).

## T7 — Migrar suite backend existente con identidad inyectable (AC-10, AC-13)

- [x] En `backend/tests/conftest.py`, instalar override de la costura de identidad para los
  clientes de tests funcionales legacy. Ejecutar toda la suite existente (~140 casos),
  conservar asserts de negocio y ajustar fixtures compartidas solo donde sea necesario.
  Mantener los tests de `test_auth.py` sin override al validar 401/seguridad.

**Hecho cuando:** todos los tests legacy conservan sus resultados funcionales con identidad
inyectada, los tests de autenticación aún demuestran protección real, y `pytest` completo
queda verde; el override existe solo en el harness de tests.

**Evidencia T7 (hecha):** en `backend/tests/conftest.py` se añadió `identidad_de_prueba()`,
que construye una `IdentidadAutenticada` (usuario local válido no persistido + `sub`
ficticio) y se registra como `app.dependency_overrides[dependencies.get_current_user]`
dentro de `_cliente_de_prueba`, el constructor de los clientes legacy `cliente` y
`cliente_sin_excepcion`. Así los ~140 tests funcionales vuelven a ejercer su comportamiento
de negocio bajo el router agregado protegido, conservando sus asserts sin cambios (ningún
test legacy requirió ajuste). Para que el override **no** se aplique a `test_auth.py`, ese
módulo ahora define su propio fixture `cliente` que sombrea el de `conftest.py` dejando solo
`get_db` redirigido: sus pruebas de 401/seguridad y OpenAPI siguen corriendo contra la
protección real, y `cliente_auth` (T2) tampoco lo hereda. El override vive solo en el
harness de tests; `git diff` toca únicamente `backend/tests/`. Comandos: `cd backend;
.venv\Scripts\python.exe -m pytest -q` → **178 passed, 2 warnings** (antes de T7: 59 passed,
119 failed); `.venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q` → **38 passed**
(protección/401 demostrada de verdad).

## T8 — OpenAPI completo y retiro backend de autenticación local (AC-4, AC-11, AC-12, AC-13)

- [x] Completar pruebas automáticas del `/openapi.json` para HTTP bearer scheme, requisitos
  en rutas de negocio y `/auth/me`, ausencia de auth en health/docs, response model/status
  explícitos y 401. Retirar stub/uso de emisión local de `auth_service.py` y lógica HS256
  residual del backend, incluidas `SECRET_KEY`, `ALGORITHM` y `ACCESS_TOKEN_EXPIRE_MINUTES`
  en config/ejemplo/Compose. La ausencia de fallback/localStorage frontend se comprueba en
  T10/T11, no en esta tarea backend.

**Hecho cuando:** tests fijan el esquema y seguridad por operación; no queda camino que
emita/acepte autenticación local y pytest permanece verde.

**Evidencia T8 (hecha):** ampliada la sección OpenAPI de `backend/tests/api/test_auth.py`
(38 → 52 casos) con: `securityScheme` HTTP bearer publicado; `test_openapi_toda_operacion_de_negocio_exige_bearer`
(recorre **todas** las operaciones bajo `/api/v1`, incluida `/auth/me`); `test_openapi_marca_operaciones_de_negocio_protegidas`
(parametrizado por las 7 rutas de `RUTAS_NEGOCIO`); `test_openapi_auth_me_exige_bearer`;
`test_openapi_rutas_tecnicas_no_exigen_bearer` (parametrizado `/health`, `/docs`, `/openapi.json`
sin `security`); `test_salud_documentacion_y_contrato_accesibles_sin_token` (`/health`, `/docs`,
`/openapi.json` responden 200 sin Bearer); `test_openapi_auth_me_declara_response_model_explicito`
(el `$ref` 200 resuelve a `IdentidadAutenticadaRespuesta` con `usuario_id`/`sub` requeridos) y
`test_openapi_auth_me_documenta_401_con_descripcion`. OpenAPI verificado: `HTTPBearer` publicado
y exigido por las operaciones de `/api/v1`; `test_openapi_marca_operaciones_de_negocio_protegidas`
parametriza las 7 rutas de `RUTAS_NEGOCIO`; `/` y `/health` sin `security`. Retiro local
confirmado por grep en `backend/app/**`: **sin coincidencias** de `HS256`, `jwt.encode`,
`from jose`/`import jose`, `autenticar`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `SECRET_KEY` (fuera de
`CLERK_SECRET_KEY`) ni `ALGORITHM` (exit 1). Se reescribieron los docstrings residuales de
`app/core/security.py` y `app/services/auth_service.py` que aún mencionaban "HS256"/"stub";
`auth_service.py` conserva solo el rol de orquestador de identidad (sin stub `autenticar`).
Config/ejemplo/Compose ya solo exponen `CLERK_*` (T1). `git diff` no toca `backend/app/models/`
ni `database/`. Comandos: `cd backend; .venv\Scripts\python.exe -m pytest tests/api/test_auth.py -q`
→ **52 passed**; suite completa `.venv\Scripts\python.exe -m pytest -q` → **192 passed, 2 warnings**.

## T9 — Angular: servicio de sesión Clerk y pruebas unitarias (AC-1…AC-4, AC-13)

- [x] Escribir primero tests para reemplazo del estado `localStorage` y luego implementar
  `AutenticacionService` standalone sobre `@clerk/clerk-js`: carga Clerk, estado reactivo,
  inicio/logout, token de sesión. Usar nombres de dominio en español y no almacenar el token
  en localStorage. Probar SDK por mock.

**Hecho cuando:** suite unitaria confirma inicio/logout, estado, token del SDK, ausencia de
lectura/escritura de `localStorage` y ausencia de fallback HS256; no hay `NgModule`.

**Evidencia T9 (hecha):** reescrito `frontend/src/app/core/services/auth.service.ts`: `AutenticacionService` standalone (`@Injectable({providedIn:'root'})`) sobre `@clerk/clerk-js`, con estado reactivo `estaAutenticado`/`usuario`/`cargando` en `signal`/`computed`; `inicializar()` idempotente que carga el SDK una vez, publica el estado inicial y engancha `addListener`; `obtenerToken()` delega en `session.getToken()`; `cerrarSesion()` en `signOut`; `montarInicioSesion`/`desmontarInicioSesion` para la UI prebuilt. Retirado todo `localStorage` y cualquier fallback HS256/API local (`guardarToken`, `token` ya no existen). Costura de inyección `CARGADOR_CLERK` (token) que devuelve el SDK por `import()` dinámico: `@clerk/clerk-js` no entra al bundle inicial (evita el presupuesto). El SDK real se satisface por interfaz estructural `InstanciaClerk`; en Karma se reemplaza por el doble `frontend/src/testing/clerk-falso.ts` (sin red). Sin `NgModule`. Nuevo spec `auth.service.spec.ts` (8 casos): carga única/idempotencia, estado reactivo, token del SDK y `null` sin sesión, logout, montaje/desmontaje, ausencia de `localStorage` (spy sobre `Storage.prototype`) y ausencia de API local. Comando: `$env:CHROME_BIN=…; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless` → **99 SUCCESS** (69 legacy + 30 nuevos).

## T10 — Angular: login prebuilt, guard, Bearer y configuración de instancia (AC-1…AC-4, AC-10, AC-13)

T10 crea pruebas frontend `*.spec.ts` nuevas junto con los elementos de interfaz/servicio indicados; hoy esos archivos no existen.

- [x] Crear ruta `/login` y componente standalone que monta `mountSignIn` prebuilt de Clerk
  (UI Clerk embebida; no Account Portal externo ni formulario propio), configurar
  `app.config.ts`/`app.routes.ts`, `auth.guard.ts` y retorno tras login (ruta local solicitada
  o `/dashboard`); logout programático `signOut` redirige a `/login`. Mantener `role.guard.ts`
  inerte. Actualizar interceptor para Bearer Clerk. Escribir tests primero y comprobar sin
  fallback/localStorage ni ruta/UI de registro. Verificar prerequisito externo de instancia:
  solo Email, Google apagado y sign-up abierto deshabilitado.

**Hecho cuando:** pruebas Angular comprueban UI prebuilt/login/logout, retorno local o
dashboard, logout a `/login`, navegación sin sesión, sesión reconocida, header Bearer,
ausencia de localStorage/fallback/ruta de registro y guard de rol inerte; se documenta la
configuración Email-only sin Google/sign-up; suite ng test verde.

**Evidencia T10 (hecha):** nuevo `frontend/src/app/features/auth/login.component.ts` + `login.component.html` (standalone, Tailwind) que en `ngAfterViewInit` espera `inicializar()` y monta `mountSignIn` sobre un `viewChild`; `effect` navega al reconocerse la sesión con `resolverDestinoRetorno()` (ruta local válida o `/dashboard`; se rechaza vacío/`//host`/URL absoluta/`/login`); desmonta la UI en `ngOnDestroy`. Ruta `/login` sin guard en `app.routes.ts` y `canActivate:[AutenticacionGuard]` en las cuatro rutas de negocio. `auth.guard.ts` espera a Clerk y sin sesión devuelve `UrlTree` a `/login?retorno=<url>`; `role.guard.ts` queda inerte (retorna `true`, sin leer roles) para la Feature 007. `token.interceptor.ts` resuelve la asincronía con `from(obtenerToken()).pipe(switchMap(...))` y adjunta `Authorization: Bearer` solo si hay sesión. Logout programático en la shell (`app.component.ts` + botón «Cerrar sesión» con `aria-label`) que llama `cerrarSesion()` y navega a `/login`. La app no expone ruta ni UI de registro. Specs nuevos (21): `auth.guard` (3), `role.guard` (2), `token.interceptor` (3), `login.component` (9: montaje prebuilt, ausencia de UI de registro, no navega sin sesión, retorno local, `/dashboard`, retorno no local, desmontaje, y la unidad de `resolverDestinoRetorno`), `app.routes` (3: guard en negocio, `/login` sin guard, sin ruta de registro) y `app.component` migrado (+2: logout a `/login` y ocultar el marco sin sesión, con doble de `AutenticacionService`). Comandos: `npx ng test …` → **99 SUCCESS**; `npx ng build` → OK, initial 316 kB (Clerk en chunk lazy `clerk` de 1,58 MB raw / 498,56 kB transfer, fuera del presupuesto inicial). **Prerequisito externo (verificación en T12, no bloquea código):** instancia Clerk solo Email, Google apagado y sign-up abierto deshabilitado; la app no publica ruta/UI de registro.

## T11 — Verificación integrada backend/frontend y restricciones (AC-3…AC-13)

- [x] Reconciliar tests y comportamiento completos. Correr `pytest`, `ng test` y build de
  producción; revisar `/openapi.json`. Revisar diff para confirmar que no se tocaron modelos,
  DDL/semilla, que no se persiste `sub`, no hay secretos, password local no interviene, no
  existe fallback/localStorage frontend, y no se añadieron dependencias distintas de T1.

**Hecho cuando:** backend y frontend quedan verdes, build compila, OpenAPI satisface AC-11
y la inspección del diff confirma todas las restricciones AC-12.

**Evidencia T11 (hecha):** `cd backend && .venv\Scripts\python.exe -m pytest -q` → **192
passed, 2 warnings** (~53 s). Frontend `npx ng test --watch=false --browsers=ChromeHeadless`
(con `CHROME_BIN`=Edge) → **99 SUCCESS**. `npx ng build` → OK, sin warnings de presupuesto:
`Initial total` **316.27 kB** (88.86 kB transfer); chunk lazy `clerk` **1.58 MB** raw /
**498.56 kB** transfer (cargado en runtime vía `import()` dinámico; riesgo de first paint,
no de build). `/openapi.json`: `securitySchemes={"HTTPBearer":{"type":"http","scheme":"bearer"}}`,
exigido por las operaciones de negocio de `/api/v1` y por `/auth/me`; `/health`, `/docs` y
`/openapi.json` sin `security`. Restricciones AC-12 verificadas por comando: `git status`/
`git diff -- backend/app/models database/` **sin cambios** (modelos, DDL y semilla intactos);
`git grep "sub" -- backend/app/models` **vacío** (no se persiste `sub`); `git grep "sk_test_"`
solo matchea el **placeholder** `sk_test_tu_clave_secreta` de `backend/.env.example` (ningún
secreto real versionado; la publishable key de `environment.ts` es pública);
`git grep "password" -- core/security.py services/auth_service.py api/dependencies.py` **vacío**
(`usuario.password` no interviene); `localStorage` solo en un **comentario** de
`auth.service.ts` (código sin acceso a almacenamiento local); `git diff` de
`requirements.txt`/`package.json` limitado a las tres dependencias de T1 (`PyJWT[crypto]==2.15.1`,
`httpx==0.28.1`, `@clerk/clerk-js ^6.39.0`).

## T12 — Recorrido funcional 4200 y humo 8080 (AC-1…AC-9, AC-14, AC-16)

- [x] Precondición: asegurar que existan en Clerk usuarios para los correos de la semilla
  local, incluyendo `camila.fernandez@losalpes.cl`, con contraseña conocida y correo
  verificado; el alta mediante el Backend API de Clerk es repetible y comprobable, y debe
  completarse antes del recorrido. Confirmar en dashboard instancia Email-only,
  Google apagado y sign-up abierto deshabilitado.
  En 4200 abrir `/login`, verificar UI prebuilt embebida y ausencia de ruta/UI de registro o
  proveedor extra. Recorrer login/logout y redirecciones, JWT real/JWKS, API Clerk, endpoints
  protegidos, `/auth/me` y rechazo sin sesión. Verificar `azp` autorizado correspondiente a
  4200; no se exige `aud`. Después reconstruir y recrear frontend para que la publishable key
  en `environment.ts` esté incluida; recorrer 8080 de humo verificando ruta/sesión y flujo
  básico. En ambos puertos verificar también que `/auth/me` presenta nombre completo, correo
  local, rol legible e inicial mayúscula; que logout y estado sin sesión no conservan
  identidad ni muestran valores ficticios; y que mientras carga o falla se presenta el
  marcador neutro definido por AC-16.

**Hecho cuando:** se documentan configuración del dashboard y ausencia de registro en app,
pruebas separadas 4200/8080, imagen nueva comprobada y sesión real vinculada; nombre/correo/
rol/avatar y estados neutros de AC-16 quedan comprobados en ambos puertos; no se usan valores
de claves en evidencia.

**Evidencia T12 (hecha):** recorrido manual (no automatizado) hecho por el coordinador en los
dos puertos; no se usa ningún valor de clave en esta evidencia.

- **Configuración del dashboard Clerk (precondición y AC-3):** la instancia es **Email-only**
  (Google apagado) y el acceso de registro pasó de `public` a **`restricted`** mediante
  `PATCH /v1/instance/user_settings` (respuesta 200), de modo que el enlace **"Sign up"
  desapareció de `/login`**. Client Trust quedó despejado y el login interactivo no pide
  código. Los usuarios de prueba (incluida `camila.fernandez@losalpes.cl`, presente en la
  semilla local) se crearon desde el **Backend API de Clerk** con el correo **verificado**.
  La aplicación no publica ruta ni UI de registro (`app.routes.ts` sin ruta de sign-up; el
  login monta `mountSignIn` embebido).
- **Recorrido funcional en 4200 (`npm start`):** `/login` monta la **UI prebuilt de Clerk
  embebida** (`mountSignIn`, no Account Portal), sin errores de consola. El **login
  interactivo** (correo → contraseña) redirige a `/dashboard`. Autenticada como
  `camila.fernandez@losalpes.cl`, el layout muestra **"Camila Fernandez"**, su **correo
  local** en el panel lateral, **"Rol: Administrador"** en el header y el avatar con la
  inicial **"C"**; durante la carga se ven los marcadores neutros **"Cargando identidad"** y
  **"—"**. `GET /api/v1/auth/me` responde **200** con los seis campos
  (`usuario_id`, `sub`, `nombre`, `apellido`, `correo`, `rol`). El cierre de sesión lleva a
  `/login?retorno=%2Fdashboard` y, sin sesión, `/dashboard` redirige a `/login`. La
  validación criptográfica real corre contra el **JWKS de Clerk** con el `azp` autorizado de
  4200; no se exige `aud`.
- **Recorrido de humo en 8080 (imagen reconstruida):** tras
  `docker compose -f docker-compose.yml build frontend` + `up -d`, el bundle de producción
  **sí** contiene "Cargando identidad" e "Identidad no disponible" y **ya no** contiene
  "Super Administrator", "admin@compustock.cl" ni "Superadmin". Se repitieron en 8080 el
  login/logout, la sesión y los marcadores neutros con el mismo resultado que en 4200.
- **Vínculo de sesión real:** el `/auth/me` autenticado devuelve la identidad del usuario
  local vinculado por el correo primario verificado (no datos del perfil Clerk), y el logout
  y el estado sin sesión no conservan identidad ni muestran valores ficticios.

---

## T14 — Enriquecer DTO y servicio de identidad local con rol (AC-8, AC-9, AC-11…AC-13)

- [x] TDD backend: ampliar primero las pruebas HTTP de `/api/v1/auth/me` para exigir
  `usuario_id`, `sub`, `nombre`, `apellido`, `correo` local y `rol` igual a
  `rol.nombre_rol`, y comprobar que `rol_id` no aparece. Incluir caso de identidad/relación
  de rol no resoluble con respuesta segura sin datos ni modificación de usuario. Después
  ampliar DTO Pydantic v2 y delegar el enriquecimiento en `app/services/`; obtener la
  relación con SQLAlchemy ORM, sin SQL raw ni cambios de modelos/DDL. Mantener router delgado,
  `response_model`, `status_code` y OpenAPI.

**Hecho cuando:** pruebas nuevas pasan y la suite completa `pytest` conserva los 192 casos
  previos verdes; `/openapi.json` publica los seis campos y excluye `rol_id`; el diff no toca
  modelos, DDL ni semilla y el endpoint no contiene consultas/lógica de negocio.

**Evidencia T14 (hecha):** TDD rojo→verde. En `backend/tests/api/test_auth.py` se añadieron
`test_auth_me_devuelve_identidad_local_completa` (200 con `usuario_id`, `sub`, `nombre="Ana"`,
`apellido="Perez"`, `correo` local y `rol == datos_base["rol_nombre"]`, es decir
`rol.nombre_rol`), `test_auth_me_no_expone_rol_id` (conjunto exacto de claves del cuerpo y
`"rol_id" not in`), y `test_identidad_no_resoluble_responde_401_sin_datos_ni_mutacion` (se
inyecta por override una identidad cuyo `usuario_id` no existe → 401 sin campos de identidad
en el cuerpo y sin crear filas: la tabla `usuario` sigue con 1 registro vía
`GET /api/v1/usuarios/`). Se amplió `test_openapi_auth_me_declara_response_model_explicito`
para exigir los seis campos requeridos y la ausencia de `rol_id`. En `tests/conftest.py` se
añadió `"rol_nombre": rol.nombre_rol` al dict de `datos_base` (solo tests). Implementación:
`IdentidadAutenticadaRespuesta` (Pydantic v2) declara `usuario_id, sub, nombre, apellido,
correo, rol` sin `rol_id`; `auth_service.construir_identidad_autenticada(db, identidad)` lee
el usuario con `select(Usuario).options(joinedload(Usuario.rol))` (ORM, sin SQL raw) y arma el
DTO con `rol=usuario.rol.nombre_rol`, respondiendo 401 si usuario o relación de rol no
resuelven; el endpoint `/auth/me` queda delgado: `Depends(get_current_user)` +
`Depends(get_db)` y una llamada al servicio. `/openapi.json` verificado: propiedades y
`required` = `{apellido, correo, nombre, rol, sub, usuario_id}`, `rol_id` ausente, `200`/`401`
y `security` presentes. Comandos: `cd backend; .venv\Scripts\python.exe -m pytest -q` →
**195 passed, 2 warnings** (192 previos + 3 nuevos); `git diff -- backend/app/models
database/` vacío. Diff solo toca `app/schemas/auth_schema.py`, `app/services/auth_service.py`,
`app/api/v1/endpoints/auth.py` y `tests/`.

## T15 — Cargar y exponer identidad una vez por sesión Clerk (AC-8, AC-9, AC-13, AC-16)

- [x] TDD frontend: escribir pruebas para petición autenticada a `/api/v1/auth/me` al
  inicializar sesión Clerk, publicación de identidad y estado, no repetición por navegación,
  limpieza inmediata al logout/sin sesión/cambio de sesión, y respuesta tardía tras logout
  que no restaure identidad anterior. Probar error/401 con identidad nula y estado de
  identidad no disponible, sin sustitución por perfil Clerk. Implementar estas capacidades
  en `AutenticacionService` usando señales Angular y mantener separado el estado de sesión
  del estado de identidad.

**Hecho cuando:** pruebas del servicio cubren carga única por sesión, valores del DTO, todos
  los casos de limpieza/error y no hay identidad ficticia; `ng test` conserva los 100 tests
  existentes en verde.

**Evidencia T15 (hecha):** TDD rojo→verde. Se añadió la interfaz `IdentidadAutenticada`
(seis campos `usuario_id, sub, nombre, apellido, correo, rol`; sin `rol_id`) en
`frontend/src/app/shared/interfaces/index.ts`, reflejando el DTO backend. `AutenticacionService`
incorpora `inject(HttpClient)`, las señales **separadas** `identidad` y `estadoIdentidad`
(`'cargando' | 'disponible' | 'no_disponible'`) y el tipo `EstadoIdentidad`, más la carga en
`cargarIdentidad()`: una única `GET ${URL_API}/auth/me` por sesión, disparada solo al
establecerse/cambiar la sesión (misma sesión reemitida no repite). `limpiarIdentidad()` borra
la identidad y sube una `generacionIdentidad` que invalida respuestas en vuelo, de modo que
una respuesta tardía tras logout **no** restaura la identidad anterior; el error/401 deja
identidad nula y `no_disponible` sin usar `fullName`/`primaryEmailAddress` del perfil Clerk.
El estado de sesión (`estaAutenticado`/`usuario`) permanece independiente. El spec
`auth.service.spec.ts` se amplió con la suite `identidad local (/auth/me)` (7 casos: sin
sesión→nula/no disponible; petición única + DTO + Bearer vía `tokenInterceptor`; no repetición
con misma sesión; limpieza inmediata en logout; limpieza+recarga al cambiar de sesión;
respuesta tardía descartada; 401 con identidad nula y sin sustitución por perfil Clerk). Como
el servicio ahora depende de `HttpClient`, se añadieron `provideHttpClient`/`provideHttpClientTesting`
en el spec del servicio y en `login.component.spec.ts` (que instancia el servicio real). La
petición se prueba **autenticada** registrando el `tokenInterceptor` real y comprobando
`Authorization: Bearer token-de-prueba`. Comandos: `$env:CHROME_BIN=…; cd frontend;
npx ng test --watch=false --browsers=ChromeHeadless` → **107 SUCCESS** (100 previos + 7
nuevos); `npx ng build` → OK, `Initial total` 318.14 kB sin warnings de presupuesto.

## T16 — Presentar perfil real y estados neutros en el layout (AC-13, AC-16)

- [x] TDD frontend: escribir pruebas del layout para identidad resuelta (nombre completo,
  correo local, rol legible e inicial del nombre normalizada a mayúscula), carga, error/401 y
  ausencia de sesión. Sustituir los valores quemados de usuario/avatar/rol por estado derivado
  con `computed()` y clases Tailwind; los marcadores neutros no deben parecer usuario real.
  La presentación no añade autorización, filtros ni redirecciones por rol. Ampliar el doble
  Clerk solo si es necesario para simular transiciones de sesión.

**Hecho cuando:** los tests verifican AC-16 y ausencia de los datos ficticios anteriores en
  todos los estados sin identidad; `ng test` conserva los 100 tests existentes en verde y el
  build de producción compila.

**Evidencia T16 (hecha):** TDD rojo→verde. Rojo: `app.component.spec.ts` reescrito exigiendo
`nombreCompleto()`, `correoLocal()`, `rolLegible()` e `inicialNombre()` → `TS2339` (propiedades
inexistentes, compilación falla). Verde tras implementar: `AppComponent` deriva con `computed()`
sobre las señales del servicio (`identidad()` y `estadoIdentidad()`): `nombreCompleto`
(`nombre + apellido`), `correoLocal` (`correo` local del vínculo), `rolLegible` (`rol`),
`inicialNombre` (primera letra del nombre con `toUpperCase()`) y `etiquetaIdentidad`
(neutro: `"Cargando identidad"` en `cargando`, `"Identidad no disponible"` en `no_disponible`).
`app.component.html` sustituye los quemados: avatar `U` → `{{ inicialNombre() ?? '—' }}` (o `—`
neutro); `Super Administrator`/`admin&#64;compustock.cl` → `nombreCompleto()`/`correoLocal()` con
`etiquetaIdentidad()` y `—` como marcadores neutros; `Rol: Superadmin` → `rolLegible() ?? '—'`.
Sin `styles`, sin CSS quemado, sin `NgModule`; los `computed` son puros y no añaden autorización,
filtros ni redirecciones por rol (Feature 007 fuera de alcance). El doble Clerk **no** se tocó
(las transiciones se simulan con señales dobles del servicio en el spec). El spec ahora usa un
doble con `WritableSignal` para `estaAutenticado`/`identidad`/`estadoIdentidad` y conserva los
6 casos previos del layout; se añadieron 6 casos (identidad resuelta sin datos ficticios,
derivación de nombre/correo/rol, inicial del avatar + normalización a mayúscula de `camila`→`C`,
carga con marcador, error `no_disponible` con marcador, y sin sesión sin marco ni ficticios),
cada uno comprobando la ausencia de `Super Administrator`/`admin@compustock.cl`/`Superadmin`.
Comandos: `$env:CHROME_BIN=…; cd frontend; npx ng test --watch=false --browsers=ChromeHeadless`
  → **113 SUCCESS** (107 previos + 6 nuevos); `npx ng build` → OK, `Initial total` 318.93 kB
  (89.69 kB transfer) sin errores ni warnings de presupuesto.

## T17 — Retirar tarjeta exterior del login (AC-17) — cambio posterior al cierre

- [x] Actualizar la vista `/login` para retirar únicamente la tarjeta exterior propia del
  sistema que enmarca la UI de Clerk. Conservar la cabecera CompuStock ERP sobre el login,
  el fondo de página y el comportamiento de retorno; no modificar la UI prebuilt de Clerk
  ni la lógica de autenticación.
- [x] Añadir o ajustar una prueba de vista que verifique una sola caja de credenciales (la
  de Clerk), sin tarjeta exterior propia, y que la cabecera de marca siga presente.
- [x] Verificar visualmente `/login` en el recorrido frontend y ejecutar `ng test`.

**Hecho cuando:** la vista muestra la UI prebuilt de Clerk sin tarjeta contenedora exterior,
la cabecera/fondo/retorno se conservan, y la prueba de vista y la suite `ng test` pasan.

## Cierre

### Trazabilidad AC → task(s)

| AC | Tasks |
|---|---|
| AC-1 | T9, T10, T12 |
| AC-2 | T9, T10 |
| AC-3 | T10, T12 |
| AC-4 | T1, T8, T9, T10, T11 |
| AC-5 | T1–T4, T11, T12 |
| AC-6 | T1–T3, T11, T12 |
| AC-7 | T2–T3, T11–T12 |
| AC-8 | T2, T4–T5, T12, T14–T15 |
| AC-9 | T2–T6, T12 |
| AC-10 | T6–T7, T10 |
| AC-11 | T2, T4–T6, T8, T11, T13 |
| AC-12 | T1, T3, T8, T11 |
| AC-13 | T2–T11, T13–T16 |
| AC-14 | T1, T6, T12–T13 |
| AC-15 | T13 |
| AC-16 | T12, T15–T16 |
| AC-17 | T17 |

## T13 — Evidencia AC, documentación viva y coherencia (AC-11…AC-16)

- [x] Registrar evidencia concreta por AC en `spec.md` solo después de verificarla; no
  cambiar requisitos aprobados. Actualizar `stack.md` §1/§2/§5 para reflejar Clerk, retiro
  de JWT local y dependencia en router agregado. Actualizar `MEMORY.md` al cierre. Hacer
  grep de coherencia sobre `AGENTS.md`, `MEMORY.md` y `.agents/skills/` para rutas/estados
  obsoletos. Revisar tests finales y `/openapi.json`; actualizar roadmap solamente cuando
  todos los AC estén verificados y 4200/8080 confirmados.

**Hecho cuando:** existe evidencia por los 16 AC; `pytest` y `ng test` están verdes;
OpenAPI, recorrido 4200 y humo 8080 (incluido AC-16 en cada puerto) quedan documentados;
`stack.md` y `MEMORY.md` reflejan el estado real; grep no deja rutas/afirmaciones obsoletas;
roadmap solo se marca cerrada si se cumplen todas las condiciones de cierre de `AGENTS.md`
§8.5–§8.7.

**Evidencia T13 (hecha):** cierre documental de la feature.

- **Evidencia por AC:** `spec.md` §6 registra la tabla "Evidencia de verificación al cierre"
  con los 16 AC (AC-1…AC-16) y su comprobación concreta; no se cambió ningún requisito
  aprobado.
- **Suites (re-ejecutadas por el implementador en el cierre):** `cd backend;
  .venv\Scripts\python.exe -m pytest -q` → **195 passed, 2 warnings** (43 s); frontend
  `$env:CHROME_BIN=…; npx ng test --watch=false --browsers=ChromeHeadless` →
  **TOTAL: 113 SUCCESS**. `npx ng build` → OK, `Initial total` **318.93 kB** sin warnings de
  presupuesto.
- **OpenAPI:** `/openapi.json` contra el backend en vivo publica `securitySchemes` con
  `HTTPBearer`, exige Bearer en las operaciones de negocio de `/api/v1` (incluida
  `/auth/me`), y `IdentidadAutenticadaRespuesta` con los seis campos requeridos
  (`apellido, correo, nombre, rol, sub, usuario_id`), **sin `rol_id`**; salud y documentos
  sin `security`.
- **Recorrido 4200 y humo 8080:** documentados en T12, incluidos nombre/correo/rol/avatar y
  los marcadores neutros de AC-16 en **ambos** puertos, con la imagen de producción
  reconstruida y recreada.
- **Documentación viva:** `stack.md` §1/§2/§5 actualizado a Clerk (retiro de JWT local
  HS256); `MEMORY.md` reescrito al estado real; `roadmap.md` fila 006 marcada como cerrada.
- **Grep de coherencia (§8.7):** se encontraron y corrigieron afirmaciones obsoletas sobre el
  estado de la autenticación en `AGENTS.md` (§3 y §7), `.agents/skills/sdd-workflow/SKILL.md`
  y `.agents/skills/fastapi-pydantic-v2/SKILL.md`, y una nota menor en
  `.agents/skills/angular-standalone/SKILL.md` sobre el interceptor funcional. Tras la
  corrección no quedan rutas ni afirmaciones obsoletas sobre autenticación local.
