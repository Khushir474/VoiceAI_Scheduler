"""FastAPI application for DailyOps AI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import get_settings
from app.db.supabase_client import get_supabase_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("Starting DailyOps AI backend")
    yield
    logger.info("Shutting down DailyOps AI backend")


# Initialize FastAPI app
app = FastAPI(
    title="DailyOps AI",
    description="Voice-first productivity assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "debug": settings.debug,
    }


# API Routes (to be imported from api module)
# from app.api import vapi_webhooks, dashboard, messages, scheduler
# app.include_router(vapi_webhooks.router)
# app.include_router(dashboard.router)
# app.include_router(messages.router)
# app.include_router(scheduler.router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
