-- =====================================================
-- COMPUSTOCK ERP - ESQUEMA COMPLETO (instalacion limpia)
-- Base de datos: apt_erp
-- PostgreSQL 16
-- =====================================================
--
-- PROPOSITO
--   Crear TODA la estructura de una instalacion limpia:
--     * el esquema global `control` (19 tablas);
--     * un esquema `tenant_<slug>_<hash>` por institucion, con las 17 tablas
--       de negocio replicadas.
--   Los datos de negocio los siembra `02_datos_semilla.sql`, que corre despues.
--
-- ORDEN DE EJECUCION (no lo cambies sin leer esto)
--   PostgreSQL ejecuta los .sql de esta carpeta solo al crear el volumen, en
--   orden alfabetico y con ON_ERROR_STOP=1. `01_` va antes que `02_`; si se
--   invierte, la semilla no encuentra las tablas y el arranque aborta.
--
-- TOPOLOGIA DE TENANTS
--   La lista de instituciones que define los esquemas tenant vive en la seccion
--   "TOPOLOGIA DE TENANTS" de este archivo (4 filas en `control.institucion`).
--   Es la unica data que contiene este script: sin esa lista no se pueden crear
--   los esquemas. Si agregas una institucion, agregala aqui y siembra sus datos
--   en `02_datos_semilla.sql`.
--
-- MODELO
--   Es el modelo canonico de 15 entidades de dominio (institucion, sede,
--   departamento, rol, usuario, categoria, producto, inventario, stock_sede,
--   movimiento_inventario, prioridad, estado_ticket, ticket, detalle_ticket,
--   historial_transicion_ticket) + `departamento_encargado` auxiliar, mas las
--   tablas de control (`funcion_institucion`, `mapa_usuario_esquema`,
--   `version_esquema`). Las justificaciones de las Features 008/010/011/012/013
--   viven en docs/spec/stack.md; aqui solo esta el DDL vigente.
--
-- VERSION OBJETIVO DEL DDL
--   013.1 (`VERSION_ESQUEMA_OBJETIVO` en backend/app/core/config.py).
-- =====================================================

-- =====================================================
-- 0. ESQUEMA DE CONTROL (Feature 010)
-- =====================================================
-- Las tablas canonicas viven en el esquema `control` (justificacion
-- aprobada en docs/spec/stack.md seccion "Multi-tenant por esquemas PostgreSQL:
-- control y tenants"). Para que toda referencia SIN prefijo resuelva al esquema
-- de control y no a `public`, este script fija el `search_path` por defecto de
-- la base en `control, public`:
--   * la semilla (`02_`) y la sesion de control de la aplicacion usan nombres
--     sin prefijo y por tanto resuelven a `control`;
--   * `public` queda como ultimo recurso.
-- Los `REFERENCES` internos de cada tabla (todos locales al mismo esquema) se
-- resuelven dentro de `control` gracias a ese `search_path`.

CREATE SCHEMA IF NOT EXISTS control;

DO $search_path$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET search_path TO control, public',
        current_database()
    );
END;
$search_path$;

SET search_path TO control, public;

-- =====================================================
-- 1. INSTITUCION
-- =====================================================

