-- =============================================================================
-- FEATURE 011 - T5: Migracion operacional al modelo organizacional (011.1)
-- =============================================================================
-- Convierte una base ya multi-tenant (posterior a la migracion 001 / version
-- `010.1`) al modelo organizacional aprobado en `docs/spec/features/011-.../spec.md`
-- (D-7) y `plan.md` §"Migracion de PostgreSQL existente y version 011.1":
--
--   * esquema global de CONTROL con la estructura canonica ampliada (sede,
--     stock_sede, departamento_encargado y las columnas nuevas) y la version
--     objetivo en `control.version_esquema`;
--   * un esquema TENANT por institucion con la estructura nueva, las sedes
--     deterministas de D-7, el reparto round-robin de departamentos, `stock_sede`
--     consolidado desde el inventario departamental, un movimiento `ENTRADA` de
--     consolidacion por cada saldo positivo y `ticket.sede_id` resuelto para los
--     tickets historicos.
--
-- Invariantes de ejecucion (patron de la migracion 001, AGENTS §7):
--
--   * NO vive bajo el montaje de initdb. Esta en `database/migraciones/`, un
--     subdirectorio de `database/`; el entrypoint de la imagen PostgreSQL no
--     desciende a subdirectorios. Se invoca de forma EXPLICITA, nunca en la
--     instalacion limpia ni en un reinicio.
--   * NO ejecuta la semilla destructiva (`02_datos_semilla.sql`).
--   * NO borra el volumen ni la base. El esquema legado `public` conserva sus
--     tablas y filas intactas: es el respaldo de recuperacion.
--   * NO modifica el inventario departamental ni los movimientos historicos: sus
--     filas, ids y FKs quedan identicos (auditoria inmutable). El saldo vigente
--     pasa a `stock_sede`; `inventario_id` de `movimiento_inventario` deja de ser
--     obligatoria porque los movimientos nuevos se enlazan por `stock_sede_id`.
--   * Es un UNICO bloque atomico: preflight y trabajo viven en el mismo `DO` /
--     transaccion. Si cualquier verificacion o consolidacion falla, el bloque
--     revierte por completo y la base queda SIN CAMBIOS.
--   * Es idempotente: una segunda ejecucion detecta control y todos los tenants
--     ya en version objetivo y no vuelve a copiar ni a alterar datos operativos.
--     Un estado parcial (estructura 011 sin version objetivo) ABORTA; nunca se
--     "repara" destruyendo datos.
--
-- Uso (respaldo previo y ventana de mantenimiento obligatorios):
--
--   psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" `
--        -v ON_ERROR_STOP=1 -f database/migraciones/002_migracion_modelo_organizacional_011.sql
--
-- El nombre de esquema se reproduce EXACTAMENTE igual que
-- `app.services.tenant_service.nombre_esquema_para_institucion` (ver 001).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Funciones auxiliares de sesion
-- -----------------------------------------------------------------------------

-- Nombre determinista del esquema tenant (espejo en SQL de
-- `tenant_service.nombre_esquema_para_institucion`). Identica a la de 001.
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

