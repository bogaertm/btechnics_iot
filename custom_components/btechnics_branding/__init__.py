"""Btechnics IOT Branding v1.21.0."""
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
_AUTH_INJECT = (
    _HIDE_CSS
    + '<script src="/btechnics_branding/btechnics-branding.js" type="module"></script>'
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


def _find_authorize_html() -> pathlib.Path | None:
    """Zoek het authorize.html bestand in de homeassistant_frontend package."""
    try:
        import homeassistant_frontend
        pkg_dir = pathlib.Path(homeassistant_frontend.__file__).parent
        _LOGGER.warning("BT: frontend package: %s", pkg_dir)
        for candidate in [
            pkg_dir / "authorize.html",
            pkg_dir / "www_static" / "authorize.html",
            pkg_dir.parent / "authorize.html",
        ]:
            if candidate.exists():
                _LOGGER.warning("BT: authorize.html gevonden: %s", candidate)
                return candidate
        # Zoek recursief
        results = list(pkg_dir.rglob("authorize*.html"))
        _LOGGER.warning("BT: authorize html search: %s", results)
        if results:
            return results[0]
    except Exception as e:
        _LOGGER.warning("BT: homeassistant_frontend import fout: %s", e)
    return None


def _patch_html_file(html_path: pathlib.Path, inject: str) -> bool:
    """Patch een HTML bestand met inject na <head>. Backup eerst."""
    try:
        original = html_path.read_text("utf-8")
        if "bt-hide" in original:
            _LOGGER.warning("BT: %s al gepatcht", html_path)
            return True
        if "<head>" not in original:
            _LOGGER.warning("BT: geen <head> in %s", html_path)
            return False
        backup = html_path.with_suffix(".html.bak")
        if not backup.exists():
            backup.write_text(original, "utf-8")
        patched = original.replace("<head>", "<head>" + inject, 1)
        html_path.write_text(patched, "utf-8")
        _LOGGER.warning("BT: %s gepatcht (backup: %s)", html_path, backup)
        return True
    except Exception as e:
        _LOGGER.warning("BT: patch fout %s: %s", html_path, e)
        return False


def _patch_main_routes(app: web.Application) -> None:
    """Patch route handlers voor main HTML + manifest."""
    def _make_html_handler(original):
        async def h(request):
            response = await original(request)
            ct = getattr(response, "content_type", "") or ""
            if "text/html" not in ct:
                return response
            text = None
            if hasattr(response, "_path") and response._path:
                try:
                    text = pathlib.Path(str(response._path)).read_text("utf-8")
                except Exception:
                    pass
            if text is None:
                for attr in ("_text", "_body", "body"):
                    val = getattr(response, attr, None)
                    if val:
                        text = val.decode("utf-8") if isinstance(val, bytes) else val
                        break
            if text and "<head>" in text and "bt-hide" not in text:
                patched = text.replace("<head>", "<head>" + _HIDE_CSS, 1)
                return web.Response(text=patched, status=response.status,
                                    content_type="text/html", charset="utf-8")
            return response
        return h

    def _make_manifest_handler(original):
        async def h(request):
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
            except Exception as e:
                _LOGGER.warning("BT manifest: %s", e)
            return response
        return h

    _SKIP = (
        '/api/', '/static/', '/frontend_latest/', '/frontend_es5/',
        '/local/', '/hacsfiles/', '/_debugger', '/service_worker',
        '/btechnics_branding/', '/auth/token', '/auth/revoke',
        '/auth/link_user', '/auth/providers', '/auth/login_flow',
        '/auth/external', '/media/', '/ai_task/',
    )
    patched = []
    for resource in app.router.resources():
        canonical = getattr(resource, 'canonical', '') or ''
        if any(canonical.startswith(p) for p in _SKIP):
            continue
        for route in resource:
            if route.method not in ('GET', '*', 'HEAD'):
                continue
            try:
                if canonical == '/manifest.json':
                    route._handler = _make_manifest_handler(route._handler)
                    patched.append('MANIFEST')
                else:
                    route._handler = _make_html_handler(route._handler)
                    patched.append(canonical[:20])
            except Exception as e:
                _LOGGER.warning("BT patch fout %s: %s", canonical, e)
    _LOGGER.warning("BT: routes gepatcht: %s", patched[:10])


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

    # Patch routes voor de hoofdapp
    _patch_main_routes(hass.http.app)

    # Patch het authorize.html bestand DIRECT op disk
    auth_html = _find_authorize_html()
    if auth_html:
        _patch_html_file(auth_html, _AUTH_INJECT)
    else:
        _LOGGER.warning("BT: authorize.html NIET gevonden - login pagina kan niet gepatcht worden")

    async def _delayed(_now=None):
        _patch_main_routes(hass.http.app)

    hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: v1.21.0 klaar")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    pass


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    # Herstel authorize.html bij unload
    try:
        auth_html = _find_authorize_html()
        if auth_html:
            backup = auth_html.with_suffix(".html.bak")
            if backup.exists():
                auth_html.write_text(backup.read_text("utf-8"), "utf-8")
                _LOGGER.warning("BT: authorize.html hersteld van backup")
    except Exception as e:
        _LOGGER.warning("BT unload: %s", e)
    return True
