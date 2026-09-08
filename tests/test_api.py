"""Official API wire contract, duplicate resources and retry boundaries."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import time
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientConnectionError, ClientSession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
    mock_aiohttp_client,
)

from custom_components.glowbright.api import ApiError, AuthError, GlowmarktClient
from custom_components.glowbright.const import API_URL
from custom_components.glowbright.models import Resource, cost_candidates


@contextmanager
def http_responses(api_client):
    """Sequence responses using HA's current aiohttp mock implementation."""
    with mock_aiohttp_client() as client:
        object.__setattr__(api_client.session, "_request", client.match_request)
        queues = {}

        class Responses:
            @property
            def requests(self):
                return {(method.upper(), url): None for method, url, *_ in client.mock_calls}

            def register(
                self,
                method,
                url,
                *,
                payload=None,
                status=200,
                body=None,
                exception=None,
                repeat=False,
            ):
                key = (method, url)
                response = AiohttpClientMockResponse(
                    method, url, status=status, json=payload, text=body, exc=exception
                )
                if key not in queues:
                    queues[key] = []

                    async def next_response(method, url, data):
                        if not queues[key]:
                            raise AssertionError("Unexpected extra request")
                        item, repeat = queues[key][0]
                        if not repeat:
                            queues[key].pop(0)
                        return item

                    client.request(method, url, side_effect=next_response)
                queues[key].append((response, repeat))

            def get(self, url, **kwargs):
                self.register("get", url, **kwargs)

            def post(self, url, **kwargs):
                self.register("post", url, **kwargs)

        yield Responses()


@pytest.fixture
async def client():
    async with ClientSession() as session:
        client = GlowmarktClient(session, "user", "secret", "account")
        client._token = "token"
        client._expiry = time() + 3600
        yield client


@pytest.mark.parametrize("expiry", [0, 3600])
async def test_expired_and_server_rejected_token(client, expiry):
    client._expiry = time() + expiry
    with http_responses(client) as mock:
        if expiry:
            mock.get(API_URL + "/virtualentity", status=401)
        mock.post(
            API_URL + "/auth",
            payload={"valid": True, "accountId": "account", "token": "new", "exp": time() + 3600},
        )
        mock.get(API_URL + "/virtualentity", payload=[])
        assert await client.get("/virtualentity") == []
        assert client._token == "new"


async def test_only_one_reauthentication(client):
    with http_responses(client) as mock:
        mock.get(API_URL + "/virtualentity", status=401, repeat=True)
        mock.post(
            API_URL + "/auth",
            payload={"valid": True, "accountId": "account", "token": "new", "exp": time() + 3600},
        )
        with pytest.raises(AuthError):
            await client.get("/virtualentity")
        assert len([key for key in mock.requests if key[0] == "POST"]) == 1


@pytest.mark.parametrize("failure", [500, 429, "network"])
async def test_transient_retry(client, failure):
    with (
        http_responses(client) as mock,
        patch("custom_components.glowbright.api.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        if failure == "network":
            mock.get(API_URL + "/virtualentity", exception=ClientConnectionError())
        else:
            mock.get(API_URL + "/virtualentity", status=failure)
        mock.get(API_URL + "/virtualentity", payload=[])
        assert await client.get("/virtualentity") == []
        sleep.assert_awaited_once()


async def test_failure_is_sanitized(client):
    with (
        http_responses(client) as mock,
        patch("custom_components.glowbright.api.asyncio.sleep", new_callable=AsyncMock),
    ):
        mock.get(API_URL + "/virtualentity", status=500, body="secret token", repeat=True)
        with pytest.raises(ApiError, match="temporarily unavailable") as error:
            await client.get("/virtualentity")
        assert "secret" not in str(error.value)


async def test_discovery_keeps_duplicate_classifiers(client):
    with http_responses(client) as mock:
        mock.get(
            API_URL + "/virtualentity",
            payload=[{"veId": "a", "name": "Full"}, {"veId": "b", "name": "DCC"}],
        )
        for ve in ("a", "b"):
            resources = [
                {
                    "resourceId": f"{ve}-{fuel}-{index}",
                    "classifier": f"{fuel}.consumption",
                    "baseUnit": "kWh",
                }
                for fuel in ("electricity", "gas")
                for index in (1, 2)
            ]
            mock.get(API_URL + f"/virtualentity/{ve}/resources", payload=resources)
            for resource in resources:
                for boundary, key in (("first-time", "firstTs"), ("last-time", "lastTs")):
                    mock.get(
                        API_URL + f"/resource/{resource['resourceId']}/{boundary}",
                        payload={"data": {key: 1700000000}},
                    )
        resources = await client.discover()
        assert len(resources) == 8
        assert len({r.key for r in resources}) == 8
        assert all(r.last_time is not None for r in resources)


async def test_nulls_zeros_and_half_open_chunks(client):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    boundary = start + timedelta(days=9)
    end = boundary + timedelta(hours=1)
    with (
        http_responses(client) as mock,
        patch("custom_components.glowbright.api.asyncio.sleep", new_callable=AsyncMock),
    ):
        matcher = re.compile(re.escape(API_URL + "/resource/r/readings") + r"\?.*")
        mock.get(
            matcher,
            payload={
                "data": [
                    [start.timestamp(), 0],
                    [(start + timedelta(minutes=30)).timestamp(), None],
                    [boundary.timestamp(), 99],
                ]
            },
        )
        mock.get(matcher, payload={"data": [[boundary.timestamp(), 4], [end.timestamp(), 88]]})
        readings = await client.readings("r", start, end, "PT30M", end)
        assert readings == {start: 0, boundary: 4}
        assert all("nulls=1" in str(url) for _, url in mock.requests)


async def test_excessive_range_halves_chunk(client):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with (
        http_responses(client) as mock,
        patch("custom_components.glowbright.api.asyncio.sleep", new_callable=AsyncMock),
    ):
        matcher = re.compile(re.escape(API_URL + "/resource/r/readings") + r"\?.*")
        mock.get(matcher, status=400, body="maximum range exceeded")
        mock.get(matcher, payload={"data": []}, repeat=True)
        assert await client.readings("r", start, start + timedelta(days=30), "PT1H", None) == {}
        calls = list(mock.requests)
        assert len(calls) == 3


def test_cost_pairing_stays_in_ve():
    consumption = Resource("a", "A", "r", "Electricity", "electricity.consumption", "kWh")
    wrong = Resource("b", "B", "c", "Cost", "electricity.consumption.cost", "pence")
    correct = Resource("a", "A", "d", "Cost", "electricity.consumption.cost", "pence")
    assert cost_candidates([wrong, correct], consumption) == [correct]
    assert cost_candidates([wrong], consumption) == []
