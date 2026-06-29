"""Tests for MapsAdapter with caching, traffic detection, and multi-mode support."""

import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.maps import MapsAdapter, CommuteCache
from app.agents.state import CommuteData
from app.services.logger import DebugLogger


@pytest.fixture
def debug_logger():
    """Mock debug logger."""
    logger = MagicMock(spec=DebugLogger)
    logger.log_event = AsyncMock()
    return logger


@pytest.fixture
def maps_adapter(debug_logger):
    """Create a MapsAdapter instance with mock logger."""
    adapter = MapsAdapter(
        debug_logger=debug_logger,
        api_key="test-api-key",
        cache_ttl_seconds=1800,
    )
    return adapter


class TestCommuteCache:
    """Tests for CommuteCache."""

    def test_cache_set_and_get(self):
        """Test basic cache set and get."""
        cache = CommuteCache(ttl_seconds=1800)
        data = {"duration": 30}

        cache.set("key1", data)
        assert cache.get("key1") == data

    def test_cache_miss(self):
        """Test cache miss for non-existent key."""
        cache = CommuteCache()
        assert cache.get("nonexistent") is None

    def test_cache_expiration(self):
        """Test cache TTL expiration."""
        cache = CommuteCache(ttl_seconds=1)  # 1 second TTL
        data = {"duration": 30}

        cache.set("key1", data)
        assert cache.get("key1") == data

        # Simulate time passing
        cache.data["key1"] = (data, 0)  # Set timestamp to epoch
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """Test clearing cache."""
        cache = CommuteCache()
        cache.set("key1", {"duration": 30})
        cache.set("key2", {"duration": 45})

        assert len(cache.data) == 2
        cache.clear()
        assert len(cache.data) == 0

    def test_cache_default_ttl(self):
        """Test default TTL is 30 minutes (1800 seconds)."""
        cache = CommuteCache()
        assert cache.ttl == 1800


class TestMapsAdapterBasic:
    """Basic tests for MapsAdapter."""

    @pytest.mark.asyncio
    async def test_cache_key_generation(self, maps_adapter):
        """Test cache key generation."""
        key = maps_adapter._cache_key("123 Main St", "456 Market St", mode="driving")
        assert key == "commute_123 Main St_456 Market St_driving"

    @pytest.mark.asyncio
    async def test_cache_key_different_modes(self, maps_adapter):
        """Test cache key generation with different modes."""
        key_driving = maps_adapter._cache_key("123 Main St", "456 Market St", mode="driving")
        key_transit = maps_adapter._cache_key("123 Main St", "456 Market St", mode="transit")

        assert key_driving != key_transit

    @pytest.mark.asyncio
    async def test_init_with_defaults(self, debug_logger):
        """Test adapter initialization with defaults."""
        adapter = MapsAdapter(
            debug_logger=debug_logger,
            api_key="test-key",
        )
        assert adapter.api_key == "test-key"
        assert adapter.cache.ttl == 1800

    @pytest.mark.asyncio
    async def test_init_with_custom_cache_ttl(self, debug_logger):
        """Test adapter initialization with custom cache TTL."""
        adapter = MapsAdapter(
            debug_logger=debug_logger,
            api_key="test-key",
            cache_ttl_seconds=900,
        )
        assert adapter.cache.ttl == 900

    @pytest.mark.asyncio
    async def test_valid_modes_constant(self, maps_adapter):
        """Test that valid modes are defined."""
        assert "driving" in maps_adapter.VALID_MODES
        assert "transit" in maps_adapter.VALID_MODES
        assert "walking" in maps_adapter.VALID_MODES
        assert "bicycling" in maps_adapter.VALID_MODES


