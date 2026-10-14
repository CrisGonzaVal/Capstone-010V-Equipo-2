# Feature 006: Integración de Clerk en Angular y validación JWT en FastAPI

**Estado:** Cerrada y verificada  
**Release:** 2.0 — Sprint 3  
**Tipo:** Seguridad e identidad federada

## 1. Problema

La autenticación actual es decorativa: el frontend simula el estado de sesión y el backend
no valida una identidad real. Por ello las peticiones a la API no pueden atribuirse con
seguridad a un usuario autenticado y las pantallas no disponen de un ciclo real de inicio y
cierre de sesión. La Release 2.0 requiere identidad federada antes de incorporar el control
de acceso por roles de la Feature 007.

## 2. Objetivo

Reemplazar la autenticación local decorativa por una sesión de Clerk iniciada desde Angular
y validada por FastAPI. El backend debe verificar los JWT de sesión de Clerk, consultar el
Backend API de Clerk para obtener el correo primario y su verificación, vincularlo con un
usuario local preexistente y exponer la identidad mediante `GET /api/v1/auth/me`. No se
emiten ni se aceptan tokens locales como alternativa.

## 3. Alcance

### Dentro

- Inicio y cierre de sesión en Angular mediante la experiencia alojada de Clerk; se define
  la ruta/flujo de login y no se habilita registro/autoregistro en la aplicación.
- Sesión frontend administrada por Clerk: sustitución de `AutenticacionService` local y
  eliminación del almacenamiento local de token. El token vigente de Clerk se presenta
  como Bearer, mediante el SDK/interceptor que corresponda.
- Validación en FastAPI del JWT de sesión Clerk mediante JWKS publicado por el emisor
  `CLERK_ISSUER`, verificando firma, vigencia y emisor.
- Uso de `CLERK_SECRET_KEY` para consultar el Backend API de Clerk, en
  `https://api.clerk.com`, mediante `GET /v1/users/{sub}`. De esa respuesta se obtiene el
  correo primario y su estado de verificación; el token de sesión por defecto no se
  considera fuente del correo.
- Vínculo de identidad por correo primario verificado en Clerk que coincida con un
  registro `usuario` existente. Si no existe coincidencia, no se crea ni modifica usuario y
  la solicitud se rechaza con 401. La consulta de Clerk puede cachearse por `sub` sin
  cambiar este comportamiento.
- Endpoint `GET /api/v1/auth/me` que devuelve `usuario_id`, `sub` validado de Clerk,
  `nombre`, `apellido`, `correo` local y el nombre legible del rol local.
- Visualización de la identidad resuelta en el panel lateral y el header compartido:
  nombre completo, correo, rol e inicial del nombre como avatar. Mientras la identidad de
  `/auth/me` se carga, la interfaz muestra un estado neutro y nunca datos de usuario
  ficticios o quemados.
- Exigencia de identidad autenticada en todas las rutas de negocio de la API v1 mediante
  dependencia aplicada al router agregado. No se añaden dependencias de auth a la lógica de
  endpoints de tickets, inventario o usuarios.
- Retiro completo de la emisión y autenticación local JWT HS256, el login simulado y el
  almacenamiento local del token. El interceptor existente inyecta el token de Clerk o es
  sustituido por el mecanismo equivalente del SDK.
- Configuración por nombres de variable `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` y
  `CLERK_ISSUER`. La clave pública se inyecta desde `environment.ts` de Angular y debe estar
  disponible en build time; no se incluyen valores secretos en esta spec.
- Análisis previo de dependencias: SDK Angular oficial de Clerk para integración frontend;
  para backend, alternativa de SDK Clerk o librería JWT/JWKS. La selección se justifica en
  el plan antes de instalar cualquier paquete.
- Migración de la suite existente del backend: las pruebas de negocio que antes invocaban
  `/api/v1/*` sin credenciales se adaptan para inyectar una identidad por una costura
  dependible y override en `conftest.py`; además se agregan pruebas de aceptación y rechazo
  de autenticación.
