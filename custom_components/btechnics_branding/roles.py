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
"""
from __future__ import annotations

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
    if any(user_id in data.get(r, []) for r in STORED) or (removed and user_id in data.get("verborgen", {})):
        new = dict(data)
        for r in STORED:
            new[r] = [x for x in data.get(r, []) if x != user_id]
        if removed:
            new["verborgen"] = {k: v for k, v in data.get("verborgen", {}).items() if k != user_id}
        await _async_save(hass, new)


def panels(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Dashboards en andere panelen in de zijbalk, voor de keuze in de Work-app."""
    out = []
    for url_path, p in (hass.data.get("frontend_panels") or {}).items():
        title = getattr(p, "sidebar_title", None)
        # Zonder titel toont HA een paneel nooit in de zijbalk (notfound, _my_redirect)
        if not title or not getattr(p, "show_in_sidebar", True) or url_path in ("config", "developer-tools", "profile"):
            continue
        out.append({"url_path": url_path, "title": str(title)[:80],
                    "require_admin": bool(getattr(p, "require_admin", False))})
    return sorted(out, key=lambda x: x["title"].lower())


async def async_set_dashboards(hass: HomeAssistant, mapping: Any) -> dict:
    """Vervang de volledige keuze: {url_path: [rollen die het zien]}. Leeg = niets beheren."""
    if not isinstance(mapping, dict):
        raise ValueError("dashboards moet een object zijn: {url_path: [rollen]}")
    known = {p["url_path"] for p in panels(hass)}
    clean: dict[str, list[str]] = {}
    for url_path, rs in mapping.items():
        if url_path not in known:
            raise ValueError(f"dashboard {str(url_path)[:60]} bestaat niet")
        if not isinstance(rs, list) or any(r not in DASH_ROLES for r in rs):
            raise ValueError(f"rollen voor {url_path}: lijst met {', '.join(DASH_ROLES)}")
        clean[url_path] = sorted(set(rs))
    async with _lock(hass):
        data = dict(await async_load(hass))
        data["dashboards"] = clean
        await _async_save(hass, data)
    await async_apply_sidebars(hass)
    return {"dashboards": clean}


async def async_apply_sidebar(hass: HomeAssistant, user) -> bool:
    """Zijbalk van een gebruiker volgens zijn rol. True als er iets veranderde.

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
        return await _apply_sidebar(hass, fresh, async_user_store)


async def _apply_sidebar(hass: HomeAssistant, user, async_user_store) -> bool:
    data = await async_load(hass)
    managed = data.get("dashboards") or {}
    ours_prev = list((data.get("verborgen") or {}).get(user.id, []))
    r = SUPER if is_admin_group(user) else role(hass, user)
    ours_new = [] if r == SUPER else sorted(p for p, rs in managed.items() if r not in rs)
    if not ours_prev and not ours_new:
        return False
    store = await async_user_store(hass, user.id)
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
        new = {"panelOrder": list(current.get("panelOrder") or []), "hiddenPanels": hidden}
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
            "rollen": list(ROLES), "fout": hass.data.get(_BROKEN)}


async def async_setup(hass: HomeAssistant) -> None:
    """Rollen laden, service voor andere koppelingen, zijbalken nazetten na de start."""
    if hass.data.pop(_BROKEN, None):
        hass.data.pop(KEY, None)  # review 2: bij herladen opnieuw proberen
    await async_load(hass)

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
