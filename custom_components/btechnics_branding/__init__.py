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
    if getattr(app, "_bt_css_patched", False):
        return

    original_handle = app._handle

    async def _patched_handle(request: web.Request) -> web.StreamResponse:
        response = await original_handle(request)
        path = request.path

        # Log elke HTML of manifest request
        ct = getattr(response, "content_type", "") or ""
        resp_type = type(response).__name__

        if path in ("/", "/manifest.json") or "text/html" in ct:
            _LOGGER.warning(
                "BT intercept: path=%s ct='%s' type=%s body=%s text=%s fpath=%s",
                path, ct, resp_type,
                hasattr(response, "_body") and response._body is not None,
                hasattr(response, "_text") and response._text is not None,
                getattr(response, "_path", None),
            )

        # --- PWA manifest patchen ---
        if path == "/manifest.json":
            try:
                raw = None
                if hasattr(response, "_body") and response._body:
                    raw = response._body
                elif hasattr(response, "body") and response.body:
                    raw = response.body
                elif hasattr(response, "_path") and response._path:
                    raw = pathlib.Path(str(response._path)).read_bytes()
                if raw:
                    manifest = json.loads(raw.decode("utf-8"))
                    manifest["name"] = "Btechnics IOT"
                    manifest["short_name"] = "Btechnics IOT"
                    for icon in manifest.get("icons", []):
                        icon["src"] = "https://btechnics.be/logo_btechnics/btechnics-icon.png"
                    _LOGGER.warning("BT: manifest gepatcht")
                    return web.Response(
                        text=json.dumps(manifest), status=200,
                        content_type="application/manifest+json",
                    )
            except Exception as err:
                _LOGGER.warning("BT manifest fout: %s", err)

        # --- CSS injecteren in HTML ---
        if "text/html" not in ct:
            return response
        try:
            text = None
            if hasattr(response, "_path") and response._path:
                text = pathlib.Path(str(response._path)).read_text(encoding="utf-8")
                _LOGGER.warning("BT: FileResponse gelezen van %s", response._path)
            if text is None and hasattr(response, "_text") and response._text:
                text = response._text
            if text is None and hasattr(response, "_body") and response._body:
                text = response._body.decode(getattr(response, "charset", "utf-8") or "utf-8", errors="replace")
            if text is None and hasattr(response, "body") and response.body:
                text = response.body.decode(getattr(response, "charset", "utf-8") or "utf-8", errors="replace")

            if text and "<head>" in text and "bt-hide" not in text:
                patched = text.replace("<head>", "<head>" + _HIDE_CSS, 1)
                _LOGGER.warning("BT: CSS geinjecteerd (type=%s)", resp_type)
                return web.Response(
                    text=patched, status=response.status,
                    content_type="text/html", charset="utf-8",
                )
            else:
                _LOGGER.warning("BT: CSS niet geinjecteerd - text=%s, head=%s",
                    text is not None, text and "<head>" in text if text else False)
        except Exception as err:
            _LOGGER.warning("BT CSS fout: %s", err)
        return response

    app._handle = _patched_handle
    app._bt_css_patched = True
    _LOGGER.warning("BT: _handle wrapper ACTIEF")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    _LOGGER.warning("BT: setup_entry start")
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
    try:
        _patch_app_handle(hass.http.app)
    except Exception as err:
        _LOGGER.warning("_handle patch fout: %s", err)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: setup_entry volledig")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.warning("BT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