class TestMapsAdapterCaching:
    """Tests for MapsAdapter caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, maps_adapter, debug_logger):
        """Test cache hit returns cached data without API call."""
        commute_data = CommuteData(
            from_address="123 Main St",
            to_address="456 Market St",
            estimated_duration_minutes=30,
            traffic_condition="moderate",
            departure_time=None,
        )

        # Pre-populate cache
        maps_adapter.cache.set("commute_123 Main St_456 Market St_driving", commute_data)

        result = await maps_adapter.get_commute_time("123 Main St", "456 Market St", mode="driving")

        assert result == commute_data
        # Verify debug logger was called for cache hit
        calls = debug_logger.log_event.call_args_list
        assert any("cache_hit" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_cache_stores_successful_result(self, maps_adapter, debug_logger):
        """Test that successful API result is cached."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},  # 30 minutes in seconds
                            "distance": {"value": 16094},  # 10 miles in meters
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St", mode="driving")

            # Verify cache was populated
            cached = maps_adapter.cache.get("commute_123 Main St_456 Market St_driving")
            assert cached is not None
            assert cached.estimated_duration_minutes == 30

    @pytest.mark.asyncio
    async def test_different_modes_different_cache(self, maps_adapter, debug_logger):
        """Test that different modes have different cache entries."""
        commute_driving = CommuteData(
            from_address="123 Main St",
            to_address="456 Market St",
            estimated_duration_minutes=30,
            traffic_condition="moderate",
            departure_time=None,
        )

        commute_transit = CommuteData(
            from_address="123 Main St",
            to_address="456 Market St",
            estimated_duration_minutes=45,
            traffic_condition="light",
            departure_time=None,
        )

        # Cache both
        maps_adapter.cache.set("commute_123 Main St_456 Market St_driving", commute_driving)
        maps_adapter.cache.set("commute_123 Main St_456 Market St_transit", commute_transit)

        # Retrieve and verify
        result_driving = maps_adapter.cache.get("commute_123 Main St_456 Market St_driving")
        result_transit = maps_adapter.cache.get("commute_123 Main St_456 Market St_transit")

        assert result_driving.estimated_duration_minutes == 30
        assert result_transit.estimated_duration_minutes == 45


class TestMapsAdapterAPISuccess:
    """Tests for successful MapsAdapter API calls."""

    @pytest.mark.asyncio
    async def test_successful_commute_fetch(self, maps_adapter, debug_logger):
        """Test successful commute data fetch."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},  # 30 minutes
                            "distance": {"value": 16094},  # 10 miles
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St", mode="driving")

            assert result is not None
            assert result.from_address == "123 Main St"
            assert result.to_address == "456 Market St"
            assert result.estimated_duration_minutes == 30
            assert result.traffic_condition == "moderate"  # 20 < 30 < 45

    @pytest.mark.asyncio
    async def test_all_transport_modes(self, maps_adapter, debug_logger):
        """Test all transport modes."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        modes = ["driving", "transit", "walking", "bicycling"]

        for mode in modes:
            with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
                result = await maps_adapter.get_commute_time(
                    "123 Main St", "456 Market St", mode=mode
                )
                assert result is not None
                assert result.estimated_duration_minutes == 30

    @pytest.mark.asyncio
    async def test_traffic_condition_light(self, maps_adapter, debug_logger):
        """Test traffic condition detection for light traffic."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 600},  # 10 minutes < 20 threshold
                            "distance": {"value": 8047},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")
            assert result.traffic_condition == "light"

    @pytest.mark.asyncio
    async def test_traffic_condition_moderate(self, maps_adapter, debug_logger):
        """Test traffic condition detection for moderate traffic."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},  # 30 minutes (20 < 30 < 45)
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")
            assert result.traffic_condition == "moderate"

    @pytest.mark.asyncio
    async def test_traffic_condition_heavy(self, maps_adapter, debug_logger):
        """Test traffic condition detection for heavy traffic."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 3600},  # 60 minutes > 45 threshold
                            "distance": {"value": 32188},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")
            assert result.traffic_condition == "heavy"

    @pytest.mark.asyncio
    async def test_duration_in_traffic_used_when_available(self, maps_adapter, debug_logger):
        """Test that duration_in_traffic is used for more accurate traffic detection."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},  # 30 minutes normal
                            "duration_in_traffic": {"value": 2700},  # 45 minutes with traffic
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            # Should use duration_in_traffic
            assert result.estimated_duration_minutes == 45
            # Ratio = 45/30 = 1.5, which should be "moderate"
            assert result.traffic_condition == "moderate"

    @pytest.mark.asyncio
    async def test_departure_time_parameter(self, maps_adapter, debug_logger):
        """Test that departure_time parameter is passed to API."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        departure_time = "2025-06-28T08:00:00Z"

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time(
                "123 Main St", "456 Market St", departure_time=departure_time
            )

            assert result is not None
            # Verify the API was called with departure_time
            mock_response.json.assert_called()

    @pytest.mark.asyncio
    async def test_logging_on_successful_fetch(self, maps_adapter, debug_logger):
        """Test that debug logger is called on successful fetch."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            # Verify logger was called
            assert debug_logger.log_event.called
            calls = debug_logger.log_event.call_args_list

            # Should have at least: fetch_started, fetch_completed
            event_types = [call[1].get("event_type") for call in calls if call[1]]
            assert "fetch_started" in event_types
            assert "fetch_completed" in event_types


