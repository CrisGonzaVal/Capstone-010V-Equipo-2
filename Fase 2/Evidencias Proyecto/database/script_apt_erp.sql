-- =====================================================
-- PROYECTO APT - ERP DE INSUMOS
-- BASE DE DATOS: apt_erp
-- PostgreSQL
-- =====================================================

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
        REFERENCES institucion(institucion_id)
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
    password VARCHAR(255) NOT NULL,
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
    descripcion_cat VARCHAR(200)
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

    CONSTRAINT producto_categoria_fk
        FOREIGN KEY (categoria_id)
        REFERENCES categoria(categoria_id),

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

    CONSTRAINT inventario_departamento_fk
        FOREIGN KEY (departamento_id)
        REFERENCES departamento(departamento_id),

    CONSTRAINT inventario_producto_fk
        FOREIGN KEY (producto_id)
        REFERENCES producto(producto_id),

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

    CONSTRAINT ticket_usuario_fk
        FOREIGN KEY (usuario_id)
        REFERENCES usuario(usuario_id),

    CONSTRAINT ticket_prioridad_fk
        FOREIGN KEY (prioridad_id)
        REFERENCES prioridad(prioridad_id),

    CONSTRAINT ticket_estado_fk
        FOREIGN KEY (estado_id)
        REFERENCES estado_ticket(estado_id)
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

    CONSTRAINT detalle_ticket_ticket_fk
        FOREIGN KEY (ticket_id)
        REFERENCES ticket(ticket_id),

    CONSTRAINT detalle_ticket_producto_fk
        FOREIGN KEY (producto_id)
        REFERENCES producto(producto_id),

    CONSTRAINT detalle_cantidad_solicitada_ck
        CHECK (cantidad_solicitada > 0),

    CONSTRAINT detalle_cantidad_entregada_ck
        CHECK (cantidad_entregada >= 0)
);