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
--   el prefijo numerico. Con los nombres viejos (`datos_semilla.sql` y
--   `script_apt_erp.sql`) la "d" sortea antes que la "s", la semilla corria
--   contra un esquema inexistente y, con ON_ERROR_STOP=1, abortaba todo el
--   arranque. Si renuevas un nombre, revisa que no invierta el orden.
--
-- USO
--   Automatica: al crear el volumen por primera vez (`docker compose up -d db`
--   con el volumen vacio). No hay que correrla a mano en una maquina nueva.
--
--   Manual, para resetear el entorno de QA con la base ya creada. Desde la raiz
--   del proyecto, en cmd.exe (NO en PowerShell):
--     docker exec -i compustock_db psql -U postgres -d apt_erp -v ON_ERROR_STOP=1 < database\02_datos_semilla.sql
--
--   En PowerShell el pipe (`Get-Content -Raw | docker exec -i ...`) mete el
--   contenido por la codificacion de la consola y destruye los acentos: se
--   guardan como "??". Usa `cmd /c` con la redireccion, que copia bytes crudos.
--   Este archivo es ASCII puro justamente para que el problema no aparezca.
--
--   Es idempotente: se puede correr las veces que quieras para resetear
--   el entorno de QA. El TRUNCATE inicial limpia las 12 tablas y reinicia
--   las secuencias GENERATED ALWAYS AS IDENTITY, de modo que los ids siempre
--   son los mismos (1..10) y los datos son reproducibles.
--
-- CONVENCION DE IDs
--   Los INSERT declaran el id de forma explicita (`OVERRIDING SYSTEM VALUE`)
--   para que el QA manual pueda referenciar filas concretas. Eso obliga a
--   sincronizar las secuencias al final (seccion 13): si no, el primer POST
--   autogenerado choca con el id 1 y devuelve HTTP 500.
--
-- RESTRICCION CRITICA - estado_ticket
--   `backend/app/services/ticket_service.py` usa la constante
--   ESTADO_CERRADO_ID = 4 para decidir si setea `ticket.fecha_cierre`.
--   Por eso "Cerrado" DEBE quedar en estado_id = 4 (ultimo del catalogo).
--   Si reordenas estos INSERTs, cerrar un ticket deja la fecha nula sin avisar.
--   Esto es la deuda H-2, a resolver por nombre en la Feature 004.
--
-- RESTRICCION - inventario
--   `inventario` tiene UNIQUE (departamento_id, producto_id). Por eso hay
--   10 filas y no 100: cada producto se ubica en un departamento distinto.
--
-- =====================================================

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

INSERT INTO institucion (institucion_id, nombre, rut, direccion) VALUES
('INST-001', 'Instituto Profesional Los Alpes', '65.432.100-9', 'Av. Providencia 1234, Santiago'),
('INST-002', 'Centro de Salud Familiar Norte', '65.887.230-1', 'Calle Los Robles 45, Maipu'),
('INST-003', 'Corporacion Educacional Cordillera', '77.120.540-3', 'Camino La Ladera 890, Lo Barnechea'),
('INST-004', 'Municipalidad de Talagante', '65.998.720-K', 'Plaza de Armas s/n, Talagante');

-- =====================================================
-- 2. DEPARTAMENTO  (10 filas)
-- =====================================================
-- Un departamento por institucion principal (INST-001) mas dos extras
-- en otras sedes, para que el QA vea el aislamiento por institucion.

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
-- 3. ROL  (4 filas)
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
-- `password` en texto plano a proposito: la autenticacion es decorativa
-- (AGENTS.md n7) y `auth_service.autenticar` todavia no implementa JWT
-- (Feature 006). Cuando exista hash real, este bloque habra que migrar.

