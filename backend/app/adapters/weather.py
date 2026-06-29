"""Weather API adapter (cloud-based) with caching."""

import logging
import httpx
import time
from datetime import datetime, timezone
from typing import Any

from app.agents.state import WeatherData
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class WeatherCache:
    """Simple in-memory cache with TTL (time-to-live)."""

    def __init__(self, ttl_seconds: int = 3600):
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


class WeatherAdapter:
    """Fetch weather from OpenWeather API (cloud) with caching."""

    def __init__(
        self,
        debug_logger: DebugLogger,
        api_key: str,
        provider: str = "openweather",
        cache_ttl_seconds: int = 3600,
    ):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.provider = provider
        self.http_client = httpx.AsyncClient(timeout=10)
        self.cache = WeatherCache(ttl_seconds=cache_ttl_seconds)

    def _cache_key(self, lat: float, lon: float, days: int = 1) -> str:
        """Generate cache key for coordinates and forecast days."""
        return f"weather_{lat}_{lon}_{days}"

    async def get_forecast(
        self, latitude: float, longitude: float, days: int = 1
    ) -> WeatherData | None:
        """Fetch weather forecast for coordinates with caching.

        Args:
            latitude: Location latitude
            longitude: Location longitude
            days: Number of days for forecast (default: 1 = today)

        Returns:
            WeatherData or None if fetch fails and no cache available
        """
        cache_key = self._cache_key(latitude, longitude, days)
        start_time = time.time()

        # Try cache first
        cached = self.cache.get(cache_key)
        if cached:
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="cache_hit",
                message=f"Weather cache hit for ({latitude}, {longitude})",
                input_payload={"lat": latitude, "lon": longitude, "days": days},
                output_payload=cached.model_dump(),
                latency_ms=0,
            )
            return cached

        await self.debug_logger.log_event(
            agent_name="WeatherAdapter",
            event_type="fetch_started",
            message=f"Fetching weather for ({latitude}, {longitude}), days={days}",
            input_payload={"lat": latitude, "lon": longitude, "days": days},
        )

        try:
            if self.provider == "openweather":
                weather = await self._fetch_openweather(latitude, longitude)
            else:
                raise ValueError(f"Unknown weather provider: {self.provider}")

            if weather:
                # Cache the result
                self.cache.set(cache_key, weather)

            latency_ms = int((time.time() - start_time) * 1000)
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="fetch_completed",
                message=f"Weather: {weather.condition}, {weather.temperature_high}°F",
                output_payload=weather.model_dump() if weather else None,
                latency_ms=latency_ms,
            )
            return weather

        except httpx.TimeoutException as e:
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="fetch_timeout",
                level="warning",
                message="Weather API timeout, attempting fallback cache",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            # Try to return any cached value even if expired
            if cache_key in self.cache.data:
                return self.cache.data[cache_key][0]
            return None

        except httpx.HTTPStatusError as e:
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Weather API error: {e.response.status_code}",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            # Try to return any cached value even if expired
            if cache_key in self.cache.data:
                return self.cache.data[cache_key][0]
            return None

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch weather: {str(e)}",
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
            return None

    async def _fetch_openweather(self, lat: float, lon: float) -> WeatherData | None:
        """Fetch from OpenWeather API."""
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": "imperial",  # For US users
        }

        response = await self.http_client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        main = data.get("main", {})
        weather_info = data.get("weather", [{}])[0]
        sys_info = data.get("sys", {})

        # Convert sunset/sunrise timestamps to datetime
        sunrise = datetime.fromtimestamp(sys_info.get("sunrise", 0), tz=timezone.utc)
        sunset = datetime.fromtimestamp(sys_info.get("sunset", 0), tz=timezone.utc)

        weather = WeatherData(
            temperature_high=main.get("temp_max", 72),
            temperature_low=main.get("temp_min", 62),
            condition=weather_info.get("main", "Unknown"),
            humidity=main.get("humidity", 65),
            wind_speed_mph=data.get("wind", {}).get("speed", 0) * 2.237,  # Convert m/s to mph
            precipitation_probability=int(data.get("clouds", {}).get("all", 0)),
            sunrise=sunrise,
            sunset=sunset,
        )

        return weather

    async def get_weather(self, latitude: float, longitude: float) -> WeatherData | None:
        """Backward compatibility method. Use get_forecast() instead."""
        return await self.get_forecast(latitude, longitude, days=1)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()

    def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self.cache.clear()
