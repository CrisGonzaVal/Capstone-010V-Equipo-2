"""Router agregado de v1 (Feature 006).

La dependencia `get_current_user` se aplica **al router agregado de negocio**,
de modo que todas las rutas incluidas (`/auth/me`, `/usuarios/*`,
`/inventario/*`, `/tickets/*`) exigen un Bearer valido sin tocar la logica de
los endpoints operativos. Salud y documentacion viven en `app` (`/health`,
`/docs`, `/redoc`, `/openapi.json`), fuera de este router, y por tanto quedan
sin proteccion.
"""

from fastapi import APIRouter, Depends

from app.api import dependencies
from app.api.v1.endpoints import auth, dashboard, inventario, tickets, usuarios

api_router = APIRouter(dependencies=[Depends(dependencies.get_current_user)])

api_router.include_router(auth.router)
api_router.include_router(usuarios.router)
api_router.include_router(inventario.router)
api_router.include_router(tickets.router)
# Feature 009: lectura analitica consolidada (KPI, alertas y actividad).
api_router.include_router(dashboard.router)
