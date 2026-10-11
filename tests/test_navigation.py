"""Launcher options and shared native panel registration boundaries."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glowbright.const import DEFAULT_HOME_PATH
from custom_components.glowbright.navigation import home_path_or_default, validate_home_path
from custom_components.glowbright.panel import async_update_panel


@pytest.mark.parametrize(
    "value",
    [
        "https://external.test/home",
        "//external.test",
        "/\\external.test",
        "/%2fexternal.test",
        "/%5cexternal.test",
        "/a/../home",
        "/%2e%2e//host",
        "/\n/host",
        "/%09/host",
        "/%",
        "/%FF",
        "relative",
        "",
        None,
    ],
)
def test_unsafe_paths(value):
    with pytest.raises((ValueError, UnicodeError)):
        validate_home_path(value)
    assert home_path_or_default(value) == DEFAULT_HOME_PATH


async def test_shared_panel_path_survives_refresh_and_updates(hass):
    first = MockConfigEntry(domain="glowbright", options={"home_path": "/launcher/home"})
    second = MockConfigEntry(domain="glowbright", options={"home_path": "/other/home"})
    for entry in (first, second):
        entry.add_to_hass(hass)
        entry.runtime_data = Mock()
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with (
        patch(
            "custom_components.glowbright.panel.panel_custom.async_register_panel",
            new_callable=AsyncMock,
        ) as register,
        patch("custom_components.glowbright.panel.frontend.async_remove_panel") as remove,
    ):
        await async_update_panel(hass)
        assert register.call_args.kwargs["config"] == {"home_path": "/launcher/home"}
        assert register.call_args.kwargs["require_admin"] is False
        await async_update_panel(hass)
        assert register.await_count == 1
        hass.config_entries.async_update_entry(first, options={"home_path": "/new/home"})
        await async_update_panel(hass)
        assert register.call_args.kwargs["config"] == {"home_path": "/new/home"}
        remove.assert_called_once_with(hass, "glowbright")
        assert hass.http.async_register_static_paths.await_count == 1


async def test_home_option_rejects_host_and_persists_local_path(hass):
    from custom_components.glowbright.models import Resource

    entry = MockConfigEntry(
        domain="glowbright", unique_id="account", data={"username": "demo", "password": "test"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {
        "backfill_days": 365,
        "refresh_days": 7,
        "panel_enabled": True,
        "gas_conversion": False,
        "volume_correction": 1.02264,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**defaults, "home_path": "//external.test"}
    )
    assert result["errors"] == {"home_path": "invalid_home_path"}
    with patch(
        "custom_components.glowbright.config_flow.GlowmarktClient.discover",
        new_callable=AsyncMock,
        return_value=[Resource("a", "Full", "e", "Electricity", "electricity.consumption", "kWh")],
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**defaults, "home_path": "/custom/home"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"resource": "a/e"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"resource": "none"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"electricity_cost": "none", "gas_cost": "none"}
        )
        result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert entry.options["home_path"] == "/custom/home"
