"""Informational sensors; historical external statistics feed Energy."""

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

FUEL_SENSORS = {
    "daily_usage": ("Latest available daily usage", None, None),
    "data_date": ("Latest available data date", SensorDeviceClass.DATE, None),
    "latest_reading": ("Latest DCC reading", SensorDeviceClass.TIMESTAMP, None),
    "data_age_hours": ("Data age", SensorDeviceClass.DURATION, "h"),
    "unit_rate": ("Unit rate", None, "p/kWh"),
    "standing_charge": ("Standing charge", None, "p/day"),
    "daily_cost": ("Latest available cost", SensorDeviceClass.MONETARY, "GBP"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    coordinator.account_device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.unique_id)},
            name="GlowBright / Bright account",
            manufacturer="GlowBright",
            model="Bright DCC service",
            entry_type=DeviceEntryType.SERVICE,
        )
        .id
    )
    entities = [
        GlowBrightSensor(
            coordinator,
            None,
            "last_api_update",
            "Last successful API update",
            SensorDeviceClass.TIMESTAMP,
            None,
        ),
        GlowBrightSensor(coordinator, None, "backfill", "Backfill status", None, None),
    ]
    for fuel in coordinator.selected:
        for key, (name, device_class, unit) in FUEL_SENSORS.items():
            if key == "daily_cost" and not coordinator.costs[fuel]:
                continue
            entities.append(GlowBrightSensor(coordinator, fuel, key, name, device_class, unit))
    async_add_entities(entities)


class GlowBrightSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = None

    def __init__(self, coordinator, fuel, key, name, device_class, unit):
        super().__init__(coordinator)
        self.fuel, self.key = fuel, key
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        entry = coordinator.entry
        account_key = (DOMAIN, entry.unique_id)
        identity = coordinator.selected[fuel].key if fuel else "account"
        self._attr_unique_id = f"{entry.unique_id}_{identity}_{key}"
        if fuel:
            resource = coordinator.selected[fuel]
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry.unique_id}_{fuel}_{resource.key}")},
                name=f"GlowBright {fuel.title()}",
                manufacturer="GlowBright",
                model=f"{resource.ve_name} · {resource.classifier} · {resource.base_unit}",
                serial_number=resource.resource_id,
                via_device_id=coordinator.account_device_id,
            )
            if key == "daily_usage":
                self._attr_native_unit_of_measurement = coordinator.unit_factor(fuel)[0]
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={account_key},
                name="GlowBright / Bright account",
                manufacturer="GlowBright",
                model="Bright DCC service",
                entry_type=DeviceEntryType.SERVICE,
            )

    @property
    def available(self):
        # A transient update failure does not erase last-good informational data.
        return not self.coordinator.auth_failed

    @property
    def native_value(self):
        status = self.coordinator.public_status()
        if self.key == "backfill":
            streams = [
                p
                for fuel in self.coordinator.book["fuels"].values()
                for p in fuel["streams"].values()
            ]
            if any(p.get("last_error") for p in streams):
                return "retrying"
            return (
                "complete" if streams and all(p.get("complete") for p in streams) else "in_progress"
            )
        state = status["fuels"][self.fuel] if self.fuel else status
        value = (
            state.get("tariff", {}).get(self.key)
            if self.key in ("unit_rate", "standing_charge")
            else state.get(self.key)
        )
        if self._attr_device_class == SensorDeviceClass.TIMESTAMP:
            return dt_util.parse_datetime(value) if value else None
        if self._attr_device_class == SensorDeviceClass.DATE:
            return date.fromisoformat(value) if value else None
        return value

    @property
    def extra_state_attributes(self):
        if self.key == "backfill":
            return {fuel: book["streams"] for fuel, book in self.coordinator.book["fuels"].items()}
        if self.fuel:
            resource = self.coordinator.selected[self.fuel]
            return {
                "ve_name": resource.ve_name,
                "resource_id": resource.resource_id,
                "classifier": resource.classifier,
                "base_unit": resource.base_unit,
                "historical_energy_source": False,
            }
        return None
