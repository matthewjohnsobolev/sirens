"""
Unit tests for alerts.api_client (UkraineAlarmClient).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from alerts.api_client import (
    UkraineAlarmAuthError,
    UkraineAlarmClient,
    UkraineAlarmError,
    UkraineAlarmNetworkError,
    UkraineAlarmRateLimitError,
)


class MockResponse:
    def __init__(
        self,
        status: int = 200,
        json_data: Any = None,
        text_data: str = "",
        headers: dict | None = None,
    ):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data
        self.headers = headers or {}

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_api_client_context_manager():
    async with UkraineAlarmClient(
        api_key="test_key", base_url="https://api.ukrainealarm.com"
    ) as client:
        assert client.api_key == "test_key"
        session = await client._get_session()
        assert not session.closed
    assert session.closed


@pytest.mark.asyncio
async def test_get_status_success():
    client = UkraineAlarmClient(api_key="test_key")
    mock_resp = MockResponse(status=200, json_data={"lastActionIndex": 42})

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        status = await client.get_status()
        assert status == 42
    await client.close()


@pytest.mark.asyncio
async def test_get_status_malformed_response():
    client = UkraineAlarmClient(api_key="test_key")
    mock_resp = MockResponse(status=200, json_data={"foo": "bar"})

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        with pytest.raises(UkraineAlarmError, match="Unexpected response"):
            await client.get_status()
    await client.close()


@pytest.mark.asyncio
async def test_get_active_alerts_success():
    client = UkraineAlarmClient(api_key="test_key")
    alerts_sample = [{"regionId": "10", "regionType": "State", "activeAlerts": []}]
    mock_resp = MockResponse(status=200, json_data=alerts_sample)

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        result = await client.get_active_alerts()
        assert result == alerts_sample
    await client.close()


@pytest.mark.asyncio
async def test_get_active_alerts_unexpected_type():
    client = UkraineAlarmClient(api_key="test_key")
    mock_resp = MockResponse(status=200, json_data={"error": "not a list"})

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        with pytest.raises(UkraineAlarmError, match="Unexpected response"):
            await client.get_active_alerts()
    await client.close()


@pytest.mark.asyncio
async def test_get_regions_success_dict_and_list():
    client = UkraineAlarmClient(api_key="test_key")

    mock_resp1 = MockResponse(status=200, json_data={"states": [{"regionId": "31"}]})
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp1):
        res1 = await client.get_regions()
        assert "states" in res1

    mock_resp2 = MockResponse(status=200, json_data=[{"regionId": "31"}])
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp2):
        res2 = await client.get_regions()
        assert "states" in res2

    mock_resp3 = MockResponse(status=200, json_data="not valid")
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp3):
        with pytest.raises(UkraineAlarmError):
            await client.get_regions()

    await client.close()


@pytest.mark.asyncio
async def test_auth_error_401():
    client = UkraineAlarmClient(api_key="bad_token")
    mock_resp = MockResponse(status=401, text_data="Unauthorized")

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        with pytest.raises(UkraineAlarmAuthError, match="401"):
            await client.get_status()
    await client.close()


@pytest.mark.asyncio
async def test_auth_error_403():
    client = UkraineAlarmClient(api_key="forbidden_token")
    mock_resp = MockResponse(status=403, text_data="Forbidden")

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        with pytest.raises(UkraineAlarmAuthError, match="403"):
            await client.get_status()
    await client.close()


@pytest.mark.asyncio
async def test_rate_limit_429_retry_and_exhaustion():
    client = UkraineAlarmClient(api_key="key")
    mock_resp = MockResponse(status=429, headers={"Retry-After": "0.01"})

    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(UkraineAlarmRateLimitError):
                await client._request("/test", max_retries=2)
            assert mock_sleep.await_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_server_error_500_retry_and_success():
    client = UkraineAlarmClient(api_key="key")
    resp_500 = MockResponse(status=500, text_data="Internal Server Error")
    resp_200 = MockResponse(status=200, json_data={"lastActionIndex": 10})

    call_count = 0

    def mock_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return resp_500 if call_count == 1 else resp_200

    with patch.object(aiohttp.ClientSession, "request", side_effect=mock_request):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            res = await client.get_status()
            assert res == 10
            assert call_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_server_error_500_exhaustion():
    client = UkraineAlarmClient(api_key="key")
    resp_500 = MockResponse(status=500, text_data="Internal Server Error")

    with patch.object(aiohttp.ClientSession, "request", return_value=resp_500):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(UkraineAlarmNetworkError):
                await client._request("/test", max_retries=2)
    await client.close()


@pytest.mark.asyncio
async def test_network_error_retry_and_exhaustion():
    client = UkraineAlarmClient(api_key="key")

    with patch.object(
        aiohttp.ClientSession,
        "request",
        side_effect=aiohttp.ClientConnectionError("Connection refused"),
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(UkraineAlarmNetworkError, match="Network error"):
                await client._request("/test", max_retries=2)
    await client.close()


@pytest.mark.asyncio
async def test_get_alerts_for_region():
    client = UkraineAlarmClient(api_key="key", base_url="https://api.ukrainealarm.com/api/v3")
    assert client.base_url == "https://api.ukrainealarm.com"

    mock_resp = MockResponse(status=200, json_data=[{"regionId": "31"}])
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        res = await client.get_alerts_for_region("31")
        assert res == [{"regionId": "31"}]

    mock_resp_err = MockResponse(status=200, json_data={"error": "bad"})
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp_err):
        with pytest.raises(UkraineAlarmError):
            await client.get_alerts_for_region("31")
    await client.close()


@pytest.mark.asyncio
async def test_get_date_history():
    client = UkraineAlarmClient(api_key="key")
    mock_resp = MockResponse(status=200, json_data=[{"regionId": "31", "startDate": "2022-02-24"}])
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        res = await client.get_date_history("20220224")
        assert len(res) == 1

    mock_resp_err = MockResponse(status=200, json_data={"error": "bad"})
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp_err):
        with pytest.raises(UkraineAlarmError):
            await client.get_date_history("20220224")
    await client.close()


@pytest.mark.asyncio
async def test_get_region_history():
    client = UkraineAlarmClient(api_key="key")
    mock_resp = MockResponse(status=200, json_data=[{"regionId": "31", "alarms": []}])
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp):
        res = await client.get_region_history("31")
        assert len(res) == 1

    mock_resp_err = MockResponse(status=200, json_data="not a list")
    with patch.object(aiohttp.ClientSession, "request", return_value=mock_resp_err):
        with pytest.raises(UkraineAlarmError):
            await client.get_region_history("31")
    await client.close()
