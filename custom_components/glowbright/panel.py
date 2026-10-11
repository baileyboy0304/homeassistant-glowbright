"""Register one bundled account-aware sidebar panel."""

from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import DEFAULT_HOME_PATH, DOMAIN, VERSION
from .navigation import home_path_or_default


async def async_update_panel(hass, excluding=None):
    enabled = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != excluding
        and entry.options.get("panel_enabled", True)
        and hasattr(entry, "runtime_data")
    ]
    state = hass.data.setdefault(DOMAIN, {})
    # The shared header has one destination, independent of the displayed meter.
    home_path = home_path_or_default(
        enabled[0].options.get("home_path", DEFAULT_HOME_PATH) if enabled else DEFAULT_HOME_PATH
    )
    if state.get("panel") and (not enabled or state.get("home_path") != home_path):
        frontend.async_remove_panel(hass, DOMAIN)
        state["panel"] = False
    if enabled and not state.get("panel"):
        bundle = Path(__file__).parent / "frontend" / "glowbright-panel.js"
        # Also invalidate browser caches for development installs of one version.
        digest = sha256(await hass.async_add_executor_job(bundle.read_bytes)).hexdigest()[:12]
        if not state.get("static"):
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/glowbright_static", str(Path(__file__).parent / "frontend"), True
                    )
                ]
            )
            state["static"] = True
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=DOMAIN,
            webcomponent_name="glowbright-panel",
            sidebar_title="GlowBright",
            sidebar_icon="mdi:flash",
            module_url=f"/glowbright_static/glowbright-panel.js?v={VERSION}-{digest}",
            require_admin=False,
            config={"home_path": home_path},
        )
        state["panel"] = True
        state["home_path"] = home_path