-- Crea, en el esquema indicado, la estructura nueva de la Feature 011 que NO
-- existe tras la migracion 010: sedes, saldos por sede, asociacion auxiliar de
-- encargados y las columnas/FKs nuevas. Se invoca una sola vez por esquema
-- (control y cada tenant), nunca sobre un esquema ya en version objetivo.
CREATE OR REPLACE FUNCTION pg_temp.aplicar_estructura_011(p_esq text)
RETURNS void
LANGUAGE plpgsql
AS $estructura$
BEGIN
    -- Entidad SEDE (destino de la FK compuesta de stock_sede).
    EXECUTE format(
        'CREATE TABLE %1$I.sede ('
        'sede_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'nombre VARCHAR(100) NOT NULL, '
        'direccion VARCHAR(200), '
        'institucion_id VARCHAR(20) NOT NULL, '
        'CONSTRAINT sede_institucion_fk FOREIGN KEY (institucion_id) '
        'REFERENCES %1$I.institucion(institucion_id), '
        'CONSTRAINT sede_institucion_uk UNIQUE (institucion_id, sede_id))',
        p_esq
    );

    -- Entidad STOCK_SEDE: saldo vigente por (sede, producto).
    EXECUTE format(
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
        p_esq
    );

    -- Columnas nuevas en DEPARTAMENTO / USUARIO / TICKET / MOVIMIENTO.
    EXECUTE format('ALTER TABLE %1$I.departamento ADD COLUMN IF NOT EXISTS sede_id INTEGER', p_esq);
    EXECUTE format(
        'ALTER TABLE %1$I.departamento ADD CONSTRAINT departamento_sede_fk '
        'FOREIGN KEY (sede_id) REFERENCES %1$I.sede(sede_id)', p_esq
    );

    EXECUTE format('ALTER TABLE %1$I.usuario ADD COLUMN IF NOT EXISTS sede_id INTEGER', p_esq);
    EXECUTE format(
        'ALTER TABLE %1$I.usuario ADD CONSTRAINT usuario_sede_fk '
        'FOREIGN KEY (sede_id) REFERENCES %1$I.sede(sede_id)', p_esq
    );

    EXECUTE format('ALTER TABLE %1$I.ticket ADD COLUMN IF NOT EXISTS sede_id INTEGER', p_esq);
    EXECUTE format(
        'ALTER TABLE %1$I.ticket ADD CONSTRAINT ticket_sede_fk '
        'FOREIGN KEY (sede_id) REFERENCES %1$I.sede(sede_id)', p_esq
    );

    EXECUTE format(
        'ALTER TABLE %1$I.movimiento_inventario ADD COLUMN IF NOT EXISTS stock_sede_id INTEGER',
        p_esq
    );
    -- (Idempotente por naturaleza: repetir el DROP NOT NULL es un no-op.)
    EXECUTE format(
        'ALTER TABLE %1$I.movimiento_inventario ALTER COLUMN inventario_id DROP NOT NULL',
        p_esq
    );
    EXECUTE format(
        'ALTER TABLE %1$I.movimiento_inventario ADD CONSTRAINT movimiento_stock_sede_fk '
        'FOREIGN KEY (stock_sede_id) REFERENCES %1$I.stock_sede(stock_sede_id)', p_esq
    );

    -- Asociacion auxiliar DEPARTAMENTO_ENCARGADO (no es entidad de dominio).
    EXECUTE format(
        'CREATE TABLE %1$I.departamento_encargado ('
        'departamento_encargado_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
        'departamento_id INTEGER NOT NULL, '
        'usuario_id INTEGER NOT NULL, '
        'CONSTRAINT departamento_encargado_departamento_fk FOREIGN KEY (departamento_id) '
        'REFERENCES %1$I.departamento(departamento_id), '
        'CONSTRAINT departamento_encargado_usuario_fk FOREIGN KEY (usuario_id) '
        'REFERENCES %1$I.usuario(usuario_id), '
        'CONSTRAINT departamento_encargado_uk UNIQUE (departamento_id, usuario_id))',
        p_esq
    );
END;
$estructura$;

-- Migra los datos organizacionales de un tenant: crea las sedes deterministas,
-- asigna departamentos por round-robin, consolida el saldo departamental en
-- `stock_sede`, registra los movimientos `ENTRADA` de consolidacion, asigna la
-- sede de los tickets historicos y VERIFICA el cuadre antes de devolver.
CREATE OR REPLACE FUNCTION pg_temp.migrar_tenant_011(p_esq text, p_num_sedes integer)
RETURNS void
LANGUAGE plpgsql
AS $datos$
DECLARE
    v_inst text;
    v_sedes integer[] := ARRAY[]::integer[];
    v_sede integer;
    v_dep record;
    v_indice integer := 0;
    v_filas integer;
