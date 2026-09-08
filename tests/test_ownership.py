"""Removal never touches another integration or GlowBright account."""

from datetime import UTC, datetime

import pytest
from test_coordinator import make_coordinator

from custom_components.glowbright import async_migrate_entry, async_remove_entry
from custom_components.glowbright.statistics import metadata


async def test_entry_removal_preserves_other_account(hass):
    coordinator = await make_coordinator(hass)
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    own = metadata(coordinator.entry.entry_id, "electricity", "kWh")
    other = metadata("other_account", "electricity", "kWh")
    await coordinator.importer.rewrite(own, {stamp: 1})
    await coordinator.importer.rewrite(other, {stamp: 2})
    await async_remove_entry(hass, coordinator.entry)
    assert not await coordinator.importer.series(own["statistic_id"], stamp, None)
    assert (await coordinator.importer.series(other["statistic_id"], stamp, None))[0]["state"] == 2
    with pytest.raises(ValueError):
        await coordinator.importer.clear_owned(coordinator.entry.entry_id, [other["statistic_id"]])


async def test_v1_migration(hass):
    coordinator = await make_coordinator(hass)
    assert await async_migrate_entry(hass, coordinator.entry)
