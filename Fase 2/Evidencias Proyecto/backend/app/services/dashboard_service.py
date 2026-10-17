"""Read model consolidado del dashboard analitico (Feature 009).

`obtener_dashboard_analitico()` reune, en una sola lectura, los cuatro KPI, el log
de alertas (filas de inventario actualmente criticas) y la actividad reciente de
movimientos, todo acotado al ambito institucional del actor. La logica de negocio
vive aqui, no en el router (`AGENTS.md` §6; `stack.md` §2).

Decisiones de la spec que este modulo implementa:

* **D-1** — Criticidad por fila de inventario (`stock_actual <= stock_minimo`),
  reutilizando el predicado puro `inventario_service.es_stock_critico`; NO se usa
  `listar_existencias(solo_criticos=True)`, que evalua el mismo nombre con el
  criterio del **agregado** por producto y no corresponde a esta feature.
* **D-2** — El log de alertas es una vista **derivada**: no se persiste ninguna
  fila de alerta; cada lectura refleja el estado actual del inventario.
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

Sin SQL raw: todo son consultas tipadas SQLAlchemy ORM/Core. Cada seccion se arma
con **una** consulta (agregados en SQL, o una proyeccion con joins explicitos), de
modo que no hay N+1 ni descarga de colecciones de tickets a Python.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import HTTPException, status

from app.core import permisos
from app.models import (
    Departamento,
    EstadoTicket,
    Institucion,
    Inventario,
    MovimientoInventario,
    Producto,
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
#: Nombre literal del unico estado de ticket que NO cuenta como activo. La
#: comparacion es sensible a mayusculas y sin normalizacion (D-4 #2, AC-2): solo
#: el nombre exacto "Cerrado" se excluye; "cerrado" o "CERRADO" si cuentan.
NOMBRE_ESTADO_CERRADO = "Cerrado"

#: Filas de la actividad reciente. Limite fijo del contrato de consulta (D-5,
#: AC-6): no es paginacion ni historial editable.
LIMITE_ACTIVIDAD = 10

_SOLICITANTE = permisos.RolConocido.SOLICITANTE.value


def _es_solicitante(identidad: IdentidadAutenticada | None) -> bool:
    """`True` solo para el rol `Solicitante` (un rol ausente/desconocido no)."""
    return permisos.nombre_rol_de(identidad) == _SOLICITANTE


def _sumar_unidades_en_stock(db: Session, institucion_id: str | None) -> int:
    """KPI «Unidades en Stock»: suma de `stock_actual` dentro del ambito (D-4 #1).

    Para Superadmin (`institucion_id is None`) es un **unico escalar global**; para
    el resto, la suma de su institucion. Sin filas devuelve `0` (`coalesce`).
    """
    consulta = select(func.coalesce(func.sum(Inventario.stock_actual), 0))
    if institucion_id is not None:
        consulta = (
            consulta.join(
                Departamento,
                Inventario.departamento_id == Departamento.departamento_id,
            ).where(Departamento.institucion_id == institucion_id)
        )
    return db.execute(consulta).scalar_one()


def _contar_tickets_activos(
    db: Session, identidad: IdentidadAutenticada | None, institucion_id: str | None
) -> int:
    """KPI «Tickets activos»: tickets cuyo estado no es exactamente «Cerrado».

    El conteo es agregado en SQL (nunca se descargan los tickets a Python). El
    alcance por rol replica la regla vigente de tickets (D-3/AC-9): Superadmin,
    global; Administrador/Bodeguero, los de su institucion via
    `ticket → usuario → departamento`; Solicitante, solo los propios por
    `usuario_id`.
    """
    consulta = (
        select(func.count())
        .select_from(Ticket)
        .join(EstadoTicket, Ticket.estado_id == EstadoTicket.estado_id)
        .where(EstadoTicket.nombre != NOMBRE_ESTADO_CERRADO)
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
    """Log de alertas: una fila por inventario critico segun D-1 (AC-4, AC-5).

    Una sola consulta cruza `inventario → producto + departamento + institucion`.
    El predicado `es_stock_critico` decide por **fila** en Python, para que KPI y
    listado compartan exactamente la misma regla; la proyeccion ya trae
    `stock_minimo` de cada producto.
    """
    consulta = (
        select(
            Inventario.inventario_id,
            Inventario.producto_id,
            Producto.nombre.label("producto_nombre"),
            Inventario.departamento_id,
            Departamento.nombre_dep.label("departamento_nombre"),
            Inventario.stock_actual,
            Producto.stock_minimo,
            Inventario.institucion_id,
            Institucion.nombre.label("institucion_nombre"),
        )
        .join(Producto, Inventario.producto_id == Producto.producto_id)
        .join(
            Departamento,
            Inventario.departamento_id == Departamento.departamento_id,
        )
        .outerjoin(
            Institucion, Inventario.institucion_id == Institucion.institucion_id
        )
        .order_by(Inventario.inventario_id)
    )
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Departamento.institucion_id, institucion_id
    )

    return [
        AlertaStockRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
        if es_stock_critico(fila["stock_actual"], fila["stock_minimo"])
    ]


def _listar_actividad(
    db: Session, institucion_id: str | None
) -> list[MovimientoDashboardRespuesta]:
    """Actividad reciente: ultimos `LIMITE_ACTIVIDAD` movimientos (D-5).

    Proyeccion enriquecida `movimiento_inventario → inventario → producto +
    departamento + institucion`, ordenada `fecha_movimiento DESC,
    movimiento_id DESC` (desempate determinista ante fechas iguales). Cada fila
    lleva la atribucion institucional de su inventario. Solo se invoca para roles
    autorizados; el Solicitante no dispara esta consulta.
    """
    consulta = (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            Inventario.producto_id,
            Producto.nombre.label("producto_nombre"),
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
        .join(
            Departamento,
            Inventario.departamento_id == Departamento.departamento_id,
        )
        .outerjoin(
            Institucion, Inventario.institucion_id == Institucion.institucion_id
        )
        .order_by(
            MovimientoInventario.fecha_movimiento.desc(),
            MovimientoInventario.movimiento_id.desc(),
        )
        .limit(LIMITE_ACTIVIDAD)
    )
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Departamento.institucion_id, institucion_id
    )

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