- Actualización de `stack.md` al cierre: §2 deja de describir `auth_service.py`/`core/security.py`
  como emisores de JWT local; §5 documenta la exigencia por dependencia del router agregado
  y que no se modifican los endpoints de negocio para autenticar.

### Fuera

- Guards y permisos por rol (`Admin`, `Bodeguero`, `Solicitante`), autorización backend por
  rol, redirecciones según rol y protección de rutas frontend por rol: Feature 007. En 006,
  `role.guard.ts` queda inerte y no implementa lógica de rol.
- Creación automática, invitación, edición o aprovisionamiento de usuarios locales;
  administración de cuentas y registro abierto en la aplicación.
- Cambios al modelo de datos de 12 entidades, a la tabla `usuario` o al DDL. No se persiste
  el `sub`; `usuario.correo` es UNIQUE y permite un vínculo local no ambiguo. La limitación
  es que un cambio/rotación de correo puede romper el vínculo. `usuario.password` queda sin
  uso por esta autenticación.
- Clerk Organizations, aislamiento multi-tenant, selección de institución/sede y políticas
  de otras features de Release 2.0.
- Autenticación con Google u otro proveedor: la instancia habilitada usa Email solamente.
- Uso simultáneo, fallback o migración progresiva desde JWT local HS256.
- JWT template personalizada: la consulta de correo se hace al Backend API de Clerk, no se
  agrega email al token mediante template.
- Decisiones técnicas de paquetes y detalles internos que no cambian el comportamiento
  requerido; corresponden al plan, respetando las exigencias técnicas expresas de esta spec.

## 4. Decisiones

### D-1 — Clerk sustituye completamente a la autenticación local

Clerk es la única autoridad de autenticación de la aplicación. Se retiran el login simulado,
el almacenamiento local del token y la emisión local HS256; admitir ambos mecanismos
mantendría dos fuentes de identidad y comportamientos de seguridad divergentes.

### D-2 — El correo se obtiene del Backend API de Clerk

El JWT de sesión por defecto no se considera portador de correo y no se usa una JWT template
personalizada. FastAPI primero valida firma, vigencia y emisor mediante JWKS de
`CLERK_ISSUER`; después consulta `GET https://api.clerk.com/v1/users/{sub}` autenticándose
con `CLERK_SECRET_KEY`, y lee allí el correo primario y su estado de verificación. Se exige
que esté verificado y que coincida con un correo local.

### D-3 — Vínculo local por correo primario verificado, sin persistir el `sub`

El correo primario verificado obtenido de Clerk debe coincidir con el correo de un usuario
local existente. Si no hay coincidencia se responde 401 y no se provisiona usuario. La
columna `usuario.correo` es UNIQUE, lo que evita vínculos ambiguos sin agregar una columna
para `sub` ni alterar las doce entidades. Se acepta como limitación que la rotación/cambio
del correo puede interrumpir el vínculo. El campo `usuario.password` queda sin uso para
autenticación.

### D-4 — La identidad autenticada tiene un endpoint explícito

`GET /api/v1/auth/me` devuelve el DTO `IdentidadAutenticadaRespuesta`, con los campos
`usuario_id` (entero local), `sub` (identificador de usuario de Clerk validado), `nombre`,
`apellido`, `correo` local y `rol` como string con el valor legible de `rol.nombre_rol`.
Se expone el rol como nombre, no como objeto con identificador, porque esta entrega solo
necesita presentarlo; la Feature 007 definirá por separado los identificadores/políticas que
requiera para autorizar. El `sub` no se persiste ni se afirma como dato local. El endpoint
permite al frontend y a clientes autenticados consultar el vínculo ya resuelto.

### D-13 — La identidad visible se deriva del usuario local vinculado

