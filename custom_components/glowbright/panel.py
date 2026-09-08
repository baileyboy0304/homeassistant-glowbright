"""Register one bundled account-aware sidebar panel."""

from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN, VERSION


async def async_update_panel(hass, excluding=None):
    enabled = any(
        entry.entry_id != excluding
        and entry.options.get("panel_enabled", True)
        and hasattr(entry, "runtime_data")
        for entry in hass.config_entries.async_entries(DOMAIN)
    )
    state = hass.data.setdefault(DOMAIN, {})
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
        )
        state["panel"] = True
    elif not enabled and state.get("panel"):
        frontend.async_remove_panel(hass, DOMAIN)
        state["panel"] = False
