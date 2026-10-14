-- =====================================================
-- COMPUSTOCK ERP - MIGRACION 008: PARTICIONAMIENTO POR INSTITUCION
-- Base de datos: apt_erp
-- PostgreSQL 16
-- =====================================================
--
-- PROPOSITO
--   Pasar una base LEGADA (catalogo global) al modelo particionado por
--   institucion de la Feature 008 (ver docs/spec/stack.md, seccion "Modelo
--   relacional y particionamiento por institucion"). Anade pertenencia
--   institucional a `categoria`, `producto`, `inventario`, `ticket` y
--   `detalle_ticket`, y las claves unicas/FK compuestas que impiden
--   referencias cruzadas entre instituciones.
--
--   NO reinicializa el volumen, NO trunca y NO ejecuta la semilla. Preserva
--   TODOS los identificadores y filas operativas (usuarios, departamentos,
--   tickets, detalles, inventario, movimientos). Es la alternativa explicita a
--   borrar el volumen, exigida por D-6, AC-14, AC-15 y AC-20.
--
-- QUE HACE (en una sola transaccion atomica: un DO block)
--   1. FASE DE DETECCION (sin cambios): infiere la institucion candidata de
--      cada producto legado por sus referencias ya persistidas y la de cada
--      categoria por sus productos. Si un registro es ambiguo ABORTA antes de
--      tocar el esquema, identificando entidad e ID (fail-closed).
--   2. Solo si no hay ambiguedad, aplica el DDL y rellena la pertenencia.
--
-- ALGORITMO DE INFERENCIA (determinista, en este orden)
--   a) PRODUCTOS: candidatos por referencias directas:
--        - inventario.producto_id -> departamento.institucion_id
--        - detalle_ticket.producto_id -> ticket.usuario_id -> usuario.departamento_id
--          -> departamento.institucion_id
--      * Si todas las referencias de un producto apuntan a UNA institucion,
--        esa es su institucion.
--      * Si apuntan a DOS o mas instituciones distintas -> AMBIGUO: aborta.
--   b) CATEGORIAS: candidatos = instituciones de sus productos ya asignados.
--      * Una sola -> esa. * Dos o mas -> AMBIGUO: aborta.
--   c) PROPAGACION categoria -> producto: un producto sin referencias directas
--      hereda la institucion de su categoria (si ya quedo asignada).
--   d) REGLA DE VACIO (0 referencias): el catalogo SIN USO no es ambiguo (no
--      hay evidencia en conflicto). Se asigna de forma determinista a la
--      PRIMERA institucion por orden de id (`min(institucion_id)`). Se elige
--      esta regla y no un aborto porque el vacio no contradice dato operativo
--      alguno y abortar bloquearia migraciones normales con catalogo no usado.
--      Si el operador quiere otro dueno, basta con crear una referencia antes
--      de migrar (o corregir despues del alta). Queda documentado aqui.
--      Si NO existiera ninguna institucion no se puede migrar: aborta.
--
-- CASOS AMBIGUOS - CORRECCION MANUAL
--   La spec (D-6, AC-14) exige NO reasignar automaticamente: el operador
--   corrige los datos y reintenta. Para localizar los registros ambiguos:
--
--     SELECT i.producto_id, d.institucion_id
--       FROM inventario i JOIN departamento d USING (departamento_id)
--     UNION
--     SELECT dt.producto_id, dep.institucion_id
--       FROM detalle_ticket dt
--       JOIN ticket t USING (ticket_id)
--       JOIN usuario u USING (usuario_id)
--       JOIN departamento dep USING (departamento_id)
--     ORDER BY 1, 2;
--
--   Cada producto debe aparecer con UNA sola institucion. Si aparece con dos,
--   hay una referencia cruzada real: un mismo producto es stock de una
--   institucion y a la vez pedido por un ticket de otra. Correccion tipica:
--   alinear la referencia ofensora con la institucion duena del producto, por
--   ejemplo reasignar el solicitante del ticket (`UPDATE ticket SET usuario_id
--   = ... WHERE ticket_id = ...`) o mover el detalle a un producto de la
--   institucion del ticket, o mover la fila de inventario al departamento
--   correcto. Tras corregir, reintentar la migracion completa.
--
-- IDEMPOTENCIA
--   La migracion empieza comprobando si existe `categoria.institucion_id`. Si
--   ya existe (instalacion nueva con `01_esquema.sql` nuevo, o segunda
--   ejecucion) termina con un NOTICE y no toca nada. Todo el cuerpo corre en
--   un unico DO block, asi que es atomico: si aborta por ambiguedad, ningun
--   cambio (columnas, constraints ni filas) queda aplicado.
--
-- ORDEN DE EJECUCION
--   El prefijo `98_` corre justo antes de `99_migracion_retiro_password.sql`
--   en orden alfabetico. En un volumen NUEVO, /docker-entrypoint-initdb.d
--   ejecuta `01`, `02`, `98`, `99`: como `01` ya crea el modelo particionado,
--   `98` detecta "ya migrado" y sale sin tocar nada. En una base LEGADA hay
--   que aplicarla a mano. Mantener el orden: no renombrar `99_`.
--
-- APLICACION MANUAL EN UNA BASE YA INICIALIZADA
--   Un volumen preexistente NO vuelve a ejecutar /docker-entrypoint-initdb.d.
--   Desde la raiz del proyecto, en cmd.exe (NO en PowerShell: su pipe corrompe
--   la entrada por codificacion):
--
--     docker exec -i compustock_db psql -U postgres -d apt_erp -v ON_ERROR_STOP=1 < database\98_migracion_particionamiento_institucional.sql
--
--   Alternativa con psql en el host (si esta instalado):
--
--     psql -h localhost -p 5433 -U postgres -d apt_erp -v ON_ERROR_STOP=1 -f database/98_migracion_particionamiento_institucional.sql
--
--   Verificacion sugerida (conteos y pertenencia, antes/despues):
--
--     SELECT 'producto' t, count(*) FROM producto
--     UNION ALL SELECT 'categoria', count(*) FROM categoria
--     UNION ALL SELECT 'inventario', count(*) FROM inventario
--     UNION ALL SELECT 'ticket', count(*) FROM ticket
--     UNION ALL SELECT 'detalle_ticket', count(*) FROM detalle_ticket
--     UNION ALL SELECT 'movimiento_inventario', count(*) FROM movimiento_inventario;
--
--     SELECT institucion_id, count(*) FROM producto GROUP BY 1 ORDER BY 1;
--
-- =====================================================

