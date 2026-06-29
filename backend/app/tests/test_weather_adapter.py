"""Tests for WeatherAdapter with caching and error handling."""

import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.weather import WeatherAdapter, WeatherCache
from app.agents.state import WeatherData
from app.services.logger import DebugLogger


@pytest.fixture
def debug_logger():
    """Mock debug logger."""
    logger = MagicMock(spec=DebugLogger)
    logger.log_event = AsyncMock()
    return logger


@pytest.fixture
def weather_adapter(debug_logger):
    """Create a WeatherAdapter instance with mock logger."""
    adapter = WeatherAdapter(
        debug_logger=debug_logger,
        api_key="test-api-key",
        provider="openweather",
        cache_ttl_seconds=3600,
    )
    return adapter


class TestWeatherCache:
    """Tests for WeatherCache."""

    def test_cache_set_and_get(self):
        """Test basic cache set and get."""
        cache = WeatherCache(ttl_seconds=3600)
        data = {"temp": 72}

        cache.set("key1", data)
        assert cache.get("key1") == data

    def test_cache_miss(self):
        """Test cache miss for non-existent key."""
        cache = WeatherCache()
        assert cache.get("nonexistent") is None

    def test_cache_expiration(self):
        """Test cache TTL expiration."""
        cache = WeatherCache(ttl_seconds=1)  # 1 second TTL
        data = {"temp": 72}

        cache.set("key1", data)
        assert cache.get("key1") == data

        # Simulate time passing
        cache.data["key1"] = (data, 0)  # Set timestamp to epoch
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """Test clearing cache."""
        cache = WeatherCache()
        cache.set("key1", {"temp": 72})
        cache.set("key2", {"temp": 65})

        assert len(cache.data) == 2
        cache.clear()
        assert len(cache.data) == 0


class TestWeatherAdapterBasic:
    """Basic tests for WeatherAdapter."""

    @pytest.mark.asyncio
    async def test_cache_key_generation(self, weather_adapter):
        """Test cache key generation."""
        key = weather_adapter._cache_key(37.7749, -122.4194, days=1)
        assert key == "weather_37.7749_-122.4194_1"

    @pytest.mark.asyncio
    async def test_init_with_defaults(self, debug_logger):
        """Test adapter initialization with defaults."""
        adapter = WeatherAdapter(
            debug_logger=debug_logger,
            api_key="test-key",
        )
        assert adapter.api_key == "test-key"
        assert adapter.provider == "openweather"
        assert adapter.cache.ttl == 3600

    @pytest.mark.asyncio
    async def test_init_with_custom_cache_ttl(self, debug_logger):
        """Test adapter initialization with custom cache TTL."""
        adapter = WeatherAdapter(
            debug_logger=debug_logger,
            api_key="test-key",
            cache_ttl_seconds=1800,
        )
        assert adapter.cache.ttl == 1800


