"""WebSocket validation, account isolation and access controls."""

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from unittest.mock import Mock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_metadata
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_coordinator import make_coordinator

from custom_components.glowbright.statistics import StatisticsImporter, metadata
from custom_components.glowbright.websocket import async_register_commands, get_series, resolve


async def test_ws_rejects_non_glowbright_entry(hass, hass_ws_client):
    other = MockConfigEntry(domain="demo", data={})
    other.add_to_hass(hass)
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "glowbright/get_status", "entry_id": other.entry_id})
    result = await client.receive_json()
    assert not result["success"]
    assert result["error"]["code"] == "not_found"


async def test_ws_no_credentials(hass, hass_ws_client):
    coordinator = await make_coordinator(hass)
    async_register_commands(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "glowbright/get_status", "entry_id": coordinator.entry.entry_id}
    )
    result = await client.receive_json()
    assert result["success"]
    assert (
        "password" not in str(result)
        and "secret" not in str(result)
        and "private@example.com" not in str(result)
    )


async def test_permissions_are_per_fuel(hass):
    coordinator = await make_coordinator(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", "glowbright", "account_a/e_daily_usage", config_entry=coordinator.entry
    )
    connection = Mock()
    connection.user.is_admin = False
    connection.user.permissions.check_entity.side_effect = lambda entity_id, policy: (
        entity_id == entity.entity_id
    )
    assert resolve(hass, connection, coordinator.entry.entry_id, "electricity") is coordinator
    with pytest.raises(PermissionError):
        resolve(hass, connection, coordinator.entry.entry_id, "gas")


async def test_series_rejects_unbounded_and_naive_ranges(hass):
    coordinator = await make_coordinator(hass)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        await get_series(
            coordinator, "electricity", "usage", "PT30M", start, start + timedelta(days=2)
        )
    with pytest.raises(ValueError):
        await get_series(
            coordinator, "electricity", "usage", "PT1H", start, start + timedelta(days=4000)
        )


async def test_actual_recorder_metadata(hass):
    importer = StatisticsImporter(hass)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    expected = [
        ("electricity", "kWh", "consumption", "energy"),
        ("gas", "m³", "consumption", "volume"),
        ("electricity", "GBP", "cost", None),
    ]
    for fuel, unit, metric, unit_class in expected:
        meta = metadata("entry", fuel, unit, metric)
        await importer.rewrite(meta, {start: 2})
        result = await get_instance(hass).async_add_executor_job(
            partial(get_metadata, hass, statistic_ids={meta["statistic_id"]})
        )
        actual = result[meta["statistic_id"]][1]
        assert actual["unit_class"] == unit_class
        assert actual["unit_of_measurement"] == unit
        assert actual["mean_type"] == 0 and actual["has_sum"]


async def test_cancellation_drains_inflight_query(hass):
    importer = StatisticsImporter(hass)
    future = hass.loop.create_future()
    recorder = get_instance(hass)
    with patch.object(recorder, "async_add_executor_job", return_value=future) as execute:
        task = asyncio.create_task(importer._executor(lambda: None))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        future.set_result(None)
        with pytest.raises(asyncio.CancelledError):
            await task
        execute.assert_called_once()
    importer.stopping = True
    with pytest.raises(asyncio.CancelledError):
        await importer._executor(lambda: None)