Nombre, apellido, correo y rol se leen del registro local resuelto por el correo primario
verificado de Clerk y su relación de rol. La aplicación muestra el correo local
(`usuario.correo`), que es la clave efectiva del vínculo, y no un valor potencialmente
distinto del perfil de Clerk. Si Clerk autentica a una persona cuyo correo no tiene vínculo
local, se mantiene el 401 actual; el layout no muestra identidad y presenta un estado neutro
de identidad no disponible. La carga de `/auth/me` tampoco usa datos de Clerk como
sustituto ni conserva datos ficticios.

### D-14 — El layout presenta identidad sin autorizar por rol

Al resolver `/auth/me`, el panel lateral presenta nombre completo y correo y el header
presenta el rol legible. El avatar usa la inicial del nombre local, normalizada a mayúscula.
Antes de recibir la identidad, y cuando la respuesta falla o no hay sesión, el layout no
presenta valores por defecto que parezcan identidad real; muestra un marcador neutro (por
ejemplo, “Cargando identidad” durante carga y “Identidad no disponible” ante fallo), sin
alterar las reglas de sesión Clerk. Mostrar el rol es informativo y no concede, restringe ni
redirecciona por permisos; eso corresponde a la Feature 007.

### D-5 — El login es alojado y no habilita autoregistro

Angular integra la experiencia alojada de Clerk para iniciar y terminar sesión. La
instancia está configurada para Email; el inicio de sesión requiere usuarios previamente
creados en Clerk y vinculados por correo a la semilla local. No se crean identidades ni se
asignan roles, departamento o institución durante el alta.

### D-6 — JWKS valida el JWT; Backend API obtiene y verifica el correo

La validación criptográfica del token de sesión usa las claves públicas JWKS del emisor
configurado en `CLERK_ISSUER` y verifica firma, vigencia y emisor. `CLERK_SECRET_KEY` no se
usa para validar la firma del JWT: autentica la consulta al Backend API de Clerk que
recupera correo primario y verificación. Las fallas en cualquiera de ambos pasos se
responden como 401. La consulta de Backend API puede cachearse por `sub` sin alterar el
resultado funcional requerido.

### D-7 — Toda ruta de negocio exige identidad; los roles se difieren

Las rutas de negocio de v1 exigen identidad autenticada. La exigencia se aplica mediante
dependencia de seguridad en el router agregado, no modificando los routers/endpoints de
tickets, inventario o usuarios. No se evalúan roles ni permisos en la 006; esa política
pertenece a la Feature 007. Salud y documentación permanecen accesibles sin token.

### D-8 — Los fallos de autenticación o vínculo se presentan como 401

Token ausente, firma inválida, emisor incorrecto, expiración, fallo de verificación JWKS,
fallo o respuesta inadecuada del Backend API de Clerk, correo no verificado o falta de
coincidencia local producen 401, sin devolver identidad autenticada ni filtrar la causa
interna al cliente.

### D-9 — La suite usa identidad inyectada y JWKS simulado

La exigencia de autenticación afecta las pruebas de negocio existentes. La suite migra para
inyectar una identidad autenticada por una costura dependible con override en `conftest.py`,
manteniendo así sus pruebas sobre la lógica de negocio sin omitir la seguridad en
producción. Las pruebas de autenticación usan un JWKS simulado con par de claves de
fixture; la validación criptográfica real contra Clerk se comprueba en el recorrido
funcional en 4200.

### D-10 — La clave publicable se configura en build time

`CLERK_PUBLISHABLE_KEY` se integra mediante `environment.ts` de Angular. Es una clave
pública y versionable, pero debe estar presente en el build frontend. El puerto 8080 sirve
una imagen congelada y solo reflejará la feature después de reconstruir y recrear el
frontend.

### D-11 — OpenAPI publica la seguridad Bearer

La seguridad Bearer se expresa mediante la dependencia de seguridad HTTP bearer de
FastAPI, de modo que `/openapi.json` publica el `securityScheme` correspondiente y marca
las operaciones de negocio protegidas. El contrato documenta 401 para credenciales
ausentes o no válidas.

