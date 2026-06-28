"""Weather API adapter (cloud-based)."""

import logging
import httpx
from datetime import datetime, timezone

from app.agents.state import WeatherData
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class WeatherAdapter:
    """Fetch weather from OpenWeather API (cloud)."""

    def __init__(self, debug_logger: DebugLogger, api_key: str, provider: str = "openweather"):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.provider = provider
        self.http_client = httpx.AsyncClient(timeout=10)

    async def get_weather(self, latitude: float, longitude: float) -> WeatherData | None:
        """Fetch weather for coordinates."""
        await self.debug_logger.log_event(
            agent_name="WeatherAdapter",
            event_type="fetch_started",
            message=f"Fetching weather for ({latitude}, {longitude})",
            input_payload={"lat": latitude, "lon": longitude},
        )

        try:
            if self.provider == "openweather":
                return await self._fetch_openweather(latitude, longitude)
            else:
                raise ValueError(f"Unknown weather provider: {self.provider}")

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="WeatherAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch weather: {str(e)}",
                error=str(e),
            )
            return None

    async def _fetch_openweather(self, lat: float, lon: float) -> WeatherData:
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

        await self.debug_logger.log_event(
            agent_name="WeatherAdapter",
            event_type="fetch_completed",
            message=f"Weather: {weather.condition}, {weather.temperature_high}°F",
            output_payload=weather.model_dump(),
        )

        return weather
