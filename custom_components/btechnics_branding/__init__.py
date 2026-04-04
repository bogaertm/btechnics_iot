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
(function(){var BRAND="Btechnics IOT",ICON="https://btechnics.be/logo_btechnics/btechnics-icon.png",LOGIN_TEXT="Btechnics IOT",LOGIN_SIZE=24;fetch("/api/btechnics_branding/config").then(function(r){if(r.ok)return r.json()}).then(function(d){if(d){LOGIN_TEXT=d.login_text||LOGIN_TEXT;LOGIN_SIZE=d.login_text_size||LOGIN_SIZE}patch();setInterval(patch,1000)}).catch(function(){patch();setInterval(patch,1000)});function deepPatch(root){if(!root)return;root.querySelectorAll('img[src*="favicon"],img[src*="logo"]').forEach(function(img){if(!img.dataset.bt){img.src=ICON;img.dataset.bt="1"}});var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);var node;while((node=walker.nextNode())){if(node.textContent.includes("Welkom thuis")||node.textContent.includes("Welcome home")){var parent=node.parentElement;node.textContent=node.textContent.replace(/Welkom thuis!?/g,LOGIN_TEXT).replace(/Welcome home!?/g,LOGIN_TEXT);if(parent)parent.style.fontSize=LOGIN_SIZE+"px"}if(node.textContent.includes("Home Assistant")){node.textContent=node.textContent.replace(/Home Assistant/g,BRAND)}}root.querySelectorAll("*").forEach(function(el){if(el.shadowRoot)deepPatch(el.shadowRoot)})}function patch(){deepPatch(document.body);document.querySelectorAll('link[rel*="icon"]').forEach(function(l){l.remove()});var link=document.createElement("link");link.rel="icon";link.type="image/png";link.href=ICON;document.head.appendChild(link);if(document.title.includes("Home Assistant"))document.title=document.title.replace(/Home Assistant/g,BRAND)}new MutationObserver(patch).observe(document.documentElement,{childList:true,subtree:true})})();
</script>"""

# Routes die we skippen - ZONDER /auth/ want we willen /auth/authorize patchen
_SKIP_PREFIXES = (
    '/api/', '/static/', '/frontend_latest/', '/frontend_es5/',
    '/local/', '/hacsfiles/', '/_debugger', '/service_worker',
    '/btechnics_branding/',
    '/auth/token', '/auth/revoke', '/auth/link_user',
    '/auth/providers', '/auth/login_flow', '/auth/external',
)

# Auth routes die WEL HTML serveren
_AUTH_HTML_PATHS = ('/auth/authorize',)


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


def _make_html_handler(original, is_auth=False):
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
                inject = _HIDE_CSS
                if is_auth:
                    inject += _AUTH_JS
                patched = text.replace("<head>", "<head>" + inject, 1)
                return web.Response(
                    text=patched, status=response.status,
                    content_type="text/html", charset="utf-8",
                )
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
    for resource in app.router.resources():
        canonical = getattr(resource, 'canonical', '') or ''

        # Skip niet-HTML routes
        if any(canonical.startswith(p) for p in _SKIP_PREFIXES):
            continue

        for route in resource:
            if route.method not in ('GET', '*', 'HEAD'):
                continue
            try:
                if canonical == '/manifest.json':
                    route._handler = _make_manifest_handler(route._handler)
                    patched.append('MANIFEST')
                elif canonical in _AUTH_HTML_PATHS or 'authorize' in canonical:
                    route._handler = _make_html_handler(route._handler, is_auth=True)
                    patched.append('AUTH:' + canonical)
                else:
                    route._handler = _make_html_handler(route._handler, is_auth=False)
                    patched.append(canonical[:25])
            except Exception as e:
                _LOGGER.warning("BT patch fout %s: %s", canonical, e)
    _LOGGER.warning("BT: gepatcht: %s", patched[:15])


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
    try:
        _patch_routes(hass.http.app)
    except Exception as err:
        _LOGGER.warning("route patch fout: %s", err)

    async def _delayed_patch(_now=None):
        try:
            _patch_routes(hass.http.app)
        except Exception as err:
            _LOGGER.warning("uitgestelde patch fout: %s", err)

    hass.bus.async_listen_once("homeassistant_started", _delayed_patch)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: setup volledig v1.17.0")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    _LOGGER.warning("BT: instellingen bijgewerkt")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
