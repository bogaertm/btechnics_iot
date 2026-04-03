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

# Routes die we NOOIT patchen (geen HTML)
_SKIP_PREFIXES = (
    '/api/', '/auth/', '/static/', '/frontend_latest/', '/frontend_es5/',
    '/local/', '/hacsfiles/', '/_debugger', '/service_worker',
    '/btechnics_branding/',
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


def _make_html_handler(original):
    async def html_handler(request):
        response = await original(request)
        ct = getattr(response, "content_type", "") or ""
        if "text/html" not in ct:
            return response
        try:
            text = None
            if hasattr(response, "_path") and response._path:
                text = pathlib.Path(str(response._path)).read_text("utf-8")
            if text is None and hasattr(response, "_text") and response._text:
                text = response._text
            if text is None and hasattr(response, "_body") and response._body:
                text = response._body.decode("utf-8", errors="replace")
            if text and "<head>" in text and "bt-hide" not in text:
                patched = text.replace("<head>", "<head>" + _HIDE_CSS, 1)
                _LOGGER.warning("BT: CSS geinjecteerd voor %s", request.path)
                return web.Response(
                    text=patched, status=response.status,
                    content_type="text/html", charset="utf-8",
                )
            else:
                _LOGGER.warning("BT: HTML niet gepatcht ct=%s text=%s path=%s",
                    ct, text is not None, request.path)
        except Exception as err:
            _LOGGER.warning("BT HTML fout: %s", err)
        return response
    return html_handler


def _make_manifest_handler(original):
    async def manifest_handler(request):
        response = await original(request)
        try:
            raw = None
            if hasattr(response, "_body") and response._body:
                raw = response._body
            elif hasattr(response, "body") and response.body:
                raw = response.body
            if raw:
                m = json.loads(raw.decode("utf-8"))
                m["name"] = "Btechnics IOT"
                m["short_name"] = "Btechnics IOT"
                for icon in m.get("icons", []):
                    icon["src"] = "https://btechnics.be/logo_btechnics/btechnics-icon.png"
                _LOGGER.warning("BT: manifest gepatcht")
                return web.Response(
                    text=json.dumps(m), status=200,
                    content_type="application/manifest+json",
                )
        except Exception as err:
            _LOGGER.warning("BT manifest fout: %s", err)
        return response
    return manifest_handler


def _patch_routes(app: web.Application) -> None:
    patched = []
    skipped = []

    for resource in app.router.resources():
        canonical = getattr(resource, 'canonical', '') or ''

        # Skip bekende niet-HTML prefixes
        if any(canonical.startswith(p) for p in _SKIP_PREFIXES):
            skipped.append(canonical)
            continue

        for route in resource:
            if route.method not in ('GET', '*', 'HEAD'):
                continue
            try:
                if canonical == '/manifest.json':
                    route._handler = _make_manifest_handler(route._handler)
                    patched.append(f"MANIFEST:{canonical}")
                else:
                    # Alle andere routes: HTML handler (checkt intern op content-type)
                    route._handler = _make_html_handler(route._handler)
                    patched.append(f"HTML:{canonical}")
            except Exception as e:
                _LOGGER.warning("BT patch fout %s: %s", canonical, e)

    _LOGGER.warning("BT: gepatcht (%d): %s", len(patched), patched)


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
        _patch_routes(hass.http.app)
    except Exception as err:
        _LOGGER.warning("route patch fout: %s", err)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: setup_entry volledig")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.warning("BT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
