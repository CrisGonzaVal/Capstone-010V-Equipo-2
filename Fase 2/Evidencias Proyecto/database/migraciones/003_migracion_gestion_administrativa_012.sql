-- =============================================================================
-- FEATURE 012 - T4: Migracion operacional a la gestion administrativa (012.1)
-- =============================================================================
-- Lleva una base ya multi-tenant (posterior a la migracion 002 / version `011.1`)
-- al modelo de gestion administrativa aprobado en
-- `docs/spec/features/012-gestion-administrativa/spec.md` (D-1/D-2/D-6) y el
-- diseno tecnico (`diseno-tecnico.md` §3), sin semilla destructiva:
--
--   * `control.institucion` recibe el estado de ciclo de vida `activo`
--     (BOOLEAN NOT NULL DEFAULT TRUE); el resto de columnas canonicas no cambia;
--   * se crea la estructura auxiliar `control.funcion_institucion` (una fila por
--     pareja `(institucion_id, funcion)`, FK local a `control.institucion`, estado
--     `habilitada` y CHECK del conjunto cerrado de seis capacidades); se pueblan
--     las seis filas habilitadas por cada institucion existente;
--   * `sede` y `departamento` (control y cada tenant) reciben la columna logica
--     `activo` (AC-6/AC-11), sin borrar filas ni historial;
--   * el espejo tenant `institucion` se reduce a las dos columnas aprobadas
--     (`institucion_id`, `nombre`): las columnas legadas `rut`/`direccion` que
--     habian quedado duplicadas del canonico se eliminan del espejo, preservando
--     las filas y sin copiar `activo` ni `funcion_institucion` al tenant (D-1);
--   * `version_esquema` de control y de cada tenant sube a `012.1` al final.
--
-- Invariantes de ejecucion (patron de las migraciones 001/002, AGENTS §7):
--
--   * NO vive bajo el montaje de initdb. Esta en `database/migraciones/`, un
--     subdirectorio de `database/`; el entrypoint de la imagen PostgreSQL no
--     desciende a subdirectorios (verificado en T8a de 010). Se invoca de forma
--     EXPLICITA, nunca en la instalacion limpia ni en un reinicio.
--   * NO ejecuta la semilla destructiva (`02_datos_semilla.sql`).
--   * NO borra el volumen ni la base. El esquema legado `public` conserva sus
--     tablas y filas intactas. No hay TRUNCATE ni DELETE.
--   * NO altera mapas (`mapa_usuario_esquema`), datos de negocio ni historial de
--     tickets/stock/movimientos: solo amplia el DDL y siembra las capacidades.
--   * Es un UNICO bloque atomico: preflight y trabajo viven en el mismo `DO`. Si
--     cualquier verificacion falla, el bloque revierte por completo y la base
--     queda SIN CAMBIOS; ninguna `version_esquema` se marca parcialmente.
--   * Es idempotente: una segunda ejecucion detecta control y todos los tenants
--     ya en `012.1` y retorna sin tocar nada operativo.
--
-- Uso (respaldo previo y ventana de mantenimiento obligatorios):
--
--   psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" `
--        -v ON_ERROR_STOP=1 -f database/migraciones/003_migracion_gestion_administrativa_012.sql
--
-- El nombre de esquema se reproduce EXACTAMENTE igual que
-- `app.services.tenant_service.nombre_esquema_para_institucion` (ver 001).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Funciones auxiliares de sesion
-- -----------------------------------------------------------------------------

-- Nombre determinista del esquema tenant (espejo en SQL de
-- `tenant_service.nombre_esquema_para_institucion`). Identica a la de 001/002.
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

-- -----------------------------------------------------------------------------
-- 1. Migracion (bloque unico y atomico)
-- -----------------------------------------------------------------------------

