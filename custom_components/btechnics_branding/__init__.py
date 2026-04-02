"""Btechnics IOT - Custom Home Assistant Integration."""
import logging
import pathlib

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOMAIN = "btechnics_branding"
_DIR = pathlib.Path(__file__).parent
_JS_FILE = str(_DIR / "btechnics-branding.js")
_JS_URL = "/btechnics_branding/btechnics-branding.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registreer het JS-bestand als statische resource."""
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
        _LOGGER.info("Btechnics IOT: statisch pad geregistreerd")
    except Exception as err:
        _LOGGER.warning("Btechnics IOT static path: %s", err)

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
        _LOGGER.info("Btechnics IOT: JS module geladen")
    except Exception as err:
        _LOGGER.error("Btechnics IOT add_extra_js_url: %s", err)

    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Config entry setup."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Config entry verwijderen."""
    return True
