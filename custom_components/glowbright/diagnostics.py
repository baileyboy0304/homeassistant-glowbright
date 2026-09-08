"""Allowlisted diagnostics, never credentials or JWTs."""

from .const import VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "version": VERSION,
        "account_id": "**" + (entry.unique_id or "")[-4:],
        "resources": [r.as_dict() for r in coordinator.resources],
        "selected": {fuel: resource.key for fuel, resource in coordinator.selected.items()},
        "options": {
            k: v
            for k, v in coordinator.options.items()
            if k
            in {
                "backfill_days",
                "refresh_days",
                "panel_enabled",
                "gas_conversion",
                "volume_correction",
                "calorific_value",
            }
        },
        "status": coordinator.public_status(),
        "owned_statistics": coordinator.book["owned_ids"],
        "progress": coordinator.book["fuels"],
    }
