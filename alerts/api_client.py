"""
Asynchronous HTTP client for Ukraine Alert API 3.0 (https://api.ukrainealarm.com).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class UkraineAlarmError(Exception):
    """Base exception for Ukraine Alarm API interactions."""


class UkraineAlarmAuthError(UkraineAlarmError):
    """Raised on HTTP 401/403 authorization failures."""


class UkraineAlarmRateLimitError(UkraineAlarmError):
    """Raised on HTTP 429 rate limit exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UkraineAlarmNetworkError(UkraineAlarmError):
    """Raised on connection timeouts, DNS, or network drops."""


class UkraineAlarmClient:
    """
    Async client for polling status and fetching active alerts from Ukraine Alert API 3.0.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.ukrainealarm.com",
        session: aiohttp.ClientSession | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key.strip()
        cleaned_url = base_url.rstrip("/")
        if cleaned_url.endswith("/api/v3"):
            cleaned_url = cleaned_url[:-7]
        self.base_url = cleaned_url
        self.timeout = timeout
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": "Sirens/1.7.0",
            }
            timeout_cfg = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout_cfg)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed and self._owns_session:
            await self._session.close()

    async def __aenter__(self) -> UkraineAlarmClient:
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _request(
        self,
        path: str,
        method: str = "GET",
        max_retries: int = 3,
        base_backoff: float = 0.5,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        session = await self._get_session()
        req_headers = {
            "Authorization": self.api_key,
            "Accept": "application/json",
            "User-Agent": "Sirens/1.7.0",
        }

        for attempt in range(1, max_retries + 1):
            try:
                async with session.request(
                    method, url, headers=req_headers, params=params
                ) as response:
                    if response.status in (401, 403):
                        text = await response.text()
                        raise UkraineAlarmAuthError(
                            f"Authentication error {response.status} from {url}: {text}"
                        )

                    if response.status == 429:
                        retry_after_hdr = response.headers.get("Retry-After")
                        retry_after: float | None = None
                        if retry_after_hdr:
                            try:
                                retry_after = float(retry_after_hdr)
                            except ValueError:
                                pass
                        if attempt < max_retries:
                            sleep_time = retry_after or (base_backoff * (2 ** (attempt - 1)))
                            log.warning("Rate limited (429) on %s. Sleeping %.1fs", url, sleep_time)
                            await asyncio.sleep(sleep_time)
                            continue
                        raise UkraineAlarmRateLimitError(
                            f"Rate limit exceeded (429) for {url}", retry_after=retry_after
                        )

                    if response.status >= 500:
                        if attempt < max_retries:
                            sleep_time = base_backoff * (2 ** (attempt - 1))
                            log.warning(
                                "Server error %s on %s (attempt %d/%d). Retrying in %.1fs",
                                response.status,
                                url,
                                attempt,
                                max_retries,
                                sleep_time,
                            )
                            await asyncio.sleep(sleep_time)
                            continue
                        response.raise_for_status()

                    response.raise_for_status()
                    return await response.json()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries:
                    sleep_time = base_backoff * (2 ** (attempt - 1))
                    log.debug(
                        "Network error on %s: %s (attempt %d/%d). Retrying in %.1fs",
                        url,
                        e,
                        attempt,
                        max_retries,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    raise UkraineAlarmNetworkError(
                        f"Network error requesting {url} after {max_retries} attempts: {e}"
                    ) from e

    async def get_status(self) -> int:
        """
        Polls GET /api/v3/alerts/status.
        Returns lastActionIndex integer.
        """
        data = await self._request("/api/v3/alerts/status", max_retries=2)
        if isinstance(data, dict):
            idx = data.get("lastActionIndex")
            if idx is not None:
                return int(idx)
        raise UkraineAlarmError(f"Unexpected response from /api/v3/alerts/status: {data}")

    async def get_active_alerts(self) -> list[dict[str, Any]]:
        """
        Fetches active alerts from GET /api/v3/alerts.
        Returns list of regions with active alerts.
        """
        data = await self._request("/api/v3/alerts", max_retries=3)
        if isinstance(data, list):
            return data
        raise UkraineAlarmError(f"Unexpected response from /api/v3/alerts: {data}")

    async def get_regions(self) -> dict[str, Any]:
        """
        Fetches regional tree from GET /api/v3/regions.
        """
        data = await self._request("/api/v3/regions", max_retries=3)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"states": data}
        raise UkraineAlarmError(f"Unexpected response from /api/v3/regions: {data}")

    async def get_alerts_for_region(self, region_id: str) -> list[dict[str, Any]]:
        """
        Fetches active alerts for a specific region from GET /api/v3/alerts/{regionId}.
        """
        data = await self._request(f"/api/v3/alerts/{region_id}", max_retries=3)
        if isinstance(data, list):
            return data
        raise UkraineAlarmError(f"Unexpected response from /api/v3/alerts/{region_id}: {data}")

    async def get_date_history(self, date: str) -> list[dict[str, Any]]:
        """
        Fetches alert history by date from GET /api/v3/alerts/dateHistory?date={date}.
        Format: YYYYMMDD (e.g. '20220224').
        """
        data = await self._request(
            "/api/v3/alerts/dateHistory", params={"date": date}, max_retries=3
        )
        if isinstance(data, list):
            return data
        raise UkraineAlarmError(f"Unexpected response from /api/v3/alerts/dateHistory: {data}")

    async def get_region_history(self, region_id: str) -> list[dict[str, Any]]:
        """
        Fetches last 25 alerts for a region from GET /api/v3/alerts/regionHistory?regionId={regionId}.
        """
        data = await self._request(
            "/api/v3/alerts/regionHistory", params={"regionId": region_id}, max_retries=3
        )
        if isinstance(data, list):
            return data
        raise UkraineAlarmError(f"Unexpected response from /api/v3/alerts/regionHistory: {data}")