### D-12 — La estrategia de dependencias se decide en el plan

La spec exige SDK Angular oficial de Clerk o mecanismo de sesión del SDK y validación
backend JWT/JWKS con consulta al Backend API de Clerk. Se comparan opciones de dependencia
y compatibilidad antes de instalar; la selección y su justificación se documentan en el
plan. Esta decisión técnica no altera los comportamientos de autenticación aquí definidos.

## 5. Contrato de identidad y autenticación

### Sesión Angular → API

- Angular presenta el flujo de login alojado de Clerk y permite logout.
- La sesión frontend la administra Clerk, no `localStorage` ni un token local.
- Para peticiones a rutas de negocio Angular presenta el token vigente de sesión Clerk como
  credencial Bearer, mediante el SDK/interceptor que se seleccione.
- La clave pública proviene de `environment.ts` y se requiere en el build de producción.

### Validación y vínculo FastAPI

1. FastAPI obtiene el Bearer de Clerk y valida su firma con JWKS publicado bajo el emisor
   `CLERK_ISSUER`; exige firma válida, token vigente y emisor coincidente.
2. Del `sub` ya validado, FastAPI consulta con `CLERK_SECRET_KEY` el Backend API
   `GET https://api.clerk.com/v1/users/{sub}` y obtiene correo primario y estado de
   verificación. El correo del token de sesión no se utiliza como fuente de vínculo; no se
   usa JWT template personalizada.
3. Exige correo primario verificado y coincidencia exacta con un registro local existente
   en `usuario.correo`. La columna es UNIQUE; no se crea ni modifica usuario y el `sub` no
   se persiste. La consulta de Clerk puede cachearse por `sub`.
4. Ante cualquier fallo de los pasos de validación o vínculo responde 401 sin identidad
   autenticada ni detalle interno de la causa.

### `GET /api/v1/auth/me`

- Requiere la autenticación y el vínculo anteriores.
- Responde HTTP 200 con `IdentidadAutenticadaRespuesta`:

  ```json
  {
    "usuario_id": 6,
    "sub": "user_clerk_validado",
    "nombre": "Camila",
    "apellido": "Fernández",
    "correo": "camila.fernandez@losalpes.cl",
    "rol": "Administrador"
  }
  ```

- `usuario_id`, `nombre`, `apellido`, `correo` y `rol` (`rol.nombre_rol`) corresponden al
  usuario y rol locales vinculados; `sub` es el identificador validado de Clerk y no implica
  persistencia en la base local. El DTO no expone `rol_id` en esta entrega.
- Sin Bearer válido o sin vínculo local responde HTTP 401.

### Protección de rutas y OpenAPI

- Todas las rutas de negocio de `/api/v1` exigen la dependencia de autenticación colocada
  en el router agregado. No se alteran las operaciones de negocio de tickets, inventario o
  usuarios para incorporar la exigencia.
- La dependencia de seguridad HTTP Bearer publica el `securityScheme` y los requisitos
  por operación en `/openapi.json`; las operaciones protegidas documentan 401.
- Salud y documentación OpenAPI quedan accesibles sin token.
- La identidad se autentica sin autorización por rol, que pertenece a la Feature 007.

## 6. Criterios de aceptación

### Experiencia de sesión y sustitución

- [x] **AC-1** DADO QUE existe en Clerk una cuenta con correo correspondiente a un usuario
  local y correo verificado, CUANDO la persona inicia sesión desde la ruta/flujo Angular de
  login mediante la experiencia alojada, ENTONCES la sesión queda reconocida como
  autenticada; al cerrar sesión, deja de estarlo.
- [x] **AC-2** DADO QUE Angular solicita una ruta de negocio, ENTONCES presenta el token
  vigente de Clerk como Bearer, obtenido mediante el SDK/interceptor; no presenta un token
  local como alternativa.
