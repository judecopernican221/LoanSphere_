from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import create_tables
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ────────────────────────────────────────────────────────────
    setup_logging()
    logger.info("app_starting", name=settings.APP_NAME, version=settings.APP_VERSION)

    # Create DB tables (dev only — use Alembic in production)
    await create_tables()
    logger.info("database_ready")

    # Initialize Qdrant collection
    try:
        from app.services.embedding_service import _get_qdrant
        _get_qdrant()
        logger.info("qdrant_ready")
    except Exception as e:
        logger.warning("qdrant_init_failed", error=str(e))

    logger.info("app_started")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("app_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered loan risk assessment using RAG, Vector Search, and LLM.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────
from app.api.auth import router as auth_router
from app.api.applications import router as applications_router

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(applications_router, prefix="/applications", tags=["Applications"])


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }
