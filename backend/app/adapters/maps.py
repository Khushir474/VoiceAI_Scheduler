"""Google Maps API adapter (cloud-based) with caching."""

import logging
import httpx
import time
from datetime import datetime
from typing import Any, Literal

from app.agents.state import CommuteData
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class CommuteCache:
    """Simple in-memory cache with TTL for commute data."""

    def __init__(self, ttl_seconds: int = 1800):  # Default 30 minutes
        self.ttl = ttl_seconds
        self.data: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        if key not in self.data:
            return None
        value, timestamp = self.data[key]
        if time.time() - timestamp > self.ttl:
            del self.data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Cache a value with current timestamp."""
        self.data[key] = (value, time.time())

    def clear(self) -> None:
        """Clear all cached data."""
        self.data.clear()


class MapsAdapter:
    """Fetch commute data from Google Maps API (cloud) with caching."""

    VALID_MODES = ("driving", "transit", "walking", "bicycling")

    def __init__(self, debug_logger: DebugLogger, api_key: str, cache_ttl_seconds: int = 1800):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.http_client = httpx.AsyncClient(timeout=10)
        self.cache = CommuteCache(ttl_seconds=cache_ttl_seconds)

    def _cache_key(
        self, origin: str, destination: str, mode: str = "driving", departure_time: str | None = None
    ) -> str:
        """Generate cache key for commute route."""
        # Note: We ignore departure_time in cache key for now since traffic changes frequently
        # but we cache for 30 minutes which is reasonable
        return f"commute_{origin}_{destination}_{mode}"

    async def get_commute_time(
        self,
        home_address: str,
        work_address: str,
        mode: Literal["driving", "transit", "walking", "bicycling"] = "driving",
        departure_time: str | None = None,
    ) -> CommuteData | None:
        """Fetch commute duration and traffic from Google Maps Distance Matrix API.

        Args:
            home_address: Origin address (e.g., "123 Main St, San Francisco, CA")
            work_address: Destination address (e.g., "456 Market St, San Francisco, CA")
            mode: Travel mode (driving, transit, walking, bicycling)
            departure_time: ISO format datetime string for traffic conditions

        Returns:
            CommuteData with estimated duration and traffic condition, or None if fetch fails
        """
        if mode not in self.VALID_MODES:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="invalid_mode",
                level="error",
                message=f"Invalid transport mode: {mode}. Valid modes: {', '.join(self.VALID_MODES)}",
                error=f"Invalid mode: {mode}",
            )
            return None

        cache_key = self._cache_key(home_address, work_address, mode, departure_time)
        start_time = time.time()

        # Try cache first
        cached = self.cache.get(cache_key)
        if cached:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="cache_hit",
                message=f"Commute cache hit: {home_address} → {work_address} ({mode})",
                input_payload={
                    "home": home_address,
                    "work": work_address,
                    "mode": mode,
                },
                output_payload=cached.model_dump(),
                latency_ms=0,
            )
            return cached

        await self.debug_logger.log_event(
            agent_name="MapsAdapter",
            event_type="fetch_started",
            message=f"Fetching commute: {home_address} → {work_address} ({mode})",
            input_payload={
                "home": home_address,
                "work": work_address,
                "mode": mode,
                "departure_time": departure_time,
            },
        )

        try:
            url = "https://maps.googleapis.com/maps/api/distancematrix/json"
            params = {
                "origins": home_address,
                "destinations": work_address,
                "mode": mode,
                "key": self.api_key,
                "units": "imperial",
            }

            # Add departure_time if provided (for traffic-aware results)
            if departure_time:
                params["departure_time"] = departure_time

            response = await self.http_client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if data.get("status") != "OK":
                raise ValueError(f"Maps API error: {data.get('status')}")

            row = data.get("rows", [{}])[0]
            element = row.get("elements", [{}])[0]

            if element.get("status") != "OK":
                raise ValueError(f"No route found: {element.get('status')}")

            # Extract duration information
            duration = element.get("duration", {})
            duration_minutes = duration.get("value", 0) // 60

            # Use duration_in_traffic if available, otherwise use duration
            # duration_in_traffic accounts for real-time traffic conditions
            duration_in_traffic = element.get("duration_in_traffic")
            if duration_in_traffic:
                traffic_duration_minutes = duration_in_traffic.get("value", 0) // 60
                # Calculate traffic condition based on ratio
                ratio = traffic_duration_minutes / max(duration_minutes, 1)
                if ratio > 1.5:
                    traffic_condition = "heavy"
                elif ratio > 1.2:
                    traffic_condition = "moderate"
                else:
                    traffic_condition = "light"
                duration_minutes = traffic_duration_minutes
            else:
                # Fallback: determine traffic condition based on duration
                traffic_condition = "moderate"
                if duration_minutes < 20:
                    traffic_condition = "light"
                elif duration_minutes > 45:
                    traffic_condition = "heavy"

            # Extract distance if available
            distance = element.get("distance", {})
            distance_miles = distance.get("value", 0) / 1609.34  # Convert meters to miles

            commute = CommuteData(
                from_address=home_address,
                to_address=work_address,
                estimated_duration_minutes=duration_minutes,
                traffic_condition=traffic_condition,
                departure_time=datetime.fromisoformat(departure_time) if departure_time else None,
            )

            # Cache the result
            self.cache.set(cache_key, commute)

            latency_ms = int((time.time() - start_time) * 1000)
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_completed",
                message=f"Commute: {duration_minutes} min ({traffic_condition} traffic), {distance_miles:.1f} mi",
                output_payload=commute.model_dump(),
                latency_ms=latency_ms,
            )

            return commute

        except httpx.TimeoutException as e:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_timeout",
                level="warning",
                message="Maps API timeout, attempting fallback cache",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            # Try to return any cached value even if expired
            if cache_key in self.cache.data:
                return self.cache.data[cache_key][0]
            return None

        except httpx.HTTPStatusError as e:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Maps API error: {e.response.status_code}",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            # Try to return any cached value even if expired
            if cache_key in self.cache.data:
                return self.cache.data[cache_key][0]
            return None

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch commute: {str(e)}",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            return None

    async def get_commute(
        self,
        origin: str,
        destination: str,
        departure_time: str | None = None,
    ) -> CommuteData | None:
        """Backward compatibility method. Use get_commute_time() instead."""
        return await self.get_commute_time(origin, destination, mode="driving", departure_time=departure_time)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()

    def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self.cache.clear()