- [x] **AC-3** La aplicación no permite registro/autoregistro abierto ni autenticación con
  Google u otro proveedor en esta entrega; solo integra inicio de sesión por Email de la
  instancia Clerk configurada.
- [x] **AC-4** El login simulado, el `localStorage` de token y la emisión local HS256 no
  autentican ni permiten acceso a rutas de negocio; no existe fallback ni coexistencia con
  Clerk. `AutenticacionService` representa la sesión de Clerk y `role.guard.ts` no introduce
  autorización por rol.

### Validación, vínculo e identidad

- [x] **AC-5** DADO QUE se presenta un JWT de sesión firmado por una clave publicada en JWKS
  de `CLERK_ISSUER`, vigente y con emisor coincidente, ENTONCES FastAPI valida firma,
  vigencia y emisor antes de usar su `sub`.
- [x] **AC-6** DADO QUE el JWT fue validado, CUANDO FastAPI consulta con
  `CLERK_SECRET_KEY` `GET https://api.clerk.com/v1/users/{sub}`, ENTONCES obtiene de la
  respuesta el correo primario y su estado de verificación; el correo de los claims del
  token no se usa como fuente de vínculo y no se requiere JWT template personalizada.
- [x] **AC-7** DADO QUE el Backend API de Clerk informa un correo primario verificado que
  coincide con exactamente un `usuario.correo` local, ENTONCES se resuelve esa identidad;
  SI el correo no está verificado o no coincide, ENTONCES no hay vínculo autenticado. La
  unicidad local de `usuario.correo` evita ambigüedad.
- [x] **AC-8** DADO QUE el token es válido y el correo primario verificado fue vinculado a un
  usuario local con rol, CUANDO se consulta `GET /api/v1/auth/me`, ENTONCES responde 200 con
  `IdentidadAutenticadaRespuesta` que contiene `usuario_id` (entero local), `sub`
  (identificador de Clerk validado), `nombre`, `apellido`, `correo` del registro local y
  `rol` como string legible igual a `rol.nombre_rol`; el contrato no incluye `rol_id` y no
  afirma que `sub` esté persistido.
- [x] **AC-9** SI falta el token, la firma/emisor/vigencia no es válida, falla la consulta o
  respuesta del Backend API de Clerk, el correo no está verificado, no hay usuario local
  coincidente o no puede resolverse la identidad, ENTONCES todas las rutas protegidas,
  incluido `/auth/me`, responden 401 sin identidad y sin crear/modificar filas de usuario.

### Protección de API y contrato

- [x] **AC-10** Todas las rutas de negocio de `/api/v1` requieren identidad autenticada; las
  rutas técnicas de salud y la documentación OpenAPI quedan accesibles sin token. La
  exigencia se aplica en el router agregado mediante dependencia y no añade lógica de
  autenticación a los endpoints de tickets, inventario o usuarios. No se deniega por rol en
  esta feature.
- [x] **AC-11** `/openapi.json` publica un `securityScheme` HTTP bearer y marca las
  operaciones de negocio protegidas; documenta 401 y el contrato de
  `GET /api/v1/auth/me` con su `response_model` y `status_code` explícitos. Salud y
  documentación no aparecen como operaciones protegidas.
- [x] **AC-12** No se modifican las doce entidades, la tabla `usuario` ni el DDL; no se
  persiste `sub`. Ningún valor de clave o secreto aparece en documentación versionada y las
  variables se nombran únicamente como `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` y
  `CLERK_ISSUER`.

### Verificación y cierre

- [x] **AC-13** `pytest` adapta la suite de negocio existente (aprox. 140 pruebas) para
  inyectar identidad mediante una costura dependible y override en `conftest.py`, sin
  desproteger la aplicación de producción. Agrega pruebas de aceptación/rechazo, vínculo,
  `/auth/me` (incluyendo los campos de perfil y rol), protección de rutas y respuestas 401;
  la firma se verifica contra un JWKS simulado con par de claves de fixture. `ng test` cubre
  login/logout, Bearer Clerk, ausencia de fallback local y presentación de identidad/estados
  neutros.
