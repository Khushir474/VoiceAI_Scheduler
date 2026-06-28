"""FastAPI application for DailyOps AI."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import get_settings
from app.db.supabase_client import get_supabase_client
from app.api import vapi_webhooks, dashboard, messages
from app.agents.state import AgentState
from app.agents.planning_agent import PlanningAgent
from app.agents.conversation_agent import ConversationAgent
from app.agents.evaluation_agent import EvaluationAgent
from app.agents.graph import DailyOpsGraph
from app.adapters.calendar import GoogleCalendarAdapter, AppleICalAdapter
from app.services.logger import DebugLogger

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
    allow_origins=["http://localhost:3000", "http://localhost:8000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency: Supabase client
async def get_db():
    """Dependency for Supabase client."""
    return get_supabase_client()


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "debug": settings.debug,
    }


# Test endpoint: Trigger a daily planning run
@app.post("/api/test-run")
async def test_run(user_id: str = "test-user-1", db = Depends(get_db)):
    """Trigger a test daily planning run."""
    try:
        run_id = str(uuid.uuid4())

        # Create debug logger
        debug_logger = DebugLogger(db, run_id, user_id)

        # Initialize adapters
        calendar_adapters = [
            GoogleCalendarAdapter(debug_logger, settings.google_calendar_client_id),
            AppleICalAdapter(debug_logger, settings.apple_ical_path),
        ]

        # Initialize agents
        planning_agent = PlanningAgent(debug_logger, calendar_adapters)
        conversation_agent = ConversationAgent(debug_logger)
        evaluation_agent = EvaluationAgent(debug_logger)

        # Build and run graph
        graph = DailyOpsGraph(debug_logger, planning_agent, conversation_agent, evaluation_agent)

        # Create initial state
        initial_state = AgentState(
            run_id=run_id,
            user_id=user_id,
        )

        # Run the workflow
        final_state = await graph.run(initial_state)

        # Save final plan to database
        if final_state.plan:
            await db.table("daily_plans").insert({
                "run_id": run_id,
                "user_id": user_id,
                "plan_date": date.today().isoformat(),
                "calendar_summary": final_state.plan.calendar_summary,
                "weather_summary": final_state.plan.weather_summary,
                "commute_summary": final_state.plan.commute_summary,
                "workout_recommendation": final_state.plan.workout_recommendation.model_dump() if final_state.plan.workout_recommendation else None,
                "carry_items": final_state.plan.carry_items,
                "extra_user_plans": final_state.plan.extra_user_plans,
                "final_summary": final_state.plan.final_summary,
                "status": "completed" if not final_state.error else "failed",
            }).execute()

        # Save evaluation
        if final_state.evaluation_score is not None:
            await db.table("evaluation_scores").insert({
                "run_id": run_id,
                "user_id": user_id,
                "overall_score": final_state.evaluation_score,
                "debug_summary": final_state.debug_summary,
            }).execute()

        return {
            "run_id": run_id,
            "status": "success" if not final_state.error else "failed",
            "error": final_state.error,
            "plan": final_state.plan.model_dump() if final_state.plan else None,
            "evaluation_score": final_state.evaluation_score,
        }

    except Exception as e:
        logger.error(f"Test run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Include API routers
app.include_router(vapi_webhooks.router)
app.include_router(dashboard.router)
app.include_router(messages.router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
