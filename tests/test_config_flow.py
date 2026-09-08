"""Exercise actual HA config-entry flows with independent meter choices."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glowbright.models import Resource


@pytest.fixture
def discovery():
    return [
        Resource("a", "Full", "e", "Electricity", "electricity.consumption", "kWh"),
        Resource("a", "Full", "stale", "Old gas", "gas.consumption", "kWh"),
        Resource("b", "DCC", "g", "Gas", "gas.consumption", "m³"),
    ]


async def test_independent_flow(hass, discovery):
    with (
        patch(
            "custom_components.glowbright.config_flow.GlowmarktClient.authenticate",
            AsyncMock(return_value="account"),
        ),
        patch(
            "custom_components.glowbright.config_flow.GlowmarktClient.discover",
            AsyncMock(return_value=discovery),
        ),
        patch("custom_components.glowbright.async_setup_entry", create=True, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            "glowbright",
            context={"source": "user"},
            data={"username": "user", "password": "secret"},
        )
        assert result["step_id"] == "electricity"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"resource": "a/e"}
        )
        assert result["step_id"] == "gas"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"resource": "b/g"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"electricity_cost": "none", "gas_cost": "none"}
        )
        assert result["step_id"] == "confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] == "create_entry"
        entry = result["result"]
        assert entry.unique_id == "account"
        assert entry.options["electricity"] == "a/e"
        assert entry.options["gas"] == "b/g"
        assert "electricity" not in entry.data


async def test_duplicate_account(hass):
    MockConfigEntry(domain="glowbright", unique_id="account", data={}).add_to_hass(hass)
    with patch(
        "custom_components.glowbright.config_flow.GlowmarktClient.authenticate",
        AsyncMock(return_value="account"),
    ):
        result = await hass.config_entries.flow.async_init(
            "glowbright",
            context={"source": "user"},
            data={"username": "user", "password": "secret"},
        )
    assert result["reason"] == "already_configured"


async def test_reauthentication_wrong_account(hass):
    entry = MockConfigEntry(
        domain="glowbright", unique_id="account", data={"username": "user", "password": "old"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "glowbright", context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
    )
    with patch(
        "custom_components.glowbright.config_flow.GlowmarktClient.authenticate",
        AsyncMock(return_value="different"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "user", "password": "new"}
        )
    assert result["reason"] == "wrong_account"
    assert entry.data["password"] == "old"


async def test_options_require_calorific_value(hass):
    entry = MockConfigEntry(
        domain="glowbright",
        unique_id="account",
        data={"username": "user", "password": "secret"},
        options={"electricity": "a/e", "gas": "none"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "backfill_days": 365,
            "refresh_days": 7,
            "panel_enabled": True,
            "gas_conversion": True,
            "volume_correction": 1.02264,
        },
    )
    assert result["errors"]["base"] == "calorific_required"
