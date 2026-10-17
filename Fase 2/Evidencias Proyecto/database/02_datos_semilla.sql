-- =====================================================
-- COMPUSTOCK ERP - DATOS SEMILLA
-- Base de datos: apt_erp
-- PostgreSQL
-- =====================================================
--
-- PROPOSITO
--   Pobla la base con datos de ejemplo para QA manual y pruebas.
--   Este script NO define el esquema: eso vive en `01_esquema.sql`.
--   Aqui solo hay TRUNCATE + INSERT, nunca ALTER/CREATE/DROP.
--
-- ORDEN DE EJECUCION (no lo cambies sin leer esto)
--   Los .sql de esta carpeta los ejecuta PostgreSQL solo al crear el volumen,
--   y los recorre en ORDEN ALFABETICO. Este archivo empieza con TRUNCATE sobre
--   las 12 tablas, asi que exige que `01_esquema.sql` ya exista: por eso lleva
--   el prefijo numerico. Con los nombres viejos (`datos_semilla.sql` para la
--   semilla y `script_apt_erp.sql` —hoy `database/01_esquema.sql`— para el
--   esquema) la "d" sortea antes que la "s", la semilla corria
--   contra un esquema inexistente y, con ON_ERROR_STOP=1, abortaba todo el
--   arranque. Si renuevas un nombre, revisa que no invierta el orden.
--   Corre antes que `98_migracion_particionamiento_institucional.sql` y
--   `99_migracion_retiro_password.sql`, que son no-op sobre una base nueva.
--
-- ESQUEMA (Feature 010)
--   Las doce tablas canonicas viven en el esquema `control` (ver `01_esquema.sql`
--   seccion 0). Este script las referencia sin prefijo: el `search_path` de la
--   base apunta a `control, public`, de modo que resuelven a `control`; en una
--   base legada sin `control` seguirian resolviendo a `public`.
--
-- USO
--   Automatica: al crear el volumen por primera vez (`docker compose up -d db`
--   con el volumen vacio). No hay que correrla a mano en una maquina nueva.
--
--   RESET DEL ENTORNO DE QA: se hace RECREANDO EL VOLUMEN, no reejecutando esta
--   semilla. Desde la raiz del proyecto:
--     docker compose -f docker-compose.yml down -v
--     docker compose -f docker-compose.yml up -d db
--   No existe un script de reset. Motivo: la GUARDIA FAIL-CLOSED de abajo
--   (seccion 0a) aborta si la base ya tiene filas, de modo que esta semilla
--   destructiva solo corre sobre una base genuinamente limpia. Recrear el
--   volumen es la unica forma inherentemente segura de volver a sembrar.
--
--   En PowerShell el pipe (`Get-Content -Raw | docker exec -i ...`) mete el
--   contenido por la codificacion de la consola y destruye los acentos: se
--   guardan como "??". Usa `cmd /c` con la redireccion, que copia bytes crudos.
--   Este archivo es ASCII puro justamente para que el problema no aparezca.
--
--   El TRUNCATE inicial limpia las 12 tablas y reinicia las secuencias
--   GENERATED ALWAYS AS IDENTITY, de modo que los ids siempre son los mismos y
--   los datos son reproducibles. No es idempotente sobre una base ya sembrada:
--   la guardia aborta (ver seccion 0a).
--
-- FEATURE 008 - PARTICIONAMIENTO POR INSTITUCION
--   La semilla deja la base en estado "ya particionada", de modo que `98_` sea
--   un no-op sobre instalacion nueva (ver `01_esquema.sql` y
--   docs/spec/stack.md, seccion "Modelo relacional y particionamiento por
--   institucion"). Consecuencias en este archivo:
--     - `categoria` y `producto` llevan `institucion_id` explicito (D-1).
--     - `inventario`, `ticket` y `detalle_ticket` derivan su institucion del
--       departamento / solicitante / ticket respectivamente (D-2).
--     - Ninguna referencia cruza instituciones: todo producto de una
--       institucion se inventaria en un departamento de ESA institucion, y todo
--       ticket/detalle usa solicitante y productos de su misma institucion.
--       Las FK compuestas del DDL rechazarian lo contrario.
--     - `rol`, `prioridad` y `estado_ticket` NO llevan institucion: siguen
--       globales y compartidos por las cuatro instituciones (D-5, AC-3).
--   Se conservan las CUATRO instituciones y sus departamentos/usuarios. Las
--   instituciones INST-001 y INST-002 quedan "completas" (departamentos,
--   usuarios, catalogo, stock, movimientos y tickets). INST-003 e INST-004
--   conservan sus departamentos y usuarios. Los nombres repetidos entre
--   instituciones ("Papeleria", "Resma Carta 75g A4", ...) son HOMONIMOS
--   DELIBERADOS: filas independientes con ids y stock distintos (AC-1).
--
-- CONVENCION DE IDs
--   Los INSERT declaran el id de forma explicita (`OVERRIDING SYSTEM VALUE`)
--   para que el QA manual pueda referenciar filas concretas. Eso obliga a
--   sincronizar las secuencias al final (seccion 14): si no, el primer POST
--   autogenerado choca con el id 1 y devuelve HTTP 500.
--
-- RESTRICCION - estado_ticket
--   El servicio de tickets reconoce el estado de cierre por NOMBRE
--   (`nombre.casefold() == "cerrado"`), nunca por un id fijo (Feature 004):
--   mover "Cerrado" de estado_id no rompe el sellado de `ticket.fecha_cierre`.
--   El id explicito de estos INSERTs se conserva solo para que el QA manual
--   pueda referenciar filas concretas.
--
-- RESTRICCION - inventario
--   `inventario` tiene UNIQUE (departamento_id, producto_id): cada producto se
--   ubica en un departamento distinto dentro de su institucion.
--
-- =====================================================

-- =====================================================
-- 0a. GUARDIA FAIL-CLOSED (Feature 010, T10)
-- =====================================================
-- Esta semilla es destructiva (TRUNCATE + INSERT). Para no confundir una base
-- real o ya sembrada con un entorno descartable, ABORTA antes del primer
-- TRUNCATE si detecta cualquier fila en las doce tablas canonicas, en
-- `mapa_usuario_esquema` o en `version_esquema` (criterio aprobado en
-- T8a-hallazgos-docker-initdb.md section 5). La condicion es una propiedad de
-- la base calculada en el servidor: no la aporta el cliente ni un parametro, y
-- ante duda cierra (aborta). El reset de QA de una base existente NO se hace
-- con esta semilla, sino recreando el volumen (`docker compose down -v`).

SET search_path TO control, public;

DO $guardia$
DECLARE
    v_total  bigint;
    v_conteo bigint;
    v_registro regclass;
BEGIN
    -- Doce tablas canonicas: se cuentan sin prefijo (resuelven a `control` o, en
    -- una base legada, a `public`). Si alguna no existiera, la consulta falla y
    -- el arranque aborta: tambien cierra.
    SELECT
        (SELECT count(*) FROM detalle_ticket)
      + (SELECT count(*) FROM movimiento_inventario)
      + (SELECT count(*) FROM ticket)
      + (SELECT count(*) FROM inventario)
      + (SELECT count(*) FROM producto)
      + (SELECT count(*) FROM categoria)
      + (SELECT count(*) FROM usuario)
      + (SELECT count(*) FROM rol)
      + (SELECT count(*) FROM departamento)
      + (SELECT count(*) FROM prioridad)
      + (SELECT count(*) FROM estado_ticket)
      + (SELECT count(*) FROM institucion)
    INTO v_total;

    -- Auxiliares: se suman solo si existen en la base (en una base legada
    -- anterior a la Feature 010 pueden no estar).
    v_registro := to_regclass('mapa_usuario_esquema');
    IF v_registro IS NOT NULL THEN
        EXECUTE format('SELECT count(*) FROM %s', v_registro) INTO v_conteo;
        v_total := v_total + v_conteo;
    END IF;

    v_registro := to_regclass('version_esquema');
    IF v_registro IS NOT NULL THEN
        EXECUTE format('SELECT count(*) FROM %s', v_registro) INTO v_conteo;
        v_total := v_total + v_conteo;
    END IF;

    IF v_total > 0 THEN
        RAISE EXCEPTION
            'Semilla QA abortada: la base ya contiene % fila(s) de negocio/control/version; no se ejecuta ningun TRUNCATE. Reset QA = recrear el volumen (docker compose down -v).',
            v_total;
    END IF;

    RAISE NOTICE 'Semilla QA: base limpia (0 filas de negocio/control/version), se permite continuar.';
END;
$guardia$;

-- =====================================================
-- 0. LIMPIEZA (orden inverso de dependencias)
-- =====================================================
-- CASCADE evita tener que declarar el orden a mano; RESTART IDENTITY
-- reinicia las secucciones GENERATED ALWAYS AS IDENTITY de Postgres 16.

TRUNCATE TABLE detalle_ticket, movimiento_inventario, ticket, inventario,
    producto, categoria, usuario, rol, departamento, prioridad,
    estado_ticket, institucion
RESTART IDENTITY CASCADE;

-- =====================================================
-- 1. INSTITUCION  (PK VARCHAR, no identity -> valor fijo)
-- =====================================================
-- Varias sedes decentralizadas: el caso de uso que motiva el proyecto.
-- Las cuatro se conservan (AC-1). INST-001 e INST-002 quedan completas.

INSERT INTO institucion (institucion_id, nombre, rut, direccion) VALUES
('INST-001', 'Instituto Profesional Los Alpes', '65.432.100-9', 'Av. Providencia 1234, Santiago'),
('INST-002', 'Centro de Salud Familiar Norte', '65.887.230-1', 'Calle Los Robles 45, Maipu'),
('INST-003', 'Corporacion Educacional Cordillera', '77.120.540-3', 'Camino La Ladera 890, Lo Barnechea'),
('INST-004', 'Municipalidad de Talagante', '65.998.720-K', 'Plaza de Armas s/n, Talagante');

-- =====================================================
-- 2. DEPARTAMENTO  (10 filas)
-- =====================================================
-- INST-001 aporta 7 departamentos (1..7); INST-002 el 8; INST-003 el 9;
-- INST-004 el 10. Los usuarios y el ambito se derivan de aqui.

INSERT INTO departamento (departamento_id, nombre_dep, descripcion, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Direccion',              'Direccion_general y planificacion',       'INST-001'),
(2,  'Secretaria',             'Recepcion, correspondencia y agenda',     'INST-001'),
(3,  'Administracion',         'Pagos, compras y contabilidad',            'INST-001'),
(4,  'RRHH',                   'Seleccion y remuneraciones y contratos',    'INST-001'),
(5,  'Docencia',               'Coordinacion de salas/material didactico',  'INST-001'),
(6,  'Biblioteca',             'Catalogacion y prestamo de material',      'INST-001'),
(7,  'Servicios Generales',    'Mantenimiento, aseo y seguridad',          'INST-001'),
(8,  'AtencionPrimaria',       'Recepcion de pacientes y fichas',         'INST-002'),
(9,  'CoordinacionAcademica',  'Programacion de cursos y matriculas',      'INST-003'),
(10, 'OficinaGeneral',         'Oficina de Partes Municipal',                'INST-004');

-- =====================================================
-- 3. ROL  (4 filas)  [GLOBAL, sin institucion - D-5/AC-3]
-- =====================================================
-- Los tres actores del sistema mas superadmin, segun AGENTS.md seccion 2.

INSERT INTO rol (rol_id, nombre_rol, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Superadmin',        'Administrador global de la plataforma SaaS'),
(2, 'Administrador',     'Gestiona usuarios, departamentos y catalogo maestro'),
(3, 'Bodeguero',         'Gestiona stock fisico y despacha pedidos aprobados'),
(4, 'Solicitante',       'Funcionario que consulta stock y emite tickets');

-- =====================================================
-- 4. USUARIO  (10 filas)
-- =====================================================
-- Clerk es la unica autoridad de autenticacion (Feature 006): el usuario local
-- no guarda credencial alguna. El vinculo con Clerk se resuelve por `correo`
-- (UNIQUE) contra el correo primario verificado, no por contrasena.
-- La institucion del usuario NO se guarda aqui: se deriva de su departamento.

INSERT INTO usuario (usuario_id, nombre, apellido, correo, departamento_id, rol_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Camila',   'Fernandez', 'camila.fernandez@losalpes.cl',   1, 2),
(2,  'Diego',    'Munoz',     'diego.munoz@losalpes.cl',       2, 4),
(3,  'Valentina', 'Reyes',     'valentina.reyes@losalpes.cl',   3, 2),
(4,  'Sebastian','Gutierrez', 'sebastian.gutierrez@losalpes.cl', 4, 2),
(5,  'Isabel',   'Contreras', 'isabel.contreras@losalpes.cl',  5, 4),
(6,  'Andres',   'Vargas',    'andres.vargas@losalpes.cl',     6, 3),
(7,  'Marcela',  'Nunez',     'marcela.nunez@losalpes.cl',     7, 3),
(8,  'Felipe',   'Soto',      'felipe.soto@cfsnorte.cl',       8, 4),
(9,  'Carla',    'Mancilla',  'carla.mancilla@cordillera.cl',  9, 4),
(10, 'Andres',   'Pino',      'andres.pino@talagante.cl',      10, 2);

-- =====================================================
-- 5. CATEGORIA  (10 filas)
-- =====================================================
-- Catalogo de insumos de ofimatica, AHORA por institucion (D-1).
--   INST-001 -> categorias 1..6
--   INST-002 -> categorias 7..10
-- HOMONIMOS DELIBERADOS: 'Papeleria' existe con id 1 (INST-001) y con id 7
-- (INST-002); 'Toner y Cartuchos' con id 2 (INST-001) y 8 (INST-002);
-- 'Organizacion' con id 4 (INST-001) y 10 (INST-002). Son filas independientes.

INSERT INTO categoria (categoria_id, nombre_cat, descripcion_cat, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Papeleria',           'Hojas, resmas y sobres',                'INST-001'),
(2,  'Toner y Cartuchos',   'Consumibles de impresion',              'INST-001'),
(3,  'Escritura',           'Lapices, marcadores y rotuladores',     'INST-001'),
(4,  'Organizacion',        'Folders, archivadores y separadores',   'INST-001'),
(5,  'Oficina',             'Clip, fasteners y consumibles',         'INST-001'),
(6,  'Limpieza',            'Productos de aseo y sanitizacion',      'INST-001'),
(7,  'Papeleria',           'Hojas, resmas y sobres',                'INST-002'),
(8,  'Toner y Cartuchos',   'Consumibles de impresion',              'INST-002'),
(9,  'Insumos Clinicos',    'Guantes, gasas y material de atencion', 'INST-002'),
(10, 'Organizacion',        'Folders, archivadores y separadores',   'INST-002');

-- =====================================================
-- 6. PRODUCTO  (14 filas)
-- =====================================================
-- Cada producto pertenece a la institucion de su categoria (FK compuesta
-- producto(institucion_id, categoria_id) -> categoria(institucion_id, categoria_id)).
--   INST-001 -> productos 1..10 (categorias 1..6)
--   INST-002 -> productos 11..14 (categorias 7..10)
-- HOMONIMOS DELIBERADOS entre instituciones (mismo `nombre`):
--   'Resma Carta 75g A4'  -> prod 1 (INST-001) y prod 11 (INST-002)
--   'Toner HP 26A Negro'  -> prod 2 (INST-001) y prod 12 (INST-002)
--   'Folder Manila Carta' -> prod 3 (INST-001) y prod 14 (INST-002)
-- Para INST-001 tres productos quedan por DEBAJO de su stock_minimo a proposito,
-- para que el dashboard muestre alertas reales en el QA manual:
--   producto 7 (Toner Negro 26A Comp.) -> 3 < 10
--   producto 8 (Grapadora Estandar)    -> 1 < 5
--   producto 9 (Rotulador Marcador)    -> 6 < 12

INSERT INTO producto (producto_id, nombre, descripcion, unidad_medida, stock_minimo, categoria_id, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Resma Carta 75g A4',      'Resma de 500 hojas tamano carta',          'RESMA',  20, 1,  'INST-001'),
(2,  'Toner HP 26A Negro',      'Cartucho de toner negro original HP26A',   'UNIDAD', 10, 2,  'INST-001'),
(3,  'Folder Manila Carta',     'Carpeta de cartulina tamano carta',        'UNIDAD', 25, 4,  'INST-001'),
(4,  'Boligrafo Bic Cristal',   'Boligrafo punta fina color negro',         'UNIDAD', 30, 3,  'INST-001'),
(5,  'Clip Metrico 33mm',       'Clip de metal de 33mm en caja x100',       'CAJA',   15, 5,  'INST-001'),
(6,  'Cinta Adhesiva 48mm',     'Cinta transparente de 48mm x 100m',        'ROLLO',  12, 6,  'INST-001'),
(7,  'Toner Negro 26A Comp.',   'Cartucho compatible negro para HP26A',     'UNIDAD', 10, 2,  'INST-001'),
(8,  'Grapadora Estandar',      'Grapadora de escritorio con grapa 24/6',   'UNIDAD',  5, 5,  'INST-001'),
(9,  'Rotulador Marcador',      'Rotulador permanente punta gruesa',        'UNIDAD', 12, 3,  'INST-001'),
(10, 'Papel Premium A4',        'Papel de presentacion alto gramaje',       'RESMA',  10, 1,  'INST-001'),
(11, 'Resma Carta 75g A4',      'Resma de 500 hojas tamano carta',          'RESMA',  20, 7,  'INST-002'),
(12, 'Toner HP 26A Negro',      'Cartucho de toner negro original HP26A',   'UNIDAD', 10, 8,  'INST-002'),
(13, 'Guantes de Latex M',      'Caja de guantes de latex talla M',         'CAJA',   40, 9,  'INST-002'),
(14, 'Folder Manila Carta',     'Carpeta de cartulina tamano carta',        'UNIDAD', 25, 10, 'INST-002');

-- =====================================================
-- 7. INVENTARIO  (14 filas)
-- =====================================================
-- `institucion_id` se deriva del departamento (D-2) y el producto debe ser de
-- esa misma institucion (FK compuesta). UNIQUE (departamento_id, producto_id):
-- cada producto va en un departamento distinto.
--   INST-001 -> inventarios 1..10, departamentos 1,2,5,6,7
--   INST-002 -> inventarios 11..14, departamento 8
-- Stock diferenciable entre homonimos: prod 1 (INST-001) = 50 vs
-- prod 11 (INST-002) = 12; prod 2 = 18 vs prod 12 = 9; prod 3 = 200 vs
-- prod 14 = 60. El stock de una institucion nunca se usa para la otra (AC-1).

INSERT INTO inventario (inventario_id, stock_actual, ubicacion, departamento_id, producto_id, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,   50, 'Bodega Central - Estante A1', 7,  1,  'INST-001'),
(2,   18, 'Bodega Central - Estante A2', 7,  2,  'INST-001'),
(3,  200, 'Bodega Central - Estante C1', 6,  3,  'INST-001'),
(4,  150, 'Bodega Central - Estante C2', 6,  4,  'INST-001'),
(5,   35, 'Bodega Central - Estante D1', 6,  5,  'INST-001'),
(6,   48, 'Bodega Central - Estante D2', 1,  6,  'INST-001'),
(7,    3, 'Bodega Central - Estante B2', 7,  7,  'INST-001'),
(8,    1, 'Bodega Central - Estante E1', 5,  8,  'INST-001'),
(9,    6, 'Bodega Central - Estante E2', 2,  9,  'INST-001'),
(10,  45, 'Bodega Central - Estante F1', 2,  10, 'INST-001'),
(11,  12, 'Bodega CFS Norte - Estante N1', 8, 11, 'INST-002'),
(12,   9, 'Bodega CFS Norte - Estante N2', 8, 12, 'INST-002'),
(13,   8, 'Bodega CFS Norte - Estante N3', 8, 13, 'INST-002'),
(14,  60, 'Bodega CFS Norte - Estante N4', 8, 14, 'INST-002');

-- =====================================================
-- 8. MOVIMIENTO_INVENTARIO  (14 filas)
-- =====================================================
-- CHECK (cantidad > 0) respetado en todas las filas. Mezcla entradas y salidas.
-- La institucion del movimiento se hereda del inventario (auditoria inmutable).
--   INST-001 -> movimientos 1..10 ; INST-002 -> movimientos 11..14.

INSERT INTO movimiento_inventario (movimiento_id, tipo_movimiento, cantidad, fecha_movimiento, observacion, inventario_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'ENTRADA', 50,  CURRENT_TIMESTAMP - INTERVAL '20 days', 'Compra a proveedor LICENSE-001', 1),
(2,  'SALIDA',  5,  CURRENT_TIMESTAMP - INTERVAL '18 days', 'Retiro por stock minimo',            2),
(3,  'ENTRADA', 10,  CURRENT_TIMESTAMP - INTERVAL '15 days', 'Compra urgente de toner',            3),
(4,  'SALIDA',  8,  CURRENT_TIMESTAMP - INTERVAL '12 days', 'Consumo interno mensual',              4),
(5,  'ENTRADA', 100, CURRENT_TIMESTAMP - INTERVAL '10 days', 'Compra trimestral de folders',        5),
(6,  'SALIDA',  3,  CURRENT_TIMESTAMP - INTERVAL '8 days',  'Entrega a biblioteca',                 6),
(7,  'SALIDA',  7,  CURRENT_TIMESTAMP - INTERVAL '6 days',  'Reposicion por merma detectada',       7),
(8,  'ENTRADA', 25,  CURRENT_TIMESTAMP - INTERVAL '5 days',  'Compra de grapadoras',                8),
(9,  'SALIDA',  4,  CURRENT_TIMESTAMP - INTERVAL '3 days',  'Prestamo a sala de clases',            9),
(10, 'SALIDA',  4,  CURRENT_TIMESTAMP - INTERVAL '1 day',   'Reposicion por stock bajo',           10),
(11, 'ENTRADA', 20,  CURRENT_TIMESTAMP - INTERVAL '9 days',  'Compra a proveedor LICENSE-014',      11),
(12, 'SALIDA',  3,  CURRENT_TIMESTAMP - INTERVAL '7 days',  'Consumo en box de atencion',          12),
(13, 'ENTRADA', 40,  CURRENT_TIMESTAMP - INTERVAL '4 days',  'Compra de insumos clinicos',          13),
(14, 'SALIDA',  5,  CURRENT_TIMESTAMP - INTERVAL '2 days',  'Reposicion de archivadores',          14);

-- =====================================================
-- 9. PRIORIDAD  (3 filas)  [GLOBAL, sin institucion - D-5/AC-3]
-- =====================================================

INSERT INTO prioridad (prioridad_id, nombre, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Alta',  'Necesario para operar en el corto plazo'),
(2, 'Media', 'Requiere reposicion pero no bloquea la operacion'),
(3, 'Baja',  'Puede esperar a la siguiente compra periodica');

-- =====================================================
-- 10. ESTADO_TICKET  (4 filas)  [GLOBAL, sin institucion - D-5/AC-3]
-- =====================================================
-- El orden de estas filas es el orden del flujo: el servicio lo lee por
-- estado_id ascendente. El id de "Cerrado" ya no es critico: el cierre se
-- reconoce por nombre (Feature 004).

INSERT INTO estado_ticket (estado_id, nombre, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Pendiente',   'Ticket creado, aun sin revision'),
(2, 'EnRevision',  'Revisando justificacion y disponibilidad'),
(3, 'EnCurso',     'Aprobado y en preparacion de despacho'),
(4, 'Cerrado',     'Despachado y con fecha de cierre registrada');

-- =====================================================
-- 11. TICKET  (10 filas)
-- =====================================================
-- `institucion_id` se deriva del solicitante (usuario -> departamento ->
-- institucion). Ningun ticket usa un solicitante de otra institucion que la de
-- sus productos. Reparto en los 4 estados; los Cerrados traen fecha_cierre.
--   INST-001 -> tickets 1..8 (solicitantes 1..7, departamentos 1..7)
--   INST-002 -> tickets 9..10 (solicitante 8, departamento 8)

INSERT INTO ticket (ticket_id, usuario_id, prioridad_id, estado_id, asunto, descripcion, fecha_creacion, fecha_cierre, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  2,  2,  1, 'Resmas para sala de computacion',   'Solicitud de 10 resmas para el curso de referencia.',   CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL, 'INST-001'),
(2,  5,  1,  1, 'Toner urgente para impresora',       'La impresora de la sala 3 quedo sin toner.',            CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL, 'INST-001'),
(3,  3,  3,  2, 'Folders para archivo de pagos',       'Carpetas para ordenar comprobantes del mes.',          CURRENT_TIMESTAMP - INTERVAL '3 days',  NULL, 'INST-001'),
(4,  2,  2,  2, 'Boligrafos para secretaria',          'Reposicion del stock de escritura.',                    CURRENT_TIMESTAMP - INTERVAL '4 days',  NULL, 'INST-001'),
(5,  3,  1,  3, 'Grapadoras para oficina',             'Grapadoras de reemplazo para el area de pagos.',        CURRENT_TIMESTAMP - INTERVAL '5 days',  NULL, 'INST-001'),
(6,  1,  2,  3, 'Clip metalico para archivo',          'El clip se perdio en la mudanza.',                      CURRENT_TIMESTAMP - INTERVAL '6 days',  NULL, 'INST-001'),
(7,  4,  3,  4, 'Cintas para sellar sobres',           'Reposicion de cintas de la oficina.',                   CURRENT_TIMESTAMP - INTERVAL '9 days',  CURRENT_TIMESTAMP - INTERVAL '7 days', 'INST-001'),
(8,  6,  2,  4, 'Rotuladores para inventario',         'Rotuladores para etiquetar activos.',                   CURRENT_TIMESTAMP - INTERVAL '12 days', CURRENT_TIMESTAMP - INTERVAL '10 days', 'INST-001'),
(9,  8,  1,  2, 'Guantes para box de atencion',        'Insumos clinicos para la atencion primaria.',           CURRENT_TIMESTAMP - INTERVAL '3 days',  NULL, 'INST-002'),
(10, 8,  2,  4, 'Resmas para fichas de pacientes',     'Resmas para imprimir fichas en la recepcion.',          CURRENT_TIMESTAMP - INTERVAL '8 days',  CURRENT_TIMESTAMP - INTERVAL '6 days', 'INST-002');

-- =====================================================
-- 12. DETALLE_TICKET  (10 filas)
-- =====================================================
-- CHECK (cantidad_solicitada > 0) y (cantidad_entregada >= 0) respetados.
-- `institucion_id` se deriva del ticket y el producto debe ser de esa misma
-- institucion (FK compuesta). Los tickets Cerrados (estado 4) llevan
-- cantidad_entregada = solicitada, coherente con su despacho.

INSERT INTO detalle_ticket (detalle_ticket_id, ticket_id, producto_id, cantidad_solicitada, cantidad_entregada, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  1,  1,  10,  0,  'INST-001'),
(2,  2,  2,  2,   0,  'INST-001'),
(3,  3,  3,  50,  0,  'INST-001'),
(4,  4,  4,  24,  0,  'INST-001'),
(5,  5,  8,  3,   0,  'INST-001'),
(6,  6,  5,  4,   0,  'INST-001'),
(7,  7,  6,  6,   6,  'INST-001'),
(8,  8,  9,  2,   2,  'INST-001'),
(9,  9,  13, 4,   0,  'INST-002'),
(10, 10, 11, 5,   5,  'INST-002');

-- =====================================================
-- 13. SINCRONIZAR SECUENCIAS  (NO OLVIDAR)
-- =====================================================
-- `OVERRIDING SYSTEM VALUE` inserta ids explicitos pero NO avanza la
-- secuencia de la columna. El TRUNCATE ... RESTART IDENTITY la dejo en 1,
-- asi que sin este bloque el siguiente POST intentaria generar ticket_id = 1,
-- chocaria con el id 1 ya insertado y responderia HTTP 500 por
-- UniqueViolation. Este bloque deja cada secuencia en MAX(id).

SELECT setval(pg_get_serial_sequence('departamento',           'departamento_id'),           COALESCE((SELECT MAX(departamento_id)           FROM departamento),           1));
SELECT setval(pg_get_serial_sequence('rol',                    'rol_id'),                    COALESCE((SELECT MAX(rol_id)                    FROM rol),                    1));
SELECT setval(pg_get_serial_sequence('usuario',                'usuario_id'),                COALESCE((SELECT MAX(usuario_id)                FROM usuario),                1));
SELECT setval(pg_get_serial_sequence('categoria',              'categoria_id'),              COALESCE((SELECT MAX(categoria_id)              FROM categoria),              1));
SELECT setval(pg_get_serial_sequence('producto',               'producto_id'),               COALESCE((SELECT MAX(producto_id)               FROM producto),               1));
SELECT setval(pg_get_serial_sequence('inventario',             'inventario_id'),             COALESCE((SELECT MAX(inventario_id)             FROM inventario),             1));
SELECT setval(pg_get_serial_sequence('movimiento_inventario', 'movimiento_id'),             COALESCE((SELECT MAX(movimiento_id)             FROM movimiento_inventario), 1));
SELECT setval(pg_get_serial_sequence('prioridad',              'prioridad_id'),              COALESCE((SELECT MAX(prioridad_id)              FROM prioridad),              1));
SELECT setval(pg_get_serial_sequence('estado_ticket',          'estado_id'),                 COALESCE((SELECT MAX(estado_id)                 FROM estado_ticket),          1));
SELECT setval(pg_get_serial_sequence('ticket',                 'ticket_id'),                 COALESCE((SELECT MAX(ticket_id)                 FROM ticket),                 1));
SELECT setval(pg_get_serial_sequence('detalle_ticket',         'detalle_ticket_id'),         COALESCE((SELECT MAX(detalle_ticket_id)         FROM detalle_ticket),         1));
