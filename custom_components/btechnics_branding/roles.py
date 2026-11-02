"""Rollen per gebruiker en zichtbaarheid van dashboards per rol (v1.49.0).

Keuze Matthias 30/10/2026: gebruikersbeheer met rollen gebeurt vanuit de Work-app
(module IOT). De rollen wonen in Btechnics IOT; Btechnics VTO en VIGI lezen ze hier.

Rollen:
- superadmin: beheerder in Home Assistant (groep system-admin). Niet opgeslagen,
  afgeleid uit HA zelf. Ziet alles.
- admin, medewerker: gewone HA-gebruiker plus deze rol.
- gebruiker: gewone HA-gebruiker zonder rol.

Opslag: .storage/btechnics_roles, zelfde vorm als Btechnics VTO v0.12.1 gebruikte:
  {"admin": [user_id, ...], "medewerker": [user_id, ...],
   "dashboards": {url_path: ["admin", "medewerker", "gebruiker"], ...}}
Ook in hass.data["btechnics_roles"] (dezelfde dict), en bij elke wijziging het
event "btechnics_roles_changed".

Dashboards: enkel de dashboards die in "dashboards" staan, worden beheerd. Voor elke
gewone gebruiker worden die in de zijbalk getoond of verborgen volgens zijn rol
(frontend user data "sidebar" -> hiddenPanels, zie frontend/storage.py en ha-sidebar;
de zijbalk volgt dat live). Superadmin ziet altijd alles. Andere verborgen panelen en
de volgorde van de gebruiker blijven zoals ze zijn.

LET OP: verbergen in de zijbalk is geen beveiliging. Wie de link kent, opent het
dashboard toch, en een gewone gebruiker kan alle entiteitsstanden lezen
(github.com/orgs/home-assistant/discussions/1171). Echte rechten (camerabeelden,
codes, deur) moeten de koppelingen zelf nakijken met role().

v1.50.0 (keuze Matthias 1/11/2026):
- leesbare titels voor de standaardpanelen (vertaling uit de HA-frontend zelf);
- "Alleen beheerders" (require_admin) per dashboard vanuit de Work-app, via de
  lovelace-dashboardcollectie van HA (enkel dashboards die in HA aangemaakt zijn);
- standaarddashboard per rol: frontend user data "core" -> default_panel (zoals
  ha-pick-dashboard-row in de frontend). De rol wint bij elke wijziging van rol of
  instelling; daarna mag de gebruiker zelf een ander kiezen ("standaard_gezet");
- elke rolwijziging komt in het logboek naar de Work-app, en een wijziging in HA
  zelf geeft ook een melding;
- zet een gewone gebruiker onze verborgen panelen zelf terug (Zijbalk bewerken),
  dan zetten we ze opnieuw verborgen (abonnement op de frontend user data);
- websocket btechnics_branding/my_role: de eigen rol, voor de profielpagina.
"""
from __future__ import annotations

import contextvars
import inspect
import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

KEY = "btechnics_roles"
EVENT = "btechnics_roles_changed"
SUPER, ADMIN, MEDEWERKER, USER = "superadmin", "admin", "medewerker", "gebruiker"
ROLES = (SUPER, ADMIN, MEDEWERKER, USER)
STORED = (ADMIN, MEDEWERKER)
DASH_ROLES = (ADMIN, MEDEWERKER, USER)  # superadmin ziet altijd alles
LABEL = {SUPER: "Superadmin", ADMIN: "Admin", MEDEWERKER: "Medewerker", USER: "Gebruiker"}
_STORE = "btechnics_branding_roles_store"
_LISTENING = "btechnics_branding_roles_listening"
_LOCK = "btechnics_branding_roles_lock"
_SNAP = "btechnics_branding_roles_snapshot"
_SUBS = "btechnics_branding_roles_sidebar_subs"
_TITLES = "btechnics_branding_roles_titles"
_PENDING = "btechnics_branding_roles_work_pending"  # user_ids met een lopende opdracht van Work
_NEW = "btechnics_branding_roles_new_users"
# Review 2 (1.50.0): zoals Instellingen > Dashboards in de frontend. Enkel deze ingebouwde
# panelen en dashboards uit de UI mogen "Alleen beheerders" wijzigen; een add-onpaneel
# (Terminal, File editor) of HACS mag nooit voor gewone gebruikers open.
_EDITABLE_BUILTIN = ("home", "light", "security", "climate", "energy", "maintenance")
# v1.50.0: komt een wijziging uit een opdracht van de Work-app? (users.py zet dit)
BRON: contextvars.ContextVar[str] = contextvars.ContextVar("btechnics_roles_bron", default="HA")
# Terugval als de vertaling van de frontend niet te lezen is (zelfde woorden als
# panel.* in hass_frontend/static/translations/nl-*.json, HA 2026.10)
_TITLES_NL = {
    "energy": "Energie", "calendar": "Agenda", "map": "Kaart", "logbook": "Activiteit",
    "history": "Geschiedenis", "todo": "Takenlijsten", "media_browser": "Media",
    "config": "Instellingen", "profile": "Profiel", "states": "Overzicht", "apps": "Apps",
    "light": "Verlichting", "security": "Beveiliging", "climate": "Klimaat", "home": "Thuis",
    "maintenance": "Onderhoud",
}


