"""Resource identity and interval transformations, independent of HA."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


@dataclass(slots=True)
class Resource:
    """A stream belonging to one Virtual Entity; classifiers are not identities."""

    ve_id: str
    ve_name: str
    resource_id: str
    resource_name: str
    classifier: str
    base_unit: str
    active: bool = True
    first_time: datetime | None = None
    last_time: datetime | None = None

    @property
    def key(self) -> str:
        return f"{self.ve_id}/{self.resource_id}"

    @property
    def label(self) -> str:
        latest = (
            self.last_time.astimezone(LONDON).strftime("%Y-%m-%d %H:%M %Z")
            if self.last_time
            else "unknown"
        )
        return f"{self.ve_name} · {self.resource_name} · resource …{self.resource_id[-6:]} · {self.base_unit} · latest {latest}"

    def as_dict(self) -> dict:
        result = asdict(self)
        for field in ("first_time", "last_time"):
            result[field] = result[field].isoformat() if result[field] else None
        return result


def utc(value: datetime) -> datetime:
    """Reject naive input rather than depending on the host's time zone."""
    if value.tzinfo is None:
        raise ValueError("An aware datetime is required")
    return value.astimezone(UTC)


def hour(value: datetime) -> datetime:
    return utc(value).replace(minute=0, second=0, microsecond=0)


def local_day(value: datetime) -> tuple[datetime, datetime]:
    start = value.astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    return utc(start), utc(start + timedelta(days=1))


def complete_hours(
    readings: dict[datetime, float], period: str, end: datetime
) -> dict[datetime, float]:
    """Only complete UTC hours can replace existing known hourly states."""
    buckets: dict[datetime, dict[datetime, float]] = {}
    for stamp, value in readings.items():
        stamp = utc(stamp)
        if not isfinite(value) or value < 0 or stamp.second or stamp.microsecond:
            continue
        if stamp.minute not in ((0, 30) if period == "PT30M" else (0,)):
            continue
        buckets.setdefault(hour(stamp), {})[stamp] = value
    count = 2 if period == "PT30M" else 1
    return {
        start: sum(values.values())
        for start, values in buckets.items()
        if len(values) == count and start + timedelta(hours=1) <= utc(end)
    }


def cost_candidates(resources: list[Resource], consumption: Resource) -> list[Resource]:
    return [
        r
        for r in resources
        if r.active
        and r.ve_id == consumption.ve_id
        and r.classifier == f"{consumption.classifier}.cost"
    ]
