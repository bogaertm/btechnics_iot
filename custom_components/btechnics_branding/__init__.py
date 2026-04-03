"""Btechnics IOT Branding."""
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
    """Wrap app._handle: injecteer CSS in HTML en patch PWA manifest."""
    if getattr(app, "_bt_css_patched", False):
        return

    original_handle = app._handle

    async def _patched_handle(request: web.Request) -> web.StreamResponse:
        response = await original_handle(request)

        path = request.path
        ct = getattr(response, "content_type", "") or ""

        # --- PWA manifest patchen ---
        if path == "/manifest.json":
            try:
                body = None
                if hasattr(response, "_body") and response._body:
                    body = response._body
                elif hasattr(response, "body") and response.body:
                    body = response.body
                if body:
                    manifest = json.loads(body.decode("utf-8"))
                    manifest["name"] = "Btechnics IOT"
                    manifest["short_name"] = "Btechnics IOT"
                    for icon in manifest.get("icons", []):
                        icon["src"] = "https://btechnics.be/logo_btechnics/btechnics-icon.png"
                    _LOGGER.info("Btechnics IOT: manifest.json gepatcht")
                    return web.Response(
                        text=json.dumps(manifest),
                        status=200,
                        content_type="application/manifest+json",
                    )
            except Exception as err:
                _LOGGER.warning("Btechnics IOT manifest patch fout: %s", err)

        # --- CSS injecteren in HTML ---
        if "text/html" not in ct:
            return response
        try:
            text = None
            if hasattr(response, "_text") and response._text:
                text = response._text
            elif hasattr(response, "_body") and response._body:
                charset = getattr(response, "charset", "utf-8") or "utf-8"
                text = response._body.decode(charset, errors="replace")
            elif hasattr(response, "body") and response.body:
                charset = getattr(response, "charset", "utf-8") or "utf-8"
                text = response.body.decode(charset, errors="replace")

            if text and "<head>" in text and "bt-hide" not in text:
                patched = text.replace("<head>", "<head>" + _HIDE_CSS, 1)
                _LOGGER.info("Btechnics IOT: CSS geinjecteerd in HTML")
                return web.Response(
                    text=patched,
                    status=response.status,
                    content_type="text/html",
                    charset="utf-8",
                )
            else:
                _LOGGER.warning("Btechnics IOT: body=%s type=%s", text is not None, type(response).__name__)
        except Exception as err:
            _LOGGER.warning("Btechnics IOT CSS injectie fout: %s", err)

        return response

    app._handle = _patched_handle
    app._bt_css_patched = True
    _LOGGER.info("Btechnics IOT: _handle wrapper actief")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Setup vanuit configuration.yaml (kan leeg zijn)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Config entry setup - hier registreren we alles."""
    # Statisch pad voor JS
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False)
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    # API view
    hass.http.register_view(BtechnicsBrandingConfigView(hass))

    # JS module
    try:
        frontend.add_extra_js_url(hass, _JS_URL)
        _LOGGER.info("Btechnics IOT: JS geladen")
    except Exception as err:
        _LOGGER.error("add_extra_js_url: %s", err)

    # _handle patch voor CSS + manifest
    try:
        _patch_app_handle(hass.http.app)
    except Exception as err:
        _LOGGER.error("_handle patch fout: %s", err)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.info("Btechnics IOT: setup_entry volledig")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.info("Btechnics IOT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
