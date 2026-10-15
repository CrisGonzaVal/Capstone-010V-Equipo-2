"""DTOs del dashboard analitico consolidado (Feature 009).

Ningun schema de este modulo lleva `model_config = ConfigDict(from_attributes=True)`:
todos son **read models** de consulta que cruzan `inventario`, `producto`,
`departamento`, `institucion` y `movimiento_inventario` con joins y agregan, asi que
los arma el service a mano (`app/services/dashboard_service.py`, plan §1). Con
`from_attributes`, Pydantic buscaria campos que el objeto ORM no expone (por ejemplo
`producto_nombre` o `total_alertas`) y fallaria (stack.md §2, "Read models de consulta").

Los nombres de campo son el contrato publico (`snake_case`, en espanol) y coinciden
1:1 con los que fijan las pruebas de `tests/api/test_dashboard_analitico.py`. No se
expone ningun campo personal de ticket: el KPI de tickets es un conteo agregado.
"""

from datetime import datetime

from pydantic import BaseModel


class DashboardKpiRespuesta(BaseModel):
    """Los cuatro KPI del dashboard (spec §5 D-4).

    Todos los conteos son escalares: sin filas devuelven cero. `total_alertas` y la
    longitud de `DashboardAnaliticoRespuesta.alertas` son el mismo conjunto (AC-5).
    """

    unidades_en_stock: int
    tickets_activos: int
    total_departamentos: int
    total_alertas: int


class AlertaStockRespuesta(BaseModel):
    """Fila de inventario actualmente critica (log de alertas derivado, D-1).

    Una fila es critica si `stock_actual <= stock_minimo` evaluado por pareja
    departamento-producto. `institucion_id`/`institucion_nombre` llevan la
    atribucion institucional de la fila (obligatoria en el resultado global del
    Superadmin) y son `null` solo si la atribucion no puede resolverse.
    """

    inventario_id: int
    producto_id: int
    producto_nombre: str
    departamento_id: int
    departamento_nombre: str
    stock_actual: int
    stock_minimo: int
    institucion_id: str | None
    institucion_nombre: str | None


class MovimientoDashboardRespuesta(BaseModel):
    """Fila de la actividad reciente (proyeccion enriquecida de movimientos, D-5).

    Cruza `movimiento_inventario` con `inventario`, `producto`, `departamento` e
    `institucion`. `ubicacion` es la de la fila de inventario de origen.
    `institucion_id`/`institucion_nombre` atribuyen cada movimiento en la lectura
    global del Superadmin.
    """

    movimiento_id: int
    tipo_movimiento: str
    cantidad: int
    fecha_movimiento: datetime
    producto_id: int
    producto_nombre: str
    departamento_id: int
    departamento_nombre: str
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
