from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import inventario, tickets, usuarios

app = FastAPI(
    title="CompuStock ERP API",
    description="API REST para la gestión centralizada de insumos de ofimática (SaaS Multi-tenant)",
    version="1.0.0"
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir Routers de los módulos
app.include_router(usuarios.router, prefix="/api/v1")
app.include_router(inventario.router, prefix="/api/v1")
app.include_router(tickets.router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {
        "message": "Bienvenido a la API de CompuStock ERP",
        "status": "online",
        "docs_url": "/docs"
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
