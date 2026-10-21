"""Read model consolidado del dashboard analitico (Feature 009).

`obtener_dashboard_analitico()` reune, en una sola lectura, los cuatro KPI, el log
de alertas (filas de inventario actualmente criticas) y la actividad reciente de
movimientos, todo acotado al ambito institucional del actor. La logica de negocio
vive aqui, no en el router (`AGENTS.md` §6; `stack.md` §2).

Decisiones de la spec que este modulo implementa:

* **D-1** — Criticidad por fila de stock por sede (`stock_actual <= stock_minimo`)
  sobre la granularidad `(sede, producto)` de la Feature 011 (spec D-6/AC-11),
  reutilizando el predicado puro `inventario_service.es_stock_critico`; NO se usa
  `listar_existencias(solo_criticos=True)`, que evalua el mismo nombre con el
  criterio del **agregado** por producto y no corresponde a esta feature.
* **D-2** — El log de alertas es una vista **derivada**: no se persiste ninguna
  fila de alerta; cada lectura refleja el estado actual del stock por sede.
* **D-3** — El ambito lo resuelve el servidor con
  `ambito_service.alcance_institucional`; `None` es Superadmin global. Un rol
  limitado sin institucion resoluble responde **403** (nunca se degrada a global)
  y ningun parametro del cliente amplia el alcance.
* **D-4** — Los cuatro KPI: unidades en stock (escalar global unico para
  Superadmin), tickets activos por nombre literal de estado, departamentos por PK
  y alertas por fila critica (igual a `len(alertas)`).
* **D-5** — Actividad desde la auditoria inmutable de movimientos, orden
  `fecha_movimiento DESC, movimiento_id DESC`, limite fijo, y solo para
  Superadmin, Administrador y Bodeguero. El Solicitante no dispara la consulta.

Feature 011 (spec D-6/AC-11): los KPI conservan exactamente las formulas de la
Feature 009 pero su **fuente** pasa de `inventario` departamental a `stock_sede`:
unidades = suma de saldos por sede; alertas = filas `(sede, producto)` criticas.
La actividad reconoce las dos poblaciones de auditoria mediante **una proyeccion
unica** (`union_all`): los movimientos historicos enlazados a `inventario_id` y los
nuevos enlazados a `stock_sede_id`, atribuyendo la sede en los nuevos sin exponer
saldos departamentales legados.

Sin SQL raw: todo son consultas tipadas SQLAlchemy ORM/Core. Cada seccion se arma
con **una** consulta (agregados en SQL, o una proyeccion con joins explicitos), de
modo que no hay N+1 ni descarga de colecciones de tickets a Python.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, cast, func, null, select, union_all
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core import permisos
from app.models import (
    Categoria,
    Departamento,
    EstadoTicket,
    Institucion,
    Inventario,
    MovimientoInventario,
    Producto,
    Sede,
    StockSede,
    Ticket,
    Usuario,
)
from app.schemas.dashboard_schema import (
    AlertaStockRespuesta,
    DashboardAnaliticoRespuesta,
    DashboardKpiRespuesta,
    MovimientoDashboardRespuesta,
)
from app.services import ambito_service
from app.services import global_service
from app.services.auth_service import IdentidadAutenticada
from app.services.inventario_service import es_stock_critico
#: Nombres literales de los estados que NO cuentan como tickets activos. La
#: comparacion es sensible a mayusculas y sin normalizacion (009 D-4 #2, que la
#: 013 conserva; AC-22/D-12): solo los nombres exactos "Cerrado" y "Anulado" se
#: excluyen; "cerrado", "CERRADO" o "anulado" (minusculas) si cuentan. Sin ids
#: fijos: la exclusion se resuelve por nombre en cualquier catalogo.
NOMBRES_ESTADOS_NO_ACTIVOS = ("Cerrado", "Anulado")

#: Filas de la actividad reciente. Limite fijo del contrato de consulta (D-5,
#: AC-6): no es paginacion ni historial editable.
LIMITE_ACTIVIDAD = 10

_SOLICITANTE = permisos.RolConocido.SOLICITANTE.value


def _es_solicitante(identidad: IdentidadAutenticada | None) -> bool:
    """`True` solo para el rol `Solicitante` (un rol ausente/desconocido no)."""
    return permisos.nombre_rol_de(identidad) == _SOLICITANTE


def _sumar_unidades_en_stock(db: Session, institucion_id: str | None) -> int:
    """KPI «Unidades en Stock»: suma de los saldos por sede del ambito (D-4 #1).

    Feature 011 (spec D-6/AC-2): la unica fuente de saldo es `stock_sede`, asi que
    el KPI nunca lee `inventario` legado. Para Superadmin (`institucion_id is
    None`) es un **unico escalar global** (suma de todas las sedes); para el resto,
    la suma de las sedes de su institucion. Sin filas devuelve `0` (`coalesce`).
    """
    consulta = select(func.coalesce(func.sum(StockSede.stock_actual), 0))
    consulta = ambito_service.filtrar_por_institucion(
        consulta, StockSede.institucion_id, institucion_id
    )
    return db.execute(consulta).scalar_one()


def _contar_tickets_activos(
    db: Session, identidad: IdentidadAutenticada | None, institucion_id: str | None
) -> int:
    """KPI «Tickets activos»: tickets cuyo estado no es `Cerrado` ni `Anulado`.

    El conteo es agregado en SQL (nunca se descargan los tickets a Python). La
    exclusion es por **nombre exacto** de los dos estados terminales
    (`NOMBRES_ESTADOS_NO_ACTIVOS`), sin ids fijos y sin insensibilidad al
    casing, conservando la semantica documentada en la 009 (Feature 013,
    spec D-12/AC-22). El alcance por rol replica la regla vigente de tickets
    (D-3/AC-9): Superadmin, global; Administrador/Bodeguero, los de su
    institucion via `ticket → usuario → departamento`; Solicitante, solo los
    propios por `usuario_id`.
    """
    consulta = (
        select(func.count())
        .select_from(Ticket)
        .join(EstadoTicket, Ticket.estado_id == EstadoTicket.estado_id)
        .where(EstadoTicket.nombre.notin_(NOMBRES_ESTADOS_NO_ACTIVOS))
    )

    if _es_solicitante(identidad):
        consulta = consulta.where(
            Ticket.usuario_id == identidad.usuario.usuario_id
        )
    elif institucion_id is not None:
        consulta = (
            consulta.join(Usuario, Ticket.usuario_id == Usuario.usuario_id)
            .join(
                Departamento,
                Usuario.departamento_id == Departamento.departamento_id,
            )
            .where(Departamento.institucion_id == institucion_id)
        )

    return db.execute(consulta).scalar_one()


def _contar_departamentos(db: Session, institucion_id: str | None) -> int:
    """KPI «Departamentos»: registros por PK dentro del ambito (D-4 #3).

    Cuenta `departamento` directamente, incluidos los que no tienen filas de
    inventario. Superadmin cuenta el total global y los homonimos de
    instituciones distintas por separado (cada PK una vez).
    """
    consulta = select(func.count(Departamento.departamento_id))
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Departamento.institucion_id, institucion_id
    )
    return db.execute(consulta).scalar_one()


def _listar_alertas(
    db: Session, institucion_id: str | None
) -> list[AlertaStockRespuesta]:
    """Log de alertas: una fila por stock de sede critico segun D-1 (AC-11).

    Feature 011 (spec D-6/AC-11): una sola consulta cruza
    `stock_sede → producto + sede + institucion`; la alerta se evalua y se atribuye
    **por sede**, no por inventario departamental. El predicado `es_stock_critico`
    decide por **fila** en Python, para que KPI y listado compartan exactamente la
    misma regla; la proyeccion ya trae `stock_minimo` de cada producto.

    Feature 014 (AC-10): quedan fuera del log -y por tanto de `total_alertas`,
    que es `len(alertas)`- los productos retirados y los productos cuya
    categoria esta retirada. El resto de KPI conserva su formula.
    """
    consulta = (
        select(
            StockSede.sede_id,
            Sede.nombre.label("sede_nombre"),
            StockSede.producto_id,
            Producto.nombre.label("producto_nombre"),
            StockSede.stock_actual,
            Producto.stock_minimo,
            StockSede.institucion_id,
            Institucion.nombre.label("institucion_nombre"),
        )
        .join(Producto, StockSede.producto_id == Producto.producto_id)
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .join(Sede, StockSede.sede_id == Sede.sede_id)
        .outerjoin(
            Institucion, StockSede.institucion_id == Institucion.institucion_id
        )
        .where(Producto.activo.is_(True), Categoria.activo.is_(True))
        .order_by(StockSede.stock_sede_id)
    )
    consulta = ambito_service.filtrar_por_institucion(
        consulta, StockSede.institucion_id, institucion_id
    )

    return [
        AlertaStockRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
        if es_stock_critico(fila["stock_actual"], fila["stock_minimo"])
    ]


def _actividad_legados():
    """Select de los movimientos historicos (enlazados a `inventario_id`).

    Proyeccion compatible de la actividad: atribuye `departamento`/`ubicacion` y
    deja `sede` en `null`, con el mismo conjunto y orden de columnas que
    `_actividad_nuevos` para poder unirlas con `union_all` (spec D-6/AC-11).
    """
    return (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            Inventario.producto_id,
            Producto.nombre.label("producto_nombre"),
            cast(null(), Integer).label("sede_id"),
            cast(null(), String(100)).label("sede_nombre"),
            Inventario.departamento_id,
            Departamento.nombre_dep.label("departamento_nombre"),
            Inventario.ubicacion,
            Inventario.institucion_id,
            Institucion.nombre.label("institucion_nombre"),
        )
        .join(
            Inventario,
            MovimientoInventario.inventario_id == Inventario.inventario_id,
        )
        .join(Producto, Inventario.producto_id == Producto.producto_id)
        .outerjoin(
            Departamento,
            Inventario.departamento_id == Departamento.departamento_id,
        )
        .outerjoin(
            Institucion, Inventario.institucion_id == Institucion.institucion_id
        )
        .where(MovimientoInventario.inventario_id.is_not(None))
    )


def _actividad_nuevos():
    """Select de los movimientos nuevos (enlazados a `stock_sede_id`).

    Misma forma que `_actividad_legados`: atribuye `sede`/producto/institucion
    desde `stock_sede` y deja `departamento`/`ubicacion` en `null`. No consulta
    saldos legados.
    """
    return (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            StockSede.producto_id,
            Producto.nombre.label("producto_nombre"),
            Sede.sede_id.label("sede_id"),
            Sede.nombre.label("sede_nombre"),
            cast(null(), Integer).label("departamento_id"),
            cast(null(), String(200)).label("departamento_nombre"),
            cast(null(), String(100)).label("ubicacion"),
            StockSede.institucion_id,
            Institucion.nombre.label("institucion_nombre"),
        )
        .join(
            StockSede,
            MovimientoInventario.stock_sede_id == StockSede.stock_sede_id,
        )
        .join(Producto, StockSede.producto_id == Producto.producto_id)
        .outerjoin(Sede, StockSede.sede_id == Sede.sede_id)
        .outerjoin(
            Institucion, StockSede.institucion_id == Institucion.institucion_id
        )
        .where(MovimientoInventario.stock_sede_id.is_not(None))
    )


def _listar_actividad(
    db: Session, institucion_id: str | None
) -> list[MovimientoDashboardRespuesta]:
    """Actividad reciente: ultimos `LIMITE_ACTIVIDAD` movimientos (D-5).

    Proyeccion **unica y compatible** (`union_all`) de las dos poblaciones de
    auditoria -históricos por `inventario_id` y nuevos por `stock_sede_id`-, para
    que la actividad no pierda ningun origen (spec D-6/AC-11). Se ordena
    `fecha_movimiento DESC, movimiento_id DESC` (desempate determinista ante
    fechas iguales) y se limita a `LIMITE_ACTIVIDAD`. Cada fila lleva la
    atribucion institucional de su origen. Solo se invoca para roles autorizados;
    el Solicitante no dispara esta consulta.
    """
    actividad = union_all(_actividad_legados(), _actividad_nuevos()).subquery(
        "actividad"
    )
    consulta = select(actividad)
    consulta = ambito_service.filtrar_por_institucion(
        consulta, actividad.c.institucion_id, institucion_id
    )
    consulta = consulta.order_by(
        actividad.c.fecha_movimiento.desc(),
        actividad.c.movimiento_id.desc(),
    ).limit(LIMITE_ACTIVIDAD)

    return [
        MovimientoDashboardRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


def _es_postgres(db: Session) -> bool:
    """`True` si la sesion corre sobre PostgreSQL (namespaces reales)."""
    return db.get_bind().dialect.name == "postgresql"


def _dashboard_global(
    db: Session, identidad: IdentidadAutenticada | None, tenants: list
) -> DashboardAnaliticoRespuesta:
    """Consolida el dashboard del Superadmin sobre TODOS los tenants (D-9/AC-14).

    Recorre los tenants registrados en control **dentro de una unica transaccion
    de lectura** (`global_service.lectura_global`, `REPEATABLE READ`) y reutiliza
    las mismas reglas por tenant (`_listar_alertas`, `_sumar_unidades_en_stock`,
    `_contar_tickets_activos`, `_contar_departamentos`, `_listar_actividad`), de
    modo que los KPI son la suma de cada tenant y cada fila conserva su
    atribucion institucional (`institucion_id`/`institucion_nombre`).

    La actividad se acota por tenant y luego se reordena globalmente
    (`fecha DESC, movimiento_id DESC`) y se limita a `LIMITE_ACTIVIDAD`, para
    respetar el contrato de 10 filas mas recientes del agregado (un movimiento
    del top-10 global siempre pertenece al top-10 de su tenant).

    Un tenant no versionado o inaccesible levanta `ErrorLecturaGlobal`, que se
    normaliza a **503** revirtiendo la transaccion: nunca se entrega un agregado
    parcial (AC-12/AC-14). No agrega escrituras de negocio al Superadmin.
    """
    total_unidades = 0
    total_tickets = 0
    total_departamentos = 0
    alertas: list[AlertaStockRespuesta] = []
    actividad: list[MovimientoDashboardRespuesta] = []
    puede_ver_actividad = not _es_solicitante(identidad)

    try:
        with global_service.lectura_global(db) as lector:
            for tenant in tenants:
                with lector.sesion(tenant) as sesion:
                    alertas.extend(
                        _listar_alertas(sesion, tenant.institucion_id)
                    )
                    total_unidades += _sumar_unidades_en_stock(
                        sesion, tenant.institucion_id
                    )
                    total_tickets += _contar_tickets_activos(
                        sesion, identidad, tenant.institucion_id
                    )
                    total_departamentos += _contar_departamentos(
                        sesion, tenant.institucion_id
                    )
                    if puede_ver_actividad:
                        actividad.extend(
                            _listar_actividad(sesion, tenant.institucion_id)
                        )
    except global_service.ErrorLecturaGlobal as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No fue posible completar la lectura global: un tenant requerido "
                "no esta disponible o no esta en la version objetivo."
            ),
        ) from exc

    if puede_ver_actividad:
        actividad = sorted(
            actividad,
            key=lambda movimiento: (
                movimiento.fecha_movimiento,
                movimiento.movimiento_id,
            ),
            reverse=True,
        )[:LIMITE_ACTIVIDAD]

    return DashboardAnaliticoRespuesta(
        kpi=DashboardKpiRespuesta(
            unidades_en_stock=total_unidades,
            tickets_activos=total_tickets,
            total_departamentos=total_departamentos,
            total_alertas=len(alertas),
        ),
        alertas=alertas,
        actividad_disponible=puede_ver_actividad,
        actividad_movimientos=actividad,
    )


def obtener_dashboard_analitico(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> DashboardAnaliticoRespuesta:
    """DTO consolidado de `GET /api/v1/dashboard/` (plan §1, AC-1..AC-12).

    Resuelve el ambito una sola vez (`alcance_institucional`; **403** si un rol
    limitado no es resoluble) y ensambla las cuatro secciones. La actividad se
    consulta solo para los roles autorizados: el Solicitante recibe
    `actividad_disponible=False` y lista vacia **sin** consultar movimientos ni
    ampliar su permiso denegado sobre `GET /inventario/movimientos`.

    Feature 010 (D-9/AC-14): el Superadmin global sobre PostgreSQL agrega sobre
    los tenants registrados en una sola transaccion de lectura; si no hay tenants
    registrados (instalacion limpia) o el motor es SQLite, opera sobre la sesion
    recibida, preservando el contrato previo.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    if institucion_id is None and _es_postgres(db):
        tenants = global_service.tenants_registrados(db)
        if tenants:
            return _dashboard_global(db, identidad, tenants)

    alertas = _listar_alertas(db, institucion_id)
    kpi = DashboardKpiRespuesta(
        unidades_en_stock=_sumar_unidades_en_stock(db, institucion_id),
        tickets_activos=_contar_tickets_activos(db, identidad, institucion_id),
        total_departamentos=_contar_departamentos(db, institucion_id),
        total_alertas=len(alertas),
    )

    puede_ver_actividad = not _es_solicitante(identidad)
    actividad_movimientos = (
        _listar_actividad(db, institucion_id) if puede_ver_actividad else []
    )

    return DashboardAnaliticoRespuesta(
        kpi=kpi,
        alertas=alertas,
        actividad_disponible=puede_ver_actividad,
        actividad_movimientos=actividad_movimientos,
    )