- [x] **AC-14** Antes del recorrido, existen en Clerk usuarios de prueba con los correos de
  la semilla local (por ejemplo, `camila.fernandez@losalpes.cl`), contraseña conocida y
  correo verificado. El Backend API de Clerk es un mecanismo válido para dar de alta esos
  usuarios; el mecanismo de alta no es relevante siempre que se cumpla ese resultado antes
  del recorrido. Se acepta el alta por Backend API porque es repetible y comprobable
  (scriptable y ejecutable de nuevo), a diferencia del alta manual desde el dashboard. En
  4200 se verifica el login/logout, la validación criptográfica real contra Clerk, el acceso
  a API, `/auth/me` y el rechazo sin sesión. En 8080, tras reconstruir y recrear el frontend
  de producción, se verifica de humo la ruta/sesión y el flujo básico;
  `CLERK_PUBLISHABLE_KEY` debe estar disponible en `environment.ts` durante el build.
- [x] **AC-15** Al cierre se actualiza `stack.md`: §2 ya no describe `auth_service.py` ni
  `core/security.py` como emisores de JWT local y §5 registra que la autenticación se
  exige en el router agregado sin modificar endpoints de negocio. La verificación de
  `/openapi.json`, suites y recorridos queda documentada por AC; la feature no se marca
  cerrada en roadmap hasta que todos los AC estén verificados y 4200/8080 reflejen el
  incremento conforme a `AGENTS.md` §8.5–§8.7.
- [x] **AC-16** DADO QUE existe sesión Clerk, CUANDO `/api/v1/auth/me` responde con identidad
  local, ENTONCES el layout compartido muestra nombre completo y correo en el panel lateral,
  rol legible en el header e inicial en mayúscula del nombre en el avatar; SI la identidad
  aún carga, falla o no está disponible, ENTONCES muestra un estado neutro (carga o identidad
  no disponible) y no muestra los valores ficticios anteriores ni un rol supuesto. La
  presentación no evalúa permisos, no bloquea rutas ni redirecciona según rol.

### Evidencia de verificación al cierre