BEGIN
    EXECUTE format('SELECT institucion_id FROM %1$I.institucion LIMIT 1', p_esq)
        INTO v_inst;

    -- (1) Sedes deterministas: exactamente `p_num_sedes`, en orden de sede_id.
    FOR i IN 1..p_num_sedes LOOP
        EXECUTE format(
            'INSERT INTO %1$I.sede (nombre, institucion_id) VALUES (%2$L, %3$L) '
            'RETURNING sede_id',
            p_esq, format('Sede %s', i), v_inst
        ) INTO v_sede;
        v_sedes := array_append(v_sedes, v_sede);
    END LOOP;

    -- (2) Reparto round-robin: departamento (por departamento_id ascendente)
    --     en la posicion i va a la sede i mod N.
    FOR v_dep IN EXECUTE format(
        'SELECT departamento_id FROM %1$I.departamento ORDER BY departamento_id', p_esq
    ) LOOP
        EXECUTE format(
            'UPDATE %1$I.departamento SET sede_id = %2$s WHERE departamento_id = %3$s',
            p_esq, v_sedes[(v_indice % p_num_sedes) + 1], v_dep.departamento_id
        );
        v_indice := v_indice + 1;
    END LOOP;

    -- (3) Consolidacion: una fila de stock_sede por (sede, producto) con la suma
    --     del inventario departamental de los departamentos de esa sede.
    EXECUTE format(
        'INSERT INTO %1$I.stock_sede (stock_actual, sede_id, producto_id, institucion_id) '
        'SELECT sum(i.stock_actual), d.sede_id, i.producto_id, %2$L '
        'FROM %1$I.inventario i '
        'JOIN %1$I.departamento d ON d.departamento_id = i.departamento_id '
        'GROUP BY d.sede_id, i.producto_id',
        p_esq, v_inst
    );

    -- (4) Un movimiento ENTRADA de consolidacion por cada saldo positivo, enlazado
    --     por stock_sede_id (inventario_id NULL). Observacion identificadora.
    EXECUTE format(
        'INSERT INTO %1$I.movimiento_inventario '
        '(tipo_movimiento, cantidad, observacion, inventario_id, stock_sede_id) '
        'SELECT %2$L, s.stock_actual, %3$L, NULL, s.stock_sede_id '
        'FROM %1$I.stock_sede s WHERE s.stock_actual > 0',
        p_esq, 'ENTRADA',
        'Consolidacion 011.1: saldo inicial por sede desde el inventario departamental'
    );

    -- (5) Tickets historicos: sede del departamento del solicitante (snapshot).
    EXECUTE format(
        'UPDATE %1$I.ticket t SET sede_id = d.sede_id '
        'FROM %1$I.usuario u '
        'JOIN %1$I.departamento d ON d.departamento_id = u.departamento_id '
        'WHERE t.usuario_id = u.usuario_id AND t.sede_id IS NULL',
        p_esq
    );

    -- (6) VERIFICACION local antes de devolver (la global va en el bloque principal).
    --     (6.1) Cuadre por producto: stock_sede == inventario departamental.
    EXECUTE format(
        'SELECT count(*) FROM ('
        '  SELECT i.producto_id, sum(i.stock_actual) AS departamental, '
        '         (SELECT coalesce(sum(s.stock_actual), 0) FROM %1$I.stock_sede s '
        '          WHERE s.producto_id = i.producto_id) AS por_sede '
        '  FROM %1$I.inventario i GROUP BY i.producto_id'
        ') t WHERE t.departamental <> t.por_sede',
        p_esq
    ) INTO v_filas;
    IF v_filas > 0 THEN
        RAISE EXCEPTION
            'Verificacion 011 fallida en %: % producto(s) no cuadran entre el inventario departamental y stock_sede.',
            p_esq, v_filas;
    END IF;

    --     (6.2) Cada saldo == suma de sus movimientos de consolidacion ENTRADA.
    EXECUTE format(
        'SELECT count(*) FROM %1$I.stock_sede s WHERE s.stock_actual <> '
        'coalesce((SELECT sum(m.cantidad) FROM %1$I.movimiento_inventario m '
        'WHERE m.stock_sede_id = s.stock_sede_id AND m.tipo_movimiento = %2$L), 0)',
        p_esq, 'ENTRADA'
    ) INTO v_filas;
    IF v_filas > 0 THEN
        RAISE EXCEPTION
            'Verificacion 011 fallida en %: % saldo(s) por sede no cuadran con su consolidacion.',
            p_esq, v_filas;
    END IF;

    --     (6.3) Ningun movimiento nuevo enlaza a la vez stock_sede_id e inventario_id.
    EXECUTE format(
        'SELECT count(*) FROM %1$I.movimiento_inventario '
        'WHERE stock_sede_id IS NOT NULL AND inventario_id IS NOT NULL', p_esq
    ) INTO v_filas;
    IF v_filas > 0 THEN
        RAISE EXCEPTION
            'Verificacion 011 fallida en %: % movimiento(s) nuevo(s) enlazan el inventario legado.',
            p_esq, v_filas;
    END IF;

    --     (6.4) Todo departamento y todo ticket quedan con sede.
    EXECUTE format('SELECT count(*) FROM %1$I.departamento WHERE sede_id IS NULL', p_esq)
        INTO v_filas;
    IF v_filas > 0 THEN
        RAISE EXCEPTION 'Verificacion 011 fallida en %: % departamento(s) sin sede.', p_esq, v_filas;
    END IF;

    EXECUTE format('SELECT count(*) FROM %1$I.ticket WHERE sede_id IS NULL', p_esq)
        INTO v_filas;
    IF v_filas > 0 THEN
        RAISE EXCEPTION 'Verificacion 011 fallida en %: % ticket(s) sin sede.', p_esq, v_filas;
    END IF;
