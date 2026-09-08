"""The phase-six gate: actual SQL statistics, never a fake Recorder."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.glowbright.models import complete_hours, local_day
from custom_components.glowbright.statistics import StatisticsImporter, metadata


@pytest.mark.usefixtures("recorder_mock")
async def test_delayed_and_revised_hours(hass):
    importer = StatisticsImporter(hass)
    meta = metadata("account", "electricity", "kWh")
    monday = datetime(2026, 9, 7, tzinfo=UTC)
    wednesday = monday + timedelta(days=2)
    await importer.rewrite(meta, {monday - timedelta(hours=1): 2, monday + timedelta(hours=1): 3})
    # A response obtained Wednesday fills Monday's originally absent hour.
    await importer.rewrite(meta, {monday: 4})
    rows = await importer.series(
        meta["statistic_id"], monday - timedelta(days=1), wednesday + timedelta(days=1)
    )
    assert [r["state"] for r in rows] == [2, 4, 3]
    assert [r["sum"] for r in rows] == [2, 6, 9]
    assert all(r["start"] < wednesday.timestamp() for r in rows)
    # Revision must carry through an existing later hour not in the response.
    await importer.rewrite(meta, {monday: 7})
    rows = await importer.series(meta["statistic_id"], monday, None)
    assert [r["state"] for r in rows] == [7, 3]
    assert [r["sum"] for r in rows] == [9, 12]
    # Null/failing response produces no mutation.
    await importer.rewrite(meta, {})
    assert rows == await importer.series(meta["statistic_id"], monday, None)


@pytest.mark.usefixtures("recorder_mock")
async def test_baseline_across_gap_and_older_backfill(hass):
    importer = StatisticsImporter(hass)
    meta = metadata("account", "electricity", "kWh")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    later = start + timedelta(days=50)
    await importer.rewrite(meta, {start: 10, later: 2, later + timedelta(hours=1): 3})
    await importer.rewrite(meta, {later: 4})
    rows = await importer.series(meta["statistic_id"], start, None)
    assert [r["sum"] for r in rows] == [10, 14, 17]
    await importer.rewrite(meta, {start - timedelta(days=10): 8})
    rows = await importer.series(meta["statistic_id"], start - timedelta(days=11), None)
    assert [r["sum"] for r in rows] == [8, 18, 22, 25]


@pytest.mark.parametrize(
    "date,hours",
    [(datetime(2026, 3, 29, 12, tzinfo=UTC), 23), (datetime(2026, 10, 25, 12, tzinfo=UTC), 25)],
)
@pytest.mark.usefixtures("recorder_mock")
async def test_dst_and_genuine_zero(hass, date, hours):
    start, end = local_day(date)
    readings = {start + timedelta(minutes=30 * i): 1.0 for i in range(hours * 2)}
    readings[start + timedelta(hours=2)] = 0
    readings[start + timedelta(hours=2, minutes=30)] = 0
    values = complete_hours(readings, "PT30M", end)
    assert len(values) == hours
    importer = StatisticsImporter(hass)
    meta = metadata("account", "gas", "m³")
    await importer.rewrite(meta, values)
    rows = await importer.series(meta["statistic_id"], start, end)
    assert len(rows) == hours
    assert rows[2]["state"] == 0
    assert rows[-1]["sum"] == (hours - 1) * 2
    assert all(b["sum"] >= a["sum"] for a, b in zip(rows, rows[1:]))


def test_incomplete_hour_does_not_replace_known_hour():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert complete_hours({start: 0}, "PT30M", start + timedelta(hours=1)) == {}


def test_modern_metadata():
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

    for unit, converter in (("kWh", EnergyConverter), ("m³", VolumeConverter)):
        meta = metadata("account", "gas", unit)
        assert meta["mean_type"] is StatisticMeanType.NONE
        assert meta["has_sum"] is True
        assert meta["unit_class"] == converter.UNIT_CLASS
        assert meta["unit_of_measurement"] == unit
        assert "has_mean" not in meta
