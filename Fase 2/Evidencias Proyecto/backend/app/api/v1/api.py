from fastapi import APIRouter

from app.api.v1.endpoints import inventario, tickets, usuarios

api_router = APIRouter()
api_router.include_router(usuarios.router)
api_router.include_router(inventario.router)
api_router.include_router(tickets.router)
