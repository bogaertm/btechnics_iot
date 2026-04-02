"""Btechnics IOT Branding."""
import logging
import pathlib

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "btechnics_branding"
_DIR = pathlib.Path(__file__).parent
_JS_FILE = str(_DIR / "btechnics-branding.js")
_JS_URL = "/btechnics_branding/btechnics-branding.js"
_API_URL = "/api/btechnics_branding/config"


class BtechnicsBrandingConfigView(HomeAssistantView):
    url = _API_URL
    name = "api:btechnics_branding:config"
    requires_auth = False

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        config = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            config = entry.options
            break
        return self.json({
            "login_text":      config.get("login_text", "Btechnics IOT"),
            "login_text_size": config.get("login_text_size", 24),
            "sidebar_text":    config.get("sidebar_text", "Btechnics IOT"),
            "sidebar_text_size": config.get("sidebar_text_size", 16),
        })


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)
    hass.http.register_view(BtechnicsBrandingConfigView(hass))
    try:
        frontend.add_extra_js_url(hass, _JS_URL)
        _LOGGER.info("Btechnics IOT: geladen")
    except Exception as err:
        _LOGGER.error("add_extra_js_url: %s", err)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.info("Btechnics IOT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