| AC | Evidencia |
|---|---|
| AC-1 | Recorrido manual 4200/8080 (T12): login interactivo correo → contraseña → redirección a `/dashboard` con la sesión reconocida; el cierre de sesión lleva a `/login?retorno=%2Fdashboard` y deja de estar autenticado. Tests de `AuthGuard` y de `login.component` (retorno local/dashboard, no navega sin sesión). |
| AC-2 | `frontend/src/app/core/interceptors/token.interceptor.ts` adjunta `Authorization: Bearer` con `session.getToken()` del SDK; `token.interceptor.spec.ts` (3 casos) y la petición autenticada de `auth.service.spec.ts` comprueban el header. Sin token, la petición pasa intacta (no hay token local). Recorrido 4200: `/auth/me` y rutas de negocio responden con Bearer real. |
| AC-3 | Instancia Clerk **Email-only** (Google apagado) y acceso de registro en modo **`restricted`** (`PATCH .../user_settings` → 200): el enlace "Sign up" desapareció de `/login`. `app.routes.ts` no publica ruta de registro y `login.component.spec.ts` comprueba la ausencia de UI de registro. |
| AC-4 | `backend/app/core/security.py` valida solo JWTs de Clerk por JWKS (allowlist `RS256`); grep sin coincidencias de `HS256`, `jwt.encode`, `autenticar`, `SECRET_KEY` (fuera de `CLERK_SECRET_KEY`) ni `ACCESS_TOKEN_EXPIRE_MINUTES` en `backend/app/**`. `auth.service.ts` representa la sesión de Clerk sin `localStorage` (spy en el spec) y `role.guard.ts` retorna `true` sin leer roles. |
| AC-5 | `test_token_valido_responde_200`, `test_firma_invalida_responde_401`, `test_iss_incorrecto_responde_401`, `test_iss_igual_al_emisor_responde_200`, `test_token_expirado_responde_401`, `test_token_antes_de_nbf_responde_401`, `test_algoritmo_no_permitido_responde_401`, `test_azp_*` y `test_token_sin_aud_no_se_exige_responde_200` (JWKS simulado con par de claves de fixture). Recorrido 4200: validación criptográfica real contra el JWKS de Clerk. |
| AC-6 | `test_correo_primario_verificado_vincula_usuario`, `test_correo_no_verificado_responde_401`, `test_correo_primario_ausente_responde_401`, `test_fallo_del_backend_api_responde_401` y `test_error_de_red_del_backend_api_responde_401`: el correo se lee de `GET /v1/users/{sub}` con `CLERK_SECRET_KEY`; no se usa el correo de los claims ni JWT template. |
| AC-7 | `test_correo_primario_verificado_vincula_usuario` (vínculo exacto por `usuario.correo` UNIQUE) y `test_correo_no_coincidente_responde_401`/`test_correo_no_verificado_responde_401` (sin vínculo). `vincular_usuario_por_correo()` usa SQLAlchemy ORM; no crea ni modifica usuario. |
| AC-8 | `test_auth_me_devuelve_identidad_local_completa` (200 con `usuario_id`, `sub`, `nombre`, `apellido`, `correo` local y `rol == rol.nombre_rol`), `test_auth_me_no_expone_rol_id` y `test_openapi_auth_me_declara_response_model_explicito` (seis campos requeridos, sin `rol_id`). Recorrido 4200/8080: `/auth/me` → 200 con los seis campos. |
| AC-9 | `test_auth_me_sin_bearer_responde_401`, `test_auth_me_con_bearer_invalido_responde_401`, `test_ruta_de_negocio_sin_bearer_responde_401`, `test_identidad_no_resoluble_responde_401_sin_datos_ni_mutacion` (sin filas creadas) y toda la batería de 401 de T2/T3; el frontend limpia identidad ante error/401 sin sustituir por el perfil Clerk (`auth.service.spec.ts`). |
| AC-10 | `test_ruta_de_negocio_con_bearer_valido_responde_200`, `test_openapi_toda_operacion_de_negocio_exige_bearer`, `test_openapi_salud_no_requiere_seguridad_y_publica_bearer` y `test_salud_documentacion_y_contrato_accesibles_sin_token`; la dependencia vive en el router agregado `app/api/v1/api.py` sin tocar los endpoints de negocio. |
| AC-11 | `test_openapi_publica_esquema_bearer`, `test_openapi_marca_operaciones_de_negocio_protegidas`, `test_openapi_auth_me_exige_bearer`, `test_openapi_auth_me_documenta_200_y_401`, `test_openapi_auth_me_documenta_401_con_descripcion` y `test_openapi_rutas_tecnicas_no_exigen_bearer`; parametrización sobre las 7 rutas de `RUTAS_NEGOCIO` y verificación en vivo de `/openapi.json` (HTTPBearer, 200/401, seis campos). |
| AC-12 | `git diff -- backend/app/models database/` **vacío** (12 entidades, tabla `usuario` y DDL intactos); no se persiste `sub` (grep vacío en `backend/app/models`); `usuario.password` sin uso en `security.py`/`auth_service.py`/`dependencies.py`; ningún valor de secreto versionado (solo se nombran `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` y `CLERK_ISSUER`). |
| AC-13 | Backend `pytest` → **195 passed, 2 warnings** (`test_auth.py` crece la cobertura de aceptación/rechazo, vínculo, `/auth/me`, protección y OpenAPI con JWKS simulado y override de identidad en `conftest.py` para la suite legacy). Frontend `ng test` → **113 SUCCESS** (login/logout, Bearer Clerk, ausencia de fallback local, carga/limpieza de identidad y estados neutros del layout). |
| AC-14 | T12 documenta usuarios de prueba dados de alta mediante Backend API de Clerk, con correos de la semilla local (incluido `camila.fernandez@losalpes.cl`), contraseña conocida y correo verificado antes del recorrido; el login interactivo correo → contraseña del recorrido 4200 confirma que esas credenciales de prueba incluyen una contraseña conocida y funcional (el valor no se registra aquí). Documenta también el recorrido funcional en 4200 y de humo en 8080 tras reconstruir y recrear el frontend. La evidencia confirma el resultado exigido, sin afirmar que se verificaron otros mecanismos de alta. |
| AC-15 | `stack.md` §1/§2/§5 actualizado: ya no describe `auth_service.py`/`core/security.py` como emisores de JWT local y §5 registra la exigencia por dependencia del router agregado sin modificar endpoints de negocio. Evidencia por AC, suites y recorridos documentados; la feature se marca cerrada en `roadmap.md` solo tras verificar todos los AC y ambos puertos (`AGENTS.md` §8.5–§8.7). |
| AC-16 | `app.component.spec.ts` (identidad resuelta sin datos ficticios, derivación de nombre/correo/rol, inicial `camila`→`C`, carga y error con marcadores, sin sesión sin marco) y `auth.service.spec.ts` (identidad y estado separados). Recorrido 4200/8080: "Camila Fernandez", correo local, "Rol: Administrador" e inicial "C"; marcadores neutros "Cargando identidad" / "Identidad no disponible" y "—"; el bundle de producción ya no contiene "Super Administrator", "admin@compustock.cl" ni "Superadmin". |

