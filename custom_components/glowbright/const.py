"""GlowBright constants."""

from datetime import timedelta

DOMAIN = "glowbright"
VERSION = "0.1.0rc1"
API_URL = "https://api.glowmarkt.com/api/v0-1"
BRIGHT_APPLICATION_ID = "b0f1b774-a586-4f72-9edd-27ead8aa7a8d"
PT30M_MAX_DAYS = 10
PT1H_MAX_DAYS = 31
BACKFILL_CHUNK_DAYS = 30
DEFAULT_BACKFILL_DAYS = 365
DEFAULT_REFRESH_DAYS = 7
POLL_INTERVAL = timedelta(hours=1)
CATCHUP_INTERVAL = timedelta(hours=2)
CACHE_TTL = timedelta(minutes=10)
FUELS = ("electricity", "gas")
NONE = "none"
DEFAULT_OPTIONS = {
    "backfill_days": DEFAULT_BACKFILL_DAYS,
    "refresh_days": DEFAULT_REFRESH_DAYS,
    "panel_enabled": True,
    "gas_conversion": False,
    "volume_correction": 1.02264,
}