DO $migracion$
DECLARE
    v_version_anterior constant text := '011.1';
    v_version_objetivo constant text := '012.1';

    v_institucion_id text;
    v_esquema text;
    v_version text;
    v_conteo integer;
    v_total integer := 0;
    v_completos integer := 0;
    v_control_objetivo boolean := false;
    v_columnas text[];
BEGIN
    -------------------------------------------------------------------------
    -- FASE 0: PREFLIGHT (solo lectura; aborta sin mutaciones)
    -------------------------------------------------------------------------

    -- (0.1) El esquema de control debe existir con su registro canonico y version.
    IF to_regclass('control.institucion') IS NULL THEN
        RAISE EXCEPTION
            'Migracion 012 abortada: no existe el esquema de control (control.institucion).';
    END IF;
    IF to_regclass('control.version_esquema') IS NULL THEN
        RAISE EXCEPTION
            'Migracion 012 abortada: control no tiene version_esquema.';
    END IF;

    -- (0.2) Version reconocible de control: `011.1` (migrable) u objetivo.
    SELECT count(*), max(version) INTO v_conteo, v_version FROM control.version_esquema;
    IF v_conteo = 1 AND v_version = v_version_objetivo THEN
        v_control_objetivo := true;
    ELSIF v_conteo = 1 AND v_version = v_version_anterior THEN
        NULL; -- migrable
    ELSE
        RAISE EXCEPTION
            'Migracion 012 abortada en control: version no reconocida (%) con % fila(s); esperada % o %.',
            v_version, v_conteo, v_version_anterior, v_version_objetivo;
    END IF;

    -- (0.3) Estado parcial de control: estructura 012 sin la version objetivo.
    IF NOT v_control_objetivo AND to_regclass('control.funcion_institucion') IS NOT NULL THEN
        RAISE EXCEPTION
            'Migracion 012 abortada: control tiene la estructura 012 parcial (funcion_institucion) sin la version objetivo %; requiere recuperacion manual.',
            v_version_objetivo;
    END IF;
    IF NOT v_control_objetivo AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'control' AND table_name = 'institucion'
          AND column_name = 'activo'
    ) THEN
        RAISE EXCEPTION
            'Migracion 012 abortada: control.institucion ya tiene `activo` sin la version objetivo %; estado parcial.',
            v_version_objetivo;
    END IF;

    -- (0.4) Enumerar instituciones y validar cada tenant.
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        v_total := v_total + 1;

        IF to_regnamespace(v_esquema) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 012 abortada: la institucion % no tiene esquema tenant %.',
                v_institucion_id, v_esquema;
        END IF;
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 012 abortada: el tenant % no tiene version_esquema (estado parcial).',
                v_esquema;
        END IF;

        EXECUTE format('SELECT count(*), max(version) FROM %I.version_esquema', v_esquema)
            INTO v_conteo, v_version;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Migracion 012 abortada: el tenant % tiene % fila(s) de version_esquema (esperada 1).',
                v_esquema, v_conteo;
        END IF;

        IF v_version = v_version_objetivo THEN
            -- Ya migrado: la estructura 012 debe estar completa y el espejo reducido.
            IF to_regclass(format('%I.sede', v_esquema)) IS NULL THEN
                RAISE EXCEPTION
                    'Migracion 012 abortada: el tenant % esta en % pero no tiene sede (estado parcial).',
                    v_esquema, v_version_objetivo;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = v_esquema AND table_name = 'sede'
                  AND column_name = 'activo'
            ) OR NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = v_esquema AND table_name = 'departamento'
                  AND column_name = 'activo'
            ) THEN
                RAISE EXCEPTION
                    'Migracion 012 abortada: el tenant % esta en % pero sede/departamento no tienen `activo` (estado parcial).',
                    v_esquema, v_version_objetivo;
            END IF;
            SELECT array_agg(column_name::text ORDER BY column_name) INTO v_columnas
            FROM information_schema.columns
            WHERE table_schema = v_esquema AND table_name = 'institucion';
            IF v_columnas IS DISTINCT FROM ARRAY['institucion_id', 'nombre']::text[] THEN
                RAISE EXCEPTION
                    'Migracion 012 abortada: el espejo tenant % no tiene las dos columnas aprobadas (%); estado parcial.',
                    v_esquema, v_columnas;
            END IF;
            v_completos := v_completos + 1;
        ELSIF v_version = v_version_anterior THEN
            -- Estado parcial de 012 sin versionar: aborta en cerrado.
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = v_esquema AND table_name = 'sede'
                  AND column_name = 'activo'
            ) THEN
                RAISE EXCEPTION
                    'Migracion 012 abortada: el tenant % tiene la estructura 012 parcial (sede.activo) sin la version objetivo; requiere recuperacion manual.',
                    v_esquema;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = v_esquema AND table_name = 'institucion'
                  AND column_name = 'rut'
            ) THEN
                RAISE EXCEPTION
                    'Migracion 012 abortada: el tenant % ya tiene el espejo reducido sin la version objetivo; estado parcial.',
                    v_esquema;
            END IF;
        ELSE
            RAISE EXCEPTION
                'Migracion 012 abortada: el tenant % tiene version % no reconocida (esperada % o %).',
                v_esquema, v_version, v_version_anterior, v_version_objetivo;
        END IF;
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 1: IDEMPOTENCIA (control y todos los tenants ya en objetivo)
    -------------------------------------------------------------------------
    IF v_control_objetivo AND v_completos = v_total THEN
        RAISE NOTICE '012: nada que migrar; control y los % tenant(s) ya estan en %.',
            v_total, v_version_objetivo;
        RETURN;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 2: CONTROL (activo, estructura auxiliar, seis capacidades, version)
    -------------------------------------------------------------------------
    IF NOT v_control_objetivo THEN
        EXECUTE 'ALTER TABLE control.institucion '
            'ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE';

        -- `sede`/`departamento` de control reciben `activo` (AC-6/AC-11). Son
        -- tablas del contexto global; en la base real de 011.1 ya existen.
        EXECUTE 'ALTER TABLE control.sede '
            'ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE';
        EXECUTE 'ALTER TABLE control.departamento '
            'ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE';

        -- Estructura auxiliar SOLO de control (nunca se copia a un tenant).
        EXECUTE 'CREATE TABLE IF NOT EXISTS control.funcion_institucion ('
            'institucion_id VARCHAR(20) NOT NULL, '
            'funcion VARCHAR(50) NOT NULL, '
            'habilitada BOOLEAN NOT NULL, '
            'CONSTRAINT funcion_institucion_pk PRIMARY KEY (institucion_id, funcion), '
            'CONSTRAINT funcion_institucion_institucion_fk FOREIGN KEY (institucion_id) '
            'REFERENCES control.institucion (institucion_id), '
            'CONSTRAINT funcion_institucion_funcion_ck CHECK (funcion IN '
            '(''catalogo'', ''inventario'', ''tickets'', ''kanban'', ''dashboard'', ''gestion_organizacional'')))';

        -- Seis filas habilitadas por cada institucion existente (idempotente).
        EXECUTE '
            INSERT INTO control.funcion_institucion (institucion_id, funcion, habilitada)
            SELECT i.institucion_id, f.funcion, TRUE
            FROM control.institucion i
            CROSS JOIN (VALUES (''catalogo''), (''inventario''), (''tickets''),
                               (''kanban''), (''dashboard''), (''gestion_organizacional''))
                        AS f(funcion)
            ON CONFLICT (institucion_id, funcion) DO NOTHING';

        -- Version de control SOLO al final de su propia fase.
        UPDATE control.version_esquema
        SET version = v_version_objetivo, actualizada_en = CURRENT_TIMESTAMP;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 3: TENANTS (activo, espejo reducido y version)
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format('SELECT version FROM %I.version_esquema', v_esquema) INTO v_version;
        IF v_version = v_version_objetivo THEN
            CONTINUE; -- tenant ya migrado: no se altera nada
        END IF;

        EXECUTE format('ALTER TABLE %I.sede '
            'ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE', v_esquema);
        EXECUTE format('ALTER TABLE %I.departamento '
            'ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE', v_esquema);

        -- Espejo tenant reducido a las dos columnas aprobadas (D-1). Las columnas
        -- legadas `rut`/`direccion` duplicaban el canonico de control; se eliminan
        -- del espejo preservando filas y sin copiar `activo` ni capacidades.
        EXECUTE format('ALTER TABLE %I.institucion DROP COLUMN IF EXISTS rut', v_esquema);
        EXECUTE format('ALTER TABLE %I.institucion DROP COLUMN IF EXISTS direccion', v_esquema);

        -- Verificacion local: espejo exactamente con las dos columnas aprobadas.
        SELECT array_agg(column_name::text ORDER BY column_name) INTO v_columnas
        FROM information_schema.columns
        WHERE table_schema = v_esquema AND table_name = 'institucion';
        IF v_columnas IS DISTINCT FROM ARRAY['institucion_id', 'nombre']::text[] THEN
            RAISE EXCEPTION
                'Verificacion 012 fallida: el espejo del tenant % no quedo en dos columnas (%).',
                v_esquema, v_columnas;
        END IF;

        -- Version objetivo SOLO al final, tras verificar el tenant.
        EXECUTE format(
            'UPDATE %I.version_esquema SET version = %L, actualizada_en = CURRENT_TIMESTAMP',
            v_esquema, v_version_objetivo
        );
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 4: VERIFICACION GLOBAL (fail-closed)
    -------------------------------------------------------------------------
    SELECT count(*) INTO v_conteo
    FROM control.version_esquema WHERE version = v_version_objetivo;
    IF v_conteo <> 1 THEN
        RAISE EXCEPTION
            'Verificacion global 012 fallida: control no tiene una unica fila de version %.',
            v_version_objetivo;
    END IF;

    -- Control: exactamente seis capacidades habilitadas por institucion.
    SELECT count(*) INTO v_conteo
    FROM control.institucion i
    WHERE (SELECT count(*) FROM control.funcion_institucion f
           WHERE f.institucion_id = i.institucion_id) <> 6;
    IF v_conteo > 0 THEN
        RAISE EXCEPTION
            'Verificacion global 012 fallida: % institucion(es) de control sin seis capacidades.',
            v_conteo;
    END IF;
    IF EXISTS (SELECT 1 FROM control.funcion_institucion WHERE NOT habilitada) THEN
        RAISE EXCEPTION
            'Verificacion global 012 fallida: hay capacidades iniciales deshabilitadas.';
    END IF;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L',
            v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion global 012 fallida: el tenant % no tiene una unica fila de version %.',
                v_esquema, v_version_objetivo;
        END IF;

        SELECT array_agg(column_name::text ORDER BY column_name) INTO v_columnas
        FROM information_schema.columns
        WHERE table_schema = v_esquema AND table_name = 'institucion';
        IF v_columnas IS DISTINCT FROM ARRAY['institucion_id', 'nombre']::text[] THEN
            RAISE EXCEPTION
                'Verificacion global 012 fallida: el espejo del tenant % no esta en dos columnas (%).',
                v_esquema, v_columnas;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = v_esquema AND table_name = 'sede'
              AND column_name = 'activo'
        ) OR NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = v_esquema AND table_name = 'departamento'
              AND column_name = 'activo'
        ) THEN
            RAISE EXCEPTION
                'Verificacion global 012 fallida: el tenant % no tiene `activo` en sede/departamento.',
                v_esquema;
        END IF;
    END LOOP;

    RAISE NOTICE
        '012: migracion completada. Control y % tenant(s) en version %; espejo de dos columnas, seis capacidades por institucion, datos/mapas/historial intactos.',
        v_total, v_version_objetivo;
END;
$migracion$;