def _lock(hass: HomeAssistant):
    """v1.49.0 (review 2): een lock rond elke lees-wijzig-schrijf van de rollen.
    De listeners op user_added/user_updated lopen anders mee met de opdracht zelf
    en de laatste schrijver won (rol stil kwijt, verborgen uit sync)."""
    import asyncio
    if (lk := hass.data.get(_LOCK)) is None:
        lk = hass.data[_LOCK] = asyncio.Lock()
    return lk


def _store(hass: HomeAssistant) -> Store:
    if (s := hass.data.get(_STORE)) is None:
        s = hass.data[_STORE] = Store(hass, 1, KEY)
    return s


def _lst(v: Any) -> list:
    return v if isinstance(v, list) else []


def _clean(data: Any) -> dict:
    data = data if isinstance(data, dict) else {}
    out: dict[str, Any] = {r: sorted({str(x) for x in _lst(data.get(r)) if isinstance(x, str) and x})
                           for r in STORED}
    out[MEDEWERKER] = [x for x in out[MEDEWERKER] if x not in out[ADMIN]]
    dash = data.get("dashboards") if isinstance(data.get("dashboards"), dict) else {}
    out["dashboards"] = {str(k): sorted({r for r in v if isinstance(r, str) and r in DASH_ROLES})
                         for k, v in dash.items() if isinstance(v, list)}
    # v1.49.0 (review): per gebruiker welke panelen WIJ verborgen. Enkel die zetten we
    # terug; wat de gebruiker zelf verborg, blijft van hem.
    hid = data.get("verborgen") if isinstance(data.get("verborgen"), dict) else {}
    out["verborgen"] = {str(k): sorted({str(p) for p in v if isinstance(p, str)})
                        for k, v in hid.items() if isinstance(v, list) and v}
    # v1.50.0: standaarddashboard per rol, en per gebruiker wat WIJ het laatst zetten
    std = data.get("standaard") if isinstance(data.get("standaard"), dict) else {}
    out["standaard"] = {r: str(v) for r, v in std.items() if r in DASH_ROLES and isinstance(v, str) and v}
    gez = data.get("standaard_gezet") if isinstance(data.get("standaard_gezet"), dict) else {}
    out["standaard_gezet"] = {str(k): str(v) for k, v in gez.items() if isinstance(v, str) and v}
    return out


_BROKEN = "btechnics_branding_roles_broken"


async def async_load(hass: HomeAssistant) -> dict:
    if KEY not in hass.data:
        try:
            raw = _clean(await _store(hass).async_load())
        except Exception as err:  # noqa: BLE001
            # v1.49.0 (review): een onleesbaar bestand mag Btechnics IOT niet stilleggen,
            # en mag ook niet overschreven worden (dan zijn de rollen weg).
            _LOGGER.error("BT rollen: .storage/%s onleesbaar, rollen staan uit: %s", KEY, err)
            hass.data[_BROKEN] = str(err)[:200]
            raw = None
        hass.data[KEY] = raw if raw is not None else _clean(None)
    return hass.data[KEY]


def is_admin_group(user) -> bool:
    """In de beheerdersgroep, ook als de gebruiker uitgeschakeld is (is_admin is dan False)."""
    from homeassistant.auth.const import GROUP_ID_ADMIN
    return bool(getattr(user, "is_owner", False)) or any(g.id == GROUP_ID_ADMIN for g in user.groups)


async def _async_save(hass: HomeAssistant, data: dict) -> dict:
    if hass.data.get(_BROKEN):
        raise ValueError("rollenopslag op deze HA is onleesbaar, niets gewijzigd: " + hass.data[_BROKEN])
    data = _clean(data)
    await _store(hass).async_save(data)
    cur = hass.data.get(KEY)
    if isinstance(cur, dict):
        # Zelfde dict-object houden: wie een verwijzing bewaarde, ziet de nieuwe stand
        cur.clear()
        cur.update(data)
        data = cur
    hass.data[KEY] = data
    hass.bus.async_fire(EVENT, {})
    return data