DO $$
DECLARE
    v_ya_migrado boolean;
    v_amb_prod   text;
    v_amb_cat    text;
    v_fallback   varchar(20);
BEGIN
    -- -----------------------------------------------------
    -- 0. GUARD DE IDEMPOTENCIA
    -- -----------------------------------------------------
    SELECT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name   = 'categoria'
           AND column_name  = 'institucion_id'
    ) INTO v_ya_migrado;

    IF v_ya_migrado THEN
        RAISE NOTICE '008: la base ya esta particionada (categoria.institucion_id existe). Migracion omitida (no-op).';
        RETURN;
    END IF;

    -- -----------------------------------------------------
    -- 1. FASE DE DETECCION (SIN DDL): candidatos e inferencia
    -- -----------------------------------------------------

    -- 1.1 Candidatos directos de institucion por producto.
    CREATE TEMP TABLE tmp_cand_producto (
        producto_id   integer,
        institucion_id varchar(20)
    ) ON COMMIT DROP;

    INSERT INTO tmp_cand_producto (producto_id, institucion_id)
    -- Desde inventario (institucion del departamento).
    SELECT i.producto_id, d.institucion_id
      FROM inventario i
      JOIN departamento d USING (departamento_id)
    UNION
    -- Desde detalle_ticket -> ticket -> usuario -> departamento.
    SELECT dt.producto_id, dep.institucion_id
      FROM detalle_ticket dt
      JOIN ticket t USING (ticket_id)
      JOIN usuario u USING (usuario_id)
      JOIN departamento dep USING (departamento_id);

    -- 1.2 Detectar productos ambiguos (>1 institucion candidata).
    SELECT string_agg(
               format('producto %s referenciado por [%s]', x.producto_id, x.insts),
               '; ' ORDER BY x.producto_id)
      INTO v_amb_prod
      FROM (
            SELECT producto_id,
                   string_agg(DISTINCT institucion_id, ', ' ORDER BY institucion_id) AS insts
              FROM tmp_cand_producto
             GROUP BY producto_id
            HAVING count(DISTINCT institucion_id) > 1
           ) x;

    -- 1.3 Asignacion de productos inequivocos (una sola institucion candidata).
    CREATE TEMP TABLE tmp_asig_producto (
        producto_id   integer PRIMARY KEY,
        institucion_id varchar(20)
    ) ON COMMIT DROP;

    INSERT INTO tmp_asig_producto (producto_id, institucion_id)
    SELECT producto_id, min(institucion_id)
      FROM tmp_cand_producto
     GROUP BY producto_id
    HAVING count(DISTINCT institucion_id) = 1;

    -- 1.4 Detectar categorias ambiguas segun sus productos ya asignados.
    SELECT string_agg(
               format('categoria %s con productos de [%s]', x.categoria_id, x.insts),
               '; ' ORDER BY x.categoria_id)
      INTO v_amb_cat
      FROM (
            SELECT p.categoria_id,
                   string_agg(DISTINCT a.institucion_id, ', ' ORDER BY a.institucion_id) AS insts
              FROM producto p
              JOIN tmp_asig_producto a USING (producto_id)
             GROUP BY p.categoria_id
            HAVING count(DISTINCT a.institucion_id) > 1
           ) x;

    -- 1.5 ABORTO FAIL-CLOSED: antes de cualquier DDL.
    IF v_amb_prod IS NOT NULL OR v_amb_cat IS NOT NULL THEN
        RAISE EXCEPTION
            '008 migracion ABORTADA por ambiguedad institucional (rollback completo, nada aplicado). Corrija manualmente y reintente. Ambiguos -> %. %',
            COALESCE(v_amb_prod, 'sin productos ambiguos'),
            COALESCE(v_amb_cat, 'sin categorias ambiguas');
    END IF;

    -- 1.6 Asignacion de categorias inequivocas (una sola institucion).
    CREATE TEMP TABLE tmp_asig_categoria (
        categoria_id  integer PRIMARY KEY,
        institucion_id varchar(20)
    ) ON COMMIT DROP;

    INSERT INTO tmp_asig_categoria (categoria_id, institucion_id)
    SELECT p.categoria_id, min(a.institucion_id)
      FROM producto p
      JOIN tmp_asig_producto a USING (producto_id)
     GROUP BY p.categoria_id
    HAVING count(DISTINCT a.institucion_id) = 1;

    -- 1.7 Propagacion categoria -> producto (productos sin referencias).
    INSERT INTO tmp_asig_producto (producto_id, institucion_id)
    SELECT p.producto_id, c.institucion_id
      FROM producto p
      JOIN tmp_asig_categoria c USING (categoria_id)
      LEFT JOIN tmp_asig_producto a USING (producto_id)
     WHERE a.producto_id IS NULL;

    -- 1.8 Regla de vacio: institucion por defecto (primera por id).
    SELECT min(institucion_id) INTO v_fallback FROM institucion;

    -- Categorias sin uso / sin asignar -> fallback.
    INSERT INTO tmp_asig_categoria (categoria_id, institucion_id)
    SELECT c.categoria_id, v_fallback
      FROM categoria c
      LEFT JOIN tmp_asig_categoria a USING (categoria_id)
     WHERE a.categoria_id IS NULL;

    -- Productos sin uso / sin asignar -> fallback.
    INSERT INTO tmp_asig_producto (producto_id, institucion_id)
    SELECT p.producto_id, v_fallback
      FROM producto p
      LEFT JOIN tmp_asig_producto a USING (producto_id)
     WHERE a.producto_id IS NULL;

    -- Si aun quedan filas sin institucion, es que no hay instituciones: aborto.
    IF EXISTS (SELECT 1 FROM categoria c
                LEFT JOIN tmp_asig_categoria a USING (categoria_id)
                WHERE a.categoria_id IS NULL)
       OR EXISTS (SELECT 1 FROM producto p
                   LEFT JOIN tmp_asig_producto a USING (producto_id)
                   WHERE a.producto_id IS NULL) THEN
        RAISE EXCEPTION '008 migracion ABORTADA: existen categorias/productos sin institucion asignable (no hay filas en `institucion`). Nada aplicado.';
    END IF;

    -- -----------------------------------------------------
    -- 2. DDL + RELLENO (mismo modelo que `01_esquema.sql`)
    -- -----------------------------------------------------

    -- 2.1 DEPARTAMENTO: destino de la FK compuesta inventario -> departamento.
    ALTER TABLE departamento
        ADD CONSTRAINT departamento_institucion_uk
        UNIQUE (institucion_id, departamento_id);

    -- 2.2 CATEGORIA: pertenencia explicita.
    ALTER TABLE categoria ADD COLUMN institucion_id VARCHAR(20);

    UPDATE categoria c
       SET institucion_id = a.institucion_id
      FROM tmp_asig_categoria a
     WHERE a.categoria_id = c.categoria_id;

    ALTER TABLE categoria
        ADD CONSTRAINT categoria_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id);

    ALTER TABLE categoria
        ADD CONSTRAINT categoria_institucion_uk
        UNIQUE (institucion_id, categoria_id);

    ALTER TABLE categoria ALTER COLUMN institucion_id SET NOT NULL;

    -- 2.3 PRODUCTO: pertenencia y FK compuesta a su categoria.
    ALTER TABLE producto ADD COLUMN institucion_id VARCHAR(20);

    UPDATE producto p
       SET institucion_id = a.institucion_id
      FROM tmp_asig_producto a
     WHERE a.producto_id = p.producto_id;

    ALTER TABLE producto DROP CONSTRAINT producto_categoria_fk;

    ALTER TABLE producto
        ADD CONSTRAINT producto_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id);

    ALTER TABLE producto
        ADD CONSTRAINT producto_categoria_institucion_fk
        FOREIGN KEY (institucion_id, categoria_id)
        REFERENCES categoria(institucion_id, categoria_id);

    ALTER TABLE producto
        ADD CONSTRAINT producto_institucion_uk
        UNIQUE (institucion_id, producto_id);

    ALTER TABLE producto ALTER COLUMN institucion_id SET NOT NULL;

    -- 2.4 INVENTARIO: institucion derivada del departamento.
    ALTER TABLE inventario ADD COLUMN institucion_id VARCHAR(20);

    UPDATE inventario i
       SET institucion_id = d.institucion_id
      FROM departamento d
     WHERE d.departamento_id = i.departamento_id;

    ALTER TABLE inventario DROP CONSTRAINT inventario_departamento_fk;
    ALTER TABLE inventario DROP CONSTRAINT inventario_producto_fk;

    ALTER TABLE inventario
        ADD CONSTRAINT inventario_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id);

    ALTER TABLE inventario
        ADD CONSTRAINT inventario_departamento_institucion_fk
        FOREIGN KEY (institucion_id, departamento_id)
        REFERENCES departamento(institucion_id, departamento_id);

    ALTER TABLE inventario
        ADD CONSTRAINT inventario_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id);

    ALTER TABLE inventario ALTER COLUMN institucion_id SET NOT NULL;

    -- 2.5 TICKET: institucion derivada del solicitante.
    ALTER TABLE ticket ADD COLUMN institucion_id VARCHAR(20);

    UPDATE ticket t
       SET institucion_id = dep.institucion_id
      FROM usuario u
      JOIN departamento dep ON dep.departamento_id = u.departamento_id
     WHERE u.usuario_id = t.usuario_id;

    ALTER TABLE ticket
        ADD CONSTRAINT ticket_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id);

    ALTER TABLE ticket
        ADD CONSTRAINT ticket_institucion_uk
        UNIQUE (institucion_id, ticket_id);

    ALTER TABLE ticket ALTER COLUMN institucion_id SET NOT NULL;

    -- 2.6 DETALLE_TICKET: institucion derivada del ticket.
    ALTER TABLE detalle_ticket ADD COLUMN institucion_id VARCHAR(20);

    UPDATE detalle_ticket dt
       SET institucion_id = t.institucion_id
      FROM ticket t
     WHERE t.ticket_id = dt.ticket_id;

    ALTER TABLE detalle_ticket DROP CONSTRAINT detalle_ticket_ticket_fk;
    ALTER TABLE detalle_ticket DROP CONSTRAINT detalle_ticket_producto_fk;

    ALTER TABLE detalle_ticket
        ADD CONSTRAINT detalle_ticket_institucion_fk
        FOREIGN KEY (institucion_id) REFERENCES institucion(institucion_id);

    ALTER TABLE detalle_ticket
        ADD CONSTRAINT detalle_ticket_ticket_institucion_fk
        FOREIGN KEY (institucion_id, ticket_id)
        REFERENCES ticket(institucion_id, ticket_id);

    ALTER TABLE detalle_ticket
        ADD CONSTRAINT detalle_ticket_producto_institucion_fk
        FOREIGN KEY (institucion_id, producto_id)
        REFERENCES producto(institucion_id, producto_id);

    ALTER TABLE detalle_ticket ALTER COLUMN institucion_id SET NOT NULL;

    RAISE NOTICE '008: migracion completada. Pertenencia institucional aplicada sin perdida de datos.';
END $$;
