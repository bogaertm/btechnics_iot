"""Btechnics IOT Branding v1.23.0.

v1.23.0:
- PWA app iconen lokaal in de integratie (app-icon-192.png, app-icon-512.png)
- Manifest icons array volledig herschreven met correcte sizes (lost Lighthouse
  waarschuwing op over mismatch tussen opgegeven en werkelijke icoongrootte)
- Geen externe afhankelijkheid van btechnics.be meer voor de PWA install

v1.22.0:
- FileResponse content_type fix voor de auth pagina
"""
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

_ICON_512_FILE = str(_DIR / "app-icon-512.png")
_ICON_512_URL = "/btechnics_branding/app-icon-512.png"
_ICON_192_FILE = str(_DIR / "app-icon-192.png")
_ICON_192_URL = "/btechnics_branding/app-icon-192.png"

_API_URL = "/api/btechnics_branding/config"

_HIDE_CSS = (
    "<style id='bt-hide'>"
    "#ha-launch-screen svg{display:none!important}"
    ".ohf-logo{display:none!important}"
    "</style>"
)
_EXT_SCRIPT = '<script src="/btechnics_branding/btechnics-branding.js" type="module"></script>'


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


def _patch_response(response, request_path: str):
    """
    Patcheer een HTML response.
    Werkt zowel voor web.Response (content_type ingesteld)
    als voor FileResponse (content_type NIET ingesteld tot prepare()).
    """
    text = None

    # Geval 1 FileResponse, lees van _path
    file_path = getattr(response, "_path", None)
    if file_path:
        p = pathlib.Path(str(file_path))
        if p.suffix.lower() not in (".html", ".htm"):
            return None
        try:
            text = p.read_text("utf-8")
            _LOGGER.warning("BT: FileResponse gelezen: %s (pad: %s)", request_path, p)
        except Exception as e:
            _LOGGER.warning("BT: FileResponse leesfout %s: %s", p, e)
            return None

    # Geval 2 gewone Response, check content_type
    else:
        ct = getattr(response, "content_type", "") or ""
        if "text/html" not in ct:
            return None
        for attr in ("_text", "_body", "body"):
            val = getattr(response, attr, None)
            if val:
                text = val.decode("utf-8") if isinstance(val, bytes) else val
                break

    if not text or "<head>" not in text:
        _LOGGER.warning("BT: geen bruikbare HTML tekst voor %s", request_path)
        return None

    if "bt-hide" in text:
        return None

    is_auth = "authorize" in request_path or "/auth/" in request_path
    inject = _HIDE_CSS + (_EXT_SCRIPT if is_auth else "")
    patched = text.replace("<head>", "<head>" + inject, 1)
    _LOGGER.warning("BT: HTML gepatcht voor %s (auth=%s)", request_path, is_auth)
    return web.Response(
        text=patched,
        status=response.status,
        content_type="text/html",
        charset="utf-8",
    )


def _make_html_handler(original):
    async def handler(request):
        response = await original(request)
        patched = _patch_response(response, request.path)
        return patched if patched is not None else response
    return handler


def _make_manifest_handler(original):
    async def handler(request):
        response = await original(request)
        try:
            raw = getattr(response, "_body", None) or getattr(response, "body", None)
            if raw:
                m = json.loads(raw.decode("utf-8"))
                m["name"] = "Btechnics IOT"
                m["short_name"] = "Btechnics IOT"
                m["icons"] = [
                    {
                        "src": _ICON_192_URL,
                        "sizes": "192x192",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                    {
                        "src": _ICON_512_URL,
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                ]
                return web.Response(
                    text=json.dumps(m), status=200,
                    content_type="application/manifest+json",
                )
        except Exception as e:
            _LOGGER.warning("BT manifest fout: %s", e)
        return response
    return handler


_SKIP = (
    "/api/", "/static/", "/frontend_latest/", "/frontend_es5/",
    "/local/", "/hacsfiles/", "/_debugger", "/service_worker",
    "/btechnics_branding/", "/auth/token", "/auth/revoke",
    "/auth/link_user", "/auth/providers", "/auth/login_flow",
    "/auth/external", "/media/", "/ai_task/",
)


def _patch_routes(app: web.Application) -> None:
    patched = []
    for resource in app.router.resources():
        canonical = getattr(resource, "canonical", "") or ""
        if any(canonical.startswith(p) for p in _SKIP):
            continue
        for route in resource:
            if route.method not in ("GET", "*", "HEAD"):
                continue
            try:
                if canonical == "/manifest.json":
                    route._handler = _make_manifest_handler(route._handler)
                    patched.append("MANIFEST")
                else:
                    route._handler = _make_html_handler(route._handler)
                    patched.append(canonical[:25])
            except Exception as e:
                _LOGGER.warning("BT patch fout %s: %s", canonical, e)
    _LOGGER.warning("BT: %d routes gepatcht: %s", len(patched), patched[:12])


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, _JS_FILE, cache_headers=False),
            StaticPathConfig(_ICON_512_URL, _ICON_512_FILE, cache_headers=True),
            StaticPathConfig(_ICON_192_URL, _ICON_192_FILE, cache_headers=True),
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    hass.http.register_view(BtechnicsBrandingConfigView(hass))

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
    except Exception as err:
        _LOGGER.warning("add_extra_js_url: %s", err)

    _patch_routes(hass.http.app)

    async def _delayed(_now=None):
        _patch_routes(hass.http.app)

    hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: v1.23.0 klaar, lokale PWA iconen actief")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    pass


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
