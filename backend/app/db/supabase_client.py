"""Supabase client initialization."""

from typing import Any
from supabase import create_client
from app.config import get_settings


def get_supabase_client() -> Any:
    """Get async Supabase client."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_secret_key)
