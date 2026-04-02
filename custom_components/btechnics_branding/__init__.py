"""Btechnics IOT Branding."""
import logging
import pathlib

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "btechnics_branding"
_DIR = pathlib.Path(__file__).parent
_JS_FILE = str(_DIR / "btechnics-branding.js")
_JS_URL = "/btechnics_branding/btechnics-branding.js"
_API_URL = "/api/btechnics_branding/config"

# CSS die server-side wordt geinjecteerd - verbergt SVG en OHF badge voor eerste render
_HIDE_CSS = (
    "<style id='bt-hide'>"
    "#ha-launch-screen svg{display:none!important}"
    ".ohf-logo{display:none!important}"
    "</style>"
)


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
            "login_text":        config.get("login_text", "Btechnics IOT"),
            "login_text_size":   config.get("login_text_size", 24),
            "sidebar_text":      config.get("sidebar_text", "Btechnics IOT"),
            "sidebar_text_size": config.get("sidebar_text_size", 16),
        })


def _patch_app_handle(app: web.Application) -> None:
    """Wrap app._handle om CSS te injecteren voor eerste HTML render."""
    if getattr(app, "_bt_css_patched", False):
        return

    original_handle = app._handle

    async def _patched_handle(request: web.Request) -> web.StreamResponse:
        response = await original_handle(request)
        ct = getattr(response, "content_type", "") or ""
        if "text/html" not in ct:
            return response
        try:
            body = response.body
            if isinstance(body, bytes):
                text = body.decode("utf-8", errors="replace")
            else:
                return response
            # Injecteer CSS direct na <head> tag
            if "<head>" in text and "bt-hide" not in text:
                patched = text.replace("<head>", "<head>" + _HIDE_CSS, 1)
                headers = dict(response.headers)
                headers.pop("Content-Length", None)
                headers.pop("content-length", None)
                headers.pop("Content-Security-Policy", None)
                headers.pop("content-security-policy", None)
                return web.Response(
                    text=patched,
                    status=response.status,
                    content_type="text/html",
                    charset="utf-8",
                    headers=headers,
                )
        except Exception as err:
            _LOGGER.debug("CSS injectie fout: %s", err)
        return response

    app._handle = _patched_handle
    app._bt_css_patched = True
    _LOGGER.info("Btechnics IOT: CSS injectie actief")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Setup: statisch pad, API view, JS en CSS injectie."""
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    hass.http.register_view(BtechnicsBrandingConfigView(hass))

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
        _LOGGER.info("Btechnics IOT: JS module geladen")
    except Exception as err:
        _LOGGER.error("add_extra_js_url: %s", err)

    # Patch de request handler voor CSS injectie
    try:
        _patch_app_handle(hass.http.app)
    except Exception as err:
        _LOGGER.error("CSS patch fout: %s", err)

    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.info("Btechnics IOT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
