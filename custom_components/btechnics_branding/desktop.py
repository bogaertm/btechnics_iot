"""Btechnics IOT desktop-apps (Mac en Windows) in de status (v1.35.0).

Twee bronnen, in deze volgorde:

Fase 1, toegangstokens. De wizard van de desktop-app laat de klant een
langlevend toegangstoken aanmaken met "Btechnics IOT" in de naam. Elk gebruikt
token wordt een regel (bron "token"). Het token zelf of een hash gaat nooit mee.
Beperking: hetzelfde token op twee computers telt als een.

Let op: HA noteert het gebruik van een token enkel wanneer er een toegangstoken
van gemaakt wordt (auth/__init__.py async_create_access_token). Bij een langlevend
token is dat een keer, bij het aanmaken; later gebruik werkt last_used_at niet
bij. Daarom kijkt deze integratie mee bij hass.auth.async_validate_access_token
(HTTP en WebSocket) en noteert zelf wanneer een "Btechnics IOT" token gebruikt
wordt. Enkel lezen, nooit iets tegenhouden. Het IP-adres is daar niet gekend,
dus laatste_ip blijft leeg tenzij HA het zelf kent.

Fase 2, aanmelding door de app (vanaf app-versie 3.8.0) via de service
btechnics_branding.register_desktop_app, bij het opstarten en elk uur. Per
app_id worden de laatste waarden bewaard (bron "app"), 30 dagen zonder
aanmelding en ze worden vergeten.

Dubbel tellen: een service-oproep draagt enkel de gebruiker mee, niet het token
(HA core.py Context: id, user_id, parent_id). Heeft die gebruiker precies een
"Btechnics IOT" token, dan valt die token-regel weg; heeft hij er meer, dan
blijven ze allemaal staan.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

DOMAIN = "btechnics_branding"
SERVICE = "register_desktop_app"
TOKEN_NAME = "btechnics iot"
_KEEP = timedelta(days=30)
_MAX_APPS = 50
_DATA = "btechnics_branding_desktop"

_TEXT = re.compile(r"^[^<>\x00-\x1f]{1,64}$")
_SHORT = re.compile(r"^[A-Za-z0-9._+\-() ]{1,32}$")

SCHEMA = vol.Schema({
    vol.Required("app_id"): vol.All(str, vol.Match(r"^[A-Za-z0-9-]{8,64}$")),
    vol.Required("naam"): vol.All(str, vol.Match(_TEXT)),
    vol.Required("app_versie"): vol.All(str, vol.Match(_SHORT)),
    vol.Required("platform"): vol.In(["macos", "windows"]),
    vol.Optional("os_versie"): vol.All(str, vol.Match(_SHORT)),
    vol.Optional("architectuur"): vol.All(str, vol.Match(_SHORT)),
})


def _state(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(_DATA, {"store": None, "apps": {}, "seen": {}, "orig": None})


def _save(hass: HomeAssistant) -> None:
    st = _state(hass)
    if st["store"]:
        st["store"].async_delay_save(lambda: {"apps": st["apps"], "seen": st["seen"]}, 30)


def _watch_tokens(hass: HomeAssistant) -> None:
    """Gebruik van "Btechnics IOT" tokens noteren (HA doet dat zelf niet voor langlevende tokens)."""
    st = _state(hass)
    auth = hass.auth
    orig = auth.async_validate_access_token
    if getattr(orig, "_bt_desktop", False):
        return
    st["orig"] = orig

    def wrapped(token):
        refresh_token = orig(token)
        try:
            if (refresh_token is not None
                    and refresh_token.token_type == "long_lived_access_token"
                    and TOKEN_NAME in (refresh_token.client_name or "").casefold()):
                now = dt_util.utcnow()
                last = st["seen"].get(refresh_token.id)
                # hoogstens een keer per minuut bijwerken
                if last is None or (now - dt_util.parse_datetime(last)).total_seconds() > 60:
                    st["seen"][refresh_token.id] = now.isoformat()
                    _save(hass)
        except Exception:  # noqa: BLE001
            pass
        return refresh_token

    wrapped._bt_desktop = True  # type: ignore[attr-defined]
    try:
        auth.async_validate_access_token = wrapped
        st["wrapper"] = wrapped
    except Exception:  # noqa: BLE001  (bv. een latere HA met __slots__)
        st["orig"] = None


def _unwatch_tokens(hass: HomeAssistant) -> None:
    st = hass.data.get(_DATA) or {}
    # Enkel terugzetten als onze wrapper er nog bovenop zit (een andere integratie
    # kan er intussen zelf een rond gezet hebben)
    if st.get("orig") is not None and hass.auth.async_validate_access_token is st.get("wrapper"):
        hass.auth.async_validate_access_token = st["orig"]
        st["orig"] = None
        st["wrapper"] = None


def _prune(apps: dict) -> dict:
    grens = dt_util.utcnow() - _KEEP
    keep = {}
    for app_id, rec in apps.items():
        seen = dt_util.parse_datetime(str(rec.get("laatst_gezien") or ""))
        if seen is not None and seen >= grens:
            keep[app_id] = rec
    # hoogstens _MAX_APPS, de recentste
    items = sorted(keep.items(), key=lambda kv: kv[1].get("laatst_gezien") or "")
    return dict(items[-_MAX_APPS:])


def _token_rows(user, seen: dict) -> list[tuple[Any, dict]]:
    rows = []
    for token in user.refresh_tokens.values():
        if token.token_type != "long_lived_access_token":
            continue
        name = token.client_name or ""
        if TOKEN_NAME not in name.casefold():
            continue
        # Laatste gebruik: wat wij zagen, of wat HA zelf kent met een IP-adres.
        # Het "gebruik" dat HA bij het aanmaken noteert (zonder IP) telt niet.
        times = []
        if seen.get(token.id):
            times.append(dt_util.parse_datetime(seen[token.id]))
        if token.last_used_at is not None and token.last_used_ip is not None:
            times.append(token.last_used_at)
        times = [t for t in times if t is not None]
        if not times:
            continue  # nooit gebruikt
        rows.append((token, {
            "id": "token:" + token.id[:12],
            "bron": "token",
            "naam": name[:64],
            "laatst_gezien": max(times).isoformat(),
            "laatste_ip": token.last_used_ip,
            "app_versie": None, "platform": None, "os_versie": None, "architectuur": None,
        }))
    return rows


async def async_list(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Alle desktop-apps: aanmeldingen van de app plus tokens die niet gekoppeld zijn."""
    st = _state(hass)
    st["apps"] = _prune(st["apps"])
    out: list[dict[str, Any]] = []
    users_with_app = {rec.get("user_id") for rec in st["apps"].values()}
    all_users = await hass.auth.async_get_users()
    existing = {t.id for u in all_users for t in u.refresh_tokens.values()}
    st["seen"] = {k: v for k, v in st["seen"].items() if k in existing}  # verwijderde tokens vergeten
    for user in all_users:
        rows = _token_rows(user, st["seen"])
        # Precies een gebruikt Btechnics IOT token en de app van die gebruiker meldt
        # zich aan: zelfde computer. Ongebruikte tokens tellen niet mee.
        if user.id in users_with_app and len(rows) == 1:
            continue
        out.extend(row for _t, row in rows)
    for app_id, rec in st["apps"].items():
        out.append({
            "id": "app:" + app_id,
            "bron": "app",
            "naam": rec.get("naam"),
            "laatst_gezien": rec.get("laatst_gezien"),
            "laatste_ip": None,
            "app_versie": rec.get("app_versie"),
            "platform": rec.get("platform"),
            "os_versie": rec.get("os_versie"),
            "architectuur": rec.get("architectuur"),
        })
    out.sort(key=lambda r: r.get("laatst_gezien") or "", reverse=True)
    return out


