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

_AUTH_JS = """<script>
(function(){var BRAND="Btechnics IOT",ICON="https://btechnics.be/logo_btechnics/btechnics-icon.png",LOGIN_TEXT="Btechnics IOT",LOGIN_SIZE=24;fetch("/api/btechnics_branding/config").then(function(r){if(r.ok)return r.json()}).then(function(d){if(d){LOGIN_TEXT=d.login_text||LOGIN_TEXT;LOGIN_SIZE=d.login_text_size||LOGIN_SIZE}patch();setInterval(patch,1000)}).catch(function(){patch();setInterval(patch,1000)});function deepPatch(root){if(!root)return;root.querySelectorAll('img[src*="favicon"],img[src*="logo"]').forEach(function(img){if(!img.dataset.bt){img.src=ICON;img.dataset.bt="1"}});var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);var node;while((node=walker.nextNode())){if(node.textContent.includes("Welkom thuis")||node.textContent.includes("Welcome home")){var p=node.parentElement;node.textContent=node.textContent.replace(/Welkom thuis!?/g,LOGIN_TEXT).replace(/Welcome home!?/g,LOGIN_TEXT);if(p)p.style.fontSize=LOGIN_SIZE+"px"}if(node.textContent.includes("Home Assistant")){node.textContent=node.textContent.replace(/Home Assistant/g,BRAND)}}root.querySelectorAll("*").forEach(function(el){if(el.shadowRoot)deepPatch(el.shadowRoot)})}function patch(){deepPatch(document.body);document.querySelectorAll('link[rel*="icon"]').forEach(function(l){l.remove()});var link=document.createElement("link");link.rel="icon";link.type="image/png";link.href=ICON;document.head.appendChild(link);if(document.title.includes("Home Assistant"))document.title=document.title.replace(/Home Assistant/g,BRAND)}new MutationObserver(patch).observe(document.documentElement,{childList:true,subtree:true})})();
</script>"""


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


def _inject_html(text, is_auth=False):
    """Injecteer CSS/JS in HTML tekst."""
    if "<head>" not in text or "bt-hide" in text:
        return None
    inject = _HIDE_CSS + (_AUTH_JS if is_auth else "")
    return text.replace("<head>", "<head>" + inject, 1)


def _read_response_text(response):
    """Lees tekst uit aiohttp response, alle mogelijke types."""
    # FileResponse: lees van disk
    if hasattr(response, "_path") and response._path:
        try:
            return pathlib.Path(str(response._path)).read_text("utf-8")
        except Exception:
            pass
    # Response met tekst
    if hasattr(response, "_text") and response._text:
        return response._text
    # Response met bytes
    for attr in ("_body", "body"):
        raw = getattr(response, attr, None)
        if raw:
            charset = getattr(response, "charset", "utf-8") or "utf-8"
            try:
                return raw.decode(charset, errors="replace")
            except Exception:
                pass
    return None


def _make_handler(original, is_auth=False):
    async def handler(request):
        response = await original(request)
        ct = getattr(response, "content_type", "") or ""
        if "text/html" not in ct:
            return response
        text = _read_response_text(response)
        if text:
            patched = _inject_html(text, is_auth)
            if patched:
                _LOGGER.warning("BT: HTML gepatcht voor %s (auth=%s)", request.path, is_auth)
                return web.Response(text=patched, status=response.status,
                                    content_type="text/html", charset="utf-8")
            else:
                _LOGGER.warning("BT: HTML skip voor %s (bt-hide al aanwezig: %s)", 
                                request.path, "bt-hide" in (text or ""))
        else:
            _LOGGER.warning("BT: geen tekst voor %s type=%s", request.path, type(response).__name__)
        return response
    return handler


def _make_manifest_handler(original):
    async def manifest_handler(request):
        response = await original(request)
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
        except Exception as err:
            _LOGGER.warning("BT manifest fout: %s", err)
        return response
    return manifest_handler


# Routes die zeker geen HTML zijn
_SKIP_PREFIXES = (
    '/api/', '/static/', '/frontend_latest/', '/frontend_es5/',
    '/local/', '/hacsfiles/', '/_debugger', '/service_worker',
    '/btechnics_branding/', '/auth/token', '/auth/revoke',
    '/auth/link_user', '/auth/providers', '/auth/login_flow',
    '/auth/external', '/media/', '/ai_task/',
)


def _patch_routes(app: web.Application) -> None:
    patched = []
    for resource in app.router.resources():
        canonical = getattr(resource, 'canonical', '') or ''
        if any(canonical.startswith(p) for p in _SKIP_PREFIXES):
            continue
        is_auth = 'authorize' in canonical or canonical == '/auth/authorize'
        for route in resource:
            if route.method not in ('GET', '*', 'HEAD'):
                continue
            try:
                if canonical == '/manifest.json':
                    route._handler = _make_manifest_handler(route._handler)
                    patched.append('MANIFEST')
                else:
                    route._handler = _make_handler(route._handler, is_auth=is_auth)
                    patched.append(canonical[:30])
            except Exception as e:
                _LOGGER.warning("BT patch fout %s: %s", canonical, e)
    _LOGGER.warning("BT patch: %d routes - %s", len(patched), patched[:15])


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
    _patch_routes(hass.http.app)

    async def _delayed(_now=None):
        _patch_routes(hass.http.app)

    hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: v1.19.0 klaar")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    pass


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
