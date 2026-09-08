"""Small asynchronous client for the official Bright individual-user API."""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from math import isfinite
from time import time
from urllib.parse import quote

import aiohttp

from .const import API_URL, BACKFILL_CHUNK_DAYS, BRIGHT_APPLICATION_ID, PT30M_MAX_DAYS
from .models import Resource, utc


class ApiError(Exception):
    """Sanitized transport/protocol error; never carries response bodies."""


class AuthError(ApiError):
    """Credentials rejected or authenticated account changed."""


class RangeError(ApiError):
    """An excessive query range was rejected."""


class GlowmarktClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        account_id: str | None = None,
    ):
        self.session = session
        self._username = username
        self._password = password
        self.account_id = account_id
        self._token: str | None = None
        self._expiry = 0.0
        self._auth_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, **kwargs):
        for attempt in range(4):
            try:
                async with self.session.request(
                    method, API_URL + path, timeout=aiohttp.ClientTimeout(total=30), **kwargs
                ) as response:
                    if response.status == 401:
                        raise AuthError("Authentication rejected")
                    if response.status == 400:
                        # Inspect only to classify; never include the body in errors/logs.
                        body = (await response.text()).lower()
                        if any(
                            term in body
                            for term in (
                                "range",
                                "maximum",
                                "too many",
                                "too large",
                                "period limit",
                            )
                        ):
                            raise RangeError("Requested range exceeds API limit")
                        raise ApiError("Invalid API request")
                    if response.status == 429 or response.status >= 500:
                        if attempt == 3:
                            raise ApiError(f"API temporarily unavailable (HTTP {response.status})")
                        retry = response.headers.get("Retry-After", "")
                        delay = (
                            min(float(retry), 120)
                            if retry.isdigit()
                            else 2**attempt + random.random()
                        )
                    elif response.status >= 400:
                        raise ApiError(f"API request failed (HTTP {response.status})")
                    else:
                        result = await response.json()
                        if isinstance(result, dict) and result.get("status") == "ERROR":
                            raise ApiError("API returned an error")
                        return result
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                if attempt == 3:
                    raise ApiError("Unable to communicate with Glowmarkt") from err
                delay = 2**attempt + random.random()
            await asyncio.sleep(delay)
        raise ApiError("Retry limit exceeded")

    async def authenticate(self, rejected_token: str | None = None) -> str:
        async with self._auth_lock:
            if self._token and self._expiry > time() + 120 and self._token != rejected_token:
                return self.account_id
            self._token = None
            result = await self._request(
                "POST",
                "/auth",
                headers={"applicationId": BRIGHT_APPLICATION_ID},
                json={"username": self._username, "password": self._password},
            )
            if (
                not isinstance(result, dict)
                or not result.get("valid")
                or not result.get("token")
                or not result.get("accountId")
            ):
                raise AuthError("Bright credentials were rejected")
            if self.account_id and result["accountId"] != self.account_id:
                raise AuthError("Bright account identity changed")
            self.account_id = result["accountId"]
            self._token = result["token"]
            self._expiry = float(result.get("exp", 0))
            return self.account_id

    async def get(self, path: str, **kwargs):
        await self.authenticate()
        token = self._token
        for attempt in range(2):
            try:
                return await self._request(
                    "GET",
                    path,
                    headers={"applicationId": BRIGHT_APPLICATION_ID, "token": self._token},
                    **kwargs,
                )
            except AuthError:
                if attempt:
                    self._token = None
                    raise
                await self.authenticate(rejected_token=token)

    @staticmethod
    def resource_path(resource_id: str, suffix: str) -> str:
        return f"/resource/{quote(resource_id, safe='')}/{suffix}"

    async def boundary(self, resource_id: str, first: bool = False) -> datetime | None:
        result = await self.get(
            self.resource_path(resource_id, "first-time" if first else "last-time")
        )
        data = result.get("data", [])
        if not data:
            return None
        value = (
            data.get("firstTs" if first else "lastTs")
            if isinstance(data, dict)
            else data[0][0]
            if isinstance(data[0], list)
            else data[0]
        )
        return datetime.fromtimestamp(float(value), UTC) if value is not None else None

    async def discover(self) -> list[Resource]:
        entities = await self.get("/virtualentity")
        resources: dict[tuple[str, str], Resource] = {}
        for ve in entities:
            ve_id = ve["veId"]
            result = await self.get(f"/virtualentity/{quote(ve_id, safe='')}/resources")
            for item in result.get("resources", []) if isinstance(result, dict) else result:
                classifier = item.get("classifier", "")
                if not item.get("active", True) or classifier not in {
                    f"{fuel}.consumption{suffix}"
                    for fuel in ("electricity", "gas")
                    for suffix in ("", ".cost")
                }:
                    continue
                resource = Resource(
                    ve_id,
                    ve.get("name", ve_id),
                    item["resourceId"],
                    item.get("name", classifier),
                    classifier,
                    item.get("baseUnit") or item.get("units", {}).get("readings", ""),
                )
                for first, attr in ((True, "first_time"), (False, "last_time")):
                    try:
                        setattr(resource, attr, await self.boundary(resource.resource_id, first))
                    except AuthError:
                        raise
                    except ApiError:
                        pass
                resources[(ve_id, resource.resource_id)] = resource
        return list(resources.values())

    async def readings(
        self,
        resource_id: str,
        start: datetime,
        end: datetime,
        period: str,
        last_time: datetime | None,
    ) -> dict[datetime, float]:
        """Chunk and filter logical half-open UTC ranges, retaining genuine zeros."""
        start, end = utc(start), utc(end)
        if period not in ("PT30M", "PT1H"):
            raise ValueError("Unsupported API interval")
        result: dict[datetime, float] = {}
        chunk = timedelta(days=PT30M_MAX_DAYS - 1 if period == "PT30M" else BACKFILL_CHUNK_DAYS)
        cursor = start
        while cursor < end:
            stop = min(cursor + chunk, end)
            try:
                payload = await self.get(
                    self.resource_path(resource_id, "readings"),
                    params={
                        "from": cursor.strftime("%Y-%m-%dT%H:%M:%S"),
                        "to": stop.strftime("%Y-%m-%dT%H:%M:%S"),
                        "period": period,
                        "offset": "0",
                        "function": "sum",
                        "nulls": "1",
                    },
                )
            except RangeError:
                if chunk <= timedelta(hours=1):
                    raise
                chunk = timedelta(hours=max(1, int(chunk.total_seconds() / 7200)))
                continue
            for stamp, value in payload.get("data", []):
                stamp = datetime.fromtimestamp(float(stamp), UTC)
                if (
                    cursor <= stamp < stop
                    and (last_time is None or stamp <= last_time)
                    and value is not None
                ):
                    value = float(value)
                    if isfinite(value) and value >= 0:
                        result[stamp] = value
            cursor = stop
            if cursor < end:
                await asyncio.sleep(0.25)
        return result

    async def catchup(self, resource_id: str):
        return await self.get(self.resource_path(resource_id, "catchup"))

    async def tariff(self, resource_id: str) -> dict:
        """Return current pence rates; never reconstruct historical costs."""
        payload = await self.get(self.resource_path(resource_id, "tariff"))
        entries = payload.get("data", [])
        if not entries:
            raise ApiError("No current tariff available")
        tariff = entries[0]
        current = tariff.get("currentRates", {})
        rate = current.get("rate")
        standing = current.get("standingCharge")
        # Swagger documents flat-rate planDetail; TOU/dynamic rates must not
        # masquerade as one current rate without a currentRates value.
        details = [d for plan in tariff.get("plan", []) for d in plan.get("planDetail", [])]
        rates = [d["rate"] for d in details if "rate" in d]
        if rate is None and len(rates) == 1 and not any("tourate" in d for d in details):
            rate = rates[0]
        charges = [d["standing"] for d in details if "standing" in d]
        if standing is None and len(charges) == 1:
            standing = charges[0]

        def number(value):
            try:
                value = float(value)
                return value if isfinite(value) else None
            except TypeError, ValueError:
                return None

        return {"unit_rate": number(rate), "standing_charge": number(standing)}

    async def tariff_list(self, resource_id: str):
        """Available for diagnostics/future tariff-history support, not estimates."""
        return await self.get(self.resource_path(resource_id, "tariff-list"))