-- Feature 012: `activo` es el estado de ciclo de vida del registro institucional
-- canonico (suspender/reactivar sin borrado). Vive SOLO en control; el espejo
-- tenant `institucion` lo materializa el constructor/`control_service` con dos
-- columnas (`institucion_id`, `nombre`), sin `activo`. Justificacion aprobada en
-- docs/spec/stack.md, seccion "Gestion del ciclo de vida institucional y capacidades
-- funcionales (Feature 012)".
CREATE TABLE control.institucion (
    institucion_id VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    rut VARCHAR(20),
    direccion VARCHAR(200),
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

-- =====================================================
-- 1a. FUNCION_INSTITUCION  (Feature 012, auxiliar)
-- =====================================================
-- Estructura auxiliar SOLO de control: una fila por pareja
-- `(institucion_id, funcion)` con estado `habilitada` explicito. No es entidad de
-- dominio ni catalogo configurable: el conjunto de funciones es una lista cerrada
-- del codigo (`catalogo`, `inventario`, `tickets`, `kanban`, `dashboard`,
-- `gestion_organizacional`). FK **local** a `institucion` del mismo esquema. Nunca
-- se copia a un tenant.

CREATE TABLE control.funcion_institucion (
    institucion_id VARCHAR(20) NOT NULL,
    funcion VARCHAR(50) NOT NULL,
    habilitada BOOLEAN NOT NULL,

    CONSTRAINT funcion_institucion_pk
        PRIMARY KEY (institucion_id, funcion),

    CONSTRAINT funcion_institucion_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    CONSTRAINT funcion_institucion_funcion_ck
        CHECK (funcion IN ('catalogo', 'inventario', 'tickets', 'kanban', 'dashboard', 'gestion_organizacional'))
);

-- =====================================================
-- 1b. SEDE  (Feature 011)
-- =====================================================
-- Entidad de dominio nueva. Cada sede pertenece a exactamente una institucion
-- (`institucion_id` NOT NULL) y expone la clave compuesta
-- `(institucion_id, sede_id)`, destino de la FK compuesta de `stock_sede`.
-- Se crea aqui, antes de `departamento`, porque `departamento.sede_id` la
-- referencia. La direccion es el dato organizacional propio de la sede: no se
-- infiere de `inventario.ubicacion`, que queda como dato legado.

CREATE TABLE control.sede (
    sede_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    direccion VARCHAR(200),
    institucion_id VARCHAR(20) NOT NULL,
    -- Feature 012 (AC-6/AC-11): estado logico de la sede. Desactivar no borra ni
    -- pierde historial; una base migrada parte con todas las sedes activas.
    activo BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT sede_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- Destino de la FK compuesta stock_sede -> sede (Feature 011, AC-2).
    CONSTRAINT sede_institucion_uk
        UNIQUE (institucion_id, sede_id)
);

-- =====================================================
-- 2. DEPARTAMENTO
-- =====================================================

CREATE TABLE control.departamento (
    departamento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_dep VARCHAR(100) NOT NULL,
    descripcion VARCHAR(200),
    institucion_id VARCHAR(20) NOT NULL,
    -- Feature 011 (D-5): sede del departamento. Nullable a proposito: la
    -- obligatoriedad es operativa (sin sede se rechazan las operaciones
    -- dependientes), de modo que una base migrada puede partir sin asignaciones.
    sede_id INTEGER,
    -- Feature 012 (AC-11): estado logico del departamento. Desactivar no borra ni
    -- pierde historial; una base migrada parte con todos los departamentos activos.
    activo BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT departamento_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    CONSTRAINT departamento_sede_fk
        FOREIGN KEY (sede_id)
        REFERENCES sede(sede_id),

    -- Destino de la FK compuesta inventario -> departamento (Feature 008).
    CONSTRAINT departamento_institucion_uk
        UNIQUE (institucion_id, departamento_id)
);

-- =====================================================
-- 3. ROL
-- =====================================================

CREATE TABLE control.rol (
    rol_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_rol VARCHAR(50) NOT NULL,
    descripcion VARCHAR(150)
);

-- =====================================================
-- 4. USUARIO
-- =====================================================

CREATE TABLE control.usuario (
    usuario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE,
    departamento_id INTEGER NOT NULL,
    rol_id INTEGER NOT NULL,
    -- Feature 011 (D-5/D-7): sede asignada al Bodeguero. Nullable: la
    -- obligatoriedad es operativa y un usuario que no es Bodeguero no la necesita.
    sede_id INTEGER,

    CONSTRAINT usuario_departamento_fk
        FOREIGN KEY (departamento_id)
        REFERENCES departamento(departamento_id),

    CONSTRAINT usuario_rol_fk
        FOREIGN KEY (rol_id)
        REFERENCES rol(rol_id),

    CONSTRAINT usuario_sede_fk
        FOREIGN KEY (sede_id)
        REFERENCES sede(sede_id)
);

-- =====================================================
-- 4b. DEPARTAMENTO_ENCARGADO  (Feature 011, auxiliar)
-- =====================================================
-- Tabla puente auxiliar (no es una entidad de dominio): un departamento admite
-- varios encargados y un usuario puede ser encargado de su departamento. La
-- regla de compatibilidad (usuario Solicitante, activo y del mismo departamento)
-- la valida el servicio; aqui solo vive la asociacion y su unicidad.

CREATE TABLE control.departamento_encargado (
    departamento_encargado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    departamento_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,

    CONSTRAINT departamento_encargado_departamento_fk
        FOREIGN KEY (departamento_id)
        REFERENCES departamento(departamento_id),

    CONSTRAINT departamento_encargado_usuario_fk
        FOREIGN KEY (usuario_id)
        REFERENCES usuario(usuario_id),

    CONSTRAINT departamento_encargado_uk
        UNIQUE (departamento_id, usuario_id)
);

-- =====================================================
-- 5. CATEGORIA
-- =====================================================

CREATE TABLE control.categoria (
    categoria_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_cat VARCHAR(100) NOT NULL,
    descripcion_cat VARCHAR(200),
    -- Feature 008 (D-1): cada categoria pertenece a una sola institucion.
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT categoria_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- Destino de la FK compuesta producto -> categoria (Feature 008, AC-2).
    CONSTRAINT categoria_institucion_uk
        UNIQUE (institucion_id, categoria_id)
);

-- =====================================================
-- 6. PRODUCTO
-- =====================================================

CREATE TABLE control.producto (
    producto_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    descripcion VARCHAR(250),
    unidad_medida VARCHAR(30),
    stock_minimo INTEGER NOT NULL DEFAULT 0,
    categoria_id INTEGER NOT NULL,
    -- Feature 008 (D-1): cada producto pertenece a una sola institucion.
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT producto_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- Sustituye a la FK simple producto.categoria_id -> categoria: exige que la
    -- categoria sea de la misma institucion (Feature 008, AC-2).
    CONSTRAINT producto_categoria_institucion_fk
        FOREIGN KEY (institucion_id, categoria_id)
        REFERENCES categoria(institucion_id, categoria_id),

    -- Destino de las FK compuestas inventario -> producto y
    -- detalle_ticket -> producto (Feature 008, AC-2, AC-4).
    CONSTRAINT producto_institucion_uk
        UNIQUE (institucion_id, producto_id),

    CONSTRAINT producto_stock_minimo_ck
        CHECK (stock_minimo >= 0)
);

-- =====================================================
-- 7. INVENTARIO
-- =====================================================

CREATE TABLE control.inventario (
    inventario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    ubicacion VARCHAR(100),
    departamento_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    -- Feature 008 (D-2): derivada del departamento; la puebla el servicio.
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT inventario_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- Ambas FK comparten institucion_id: obligan a que el departamento y el
    -- producto del inventario sean de la misma institucion (Feature 008, AC-2,
    -- AC-4). Sustituyen a las FK simples previas.
    CONSTRAINT inventario_departamento_institucion_fk
        FOREIGN KEY (institucion_id, departamento_id)
        REFERENCES departamento(institucion_id, departamento_id),

    CONSTRAINT inventario_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id),

    CONSTRAINT inventario_stock_ck
        CHECK (stock_actual >= 0),

    CONSTRAINT inventario_producto_departamento_uk
        UNIQUE (departamento_id, producto_id)
);

