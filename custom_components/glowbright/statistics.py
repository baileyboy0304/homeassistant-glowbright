"""Serialized, cancellable Recorder imports of mutable hourly interval data."""

import asyncio
from datetime import UTC, datetime, timedelta
from math import isfinite

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import DOMAIN
from .models import hour

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def statistic_id(entry_id: str, fuel: str, metric: str = "consumption") -> str:
    return f"{DOMAIN}:{entry_id.lower()}_{fuel}_{metric}"


def metadata(entry_id: str, fuel: str, unit: str, metric: str = "consumption") -> StatisticMetaData:
    """Current Recorder metadata, with native volume support."""
    if metric == "cost" and unit == "GBP":
        unit_class = None
    elif unit == "kWh":
        unit_class, unit = EnergyConverter.UNIT_CLASS, UnitOfEnergy.KILO_WATT_HOUR
    elif unit in ("m³", "m3", "m^3"):
        unit_class, unit = VolumeConverter.UNIT_CLASS, UnitOfVolume.CUBIC_METERS
    else:
        raise ValueError(f"Unsupported consumption unit: {unit}")
    return StatisticMetaData(
        statistic_id=statistic_id(entry_id, fuel, metric),
        source=DOMAIN,
        name=f"GlowBright {fuel} {metric}",
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


class StatisticsImporter:
    """All readers and writers share a lock and drain cancellation safely."""

    def __init__(self, hass):
        self.hass = hass
        self.lock = asyncio.Lock()
        self.stopping = False

    def check_running(self):
        if self.stopping or self.hass.is_stopping:
            raise asyncio.CancelledError

    async def _executor(self, target, *args):
        self.check_running()
        pending = get_instance(self.hass).async_add_executor_job(target, *args)
        # Cancelling the awaiting task cannot kill a synchronous SQL query.
        # Drain the shielded future before allowing shutdown to continue.
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await pending
            raise

    async def _query(self, stat_id, start, end, types):
        result = await self._executor(
            statistics_during_period, self.hass, start, end, {stat_id}, "hour", None, types
        )
        return [
            row
            for row in result.get(stat_id, [])
            if start.timestamp() <= row["start"] and (end is None or row["start"] < end.timestamp())
        ]

    async def _baseline(self, stat_id, start):
        width = timedelta(days=7)
        while start > EPOCH:
            lower = max(EPOCH, start - width)
            rows = await self._query(stat_id, lower, start, {"sum"})
            if rows:
                return float(rows[-1]["sum"] or 0)
            if lower == EPOCH:
                break
            width *= 4
        return 0.0

    async def _flush(self):
        self.check_running()
        await self._executor(get_instance(self.hass).block_till_done)

    async def rewrite(self, meta: StatisticMetaData, incoming: dict[datetime, float]) -> int:
        """Merge complete known hours and recompute the entire affected tail."""
        if not incoming:
            return 0
        if any(
            hour(stamp) != stamp or not isfinite(value) or value < 0
            for stamp, value in incoming.items()
        ):
            raise ValueError("Statistics require aligned, finite nonnegative hourly values")
        async with self.lock:
            self.check_running()
            stat_id = meta["statistic_id"]
            start = min(incoming)
            baseline = await self._baseline(stat_id, start)
            existing = await self._query(stat_id, start, None, {"state", "sum"})
            states = {
                datetime.fromtimestamp(row["start"], UTC): float(row["state"])
                for row in existing
                if row.get("state") is not None
            }
            states.update(incoming)
            rows = []
            for stamp, state in sorted(states.items()):
                baseline += state
                rows.append(StatisticData(start=stamp, state=state, sum=baseline))
            self.check_running()
            async_add_external_statistics(self.hass, meta, rows)
            await self._flush()
            return len(rows)

    async def series(self, stat_id, start, end):
        async with self.lock:
            return await self._query(stat_id, start, end, {"state", "sum"})

    async def clear_owned(self, entry_id, ids):
        prefix = f"{DOMAIN}:{entry_id.lower()}_"
        if any(not item.startswith(prefix) for item in ids):
            raise ValueError("Refusing to clear statistics outside this entry")
        async with self.lock:
            self.check_running()
            get_instance(self.hass).async_clear_statistics(list(ids))
            await self._flush()

    async def stop(self):
        self.stopping = True
        async with self.lock:
            pass
