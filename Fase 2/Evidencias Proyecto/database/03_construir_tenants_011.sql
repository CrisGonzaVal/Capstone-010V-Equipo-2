-- =====================================================
-- COMPUSTOCK ERP - CONSTRUCTOR DE TENANTS (Feature 011)
-- Base de datos: apt_erp
-- PostgreSQL 16
-- =====================================================
-- PROPOSITO
--   Deja una INSTALACION LIMPIA multi-tenant completa con UN SOLO
--   `docker compose up -d` (initdb), sin pasos manuales. `01_esquema.sql` crea
--   el DDL canonico en `control` y `02_datos_semilla.sql` lo puebla; este script
--   es el paso que faltaba: reparte esa semilla en los cuatro esquemas tenant
--   (`tenant_<institucion>_<hash>`) con la estructura ampliada de la Feature 011
--   y deja `control` como contexto global (identidad + mapa + version).
--
--   Antes de este script, la semilla dejaba TODOS los datos de negocio dentro de
--   `control` y ningun esquema `tenant_*`: el sistema no podia enrutar por
--   tenant. Ahora la base que produce el initdb es estructural y funcionalmente
--   equivalente a la `apt_erp` real migrada (control + 4 tenants en `012.1`),
--   con la salvedad de que las cifras provienen de la semilla QA (11 sedes
--   repartidas 2/3/4/2, stock cuadrado) y no del historico real.
--
-- POR QUE UN .sql Y NO UN .sh
--   PostgreSQL ejecuta los archivos de /docker-entrypoint-initdb.d en orden
--   alfabetico y con `psql -v ON_ERROR_STOP=1`. El SQL dinamico que necesita
--   crear N esquemas con estructura identica vive en un bloque `DO` (igual que
--   las migraciones 001/002), asi que no hace falta un wrapper `.sh`: un solo
--   `.sql` es mas simple y coherente con el resto de `database/`.
--
-- ORDEN DE EJECUCION (no lo cambies sin leer esto)
--   Orden alfabetico en /docker-entrypoint-initdb.d:
--     01_esquema.sql  -> DDL canonico en `control`
--     02_datos_semilla.sql -> semilla QA en `control` (guardia fail-closed)
--     03_construir_tenants_011.sql -> ESTE script (crea y puebla los tenants)
--     98_migracion_particionamiento_institucional.sql -> no-op (base ya particionada)
--     99_migracion_retiro_password.sql -> no-op (columna ya ausente)
--   Debe correr DESPUES de `02_` (la semilla es su fuente) y ANTES de `98_`/`99_`
--   (que asumen una base ya multi-tenant pero no dependen de los tenants). El
--   prefijo `03_` garantiza ese lugar; un prefijo que sortee despues de `98_`
--   correria con la semilla ya movida o fuera de orden.
--
-- ESQUEMA (Feature 010/011)
--   `01_esquema.sql` fija `ALTER DATABASE ... SET search_path TO control, public`
--   y este script abre con `SET search_path TO control, public`. Todas las
--   referencias a `control` van explicitas para no depender del search_path.
--
-- DISENO (por que "mover" y no "copiar")
--   En la `apt_erp` real (migrada con `database/migraciones/001` y `002`):
--     * `control` conserva el registro canonico (`institucion`, `rol` con
--       Superadmin), el mapa `correo -> esquema` y `version_esquema`; las tablas
--       de negocio quedan VACIAS (los datos viven en cada tenant);
--     * cada tenant recibe su institucion espejo, los catalogos replicados
--       (`rol` sin Superadmin, `prioridad`, `estado_ticket`) y sus datos.
--   La semilla QA, en cambio, escribe todo en `control`. Este script reproduce
--   el reparto: COPIA lo replicable (institucion, catalogos) y MUEVE lo de
--   negocio (borra de `control` tras copiar). Resultado: `control` con la misma
--   forma que en `apt_erp`.
--
-- IDENTIDAD SUPERADMIN
--   La semilla QA NO define ningun usuario con rol Superadmin (sus 10 usuarios
--   son de negocio). Por eso `control` queda sin usuario/departamento de
--   identidad: el rol Superadmin SI existe en `control.rol`, pero la identidad
--   concreta la crea la aplicacion (`control_service.ejecutar_bootstrap_control`,
--   idempotente) cuando se necesita. NO se inventa aqui una institucion
--   administrativa ("CTRL-SAAS") porque la semilla fija `control.institucion`
--   con las cuatro instituciones de negocio y el DDL/seed aprobados exigen
--   mantener ese conteo (ver `backend/tests/test_migracion_modelo_organizacional_011.py`,
--   `test_instalacion_limpia_crea_sedes_y_conserva_la_guardia`).
--
-- IDEMPOTENCIA / SEGURIDAD
--   Solo tiene sentido sobre una base recien sembrada (la guardia de `02_`
--   garantiza que `control` estaba vacio antes de sembrar). Preflight: si algun
--   esquema tenant objetivo ya existe, ABORTA en cerrado en vez de mezclar
--   estados. Nunca se reejecuta en el initdb (el volumen persiste) y no toca la
--   base real `apt_erp` salvo que se invoque a proposito.
-- =====================================================

