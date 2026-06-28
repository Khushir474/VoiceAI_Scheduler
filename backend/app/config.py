import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str = ""

    # OpenAI / LLM
    openai_api_key: str

    # Vapi
    vapi_api_key: str
    vapi_assistant_id: str = ""

    # ElevenLabs
    elevenlabs_api_key: str

    # Google Calendar
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""

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

    # Application
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
