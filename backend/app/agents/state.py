"""Shared state and schemas for agents."""

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    """Normalized calendar event from any source."""

    source: Literal["google_calendar", "apple_ical"]
    external_id: str | None = None
    title: str
    start_time: datetime
    end_time: datetime
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "source": "google_calendar",
                "external_id": "abc123",
                "title": "Team sync",
                "start_time": "2025-06-28T10:00:00Z",
                "end_time": "2025-06-28T10:30:00Z",
                "location": "Conference room",
                "attendees": ["alice@example.com"],
            }
        }


class WeatherData(BaseModel):
    """Weather forecast for the day."""

    temperature_high: float
    temperature_low: float
    condition: str  # "sunny", "rainy", "cloudy", etc.
    humidity: int
    wind_speed_mph: float
    precipitation_probability: int
    uv_index: int | None = None
    sunrise: datetime
    sunset: datetime


class CommuteData(BaseModel):
    """Commute information."""

    from_address: str
    to_address: str
    estimated_duration_minutes: int
    traffic_condition: str  # "light", "moderate", "heavy"
    departure_time: datetime | None = None


class WorkoutRecommendation(BaseModel):
    """Workout recommendation."""

    duration_minutes: int
    recommended_time: Literal["morning", "evening", "flexible"]
    start_time: datetime | None = None
    end_time: datetime | None = None
    notes: str | None = None


class DailyPlanData(BaseModel):
    """Structured daily plan."""

    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    calendar_summary: str = ""
    weather: WeatherData | None = None
    weather_summary: str = ""
    commute: CommuteData | None = None
    commute_summary: str = ""
    workout_recommendation: WorkoutRecommendation | None = None
    leave_time: datetime | None = None
    carry_items: list[str] = Field(default_factory=list)
    extra_user_plans: str = ""
    final_summary: str = ""


class AgentState(BaseModel):
    """Shared state across all agents in the graph."""

    run_id: str
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Conversation state (FSM)
    current_state: str = "greeting"  # ConversationState enum value
    previous_state: str | None = None
    state_changed_at: datetime = Field(default_factory=datetime.utcnow)
    transcript: list[dict[str, str]] = Field(default_factory=list)
    user_input: str = ""

    # Interaction tracking
    barge_in_count: int = 0
    silence_timeout_count: int = 0
    stt_attempts: int = 0
    stt_low_confidence_count: int = 0

    # Planning data
    plan: DailyPlanData | None = None

    # Evaluation
    evaluation_score: float | None = None
    hallucinations_detected: list[str] = Field(default_factory=list)
    debug_summary: dict[str, Any] = Field(default_factory=dict)

    # Error tracking
    error: str | None = None
    error_count: int = 0
    error_recovery_attempts: int = 0
    call_duration_seconds: int | None = None
