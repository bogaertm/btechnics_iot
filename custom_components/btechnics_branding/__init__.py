"""Btechnics IOT - Custom Home Assistant Integration."""
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

DEFAULT_LOGIN_TEXT = "Btechnics IOT"
DEFAULT_SIDEBAR_TEXT = "Btechnics IOT"


class BtechnicsBrandingConfigView(HomeAssistantView):
    """API endpoint die de branding instellingen teruggeeft als JSON."""

    url = _API_URL
    name = "api:btechnics_branding:config"
    requires_auth = False

    def __init__(self, hass):
        """Init."""
        self.hass = hass

    async def get(self, request):
        """Geef de huidige instellingen terug."""
        config = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            config = entry.options
            break

        return self.json({
            "login_text": config.get("login_text", DEFAULT_LOGIN_TEXT),
            "sidebar_text": config.get("sidebar_text", DEFAULT_SIDEBAR_TEXT),
        })


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registreer het JS-bestand en de API view."""
    # Statisch pad registreren
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
        _LOGGER.info("Btechnics IOT: statisch pad geregistreerd")
    except Exception as err:
        _LOGGER.warning("Btechnics IOT static path: %s", err)

    # API view registreren
    hass.http.register_view(BtechnicsBrandingConfigView(hass))
    _LOGGER.info("Btechnics IOT: config API geregistreerd op %s", _API_URL)

    # JS toevoegen aan frontend
    try:
        frontend.add_extra_js_url(hass, _JS_URL)
        _LOGGER.info("Btechnics IOT: JS module geladen")
    except Exception as err:
        _LOGGER.error("Btechnics IOT add_extra_js_url: %s", err)

    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Config entry setup."""
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    """Herlaad wanneer opties wijzigen."""
    _LOGGER.info("Btechnics IOT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Config entry verwijderen."""
    return True
