"""Supabase client initialization."""

from supabase import create_client, AsyncClient
from app.config import get_settings


def get_supabase_client() -> AsyncClient:
    """Get async Supabase client."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
