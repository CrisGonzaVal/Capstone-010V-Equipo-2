-- =============================================================================
-- FEATURE 010 - T9: Migracion de la base existente a multi-tenant por esquemas
-- =============================================================================
-- Convierte una base PostgreSQL legada (las doce tablas canonicas 3NF en el
-- esquema `public`, con las columnas y claves de la Feature 008) en el estado
-- multi-tenant aprobado:
--
--   * esquema global de CONTROL con las doce tablas canonicas, el registro de
--     instituciones, el catalogo `rol` (incluido Superadmin), el departamento y
--     usuario administrativo, y el mapa `correo -> esquema`;
--   * un esquema TENANT por institucion con las doce tablas canonicas, la fila
--     `institucion` espejo, los catalogos `rol`/`prioridad`/`estado_ticket`
--     replicados y `version_esquema` en la version objetivo (`010.1`).
--
-- Invariantes de ejecucion (plan §"Migracion de la base existente", AGENTS §7):
--
--   * NO vive bajo el montaje de initdb. Esta en `database/migraciones/`, un
--     subdirectorio de `database/`; el entrypoint de la imagen PostgreSQL no
--     desciende a subdirectorios (verificado en T8a). Se invoca de forma
--     EXPLICITA, nunca en la instalacion limpia ni en un reinicio.
--   * NO ejecuta la semilla destructiva (`02_datos_semilla.sql`).
--   * NO borra el volumen ni la base. El esquema legado `public` conserva sus
--     tablas y filas intactas: es el respaldo de recuperacion. La limpieza o
--     renombrado de `public` es un paso operacional posterior y explicito.
--   * Es un UNICO bloque atomico: preflight y trabajo viven en el mismo `DO`.
--     Si cualquier verificacion o copia falla, el bloque revierte por completo
--     y la base queda SIN CAMBIOS.
--   * Es idempotente: una segunda ejecucion detecta los tenants ya en version
--     objetivo y no vuelve a copiar ni a alterar datos operativos.
--
-- Uso (respaldo previo y ventana de mantenimiento obligatorios):
--
--   psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" `
--        -v ON_ERROR_STOP=1 -f database/migraciones/001_migracion_multitenant_esquemas.sql
--
-- El nombre de esquema se reproduce EXACTAMENTE igual que
-- `app.services.tenant_service.nombre_esquema_para_institucion`:
--   `tenant_` + slug ASCII del ID (minusculas, cada caracter no alfanumerico a
--   `_`, recortado de `_`, truncado a 47) + `_` + primeros 8 hex del SHA-256 del
--   ID normalizado. `sha256()` y `normalize(..., NFKD)` son funciones de nucleo
--   de PostgreSQL (>= 13); no se requiere ninguna extension ni dependencia nueva.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Funciones auxiliares de sesion
-- -----------------------------------------------------------------------------

