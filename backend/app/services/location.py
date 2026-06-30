"""LocationService — detect user's current city, timezone, and coordinates via IP geolocation.

Uses ipapi.co (free tier: 1000 req/day, HTTPS). Called once at call-start by PlanningAgent;
result stored in daily_context and threaded through AgentState so the LLM always has
accurate local time without any hardcoded values.
"""

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

IPAPI_URL = "https://ipapi.co/json/"
REQUEST_TIMEOUT = 5.0  # seconds — fail fast rather than block the call


@dataclass
class LocationContext:
    city: str
    region: str
    country: str
    timezone: str   # IANA tz name, e.g. "America/Chicago"
    lat: float
    lng: float

    @property
    def display_name(self) -> str:
        return f"{self.city}, {self.region}"


_FALLBACK = LocationContext(
    city="Unknown",
    region="Unknown",
    country="Unknown",
    timezone="UTC",
    lat=0.0,
    lng=0.0,
)


class LocationService:
    """Detect the server's public-IP location as a proxy for the user's location.

    For a real production system this would use device GPS or a user-stored address.
    For this MVP the server and the user share the same rough location (same city).
    """

    def __init__(self, debug_logger=None):
        self.debug_logger = debug_logger

    async def detect(self) -> LocationContext:
        """Return location context derived from the server's public IP.

        Raises on network / API error — callers should use detect_with_fallback().
        """
        start = time.time()
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(IPAPI_URL, headers={"User-Agent": "DailyOps-AI/1.0"})
            resp.raise_for_status()
            data = resp.json()

        latency_ms = int((time.time() - start) * 1000)

        if data.get("error"):
            raise ValueError(f"ipapi.co error: {data.get('reason', 'unknown')}")

        ctx = LocationContext(
            city=data.get("city") or "Unknown",
            region=data.get("region") or "",
            country=data.get("country_name") or "",
            timezone=data.get("timezone") or "UTC",
            lat=float(data.get("latitude") or 0.0),
            lng=float(data.get("longitude") or 0.0),
        )

        if self.debug_logger:
            await self.debug_logger.log_event(
                agent_name="LocationService",
                event_type="location_detected",
                message=f"Detected location: {ctx.display_name} ({ctx.timezone})",
                output_payload={
                    "city": ctx.city,
                    "region": ctx.region,
                    "timezone": ctx.timezone,
                    "lat": ctx.lat,
                    "lng": ctx.lng,
                },
                latency_ms=latency_ms,
            )

        return ctx

    async def detect_with_fallback(self, fallback_timezone: str = "UTC") -> LocationContext:
        """Return location context, falling back to fallback_timezone on any error."""
        try:
            return await self.detect()
        except Exception as e:
            logger.warning(f"LocationService: IP geolocation failed, using fallback ({e})")
            if self.debug_logger:
                await self.debug_logger.log_event(
                    agent_name="LocationService",
                    event_type="location_fallback",
                    level="warning",
                    message=f"IP geolocation failed, falling back to timezone={fallback_timezone}",
                    error=str(e),
                )
            fallback = LocationContext(
                city="Unknown", region="", country="",
                timezone=fallback_timezone, lat=0.0, lng=0.0,
            )
            return fallback
