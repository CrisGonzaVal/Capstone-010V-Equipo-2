-- =====================================================
-- COMPUSTOCK ERP - DATOS SEMILLA + TENANTS (instalacion limpia)
-- Base de datos: apt_erp
-- PostgreSQL 16
-- =====================================================
--
-- PROPOSITO
--   Llenar la instalacion creada por `01_esquema.sql`:
--     1. sembrar en `control` los datos de QA (capacidades, sedes,
--        departamentos, usuarios, catalogo, stock, movimientos, tickets);
--     2. repartir esos datos a los esquemas `tenant_*` (una institucion por
--        esquema), dejando `control` como contexto global;
--     3. poblar `control.mapa_usuario_esquema` y `control.version_esquema`.
--   `control.registro_motivo_constancia` (Feature 017) queda VACIA: es evidencia
--   recuperable generada por las operaciones administrativas, no semilla.
--
-- ORDEN DE EJECUCION (no lo cambies sin leer esto)
--   PostgreSQL ejecuta los .sql de esta carpeta solo al crear el volumen, en
--   orden alfabetico y con ON_ERROR_STOP=1. `02_` va DESPUES de `01_`, que crea
--   `control` y los esquemas tenant; si se invierte, la semilla aborta.
--
-- ATOMICIDAD Y GUARDIA FAIL-CLOSED
--   Todo el archivo corre en una sola transaccion (BEGIN/COMMIT). La guardia de
--   la seccion 0 aborta ANTES de tocar nada si la base ya tiene filas de
--   negocio; ese es el motivo por el que el reset del entorno de QA se hace
--   recreando el volumen, no reejecutando la semilla:
--     docker compose -f docker-compose.yml down -v
--     docker compose -f docker-compose.yml up -d db
--   No se usa TRUNCATE: la guardia garantiza que la base esta limpia y
--   `control.institucion` (la topologia sembrada por `01_`) no se toca.
--
-- ESQUEMA (Feature 010)
--   Las tablas canonicas se referencian sin prefijo: el `search_path` de la base
--   apunta a `control, public`. Los tenants se referencian siempre calificados.
--
-- DATOS
--   Cuatro instituciones (INST-001..INST-004). INST-001 e INST-002 quedan
--   completas (departamentos, usuarios, catalogo, stock, movimientos y
--   tickets); INST-003 e INST-004 conservan sus departamentos y usuarios. Los
--   homonimos entre instituciones ("Papeleria", "Resma Carta 75g A4", ...) son
--   DELIBERADOS: filas independientes con ids y stock distintos.
--   El reparto de sedes es el de la Feature 011: INST-001 -> 2, INST-002 -> 3,
--   INST-003 -> 4, INST-004 -> 2; cada departamento va a UNA sede por
--   round-robin sobre ids ascendentes. `stock_sede` es el saldo vigente;
--   `inventario` queda como registro legado.
--
-- CONVENCION DE IDs
--   Los INSERT declaran el id de forma explicita (`OVERRIDING SYSTEM VALUE`)
--   para que el QA manual pueda referenciar filas concretas. Eso obliga a
--   sincronizar las secuencias de control (seccion 13) y de cada tenant (lo
--   hace `resetear_identidades` en el bloque de reparto).
--
-- RESTRICCION - estado_ticket
--   El servicio de tickets reconoce los estados terminales por NOMBRE
--   (`Cerrado`, `Anulado`), nunca por un id fijo. `Anulado` queda FUERA de la
--   secuencia lineal y solo se alcanza por anulacion o rechazo con motivo.
--
-- VERSION OBJETIVO DEL DDL
--   013.1 (`VERSION_ESQUEMA_OBJETIVO` en backend/app/core/config.py).
-- =====================================================

BEGIN;

SET search_path TO control, public;

-- Nombre determinista del esquema tenant: espejo EXACTO en SQL de
-- `app.services.tenant_service.nombre_esquema_para_institucion`.
-- Identica a la de 01_esquema.sql; se repite aqui porque pg_temp no se comparte
-- entre archivos.
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

-- =====================================================
-- 0. GUARDIA FAIL-CLOSED
-- =====================================================
-- Aborta antes de tocar nada si `control` o cualquier tenant ya tienen filas de
-- negocio. `control.institucion` se excluye: esas cuatro filas son la topologia
-- que siembra `01_esquema.sql`. Si alguna tabla esperada no existe, tambien
-- aborta (cierra por defecto).
DO $guardia$
DECLARE
    v_institucion_id text;
    v_esquema text;
    v_tabla text;
    v_conteo bigint;
    v_total bigint := 0;
    v_instituciones integer;