def role(hass: HomeAssistant, user) -> str:
    """Rol van een HA-gebruiker (object met is_admin en id). Voor VTO, VIGI en de status."""
    if user is None:
        return USER
    if getattr(user, "is_admin", False) or (hasattr(user, "groups") and is_admin_group(user)):
        return SUPER  # review 2: ook een uitgeschakelde beheerder blijft superadmin
    data = hass.data.get(KEY) or {}
    uid = getattr(user, "id", None)
    if uid in data.get(ADMIN, []):
        return ADMIN
    if uid in data.get(MEDEWERKER, []):
        return MEDEWERKER
    return USER


async def async_store_role(hass: HomeAssistant, user_id: str, new_role: str) -> None:
    """Enkel de opgeslagen rol (admin/medewerker/geen). Superadmin regelt users.py via de HA-groep."""
    async with _lock(hass):
        await _store_role(hass, user_id, new_role)


async def _store_role(hass: HomeAssistant, user_id: str, new_role: str) -> None:
    data = dict(await async_load(hass))
    for r in STORED:
        data[r] = [x for x in data.get(r, []) if x != user_id]
    if new_role in STORED:
        data[new_role] = data[new_role] + [user_id]
    await _async_save(hass, data)


async def async_forget_user(hass: HomeAssistant, user_id: str, removed: bool = False) -> None:
    async with _lock(hass):
        await _forget_user(hass, user_id, removed)


async def _forget_user(hass: HomeAssistant, user_id: str, removed: bool = False) -> None:
    data = await async_load(hass)
    if removed:
        (hass.data.get(_SNAP) or {}).pop(user_id, None)
        (hass.data.get(_NEW) or {}).pop(user_id, None)
        if (unsub := (hass.data.get(_SUBS) or {}).pop(user_id, None)) is not None:
            try:
                unsub[1]()
            except Exception:  # noqa: BLE001
                pass
    if any(user_id in data.get(r, []) for r in STORED) or (removed and (
            user_id in data.get("verborgen", {}) or user_id in data.get("standaard_gezet", {}))):
        new = dict(data)
        for r in STORED:
            new[r] = [x for x in data.get(r, []) if x != user_id]
        if removed:
            new["verborgen"] = {k: v for k, v in data.get("verborgen", {}).items() if k != user_id}
            new["standaard_gezet"] = {k: v for k, v in data.get("standaard_gezet", {}).items() if k != user_id}
        await _async_save(hass, new)


def _title(hass: HomeAssistant, title: str) -> str:
    """v1.50.0: standaardpanelen hebben een vertaalsleutel als titel (energy, history,
    ...). De frontend toont panel.<titel> (frontend src/data/panel.ts); wij ook."""
    return (hass.data.get(_TITLES) or _TITLES_NL).get(title, title)


async def async_load_titles(hass: HomeAssistant) -> None:
    """Nederlandse paneeltitels uit de frontend van deze HA (hass_frontend), eenmalig."""
    if _TITLES in hass.data:
        return

    def _read() -> dict[str, str]:
        import glob
        import json
        import os

        import hass_frontend
        root = os.path.join(os.path.dirname(hass_frontend.__file__), "static", "translations")
        files = sorted(glob.glob(os.path.join(root, "nl-*.json"))) or sorted(glob.glob(os.path.join(root, "nl.json")))
        if not files:
            return {}
        with open(files[0], encoding="utf-8") as fh:
            raw = json.load(fh)
        res = raw.get("resources", raw) if isinstance(raw, dict) else {}
        return {k[6:]: str(v)[:80] for k, v in res.items()
                if isinstance(k, str) and k.startswith("panel.") and isinstance(v, str) and v}

    try:
        found = await hass.async_add_executor_job(_read)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("BT rollen: paneeltitels niet gelezen: %s", err)
        found = {}
    hass.data[_TITLES] = {**_TITLES_NL, **found}


def _dashboard_collection(hass: HomeAssistant):
    """De lovelace-dashboardcollectie van HA (helpers/collection.py, DashboardsCollection).

    HA bewaart ze niet in hass.data; enkel de websocket lovelace/dashboards/update
    (DashboardsCollectionWebSocket, lovelace/__init__.py) houdt ze vast. Dezelfde weg als
    Instellingen > Dashboards > "Alleen beheerders": update_item met require_admin.
    """
    handlers = hass.data.get("websocket_api") or {}
    entry = handlers.get("lovelace/dashboards/update")
    fn = inspect.unwrap(entry[0]) if entry else None
    coll = getattr(getattr(fn, "__self__", None), "storage_collection", None)
    if coll is None or not hasattr(coll, "async_update_item") or not isinstance(getattr(coll, "data", None), dict):
        raise ValueError("Alleen beheerders aanpassen lukt niet op deze HA-versie")
    return coll


