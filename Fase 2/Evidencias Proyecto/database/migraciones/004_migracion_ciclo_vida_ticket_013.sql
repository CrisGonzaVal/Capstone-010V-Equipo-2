-- =============================================================================
-- FEATURE 013 - T5: Migracion operacional del ciclo de vida del ticket (013.1)
-- =============================================================================
-- Lleva una base ya multi-tenant (posterior a la migracion 003 / version `012.1`)
-- al modelo de ciclo de vida del ticket aprobado en
-- `docs/spec/features/013-ciclo-vida-ticket/spec.md` (D-2/D-10), sin semilla
-- destructiva:
--
--   * el catalogo replicado `estado_ticket` (control y cada tenant) recibe la
--     quinta fila `Anulado` (insercion idempotente por NOMBRE; el id es
--     `max(estado_id) + 1` del catalogo receptor, que en un 012.1 tipico da 5,
--     pero no se fija un id hardcodeado);
--   * `historial_transicion_ticket` se crea en control y en cada tenant con la
--     MISMA forma del canonico (`01_esquema.sql` seccion 12b): PK identity,
--     cuatro FKs locales (ticket, estado_ticket x2, usuario) y `motivo
--     VARCHAR(500)` nullable; SIN filas sembradas (AC-12: sin trazabilidad
--     fabricada y sin reconstruccion de transiciones previas);
--   * `version_esquema` de control y de cada tenant sube a `013.1` al final.
--
-- Invariantes de ejecucion (patron de las migraciones 001/002/003, AGENTS §7):
--
--   * NO vive bajo el montaje de initdb. Esta en `database/migraciones/`, un
--     subdirectorio de `database/`; el entrypoint de la imagen PostgreSQL no
--     desciende a subdirectorios (verificado en T8a de 010). Se invoca de forma
--     EXPLICITA, nunca en la instalacion limpia ni en un reinicio.
--   * NO ejecuta la semilla destructiva (`02_datos_semilla.sql`).
--   * NO borra el volumen ni la base. No hay TRUNCATE ni DELETE: los datos de
--     negocio, los mapas y el (no) historial previo quedan intactos.
--   * NO siembra filas de historial: los tickets existentes no reciben
--     transiciones retroactivas; su historial queda vacio hasta la proxima
--     mutacion real (AC-12).
--   * Es un UNICO bloque atomico: preflight y trabajo viven en el mismo `DO`. Si
--     cualquier verificacion falla, el bloque revierte por completo y la base
--     queda SIN CAMBIOS; ninguna `version_esquema` se marca parcialmente.
--   * Es idempotente: una segunda ejecucion detecta control y todos los tenants
--     ya en `013.1` y retorna sin tocar nada operativo.
--
-- Uso (respaldo previo y ventana de mantenimiento obligatorios):
--
--   psql "postgresql://<usuario>:<clave>@<host>:<puerto>/apt_erp" `
--        -v ON_ERROR_STOP=1 -f database/migraciones/004_migracion_ciclo_vida_ticket_013.sql
--
-- El nombre de esquema se reproduce EXACTAMENTE igual que
-- `app.services.tenant_service.nombre_esquema_para_institucion` (ver 001).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Funciones auxiliares de sesion
-- -----------------------------------------------------------------------------

-- Nombre determinista del esquema tenant (espejo en SQL de
-- `tenant_service.nombre_esquema_para_institucion`). Identica a la de 001/002/003.
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
    v_version_anterior constant text := '012.1';
    v_version_objetivo constant text := '013.1';
    --: Descripcion del estado nuevo, identica a la de `02_datos_semilla.sql`
    --: para que instalacion nueva y migrada compartan el mismo catalogo.
    v_descripcion_anulado constant text :=
        'Cancelado antes del despacho; anulado o rechazado con motivo en el historial';

    v_institucion_id text;
    v_esquema text;
    v_version text;
    v_conteo integer;
    v_total integer := 0;
    v_completos integer := 0;
    v_control_objetivo boolean := false;
BEGIN
    -------------------------------------------------------------------------
    -- FASE 0: PREFLIGHT (solo lectura; aborta sin mutaciones)
    -------------------------------------------------------------------------

    -- (0.1) El esquema de control debe existir con su registro canonico y version.
    IF to_regclass('control.institucion') IS NULL THEN
        RAISE EXCEPTION
            'Migracion 013 abortada: no existe el esquema de control (control.institucion).';
    END IF;
    IF to_regclass('control.version_esquema') IS NULL THEN
        RAISE EXCEPTION
            'Migracion 013 abortada: control no tiene version_esquema.';
    END IF;

    -- (0.2) Version reconocible de control: `012.1` (migrable) u objetivo.
    SELECT count(*), max(version) INTO v_conteo, v_version FROM control.version_esquema;
    IF v_conteo = 1 AND v_version = v_version_objetivo THEN
        v_control_objetivo := true;
    ELSIF v_conteo = 1 AND v_version = v_version_anterior THEN
        NULL; -- migrable
    ELSE
        RAISE EXCEPTION
            'Migracion 013 abortada en control: version no reconocida (%) con % fila(s); esperada % o %.',
            v_version, v_conteo, v_version_anterior, v_version_objetivo;
    END IF;

    -- (0.3) Estructura 013 parcial de control sin versionar: aborta en cerrado.
    IF NOT v_control_objetivo THEN
        IF to_regclass('control.historial_transicion_ticket') IS NOT NULL THEN
            RAISE EXCEPTION
                'Migracion 013 abortada: control tiene la estructura 013 parcial (historial_transicion_ticket) sin la version objetivo %; requiere recuperacion manual.',
                v_version_objetivo;
        END IF;
        IF EXISTS (SELECT 1 FROM control.estado_ticket WHERE nombre = 'Anulado') THEN
            RAISE EXCEPTION
                'Migracion 013 abortada: control tiene el estado `Anulado` sin la version objetivo %; estado parcial.',
                v_version_objetivo;
        END IF;
    END IF;

    -- (0.4) Enumerar instituciones y validar cada tenant.
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);
        v_total := v_total + 1;

        IF to_regnamespace(v_esquema) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 013 abortada: la institucion % no tiene esquema tenant %.',
                v_institucion_id, v_esquema;
        END IF;
        IF to_regclass(format('%I.version_esquema', v_esquema)) IS NULL THEN
            RAISE EXCEPTION
                'Migracion 013 abortada: el tenant % no tiene version_esquema (estado parcial).',
                v_esquema;
        END IF;

        EXECUTE format('SELECT count(*), max(version) FROM %I.version_esquema', v_esquema)
            INTO v_conteo, v_version;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Migracion 013 abortada: el tenant % tiene % fila(s) de version_esquema (esperada 1).',
                v_esquema, v_conteo;
        END IF;

        IF v_version = v_version_objetivo THEN
            -- Ya migrado: la estructura 013 debe estar completa (tabla y estado).
            IF to_regclass(format('%I.historial_transicion_ticket', v_esquema)) IS NULL THEN
                RAISE EXCEPTION
                    'Migracion 013 abortada: el tenant % esta en % pero no tiene historial_transicion_ticket (estado parcial).',
                    v_esquema, v_version_objetivo;
            END IF;
            EXECUTE format(
                'SELECT count(*) FROM %I.estado_ticket WHERE nombre = ''Anulado''', v_esquema
            ) INTO v_conteo;
            IF v_conteo <> 1 THEN
                RAISE EXCEPTION
                    'Migracion 013 abortada: el tenant % esta en % pero tiene % fila(s) `Anulado` (esperada 1; estado parcial).',
                    v_esquema, v_version_objetivo, v_conteo;
            END IF;
            v_completos := v_completos + 1;
        ELSIF v_version = v_version_anterior THEN
            -- Estructura 013 parcial del tenant sin versionar: aborta en cerrado.
            IF to_regclass(format('%I.historial_transicion_ticket', v_esquema)) IS NOT NULL THEN
                RAISE EXCEPTION
                    'Migracion 013 abortada: el tenant % tiene la estructura 013 parcial (historial_transicion_ticket) sin la version objetivo %; requiere recuperacion manual.',
                    v_esquema, v_version_objetivo;
            END IF;
            EXECUTE format(
                'SELECT count(*) FROM %I.estado_ticket WHERE nombre = ''Anulado''', v_esquema
            ) INTO v_conteo;
            IF v_conteo > 0 THEN
                RAISE EXCEPTION
                    'Migracion 013 abortada: el tenant % tiene el estado `Anulado` sin la version objetivo %; estado parcial.',
                    v_esquema, v_version_objetivo;
            END IF;
        ELSE
            RAISE EXCEPTION
                'Migracion 013 abortada: el tenant % tiene version % no reconocida (esperada % o %).',
                v_esquema, v_version, v_version_anterior, v_version_objetivo;
        END IF;
    END LOOP;

    -------------------------------------------------------------------------
    -- FASE 1: IDEMPOTENCIA (control y todos los tenants ya en objetivo)
    -------------------------------------------------------------------------
    IF v_control_objetivo AND v_completos = v_total THEN
        RAISE NOTICE '013: nada que migrar; control y los % tenant(s) ya estan en %.',
            v_total, v_version_objetivo;
        RETURN;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 2: CONTROL (`Anulado`, tabla del historial, version)
    -------------------------------------------------------------------------
    IF NOT v_control_objetivo THEN
        -- Quinta fila del catalogo por NOMBRE; el id respeta el orden del
        -- catalogo receptor (`max(estado_id) + 1`, no un id fijo). El `WHERE
        -- NOT EXISTS` de la consulta-SELECT fila la unica fila emitida, de modo
        -- que una reejecucion no duplica el estado.
        EXECUTE '
            INSERT INTO control.estado_ticket (estado_id, nombre, descripcion)
            OVERRIDING SYSTEM VALUE
            SELECT (SELECT COALESCE(max(estado_id), 0) + 1 FROM control.estado_ticket),
                   ''Anulado'',
                   $1
            WHERE NOT EXISTS (SELECT 1 FROM control.estado_ticket WHERE nombre = ''Anulado'')'
            USING v_descripcion_anulado;

        EXECUTE 'CREATE TABLE IF NOT EXISTS control.historial_transicion_ticket ('
            'historial_transicion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
            'ticket_id INTEGER NOT NULL, '
            'estado_origen_id INTEGER, '
            'estado_destino_id INTEGER NOT NULL, '
            'usuario_id INTEGER NOT NULL, '
            'fecha_transicion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
            'motivo VARCHAR(500), '
            'CONSTRAINT historial_transicion_ticket_ticket_fk '
            'FOREIGN KEY (ticket_id) REFERENCES control.ticket(ticket_id), '
            'CONSTRAINT historial_transicion_ticket_estado_origen_fk '
            'FOREIGN KEY (estado_origen_id) REFERENCES control.estado_ticket(estado_id), '
            'CONSTRAINT historial_transicion_ticket_estado_destino_fk '
            'FOREIGN KEY (estado_destino_id) REFERENCES control.estado_ticket(estado_id), '
            'CONSTRAINT historial_transicion_ticket_usuario_fk '
            'FOREIGN KEY (usuario_id) REFERENCES control.usuario(usuario_id))';

        -- Verificacion local: control queda completo antes de tocar tenants.
        SELECT count(*) INTO v_conteo FROM control.estado_ticket WHERE nombre = 'Anulado';
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion 013 fallida: control tiene % fila(s) `Anulado` (esperada 1).',
                v_conteo;
        END IF;
        IF to_regclass('control.historial_transicion_ticket') IS NULL THEN
            RAISE EXCEPTION
                'Verificacion 013 fallida: control no tiene historial_transicion_ticket.';
        END IF;

        -- Version de control SOLO al final de su propia fase.
        UPDATE control.version_esquema
        SET version = v_version_objetivo, actualizada_en = CURRENT_TIMESTAMP;
    END IF;

    -------------------------------------------------------------------------
    -- FASE 3: TENANTS (`Anulado`, tabla del historial y version)
    -------------------------------------------------------------------------
    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format('SELECT version FROM %I.version_esquema', v_esquema) INTO v_version;
        IF v_version = v_version_objetivo THEN
            CONTINUE; -- tenant ya migrado: no se altera nada
        END IF;

        -- Catalogo: misma insercion idempotente por nombre, con el max+1 del
        -- catalogo LOCAL del tenant.
        EXECUTE format(
            'INSERT INTO %I.estado_ticket (estado_id, nombre, descripcion) '
            'OVERRIDING SYSTEM VALUE '
            'SELECT (SELECT COALESCE(max(estado_id), 0) + 1 FROM %I.estado_ticket), '
            '''Anulado'', $1 '
            'WHERE NOT EXISTS (SELECT 1 FROM %I.estado_ticket WHERE nombre = ''Anulado'')',
            v_esquema, v_esquema, v_esquema
        ) USING v_descripcion_anulado;

        -- Tabla del historial con FKs locales al tenant (sin cross-schema).
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I.historial_transicion_ticket ('
            'historial_transicion_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, '
            'ticket_id INTEGER NOT NULL, '
            'estado_origen_id INTEGER, '
            'estado_destino_id INTEGER NOT NULL, '
            'usuario_id INTEGER NOT NULL, '
            'fecha_transicion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, '
            'motivo VARCHAR(500), '
            'CONSTRAINT historial_transicion_ticket_ticket_fk '
            'FOREIGN KEY (ticket_id) REFERENCES %I.ticket(ticket_id), '
            'CONSTRAINT historial_transicion_ticket_estado_origen_fk '
            'FOREIGN KEY (estado_origen_id) REFERENCES %I.estado_ticket(estado_id), '
            'CONSTRAINT historial_transicion_ticket_estado_destino_fk '
            'FOREIGN KEY (estado_destino_id) REFERENCES %I.estado_ticket(estado_id), '
            'CONSTRAINT historial_transicion_ticket_usuario_fk '
            'FOREIGN KEY (usuario_id) REFERENCES %I.usuario(usuario_id))',
            v_esquema, v_esquema, v_esquema, v_esquema, v_esquema
        );

        -- Verificacion local: el tenant queda completo antes de versionar.
        EXECUTE format(
            'SELECT count(*) FROM %I.estado_ticket WHERE nombre = ''Anulado''', v_esquema
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion 013 fallida: el tenant % tiene % fila(s) `Anulado` (esperada 1).',
                v_esquema, v_conteo;
        END IF;
        IF to_regclass(format('%I.historial_transicion_ticket', v_esquema)) IS NULL THEN
            RAISE EXCEPTION
                'Verificacion 013 fallida: el tenant % no tiene historial_transicion_ticket.',
                v_esquema;
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
            'Verificacion global 013 fallida: control no tiene una unica fila de version %.',
            v_version_objetivo;
    END IF;
    SELECT count(*) INTO v_conteo FROM control.estado_ticket WHERE nombre = 'Anulado';
    IF v_conteo <> 1 THEN
        RAISE EXCEPTION
            'Verificacion global 013 fallida: control tiene % fila(s) `Anulado` (esperada 1).',
            v_conteo;
    END IF;
    IF to_regclass('control.historial_transicion_ticket') IS NULL THEN
        RAISE EXCEPTION
            'Verificacion global 013 fallida: control no tiene historial_transicion_ticket.';
    END IF;

    FOR v_institucion_id IN SELECT institucion_id FROM control.institucion ORDER BY institucion_id LOOP
        v_esquema := pg_temp.nombre_esquema_tenant(v_institucion_id);

        EXECUTE format(
            'SELECT count(*) FROM %I.version_esquema WHERE version = %L',
            v_esquema, v_version_objetivo
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion global 013 fallida: el tenant % no tiene una unica fila de version %.',
                v_esquema, v_version_objetivo;
        END IF;

        EXECUTE format(
            'SELECT count(*) FROM %I.estado_ticket WHERE nombre = ''Anulado''', v_esquema
        ) INTO v_conteo;
        IF v_conteo <> 1 THEN
            RAISE EXCEPTION
                'Verificacion global 013 fallida: el tenant % tiene % fila(s) `Anulado` (esperada 1).',
                v_esquema, v_conteo;
        END IF;

        IF to_regclass(format('%I.historial_transicion_ticket', v_esquema)) IS NULL THEN
            RAISE EXCEPTION
                'Verificacion global 013 fallida: el tenant % no tiene historial_transicion_ticket.',
                v_esquema;
        END IF;
    END LOOP;

    RAISE NOTICE
        '013: migracion completada. Control y % tenant(s) en version %; estado `Anulado` e historial_transicion_ticket presentes, datos/mapas/historial previo intactos.',
        v_total, v_version_objetivo;
END;
$migracion$;