-- =====================================================
-- 7b. STOCK_SEDE  (Feature 011)
-- =====================================================
-- Entidad de dominio nueva: el saldo operativo vigente es por `(sede, producto)`
-- y sustituye al saldo departamental (que queda como registro legado). Las FKs
-- compuestas obligan a que la sede y el producto sean de la misma institucion.

CREATE TABLE control.stock_sede (
    stock_sede_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    sede_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT stock_sede_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    CONSTRAINT stock_sede_sede_institucion_fk
        FOREIGN KEY (institucion_id, sede_id)
        REFERENCES sede(institucion_id, sede_id),

    CONSTRAINT stock_sede_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id),

    CONSTRAINT stock_sede_stock_ck
        CHECK (stock_actual >= 0),

    CONSTRAINT stock_sede_sede_producto_uk
        UNIQUE (sede_id, producto_id)
);

-- =====================================================
-- 8. MOVIMIENTO_INVENTARIO
-- =====================================================

CREATE TABLE control.movimiento_inventario (
    movimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_movimiento VARCHAR(20) NOT NULL,
    cantidad INTEGER NOT NULL,
    fecha_movimiento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacion VARCHAR(250),
    -- Feature 011 (D-2): referencia historica al inventario departamental. Sus
    -- valores no se alteran, pero deja de ser obligatoria porque los movimientos
    -- nuevos se enlazan por `stock_sede_id` y dejan esta columna nula.
    inventario_id INTEGER,
    -- Referencia de los movimientos nuevos (negocio y consolidacion).
    stock_sede_id INTEGER,

    CONSTRAINT movimiento_inventario_fk
        FOREIGN KEY (inventario_id)
        REFERENCES inventario(inventario_id),

    CONSTRAINT movimiento_stock_sede_fk
        FOREIGN KEY (stock_sede_id)
        REFERENCES stock_sede(stock_sede_id),

    CONSTRAINT movimiento_cantidad_ck
        CHECK (cantidad > 0)
);

