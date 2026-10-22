"""DTOs del dashboard analitico consolidado (Features 009 y 011).

Ningun schema de este modulo lleva `model_config = ConfigDict(from_attributes=True)`:
todos son **read models** de consulta que cruzan `stock_sede` (o `inventario`
legado), `producto`, `sede`, `departamento`, `institucion` y
`movimiento_inventario` con joins y agregan, asi que los arma el service a mano
(`app/services/dashboard_service.py`, plan §1). Con `from_attributes`, Pydantic
buscaria campos que el objeto ORM no expone (por ejemplo `producto_nombre` o
`total_alertas`) y fallaria (stack.md §2, "Read models de consulta").

Feature 011 (spec D-6/AC-11): la fuente de saldo pasa a ser el **stock por sede**,
asi que la alerta se atribuye a `sede_id`/`sede_nombre` y a la institucion, y la
actividad reconoce tanto movimientos historicos (`inventario_id`) como nuevos
(`stock_sede_id`) mediante una proyeccion unica compatible: los campos de sede y
los de departamento son mutuamente opcionales segun el origen del movimiento.

Los nombres de campo son el contrato publico (`snake_case`, en espanol) y coinciden
1:1 con los que fijan las pruebas de `tests/api/`. No se expone ningun campo
personal de ticket: el KPI de tickets es un conteo agregado.
"""

from datetime import datetime

from pydantic import BaseModel


class DashboardKpiRespuesta(BaseModel):
    """Los cuatro KPI del dashboard (spec 009 §5 D-4; fuente 011 spec D-6).

    Todos los conteos son escalares: sin filas devuelven cero. `total_alertas` y la
    longitud de `DashboardAnaliticoRespuesta.alertas` son el mismo conjunto (AC-5).
    """

    unidades_en_stock: int
    tickets_activos: int
    total_departamentos: int
    total_alertas: int


class AlertaStockRespuesta(BaseModel):
    """Fila de stock por sede actualmente critica (log de alertas derivado, D-1).

    Feature 011 (spec D-6/AC-11): una fila es critica si
    `stock_actual <= stock_minimo` evaluado **por par sede-producto**. La alerta
    identifica la bodega fisica que puede abastecer, por lo que se atribuye a la
    **sede** (`sede_id`/`sede_nombre`) y a la institucion
    (`institucion_id`/`institucion_nombre`, obligatoria en el resultado global del
    Superadmin; `null` solo si la atribucion no puede resolverse). No se expone
    ningun saldo departamental legado.
    """

    sede_id: int
    sede_nombre: str
    producto_id: int
    producto_nombre: str
    stock_actual: int
    stock_minimo: int
    institucion_id: str | None
    institucion_nombre: str | None


class MovimientoDashboardRespuesta(BaseModel):
    """Fila de la actividad reciente (proyeccion unica de movimientos, D-5).

    Cruza `movimiento_inventario` con su origen de auditoria, ya sea legado
    (`inventario_id -> inventario -> producto + departamento`) o nuevo
    (`stock_sede_id -> stock_sede -> producto + sede`). La proyeccion es unica y
    compatible: `sede_id`/`sede_nombre` se pueblan en los movimientos nuevos y
    `departamento_id`/`departamento_nombre`/`ubicacion` en los legados; el otro
    conjunto queda `null` segun el origen. `institucion_id`/`institucion_nombre`
    atribuyen cada movimiento en la lectura global del Superadmin.
    """

    movimiento_id: int
    tipo_movimiento: str
    cantidad: int
    fecha_movimiento: datetime
    producto_id: int
    producto_nombre: str
    sede_id: int | None
    sede_nombre: str | None
    departamento_id: int | None
    departamento_nombre: str | None
    ubicacion: str | None
    institucion_id: str | None
    institucion_nombre: str | None


class DashboardAnaliticoRespuesta(BaseModel):
    """Contrato de exito consolidado de `GET /api/v1/dashboard/` (plan §1).

    Una sola lectura reune KPI y log de alertas para todos los roles. La actividad
    de movimientos queda sujeta al rol: `actividad_disponible` es `false` y la lista
    viene vacia para Solicitante (su permiso de `GET /inventario/movimientos` sigue
    denegado); para los demas roles es `true` aun con lista vacia (ausencia de
    registros). Este booleano es de presentacion y no otorga autorizacion alguna.
    """

    kpi: DashboardKpiRespuesta
    alertas: list[AlertaStockRespuesta]
    actividad_disponible: bool
    actividad_movimientos: list[MovimientoDashboardRespuesta]