INSERT INTO usuario (usuario_id, nombre, apellido, correo, password, departamento_id, rol_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Camila',   'Fernandez', 'camila.fernandez@losalpes.cl',   'demo1234', 1, 2),
(2,  'Diego',    'Munoz',     'diego.munoz@losalpes.cl',       'demo1234', 2, 4),
(3,  'Valentina', 'Reyes',     'valentina.reyes@losalpes.cl',   'demo1234', 3, 2),
(4,  'Sebastian','Gutierrez', 'sebastian.gutierrez@losalpes.cl','demo1234', 4, 2),
(5,  'Isabel',   'Contreras', 'isabel.contreras@losalpes.cl',  'demo1234', 5, 4),
(6,  'Andres',   'Vargas',    'andres.vargas@losalpes.cl',     'demo1234', 6, 3),
(7,  'Marcela',  'Nunez',     'marcela.nunez@losalpes.cl',     'demo1234', 7, 3),
(8,  'Felipe',   'Soto',      'felipe.soto@cfsnorte.cl',       'demo1234', 8, 4),
(9,  'Carla',    'Mancilla',  'carla.mancilla@cordillera.cl',  'demo1234', 9, 4),
(10, 'Andres',   'Pino',      'andres.pino@talagante.cl',      'demo1234', 10, 2);

-- =====================================================
-- 5. CATEGORIA  (10 filas)
-- =====================================================
-- Catalogo maestro de insumos de ofimatica.

INSERT INTO categoria (categoria_id, nombre_cat, descripcion_cat) OVERRIDING SYSTEM VALUE VALUES
(1,  'Papeleria',           'Hojas, resmas y sobres'),
(2,  'Toner y Cartuchos',   'Consumibles de impresion'),
(3,  'Escritura',           'Lapices, marcadores y rotuladores'),
(4,  'Organizacion',        'Folders, archivadores y separadores'),
(5,  'Oficina',             'Clip, fasteners y consumibles de escritorio'),
(6,  'Etiquetado',          'Etiquetas y cintas adhesivas'),
(7,  'Limpieza',            'Productos de aseo y sanitizacion'),
(8,  'Equipos',             'Perifericos y equipos de uso diario'),
(9,  'Didactico',           'Material para salas de clases'),
(10, 'Papeleria Premium',   'Papel especial y de presentacion');

-- =====================================================
-- 6. PRODUCTO  (10 filas)
-- =====================================================
-- Datos realistas de ofimatica. Tres productos quedan por DEBAJO de su
-- stock_minimo a proposito, para que el dashboard muestre las tarjetas
-- "Alertas de Stock" y "Stock Critico" con valores reales en el QA manual.
--   producto 7  (Toner 26A)       : stock_actual  3 < stock_minimo 10
--   producto 9  (Grapadora)       : stock_actual  1 < stock_minimo  5
--   producto 10 (Rotuladores)     : stock_actual  6 < stock_minimo 12

INSERT INTO producto (producto_id, nombre, descripcion, unidad_medida, stock_minimo, categoria_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Resma Carta 75g A4',      'Resma de 500 hojas tamano carta',           'RESMA',    20, 1),
(2,  'Resma Carta 90g A4',      'Resma de 500 hojas de alto gramaje',        'RESMA',    10, 10),
(3,  'Toner HP 26A Negro',      'Cartucho de toner negro original HP26A',    'UNIDAD',   10, 2),
(4,  'Folder Manila Carta',     'Carpeta de cartulina tamano carta',         'UNIDAD',   25, 4),
(5,  'Boligrota Bic Cristal',   'Boligrota punta fina color negro',         'UNIDAD',   30, 3),
(6,  'Clip Metrico 33mm',       'Clip de metal de 33mm en caja x100',       'CAJA',     15, 5),
(7,  'Toner Negro 26A Comp.',   'Cartucho compatible negro para HP26A',     'UNIDAD',   10, 2),
(8,  'Cinta Adhesiva 48mm',     'Cinta transparente de 48mm x 100m',        'ROLLO',    12, 6),
(9,  'Grapadora Estandar',      'Grapadora de escritorio con grapa 24/6',   'UNIDAD',    5, 8),
(10, 'Rotulador Marcador',      'Rotulador permanente punta gruesa',        'UNIDAD',   12, 3);

-- =====================================================
-- 7. INVENTARIO  (10 filas)
-- =====================================================
-- UNIQUE (departamento_id, producto_id): cada producto va en un
-- departamento distinto, por eso 10 filas y no 100.
-- stock_actual vs stock_minimo del producto:
--   producto 7  -> 3  vs 10  = CRITICO
--   producto 9  -> 1  vs 5   = CRITICO
--   producto 10 -> 6  vs 12  = CRITICO
-- El resto con holgura sobre el minimo.

INSERT INTO inventario (inventario_id, stock_actual, ubicacion, departamento_id, producto_id) OVERRIDING SYSTEM VALUE VALUES
(1,  120, 'Bodega Central - Estante A1', 7,  1),
(2,   45, 'Bodega Central - Estante A2', 7,  2),
(3,   18, 'Bodega Central - Estante B1', 7,  3),
(4,  200, 'Bodega Central - Estante C1', 6,  4),
(5,  150, 'Bodega Central - Estante C2', 6,  5),
(6,   35, 'Bodega Central - Estante D1', 6,  6),
(7,    3, 'Bodega Central - Estante B2', 7,  7),
(8,   48, 'Bodega Central - Estante D2', 1,  8),
(9,    1, 'Bodega Central - Estante E1', 5,  9),
(10,   6, 'Bodega Central - Estante E2', 2,  10);

-- =====================================================
-- 8. MOVIMIENTO_INVENTARIO  (10 filas)
-- =====================================================
-- CHECK (cantidad > 0) respetado en todas las filas.
-- Mezcla entradas y salidas para que el QA vea historial con ambos tipos.

INSERT INTO movimiento_inventario (movimiento_id, tipo_movimiento, cantidad, fecha_movimiento, observacion, inventario_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'ENTRADA', 50,  CURRENT_TIMESTAMP - INTERVAL '20 days', 'Compra a proveedor LICENSE-001', 1),
(2,  'SALIDA',  5,  CURRENT_TIMESTAMP - INTERVAL '18 days', 'Retiro por stock minimo',            2),
(3,  'ENTRADA', 10,  CURRENT_TIMESTAMP - INTERVAL '15 days', 'Compra urgente de toner',            3),
(4,  'SALIDA',  8,  CURRENT_TIMESTAMP - INTERVAL '12 days', 'Consumo interno mensual',              4),
(5,  'ENTRADA', 100, CURRENT_TIMESTAMP - INTERVAL '10 days', 'Compra trimestral de folders',        5),
(6,  'SALIDA',  3,  CURRENT_TIMESTAMP - INTERVAL '8 days',  'Entrega a biblioteca',                 6),
(7,  'SALIDA',  7,  CURRENT_TIMESTAMP - INTERVAL '6 days',  'Reposicion por merma detectada',       7),
(8,  'ENTRADA', 25,  CURRENT_TIMESTAMP - INTERVAL '5 days',  'Compra de cintas adhesivas',          8),
(9,  'SALIDA',  4,  CURRENT_TIMESTAMP - INTERVAL '3 days',  'Prestamo a sala de clases',            9),
(10, 'SALIDA',  4,  CURRENT_TIMESTAMP - INTERVAL '1 day',   'Reposicion por stock bajo',           10);

-- =====================================================
-- 9. PRIORIDAD  (3 filas)
-- =====================================================

INSERT INTO prioridad (prioridad_id, nombre, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Alta',  'Necesario para operar en el corto plazo'),
(2, 'Media', 'Requiere reposicion pero no bloquea la operacion'),
(3, 'Baja',  'Puede esperar a la siguiente compra periodica');

-- =====================================================
-- 10. ESTADO_TICKET  (4 filas)
-- =====================================================
-- ORDEN CRITICO: "Cerrado" debe quedar en estado_id = 4 para que
-- ticket_service.ESTADO_CERRADO_ID = 4 siga siendo correcto.

INSERT INTO estado_ticket (estado_id, nombre, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Pendiente',   'Ticket creado, aun sin revision'),
(2, 'EnRevision',  'Revisando justificacion y disponibilidad'),
(3, 'EnCurso',     'Aprobado y en preparacion de despacho'),
(4, 'Cerrado',     'Despachado y con fecha de cierre registrada');

-- =====================================================
-- 11. TICKET  (10 filas)
-- =====================================================
-- Reparto en los 4 estados para que el futuro Kanban tenga columnas con
-- datos. Tickets en estado 4 (Cerrado) traen fecha_cierre; los demas, NULL.

INSERT INTO ticket (ticket_id, usuario_id, prioridad_id, estado_id, asunto, descripcion, fecha_creacion, fecha_cierre) OVERRIDING SYSTEM VALUE VALUES
(1,  2,  2,  1, 'Resmas para sala de computacion',        'Solicitud de 10 resmas para el curso de referencia.',        CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL),
(2,  5,  1,  1, 'Toner urgente para impresora',            'La impresora de la sala 3 quedo sin toner.',               CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL),
(3,  8,  3,  2, 'Folders para fichas de pacientes',         'Fichas medicas se estan agotando.',                          CURRENT_TIMESTAMP - INTERVAL '3 days',  NULL),
(4,  2,  2,  2, 'Boligrafos para secretaria',              'Reposicion del stock de escritura.',                         CURRENT_TIMESTAMP - INTERVAL '4 days',  NULL),
(5,  9,  1,  3, 'Material didactico para el curso',         'Kits de escritura para 40 estudiantes.',                      CURRENT_TIMESTAMP - INTERVAL '5 days',  NULL),
(6,  3,  2,  3, 'Clip metalico para archivo',              'El clip se perdio en la mudanza.',                           CURRENT_TIMESTAMP - INTERVAL '6 days',  NULL),
(7,  1,  3,  4, 'Cintas para sellar sobres',                'Reposicion de cintas de la oficina.',                         CURRENT_TIMESTAMP - INTERVAL '9 days',  CURRENT_TIMESTAMP - INTERVAL '7 days'),
(8,  4,  2,  4, 'Grapadoras para reemplazo',                'Se rompio la grapadora de la sala 2.',                      CURRENT_TIMESTAMP - INTERVAL '12 days', CURRENT_TIMESTAMP - INTERVAL '10 days'),
(9,  7,  3,  4, 'Rotuladores para inventario',             'Rotuladores para etiquetar activos.',                       CURRENT_TIMESTAMP - INTERVAL '15 days', CURRENT_TIMESTAMP - INTERVAL '14 days'),
(10, 6,  2,  1, 'Papel premium para presentacion',          'Papel de presentacion para el informe anual.',               CURRENT_TIMESTAMP - INTERVAL '1 day',   NULL);

-- =====================================================
-- 12. DETALLE_TICKET  (10 filas)
-- =====================================================
-- CHECK (cantidad_solicitada > 0) y (cantidad_entregada >= 0) respetados.
-- Los tickets en estado Cerrado (4) llevan cantidad_entregada = solicitada,
-- en coherencia con que ya fueron despachados.

INSERT INTO detalle_ticket (detalle_ticket_id, ticket_id, producto_id, cantidad_solicitada, cantidad_entregada) OVERRIDING SYSTEM VALUE VALUES
(1,  1,  1,  10,  0),
(2,  2,  3,  2,   0),
(3,  3,  4,  50,  0),
(4,  4,  5,  24,  0),
(5,  5,  9,  3,   0),
(6,  6,  6,  4,   0),
(7,  7,  8,  6,   6),
(8,  8,  9,  2,   2),
(9,  9,  10, 8,   8),
(10, 10, 2,  5,   0);

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
