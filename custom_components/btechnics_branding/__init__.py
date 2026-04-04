"""Btechnics IOT Branding v1.20.0."""
import json
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

_HIDE_CSS = (
    "<style id='bt-hide'>"
    "#ha-launch-screen svg{display:none!important}"
    ".ohf-logo{display:none!important}"
    "</style>"
)

_AUTH_JS = """<script src="/btechnics_branding/btechnics-branding.js" type="module"></script>"""


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


def _read_text(response):
    """Lees tekst uit response - alle mogelijke response types."""
    if hasattr(response, "_path") and response._path:
        try:
            return pathlib.Path(str(response._path)).read_text("utf-8")
        except Exception as e:
            _LOGGER.warning("BT _path leesfout: %s", e)
    for attr in ("_text", "_body", "body"):
        val = getattr(response, attr, None)
        if val:
            if isinstance(val, bytes):
                return val.decode(getattr(response, "charset", "utf-8") or "utf-8", errors="replace")
            return val
    return None


def _patch_html_response(response, path):
    """Patch een HTML response met onze CSS/JS. Geeft nieuwe Response of None."""
    ct = getattr(response, "content_type", "") or ""
    if "text/html" not in ct:
        return None
    text = _read_text(response)
    if not text:
        _LOGGER.warning("BT: geen tekst voor %s (type=%s, ct=%s)", path, type(response).__name__, ct)
        return None
    if "bt-hide" in text:
        return None  # al gepatcht
    is_auth = "authorize" in path or "/auth/" in path
    inject = _HIDE_CSS + (_AUTH_JS if is_auth else "")
    patched = text.replace("<head>", "<head>" + inject, 1)
    if patched == text:
        return None
    _LOGGER.warning("BT: HTML gepatcht voor %s (auth=%s)", path, is_auth)
    return web.Response(text=patched, status=response.status,
                        content_type="text/html", charset="utf-8")


def _patch_app(app: web.Application, label: str = "") -> None:
    """Patch alle routes in een aiohttp app + manifest + _handle."""

    # 1. Wrap _handle om ALLE requests te onderscheppen (ook subapp/auth)
    if not getattr(app, "_bt_handle_patched", False):
        orig_handle = app._handle

        async def _bt_handle(request: web.Request) -> web.StreamResponse:
            response = await orig_handle(request)
            path = request.path

            # Manifest
            if path == "/manifest.json":
                try:
                    raw = getattr(response, "_body", None) or getattr(response, "body", None)
                    if raw:
                        m = json.loads(raw.decode("utf-8"))
                        m["name"] = "Btechnics IOT"
                        m["short_name"] = "Btechnics IOT"
                        for icon in m.get("icons", []):
                            icon["src"] = "https://btechnics.be/logo_btechnics/btechnics-icon.png"
                        return web.Response(text=json.dumps(m), status=200,
                                            content_type="application/manifest+json")
                except Exception as e:
                    _LOGGER.warning("BT manifest fout: %s", e)
                return response

            # HTML patch
            patched = _patch_html_response(response, path)
            return patched if patched is not None else response

        app._handle = _bt_handle
        app._bt_handle_patched = True
        _LOGGER.warning("BT: _handle gepatcht voor app %s", label)

    # 2. Patch ook alle subapps recursief
    for resource in app.router.resources():
        if hasattr(resource, '_app'):
            subapp = resource._app
            sublabel = label + "/" + (getattr(resource, 'canonical', '') or '?')
            _LOGGER.warning("BT: subapp gevonden: %s", sublabel)
            _patch_app(subapp, sublabel)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    hass.http.register_view(BtechnicsBrandingConfigView(hass))

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
    except Exception as err:
        _LOGGER.warning("add_extra_js_url: %s", err)

    _patch_app(hass.http.app, "main")

    async def _delayed(_now=None):
        _patch_app(hass.http.app, "main-delayed")

    hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: v1.20.0 klaar")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    pass


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
