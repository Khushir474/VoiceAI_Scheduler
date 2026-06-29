"""Supabase client initialization."""

from typing import Any
from supabase import create_async_client
from app.config import get_settings


async def get_supabase_client() -> Any:
    """Get async Supabase client."""
    settings = get_settings()
    return await create_async_client(settings.supabase_url, settings.supabase_secret_key)
