from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router

app = FastAPI(
    title="CompuStock ERP API",
    description="API REST para la gestión centralizada de insumos de ofimática (SaaS Multi-tenant)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", summary="Raiz de la API")
def leer_raiz():
    return {
        "message": "Bienvenido a la API de CompuStock ERP",
        "status": "online",
        "docs_url": "/docs",
    }


@app.get("/health", summary="Estado de salud del servicio")
def verificar_salud():
    return {"status": "healthy"}
