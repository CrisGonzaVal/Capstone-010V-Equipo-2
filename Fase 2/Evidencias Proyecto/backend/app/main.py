from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router

app = FastAPI(
    title="CompuStock ERP API",
    description="API REST para la gestión centralizada de insumos de ofimática (SaaS Multi-tenant)",
    version="1.0.0",
)

#: Origenes del frontend (dev 4200 y contenedor nginx 8080). El header
#: `Authorization` se admite explicitamente para el flujo de sesion Clerk.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
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
