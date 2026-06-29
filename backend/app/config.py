import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Supabase
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str

    # LLM APIs
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    llm_provider: str = "openrouter"  # 'anthropic', 'openai', or 'openrouter'

    # Vapi
    vapi_api_key: str
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""  # ID of the outbound number in Vapi dashboard
    vapi_webhook_url: str = "https://localhost:8000/api/webhook/vapi"
    vapi_websocket_enabled: bool = True
    vapi_websocket_timeout_seconds: int = 300

    # ElevenLabs
    elevenlabs_api_key: str

    # Google Calendar (OAuth 2.0)
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    google_calendar_access_token: str = ""  # Runtime token (refreshed as needed)
    google_calendar_token_expiry: str = ""  # ISO format timestamp

    # Google Maps
    google_maps_api_key: str = ""

    # Weather
    weather_api_key: str = ""
    weather_provider: str = "openweather"  # 'openweather' or 'weatherapi'

    # Messaging
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    user_phone_number: str = ""
    imessage_bridge_url: str = "http://localhost:8001"

    # Apple iCal (CalDAV)
    apple_ical_caldav_url: str = "https://caldav.icloud.com"
    apple_ical_username: str = ""  # Apple ID email
    apple_ical_password: str = ""  # App-specific password

    # Langfuse (observability)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_enabled: bool = True

    # Application
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore unknown fields from .env


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
