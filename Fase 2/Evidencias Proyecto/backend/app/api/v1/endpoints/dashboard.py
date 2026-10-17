"""Endpoint del dashboard analitico consolidado (Feature 009).

Router delgado: valida la identidad y la sesion, delega la composicion en
`app.services.dashboard_service` y devuelve el DTO consolidado. No contiene
consultas ni logica de negocio (`AGENTS.md` §6; `stack.md` §2).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.dashboard_schema import DashboardAnaliticoRespuesta
from app.services import dashboard_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "/",
    response_model=DashboardAnaliticoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Consultar el dashboard analitico consolidado",
    description=(
        "Devuelve en **una sola lectura** los cuatro KPI (unidades en stock, "
        "tickets activos, departamentos y alertas de stock), el log de alertas y "
        "la actividad reciente de movimientos, acotados al ambito del actor. La "
        "consolidacion evita una cascada de peticiones y garantiza que los KPI y "
        "las alertas sean temporalmente coherentes.\n\n"
        "**Ambito (servidor).** Superadmin tiene lectura **global** y cada fila de "
        "alerta y de actividad lleva su atribucion institucional "
        "(`institucion_id`/`institucion_nombre`); sus agregados no fusionan "
        "productos homonimos ni stock entre instituciones. Administrador, "
        "Bodeguero y Solicitante solo ven su institucion. Un ambito no resoluble "
        "para un rol limitado responde **403** en vez de degradar a global, y "
        "ningun parametro del cliente amplia el alcance.\n\n"
        "**Alertas.** El log es una vista **derivada**: una fila de stock por "
        "sede es critica si `stock_actual <= stock_minimo` evaluado **por pareja "
        "sede-producto** (granularidad operativa de la Feature 011; no sobre el "
        "agregado del producto) y se atribuye a la sede y a la institucion. "
        "`total_alertas` es exactamente la cantidad de filas del listado. No se "
        "persiste ninguna entidad de alerta.\n\n"
        "**Actividad.** Solo para Superadmin, Administrador y Bodeguero: "
        "movimientos reales ordenados `fecha_movimiento` descendente y, ante "
        "empates, `movimiento_id` descendente, limitados a las **10** filas mas "
        "recientes. La actividad reune la auditoria historica (por "
        "`inventario_id`) y la nueva (por `stock_sede_id`) en una proyeccion "
        "unica. El **Solicitante** recibe "
        "`actividad_disponible=false` con la lista vacia sin consultar "
        "movimientos; este booleano de presentacion **no** amplia su permiso "
        "denegado sobre `GET /api/v1/inventario/movimientos`."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
)
def obtener_dashboard_analitico(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/dashboard/")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
) -> DashboardAnaliticoRespuesta:
    return dashboard_service.obtener_dashboard_analitico(db, identidad)