async def async_setup(hass: HomeAssistant) -> None:
    st = _state(hass)
    if st["store"] is None:
        st["store"] = Store(hass, 1, f"{DOMAIN}.desktop_apps")
        data = await st["store"].async_load() or {}
        st["apps"] = _prune(data.get("apps", {}) if isinstance(data, dict) else {})
        st["seen"] = dict(data.get("seen", {})) if isinstance(data, dict) else {}
    _watch_tokens(hass)

    if hass.services.has_service(DOMAIN, SERVICE):
        return

    async def _register(call: ServiceCall) -> None:
        user_id = call.context.user_id
        if not user_id:
            raise HomeAssistantError("enkel door een aangemelde gebruiker (de desktop-app)")
        st = _state(hass)
        app_id = call.data["app_id"]
        old = st["apps"].get(app_id)
        naam = call.data["naam"].strip()
        if not naam:
            raise HomeAssistantError("naam is leeg")
        if old is not None and old.get("user_id") != user_id:
            raise HomeAssistantError("deze app_id hoort bij een andere gebruiker")
        if old is None and sum(1 for r in st["apps"].values() if r.get("user_id") == user_id) >= 5:
            raise HomeAssistantError("hoogstens 5 desktop-apps per gebruiker")
        rec = {
            "naam": naam,
            "app_versie": call.data["app_versie"],
            "platform": call.data["platform"],
            "os_versie": call.data.get("os_versie"),
            "architectuur": call.data.get("architectuur"),
            "user_id": user_id,
            "laatst_gezien": dt_util.utcnow().isoformat(),
        }
        apps = dict(st["apps"])
        apps.pop(app_id, None)
        apps[app_id] = rec
        st["apps"] = _prune(apps)
        _save(hass)
        # Nieuwe app of andere versie: meteen melden aan Btechnics; een gewone
        # uurlijkse aanmelding zonder wijziging stuurt geen extra bericht.
        if old is None or old.get("app_versie") != rec["app_versie"]:
            async_dispatcher_send(hass, f"{DOMAIN}_status_changed", "desktop_app")

    hass.services.async_register(DOMAIN, SERVICE, _register, schema=SCHEMA)


def async_unload(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE)
    _unwatch_tokens(hass)


async def async_remove(hass: HomeAssistant) -> None:
    _unwatch_tokens(hass)
    st = hass.data.pop(_DATA, None)
    store = (st or {}).get("store") or Store(hass, 1, f"{DOMAIN}.desktop_apps")
    await store.async_remove()