## 7. Restricciones

- Se usa exclusivamente la instancia de desarrollo de Clerk configurada para Email. La
  spec nunca contiene valores de claves; solo nombra `CLERK_PUBLISHABLE_KEY`,
  `CLERK_SECRET_KEY` y `CLERK_ISSUER`.
- `CLERK_ISSUER` identifica el emisor del JWT y la ubicación de sus claves públicas JWKS.
  `CLERK_SECRET_KEY` autentica la consulta al Backend API para obtener correo y verificación;
  no se usa como sustituto de JWKS para verificar la firma.
- El correo se lee del Backend API de Clerk después de validar el JWT; el token de sesión
  por defecto no trae email y no se usa JWT template personalizada.
- El `sub` no se persiste. `usuario.correo` es UNIQUE y es la clave de vínculo funcional;
  cambio/rotación del correo es una limitación aceptada. `usuario.password` queda sin uso.
- No se modifica el modelo de 12 entidades ni se implementa autorización por rol; esta
  última corresponde a Feature 007. `role.guard.ts` queda inerte en lo relativo a roles.
- La identidad extendida se obtiene leyendo `usuario.nombre`, `usuario.apellido`,
  `usuario.correo` y el nombre de la relación `usuario.rol.nombre_rol`; no se modifica el
  esquema. El endpoint expone `rol` como string y no expone `rol_id`.
- El layout solo presenta la identidad resuelta por `/auth/me`. No usa nombre/correo del
  perfil Clerk como reemplazo, no inventa datos durante la carga y mantiene un estado neutro
  ante carga, 401 o error.
- No se agregan dependencias sin análisis comparativo y decisión documentada en el plan.
- La suite valida firma frente a JWKS simulado; la verificación criptográfica contra Clerk
  se comprueba en el recorrido real por 4200.
- La dependencia de seguridad se aplica en el router agregado. Se preserva la lógica de
  endpoints existente y se actualiza `stack.md` al cierre para reflejar esa regla y el
  reemplazo de la emisión JWT local.
- `CLERK_PUBLISHABLE_KEY` se inyecta mediante `environment.ts`; el frontend de 8080 es un
  build congelado y debe reconstruirse/recrearse para verificar la feature.
- Los errores de validación, consulta Clerk y vínculo se expresan como 401 sin filtrar al
  cliente la causa interna específica.