-- =====================================================
-- 9. PRIORIDAD
-- =====================================================

CREATE TABLE control.prioridad (
    prioridad_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

-- =====================================================
-- 10. ESTADO_TICKET
-- =====================================================

CREATE TABLE control.estado_ticket (
    estado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

-- =====================================================
-- 11. TICKET
-- =====================================================

CREATE TABLE control.ticket (
    ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    prioridad_id INTEGER NOT NULL,
    estado_id INTEGER NOT NULL,
    asunto VARCHAR(150) NOT NULL,
    descripcion VARCHAR(500),
    fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_cierre TIMESTAMP,
    -- Feature 008: derivada del solicitante (usuario -> departamento -> institucion);
    -- la puebla el servicio.
    institucion_id VARCHAR(20) NOT NULL,
    -- Feature 011 (D-5/AC-9): instantanea de la sede del departamento al crearse
    -- el ticket. El despacho usa esta sede aunque el departamento se reasigne
    -- despues; los tickets legados quedan nulos hasta que la migracion los asigne.
    sede_id INTEGER,

    CONSTRAINT ticket_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    CONSTRAINT ticket_sede_fk
        FOREIGN KEY (sede_id)
        REFERENCES sede(sede_id),

    CONSTRAINT ticket_usuario_fk
        FOREIGN KEY (usuario_id)
        REFERENCES usuario(usuario_id),

    CONSTRAINT ticket_prioridad_fk
        FOREIGN KEY (prioridad_id)
        REFERENCES prioridad(prioridad_id),

    CONSTRAINT ticket_estado_fk
        FOREIGN KEY (estado_id)
        REFERENCES estado_ticket(estado_id),

    -- Destino de la FK compuesta detalle_ticket -> ticket (Feature 008, AC-4).
    CONSTRAINT ticket_institucion_uk
        UNIQUE (institucion_id, ticket_id)
);

-- =====================================================
-- 12. DETALLE_TICKET
-- =====================================================

CREATE TABLE control.detalle_ticket (
    detalle_ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad_solicitada INTEGER NOT NULL,
    cantidad_entregada INTEGER NOT NULL DEFAULT 0,
    -- Feature 008: derivada del ticket; la puebla el servicio.
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT detalle_ticket_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- El detalle queda anclado a la institucion de su ticket y obligado a un
    -- producto de esa misma institucion (Feature 008, AC-4). Sustituyen a las FK
    -- simples previas.
    CONSTRAINT detalle_ticket_ticket_institucion_fk
        FOREIGN KEY (institucion_id, ticket_id)
        REFERENCES ticket(institucion_id, ticket_id),

    CONSTRAINT detalle_ticket_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id),

    CONSTRAINT detalle_cantidad_solicitada_ck
        CHECK (cantidad_solicitada > 0),

    CONSTRAINT detalle_cantidad_entregada_ck
        CHECK (cantidad_entregada >= 0)
);

-- =====================================================
-- 12b. HISTORIAL_TRANSICION_TICKET  (Feature 013)
-- =====================================================
-- Una fila por transicion del ciclo de vida del ticket (spec D-10, AC-9):
-- creacion (estado_origen_id nulo), cambio de estado de la 004, despacho de la
-- 005 y anulacion/rechazo de la 013. Es inmutable y de solo lectura por API: no
-- hay operacion de creacion/edicion/borrado fuera de las transiciones mismas, y
-- cada fila se escribe en la MISMA transaccion que el cambio que representa
-- (constitucion.md, seccion 3). Tabla de negocio por esquema tenant; aqui se crea en
-- `control` por paridad estructural del DDL canonico (el constructor de
-- tenants y la migracion `013.1` la replican a cada tenant). Sin columna
-- `institucion_id`: su aislamiento es el de su esquema, con la misma defensa
-- que `movimiento_inventario` (anclada por su ticket, que ya porta la
-- institucion). Justificacion aprobada en docs/spec/stack.md, seccion "Ciclo de vida
-- del ticket: estado `Anulado` e historial de transiciones (Feature 013)".

CREATE TABLE control.historial_transicion_ticket (
    historial_transicion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    -- Nulo SOLO en la fila de creacion del ticket (Feature 013, AC-9).
    estado_origen_id INTEGER,
    estado_destino_id INTEGER NOT NULL,
    -- Actor autenticado de la transicion.
    usuario_id INTEGER NOT NULL,
    fecha_transicion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Escala de `ticket.descripcion`. Nullable: la anulacion y el rechazo lo
    -- exigen no vacio, pero esa validacion vive en el servicio, no en el DDL.
    motivo VARCHAR(500),

    CONSTRAINT historial_transicion_ticket_ticket_fk
        FOREIGN KEY (ticket_id)
        REFERENCES ticket(ticket_id),

    CONSTRAINT historial_transicion_ticket_estado_origen_fk
        FOREIGN KEY (estado_origen_id)
        REFERENCES estado_ticket(estado_id),

    CONSTRAINT historial_transicion_ticket_estado_destino_fk
        FOREIGN KEY (estado_destino_id)
        REFERENCES estado_ticket(estado_id),

    CONSTRAINT historial_transicion_ticket_usuario_fk
        FOREIGN KEY (usuario_id)
        REFERENCES usuario(usuario_id)
);

-- =====================================================
-- FEATURE 010: CONTEXTO DE CONTROL Y VERSIONADO POR TENANT
-- =====================================================
--
-- Esta seccion es **aditiva** respecto del DDL de las doce tablas definido
-- arriba (que ahora se crea en el esquema `control`, ver seccion 0). Agrega las
-- estructuras auxiliares del esquema global de control y la tabla de version que
-- cada esquema tenant materializa. Justificacion aprobada en docs/spec/stack.md
-- seccion "Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)".
--
-- o `mapa_usuario_esquema` vive en el esquema de control y traduce el correo
--   primario verificado a un esquema tenant (no es una de las doce entidades
--   3NF). `institucion_id` mantiene una FK **local** al registro de
--   `institucion` del mismo esquema (control); nunca hay FK cross-schema.
-- o `version_esquema` es la marca de version del DDL por esquema: exactamente
--   una fila vigente. En la instalacion limpia se materializa en `control` (el
--   esquema canonico de este script); cada tenant tiene la suya, creada por el
--   aprovisionamiento y por la migracion.

CREATE TABLE control.mapa_usuario_esquema (
    -- Correo primario verificado; clave de la identidad local: un correo no
    -- puede apuntar a mas de un esquema.
    correo VARCHAR(150) PRIMARY KEY,
    -- Registro de institucion del mismo esquema (control). FK local, sin
    -- cross-schema.
    institucion_id VARCHAR(20) NOT NULL,
    -- Nombre PostgreSQL del esquema tenant, generado/validado en servidor.
    nombre_esquema VARCHAR(63) NOT NULL,
    -- Solo las asociaciones activas resuelven solicitudes.
    activo BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT mapa_usuario_esquema_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES control.institucion (institucion_id)
);

CREATE TABLE control.version_esquema (
    version_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Token de version objetivo del DDL (VERSION_ESQUEMA_OBJETIVO). No nulo.
    version VARCHAR(20) NOT NULL,
    -- Instante del ultimo registro exitoso.
    actualizada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- TOPOLOGIA DE TENANTS  (un esquema por institucion)
-- =====================================================
-- Las cuatro instituciones de la instalacion de QA. Esta lista es la
-- TOPOLOGIA de los esquemas `tenant_*`: el bloque siguiente la recorre y crea
-- un esquema por cada fila. Es la unica data de este archivo; el resto de los
-- datos (capacidades, sedes, usuarios, catalogo, stock, tickets) los siembra
-- `02_datos_semilla.sql`.
--
-- Si agregas una institucion aqui, agrega tambien sus datos en `02_`; el
-- constructor de tenants de `02_` recorre esta misma tabla. Las FK de
-- `funcion_institucion` y `mapa_usuario_esquema` apuntan a este registro.
--
-- `activo` toma su DEFAULT TRUE; no se nombra la columna.

INSERT INTO control.institucion (institucion_id, nombre, rut, direccion) VALUES
('INST-001', 'Instituto Profesional Los Alpes', '65.432.100-9', 'Av. Providencia 1234, Santiago'),
('INST-002', 'Centro de Salud Familiar Norte', '65.887.230-1', 'Calle Los Robles 45, Maipu'),
('INST-003', 'Corporacion Educacional Cordillera', '77.120.540-3', 'Camino La Ladera 890, Lo Barnechea'),
('INST-004', 'Municipalidad de Talagante', '65.998.720-K', 'Plaza de Armas s/n, Talagante');

-- Nombre determinista del esquema tenant: espejo EXACTO en SQL de
-- `app.services.tenant_service.nombre_esquema_para_institucion`
-- (`tenant_` + slug ASCII del ID + `_` + primeros 8 hex del SHA-256).
-- La misma funcion se repite en `02_datos_semilla.sql` porque ambos scripts
-- corren en sesiones distintas y `pg_temp` no se comparte entre archivos.
CREATE OR REPLACE FUNCTION pg_temp.nombre_esquema_tenant(p_institucion_id text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $nombre$
    SELECT 'tenant_'
        || left(
             btrim(
               regexp_replace(
                 lower(
                   regexp_replace(
                     normalize(btrim(p_institucion_id), NFKD),
                     '[^[:ascii:]]', '', 'g'
                   )
                 ),
                 '[^a-z0-9]', '_', 'g'
               ),
               '_'
             ),
             47
           )
        || '_'
        || substr(encode(sha256(convert_to(btrim(p_institucion_id), 'UTF8')), 'hex'), 1, 8);
$nombre$;

-- Crea un esquema tenant por cada institucion de la topologia. Las plantillas
-- son identicas al DDL de `control` de las 17 tablas de negocio, con las FKs
-- calificadas al mismo esquema (sin referencias cross-schema). El espejo
-- `institucion` se limita a dos columnas (`institucion_id`, `nombre`): `rut`,
-- `direccion`, `activo` y `funcion_institucion` viven SOLO en control.
DO $tenants$
DECLARE
    v_institucion_id text;
    v_esquema text;
    v_plantilla text;
    v_plantillas text[];
    v_conteo integer;
BEGIN
    v_plantillas := ARRAY[
        'CREATE TABLE %1$I.institucion ('
        'institucion_id VARCHAR(20) PRIMARY KEY, '
        'nombre VARCHAR(150) NOT NULL)',

        'CREATE TABLE %1$I.sede ('
        'sede_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(100) NOT NULL, '
        'direccion VARCHAR(200), '
        'institucion_id VARCHAR(20) NOT NULL, '
        'activo BOOLEAN NOT NULL DEFAULT TRUE, '
        'CONSTRAINT sede_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT sede_institucion_uk UNIQUE (institucion_id, sede_id))',

        'CREATE TABLE %1$I.departamento ('
        'departamento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre_dep VARCHAR(100) NOT NULL, '
        'descripcion VARCHAR(200), '
        'institucion_id VARCHAR(20) NOT NULL, '
        'sede_id INTEGER, '
        'activo BOOLEAN NOT NULL DEFAULT TRUE, '
        'CONSTRAINT departamento_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT departamento_sede_fk FOREIGN KEY (sede_id) '
        'REFERENCES %1$I.sede(sede_id), '
        'CONSTRAINT departamento_institucion_uk UNIQUE (institucion_id, departamento_id))',

        'CREATE TABLE %1$I.rol ('
        'rol_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre_rol VARCHAR(50) NOT NULL, '
        'descripcion VARCHAR(150))',

        'CREATE TABLE %1$I.usuario ('
        'usuario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(100) NOT NULL, '
        'apellido VARCHAR(100) NOT NULL, '
        'correo VARCHAR(150) NOT NULL UNIQUE, '
        'departamento_id INTEGER NOT NULL, '
        'rol_id INTEGER NOT NULL, '
        'sede_id INTEGER, '
        'CONSTRAINT usuario_departamento_fk FOREIGN KEY (departamento_id) '
        'REFERENCES %1$I.departamento(departamento_id), '
        'CONSTRAINT usuario_rol_fk FOREIGN KEY (rol_id) REFERENCES %1$I.rol(rol_id), '
        'CONSTRAINT usuario_sede_fk FOREIGN KEY (sede_id) REFERENCES %1$I.sede(sede_id))',

        'CREATE TABLE %1$I.departamento_encargado ('
        'departamento_encargado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'departamento_id INTEGER NOT NULL, '
        'usuario_id INTEGER NOT NULL, '
        'CONSTRAINT departamento_encargado_departamento_fk FOREIGN KEY (departamento_id) '
        'REFERENCES %1$I.departamento(departamento_id), '
        'CONSTRAINT departamento_encargado_usuario_fk FOREIGN KEY (usuario_id) '
        'REFERENCES %1$I.usuario(usuario_id), '
        'CONSTRAINT departamento_encargado_uk UNIQUE (departamento_id, usuario_id))',

        'CREATE TABLE %1$I.categoria ('
        'categoria_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre_cat VARCHAR(100) NOT NULL, '
        'descripcion_cat VARCHAR(200), '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT categoria_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT categoria_institucion_uk UNIQUE (institucion_id, categoria_id))',

        'CREATE TABLE %1$I.producto ('
        'producto_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(150) NOT NULL, '
        'descripcion VARCHAR(250), '
        'unidad_medida VARCHAR(30), '
        'stock_minimo INTEGER NOT NULL DEFAULT 0, '
        'categoria_id INTEGER NOT NULL, '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT producto_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT producto_categoria_institucion_fk FOREIGN KEY (institucion_id, categoria_id) '
        'REFERENCES %1$I.categoria(institucion_id, categoria_id), '
        'CONSTRAINT producto_institucion_uk UNIQUE (institucion_id, producto_id), '
        'CONSTRAINT producto_stock_minimo_ck CHECK (stock_minimo >= 0))',

        'CREATE TABLE %1$I.inventario ('
        'inventario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'stock_actual INTEGER NOT NULL DEFAULT 0, '
        'ubicacion VARCHAR(100), '
        'departamento_id INTEGER NOT NULL, '
        'producto_id INTEGER NOT NULL, '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT inventario_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT inventario_departamento_institucion_fk FOREIGN KEY (institucion_id, departamento_id) '
        'REFERENCES %1$I.departamento(institucion_id, departamento_id), '
        'CONSTRAINT inventario_producto_institucion_fk FOREIGN KEY (institucion_id, producto_id) '
        'REFERENCES %1$I.producto(institucion_id, producto_id), '
        'CONSTRAINT inventario_stock_ck CHECK (stock_actual >= 0), '
        'CONSTRAINT inventario_producto_departamento_uk UNIQUE (departamento_id, producto_id))',

        'CREATE TABLE %1$I.stock_sede ('
        'stock_sede_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'stock_actual INTEGER NOT NULL DEFAULT 0, '
        'sede_id INTEGER NOT NULL, '
        'producto_id INTEGER NOT NULL, '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT stock_sede_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT stock_sede_sede_institucion_fk FOREIGN KEY (institucion_id, sede_id) '
        'REFERENCES %1$I.sede(institucion_id, sede_id), '
        'CONSTRAINT stock_sede_producto_institucion_fk FOREIGN KEY (institucion_id, producto_id) '
        'REFERENCES %1$I.producto(institucion_id, producto_id), '
        'CONSTRAINT stock_sede_stock_ck CHECK (stock_actual >= 0), '
        'CONSTRAINT stock_sede_sede_producto_uk UNIQUE (sede_id, producto_id))',

        'CREATE TABLE %1$I.movimiento_inventario ('
        'movimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'tipo_movimiento VARCHAR(20) NOT NULL, '
        'cantidad INTEGER NOT NULL, '
        'fecha_movimiento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
        'observacion VARCHAR(250), '
        'inventario_id INTEGER, '
        'stock_sede_id INTEGER, '
        'CONSTRAINT movimiento_inventario_fk FOREIGN KEY (inventario_id) '
        'REFERENCES %1$I.inventario(inventario_id), '
        'CONSTRAINT movimiento_stock_sede_fk FOREIGN KEY (stock_sede_id) '
        'REFERENCES %1$I.stock_sede(stock_sede_id), '
        'CONSTRAINT movimiento_cantidad_ck CHECK (cantidad > 0))',

        'CREATE TABLE %1$I.prioridad ('
        'prioridad_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(30) NOT NULL, '
        'descripcion VARCHAR(100))',

        'CREATE TABLE %1$I.estado_ticket ('
        'estado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(30) NOT NULL, '
        'descripcion VARCHAR(100))',

        'CREATE TABLE %1$I.ticket ('
        'ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'usuario_id INTEGER NOT NULL, '
        'prioridad_id INTEGER NOT NULL, '
        'estado_id INTEGER NOT NULL, '
        'asunto VARCHAR(150) NOT NULL, '
        'descripcion VARCHAR(500), '
        'fecha_creacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
        'fecha_cierre TIMESTAMP, '
        'institucion_id VARCHAR(20) NOT NULL, '
        'sede_id INTEGER, '
        'CONSTRAINT ticket_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT ticket_sede_fk FOREIGN KEY (sede_id) REFERENCES %1$I.sede(sede_id), '
        'CONSTRAINT ticket_usuario_fk FOREIGN KEY (usuario_id) REFERENCES %1$I.usuario(usuario_id), '
        'CONSTRAINT ticket_prioridad_fk FOREIGN KEY (prioridad_id) REFERENCES %1$I.prioridad(prioridad_id), '
        'CONSTRAINT ticket_estado_fk FOREIGN KEY (estado_id) REFERENCES %1$I.estado_ticket(estado_id), '
        'CONSTRAINT ticket_institucion_uk UNIQUE (institucion_id, ticket_id))',

        'CREATE TABLE %1$I.detalle_ticket ('
        'detalle_ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'ticket_id INTEGER NOT NULL, '
        'producto_id INTEGER NOT NULL, '
        'cantidad_solicitada INTEGER NOT NULL, '
        'cantidad_entregada INTEGER NOT NULL DEFAULT 0, '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT detalle_ticket_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT detalle_ticket_ticket_institucion_fk FOREIGN KEY (institucion_id, ticket_id) '
        'REFERENCES %1$I.ticket(institucion_id, ticket_id), '
        'CONSTRAINT detalle_ticket_producto_institucion_fk FOREIGN KEY (institucion_id, producto_id) '
        'REFERENCES %1$I.producto(institucion_id, producto_id), '
        'CONSTRAINT detalle_cantidad_solicitada_ck CHECK (cantidad_solicitada > 0), '
        'CONSTRAINT detalle_cantidad_entregada_ck CHECK (cantidad_entregada >= 0))',

        'CREATE TABLE %1$I.historial_transicion_ticket ('
        'historial_transicion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'ticket_id INTEGER NOT NULL, '
        'estado_origen_id INTEGER, '
        'estado_destino_id INTEGER NOT NULL, '
        'usuario_id INTEGER NOT NULL, '
        'fecha_transicion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
        'motivo VARCHAR(500), '
        'CONSTRAINT historial_transicion_ticket_ticket_fk '
        'FOREIGN KEY (ticket_id) REFERENCES %1$I.ticket(ticket_id), '
        'CONSTRAINT historial_transicion_ticket_estado_origen_fk '
        'FOREIGN KEY (estado_origen_id) REFERENCES %1$I.estado_ticket(estado_id), '
        'CONSTRAINT historial_transicion_ticket_estado_destino_fk '
        'FOREIGN KEY (estado_destino_id) REFERENCES %1$I.estado_ticket(estado_id), '
        'CONSTRAINT historial_transicion_ticket_usuario_fk '
        'FOREIGN KEY (usuario_id) REFERENCES %1$I.usuario(usuario_id))',

        'CREATE TABLE %1$I.version_esquema ('
        'version_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'version VARCHAR(20) NOT NULL, '
        'actualizada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'
    ];

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format('CREATE SCHEMA %I', v_esquema);
        FOREACH v_plantilla IN ARRAY v_plantillas LOOP
            EXECUTE format(v_plantilla, v_esquema);
        END LOOP;

        -- Fail-closed: el tenant debe tener exactamente las 17 tablas de negocio.
        SELECT count(*) INTO v_conteo
        FROM information_schema.tables
        WHERE table_schema = v_esquema
          AND table_type = 'BASE TABLE';
        IF v_conteo <> 17 THEN
            RAISE EXCEPTION
                '01: el tenant % tiene % tabla(s) (esperadas 17).',
                v_esquema, v_conteo;
        END IF;
        RAISE NOTICE '01: tenant % creado con 17 tablas.', v_esquema;
    END LOOP;
END;
$tenants$;