SET search_path TO control, public;

-- -----------------------------------------------------------------------------
-- 0. Funciones auxiliares de sesion
-- -----------------------------------------------------------------------------

-- Nombre determinista del esquema tenant: espejo EXACTO en SQL de
-- `app.services.tenant_service.nombre_esquema_para_institucion`
-- (`tenant_` + slug ASCII del ID + `_` + primeros 8 hex del SHA-256). Verificado
-- contra los esquemas reales de `apt_erp` (p. ej. INST-001 -> 038aa2a9).
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

-- Reinicia las secuencias de identidad de las tablas con PK `GENERATED ALWAYS
-- AS IDENTITY` de un esquema, tras copiar filas con `OVERRIDING SYSTEM VALUE`
-- (que NO avanza la secuencia). Deja cada secuencia en MAX(id)+1 para que el
-- primer INSERT autogenerado (p. ej. un POST) no choque con un id de la semilla.
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
        'detalle_ticket:detalle_ticket_id'
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

-- -----------------------------------------------------------------------------
-- 1. Construccion (bloque unico y atomico)
-- -----------------------------------------------------------------------------

DO $construccion$
DECLARE
    --: Version objetivo del DDL. Sube a `012.1` con la Feature 012 (activo
    --: institucional + capacidades), la misma que fija el codigo en
    --: `app.core.config.VERSION_ESQUEMA_OBJETIVO`.
    v_version_objetivo constant text := '012.1';

    --: Plantillas del DDL canonico ampliado (Feature 011), identicas a
    --: `database/01_esquema.sql` (mismas columnas, FKs, checks e indices
    --: implicitos). `%1$I` es el esquema destino (control o cada tenant); las
    --: FKs van calificadas al mismo esquema, sin referencias cross-schema.
    v_plantillas text[];

    v_institucion_id text;
    v_esquema text;
    v_plantilla text;
    v_conteo integer;
    v_esperado integer;
    v_obtenido integer;
