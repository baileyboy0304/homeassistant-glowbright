"""Authenticated, permission-checked series over Recorder and a bounded cache."""

from datetime import UTC, datetime, timedelta

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import ApiError, AuthError
from .const import CACHE_TTL, DOMAIN
from .models import LONDON, utc
from .statistics import statistic_id


def resolve(hass, connection, entry_id, fuel=None):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        raise ValueError("Unknown or unloaded GlowBright account")
    coordinator = entry.runtime_data
    if coordinator.importer.stopping:
        raise ValueError("Account is unloading")
    if connection.user.is_admin:
        return coordinator
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry_id)
    resources = (
        [coordinator.selected[fuel].key]
        if fuel in coordinator.selected
        else [r.key for r in coordinator.selected.values()]
    )
    if not any(
        any(f"_{key}_" in entity.unique_id for key in resources)
        and connection.user.permissions.check_entity(entity.entity_id, POLICY_READ)
        for entity in entities
    ):
        raise PermissionError("No access to this meter")
    return coordinator


def bucket_start(stamp, period):
    if period == "PT1H":
        return stamp
    local = stamp.astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "P1W":
        local -= timedelta(days=local.weekday())
    elif period == "P1M":
        local = local.replace(day=1)
    return utc(local)


def aggregate(rows, period):
    buckets = {}
    for row in rows:
        stamp = datetime.fromtimestamp(row["start"], UTC)
        if row.get("state") is None:
            continue
        start = bucket_start(stamp, period)
        item = buckets.setdefault(start, {"start": start.isoformat(), "value": 0, "hours": 0})
        item["value"] += row["state"]
        item["hours"] += 1
    return [buckets[key] for key in sorted(buckets)]


async def get_series(coordinator, fuel, metric, period, start, end):
    if fuel not in coordinator.selected:
        raise ValueError("Fuel is not configured")
    if (
        end <= start
        or end - start > timedelta(days=3660)
        or start.minute
        or end.minute
        or start.second
        or end.second
        or start.microsecond
        or end.microsecond
    ):
        raise ValueError("Invalid series range")
    resource = coordinator.selected[fuel] if metric == "usage" else coordinator.costs[fuel]
    if resource is None:
        return {"rows": [], "unit": "GBP", "unavailable": True}
    unit, factor = (
        coordinator.unit_factor(fuel)
        if metric == "usage"
        else ("GBP", coordinator.cost_factor(resource))
    )
    cached = False
    if period == "PT30M":
        if end - start > timedelta(hours=25):
            raise ValueError("Half-hour view is limited to one local day")
        key = (resource.key, start, end, factor)
        async with coordinator._cache_lock:
            now = dt_util.utcnow()
            cache = coordinator._cache.get(key)
            if cache and now - cache[0] < CACHE_TTL:
                values = cache[1]
                cached = True
            else:
                try:
                    values = await coordinator.client.readings(
                        resource.resource_id, start, end, period, resource.last_time
                    )
                    coordinator._cache[key] = (now, values)
                    while len(coordinator._cache) > 32:
                        coordinator._cache.pop(next(iter(coordinator._cache)))
                except AuthError:
                    raise
                except ApiError:
                    if cache is None:
                        raise
                    values = cache[1]
                    cached = True
            rows = [
                {"start": stamp.isoformat(), "value": value * factor, "hours": 0.5}
                for stamp, value in sorted(values.items())
            ]
    else:
        rows = aggregate(
            await coordinator.importer.series(
                statistic_id(
                    coordinator.entry.entry_id, fuel, "consumption" if metric == "usage" else "cost"
                ),
                start,
                end,
            ),
            period,
        )
    return {
        "rows": rows,
        "unit": unit,
        "cached": cached,
        "total": sum(row["value"] for row in rows),
        "coverage_hours": sum(row["hours"] for row in rows),
        "requested_hours": (end - start).total_seconds() / 3600,
    }


@websocket_api.websocket_command(
    {vol.Required("type"): "glowbright/get_status", vol.Optional("entry_id"): str}
)
@websocket_api.async_response
async def ws_status(hass, connection, msg):
    try:
        entries = (
            [msg["entry_id"]]
            if "entry_id" in msg
            else [e.entry_id for e in hass.config_entries.async_entries(DOMAIN)]
        )
        accounts = []
        for entry_id in entries:
            try:
                coordinator = resolve(hass, connection, entry_id)
                status = coordinator.public_status()
                status["fuels"] = {
                    fuel: state
                    for fuel, state in status["fuels"].items()
                    if _can_read(hass, connection, entry_id, fuel)
                }
                accounts.append(status)
            except ValueError, PermissionError:
                if "entry_id" in msg:
                    raise
        connection.send_result(msg["id"], {"accounts": accounts})
    except (ValueError, PermissionError) as err:
        connection.send_error(msg["id"], "not_found", str(err))


def _can_read(hass, connection, entry_id, fuel):
    try:
        resolve(hass, connection, entry_id, fuel)
        return True
    except ValueError, PermissionError:
        return False


@websocket_api.websocket_command(
    {
        vol.Required("type"): "glowbright/get_series",
        vol.Required("entry_id"): str,
        vol.Required("fuel"): vol.In(("electricity", "gas")),
        vol.Required("metric"): vol.In(("usage", "cost")),
        vol.Required("period"): vol.In(("PT30M", "PT1H", "P1D", "P1W", "P1M")),
        vol.Required("start"): str,
        vol.Required("end"): str,
    }
)
@websocket_api.async_response
async def ws_series(hass, connection, msg):
    try:
        coordinator = resolve(hass, connection, msg["entry_id"], msg["fuel"])
        start, end = dt_util.parse_datetime(msg["start"]), dt_util.parse_datetime(msg["end"])
        if start is None or end is None:
            raise ValueError("Invalid timestamps")
        result = await get_series(
            coordinator, msg["fuel"], msg["metric"], msg["period"], utc(start), utc(end)
        )
        connection.send_result(msg["id"], result)
    except (ValueError, PermissionError, ApiError) as err:
        connection.send_error(msg["id"], "series_unavailable", str(err))


@callback
def async_register_commands(hass):
    websocket_api.async_register_command(hass, ws_status)
    websocket_api.async_register_command(hass, ws_series)
