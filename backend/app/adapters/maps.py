"""Google Maps API adapter (cloud-based)."""

import logging
import httpx

from app.agents.state import CommuteData
from app.services.logger import DebugLogger

logger = logging.getLogger(__name__)


class MapsAdapter:
    """Fetch commute data from Google Maps API (cloud)."""

    def __init__(self, debug_logger: DebugLogger, api_key: str):
        self.debug_logger = debug_logger
        self.api_key = api_key
        self.http_client = httpx.AsyncClient(timeout=10)

    async def get_commute(
        self,
        origin: str,
        destination: str,
        departure_time: str | None = None,
    ) -> CommuteData | None:
        """Fetch commute duration and traffic from Google Maps Distance Matrix API."""
        await self.debug_logger.log_event(
            agent_name="MapsAdapter",
            event_type="fetch_started",
            message=f"Fetching commute from {origin} to {destination}",
            input_payload={"origin": origin, "destination": destination},
        )

        try:
            url = "https://maps.googleapis.com/maps/api/distancematrix/json"
            params = {
                "origins": origin,
                "destinations": destination,
                "key": self.api_key,
                "units": "imperial",
            }

            response = await self.http_client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if data.get("status") != "OK":
                raise ValueError(f"Maps API error: {data.get('status')}")

            row = data.get("rows", [{}])[0]
            element = row.get("elements", [{}])[0]

            if element.get("status") != "OK":
                raise ValueError(f"No route found: {element.get('status')}")

            duration = element.get("duration", {})
            duration_minutes = duration.get("value", 0) // 60

            # Determine traffic condition based on duration_in_traffic if available
            # For MVP, assume traffic condition based on time of day
            traffic_condition = "moderate"
            if duration_minutes < 20:
                traffic_condition = "light"
            elif duration_minutes > 45:
                traffic_condition = "heavy"

            commute = CommuteData(
                from_address=origin,
                to_address=destination,
                estimated_duration_minutes=duration_minutes,
                traffic_condition=traffic_condition,
                departure_time=None,
            )

            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_completed",
                message=f"Commute: {duration_minutes} min ({traffic_condition} traffic)",
                output_payload=commute.model_dump(),
            )

            return commute

        except Exception as e:
            await self.debug_logger.log_event(
                agent_name="MapsAdapter",
                event_type="fetch_failed",
                level="error",
                message=f"Failed to fetch commute: {str(e)}",
                error=str(e),
            )
            return None
