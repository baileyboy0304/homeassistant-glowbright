"""GlowBright: delayed utility intervals at their original consumption time."""

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import GlowmarktClient
from .const import DOMAIN
from .coordinator import GlowBrightCoordinator
from .statistics import StatisticsImporter

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass, config):
    from .websocket import async_register_commands

    async_register_commands(hass)
    return True


async def async_setup_entry(hass, entry):
    from .panel import async_update_panel

    client = GlowmarktClient(
        async_get_clientsession(hass),
        entry.data["username"],
        entry.data["password"],
        entry.unique_id,
    )
    coordinator = GlowBrightCoordinator(hass, entry, client)
    await coordinator.initialize()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    async def stopping(event):
        await coordinator.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopping))
    await async_update_panel(hass)
    coordinator.start()
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    from .panel import async_update_panel

    await entry.runtime_data.stop()
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await async_update_panel(hass, excluding=entry.entry_id)
    return unloaded


async def async_remove_entry(hass, entry):
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    book = await store.async_load()
    if book and not hass.is_stopping:
        await StatisticsImporter(hass).clear_owned(entry.entry_id, book.get("owned_ids", []))
    await store.async_remove()


async def async_migrate_entry(hass, entry):
    """Refuse future schemas; v1 has no predecessor or implicit meter migration."""
    return entry.version == 1