def _storage_dashboards(hass: HomeAssistant) -> dict[str, str]:
    """url_path -> item_id van de dashboards die in HA zelf aangemaakt zijn (bewerkbaar)."""
    try:
        coll = _dashboard_collection(hass)
    except ValueError:
        return {}
    return {str(item.get("url_path")): str(item_id) for item_id, item in coll.data.items()
            if isinstance(item, dict) and item.get("url_path")}


def _override(hass: HomeAssistant, url_path: str) -> dict:
    """Paneelinstelling van HA zelf (Instellingen > Dashboards, frontend/update_panel):
    title, icon, require_admin, show_in_sidebar winnen van het paneel
    (frontend/__init__.py, DATA_PANELS_CONFIG, websocket_get_panels). Review 1.50.0."""
    ov = (hass.data.get("frontend_panels_config") or {}).get(url_path)
    return ov if isinstance(ov, dict) else {}


def _panel_info(hass: HomeAssistant, url_path: str, p) -> dict[str, Any]:
    ov = _override(hass, url_path)
    title = ov["title"] if ov.get("title") else _title(hass, str(getattr(p, "sidebar_title", "") or ""))
    return {"url_path": url_path, "title": str(title)[:80],
            "require_admin": bool(ov.get("require_admin", getattr(p, "require_admin", False))),
            "show": bool(ov.get("show_in_sidebar", getattr(p, "show_in_sidebar", True)))}


def _editable(hass: HomeAssistant, url_path: str, storage: dict | None = None) -> bool:
    return url_path in _EDITABLE_BUILTIN or url_path in (storage if storage is not None else _storage_dashboards(hass))


_NOT_MANAGED = ("config", "developer-tools", "profile", "notfound")


