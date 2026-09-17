"""Btechnics IOT Branding v1.28.2.

v1.28.2:
- Zoom wordt niet meer toegepast in de companion app (iOS/Android); de app zet
  zelf zijn schaal en brak op de CSS zoom.

v1.28.1:
- Zijbalk: vaste logoregel (Btechnics en klantenlogo naast elkaar, automatisch op
  hoogte geschaald, tekst eronder op één regel). Logo's kunnen de kop niet meer breken.

v1.28.0:
- Klantenlogo: upload via de opties (bestand wordt bewaard in
  config/btechnics_branding/) en wordt naast het Btechnics logo getoond in
  de zijbalk, op het aanmeldscherm en op het opstartscherm. Schaal instelbaar,
  verwijderen via vinkje.

v1.27.0:
- Zoom instelbaar per desktop en mobiel (opties: zoom_desktop, zoom_mobile,
  zoom_breakpoint). Standaard 80% desktop, 85% mobiel, grens 870 px.

v1.26.1:
- JS: observer op shadow roots (dialogen/dropdowns direct gepatcht), help
  knoppen met HA link verborgen

v1.26.0:
- JS: sidebar en header terug licht (origineel), petrol enkel als primaire kleur

v1.25.2:
- brand/ map met icon.png, logo.png, dark_logo.png: HA brands API serveert nu
  het Btechnics icoon voor btechnics_branding (integratiepagina, HACS)
- JS: HACS update entiteit (CDN placeholder) krijgt het lokale icoon

v1.25.1:
- JS: actieve tabs in petrol header/bottom bar in goud (leesbaarheid mobiel)

v1.25.0:
- JS: Btechnics kleurenschema (petrol primair, oranje accent, petrol sidebar
  en header, gouden actieve items).
- btechnics-branding.js via eigen view met Cache-Control no-store, zodat
  Cloudflare (of een andere proxy) de JS niet 4 uur cachet na een update.
- JS: "Tip!" balk in Instellingen (ha-tip) verborgen.

v1.24.0:
- Brands API onderschept: /api/brands/integration/{homeassistant,hassio,demo}/*
  geeft nu het Btechnics icoon terug. Dit vervangt het HA huisje in o.a. de
  update dialogen (Core/Supervisor/OS), de updatelijst in Instellingen, de
  integratiepagina en overal waar de frontend een brand icoon opvraagt.
- JS: inline HA logo (ha-logo-svg en ha-svg-icon met het HA pad) wordt
  vervangen door het Btechnics icoon (Home paneel, Info pagina, ...)
- Static route onderschept: /static/icons/favicon*.png, favicon.ico,
  mask-icon.svg, apple touch iconen en /static/images/home-assistant-logo-*.svg
  komen nu uit de integratie (QR code logo, tag dialoog, login pagina, tabblad)
- Launch screen: HA gebruikt nu een <img class="ha-logo"> ipv inline svg;
  wordt nu ook verborgen en vervangen
- JS: ook alt/title/aria-label attributen met "Home Assistant" worden vervangen
- logo.svg en favicon.ico lokaal in de integratie
- JS: Open Home Foundation kaart (Info pagina) verborgen; release notes,
  community en OHF links verborgen; overige home-assistant.io links -> btechnics.be

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
import re

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

_LOGO_SVG_FILE = str(_DIR / "logo.svg")
_LOGO_SVG_URL = "/btechnics_branding/logo.svg"
_FAVICON_ICO_FILE = str(_DIR / "favicon.ico")

_API_URL = "/api/btechnics_branding/config"
_CUSTOMER_LOGO_URL = "/btechnics_branding/customer-logo"
_CUSTOMER_LOGO_DIR = "btechnics_branding"


def _customer_logo_path(hass, options):
    """Pad naar het klantenlogo of None."""
    name = options.get("customer_logo_file")
    if not name or "/" in name or "\\" in name:
        return None
    path = pathlib.Path(hass.config.path(_CUSTOMER_LOGO_DIR)) / name
    return path if path.is_file() else None


def _entry_options(hass):
    for entry in hass.config_entries.async_entries(DOMAIN):
        return entry.options
    return {}

_HIDE_CSS = (
    "<style id='bt-hide'>"
    "#ha-launch-screen svg,#ha-launch-screen img.ha-logo{display:none!important}"
    ".ohf-logo{display:none!important}"
    "</style>"
)
_EXT_SCRIPT = '<script src="/btechnics_branding/btechnics-branding.js" type="module"></script>'


class BtechnicsBrandingJsView(HomeAssistantView):
    """Serveert de branding JS zonder caching (Cloudflare cachet .js anders 4u)."""

    url = _JS_URL
    name = "btechnics_branding:js"
    requires_auth = False

    async def get(self, request):
        return web.FileResponse(
            _JS_FILE,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Content-Type": "application/javascript; charset=utf-8",
            },
        )


class BtechnicsBrandingCustomerLogoView(HomeAssistantView):
    """Serveert het geuploade klantenlogo (ook op het aanmeldscherm, dus zonder auth)."""

    url = _CUSTOMER_LOGO_URL
    name = "btechnics_branding:customer_logo"
    requires_auth = False

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        path = _customer_logo_path(self.hass, _entry_options(self.hass))
        if path is None:
            return web.Response(status=404, text="Geen klantenlogo")
        ctype = {
            ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        }.get(path.suffix.lower(), "application/octet-stream")
        return web.FileResponse(
            str(path),
            headers={"Cache-Control": "no-cache", "Content-Type": ctype},
        )


class BtechnicsBrandingConfigView(HomeAssistantView):
    url = _API_URL
    name = "api:btechnics_branding:config"
    requires_auth = False

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        config = _entry_options(self.hass)
        logo_path = _customer_logo_path(self.hass, config)
        customer_logo = None
        if logo_path is not None:
            try:
                customer_logo = f"{_CUSTOMER_LOGO_URL}?v={int(logo_path.stat().st_mtime)}"
            except OSError:
                customer_logo = _CUSTOMER_LOGO_URL
        return self.json({
            "login_text":        config.get("login_text", "Btechnics IOT"),
            "login_text_size":   config.get("login_text_size", 24),
            "sidebar_text":      config.get("sidebar_text", "Btechnics IOT"),
            "sidebar_text_size": config.get("sidebar_text_size", 16),
            "zoom_desktop":      config.get("zoom_desktop", 80),
            "zoom_mobile":       config.get("zoom_mobile", 85),
            "zoom_breakpoint":   config.get("zoom_breakpoint", 870),
            "customer_logo":     customer_logo,
            "customer_logo_scale": config.get("customer_logo_scale", 100),
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


_BRANDS_CANONICAL = "/api/brands/integration/{domain}/{image}"
_BRANDS_DOMAINS = ("homeassistant", "hassio", "demo")
_BRANDS_MARK = "_bt_brands_patched"


def _make_brands_handler(original):
    async def handler(request):
        domain = request.match_info.get("domain", "")
        image = request.match_info.get("image", "")
        if domain in _BRANDS_DOMAINS:
            path = _ICON_512_FILE if "@2x" in image or "logo" in image else _ICON_192_FILE
            return web.FileResponse(
                path,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        return await original(request)
    handler._bt_brands_patched = True  # type: ignore[attr-defined]
    return handler


def _patch_brands_route(app: web.Application) -> None:
    for resource in app.router.resources():
        canonical = getattr(resource, "canonical", "") or ""
        if canonical != _BRANDS_CANONICAL:
            continue
        for route in resource:
            if route.method not in ("GET", "*", "HEAD"):
                continue
            if getattr(route._handler, _BRANDS_MARK, False):
                continue
            try:
                route._handler = _make_brands_handler(route._handler)
                _LOGGER.warning("BT: brands route gepatcht (%s)", _BRANDS_DOMAINS)
            except Exception as e:
                _LOGGER.warning("BT brands patch fout: %s", e)


# Static bestanden van HA die het HA logo bevatten -> vervangen door Btechnics
_STATIC_PREFIX = "/static/"
_STATIC_RE = re.compile(
    r"^/static/(icons/(favicon[^/]*\.png|favicon\.ico|mask-icon\.svg|"
    r"apple-touch-icon[^/]*\.png|ha-icon[^/]*\.png)"
    r"|images/home-assistant-logo[^/]*\.svg)$"
)


def _static_override(path: str):
    if not _STATIC_RE.match(path):
        return None
    if path.endswith(".ico"):
        return _FAVICON_ICO_FILE, "image/x-icon"
    if path.endswith(".svg"):
        return _LOGO_SVG_FILE, "image/svg+xml"
    if "512" in path or "384" in path:
        return _ICON_512_FILE, "image/png"
    return _ICON_192_FILE, "image/png"


def _make_static_handler(original):
    async def handler(request):
        override = _static_override(request.path)
        if override:
            file_path, ctype = override
            return web.FileResponse(
                file_path,
                headers={"Cache-Control": "public, max-age=86400", "Content-Type": ctype},
            )
        return await original(request)
    handler._bt_static_patched = True  # type: ignore[attr-defined]
    return handler


def _patch_static_route(app: web.Application) -> None:
    for resource in app.router.resources():
        canonical = getattr(resource, "canonical", "") or ""
        if canonical.rstrip("/") != "/static":
            continue
        for route in resource:
            if route.method not in ("GET", "*", "HEAD"):
                continue
            if getattr(route._handler, "_bt_static_patched", False):
                continue
            try:
                route._handler = _make_static_handler(route._handler)
                _LOGGER.warning("BT: static route gepatcht (%s)", canonical)
            except Exception as e:
                _LOGGER.warning("BT static patch fout: %s", e)


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
            StaticPathConfig(_ICON_512_URL, _ICON_512_FILE, cache_headers=True),
            StaticPathConfig(_ICON_192_URL, _ICON_192_FILE, cache_headers=True),
            StaticPathConfig(_LOGO_SVG_URL, _LOGO_SVG_FILE, cache_headers=True),
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    hass.http.register_view(BtechnicsBrandingJsView())
    hass.http.register_view(BtechnicsBrandingConfigView(hass))
    hass.http.register_view(BtechnicsBrandingCustomerLogoView(hass))

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
    except Exception as err:
        _LOGGER.warning("add_extra_js_url: %s", err)

    _patch_routes(hass.http.app)
    _patch_brands_route(hass.http.app)
    _patch_static_route(hass.http.app)

    async def _delayed(_now=None):
        _patch_routes(hass.http.app)
        _patch_brands_route(hass.http.app)
        _patch_static_route(hass.http.app)

    hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.warning("BT: v1.28.2 klaar, klantenlogo ondersteund")
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    pass


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    return True