BEGIN
    SELECT count(*) INTO v_instituciones FROM control.institucion;
    IF v_instituciones <> 4 THEN
        RAISE EXCEPTION
            'Semilla QA abortada: control.institucion tiene % fila(s); se esperan 4 (01_ no corrio o la topologia cambio).',
            v_instituciones;
    END IF;

    FOREACH v_tabla IN ARRAY ARRAY[
        'funcion_institucion', 'sede', 'departamento', 'rol', 'usuario',
        'departamento_encargado', 'categoria', 'producto', 'inventario',
        'stock_sede', 'movimiento_inventario', 'prioridad', 'estado_ticket',
        'ticket', 'detalle_ticket', 'historial_transicion_ticket',
        'mapa_usuario_esquema', 'version_esquema', 'registro_motivo_constancia'
    ] LOOP
        EXECUTE format('SELECT count(*) FROM control.%I', v_tabla) INTO v_conteo;
        v_total := v_total + v_conteo;
    END LOOP;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regnamespace(v_esquema) IS NULL THEN
            RAISE EXCEPTION 'Semilla QA abortada: falta el esquema tenant % (01_ no lo creo).', v_esquema;
        END IF;

        FOREACH v_tabla IN ARRAY ARRAY[
            'institucion', 'sede', 'departamento', 'rol', 'usuario',
            'departamento_encargado', 'categoria', 'producto', 'inventario',
            'stock_sede', 'movimiento_inventario', 'prioridad', 'estado_ticket',
            'ticket', 'detalle_ticket', 'historial_transicion_ticket',
            'version_esquema'
        ] LOOP
            IF to_regclass(format('%I.%I', v_esquema, v_tabla)) IS NULL THEN
                RAISE EXCEPTION 'Semilla QA abortada: falta la tabla %.% en el tenant.', v_esquema, v_tabla;
            END IF;
            EXECUTE format('SELECT count(*) FROM %I.%I', v_esquema, v_tabla) INTO v_conteo;
            v_total := v_total + v_conteo;
        END LOOP;
    END LOOP;

    IF v_total > 0 THEN
        RAISE EXCEPTION
            'Semilla QA abortada: la base ya contiene % fila(s) de negocio; no se ejecuta ningun cambio. Reset QA = recrear el volumen (docker compose down -v).',
            v_total;
    END IF;

    RAISE NOTICE 'Semilla QA: base limpia (4 instituciones, tenants vacios), se permite continuar.';
END;
$guardia$;

-- =====================================================
-- 1a. FUNCION_INSTITUCION  (24 filas = 4 x 6)  [Feature 012, auxiliar]
-- =====================================================
-- Cada institucion nace con sus seis capacidades funcionales habilitadas
-- (conjunto cerrado, AC-5). `activo` de `institucion` toma su DEFAULT TRUE (la
-- semilla no nombra la columna). `funcion_institucion` es SOLO de control: el
-- constructor no la copia a ningun tenant.

INSERT INTO funcion_institucion (institucion_id, funcion, habilitada)
SELECT i.institucion_id, f.funcion, TRUE
FROM institucion i
CROSS JOIN (
    VALUES ('catalogo'), ('inventario'), ('tickets'),
           ('kanban'), ('dashboard'), ('gestion_organizacional')
) AS f(funcion);

-- =====================================================
-- 1b. SEDE  (11 filas)  [Feature 011]
-- =====================================================
-- Reparto fijo de D-7 por institucion: INST-001 -> 2, INST-002 -> 3,
-- INST-003 -> 4, INST-004 -> 2. Los ids son explicitos para que la regla
-- round-robin (departamentos por id ascendente, sedes por id ascendente,
-- indice i mod N) sea reproducible y referenciable en el QA manual.

