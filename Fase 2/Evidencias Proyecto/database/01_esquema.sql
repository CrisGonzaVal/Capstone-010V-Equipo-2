-- =====================================================
-- PROYECTO APT - ERP DE INSUMOS
-- BASE DE DATOS: apt_erp
-- PostgreSQL
-- =====================================================
--
-- Esquema 3NF de 12 entidades. Solo DDL: aqui no hay TRUNCATE ni INSERT,
-- los datos de ejemplo son responsabilidad de `02_datos_semilla.sql`.
--
-- Feature 011 (modelo organizacional): se agregan las entidades de dominio
-- `sede` y `stock_sede`, la tabla puente auxiliar `departamento_encargado` y las
-- columnas nullable `departamento.sede_id`, `usuario.sede_id`, `ticket.sede_id`
-- y `movimiento_inventario.stock_sede_id`. `movimiento_inventario.inventario_id`
-- deja de ser obligatoria para admitir los movimientos nuevos, que se enlazan por
-- `stock_sede_id`. Justificacion aprobada en docs/spec/stack.md §"Evolucion del
-- modelo organizacional e inventario por sede (Feature 011)".
--
-- Feature 013 (ciclo de vida del ticket): se agrega la entidad de dominio
-- `historial_transicion_ticket` (seccion 12b), tabla de historial inmutable
-- por esquema tenant que aqui se crea en `control` por paridad estructural del
-- DDL canonico; el constructor de tenants y la migracion operacional `013.1` la
-- replican a cada esquema. El DDL de `estado_ticket` no cambia: la quinta fila
-- del catalogo (`Anulado`) la siembra `02_datos_semilla.sql`. Sin columna
-- `institucion_id` (su aislamiento es el de su esquema). Justificacion
-- aprobada en docs/spec/stack.md §"Ciclo de vida del ticket: estado `Anulado` e
-- historial de transiciones (Feature 013)".
--
-- Feature 008: pertenencia institucional explicitamente (categoria.institucion_id,
-- producto.institucion_id) o derivada (inventario/ticket/detalle_ticket). Se
-- conservan las PK simples y se agregan claves unicas compuestas como destino de
-- FK compuestas, de modo que el esquema rechace referencias cruzadas entre
-- instituciones. Justificacion en docs/spec/stack.md §"Modelo relacional y
-- particionamiento por institucion (Feature 008)".
--
-- El prefijo `01_` es obligatorio, no decorativo: este archivo crea las tablas
-- y la semilla las trunca. PostgreSQL ejecuta los .sql de esta carpeta en orden
-- alfabetico y con ON_ERROR_STOP=1, asi que si la semilla corriera primero el
-- arranque abortaria. Ver la cabecera de `02_datos_semilla.sql`.

-- =====================================================
-- 0. ESQUEMA DE CONTROL (Feature 010)
-- =====================================================
-- Las doce tablas canonicas viven en el esquema `control` (justificacion
-- aprobada en docs/spec/stack.md seccion "Multi-tenant por esquemas PostgreSQL:
-- control y tenants"). Para que toda referencia SIN prefijo resuelva al esquema
-- de control y no a `public`, este script fija el `search_path` por defecto de
-- la base en `control, public`:
--   * la semilla (`02_`), las migraciones `98_`/`99_` y la sesion de control de
--     la aplicacion usan nombres sin prefijo y por tanto resuelven a `control`;
--   * `public` queda como ultimo recurso, de modo que una base legada (donde
--     `control` aun no existe) sigue resolviendo a `public` sin cambios.
-- El DDL de las doce entidades no cambia: solo cambia el esquema que las aloja.
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
-- docs/spec/stack.md §"Gestion del ciclo de vida institucional y capacidades
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
-- (constitucion.md §3). Tabla de negocio por esquema tenant; aqui se crea en
-- `control` por paridad estructural del DDL canonico (el constructor de
-- tenants y la migracion `013.1` la replican a cada tenant). Sin columna
-- `institucion_id`: su aislamiento es el de su esquema, con la misma defensa
-- que `movimiento_inventario` (anclada por su ticket, que ya porta la
-- institucion). Justificacion aprobada en docs/spec/stack.md §"Ciclo de vida
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
-- §"Multi-tenant por esquemas PostgreSQL: control y tenants (Feature 010)".
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