END;
$datos$;

-- -----------------------------------------------------------------------------
-- 1. Migracion (bloque unico y atomico)
-- -----------------------------------------------------------------------------

DO $migracion$
DECLARE
    v_version_anterior constant text := '010.1';
    v_version_objetivo constant text := '011.1';

    v_institucion_id text;
    v_esquema text;
    v_num_sedes integer;
    v_version text;
    v_conteo integer;
    v_filas integer;
    v_total integer := 0;
    v_completos integer := 0;
    v_control_objetivo boolean := false;
BEGIN
    -------------------------------------------------------------------------
    -- FASE 0: PREFLIGHT (solo lectura; aborta sin mutaciones)
    -------------------------------------------------------------------------

    -- (0.1) El esquema de control debe existir con su registro canonico.
    IF to_regclass('control.institucion') IS NULL THEN
        RAISE EXCEPTION
            'Migracion 011 abortada: no existe el esquema de control (control.institucion).';
    END IF;

    -- (0.2) Version reconocible de control: ausente (post-010), 010.1 u objetivo.
    IF to_regclass('control.version_esquema') IS NOT NULL THEN
        SELECT count(*), max(version) INTO v_conteo, v_version FROM control.version_esquema;
        IF v_conteo = 1 AND v_version = v_version_objetivo THEN
            v_control_objetivo := true;
        ELSIF v_conteo = 1 AND v_version = v_version_anterior THEN
            NULL; -- migrable
        ELSIF v_conteo = 0 THEN
            NULL; -- control sin versionar: migrable
        ELSE
            RAISE EXCEPTION
                'Migracion 011 abortada en control: version no reconocida (%) con % fila(s); esperada % o %.',
                v_version, v_conteo, v_version_anterior, v_version_objetivo;
        END IF;
    END IF;

    -- (0.3) Estado parcial de control: estructura 011 sin version objetivo.
    IF NOT v_control_objetivo AND to_regclass('control.sede') IS NOT NULL THEN
        RAISE EXCEPTION
            'Migracion 011 abortada: control tiene estructura 011 parcial sin la version objetivo %; requiere recuperacion manual.',
            v_version_objetivo;
    END IF;

    -- (0.4) Enumerar instituciones y validar cada tenant.
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        v_total := v_total + 1;

        IF to_regnamespace(v_esquema) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 011 abortada: la institucion % no tiene esquema tenant %.',
                v_institucion_id, v_esquema;
        END IF;
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 011 abortada: el tenant % no tiene version_esquema (estado parcial).',
                v_esquema;
        END IF;

        EXECUTE format('SELECT count(*) FROM %I.version_esquema', v_esquema) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Migracion 011 abortada: el tenant % tiene % fila(s) de version_esquema (esperada 1).',
                v_esquema, v_conteo;
        END IF;
        EXECUTE format('SELECT version FROM %I.version_esquema', v_esquema) INTO v_version;

        IF v_version = v_version_objetivo THEN
            -- Ya migrado: la estructura nueva debe estar completa.
            IF to_regclass(format('%I.stock_sede', v_esquema)) IS NULL THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % esta en % pero no tiene stock_sede (estado parcial).',
                    v_esquema, v_version_objetivo;
            END IF;
            v_completos := v_completos + 1;
        ELSIF v_version = v_version_anterior THEN
            -- Estado parcial: estructura 011 sin version objetivo.
            IF to_regclass(format('%I.sede', v_esquema)) IS NOT NULL THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene estructura parcial (sede existe pero la version sigue en %); requiere recuperacion manual.',
                    v_esquema, v_version_anterior;
            END IF;
            IF to_regclass(format('%I.stock_sede', v_esquema)) IS NOT NULL
               OR to_regclass(format('%I.departamento_encargado', v_esquema)) IS NOT NULL THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene estructura 011 parcial sin versionar; requiere recuperacion manual.',
                    v_esquema;
            END IF;

            -- Integridad del legado: inventario, movimientos y tickets resolubles.
            EXECUTE format(
                'SELECT count(*) FROM %I.inventario i '
                'LEFT JOIN %I.departamento d ON d.departamento_id = i.departamento_id '
                'WHERE d.departamento_id IS NULL', v_esquema, v_esquema
            ) INTO v_filas;
            IF v_filas > 0 THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene % fila(s) de inventario sin departamento resoluble.',
                    v_esquema, v_filas;
            END IF;

            EXECUTE format(
                'SELECT count(*) FROM %I.inventario i '
                'LEFT JOIN %I.producto p ON p.producto_id = i.producto_id '
                'WHERE p.producto_id IS NULL', v_esquema, v_esquema
            ) INTO v_filas;
            IF v_filas > 0 THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene % fila(s) de inventario sin producto resoluble.',
                    v_esquema, v_filas;
            END IF;

            EXECUTE format(
                'SELECT count(*) FROM %I.movimiento_inventario m '
                'WHERE m.inventario_id IS NOT NULL AND NOT EXISTS '
                '(SELECT 1 FROM %I.inventario i WHERE i.inventario_id = m.inventario_id)',
                v_esquema, v_esquema
            ) INTO v_filas;
            IF v_filas > 0 THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene % movimiento(s) con inventario_id irresoluble.',
                    v_esquema, v_filas;
            END IF;

            EXECUTE format(
                'SELECT count(*) FROM %I.ticket t '
                'LEFT JOIN %I.usuario u ON u.usuario_id = t.usuario_id '
                'WHERE u.usuario_id IS NULL', v_esquema, v_esquema
            ) INTO v_filas;
            IF v_filas > 0 THEN
                RAISE EXCEPTION
                    'Migracion 011 abortada: el tenant % tiene % ticket(s) sin usuario resoluble.',
                    v_esquema, v_filas;
            END IF;
        ELSE
            RAISE EXCEPTION
                'Migracion 011 abortada: el tenant % tiene version % no reconocida (esperada % o %).',
                v_esquema, v_version, v_version_anterior, v_version_objetivo;
        END IF;
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 1: IDEMPOTENCIA (control y todos los tenants ya en objetivo)
    -------------------------------------------------------------------------
    IF v_control_objetivo AND v_completos = v_total THEN
        RAISE NOTICE '011: nada que migrar; control y los % tenant(s) ya estan en %.',
            v_total, v_version_objetivo;
        RETURN;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 2: CONTROL (estructura canonica ampliada y version)
    -------------------------------------------------------------------------
    IF NOT v_control_objetivo THEN
        PERFORM pg_temp.aplicar_estructura_011('control');

        IF to_regclass('control.version_esquema') IS NULL THEN
            EXECUTE 'CREATE TABLE control.version_esquema ('
                'version_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
                'version VARCHAR(20) NOT NULL, '
                'actualizada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)';
        END IF;

        SELECT count(*) INTO v_conteo FROM control.version_esquema;
        IF v_conteo = 0 THEN
            INSERT INTO control.version_esquema (version) VALUES (v_version_objetivo);
        ELSE
            UPDATE control.version_esquema
            SET version = v_version_objetivo, actualizada_en = CURRENT_TIMESTAMP;
        END IF;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 3: TENANTS (estructura + datos + version)
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format('SELECT version FROM %I.version_esquema', v_esquema) INTO v_version;
        IF v_version = v_version_objetivo THEN
            CONTINUE; -- tenant ya migrado: no se altera nada
        END IF;

        -- Reparto fijo de D-7 en las cuatro instituciones operativas; cualquier
        -- otro tenant recibe una unica "Sede Central".
        v_num_sedes := CASE v_institucion_id
            WHEN 'INST-001' THEN 2
            WHEN 'INST-002' THEN 3
            WHEN 'INST-003' THEN 4
            WHEN 'INST-004' THEN 2
            ELSE 1
        END;

        PERFORM pg_temp.aplicar_estructura_011(v_esquema);
        PERFORM pg_temp.migrar_tenant_011(v_esquema, v_num_sedes);

        -- Version objetivo SOLO al final, tras verificar el tenant.
        EXECUTE format(
            'UPDATE %I.version_esquema SET version = %L, actualizada_en = CURRENT_TIMESTAMP',
            v_esquema, v_version_objetivo
        );
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 4: VERIFICACION GLOBAL
    -------------------------------------------------------------------------
    SELECT count(*) INTO v_conteo FROM control.version_esquema WHERE version = v_version_objetivo;
    IF v_conteo <> 1 THEN
        RAISE EXCEPTION
            'Verificacion global 011 fallida: control no tiene una unica fila de version %.',
            v_version_objetivo;
    END IF;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L',
            v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion global 011 fallida: el tenant % no tiene una unica fila de version %.',
                v_esquema, v_version_objetivo;
        END IF;
    END LOOP;

    RAISE NOTICE
        '011: migracion completada. Control y % tenant(s) en version %; inventario y auditoria legados intactos.',
        v_total, v_version_objetivo;
END;
$migracion$;