INSERT INTO sede (sede_id, nombre, direccion, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Sede Providencia',        'Av. Providencia 1234, Santiago',    'INST-001'),
(2,  'Sede Maipu',              'Av. Pajaritos 2200, Maipu',         'INST-001'),
(3,  'Sede Los Robles',         'Calle Los Robles 45, Maipu',        'INST-002'),
(4,  'Sede CFS Norte Poniente', 'Av. Colon 3300, Maipu',             'INST-002'),
(5,  'Sede CFS Norte Oriente',  'Pasaje El Bosque 12, Renca',        'INST-002'),
(6,  'Sede La Ladera',          'Camino La Ladera 890, Lo Barnechea','INST-003'),
(7,  'Sede Cordillera Centro',  'Av. Apoquindo 4500, Las Condes',    'INST-003'),
(8,  'Sede Cordillera Sur',     'Av. Vicuna Mackenna 8900, La Florida','INST-003'),
(9,  'Sede Cordillera Norte',   'Av. Recoleta 1200, Recoleta',       'INST-003'),
(10, 'Sede Municipal',          'Plaza de Armas s/n, Talagante',     'INST-004'),
(11, 'Sede Oficina Barrio Sur', 'Av. Bernardo OHiggins 1450, Talagante','INST-004');

-- =====================================================
-- 2. DEPARTAMENTO  (10 filas)
-- =====================================================
-- INST-001 aporta 7 departamentos (1..7); INST-002 el 8; INST-003 el 9;
-- INST-004 el 10. Los usuarios y el ambito se derivan de aqui.
-- Feature 011 (D-7): cada departamento queda en UNA sede por la regla
-- round-robin (indice del departamento en su institucion, por id ascendente,
-- modulo el numero de sedes de esa institucion):
--   INST-001 (2 sedes 1,2): deps 1..7 -> 1,2,1,2,1,2,1
--   INST-002 (3 sedes 3,4,5): dep 8   -> 3
--   INST-003 (4 sedes 6..9):  dep 9   -> 6
--   INST-004 (2 sedes 10,11): dep 10  -> 10

INSERT INTO departamento (departamento_id, nombre_dep, descripcion, institucion_id, sede_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Direccion',              'Direccion_general y planificacion',       'INST-001', 1),
(2,  'Secretaria',             'Recepcion, correspondencia y agenda',     'INST-001', 2),
(3,  'Administracion',         'Pagos, compras y contabilidad',            'INST-001', 1),
(4,  'RRHH',                   'Seleccion y remuneraciones y contratos',    'INST-001', 2),
(5,  'Docencia',               'Coordinacion de salas/material didactico',  'INST-001', 1),
(6,  'Biblioteca',             'Catalogacion y prestamo de material',      'INST-001', 2),
(7,  'Servicios Generales',    'Mantenimiento, aseo y seguridad',          'INST-001', 1),
(8,  'AtencionPrimaria',       'Recepcion de pacientes y fichas',         'INST-002', 3),
(9,  'CoordinacionAcademica',  'Programacion de cursos y matriculas',      'INST-003', 6),
(10, 'OficinaGeneral',         'Oficina de Partes Municipal',                'INST-004', 10);

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
-- 4. USUARIO  (12 filas)
-- =====================================================
-- Clerk es la unica autoridad de autenticacion (Feature 006): el usuario local
-- no guarda credencial alguna. El vinculo con Clerk se resuelve por `correo`
-- (UNIQUE) contra el correo primario verificado, no por contrasena.
-- La institucion del usuario NO se guarda aqui: se deriva de su departamento.
-- Feature 011 (D-5): `sede_id` solo se puebla para los Bodegueros (rol 3) y con
-- la sede de su propio departamento; el resto queda NULL porque no opera stock:
--   usuario 6 (dep 6 -> sede 2), usuario 7 (dep 7 -> sede 1) y usuario 12
--   (dep 6 -> sede 2).
-- Los usuarios 11 y 12 (Feature 013) son las cuentas QA de ciclo de vida: sus
-- correos `+clerk_test@example.com` existen en la instancia dev de Clerk con
-- codigo de verificacion fijo 424242, de modo que cualquier clon puede probar
-- el circuito Solicitante -> Bodeguero sin crear usuarios a mano. Ambos estan
-- en el departamento 6 (Biblioteca, Sede 2) para que el ticket emitido por el
-- Solicitante se despache desde la misma sede que opera el Bodeguero.

INSERT INTO usuario (usuario_id, nombre, apellido, correo, departamento_id, rol_id, sede_id) OVERRIDING SYSTEM VALUE VALUES
(1,  'Camila',   'Fernandez', 'camila.fernandez@losalpes.cl',   1, 2, NULL),
(2,  'Diego',    'Munoz',     'diego.munoz@losalpes.cl',       2, 4, NULL),
(3,  'Valentina', 'Reyes',     'valentina.reyes@losalpes.cl',   3, 2, NULL),
(4,  'Sebastian','Gutierrez', 'sebastian.gutierrez@losalpes.cl', 4, 2, NULL),
(5,  'Isabel',   'Contreras', 'isabel.contreras@losalpes.cl',  5, 4, NULL),
(6,  'Andres',   'Vargas',    'andres.vargas@losalpes.cl',     6, 3, 2),
(7,  'Marcela',  'Nunez',     'marcela.nunez@losalpes.cl',     7, 3, 1),
(8,  'Felipe',   'Soto',      'felipe.soto@cfsnorte.cl',       8, 4, NULL),
(9,  'Carla',    'Mancilla',  'carla.mancilla@cordillera.cl',  9, 4, NULL),
(10, 'Andres',   'Pino',      'andres.pino@talagante.cl',      10, 2, NULL),
(11, 'Paula',    'Rojas',     'solicitante.test+clerk_test@example.com', 6, 4, NULL),
(12, 'Roberto',  'Diaz',      'bodeguero.test+clerk_test@example.com',   6, 3, 2);

-- =====================================================
-- 4b. DEPARTAMENTO_ENCARGADO  (5 filas)  [Feature 011, auxiliar]
-- =====================================================
-- Encargado de departamento = usuario Solicitante (rol 4) del MISMO departamento
-- (spec D-4); no concede permisos adicionales. En la semilla hay un Solicitante
-- por departamento, de modo que se asocia 1:1 al departamento al que pertenece.
-- La tabla admite varios encargados por departamento; la compatibilidad la
-- valida el servicio, no un trigger.
--   departamento 2 -> usuario 2 | departamento 5 -> usuario 5
--   departamento 6 -> usuario 11 (QA 013) | departamento 8 -> usuario 8
--   departamento 9 -> usuario 9

INSERT INTO departamento_encargado (departamento_encargado_id, departamento_id, usuario_id) OVERRIDING SYSTEM VALUE VALUES
(1, 2, 2),
(2, 5, 5),
(3, 6, 11),
(4, 8, 8),
(5, 9, 9);

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
-- 7b. STOCK_SEDE  (14 filas)  [Feature 011]
-- =====================================================
-- Saldo vigente por (sede, producto): UNIQUE (sede_id, producto_id) y
-- CHECK (stock_actual >= 0). `institucion_id` es la de la sede y el producto, que
-- las FK compuestas obligan a que coincida.
-- Consolidacion integra (spec D-7/AC-10): el saldo de cada fila departamental de
-- `inventario` se traslada tal cual a la sede de ESE departamento, sin repartir
-- ni duplicar. Como cada producto de la semilla vive en una sola fila
-- departamental, el total por producto coincide exactamente con el legado:
--   sede 1 (deps 1,3,5,7): prods 1 (50), 2 (18), 6 (48), 7 (3), 8 (1)
--   sede 2 (deps 2,4,6):   prods 3 (200), 4 (150), 5 (35), 9 (6), 10 (45)
--   sede 3 (dep 8):        prods 11 (12), 12 (9), 13 (8), 14 (60)
-- `departamento_id` deja de ser parte de la identidad del saldo vigente.

INSERT INTO stock_sede (stock_sede_id, stock_actual, sede_id, producto_id, institucion_id) OVERRIDING SYSTEM VALUE VALUES
(1,  50,  1, 1,  'INST-001'),
(2,  18,  1, 2,  'INST-001'),
(3,  48,  1, 6,  'INST-001'),
(4,  3,   1, 7,  'INST-001'),
(5,  1,   1, 8,  'INST-001'),
(6,  200, 2, 3,  'INST-001'),
(7,  150, 2, 4,  'INST-001'),
(8,  35,  2, 5,  'INST-001'),
(9,  6,   2, 9,  'INST-001'),
(10, 45,  2, 10, 'INST-001'),
(11, 12,  3, 11, 'INST-002'),
(12, 9,   3, 12, 'INST-002'),
(13, 8,   3, 13, 'INST-002'),
(14, 60,  3, 14, 'INST-002');

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
-- 10. ESTADO_TICKET  (5 filas)  [GLOBAL, sin institucion - D-5/AC-3]
-- =====================================================
-- El orden de las primeras cuatro filas es el orden del flujo lineal: el
-- servicio lo lee por estado_id ascendente. El id de "Cerrado" ya no es
-- critico: el cierre se reconoce por nombre (Feature 004). "Anulado" (Feature
-- 013) es la quinta y ultima fila del catalogo pero queda FUERA de la
-- secuencia lineal: es terminal por NOMBRE junto a "Cerrado", alcanzable solo
-- por anulacion o rechazo con motivo (D-1/D-6 de la 013) y nunca como estado
-- inicial de alta (D-11) ni por el cambio de estado de la 004.

INSERT INTO estado_ticket (estado_id, nombre, descripcion) OVERRIDING SYSTEM VALUE VALUES
(1, 'Pendiente',   'Ticket creado, aun sin revision'),
(2, 'EnRevision',  'Revisando justificacion y disponibilidad'),
(3, 'EnCurso',     'Aprobado y en preparacion de despacho'),
(4, 'Cerrado',     'Despachado y con fecha de cierre registrada'),
(5, 'Anulado',     'Cancelado antes del despacho; anulado o rechazado con motivo en el historial');

-- =====================================================
-- 11. TICKET  (10 filas)
-- =====================================================
-- `institucion_id` se deriva del solicitante (usuario -> departamento ->
-- institucion). Ningun ticket usa un solicitante de otra institucion que la de
-- sus productos. Reparto en los 4 estados; los Cerrados traen fecha_cierre.
--   INST-001 -> tickets 1..8 (solicitantes 1..7, departamentos 1..7)
--   INST-002 -> tickets 9..10 (solicitante 8, departamento 8)
-- Feature 011 (D-5/AC-9): `sede_id` es la instantanea de la sede vigente del
-- departamento del solicitante al crearse el ticket (2 -> sede 1, 3 -> 1,
-- 4 -> 2, 5 -> 1, 6 -> 2, 1 -> 1, 8 -> 3). Un cambio posterior de sede del
-- departamento NO reescribe estos tickets.

INSERT INTO ticket (ticket_id, usuario_id, prioridad_id, estado_id, asunto, descripcion, fecha_creacion, fecha_cierre, institucion_id, sede_id) OVERRIDING SYSTEM VALUE VALUES
(1,  2,  2,  1, 'Resmas para sala de computacion',   'Solicitud de 10 resmas para el curso de referencia.',   CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL, 'INST-001', 2),
(2,  5,  1,  1, 'Toner urgente para impresora',       'La impresora de la sala 3 quedo sin toner.',            CURRENT_TIMESTAMP - INTERVAL '2 days',  NULL, 'INST-001', 1),
(3,  3,  3,  2, 'Folders para archivo de pagos',       'Carpetas para ordenar comprobantes del mes.',          CURRENT_TIMESTAMP - INTERVAL '3 days',  NULL, 'INST-001', 1),
(4,  2,  2,  2, 'Boligrafos para secretaria',          'Reposicion del stock de escritura.',                    CURRENT_TIMESTAMP - INTERVAL '4 days',  NULL, 'INST-001', 2),
(5,  3,  1,  3, 'Grapadoras para oficina',             'Grapadoras de reemplazo para el area de pagos.',        CURRENT_TIMESTAMP - INTERVAL '5 days',  NULL, 'INST-001', 1),
(6,  1,  2,  3, 'Clip metalico para archivo',          'El clip se perdio en la mudanza.',                      CURRENT_TIMESTAMP - INTERVAL '6 days',  NULL, 'INST-001', 1),
(7,  4,  3,  4, 'Cintas para sellar sobres',           'Reposicion de cintas de la oficina.',                   CURRENT_TIMESTAMP - INTERVAL '9 days',  CURRENT_TIMESTAMP - INTERVAL '7 days', 'INST-001', 2),
(8,  6,  2,  4, 'Rotuladores para inventario',         'Rotuladores para etiquetar activos.',                   CURRENT_TIMESTAMP - INTERVAL '12 days', CURRENT_TIMESTAMP - INTERVAL '10 days', 'INST-001', 2),
(9,  8,  1,  2, 'Guantes para box de atencion',        'Insumos clinicos para la atencion primaria.',           CURRENT_TIMESTAMP - INTERVAL '3 days',  NULL, 'INST-002', 3),
(10, 8,  2,  4, 'Resmas para fichas de pacientes',     'Resmas para imprimir fichas en la recepcion.',          CURRENT_TIMESTAMP - INTERVAL '8 days',  CURRENT_TIMESTAMP - INTERVAL '6 days', 'INST-002', 3);

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
SELECT setval(pg_get_serial_sequence('departamento_encargado', 'departamento_encargado_id'), COALESCE((SELECT MAX(departamento_encargado_id) FROM departamento_encargado), 1));
SELECT setval(pg_get_serial_sequence('sede',                   'sede_id'),                   COALESCE((SELECT MAX(sede_id)                   FROM sede),                   1));
SELECT setval(pg_get_serial_sequence('stock_sede',             'stock_sede_id'),             COALESCE((SELECT MAX(stock_sede_id)             FROM stock_sede),             1));
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

-- =====================================================
-- REPARTO A TENANTS
-- =====================================================
-- Los esquemas y las tablas ya existen: los creo 01_esquema.sql. Este
-- bloque copia los datos de control a cada tenant, resetea sus secuencias,
-- marca la version objetivo y verifica el cuadre. `control` se vacia al
-- final (seccion FASE 3), conservando la topologia y el contexto global.

CREATE OR REPLACE FUNCTION pg_temp.resetear_identidades(p_esq text)
RETURNS void
LANGUAGE plpgsql
AS $reset$
DECLARE
    pares text[] := ARRAY[
        'sede:sede_id',
        'stock_sede:stock_sede_id',
        'departamento:departamento_id',
        'departamento_encargado:departamento_encargado_id',
        'rol:rol_id',
        'usuario:usuario_id',
        'categoria:categoria_id',
        'producto:producto_id',
        'inventario:inventario_id',
        'movimiento_inventario:movimiento_id',
        'prioridad:prioridad_id',
        'estado_ticket:estado_id',
        'ticket:ticket_id',
        'detalle_ticket:detalle_ticket_id',
        'historial_transicion_ticket:historial_transicion_id'
    ];
    par text;
    v_tabla text;
    v_columna text;
    v_registro text;
BEGIN
    FOREACH par IN ARRAY pares LOOP
        v_tabla := split_part(par, ':', 1);
        v_columna := split_part(par, ':', 2);
        v_registro := format('%I.%I', p_esq, v_tabla);
        IF to_regclass(v_registro) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'SELECT setval(pg_get_serial_sequence(%L, %L), '
            'COALESCE((SELECT max(%I) FROM %I.%I), 0) + 1, false)',
            v_registro, v_columna, v_columna, p_esq, v_tabla
        );
    END LOOP;
END;
$reset$;

DO $construccion$
DECLARE
    v_version_objetivo constant text := '013.1';
    v_institucion_id text;
    v_esquema text;
    v_plantilla text;
    v_conteo integer;
    v_esperado integer;
    v_mapa_esperado integer;
    v_obtenido integer;
BEGIN
    -- Preflight: los tenants ya deben existir (los creo 01_).
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regnamespace(v_esquema) IS NULL THEN
            RAISE EXCEPTION '02: falta el esquema tenant % (01_ no lo creo).', v_esquema;
        END IF;
    END LOOP;

    -- FASE 1: UN ESQUEMA TENANT POR INSTITUCION (estructura + datos)
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);


        -- (1.2) Registro institucional espejo y catalogos replicados.
        --       `rol` excluye Superadmin (vive solo en control); D-4 replica
        --       rol/prioridad/estado_ticket en cada tenant.
        -- Espejo tenant de dos columnas (Feature 012): el canonico de control ya
        -- no cabe en un `SELECT *` (porta `rut`/`direccion`/`activo`), asi que la
        -- copia nombra exactamente las columnas del espejo aprobado.
        EXECUTE format(
            'INSERT INTO %I.institucion (institucion_id, nombre) '
            'SELECT institucion_id, nombre FROM control.institucion WHERE institucion_id = $1',
            v_esquema
        ) USING v_institucion_id;
        EXECUTE format(
            'INSERT INTO %I.rol OVERRIDING SYSTEM VALUE '
            'SELECT * FROM control.rol WHERE nombre_rol <> ''Superadmin''', v_esquema
        );
        EXECUTE format('INSERT INTO %1$I.prioridad OVERRIDING SYSTEM VALUE SELECT * FROM control.prioridad', v_esquema);
        EXECUTE format('INSERT INTO %1$I.estado_ticket OVERRIDING SYSTEM VALUE SELECT * FROM control.estado_ticket', v_esquema);

        -- (1.3) Datos organizacionales: sede, departamento y usuario.
        EXECUTE format(
            'INSERT INTO %I.sede OVERRIDING SYSTEM VALUE '
            'SELECT * FROM control.sede WHERE institucion_id = $1', v_esquema
        ) USING v_institucion_id;
        EXECUTE format(
            'INSERT INTO %I.departamento OVERRIDING SYSTEM VALUE '
            'SELECT * FROM control.departamento WHERE institucion_id = $1', v_esquema
        ) USING v_institucion_id;
        -- usuario se asigna por el departamento; el Superadmin no se replica.
        EXECUTE format(
            'INSERT INTO %I.usuario OVERRIDING SYSTEM VALUE '
            'SELECT u.* FROM control.usuario u '
            'JOIN control.departamento d ON d.departamento_id = u.departamento_id '
            'WHERE d.institucion_id = $1 '
            'AND u.rol_id NOT IN (SELECT rol_id FROM control.rol WHERE nombre_rol = ''Superadmin'')',
            v_esquema
        ) USING v_institucion_id;
        -- Encargados: por la institucion de su departamento.
        EXECUTE format(
            'INSERT INTO %I.departamento_encargado OVERRIDING SYSTEM VALUE '
            'SELECT de.* FROM control.departamento_encargado de '
            'JOIN control.departamento d ON d.departamento_id = de.departamento_id '
            'WHERE d.institucion_id = $1', v_esquema
        ) USING v_institucion_id;

        -- (1.4) Catalogo y stock, con institucion_id directo.
        FOREACH v_plantilla IN ARRAY ARRAY['categoria', 'producto', 'inventario', 'stock_sede'] LOOP
            EXECUTE format(
                'INSERT INTO %I.%I OVERRIDING SYSTEM VALUE '
                'SELECT * FROM control.%I WHERE institucion_id = $1',
                v_esquema, v_plantilla, v_plantilla
            ) USING v_institucion_id;
        END LOOP;

        -- (1.5) Movimientos (por el inventario) y tickets/detalles (institucion directa).
        EXECUTE format(
            'INSERT INTO %I.movimiento_inventario OVERRIDING SYSTEM VALUE '
            'SELECT m.* FROM control.movimiento_inventario m '
            'JOIN control.inventario i ON i.inventario_id = m.inventario_id '
            'WHERE i.institucion_id = $1', v_esquema
        ) USING v_institucion_id;
        FOREACH v_plantilla IN ARRAY ARRAY['ticket', 'detalle_ticket'] LOOP
            EXECUTE format(
                'INSERT INTO %I.%I OVERRIDING SYSTEM VALUE '
                'SELECT * FROM control.%I WHERE institucion_id = $1',
                v_esquema, v_plantilla, v_plantilla
            ) USING v_institucion_id;
        END LOOP;

        -- (1.6) Secuencias continuas (la copia con OVERRIDING no las avanza).
        PERFORM pg_temp.resetear_identidades(v_esquema);

        -- (1.7) Version objetivo SOLO al final, tras poblar el tenant.
        EXECUTE format(
            'INSERT INTO %I.version_esquema (version) VALUES (%L)',
            v_esquema, v_version_objetivo
        );

        -- (1.8) Verificacion local antes de continuar (fail-closed).
        --       (1.8.1) Espejo institucional exactamente una fila.
        EXECUTE format('SELECT count(*) FROM %I.institucion', v_esquema) INTO v_obtenido;
        IF v_obtenido <> 1 THEN
            RAISE EXCEPTION '02: espejo institucion en % -> % (esperado 1).', v_esquema, v_obtenido;
        END IF;
        --       (1.8.2) Una unica fila de version objetivo.
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L', v_esquema, v_version_objetivo
        ) INTO v_obtenido;
        IF v_obtenido <> 1 THEN
            RAISE EXCEPTION '02: % no tiene una fila de version % (tiene %).', v_esquema, v_version_objetivo, v_obtenido;
        END IF;
        --       (1.8.3) Conteos de negocio == los de control para esta institucion.
        EXECUTE format('SELECT count(*) FROM control.departamento WHERE institucion_id = $1', v_esquema)
            INTO v_esperado USING v_institucion_id;
        EXECUTE format('SELECT count(*) FROM %I.departamento', v_esquema) INTO v_obtenido;
        IF v_esperado <> v_obtenido THEN
            RAISE EXCEPTION '02: % departamento(s) esperados en %, obtenidos %.', v_esperado, v_esquema, v_obtenido;
        END IF;
        EXECUTE format('SELECT count(*) FROM control.sede WHERE institucion_id = $1', v_esquema)
            INTO v_esperado USING v_institucion_id;
        EXECUTE format('SELECT count(*) FROM %I.sede', v_esquema) INTO v_obtenido;
        IF v_esperado <> v_obtenido THEN
            RAISE EXCEPTION '02: % sede(s) esperadas en %, obtenidas %.', v_esperado, v_esquema, v_obtenido;
        END IF;
        --       (1.8.4) Ningun usuario huerfano (todo usuario tiene departamento).
        EXECUTE format(
            'SELECT count(*) FROM %I.usuario u '
            'LEFT JOIN %I.departamento d ON d.departamento_id = u.departamento_id '
            'WHERE d.departamento_id IS NULL', v_esquema, v_esquema
        ) INTO v_obtenido;
        IF v_obtenido <> 0 THEN
            RAISE EXCEPTION '02: % usuario(s) huerfano(s) en %.', v_obtenido, v_esquema;
        END IF;
        --       (1.8.5) Cuadre de stock por producto entre inventario y stock_sede.
        EXECUTE format(
            'SELECT count(*) FROM ('
            '  SELECT i.producto_id, sum(i.stock_actual) AS departamental, '
            '         coalesce((SELECT sum(s.stock_actual) FROM %1$I.stock_sede s '
            '                   WHERE s.producto_id = i.producto_id), 0) AS por_sede '
            '  FROM %1$I.inventario i GROUP BY i.producto_id'
            ') t WHERE t.departamental <> t.por_sede', v_esquema
        ) INTO v_obtenido;
        IF v_obtenido <> 0 THEN
            RAISE EXCEPTION '02: % producto(s) no cuadran entre inventario y stock_sede en %.', v_obtenido, v_esquema;
        END IF;
    END LOOP;
    -------------------------------------------------------------------------
    -- FASE 2: MAPA `correo -> esquema` DE TODOS LOS USUARIOS LOCALES
    -------------------------------------------------------------------------
    -- La identidad Superadmin se asocia al esquema reservado `control` (stack
    -- 4/7); el resto apunta a su tenant derivado. Se puebla ANTES de vaciar
    -- `control.usuario`.
    -- Feature 017: todos los usuarios de la semilla tienen identidad Clerk
    -- preexistente, asi que su mapa nace en `aceptada` (D-1); no hay invitacion
    -- pendiente, por lo que `invitacion_id` y sus timestamps quedan nulos.
    SELECT count(*) INTO v_mapa_esperado FROM control.usuario;

    INSERT INTO control.mapa_usuario_esquema (
        correo, institucion_id, nombre_esquema, activo, estado_invitacion
    )
    SELECT u.correo,
           d.institucion_id,
           CASE WHEN r.nombre_rol = 'Superadmin'
                THEN 'control'
                ELSE pg_temp.nombre_esquema_tenant(d.institucion_id)
           END,
           TRUE,
           'aceptada'
    FROM control.usuario u
    JOIN control.departamento d ON d.departamento_id = u.departamento_id
    JOIN control.rol r ON r.rol_id = u.rol_id
    ON CONFLICT (correo) DO NOTHING;

    -------------------------------------------------------------------------
    -- FASE 3: DEJAR `control` COMO CONTEXTO GLOBAL
    -------------------------------------------------------------------------
    -- Se conservan `institucion` (registro canonico, destino de la FK del mapa),
    -- `rol` (incluido Superadmin) y `mapa_usuario_esquema`. Se VACIAN las tablas
    -- de negocio tras copiarlas: su lugar es cada tenant. El orden respeta las FK.
    -- Excepcion de la Feature 013: `estado_ticket` conserva la fila `Anulado`
    -- (presencia obligatoria en toda instalacion; stack.md Feature 013); es el espejo
    -- exacto del estado que el backend espera encontrar en `control` de una
    -- instalacion limpia. El resto del catalogo (y `prioridad`) se vacia como antes.
    DELETE FROM control.detalle_ticket;
    DELETE FROM control.movimiento_inventario;
    DELETE FROM control.stock_sede;
    DELETE FROM control.ticket;
    DELETE FROM control.inventario;
    DELETE FROM control.departamento_encargado;
    DELETE FROM control.producto;
    DELETE FROM control.categoria;
    DELETE FROM control.usuario;
    DELETE FROM control.departamento;
    DELETE FROM control.sede;
    DELETE FROM control.prioridad;
    DELETE FROM control.estado_ticket WHERE nombre <> 'Anulado';

    -- Version objetivo de control (una sola fila vigente).
    IF EXISTS (SELECT 1 FROM control.version_esquema) THEN
        UPDATE control.version_esquema
        SET version = v_version_objetivo, actualizada_en = CURRENT_TIMESTAMP;
    ELSE
        INSERT INTO control.version_esquema (version) VALUES (v_version_objetivo);
    END IF;

    -------------------------------------------------------------------------
    -- FASE 4: VERIFICACION GLOBAL (fail-closed)
    -------------------------------------------------------------------------
    SELECT count(*) INTO v_conteo
    FROM control.version_esquema WHERE version = v_version_objetivo;
    IF v_conteo <> 1 THEN
        RAISE EXCEPTION '02: control no tiene una unica fila de version %.', v_version_objetivo;
    END IF;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION '02: el tenant % no existe.', v_esquema;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L', v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION '02: el tenant % no tiene una unica fila de version %.', v_esquema, v_version_objetivo;
        END IF;
    END LOOP;

    RAISE NOTICE '02: semilla y tenants completados. control + tenants en version %; datos distribuidos por institucion.', v_version_objetivo;

    -- Chequeo final de control: contexto global sin negocio.
    IF (SELECT count(*) FROM control.usuario) <> 0 THEN
        RAISE EXCEPTION '02: control.usuario no quedo vacio.';
    END IF;
    IF (SELECT count(*) FROM control.ticket) <> 0 OR (SELECT count(*) FROM control.detalle_ticket) <> 0 THEN
        RAISE EXCEPTION '02: quedaron tickets en control.';
    END IF;
    IF (SELECT count(*) FROM control.estado_ticket) <> 1 THEN
        RAISE EXCEPTION '02: control.estado_ticket debe conservar solo Anulado.';
    END IF;
    IF (SELECT count(*) FROM control.mapa_usuario_esquema) <> v_mapa_esperado THEN
        RAISE EXCEPTION '02: el mapa de usuarios no coincide con los usuarios sembrados.';
    END IF;
    -- Feature 017: la semilla solo vincula identidades Clerk existentes.
    IF EXISTS (
        SELECT 1 FROM control.mapa_usuario_esquema
        WHERE estado_invitacion IS DISTINCT FROM 'aceptada'
    ) THEN
        RAISE EXCEPTION '02: el mapa sembrado debe nacer en estado_invitacion = aceptada.';
    END IF;
    IF (SELECT count(*) FROM control.registro_motivo_constancia) <> 0 THEN
        RAISE EXCEPTION '02: control.registro_motivo_constancia debe quedar vacia.';
    END IF;
END;
$construccion$;

COMMIT;