def _all_panels(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """v1.50.1: alle bestaande panelen met een titel, ook die in HA verborgen zijn in de
    zijbalk (paneelinstelling show_in_sidebar false). Voor de controle in set_dashboards:
    Work stuurt de volledige keuze uit de status mee, ook voor een paneel dat intussen
    verborgen is (energy op Trefpunt, 2/11)."""
    out: dict[str, dict[str, Any]] = {}
    for url_path, p in (hass.data.get("frontend_panels") or {}).items():
        if not getattr(p, "sidebar_title", None) or url_path in _NOT_MANAGED:
            continue
        info = _panel_info(hass, url_path, p)
        info.pop("show", None)
        out[url_path] = info
    return out


def panels(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Dashboards en andere panelen in de zijbalk, voor de keuze in de Work-app.

    v1.50.1 (review): ook een paneel dat in HA verborgen is (paneelinstelling
    show_in_sidebar false), zodra het in de beheerde keuze of als standaard staat. Zo
    kan Work het blijven tonen en meesturen. Veld in_zijbalk zegt of HA het toont."""
    data = hass.data.get(KEY) or {}
    ref = set((data.get("dashboards") or {}).keys()) | set((data.get("standaard") or {}).values())
    storage = _storage_dashboards(hass)
    out = []
    for url_path, p in (hass.data.get("frontend_panels") or {}).items():
        # Zonder titel toont HA een paneel nooit in de zijbalk (notfound, _my_redirect)
        if not getattr(p, "sidebar_title", None) or url_path in _NOT_MANAGED:
            continue
        info = _panel_info(hass, url_path, p)
        shown = info.pop("show")
        if not shown and url_path not in ref:
            continue
        info["bewerkbaar"] = _editable(hass, url_path, storage)  # v1.50.0: Alleen beheerders vanuit Work
        info["in_zijbalk"] = shown  # v1.50.1
        out.append(info)
    return sorted(out, key=lambda x: x["title"].lower())


def _check_standaard(standaard: dict, dashboards: dict, info: dict[str, dict], volledig: bool = True) -> None:
    """Een standaarddashboard moet bestaan, niet op Alleen beheerders staan en zichtbaar zijn
    voor zijn rol. volledig=False (set_dashboards): enkel de zichtbaarheid, zodat een
    intussen verwijderd of afgeschermd dashboard de rest niet blokkeert (review 1.50.0)."""
    for r, path in standaard.items():
        p = info.get(path)
        if p is None and volledig:
            raise ValueError(f"dashboard {str(path)[:60]} bestaat niet")
        if p is not None and volledig and p["require_admin"]:
            raise ValueError(f"{p['title']} staat op Alleen beheerders en kan geen standaard zijn voor {LABEL[r]}")
        # v1.50.1 (review 2): altijd, ook als het paneel er even niet is (kort na een herstart)
        if path in dashboards and r not in dashboards[path]:
            title = p["title"] if p is not None else str(path)[:60]
            raise ValueError(f"{title} is het standaarddashboard van {LABEL[r]} en moet voor die rol zichtbaar blijven")


async def async_set_dashboards(hass: HomeAssistant, mapping: Any) -> dict:
    """Vervang de volledige keuze: {url_path: [rollen die het zien]}. Leeg = niets beheren."""
    if not isinstance(mapping, dict):
        raise ValueError("dashboards moet een object zijn: {url_path: [rollen]}")
    for url_path, rs in mapping.items():
        if not isinstance(rs, list) or any(r not in DASH_ROLES for r in rs):
            raise ValueError(f"rollen voor {str(url_path)[:60]}: lijst met {', '.join(DASH_ROLES)}")
    async with _lock(hass):
        data = dict(await async_load(hass))
        info = _all_panels(hass)  # v1.50.1: ook in HA verborgen panelen
        known = data.get("dashboards") or {}
        clean: dict[str, list[str]] = {}
        for url_path, rs in mapping.items():
            # v1.50.1 (review): een sleutel die al beheerd werd, blijft aanvaard, ook als het
            # paneel intussen weg is (verwijderd, of nog niet geladen kort na een herstart)
            if url_path not in info and url_path not in known:
                raise ValueError(f"dashboard {str(url_path)[:60]} bestaat niet")
            clean[url_path] = sorted(set(rs))
        _check_standaard(data.get("standaard") or {}, clean, info, volledig=False)  # v1.50.0
        data["dashboards"] = clean
        await _async_save(hass, data)
    await async_apply_sidebars(hass)
    return {"dashboards": clean}


async def async_set_standaard(hass: HomeAssistant, mapping: Any) -> dict:
    """v1.50.0: standaarddashboard per rol, volledige keuze {rol: url_path}. {} = geen."""
    if not isinstance(mapping, dict):
        raise ValueError("standaard moet een object zijn: {rol: url_path}")
    clean: dict[str, str] = {}
    for r, path in mapping.items():
        if r not in DASH_ROLES:
            raise ValueError(f"rol moet {', '.join(DASH_ROLES)} zijn")
        if path in (None, ""):
            continue
        if not isinstance(path, str):
            raise ValueError(f"standaard voor {r}: url_path als tekst")
        clean[r] = path
    async with _lock(hass):
        info = _all_panels(hass)  # v1.50.1: ook in HA verborgen panelen (bv. home)
        data = dict(await async_load(hass))
        dash = data.get("dashboards") or {}
        oud = data.get("standaard") or {}
        # v1.50.1 (review): volledige controle enkel voor rollen die wijzigen; een
        # ongewijzigde standaard die intussen in HA veranderde, blokkeert de rest niet
        _check_standaard({r: p for r, p in clean.items() if oud.get(r) != p}, dash, info)
        _check_standaard({r: p for r, p in clean.items() if oud.get(r) == p}, dash, info, volledig=False)
        data["standaard"] = clean
        await _async_save(hass, data)
    await async_apply_sidebars(hass)
    return {"standaard": clean}


async def _system_default(hass: HomeAssistant) -> str:
    """Standaarddashboard van het systeem, zoals de frontend: systemData.default_panel || "home"."""
    try:
        from homeassistant.components.frontend.storage import async_system_store
        core = (await async_system_store(hass)).data.get("core")
        dp = core.get("default_panel") if isinstance(core, dict) else None
        return dp if isinstance(dp, str) and dp else "home"
    except Exception:  # noqa: BLE001
        return "home"


def _set_override(hass: HomeAssistant, url_path: str, value: bool) -> None:
    """Zelfde als HA's frontend/update_panel met require_admin (frontend/__init__.py)."""
    cfg = hass.data.get("frontend_panels_config")
    store = hass.data.get("frontend_panels_store")
    if not isinstance(cfg, dict) or store is None or not hasattr(store, "async_delay_save"):
        raise ValueError("Alleen beheerders aanpassen lukt niet op deze HA-versie")
    cfg[url_path] = {**(cfg.get(url_path) or {}), "require_admin": value}
    store.async_delay_save(lambda: hass.data["frontend_panels_config"], 10)  # PANELS_SAVE_DELAY
    hass.bus.async_fire("panels_updated")


async def async_set_require_admin(hass: HomeAssistant, url_path: Any, value: Any) -> dict:
    """v1.50.0: "Alleen beheerders" van een dashboard of paneel aan of uit, zoals in
    Instellingen > Dashboards: een dashboard uit de UI via zijn collectie, een ander
    paneel via de paneelinstelling (frontend/update_panel)."""
    if not isinstance(value, bool):
        raise ValueError("require_admin moet true of false zijn")
    if not isinstance(url_path, str) or not url_path:
        raise ValueError("url_path ontbreekt")
    raw = (hass.data.get("frontend_panels") or {}).get(url_path)
    if raw is None or url_path in _NOT_MANAGED:
        raise ValueError(f"dashboard {url_path[:60]} bestaat niet")
    title = _panel_info(hass, url_path, raw)["title"]
    storage = _storage_dashboards(hass)
    if not _editable(hass, url_path, storage):
        raise ValueError(f"Alleen beheerders kan voor {title} enkel in HA zelf, zoals in Instellingen > Dashboards")
    async with _lock(hass):
        data = await async_load(hass)
        if value:
            # HA's eigen scherm laat dit niet toe voor het standaarddashboard (isDefault)
            if url_path == await _system_default(hass):
                raise ValueError(f"{title} is het standaarddashboard van HA en kan niet op Alleen beheerders")
            if url_path in (data.get("standaard") or {}).values():
                raise ValueError(f"{title} is een standaarddashboard en kan niet op Alleen beheerders")
        item_id = storage.get(url_path)
        if item_id is not None:
            await _dashboard_collection(hass).async_update_item(item_id, {"require_admin": value})
            if "require_admin" in _override(hass, url_path):
                _set_override(hass, url_path, value)  # anders wint de paneelinstelling
        else:
            _set_override(hass, url_path, value)
    await async_apply_sidebars(hass)
    return {"url_path": url_path, "title": title, "require_admin": value, "name": title}


def _ensure_sidebar_sub(hass: HomeAssistant, user_id: str, store) -> None:
    """v1.50.0: zet de gebruiker via Zijbalk bewerken onze verborgen panelen terug, dan
    opnieuw verbergen. UserStore.async_subscribe("sidebar") (frontend/storage.py)."""
    subs = hass.data.setdefault(_SUBS, {})
    if (cur := subs.get(user_id)) is not None and cur[0] is store:
        return

    def _changed() -> None:
        from homeassistant.config_entries import ConfigEntryState
        if (subs.get(user_id) or (None,))[0] is not store:
            return
        if not any(e.state is ConfigEntryState.LOADED
                   for e in hass.config_entries.async_entries("btechnics_branding")):
            return

        async def _again() -> None:
            try:
                user = await hass.auth.async_get_user(user_id)
                if user is not None:
                    await async_apply_sidebar(hass, user)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("BT rollen: zijbalk niet opnieuw gezet: %s", err)

        hass.async_create_task(_again())

    subs[user_id] = (store, store.async_subscribe("sidebar", _changed))


def _note_role(hass: HomeAssistant, user, r: str) -> None:
    """v1.50.0: elke rolwijziging in het logboek (en in de Work-app); vanuit HA ook een melding."""
    snap = hass.data.setdefault(_SNAP, {})
    import time
    nieuw = hass.data.setdefault(_NEW, {})
    prev = snap.get(user.id)
    snap[user.id] = r
    if prev is None and r == USER:
        nieuw[user.id] = time.monotonic()  # net aangemaakt: de rol kan nog volgen
        return
    if prev == r:
        return
    sinds = nieuw.pop(user.id, None)
    if sinds is not None and time.monotonic() - sinds < 120:
        prev = None  # review 2: enkel kort na het aanmaken is het "nieuw"
    # Een andere taak (abonnement, listener) kan de wijziging eerst opmerken: daarom ook
    # kijken of er voor deze gebruiker net een opdracht van Work loopt (simulatie 1/11).
    bron = "Work" if BRON.get() == "Work" or user.id in (hass.data.get(_PENDING) or {}) else "HA"
    oud = LABEL.get(prev, "nieuw") if prev else "nieuw"
    msg = f"rol van {user.name}: {oud} → {LABEL[r]} ({'via Work' if bron == 'Work' else 'in HA'})"
    try:
        from . import auto_update
        auto_update._log(hass, msg)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        _LOGGER.info("BT rollen: %s", msg)
    if bron != "Work":
        from homeassistant.components import persistent_notification
        from homeassistant.util import dt as dt_util
        persistent_notification.async_create(
            hass, f"De rol van {user.name} is in Home Assistant gewijzigd: {oud} → {LABEL[r]}. "
                  f"Tijdstip: {dt_util.now().strftime('%d/%m/%Y %H:%M')}.",
            title="Btechnics IOT: rollen", notification_id=f"btechnics_roles_{user.id}",
        )
    try:
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .status import SIGNAL_CHANGED
        async_dispatcher_send(hass, SIGNAL_CHANGED, "rollen")
    except Exception:  # noqa: BLE001
        pass


async def async_apply_sidebar(hass: HomeAssistant, user) -> bool:
    """Zijbalk en standaarddashboard van een gebruiker volgens zijn rol. True als er iets veranderde.

    Wij verbergen per gebruiker een eigen lijst ("verborgen"). Daarbuiten raken we
    niets: zelf verborgen panelen en de volgorde blijven. Superadmin, een verwijderd
    dashboard uit de keuze of een ruimere rol: onze verborgen panelen komen terug.
    """
    from homeassistant.components.frontend.storage import async_user_store

    if user is None or user.system_generated:
        return False
    async with _lock(hass):
        # opnieuw ophalen binnen de lock: groep en rol kunnen net veranderd zijn
        fresh = await hass.auth.async_get_user(user.id)
        if fresh is None:
            return False
        try:
            changed = await _apply_sidebar(hass, fresh, async_user_store)
            changed = await _apply_standaard(hass, fresh, async_user_store) or changed
        finally:
            # review 1.50.0: ook als de zijbalk faalt, de rolwijziging nu loggen (juiste bron)
            _note_role(hass, fresh, SUPER if is_admin_group(fresh) else role(hass, fresh))
        return changed


async def _apply_standaard(hass: HomeAssistant, user, async_user_store) -> bool:
    """v1.50.0: frontend user data core.default_panel (ha-pick-dashboard-row). Enkel zetten
    als rol of keuze verschilt van wat wij het laatst zetten ("rol:pad"); anders blijft
    de eigen keuze van de gebruiker staan."""
    data = await async_load(hass)
    r = SUPER if is_admin_group(user) else role(hass, user)
    want = None if r == SUPER else (data.get("standaard") or {}).get(r)
    if want is not None:
        p = (hass.data.get("frontend_panels") or {}).get(want)
        if p is None or _panel_info(hass, want, p)["require_admin"]:
            return False  # weg of enkel voor beheerders: niets aanraken (review 1.50.0)
    gezet = (data.get("standaard_gezet") or {}).get(user.id)
    key = f"{r}:{want}" if want is not None else None
    if key == gezet:
        return False
    gezet_pad = gezet.split(":", 1)[1] if gezet and ":" in gezet else gezet
    store = await async_user_store(hass, user.id)
    core = store.data.get("core") if isinstance(store.data.get("core"), dict) else {}
    changed = False
    if want is not None:
        if core.get("default_panel") != want:
            await store.async_set_item("core", {**core, "default_panel": want})
            changed = True
    elif gezet_pad and core.get("default_panel") == gezet_pad:
        # Niet meer beheerd: onze keuze weg, terug naar de standaard van het systeem
        await store.async_set_item("core", {k: v for k, v in core.items() if k != "default_panel"})
        changed = True
    cur = await async_load(hass)
    gez = dict(cur.get("standaard_gezet") or {})
    if key is None:
        gez.pop(user.id, None)
    else:
        gez[user.id] = key
    await _async_save(hass, {**cur, "standaard_gezet": gez})
    return changed


async def _apply_sidebar(hass: HomeAssistant, user, async_user_store) -> bool:
    data = await async_load(hass)
    managed = data.get("dashboards") or {}
    ours_prev = list((data.get("verborgen") or {}).get(user.id, []))
    r = SUPER if is_admin_group(user) else role(hass, user)
    ours_new = [] if r == SUPER else sorted(p for p, rs in managed.items() if r not in rs)
    if not ours_prev and not ours_new:
        return False
    store = await async_user_store(hass, user.id)
    if ours_new:
        _ensure_sidebar_sub(hass, user.id, store)
    current = store.data.get("sidebar") if isinstance(store.data.get("sidebar"), dict) else {}
    hidden_now = [p for p in current.get("hiddenPanels") or [] if isinstance(p, str)]
    keep = [p for p in hidden_now if p not in ours_prev and p not in ours_new]
    hidden = keep + ours_new
    changed = sorted(hidden) != sorted(hidden_now) or "hiddenPanels" not in current

    async def _save_ours(panels_: list[str]) -> None:
        cur = await async_load(hass)
        verborgen = dict(cur.get("verborgen") or {})
        if panels_:
            verborgen[user.id] = sorted(panels_)
        else:
            verborgen.pop(user.id, None)
        if verborgen != (cur.get("verborgen") or {}):
            await _async_save(hass, {**cur, "verborgen": verborgen})

    # review 2: eerst registreren wat we gaan verbergen (ook de vorige), dan de zijbalk,
    # dan de definitieve lijst. Faalt een stap, dan staat nooit een paneel verborgen
    # zonder dat wij weten dat het van ons is.
    if changed:
        await _save_ours(sorted(set(ours_prev) | set(ours_new)))
        new = {**current, "panelOrder": list(current.get("panelOrder") or []), "hiddenPanels": hidden}
        await store.async_set_item("sidebar", new)
    await _save_ours(ours_new)
    return changed


async def async_apply_sidebars(hass: HomeAssistant) -> int:
    n = 0
    for user in await hass.auth.async_get_users():
        if user.system_generated:
            continue
        try:
            n += await async_apply_sidebar(hass, user)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("BT rollen: zijbalk van %s niet aangepast: %s", user.name, err)
    return n


async def async_status(hass: HomeAssistant) -> dict[str, Any]:
    data = await async_load(hass)
    return {"dashboards": dict(data.get("dashboards") or {}), "panels": panels(hass),
            "standaard": dict(data.get("standaard") or {}),  # v1.50.0
            "rollen": list(ROLES), "fout": hass.data.get(_BROKEN)}


async def async_setup(hass: HomeAssistant) -> None:
    """Rollen laden, service voor andere koppelingen, zijbalken nazetten na de start."""
    if hass.data.pop(_BROKEN, None):
        hass.data.pop(KEY, None)  # review 2: bij herladen opnieuw proberen
    await async_load(hass)
    await async_load_titles(hass)  # v1.50.0
    # v1.50.0: huidige rollen onthouden, zodat enkel echte wijzigingen gelogd worden
    snap = hass.data.setdefault(_SNAP, {})
    for u in await hass.auth.async_get_users():
        if not u.system_generated and u.id not in snap:
            snap[u.id] = SUPER if is_admin_group(u) else role(hass, u)
    _register_ws(hass)

    async def _get_roles(call: ServiceCall) -> ServiceResponse:
        if call.context.user_id:
            caller = await hass.auth.async_get_user(call.context.user_id)
            if caller is None or not caller.is_admin:
                raise Unauthorized()
        users = [u for u in await hass.auth.async_get_users() if not u.system_generated]
        return {"users": [{"user_id": u.id, "name": u.name, "active": u.is_active,
                           "role": role(hass, u)} for u in users],
                "dashboards": dict((await async_load(hass)).get("dashboards") or {})}

    if not hass.services.has_service("btechnics_branding", "get_roles"):
        hass.services.async_register("btechnics_branding", "get_roles", _get_roles,
                                     supports_response=SupportsResponse.ONLY)

    async def _apply(_evt=None) -> None:
        try:
            await async_apply_sidebars(hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("BT rollen: zijbalken niet nagezet: %s", err)

    if hass.is_running:
        hass.async_create_task(_apply())
    else:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _apply)

    # v1.49.0 (review): ook bij aanmaken, wijzigen of verwijderen in HA zelf
    if not hass.data.get(_LISTENING):
        hass.data[_LISTENING] = True

        async def _user_event(evt) -> None:
            from homeassistant.config_entries import ConfigEntryState
            if not any(e.state is ConfigEntryState.LOADED
                       for e in hass.config_entries.async_entries("btechnics_branding")):
                return  # review 2: integratie verwijderd of uitgeschakeld
            uid = evt.data.get("user_id")
            try:
                if evt.event_type == "user_removed":
                    await async_forget_user(hass, uid, removed=True)
                    return
                user = await hass.auth.async_get_user(uid)
                if user is not None and is_admin_group(user):
                    await async_forget_user(hass, uid)
                await async_apply_sidebar(hass, user)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("BT rollen: na %s niet bijgewerkt: %s", evt.event_type, err)

        for name in ("user_added", "user_updated", "user_removed"):
            hass.bus.async_listen(name, _user_event)


def work_begin(hass: HomeAssistant, user_id: Any) -> None:
    if isinstance(user_id, str) and user_id:
        pend = hass.data.setdefault(_PENDING, {})
        pend[user_id] = pend.get(user_id, 0) + 1


def work_end(hass: HomeAssistant, user_id: Any) -> None:
    pend = hass.data.get(_PENDING) or {}
    if isinstance(user_id, str) and user_id in pend:
        pend[user_id] -= 1
        if pend[user_id] <= 0:
            pend.pop(user_id, None)


def _register_ws(hass: HomeAssistant) -> None:
    """v1.50.0: btechnics_branding/my_role, voor elke aangemelde gebruiker zijn eigen rol."""
    from homeassistant.components import websocket_api
    import voluptuous as vol

    @websocket_api.websocket_command({vol.Required("type"): "btechnics_branding/my_role"})
    @websocket_api.async_response
    async def _my_role(hass_: HomeAssistant, connection, msg: dict) -> None:
        user = connection.user
        r = SUPER if user is not None and is_admin_group(user) else role(hass_, user)
        # review 1.50.0: enkel vast als er dashboards per rol beheerd worden
        beheerd = bool((hass_.data.get(KEY) or {}).get("dashboards"))
        connection.send_result(msg["id"], {"role": r, "label": LABEL[r],
                                           "zijbalk_vast": r != SUPER and beheerd})

    websocket_api.async_register_command(hass, _my_role)
