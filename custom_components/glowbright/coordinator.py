"""Background history import and last-good account state."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import ApiError, AuthError
from .const import (
    BACKFILL_CHUNK_DAYS,
    CATCHUP_INTERVAL,
    DEFAULT_OPTIONS,
    DOMAIN,
    FUELS,
    POLL_INTERVAL,
)
from .models import LONDON, complete_hours, cost_candidates, hour, local_day
from .statistics import StatisticsImporter, metadata, statistic_id

LOGGER = logging.getLogger(__name__)


class GlowBrightCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass, LOGGER, name=DOMAIN, config_entry=entry, update_interval=POLL_INTERVAL
        )
        self.entry = entry
        self.client = client
        self.options = {**DEFAULT_OPTIONS, **entry.options}
        self.importer = StatisticsImporter(hass)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.book = {"fuels": {}, "owned_ids": []}
        self.resources = []
        self.selected = {}
        self.costs = {}
        self.status = {"last_api_update": None, "api_error": None, "fuels": {}}
        self.auth_failed = False
        self._work_lock = asyncio.Lock()
        self._task = None
        self._cache = {}
        self._cache_lock = asyncio.Lock()

    async def initialize(self):
        self.book = await self.store.async_load() or self.book
        try:
            self.resources = await self.client.discover()
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ApiError as err:
            raise ConfigEntryNotReady(str(err)) from err
        for fuel in FUELS:
            resource = next((r for r in self.resources if r.key == self.options.get(fuel)), None)
            if self.options.get(fuel) not in (None, "none") and resource is None:
                raise ConfigEntryNotReady(
                    f"Selected {fuel} resource is unavailable; reconfigure to choose another"
                )
            old = self.book["fuels"].get(fuel, {})
            if resource is None:
                if old:
                    await self.importer.clear_owned(
                        self.entry.entry_id,
                        [
                            statistic_id(self.entry.entry_id, fuel, m)
                            for m in ("consumption", "cost")
                        ],
                    )
                    self.book["fuels"].pop(fuel)
                continue
            if resource.classifier != f"{fuel}.consumption":
                raise ConfigEntryNotReady("Selected resource has an incompatible classifier")
            self.selected[fuel] = resource
            candidates = cost_candidates(self.resources, resource)
            cost = next((r for r in candidates if r.key == self.options.get(f"{fuel}_cost")), None)
            self.costs[fuel] = cost
            unit, factor = self.unit_factor(fuel)
            identity = [resource.key, resource.base_unit, unit, factor, cost.key if cost else None]
            if old.get("identity") != identity:
                # Clear before checkpointing new identity. A crash can repeat
                # this harmlessly; it cannot append a different meter's values.
                await self.importer.clear_owned(
                    self.entry.entry_id,
                    [statistic_id(self.entry.entry_id, fuel, m) for m in ("consumption", "cost")],
                )
                old = {"identity": identity, "resource_id": resource.resource_id, "streams": {}}
                self.book["fuels"][fuel] = old
            for metric in ("consumption", "cost"):
                stat_id = statistic_id(self.entry.entry_id, fuel, metric)
                if stat_id not in self.book["owned_ids"]:
                    self.book["owned_ids"].append(stat_id)
            self.status["fuels"][fuel] = {
                "resource": resource.as_dict(),
                "latest_reading": resource.last_time.isoformat() if resource.last_time else None,
                "unit": unit,
                "estimated_conversion": factor != 1,
                "tariff": old.get("tariff", {}),
                "cost_available": cost is not None,
                "statistics": {
                    m: statistic_id(self.entry.entry_id, fuel, m) for m in ("consumption", "cost")
                },
            }
        await self.store.async_save(self.book)
        self.async_set_updated_data(self.status)

    def unit_factor(self, fuel):
        resource = self.selected[fuel]
        unit = resource.base_unit
        if unit in ("m3", "m^3", "m³"):
            if self.options["gas_conversion"] and fuel == "gas":
                calorific = self.options.get("calorific_value")
                if not calorific or calorific <= 0:
                    raise ConfigEntryNotReady("Gas conversion requires a calorific value")
                return "kWh", self.options["volume_correction"] * calorific / 3.6
            return "m³", 1
        if unit == "kWh":
            return unit, 1
        raise ConfigEntryNotReady(f"Unsupported consumption unit: {unit}")

    def start(self):
        self._task = self.entry.async_create_background_task(
            self.hass, self._background(), "GlowBright initial import"
        )

    async def _background(self):
        try:
            await self.async_refresh()
        except asyncio.CancelledError:
            raise

    async def _async_update_data(self):
        async with self._work_lock:
            self.importer.check_running()
            try:
                await self._recent()
                await self._backfill()
            except AuthError as err:
                self.auth_failed = True
                raise ConfigEntryAuthFailed(str(err)) from err
            self.auth_failed = False
            return self.status

    async def _recent(self):
        now = dt_util.utcnow()
        end = hour(now)
        start = end - timedelta(days=self.options["refresh_days"])
        errors = []
        for fuel, resource in self.selected.items():
            state = self.status["fuels"][fuel]
            book = self.book["fuels"][fuel]
            last_catchup = dt_util.parse_datetime(book.get("catchup_attempt", ""))
            if not last_catchup or now - last_catchup >= CATCHUP_INTERVAL:
                book["catchup_attempt"] = now.isoformat()
                try:
                    await self.client.catchup(resource.resource_id)
                    book["catchup_status"] = "requested"
                except AuthError:
                    raise
                except ApiError:
                    book["catchup_status"] = "temporarily unavailable"
            try:
                resource.last_time = await self.client.boundary(resource.resource_id)
                if resource.last_time:
                    state["latest_reading"] = resource.last_time.isoformat()
                unit, factor = self.unit_factor(fuel)
                await self._import_window(
                    fuel, "consumption", resource, start, end, "PT30M", unit, factor
                )
                state["last_api_update"] = now.isoformat()
                self.status["last_api_update"] = now.isoformat()
            except AuthError:
                raise
            except ApiError as err:
                errors.append(str(err))
            try:
                state["tariff"] = await self.client.tariff(resource.resource_id)
                book["tariff"] = state["tariff"]
                state["tariff_error"] = False
            except AuthError:
                raise
            except ApiError:
                state["tariff_error"] = True
            cost = self.costs[fuel]
            if cost:
                try:
                    cost.last_time = await self.client.boundary(cost.resource_id)
                    await self._import_window(
                        fuel, "cost", cost, start, end, "PT30M", "GBP", self.cost_factor(cost)
                    )
                except AuthError:
                    raise
                except (ApiError, ValueError) as err:
                    errors.append(str(err))
            await self._daily_summary(fuel)
        self.status["api_error"] = "; ".join(sorted(set(errors))) or None
        await self.store.async_save(self.book)
        self.async_set_updated_data(self.status)

    @staticmethod
    def cost_factor(resource):
        if resource.base_unit.lower() in ("p", "pence", "gbpence", "gbp pence"):
            return 0.01
        if resource.base_unit in ("GBP", "£"):
            return 1
        raise ValueError("Historical cost resource has unsupported units")

    async def _import_window(self, fuel, metric, resource, start, end, period, unit, factor):
        values = await self.client.readings(
            resource.resource_id, start, end, period, resource.last_time
        )
        values = {
            stamp: value * factor for stamp, value in complete_hours(values, period, end).items()
        }
        await self.importer.rewrite(metadata(self.entry.entry_id, fuel, unit, metric), values)
        progress = self.book["fuels"][fuel]["streams"].setdefault(metric, {})
        progress["resource_id"] = resource.resource_id
        if values:
            earliest = min(values).isoformat()
            latest = max(values).isoformat()
            progress["earliest_imported"] = min(
                progress.get("earliest_imported", earliest), earliest
            )
            progress["latest_imported"] = max(progress.get("latest_imported", latest), latest)
        return values

    async def _backfill(self):
        now = hour(dt_util.utcnow())
        recent_start = now - timedelta(days=self.options["refresh_days"])
        for fuel, consumption in self.selected.items():
            unit, factor = self.unit_factor(fuel)
            streams = [("consumption", consumption, unit, factor)]
            if cost := self.costs[fuel]:
                try:
                    streams.append(("cost", cost, "GBP", self.cost_factor(cost)))
                except ValueError:
                    pass
            for metric, resource, unit, factor in streams:
                progress = self.book["fuels"][fuel]["streams"].setdefault(metric, {})
                try:
                    if resource.first_time is None:
                        resource.first_time = await self.client.boundary(resource.resource_id, True)
                    if resource.first_time is None:
                        progress["complete"] = False
                        progress["last_error"] = "No first-time available; retrying later"
                        await self.store.async_save(self.book)
                        continue
                    target = max(
                        hour(resource.first_time),
                        now - timedelta(days=self.options["backfill_days"]),
                    )
                    stored_target = dt_util.parse_datetime(progress.get("target", ""))
                    if stored_target is None or target < stored_target:
                        progress.update(
                            target=target.isoformat(), cursor=target.isoformat(), complete=False
                        )
                    cursor = dt_util.parse_datetime(progress.get("cursor", "")) or target
                    if resource.last_time is None:
                        resource.last_time = await self.client.boundary(resource.resource_id)
                    if resource.last_time is None:
                        progress.update(
                            complete=False, last_error="No last-time available; retrying later"
                        )
                        await self.store.async_save(self.book)
                        continue
                    historical_end = min(
                        recent_start, hour(resource.last_time + timedelta(minutes=30))
                    )
                    # Retry gaps after an outage longer than the rolling window.
                    while cursor < historical_end:
                        self.importer.check_running()
                        stop = min(cursor + timedelta(days=BACKFILL_CHUNK_DAYS), historical_end)
                        progress["last_attempted_chunk"] = [cursor.isoformat(), stop.isoformat()]
                        progress["complete"] = False
                        await self.store.async_save(self.book)
                        await self._import_window(
                            fuel, metric, resource, cursor, stop, "PT1H", unit, factor
                        )
                        cursor = stop
                        progress.update(cursor=cursor.isoformat(), last_error=None)
                        await self.store.async_save(self.book)
                        self.async_set_updated_data(self.status)
                        await asyncio.sleep(0.25)
                    progress["complete"] = True
                except AuthError:
                    raise
                except ApiError as err:
                    progress.update(complete=False, last_error=str(err))
                await self.store.async_save(self.book)

    async def _daily_summary(self, fuel):
        state = self.status["fuels"][fuel]
        latest = dt_util.parse_datetime(state.get("latest_reading") or "")
        if not latest:
            return
        start, end = local_day(latest)
        for metric, field in (("consumption", "daily_usage"), ("cost", "daily_cost")):
            rows = await self.importer.series(
                statistic_id(self.entry.entry_id, fuel, metric), start, end
            )
            if rows:
                state[field] = sum(r["state"] for r in rows if r["state"] is not None)
        state["data_date"] = start.astimezone(LONDON).date().isoformat()

    async def stop(self):
        self.importer.stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.async_shutdown()
        await self.importer.stop()

    def public_status(self):
        """Explicit allowlist: never serialize a client or ConfigEntry.data."""
        now = dt_util.utcnow()
        fuels = {}
        for fuel, state in self.status["fuels"].items():
            latest = dt_util.parse_datetime(state.get("latest_reading") or "")
            fuels[fuel] = {
                **state,
                "data_age_hours": (now - latest).total_seconds() / 3600 if latest else None,
                "backfill": self.book["fuels"][fuel]["streams"],
            }
        return {
            "entry_id": self.entry.entry_id,
            "title": self.entry.title,
            "last_api_update": self.status["last_api_update"],
            "api_error": self.status["api_error"],
            "auth_failed": self.auth_failed,
            "fuels": fuels,
        }