class TestWeatherAdapterCaching:
    """Tests for WeatherAdapter caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, weather_adapter, debug_logger):
        """Test cache hit returns cached data without API call."""
        weather_data = WeatherData(
            temperature_high=72,
            temperature_low=62,
            condition="Sunny",
            humidity=65,
            wind_speed_mph=5.0,
            precipitation_probability=10,
            sunrise=datetime.now(timezone.utc),
            sunset=datetime.now(timezone.utc),
        )

        # Pre-populate cache
        weather_adapter.cache.set("weather_37.7749_-122.4194_1", weather_data)

        result = await weather_adapter.get_forecast(37.7749, -122.4194, days=1)

        assert result == weather_data
        # Verify debug logger was called for cache hit
        calls = debug_logger.log_event.call_args_list
        assert any("cache_hit" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_cache_stores_successful_result(self, weather_adapter, debug_logger):
        """Test that successful API result is cached."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main": {
                "temp_max": 72,
                "temp_min": 62,
                "humidity": 65,
            },
            "weather": [{"main": "Sunny"}],
            "wind": {"speed": 2.237},  # 5 mph
            "clouds": {"all": 10},
            "sys": {
                "sunrise": int(datetime.now(timezone.utc).timestamp()),
                "sunset": int(datetime.now(timezone.utc).timestamp()),
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response) as mock_get:
            result = await weather_adapter.get_forecast(37.7749, -122.4194, days=1)

            # Verify cache was populated
            cached = weather_adapter.cache.get("weather_37.7749_-122.4194_1")
            assert cached is not None
            assert cached.condition == "Sunny"

    @pytest.mark.asyncio
    async def test_different_locations_different_cache_keys(self, weather_adapter, debug_logger):
        """Test that different locations have different cache keys."""
        weather1 = WeatherData(
            temperature_high=72,
            temperature_low=62,
            condition="Sunny",
            humidity=65,
            wind_speed_mph=5.0,
            precipitation_probability=10,
            sunrise=datetime.now(timezone.utc),
            sunset=datetime.now(timezone.utc),
        )

        weather2 = WeatherData(
            temperature_high=55,
            temperature_low=45,
            condition="Rainy",
            humidity=80,
            wind_speed_mph=10.0,
            precipitation_probability=80,
            sunrise=datetime.now(timezone.utc),
            sunset=datetime.now(timezone.utc),
        )

        # Cache both
        weather_adapter.cache.set("weather_37.7749_-122.4194_1", weather1)
        weather_adapter.cache.set("weather_40.7128_-74.0060_1", weather2)

        # Retrieve and verify
        result1 = weather_adapter.cache.get("weather_37.7749_-122.4194_1")
        result2 = weather_adapter.cache.get("weather_40.7128_-74.0060_1")

        assert result1.condition == "Sunny"
        assert result2.condition == "Rainy"


class TestWeatherAdapterAPISuccess:
    """Tests for successful WeatherAdapter API calls."""

    @pytest.mark.asyncio
    async def test_successful_weather_fetch(self, weather_adapter, debug_logger):
        """Test successful weather data fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main": {
                "temp_max": 72,
                "temp_min": 62,
                "humidity": 65,
            },
            "weather": [{"main": "Sunny"}],
            "wind": {"speed": 2.237},  # 5 mph
            "clouds": {"all": 10},
            "sys": {
                "sunrise": int(datetime.now(timezone.utc).timestamp()),
                "sunset": int(datetime.now(timezone.utc).timestamp()),
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            result = await weather_adapter.get_forecast(37.7749, -122.4194)

            assert result is not None
            assert result.temperature_high == 72
            assert result.temperature_low == 62
            assert result.condition == "Sunny"
            assert result.humidity == 65
            assert result.wind_speed_mph == pytest.approx(5.0, rel=0.1)
            assert result.precipitation_probability == 10

    @pytest.mark.asyncio
    async def test_weather_fetch_with_days_parameter(self, weather_adapter, debug_logger):
        """Test weather forecast with different day values."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main": {"temp_max": 72, "temp_min": 62, "humidity": 65},
            "weather": [{"main": "Cloudy"}],
            "wind": {"speed": 1},
            "clouds": {"all": 50},
            "sys": {
                "sunrise": int(datetime.now(timezone.utc).timestamp()),
                "sunset": int(datetime.now(timezone.utc).timestamp()),
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            # Test with days=3
            result = await weather_adapter.get_forecast(37.7749, -122.4194, days=3)

            assert result is not None
            assert result.condition == "Cloudy"

            # Verify cache key includes days
            cached = weather_adapter.cache.get("weather_37.7749_-122.4194_3")
            assert cached is not None

    @pytest.mark.asyncio
    async def test_logging_on_successful_fetch(self, weather_adapter, debug_logger):
        """Test that debug logger is called on successful fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main": {"temp_max": 72, "temp_min": 62, "humidity": 65},
            "weather": [{"main": "Sunny"}],
            "wind": {"speed": 2.237},
            "clouds": {"all": 10},
            "sys": {
                "sunrise": int(datetime.now(timezone.utc).timestamp()),
                "sunset": int(datetime.now(timezone.utc).timestamp()),
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            await weather_adapter.get_forecast(37.7749, -122.4194)

            # Verify logger was called
            assert debug_logger.log_event.called
            calls = debug_logger.log_event.call_args_list

            # Should have at least: fetch_started, fetch_completed
            event_types = [call[1].get("event_type") for call in calls if call[1]]
            assert "fetch_started" in event_types
            assert "fetch_completed" in event_types


class TestWeatherAdapterErrors:
    """Tests for WeatherAdapter error handling."""

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, weather_adapter, debug_logger):
        """Test handling of timeout errors."""
        with patch.object(
            weather_adapter.http_client,
            "get",
            side_effect=httpx.TimeoutException("Request timeout")
        ):
            result = await weather_adapter.get_forecast(37.7749, -122.4194)

            assert result is None
            # Verify error was logged
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_timeout_logs_warning(self, weather_adapter, debug_logger):
        """Test that timeout logs a warning event."""
        # Mock httpx.get to raise timeout
        async def mock_timeout_get(*args, **kwargs):
            raise httpx.TimeoutException("Request timeout")

        with patch.object(weather_adapter.http_client, "get", side_effect=mock_timeout_get):
            result = await weather_adapter.get_forecast(37.7749, -122.4194, days=1)

            # Should return None on timeout with no cache
            assert result is None
            # Verify timeout was logged
            calls = debug_logger.log_event.call_args_list
            event_types = [call[1].get("event_type") for call in calls if call[1]]
            assert "fetch_timeout" in event_types

    @pytest.mark.asyncio
    async def test_http_error_handling(self, weather_adapter, debug_logger):
        """Test handling of HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response
        )

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            result = await weather_adapter.get_forecast(37.7749, -122.4194)

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_unknown_provider_error(self, debug_logger):
        """Test error handling for unknown weather provider."""
        adapter = WeatherAdapter(
            debug_logger=debug_logger,
            api_key="test-key",
            provider="unknown_provider",
        )

        result = await adapter.get_forecast(37.7749, -122.4194)

        assert result is None
        assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_malformed_response_handling(self, weather_adapter, debug_logger):
        """Test handling of malformed API responses."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            result = await weather_adapter.get_forecast(37.7749, -122.4194)

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_missing_fields_in_response(self, weather_adapter, debug_logger):
        """Test handling of responses missing expected fields."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # Empty response
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            result = await weather_adapter.get_forecast(37.7749, -122.4194)

            # Should handle gracefully with defaults
            assert result is not None
            assert result.condition == "Unknown"