BEGIN
    -------------------------------------------------------------------------
    -- FASE 0: PREFLIGHT (solo lectura; aborta sin cambios)
    -------------------------------------------------------------------------

    IF to_regclass('control.institucion') IS NULL THEN
        RAISE EXCEPTION 'Constructor 011 abortado: no existe control.institucion (falta 01_esquema.sql).';
    END IF;
    IF to_regclass('control.version_esquema') IS NULL THEN
        RAISE EXCEPTION 'Constructor 011 abortado: no existe control.version_esquema (falta 01_esquema.sql).';
    END IF;

    -- El seed debe haber corrido: sin instituciones no hay nada que repartir.
    SELECT count(*) INTO v_conteo FROM control.institucion;
    IF v_conteo = 0 THEN
        RAISE EXCEPTION 'Constructor 011 abortado: control.institucion esta vacio; la semilla (02_) no corrio.';
    END IF;

    -- Ningun esquema tenant objetivo debe preexistir: este script es de
    -- instalacion limpia, no un reparador de estados parciales.
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regnamespace(v_esquema) IS NOT NULL THEN
            RAISE EXCEPTION
                'Constructor 011 abortado: el esquema % ya existe; no se reconstruye un estado parcial.',
                v_esquema;
        END IF;
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 0b: CAPACIDADES DE CONTROL (Feature 012)
    -------------------------------------------------------------------------
    -- `funcion_institucion` es SOLO de control y nunca se copia a un tenant. La
    -- semilla (02_) ya la puebla; este bloque la normaliza de forma idempotente
    -- (una fila por pareja institucion/funcion) por si el constructor corre sobre
    -- un control sin capacidades.
    INSERT INTO control.funcion_institucion (institucion_id, funcion, habilitada)
    SELECT i.institucion_id, f.funcion, TRUE
    FROM control.institucion i
    CROSS JOIN (
        VALUES ('catalogo'), ('inventario'), ('tickets'),
               ('kanban'), ('dashboard'), ('gestion_organizacional')
    ) AS f(funcion)
    ON CONFLICT (institucion_id, funcion) DO NOTHING;

    -- Plantillas del DDL canonico ampliado (Feature 011).
    v_plantillas := ARRAY[
        --: Feature 012 (D-1): el espejo tenant de `institucion` se limita
        --: EXACTAMENTE a dos columnas. El canonico (con `rut`, `direccion` y
        --: `activo`) y `funcion_institucion` viven SOLO en control y nunca se
        --: copian a un tenant.
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

        'CREATE TABLE %1$I.version_esquema ('
        'version_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'version VARCHAR(20) NOT NULL, '
        'actualizada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'
    ];

    -------------------------------------------------------------------------
    -- FASE 1: UN ESQUEMA TENANT POR INSTITUCION (estructura + datos)
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        -- (1.1) Schema y DDL canonico ampliado (16 tablas, incluida version_esquema).
        EXECUTE format('CREATE SCHEMA %I', v_esquema);
        FOREACH v_plantilla IN ARRAY v_plantillas LOOP
            EXECUTE format(v_plantilla, v_esquema);
        END LOOP;

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
            RAISE EXCEPTION 'Constructor 011: espejo institucion en % -> % (esperado 1).', v_esquema, v_obtenido;
        END IF;
        --       (1.8.2) Una unica fila de version objetivo.
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L', v_esquema, v_version_objetivo
        ) INTO v_obtenido;
        IF v_obtenido <> 1 THEN
            RAISE EXCEPTION 'Constructor 011: % no tiene una fila de version % (tiene %).', v_esquema, v_version_objetivo, v_obtenido;
        END IF;
        --       (1.8.3) Conteos de negocio == los de control para esta institucion.
        EXECUTE format('SELECT count(*) FROM control.departamento WHERE institucion_id = $1', v_esquema)
            INTO v_esperado USING v_institucion_id;
        EXECUTE format('SELECT count(*) FROM %I.departamento', v_esquema) INTO v_obtenido;
        IF v_esperado <> v_obtenido THEN
            RAISE EXCEPTION 'Constructor 011: % departamento(s) esperados en %, obtenidos %.', v_esperado, v_esquema, v_obtenido;
        END IF;
        EXECUTE format('SELECT count(*) FROM control.sede WHERE institucion_id = $1', v_esquema)
            INTO v_esperado USING v_institucion_id;
        EXECUTE format('SELECT count(*) FROM %I.sede', v_esquema) INTO v_obtenido;
        IF v_esperado <> v_obtenido THEN
            RAISE EXCEPTION 'Constructor 011: % sede(s) esperadas en %, obtenidas %.', v_esperado, v_esquema, v_obtenido;
        END IF;
        --       (1.8.4) Ningun usuario huerfano (todo usuario tiene departamento).
        EXECUTE format(
            'SELECT count(*) FROM %I.usuario u '
            'LEFT JOIN %I.departamento d ON d.departamento_id = u.departamento_id '
            'WHERE d.departamento_id IS NULL', v_esquema, v_esquema
        ) INTO v_obtenido;
        IF v_obtenido <> 0 THEN
            RAISE EXCEPTION 'Constructor 011: % usuario(s) huerfano(s) en %.', v_obtenido, v_esquema;
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
            RAISE EXCEPTION 'Constructor 011: % producto(s) no cuadran entre inventario y stock_sede en %.', v_obtenido, v_esquema;
        END IF;
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 2: MAPA `correo -> esquema` DE TODOS LOS USUARIOS LOCALES
    -------------------------------------------------------------------------
    -- La identidad Superadmin se asocia al esquema reservado `control` (stack
    -- §4/§7); el resto apunta a su tenant derivado. Se puebla ANTES de vaciar
    -- `control.usuario`.
    INSERT INTO control.mapa_usuario_esquema (correo, institucion_id, nombre_esquema, activo)
    SELECT u.correo,
           d.institucion_id,
           CASE WHEN r.nombre_rol = 'Superadmin'
                THEN 'control'
                ELSE pg_temp.nombre_esquema_tenant(d.institucion_id)
           END,
           TRUE
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
    DELETE FROM control.estado_ticket;

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
        RAISE EXCEPTION 'Constructor 011: control no tiene una unica fila de version %.', v_version_objetivo;
    END IF;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION 'Constructor 011: el tenant % no existe.', v_esquema;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L', v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION 'Constructor 011: el tenant % no tiene una unica fila de version %.', v_esquema, v_version_objetivo;
        END IF;
    END LOOP;

    RAISE NOTICE '012: constructor completado. control + tenants en version %; datos de la semilla distribuidos por institucion.', v_version_objetivo;
END;
$construccion$;
