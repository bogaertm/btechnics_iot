"""Btechnics IOT Branding v1.32.0.

v1.32.0:
- Updates die automatisch 's nachts geinstalleerd worden, zijn niet meer
  zichtbaar in de zijbalk en bovenaan Instellingen. Na 2 mislukte pogingen voor
  dezelfde versie komt de update weer tevoorschijn, met een melding onder
  Reparaties. Details in auto_update.py.

v1.31.0:
- Automatische updates, instelbaar in de opties: elke nacht op een gekozen uur
  (standaard 04:00) worden Supervisor, apps, HACS en Core/OS bijgewerkt. Core
  enkel vanaf x.1, altijd met back-up, en niet zolang de zelfcontrole een
  probleem meldt. Zie auto_update.py. Service btechnics_branding.run_updates om
  het meteen te starten of met dry_run te zien wat er zou gebeuren.

v1.30.0:
- Zelfcontrole na elke start: controleert of alle haken in HA nog werken
  (pagina's, manifest, brands, static iconen, enquete, JS) en of de frontend
  de zijbalk en systeemdata nog vindt. Werkt iets niet meer na een HA update,
  dan verschijnt een melding onder Instellingen > Reparaties met wat er stuk is.

v1.29.1 (audit):
- HTML routes werden bij elke start twee keer ingepakt (bij setup en bij
  homeassistant_started); nu met merkteken, dus maar een keer.
- authorize.html wordt niet meer in de event loop van schijf gelezen maar in
  een executor.
- Logboek: de meldingen per paginabezoek staan nu op debug in plaats van
  warning, zodat het HA logboek niet volloopt.
- Brands: logo afbeeldingen (logo.png, dark_logo.png) krijgen het brede
  Btechnics logo in plaats van het vierkante icoon.

v1.29.0:
- Enquete (onboarding survey) van HA volledig uit: bij elke start wordt in de
  frontend systeemdata gezet dat ze al afgehandeld is, zodat de melding nooit
  meer verschijnt bij de eigenaar.
- Brands API: alle integraties die in de brands repo naar het HA logo wijzen
  (o.a. version, trace, syslog, homeassistant_hardware, update, HA Green/Yellow)
  krijgen nu het Btechnics icoon.
- Static: ook maskable_icon, tile-win, notification-badge en de Open Home
  Foundation afbeeldingen worden vervangen (OHF door een lege afbeelding).
- Opstartscherm: het HA logo wordt al in de HTML vervangen door het Btechnics
  logo, dus geen flits meer van het huisje voor de JS geladen is.

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
import asyncio
import json
import logging
import pathlib
import re

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from . import app_download, auto_update, desktop, remote, status
from homeassistant.helpers.dispatcher import async_dispatcher_send

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
_FAVICON_ICO_URL = "/btechnics_branding/favicon.ico"
_ICON_PNG_RE = re.compile(r"/static/icons/(?:favicon-(?:\d+x\d+|apple-\d+x\d+)|maskable_icon-\d+x\d+)\.png")
_BRAND_LOGO_FILE = str(_DIR / "brand" / "logo.png")
_BRAND_DARK_LOGO_FILE = str(_DIR / "brand" / "dark_logo.png")

_API_URL = "/api/btechnics_branding/config"
_LAUNCH_LOGO_HA = "/static/images/home-assistant-logo-loading.svg"
_BT_PETROL = "#00222b"
_HA_THEME_COLOR = "#2980b9"
_HTML_REPLACE = (
    ("<title>Home Assistant</title>", "<title>Btechnics IOT</title>"),
    ('content="Home Assistant"', 'content="Btechnics IOT"'),
    ('alt="Home Assistant"', 'alt="Btechnics IOT"'),
    ("Could not load Home Assistant", "Could not load Btechnics IOT"),
    ('color="#18bcf2"', 'color="#ed6928"'),
    (f'content="{_HA_THEME_COLOR}"', f'content="{_BT_PETROL}"'),
)
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
    "#ha-launch-screen svg{display:none!important}"
    "#ha-launch-screen img.ha-logo{width:auto!important;height:80px!important}"
    ".ohf-logo{display:none!important}"
    "</style>"
)
_EXT_SCRIPT = '<script src="/btechnics_branding/btechnics-branding.js" type="module"></script>'

# v1.34.0: WOORDKEUZE VOOR WONINGEN EN BEDRIJVEN.
# HA spreekt in het Nederlands overal van "woning", "je huis" en "Welkom thuis".
# Btechnics IOT draait ook in bedrijven, dus neutrale woorden. De frontend haalt
# zijn vertalingen op als /static/translations/[fragment/]nl-<hash>.json
# (frontend src/util/common-translation.ts). Dit script staat als eerste in de
# <head>, nog voor HA zelf laadt, en past die bestanden aan op het moment dat ze
# binnenkomen. Zo werkt het ook als de browser of de app ze al in de cache heeft.
_TR_KEYS = {
    "ui.panel.config.core.caption": "Algemeen",
    "ui.dialogs.quick-bar.commands.navigation.general": "Algemeen",
    "ui.panel.config.core.section.core.home_name_card.header": "Locatienaam",
    "ui.panel.page-authorize.welcome_home": "Welkom!",
    "ui.panel.lovelace.strategy.original-states.empty_state_title": "Welkom",
    "ui.panel.page-onboarding.core-config.location_header": "Locatie",
    "ui.panel.config.energy.battery.title": "Batterijopslag",
}
_TR_RULES = [
    [r"\b(je|jouw) (huis|woning)\b", "$1 locatie"],
    [r"\bThuisbatterij", "Batterij"],
    [r"\bthuisbatterij", "batterij"],
]
_TR_SCRIPT = (
    "<script>(function(){var K=" + json.dumps(_TR_KEYS, ensure_ascii=False)
    + ",R=" + json.dumps(_TR_RULES)
    + ".map(function(x){return [new RegExp(x[0],'g'),x[1]]});"
    "var M=/^\\/static\\/translations\\/(?:[\\w-]+\\/)?nl-[0-9a-f]+\\.json$/;"
    "var f=window.fetch;if(!f||f._bt)return;"
    "var w=function(i,o){var u=typeof i==='string'?i:(i&&i.url)||'';"
    "var p=f.apply(window,arguments);var a;try{a=new URL(u,location.href)}catch(e){return p}"
    "if(a.origin!==location.origin||!M.test(a.pathname))return p;"
    "return p.then(function(r){if(!r.ok)return r;return r.clone().json().then(function(d){"
    "for(var k in d){var v=d[k];if(typeof v!=='string')continue;"
    "if(K.hasOwnProperty(k)){d[k]=K[k];continue}"
    "for(var j=0;j<R.length;j++)v=v.replace(R[j][0],R[j][1]);d[k]=v}"
    "return new Response(JSON.stringify(d),{status:r.status,headers:{'Content-Type':'application/json'}})"
    "},function(){return r})})};w._bt=1;window.fetch=w})();</script>"
)


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
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": ctype,
                # Een geupload SVG mag geen script uitvoeren als iemand de URL
                # rechtstreeks opent (zelfde domein als HA).
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
                "X-Content-Type-Options": "nosniff",
            },
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


def _patch_response(response, request_path: str, file_text: str | None = None):
    """
    Patcheer een HTML response.
    Werkt zowel voor web.Response (content_type ingesteld)
    als voor FileResponse (content_type NIET ingesteld tot prepare()).
    """
    text = None

    # Geval 1 FileResponse: de handler las het bestand al in een executor
    file_path = getattr(response, "_path", None)
    if file_path:
        if file_text is None:
            return None
        text = file_text

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
        _LOGGER.debug("BT: geen bruikbare HTML tekst voor %s", request_path)
        return None

    if "bt-hide" in text:
        return None

    is_auth = "authorize" in request_path or "/auth/" in request_path
    inject = _TR_SCRIPT + _HIDE_CSS + (_EXT_SCRIPT if is_auth else "")
    patched = text.replace("<head>", "<head>" + inject, 1)
    # Opstartscherm: HA logo meteen in de HTML vervangen (geen flits voor de JS er is)
    patched = patched.replace(_LAUNCH_LOGO_HA, _LOGO_SVG_URL)
    # v1.29.1: naam en kleuren die al in de HTML staan, voor de JS geladen is.
    # apple-mobile-web-app-title is de naam onder het icoon bij "Zet op
    # beginscherm" op iPhone; application-name idem op Android/Windows.
    for old, new in _HTML_REPLACE:
        patched = patched.replace(old, new)
    # v1.40.0: HA-iconen in de HTML naar eigen, geversioneerde adressen. Een browser
    # die de site al eens opende voor de branding er was, bewaart het HA-icoon onder
    # het oude adres (1 dag, iOS het "site-icoon" nog langer) en toonde dat verder,
    # ook op het aanmeldscherm. Een nieuw adres wordt altijd opnieuw opgehaald.
    patched = _ICON_PNG_RE.sub(f"{_ICON_192_URL}?v={_BT_VERSION}", patched)
    patched = patched.replace('"/static/icons/favicon.ico"', f'"{_FAVICON_ICO_URL}?v={_BT_VERSION}"')
    _LOGGER.debug("BT: HTML gepatcht voor %s (auth=%s)", request_path, is_auth)
    return web.Response(
        text=patched,
        status=response.status,
        content_type="text/html",
        charset="utf-8",
    )


def _make_html_handler(original):
    async def handler(request):
        response = await original(request)
        text = None
        file_path = getattr(response, "_path", None)
        if file_path and str(file_path).lower().endswith((".html", ".htm")):
            try:
                text = await asyncio.get_running_loop().run_in_executor(
                    None, pathlib.Path(str(file_path)).read_text, "utf-8"
                )
            except OSError as err:
                _LOGGER.debug("BT: leesfout %s: %s", file_path, err)
                return response
        patched = _patch_response(response, request.path, text)
        return patched if patched is not None else response
    handler._bt_html_patched = True  # type: ignore[attr-defined]
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
                if str(m.get("theme_color", "")).lower() == _HA_THEME_COLOR:
                    m["theme_color"] = _BT_PETROL
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
    handler._bt_html_patched = True  # type: ignore[attr-defined]
    return handler


_BRANDS_CANONICAL = "/api/brands/integration/{domain}/{image}"
# Alle domeinen die in de brands repo (core_integrations/*) een symlink naar
# _homeassistant zijn, plus de HA-huisjes van update en de HA hardware.
_BRANDS_DOMAINS = (
    "homeassistant", "hassio", "demo", "homeassistant_hardware",
    "compensation", "emulated_hue", "emulated_kasa", "emulated_roku",
    "lacrosse", "picotts", "rss_feed_template", "seven_segments",
    "simulated", "syslog", "tcp", "telnet", "trace", "version",
    "update", "homeassistant_green", "homeassistant_yellow",
    "homeassistant_sky_connect", "homeassistant_connect_zbt1",
    "homeassistant_connect_zbt2",
)
_BRANDS_MARK = "_bt_brands_patched"


def _make_brands_handler(original):
    async def handler(request):
        domain = request.match_info.get("domain", "")
        image = request.match_info.get("image", "")
        if domain in _BRANDS_DOMAINS:
            if "logo" in image:
                path = _BRAND_DARK_LOGO_FILE if image.startswith("dark_") else _BRAND_LOGO_FILE
            else:
                path = _ICON_512_FILE if "@2x" in image else _ICON_192_FILE
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
                _LOGGER.info("BT: brands route gepatcht (%s)", _BRANDS_DOMAINS)
            except Exception as e:
                _LOGGER.warning("BT brands patch fout: %s", e)


# Static bestanden van HA die het HA logo bevatten -> vervangen door Btechnics
_STATIC_PREFIX = "/static/"
_STATIC_RE = re.compile(
    r"^/static/(icons/(favicon[^/]*\.png|favicon\.ico|mask-icon\.svg|"
    r"apple-touch-icon[^/]*\.png|ha-icon[^/]*\.png|maskable_icon[^/]*\.png|"
    r"tile-win[^/]*\.png|logo_ohf\.svg|ohf\.svg)"
    r"|images/(home-assistant-logo[^/]*\.svg|notification-badge\.png|"
    r"ohf-badge\.svg|open-home-foundation[^/]*\.svg))$"
)
_BLANK_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'


def _static_override(path: str):
    if not _STATIC_RE.match(path):
        return None
    if "ohf" in path or "open-home-foundation" in path:
        return "BLANK", "image/svg+xml"
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
            if file_path == "BLANK":
                return web.Response(
                    body=_BLANK_SVG, content_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"},
                )
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
                _LOGGER.info("BT: static route gepatcht (%s)", canonical)
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
            if getattr(route._handler, "_bt_html_patched", False):
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
    if patched:
        _LOGGER.debug("BT: %d routes gepatcht: %s", len(patched), patched[:12])


async def _disable_onboarding_survey(hass: HomeAssistant) -> None:
    """Zet de HA enquete definitief op afgehandeld.

    De frontend toont de enquete aan de eigenaar tussen 5 en 30 dagen na de
    installatie, tenzij frontend systeemdata core.surveys.onboarding bestaat
    (frontend src/util/onboarding-survey.ts). Die sleutel zetten we hier zelf.
    """
    try:
        from homeassistant.components.frontend.storage import async_system_store
    except ImportError:
        _health(hass)["backend"].add("survey")
        return
    try:
        store = await async_system_store(hass)
        core = dict(store.data.get("core") or {})
        surveys = dict(core.get("surveys") or {})
        if surveys.get("onboarding"):
            return
        surveys["onboarding"] = {
            "date": dt_util.utcnow().isoformat(),
            "action": "dismissed",
        }
        core["surveys"] = surveys
        await store.async_set_item("core", core)
        _LOGGER.info("BT: HA enquete uitgeschakeld")
    except Exception as err:  # noqa: BLE001
        _health(hass)["backend"].add("survey")
        _LOGGER.warning("BT: enquete uitschakelen mislukt: %s", err)


# --- Zelfcontrole -------------------------------------------------------------
_HEALTH_KEY = "btechnics_branding_health"
_HEALTH_URL = "/api/btechnics_branding/health"
_ISSUE_ID = "hooks_broken"
_HEALTH_LABELS = {
    "pages": "pagina's (index en aanmeldscherm)",
    "manifest": "app manifest",
    "brands": "brand iconen",
    "static": "HA iconen en favicon",
    "survey": "enquete uitschakelen",
    "js": "Btechnics script in de frontend",
    "sidebar": "zijbalk (logo en tekst)",
    "systemdata": "systeemdata in de frontend",
    "launch": "opstartscherm",
}


def _health(hass) -> dict:
    return hass.data.setdefault(_HEALTH_KEY, {"backend": set(), "frontend": set(), "ok_version": None, "store": None})


# v1.37.0: een scherm dat de zijbalk niet vindt (kiosk, verborgen of traag
# toestel) gaf een valse melding "branding werkt niet meer". Een echte breuk
# komt na een update en zit dan op elk scherm. Daarom: zodra een scherm op deze
# combinatie van HA en Btechnics IOT meldt dat alles werkt, is die versie
# bevestigd. Latere probleemmeldingen van een enkel scherm op een bevestigde
# versie worden genegeerd (enkel gelogd). Na een update begint het opnieuw.
_BT_VERSION = "1.40.0"
_HEALTH_STORE = f"{DOMAIN}.health"


def _version_key() -> str:
    return f"{HA_VERSION}|{_BT_VERSION}"


async def _load_health(hass) -> None:
    from homeassistant.helpers.storage import Store

    state = _health(hass)
    if state["store"] is not None:
        return
    state["store"] = Store(hass, 1, _HEALTH_STORE)
    data = await state["store"].async_load() or {}
    state["ok_version"] = data.get("ok_version") if isinstance(data, dict) else None


def _route_marked(app: web.Application, canonical: str, mark: str) -> bool:
    for resource in app.router.resources():
        if (getattr(resource, "canonical", "") or "").rstrip("/") != canonical.rstrip("/"):
            continue
        for route in resource:
            if getattr(route._handler, mark, False):
                return True
    return False


def _check_backend(hass) -> set[str]:
    app = hass.http.app
    problems = set()
    if not _route_marked(app, "/", "_bt_html_patched"):
        problems.add("pages")
    if not _route_marked(app, "/manifest.json", "_bt_html_patched"):
        problems.add("manifest")
    if not _route_marked(app, _BRANDS_CANONICAL, _BRANDS_MARK):
        problems.add("brands")
    if not _route_marked(app, "/static", "_bt_static_patched"):
        problems.add("static")
    problems |= _health(hass)["backend"] & {"survey", "js"}
    return problems


@callback
def _update_issue(hass) -> None:
    state = _health(hass)
    problems = sorted(state["backend"] | state["frontend"])
    # v1.33.0: Btechnics meteen verwittigen als de stand verandert
    if state.get("sent") != problems:
        state["sent"] = problems
        async_dispatcher_send(hass, status.SIGNAL_CHANGED, "branding")
    if not problems:
        ir.async_delete_issue(hass, DOMAIN, _ISSUE_ID)
        return
    _LOGGER.warning("BT zelfcontrole: werkt niet meer na update: %s", problems)
    ir.async_create_issue(
        hass,
        DOMAIN,
        _ISSUE_ID,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=_ISSUE_ID,
        translation_placeholders={
            "problems": ", ".join(_HEALTH_LABELS.get(p, p) for p in problems),
            "ha_version": HA_VERSION,
        },
    )


class BtechnicsBrandingHealthView(HomeAssistantView):
    """De frontend meldt hier wat hij niet (meer) vindt. Enkel voor admins."""

    url = _HEALTH_URL
    name = "api:btechnics_branding:health"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        """Stand van de zelfcontrole en de laatste automatische update (admins)."""
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return web.Response(status=403)
        state = _health(self.hass)
        return self.json({
            "problems": sorted(state["backend"] | state["frontend"]),
            "auto_update_last": self.hass.data.get("btechnics_branding_update_last"),
            "status_last": (self.hass.data.get("btechnics_branding_status") or {}).get("last"),
            "bevestigd": state.get("ok_version") == _version_key(),
            "laatste_probleem": state.get("last_problem"),
        })

    async def post(self, request):
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            return web.Response(status=403)
        try:
            data = await request.json()
        except ValueError:
            return web.Response(status=400)
        if not isinstance(data, dict) or not isinstance(data.get("problems", []), list):
            return web.Response(status=400)
        allowed = {"sidebar", "systemdata", "launch"}
        found = {p for p in data.get("problems", []) if isinstance(p, str) and p in allowed}
        state = _health(self.hass)
        if found:
            # v1.38.0: welk scherm meldt dit? In het HA logboek en in de status (Work-app).
            client = data.get("client") if isinstance(data.get("client"), dict) else {}
            clean = {k: re.sub(r"[<>\x00-\x1f]", "", str(client.get(k) or ""))[:200]
                     for k in ("user", "agent", "page", "screen", "found")}
            clean["ip"] = str(request.remote or "")[:60]
            state["last_problem"] = {"at": dt_util.utcnow().isoformat(), "problems": sorted(found), **clean}
            ignored = state.get("ok_version") == _version_key()
            _LOGGER.warning(
                "BT zelfcontrole: scherm meldt %s%s. Gebruiker %s, IP %s, pagina %s, scherm %s, gevonden %s, toestel %s",
                sorted(found), " (genegeerd, deze versie werkte al)" if ignored else "",
                clean["user"], clean["ip"], clean["page"], clean["screen"], clean["found"], clean["agent"],
            )
            auto_update._log(  # noqa: SLF001
                self.hass,
                f"zelfcontrole: {', '.join(sorted(found))} gemeld door {clean['user'] or '?'} "
                f"({clean['ip']}, {clean['screen']}, {clean['agent'][:80]})"
                + (", genegeerd" if ignored else ""),
            )
        if not found and state.get("ok_version") != _version_key():
            state["ok_version"] = _version_key()
            if state.get("store") is not None:
                state["store"].async_delay_save(lambda: {"ok_version": state["ok_version"]}, 5)
        elif found and state.get("ok_version") == _version_key():
            return self.json({"ok": True, "genegeerd": True})
        if found != state["frontend"]:
            state["frontend"] = found
            _update_issue(self.hass)
        return self.json({"ok": True})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(_ICON_512_URL, _ICON_512_FILE, cache_headers=True),
            StaticPathConfig(_ICON_192_URL, _ICON_192_FILE, cache_headers=True),
            StaticPathConfig(_FAVICON_ICO_URL, _FAVICON_ICO_FILE, cache_headers=True),
            StaticPathConfig(_LOGO_SVG_URL, _LOGO_SVG_FILE, cache_headers=True),
        ])
    except Exception as err:
        _LOGGER.warning("Static path: %s", err)

    hass.http.register_view(BtechnicsBrandingJsView())
    hass.http.register_view(BtechnicsBrandingConfigView(hass))
    hass.http.register_view(BtechnicsBrandingCustomerLogoView(hass))
    await _load_health(hass)
    hass.http.register_view(BtechnicsBrandingHealthView(hass))
    hass.http.register_view(app_download.AppDownloadView())

    try:
        frontend.add_extra_js_url(hass, _JS_URL)
    except Exception as err:
        _health(hass)["backend"].add("js")
        _LOGGER.warning("add_extra_js_url: %s", err)

    _patch_routes(hass.http.app)
    _patch_brands_route(hass.http.app)
    _patch_static_route(hass.http.app)

    await _disable_onboarding_survey(hass)

    async def _delayed(_now=None):
        await _disable_onboarding_survey(hass)
        _patch_routes(hass.http.app)
        _patch_brands_route(hass.http.app)
        _patch_static_route(hass.http.app)
        state = _health(hass)
        state["backend"] = _check_backend(hass)
        _update_issue(hass)

    auto_update.register_services(hass, lambda: dict(entry.options))
    auto_update.async_schedule(hass, dict(entry.options))
    await auto_update.async_setup_visibility(hass, lambda: dict(entry.options))
    status.register_services(hass, lambda: dict(entry.options))
    await status.async_setup(hass, lambda: dict(entry.options))
    await remote.async_setup(hass, entry)
    await desktop.async_setup(hass)
    app_download.async_setup(hass)  # v1.36.0: zijbalk-item om de desktop-app te downloaden

    if hass.is_running:
        hass.async_create_task(_delayed())
    else:
        hass.bus.async_listen_once("homeassistant_started", _delayed)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.info("BT: v%s klaar", _BT_VERSION)
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    # Geen herlaad (de views en routes zijn al geregistreerd); enkel herplannen.
    auto_update.async_schedule(hass, dict(entry.options))
    auto_update.apply_options(hass, dict(entry.options))
    async_dispatcher_send(hass, status.SIGNAL_CHANGED, "instellingen")


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    auto_update.async_unschedule(hass)
    auto_update.async_teardown_visibility(hass)
    status.async_teardown(hass)
    remote.async_teardown(hass)
    desktop.async_unload(hass)
    app_download.async_unload(hass)
    # v1.33.1: services weg, anders werken ze verder met de oude instellingen
    for service in ("run_updates", "send_status"):
        hass.services.async_remove(DOMAIN, service)
    return True


async def async_remove_entry(hass: HomeAssistant, entry) -> None:
    """v1.33.0: integratie verwijderd, niets achterlaten."""
    from homeassistant.helpers.storage import Store
    from .config_flow import CUSTOMER_LOGO_DIR, _remove_customer_logo

    def _cleanup() -> None:
        _remove_customer_logo(hass)
        folder = pathlib.Path(hass.config.path(CUSTOMER_LOGO_DIR))
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError as err:
            _LOGGER.warning("BT: map %s niet verwijderd: %s", folder, err)

    await hass.async_add_executor_job(_cleanup)
    # v1.33.1: via de Store van de tracker zelf, zodat een geplande bewaring
    # het bestand niet opnieuw aanmaakt; tracker weg voor een latere herinstallatie
    tracker = hass.data.pop(auto_update._DATA_TRACKER, None)  # noqa: SLF001
    await (tracker._store if tracker else Store(hass, 1, f"{DOMAIN}.auto_update")).async_remove()  # noqa: SLF001
    await remote.async_remove(hass)
    await desktop.async_remove(hass)
    health_store = _health(hass).get("store")
    hass.data.pop(_HEALTH_KEY, None)
    await (health_store or Store(hass, 1, _HEALTH_STORE)).async_remove()
    ir.async_delete_issue(hass, DOMAIN, _ISSUE_ID)