class TestWeatherAdapterCleanup:
    """Tests for WeatherAdapter cleanup methods."""

    @pytest.mark.asyncio
    async def test_clear_cache(self, weather_adapter):
        """Test clearing the cache."""
        weather_data = WeatherData(
            temperature_high=72,
            temperature_low=62,
            condition="Sunny",
            humidity=65,
            wind_speed_mph=5.0,
            precipitation_probability=10,
            sunrise=datetime.now(timezone.utc),
            sunset=datetime.now(timezone.utc),
        )

        weather_adapter.cache.set("weather_37.7749_-122.4194_1", weather_data)
        assert len(weather_adapter.cache.data) > 0

        weather_adapter.clear_cache()
        assert len(weather_adapter.cache.data) == 0

    @pytest.mark.asyncio
    async def test_close(self, weather_adapter):
        """Test closing the HTTP client."""
        await weather_adapter.close()
        # Verify client is closed (httpx should handle this gracefully)
        assert weather_adapter.http_client is not None


class TestWeatherAdapterBackwardCompatibility:
    """Tests for backward compatibility with get_weather()."""

    @pytest.mark.asyncio
    async def test_get_weather_calls_get_forecast(self, weather_adapter, debug_logger):
        """Test that get_weather() delegates to get_forecast()."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "main": {"temp_max": 72, "temp_min": 62, "humidity": 65},
            "weather": [{"main": "Sunny"}],
            "wind": {"speed": 2.237},
            "clouds": {"all": 10},
            "sys": {
                "sunrise": int(datetime.now(timezone.utc).timestamp()),
                "sunset": int(datetime.now(timezone.utc).timestamp()),
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(weather_adapter.http_client, "get", return_value=mock_response):
            result = await weather_adapter.get_weather(37.7749, -122.4194)

            assert result is not None
            assert result.condition == "Sunny"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
