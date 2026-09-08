"""Set up and unload actual sensor platform and current device relationships."""

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from test_coordinator import make_coordinator


async def test_full_entry_sensor_setup_and_unload(hass):
    prepared = await make_coordinator(hass)
    with (
        patch("custom_components.glowbright.GlowmarktClient", return_value=prepared.client),
        patch("custom_components.glowbright.panel.async_update_panel", new_callable=AsyncMock),
    ):
        assert await hass.config_entries.async_setup(prepared.entry.entry_id)
        runtime = prepared.entry.runtime_data
        await runtime._task
        await hass.async_block_till_done()
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), prepared.entry.entry_id)
        assert len(devices) == 3
        assert sum(device.via_device_id == runtime.account_device_id for device in devices) == 2
        entities = er.async_entries_for_config_entry(er.async_get(hass), prepared.entry.entry_id)
        assert entities
        for entity in entities:
            state = hass.states.get(entity.entity_id)
            assert state is not None
            assert "state_class" not in state.attributes
        assert await hass.config_entries.async_unload(prepared.entry.entry_id)
        assert runtime.importer.stopping