-- Nombre determinista del esquema tenant (espejo en SQL de
-- `tenant_service.nombre_esquema_para_institucion`).
CREATE OR REPLACE FUNCTION pg_temp.nombre_esquema_tenant(p_institucion_id text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $nombre$
    SELECT 'tenant_'
        || left(
             btrim(
               regexp_replace(
                 -- NFKD + descarte de no-ASCII + minusculas: replica exacta del
                 -- `_slug` de `tenant_service` (misma normalizacion Unicode).
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
-- AS IDENTITY` de un esquema, tras copiar filas con `OVERRIDING SYSTEM VALUE`.
-- Conserva la continuidad de IDs (nunca reasigna un valor ya usado).
CREATE OR REPLACE FUNCTION pg_temp.resetear_identidades(p_esq text)
RETURNS void
LANGUAGE plpgsql
AS $reset$
DECLARE
    pares text[] := ARRAY[
        'departamento:departamento_id',
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
-- 1. Migracion (bloque unico y atomico)
-- -----------------------------------------------------------------------------

DO $migracion$
DECLARE
    --: Version objetivo del DDL por tenant (constante de despliegue).
    v_version_objetivo constant text := '010.1';

    --: Plantillas del DDL canonico (12 entidades 3NF). `%1$I` es el esquema
    --: destino; se expanden con `format` para `control` y para cada tenant.
    v_plantillas text[];

    v_control_existe boolean;
    v_esquema text;
    v_plantilla text;
    v_tabla text;
    v_institucion_id text;
    v_conteo integer;
    v_ambiguas integer;
    v_esperado integer;
    v_obtenido integer;
    v_token text;
    v_superadmin_rol integer;
    v_departamento_admin integer;
    v_institucion_admin constant text := 'CTRL-SAAS';
BEGIN
    -------------------------------------------------------------------------
    -- FASE 0: PREFLIGHT (solo lectura; aborta sin cambios)
    -------------------------------------------------------------------------

    -- Plantillas del DDL canonico, identicas a `database/01_esquema.sql`.
    v_plantillas := ARRAY[
        'CREATE TABLE %1$I.institucion ('
        'institucion_id VARCHAR(20) PRIMARY KEY, '
        'nombre VARCHAR(150) NOT NULL, '
        'rut VARCHAR(20), '
        'direccion VARCHAR(200))',

        'CREATE TABLE %1$I.departamento ('
        'departamento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre_dep VARCHAR(100) NOT NULL, '
        'descripcion VARCHAR(200), '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT departamento_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
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
        'CONSTRAINT usuario_departamento_fk FOREIGN KEY (departamento_id) '
        'REFERENCES %1$I.departamento(departamento_id), '
        'CONSTRAINT usuario_rol_fk FOREIGN KEY (rol_id) REFERENCES %1$I.rol(rol_id))',

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

        'CREATE TABLE %1$I.movimiento_inventario ('
        'movimiento_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'tipo_movimiento VARCHAR(20) NOT NULL, '
        'cantidad INTEGER NOT NULL, '
        'fecha_movimiento TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
        'observacion VARCHAR(250), '
        'inventario_id INTEGER NOT NULL, '
        'CONSTRAINT movimiento_inventario_fk FOREIGN KEY (inventario_id) '
        'REFERENCES %1$I.inventario(inventario_id), '
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
        'CONSTRAINT ticket_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT ticket_usuario_fk FOREIGN KEY (usuario_id) '
        'REFERENCES %1$I.usuario(usuario_id), '
        'CONSTRAINT ticket_prioridad_fk FOREIGN KEY (prioridad_id) '
        'REFERENCES %1$I.prioridad(prioridad_id), '
        'CONSTRAINT ticket_estado_fk FOREIGN KEY (estado_id) '
        'REFERENCES %1$I.estado_ticket(estado_id), '
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
        'CONSTRAINT detalle_cantidad_entregada_ck CHECK (cantidad_entregada >= 0))'
    ];

    v_control_existe := to_regclass('control.institucion') IS NOT NULL;

    -- (0.1) Estado inicial reconocible: base legada en `public`, o ya migrada.
    IF NOT v_control_existe THEN
        IF to_regnamespace('control') IS NOT NULL THEN
            RAISE EXCEPTION 'Migracion abortada: el esquema control existe pero no contiene el registro canonico (control.institucion); estado no reconocido, requiere recuperacion manual.';
        END IF;
        IF to_regclass('public.institucion') IS NULL THEN
            RAISE EXCEPTION 'Migracion abortada: no existe el esquema legado public.institucion ni un control ya migrado.';
        END IF;
    END IF;

    IF to_regclass('public.institucion') IS NOT NULL THEN
        -- (0.2) Debe haber instituciones, sin identificadores vacios.
        SELECT count(*) INTO v_conteo FROM public.institucion;
        IF v_conteo = 0 THEN
            RAISE EXCEPTION 'Migracion abortada: no hay instituciones que migrar.';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.institucion
            WHERE institucion_id IS NULL OR btrim(institucion_id) = ''
        ) THEN
            RAISE EXCEPTION 'Migracion abortada: existe una institucion con identificador vacio.';
        END IF;

        -- (0.3) `usuario` se asigna por `departamento`; ninguna fila sin institucion.
        SELECT count(*) INTO v_ambiguas
        FROM public.usuario u
        LEFT JOIN public.departamento d ON d.departamento_id = u.departamento_id
        WHERE d.departamento_id IS NULL OR d.institucion_id IS NULL;
        IF v_ambiguas > 0 THEN
            RAISE EXCEPTION 'Migracion abortada: % usuario(s) sin institucion resoluble via departamento.', v_ambiguas;
        END IF;

        -- (0.4) `movimiento_inventario` se asigna por `inventario`.
        SELECT count(*) INTO v_ambiguas
        FROM public.movimiento_inventario m
        LEFT JOIN public.inventario i ON i.inventario_id = m.inventario_id
        WHERE i.inventario_id IS NULL OR i.institucion_id IS NULL;
        IF v_ambiguas > 0 THEN
            RAISE EXCEPTION 'Migracion abortada: % movimiento_inventario sin inventario resoluble.', v_ambiguas;
        END IF;

        -- (0.5) Tablas con `institucion_id` directo: sin nulidad ni referencias
        --      huerfanas al registro institucional.
        FOREACH v_tabla IN ARRAY ARRAY['departamento', 'categoria', 'producto', 'inventario', 'ticket', 'detalle_ticket'] LOOP
            IF to_regclass(format('public.%I', v_tabla)) IS NULL THEN
                RAISE EXCEPTION 'Migracion abortada: falta la tabla legada public.%.', v_tabla;
            END IF;
            EXECUTE format('SELECT count(*) FROM public.%I WHERE institucion_id IS NULL', v_tabla) INTO v_ambiguas;
            IF v_ambiguas > 0 THEN
                RAISE EXCEPTION 'Migracion abortada: % fila(s) de % sin institucion_id.', v_ambiguas, v_tabla;
            END IF;
            EXECUTE format(
                'SELECT count(*) FROM public.%I t '
                'LEFT JOIN public.institucion i ON i.institucion_id = t.institucion_id '
                'WHERE i.institucion_id IS NULL', v_tabla
            ) INTO v_ambiguas;
            IF v_ambiguas > 0 THEN
                RAISE EXCEPTION 'Migracion abortada: % fila(s) de % referencian una institucion inexistente.', v_ambiguas, v_tabla;
            END IF;
        END LOOP;

        -- (0.6) Sin colisiones en el nombre de esquema derivado.
        SELECT count(*) INTO v_ambiguas FROM (
            SELECT pg_temp.nombre_esquema_tenant(institucion_id) AS esq
            FROM public.institucion
            GROUP BY 1
            HAVING count(*) > 1
        ) AS colisiones;
        IF v_ambiguas > 0 THEN
            RAISE EXCEPTION 'Migracion abortada: % colision(es) de nombre de esquema derivado.', v_ambiguas;
        END IF;

        -- (0.7) Ningun esquema tenant del objetivo debe preexistir sin la
        --      version objetivo (estado parcial = recuperacion manual).
        FOR v_institucion_id IN SELECT institucion_id FROM public.institucion LOOP
            v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
            IF to_regnamespace(v_esquema) IS NOT NULL
               AND to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
                RAISE EXCEPTION
                    'Migracion abortada: el esquema % ya existe sin version_esquema (estado parcial; requiere recuperacion manual).',
                    v_esquema;
            END IF;
        END LOOP;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 1: CONTROL (registro, identidad, mapa y estructura canonica)
    -------------------------------------------------------------------------
    IF NOT v_control_existe THEN
        EXECUTE 'CREATE SCHEMA control';
        FOREACH v_plantilla IN ARRAY v_plantillas LOOP
            EXECUTE format(v_plantilla, 'control');
        END LOOP;

        EXECUTE 'CREATE TABLE control.mapa_usuario_esquema ('
            'correo VARCHAR(150) PRIMARY KEY, '
            'institucion_id VARCHAR(20) NOT NULL, '
            'nombre_esquema VARCHAR(63) NOT NULL, '
            'activo BOOLEAN NOT NULL DEFAULT TRUE, '
            'CONSTRAINT mapa_usuario_esquema_institucion_fk FOREIGN KEY (institucion_id) '
            'REFERENCES control.institucion (institucion_id))';

        -- Registro institucional y catalogo de roles. La identidad que vive en
        -- control es la del Superadmin (el resto de las identidades pertenecen a
        -- su tenant); las tablas de negocio quedan vacias en control.
        EXECUTE 'INSERT INTO control.institucion SELECT * FROM public.institucion';
        EXECUTE 'INSERT INTO control.rol OVERRIDING SYSTEM VALUE SELECT * FROM public.rol';
        EXECUTE '
            INSERT INTO control.departamento OVERRIDING SYSTEM VALUE
            SELECT d.* FROM public.departamento d
            WHERE d.departamento_id IN (
                SELECT u.departamento_id FROM public.usuario u
                JOIN public.rol r ON r.rol_id = u.rol_id
                WHERE r.nombre_rol = ''Superadmin''
            )';
        EXECUTE '
            INSERT INTO control.usuario OVERRIDING SYSTEM VALUE
            SELECT u.* FROM public.usuario u
            JOIN public.rol r ON r.rol_id = u.rol_id
            WHERE r.nombre_rol = ''Superadmin''';

        -- Identidad Superadmin garantizada en control (si la base no traia una).
        SELECT rol_id INTO v_superadmin_rol FROM control.rol WHERE nombre_rol = 'Superadmin' LIMIT 1;
        IF v_superadmin_rol IS NULL THEN
            INSERT INTO control.rol (nombre_rol, descripcion)
            VALUES ('Superadmin', 'Administrador global de la plataforma SaaS')
            RETURNING rol_id INTO v_superadmin_rol;

            INSERT INTO control.institucion (institucion_id, nombre, direccion)
            VALUES (v_institucion_admin, 'CompuStock SaaS', 'Esquema de control');

            INSERT INTO control.departamento (nombre_dep, descripcion, institucion_id)
            VALUES ('Administracion SaaS', 'Departamento administrativo del esquema de control', v_institucion_admin)
            RETURNING departamento_id INTO v_departamento_admin;

            INSERT INTO control.usuario (nombre, apellido, correo, departamento_id, rol_id)
            VALUES ('Superadmin', 'CompuStock', 'superadmin@compustock.cl', v_departamento_admin, v_superadmin_rol);
        END IF;

        PERFORM pg_temp.resetear_identidades('control');
    END IF;

    -- ---------------------------------------------------------------------
    -- MAPA `correo -> esquema` de TODOS los usuarios locales.
    -- La identidad Superadmin se asocia al esquema reservado `control`
    -- (stack §4/§7: se resuelve en control y nunca se enruta como usuario
    -- tenant). El resto apunta a su tenant derivado. Idempotente.
    -- ---------------------------------------------------------------------
    INSERT INTO control.mapa_usuario_esquema (correo, institucion_id, nombre_esquema, activo)
    SELECT u.correo,
           d.institucion_id,
           CASE WHEN r.nombre_rol = 'Superadmin'
                THEN 'control'
                ELSE pg_temp.nombre_esquema_tenant(d.institucion_id)
           END,
           TRUE
    FROM public.usuario u
    JOIN public.departamento d ON d.departamento_id = u.departamento_id
    JOIN public.rol r ON r.rol_id = u.rol_id
    ON CONFLICT (correo) DO NOTHING;

    -------------------------------------------------------------------------
    -- FASE 2: UN ESQUEMA TENANT POR INSTITUCION
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM public.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        -- (2.1) Idempotencia / recuperacion.
        IF to_regnamespace(v_esquema) IS NOT NULL THEN
            IF to_regclass(format('%I.version_esquema', v_esquema)) IS NOT NULL THEN
                EXECUTE format('SELECT count(*) FROM %I.version_esquema', v_esquema) INTO v_conteo;
                IF v_conteo = 1 THEN
                    EXECUTE format('SELECT version FROM %I.version_esquema', v_esquema) INTO v_token;
                    IF v_token = v_version_objetivo THEN
                        CONTINUE; -- tenant ya migrado: no se altera nada
                    END IF;
                END IF;
            END IF;
            RAISE EXCEPTION
                'Migracion abortada: el esquema % ya existe sin la version objetivo % (estado parcial; requiere recuperacion manual).',
                v_esquema, v_version_objetivo;
        END IF;

        -- (2.2) Estructura canonica + tabla de version.
        EXECUTE format('CREATE SCHEMA %I', v_esquema);
        FOREACH v_plantilla IN ARRAY v_plantillas LOOP
            EXECUTE format(v_plantilla, v_esquema);
        END LOOP;
        EXECUTE format(
            'CREATE TABLE %I.version_esquema ('
            'version_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
            'version VARCHAR(20) NOT NULL, '
            'actualizada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)', v_esquema
        );

        -- (2.3) Espejo de institucion + catalogos replicados (IDs preservados).
        EXECUTE format(
            'INSERT INTO %I.institucion SELECT * FROM public.institucion WHERE institucion_id = $1',
            v_esquema
        ) USING v_institucion_id;
        EXECUTE format(
            'INSERT INTO %I.rol OVERRIDING SYSTEM VALUE '
            'SELECT * FROM public.rol WHERE nombre_rol <> ''Superadmin''', v_esquema
        );
        EXECUTE format('INSERT INTO %I.prioridad OVERRIDING SYSTEM VALUE SELECT * FROM public.prioridad', v_esquema);
        EXECUTE format('INSERT INTO %I.estado_ticket OVERRIDING SYSTEM VALUE SELECT * FROM public.estado_ticket', v_esquema);

        -- (2.4) Departamento por institucion_id directo.
        EXECUTE format(
            'INSERT INTO %I.departamento OVERRIDING SYSTEM VALUE '
            'SELECT * FROM public.departamento WHERE institucion_id = $1', v_esquema
        ) USING v_institucion_id;

        -- usuario se asigna por departamento; el Superadmin no se replica a
        -- ningun tenant (vive en control).
        EXECUTE format(
            'INSERT INTO %I.usuario OVERRIDING SYSTEM VALUE '
            'SELECT u.* FROM public.usuario u '
            'JOIN public.departamento d ON d.departamento_id = u.departamento_id '
            'WHERE d.institucion_id = $1 '
            'AND u.rol_id NOT IN (SELECT rol_id FROM public.rol WHERE nombre_rol = ''Superadmin'')',
            v_esquema
        ) USING v_institucion_id;

        -- (2.5) Tablas con institucion_id directo.
        FOREACH v_tabla IN ARRAY ARRAY['categoria', 'producto', 'inventario', 'ticket', 'detalle_ticket'] LOOP
            EXECUTE format(
                'INSERT INTO %I.%I OVERRIDING SYSTEM VALUE '
                'SELECT * FROM public.%I WHERE institucion_id = $1',
                v_esquema, v_tabla, v_tabla
            ) USING v_institucion_id;
        END LOOP;

        -- movimiento_inventario se asigna por inventario.
        EXECUTE format(
            'INSERT INTO %I.movimiento_inventario OVERRIDING SYSTEM VALUE '
            'SELECT m.* FROM public.movimiento_inventario m '
            'JOIN public.inventario i ON i.inventario_id = m.inventario_id '
            'WHERE i.institucion_id = $1', v_esquema
        ) USING v_institucion_id;

        -- (2.6) Secuencias continuas.
        PERFORM pg_temp.resetear_identidades(v_esquema);

        -- (2.7) Verificacion del tenant ANTES de escribir la version.
        EXECUTE format('SELECT count(*) FROM %I.institucion', v_esquema) INTO v_obtenido;
        IF v_obtenido <> 1 THEN
            RAISE EXCEPTION 'Verificacion fallida en el tenant %: espejo institucion -> % (esperado 1).', v_esquema, v_obtenido;
        END IF;
        FOREACH v_tabla IN ARRAY ARRAY['departamento', 'categoria', 'producto', 'inventario', 'ticket', 'detalle_ticket'] LOOP
            EXECUTE format(
                'SELECT count(*) FROM public.%I WHERE institucion_id = $1', v_tabla
            ) INTO v_esperado USING v_institucion_id;
            EXECUTE format('SELECT count(*) FROM %I.%I', v_esquema, v_tabla) INTO v_obtenido;
            IF v_esperado <> v_obtenido THEN
                RAISE EXCEPTION
                    'Verificacion fallida en el tenant % (%): esperado %, obtenido %.',
                    v_esquema, v_tabla, v_esperado, v_obtenido;
            END IF;
        END LOOP;

        -- (2.8) Version objetivo SOLO al final, tras verificar el tenant.
        EXECUTE format(
            'INSERT INTO %I.version_esquema (version) VALUES (%L)',
            v_esquema, v_version_objetivo
        );
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 3: VERIFICACION GLOBAL
    -------------------------------------------------------------------------
    -- Todos los usuarios de tenant tienen fila activa en el mapa.
    SELECT count(*) INTO v_ambiguas
    FROM public.usuario u
    JOIN public.departamento d ON d.departamento_id = u.departamento_id
    JOIN public.rol r ON r.rol_id = u.rol_id
    LEFT JOIN control.mapa_usuario_esquema m ON m.correo = u.correo
    WHERE r.nombre_rol <> 'Superadmin'
      AND (m.correo IS NULL OR NOT m.activo);
    IF v_ambiguas > 0 THEN
        RAISE EXCEPTION 'Verificacion global fallida: % usuario(s) sin correo->esquema activo.', v_ambiguas;
    END IF;

    -- Cada institucion tiene tenant con una unica fila de version objetivo.
    FOR v_institucion_id IN SELECT institucion_id FROM public.institucion LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION 'Verificacion global fallida: el tenant % no existe.', v_esquema;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L',
            v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion global fallida: el tenant % no tiene una fila de version %.',
                v_esquema, v_version_objetivo;
        END IF;
    END LOOP;

    RAISE NOTICE '010: migracion completada. Esquema legacy public intacto; control y tenants en version %.', v_version_objetivo;
END;
$migracion$;
