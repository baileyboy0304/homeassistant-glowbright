"""Account lifecycle, stream isolation, durable progress, and real statistics."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glowbright.api import ApiError
from custom_components.glowbright.coordinator import GlowBrightCoordinator
from custom_components.glowbright.diagnostics import async_get_config_entry_diagnostics
from custom_components.glowbright.models import Resource
from custom_components.glowbright.statistics import metadata, statistic_id
from custom_components.glowbright.websocket import get_series

MONDAY = datetime(2026, 9, 7, tzinfo=UTC)


async def make_coordinator(hass, dual=True, cost=True, options=None):
    resources = [
        Resource(
            "a",
            "Full",
            "e",
            "Electricity",
            "electricity.consumption",
            "kWh",
            first_time=MONDAY,
            last_time=MONDAY + timedelta(hours=23, minutes=30),
        ),
        Resource("a", "Full", "stale", "Old gas", "gas.consumption", "kWh"),
        Resource(
            "b",
            "DCC",
            "g",
            "Gas",
            "gas.consumption",
            "m³",
            first_time=MONDAY,
            last_time=MONDAY + timedelta(hours=23, minutes=30),
        ),
        Resource(
            "a",
            "Full",
            "ec",
            "Electricity cost",
            "electricity.consumption.cost",
            "pence",
            first_time=MONDAY,
            last_time=MONDAY + timedelta(hours=23, minutes=30),
        ),
        Resource(
            "b", "DCC", "wrong", "Wrong electricity cost", "electricity.consumption.cost", "pence"
        ),
    ]
    entry = MockConfigEntry(
        domain="glowbright",
        title="GlowBright",
        unique_id="account",
        data={"username": "private@example.com", "password": "secret", "account_id": "account"},
        options={
            "electricity": "a/e",
            "gas": "b/g" if dual else "none",
            "electricity_cost": "a/ec" if cost else "none",
            "gas_cost": "none",
            **(options or {}),
        },
    )
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.discover.return_value = resources
    client.boundary.return_value = MONDAY + timedelta(hours=23, minutes=30)
    client.tariff.return_value = {"unit_rate": 25, "standing_charge": 55}

    async def readings(resource_id, start, end, period, last_time):
        increment = timedelta(minutes=30) if period == "PT30M" else timedelta(hours=1)
        step = max(start, MONDAY)
        values = {}
        while step < min(end, MONDAY + timedelta(days=1)):
            values[step] = 10 if resource_id == "ec" else 1
            step += increment
        return values

    client.readings.side_effect = readings
    coordinator = GlowBrightCoordinator(hass, entry, client)
    entry.runtime_data = coordinator
    await coordinator.initialize()
    return coordinator


@pytest.mark.parametrize("dual,cost", [(False, False), (True, False), (True, True)])
async def test_selected_resources_and_costs(hass, freezer, dual, cost):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(hass, dual, cost)
    await coordinator._recent()
    ids = {call.args[0] for call in coordinator.client.readings.call_args_list}
    assert ids == {"e"} | ({"g"} if dual else set()) | ({"ec"} if cost else set())
    for fuel in coordinator.selected:
        rows = await coordinator.importer.series(
            statistic_id(coordinator.entry.entry_id, fuel), MONDAY, None
        )
        assert len(rows) == 24
        assert rows[-1]["sum"] == 48
    costs = await coordinator.importer.series(
        statistic_id(coordinator.entry.entry_id, "electricity", "cost"), MONDAY, None
    )
    assert len(costs) == (24 if cost else 0)
    if cost:
        assert costs[-1]["sum"] == pytest.approx(4.8)
        assert costs[0]["state"] == pytest.approx(0.2)  # no standing charge


async def test_outage_tariff_and_last_good(hass, freezer):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(hass)
    await coordinator._recent()
    before = await coordinator.importer.series(
        statistic_id(coordinator.entry.entry_id, "electricity"), MONDAY, None
    )
    coordinator.client.readings.side_effect = ApiError("Temporary outage")
    coordinator.client.tariff.side_effect = ApiError("No tariff")
    await coordinator._recent()
    assert before == await coordinator.importer.series(
        statistic_id(coordinator.entry.entry_id, "electricity"), MONDAY, None
    )
    assert coordinator.status["fuels"]["electricity"]["tariff"]["standing_charge"] == 55
    assert not coordinator.auth_failed
    assert coordinator.status["api_error"]


async def test_resource_change_rebuilds_one_fuel(hass, freezer):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(hass)
    await coordinator._recent()
    gas_id = statistic_id(coordinator.entry.entry_id, "gas")
    gas = await coordinator.importer.series(gas_id, MONDAY, None)
    coordinator.client.discover.return_value.append(
        Resource("c", "New", "e2", "New electricity", "electricity.consumption", "kWh")
    )
    hass.config_entries.async_update_entry(
        coordinator.entry, options={**coordinator.entry.options, "electricity": "c/e2"}
    )
    replacement = GlowBrightCoordinator(hass, coordinator.entry, coordinator.client)
    await replacement.initialize()
    assert (
        await replacement.importer.series(
            statistic_id(coordinator.entry.entry_id, "electricity"), MONDAY, None
        )
        == []
    )
    assert await replacement.importer.series(gas_id, MONDAY, None) == gas


async def test_conversion_is_explicit(hass, freezer):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(
        hass, options={"gas_conversion": True, "calorific_value": 40, "volume_correction": 1.02264}
    )
    await coordinator._recent()
    rows = await coordinator.importer.series(
        statistic_id(coordinator.entry.entry_id, "gas"), MONDAY, None
    )
    assert rows[-1]["sum"] == pytest.approx(48 * 1.02264 * 40 / 3.6)
    assert coordinator.public_status()["fuels"]["gas"]["estimated_conversion"]


async def test_resume_backfill_and_failed_chunk(hass, freezer):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(
        hass, dual=False, cost=False, options={"backfill_days": 80}
    )
    coordinator.selected["electricity"].first_time = MONDAY - timedelta(days=90)
    calls = []

    async def readings(resource_id, start, end, period, last_time):
        calls.append((start, end, period))
        if len(calls) == 2:
            raise ApiError("Temporary chunk failure")
        return {start: 1}

    coordinator.client.readings.side_effect = readings
    with patch("custom_components.glowbright.coordinator.asyncio.sleep", new_callable=AsyncMock):
        await coordinator._backfill()
    progress = coordinator.book["fuels"]["electricity"]["streams"]["consumption"]
    cursor = progress["cursor"]
    assert not progress["complete"]
    assert progress["last_error"]
    restarted = GlowBrightCoordinator(hass, coordinator.entry, coordinator.client)
    await restarted.initialize()
    with patch("custom_components.glowbright.coordinator.asyncio.sleep", new_callable=AsyncMock):
        await restarted._backfill()
    assert calls[2][0].isoformat() == cursor
    assert all(
        end - start <= timedelta(days=30) and period == "PT1H" for start, end, period in calls
    )
    assert restarted.book["fuels"]["electricity"]["streams"]["consumption"]["complete"]


async def test_diagnostics_and_cached_series(hass, freezer):
    freezer.move_to(MONDAY + timedelta(days=2))
    coordinator = await make_coordinator(hass)
    first = await get_series(
        coordinator, "electricity", "usage", "PT30M", MONDAY, MONDAY + timedelta(days=1)
    )
    coordinator.client.readings.side_effect = ApiError("Temporary outage")
    freezer.tick(timedelta(minutes=11))
    cached = await get_series(
        coordinator, "electricity", "usage", "PT30M", MONDAY, MONDAY + timedelta(days=1)
    )
    assert cached["cached"]
    assert cached["rows"] == first["rows"]
    diagnostic = await async_get_config_entry_diagnostics(hass, coordinator.entry)
    serialized = json.dumps(diagnostic)
    assert (
        "secret" not in serialized
        and "password" not in serialized
        and "private@example.com" not in serialized
    )


async def test_unload_cancels_background(hass):
    coordinator = await make_coordinator(hass)
    started = asyncio.Event()

    async def stuck():
        started.set()
        await asyncio.Event().wait()

    coordinator._background = stuck
    coordinator.start()
    await started.wait()
    await coordinator.stop()
    assert coordinator._task.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await coordinator.importer.series("glowbright:any", MONDAY, None)


async def test_energy_change_includes_first_hour(hass):
    coordinator = await make_coordinator(hass)
    meta = metadata(coordinator.entry.entry_id, "electricity", "kWh")
    await coordinator.importer.rewrite(meta, {MONDAY: 2, MONDAY + timedelta(hours=1): 3})
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        MONDAY,
        MONDAY + timedelta(days=1),
        {meta["statistic_id"]},
        "hour",
        None,
        {"change"},
    )
    assert [row["change"] for row in result[meta["statistic_id"]]] == [2, 3]
