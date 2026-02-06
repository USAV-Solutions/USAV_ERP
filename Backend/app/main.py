"""
USAV Inventory Database API
Main FastAPI Application

This is the central authority for all USAV product data,
implementing the Hub & Spoke middleware architecture.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.database import close_db, engine
from app.modules.orders.routes import router as orders_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan handler.
    Manages startup and shutdown events.
    """
    # Startup
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print(f"📊 Environment: {settings.environment}")
    print(f"🔗 Database: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down...")
    await close_db()
    print("✅ Database connections closed")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## USAV Core Inventory Database API

This API serves as the **central authority** for all USAV product data.
It implements the Hub & Spoke middleware architecture where:

- **The Hub (This API):** Owns immutable Product Identity and physical inventory
- **The Spokes (Zoho, Amazon, eBay):** Receive data updates from the Hub

### Key Concepts

1. **Product Family**: High-level grouping (5-digit ECWID ID)
2. **Product Identity (Layer 1)**: Engineering layer - what an item IS
3. **Product Variant (Layer 2)**: Sales layer - sellable configurations
4. **Bundle Component**: Bill of Materials for bundles/kits
5. **Platform Listing**: External platform sync management
6. **Inventory Item**: Physical inventory tracking

### SKU Structure

Full SKU: `{product_id}-{type}-{lci}-{color}-{condition}`
Example: `00845-P-1-WY-N` (Product 845, Part 1, White, New)
    """,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors gracefully."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected error occurred",
            "error": str(exc) if settings.debug else "Internal server error",
        }
    )


# Health check endpoint (root level for Docker health checks)
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for load balancers and container orchestration.
    """
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/health/db", tags=["Health"])
async def database_health():
    """
    Database connectivity health check.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "disconnected", "error": str(e)}
        )


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root - provides basic info and links."""
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "docs": f"{settings.api_prefix}/docs",
        "health": "/health",
    }


# Include API router with prefix
app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(orders_router, prefix=settings.api_prefix)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