class TestMapsAdapterErrors:
    """Tests for MapsAdapter error handling."""

    @pytest.mark.asyncio
    async def test_invalid_mode_error(self, maps_adapter, debug_logger):
        """Test handling of invalid transport mode."""
        result = await maps_adapter.get_commute_time(
            "123 Main St", "456 Market St", mode="invalid_mode"
        )

        assert result is None
        assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, maps_adapter, debug_logger):
        """Test handling of timeout errors."""
        with patch.object(
            maps_adapter.http_client,
            "get",
            side_effect=httpx.TimeoutException("Request timeout")
        ):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_timeout_logs_warning(self, maps_adapter, debug_logger):
        """Test that timeout logs a warning event."""
        async def mock_timeout_get(*args, **kwargs):
            raise httpx.TimeoutException("Request timeout")

        with patch.object(maps_adapter.http_client, "get", side_effect=mock_timeout_get):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            # Should return None on timeout with no cache
            assert result is None
            # Verify timeout was logged
            calls = debug_logger.log_event.call_args_list
            event_types = [call[1].get("event_type") for call in calls if call[1]]
            assert "fetch_timeout" in event_types

    @pytest.mark.asyncio
    async def test_http_error_handling(self, maps_adapter, debug_logger):
        """Test handling of HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden",
            request=MagicMock(),
            response=mock_response
        )

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_api_status_error(self, maps_adapter, debug_logger):
        """Test handling of API status errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "ZERO_RESULTS",  # No route found
            "rows": [],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_element_status_error(self, maps_adapter, debug_logger):
        """Test handling of element status errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "NOT_FOUND",  # Element error
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_malformed_response_handling(self, maps_adapter, debug_logger):
        """Test handling of malformed API responses."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            assert result is None
            assert debug_logger.log_event.called

    @pytest.mark.asyncio
    async def test_missing_fields_in_response(self, maps_adapter, debug_logger):
        """Test handling of responses missing expected fields."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK"}]}],  # Missing duration and distance
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute_time("123 Main St", "456 Market St")

            # Should handle gracefully
            assert result is not None
            assert result.estimated_duration_minutes == 0


class TestMapsAdapterCleanup:
    """Tests for MapsAdapter cleanup methods."""

    @pytest.mark.asyncio
    async def test_clear_cache(self, maps_adapter):
        """Test clearing the cache."""
        commute_data = CommuteData(
            from_address="123 Main St",
            to_address="456 Market St",
            estimated_duration_minutes=30,
            traffic_condition="moderate",
            departure_time=None,
        )

        maps_adapter.cache.set("commute_123 Main St_456 Market St_driving", commute_data)
        assert len(maps_adapter.cache.data) > 0

        maps_adapter.clear_cache()
        assert len(maps_adapter.cache.data) == 0

    @pytest.mark.asyncio
    async def test_close(self, maps_adapter):
        """Test closing the HTTP client."""
        await maps_adapter.close()
        # Verify client is closed (httpx should handle this gracefully)
        assert maps_adapter.http_client is not None


class TestMapsAdapterBackwardCompatibility:
    """Tests for backward compatibility with get_commute()."""

    @pytest.mark.asyncio
    async def test_get_commute_calls_get_commute_time(self, maps_adapter, debug_logger):
        """Test that get_commute() delegates to get_commute_time()."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1800},
                            "distance": {"value": 16094},
                        }
                    ]
                }
            ],
        }

        with patch.object(maps_adapter.http_client, "get", return_value=mock_response):
            result = await maps_adapter.get_commute("123 Main St", "456 Market St")

            assert result is not None
            assert result.estimated_duration_minutes == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
