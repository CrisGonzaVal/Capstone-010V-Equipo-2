-- =====================================================
-- PROYECTO APT - ERP DE INSUMOS
-- BASE DE DATOS: apt_erp
-- PostgreSQL
-- =====================================================
--
-- Esquema 3NF de 12 entidades. Solo DDL: aqui no hay TRUNCATE ni INSERT,
-- los datos de ejemplo son responsabilidad de `02_datos_semilla.sql`.
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
-- 1. INSTITUCION
-- =====================================================

CREATE TABLE institucion (
    institucion_id VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    rut VARCHAR(20),
    direccion VARCHAR(200)
);

-- =====================================================
-- 2. DEPARTAMENTO
-- =====================================================

CREATE TABLE departamento (
    departamento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_dep VARCHAR(100) NOT NULL,
    descripcion VARCHAR(200),
    institucion_id VARCHAR(20) NOT NULL,

    CONSTRAINT departamento_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

    -- Destino de la FK compuesta inventario -> departamento (Feature 008).
    CONSTRAINT departamento_institucion_uk
        UNIQUE (institucion_id, departamento_id)
);

-- =====================================================
-- 3. ROL
-- =====================================================

CREATE TABLE rol (
    rol_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre_rol VARCHAR(50) NOT NULL,
    descripcion VARCHAR(150)
);

-- =====================================================
-- 4. USUARIO
-- =====================================================

CREATE TABLE usuario (
    usuario_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE,
    departamento_id INTEGER NOT NULL,
    rol_id INTEGER NOT NULL,

    CONSTRAINT usuario_departamento_fk
        FOREIGN KEY (departamento_id)
        REFERENCES departamento(departamento_id),

    CONSTRAINT usuario_rol_fk
        FOREIGN KEY (rol_id)
        REFERENCES rol(rol_id)
);

-- =====================================================
-- 5. CATEGORIA
-- =====================================================

CREATE TABLE categoria (
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

CREATE TABLE producto (
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

CREATE TABLE inventario (
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
-- 8. MOVIMIENTO_INVENTARIO
-- =====================================================

CREATE TABLE movimiento_inventario (
    movimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_movimiento VARCHAR(20) NOT NULL,
    cantidad INTEGER NOT NULL,
    fecha_movimiento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observacion VARCHAR(250),
    inventario_id INTEGER NOT NULL,

    CONSTRAINT movimiento_inventario_fk
        FOREIGN KEY (inventario_id)
        REFERENCES inventario(inventario_id),

    CONSTRAINT movimiento_cantidad_ck
        CHECK (cantidad > 0)
);

-- =====================================================
-- 9. PRIORIDAD
-- =====================================================

CREATE TABLE prioridad (
    prioridad_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

-- =====================================================
-- 10. ESTADO_TICKET
-- =====================================================

CREATE TABLE estado_ticket (
    estado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre VARCHAR(30) NOT NULL,
    descripcion VARCHAR(100)
);

-- =====================================================
-- 11. TICKET
-- =====================================================

CREATE TABLE ticket (
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

    CONSTRAINT ticket_institucion_fk
        FOREIGN KEY (institucion_id)
        REFERENCES institucion(institucion_id),

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

CREATE TABLE detalle_ticket (
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