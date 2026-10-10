"""Bediening op afstand vanuit de Work-app (v1.34.0, beveiligd in v1.35.0).

Elke minuut vraagt de installatie aan de Work-app of er opdrachten klaarstaan
(GET <basis>/commands, met de sleutel van de klant). De installatie haalt zelf
op: er hoeft geen poort open en de Work-app kan niets rechtstreeks aanroepen.

Enkel deze opdrachten bestaan; al de rest wordt geweigerd:
- set_auto_update   automatische updates aan/uit, uur, categorieen, back-up
- run_updates       de nachtelijke run nu starten (of dry_run: enkel tonen)
- install_update    een update installeren (enkel update.* entiteiten); de herstart
                    na een HACS update wacht overdag tot de nacht (v1.43.0),
                    tenzij "now": true
- skip_update       een update overslaan
- clear_skipped     overgeslagen update terug tonen
- retry_failed      telling van mislukte pogingen wissen (volgende nacht opnieuw)
- send_status       meteen de status versturen
- restart           Home Assistant herstarten (enkel na een geslaagde configuratiecontrole)
- reboot_host       het toestel herstarten (enkel HA OS / Supervised)
- create_user, update_user, set_password, logout_user, delete_user  (users.py,
  enkel als "Gebruikersbeheer op afstand" aan staat, standaard uit)

Veiligheid (v1.35.0, na audit):
- elke opdracht heeft een id en een vervaldatum (expires_at, hoogstens 1 dag
  vooruit); verlopen of al uitgevoerde opdrachten worden nooit (opnieuw) uitgevoerd,
  ook niet na een herstart (uitgevoerde id's worden bewaard voor ze starten);
- redirects worden niet gevolgd, het antwoord is hoogstens 256 kB;
- ja/nee velden moeten echt true/false zijn (geen "false" als tekst);
- een opdrachtenreeks tegelijk; installeren en herstarten nooit tijdens een run;
- herstarten pas nadat het resultaat verstuurd is.

Het resultaat gaat terug naar POST <basis>/commands/result. Uitschakelen kan in
de instellingen ("Bediening op afstand door Btechnics").
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import auto_update, status, users

_LOGGER = logging.getLogger(__name__)

DOMAIN = "btechnics_branding"
CONF_REMOTE = "remote_control"
_INTERVAL = timedelta(seconds=60)
_TIMEOUT_S = 20
_MAX_BODY = 256 * 1024
_MAX_AHEAD = timedelta(days=1)
_DATA = "btechnics_branding_remote"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
_UPDATE_RE = re.compile(r"^update\.[a-z0-9_]+$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_RESTART_DELAY = 5  # na het versturen van het resultaat
_RESTARTS = {"restart": ("homeassistant", "restart"), "reboot_host": ("hassio", "host_reboot")}


def _bool(cmd: dict, key: str, default: bool | None = None) -> bool:
    """Enkel echte true/false; "false" als tekst mag niet stilletjes waar worden."""
    value = cmd.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} moet true of false zijn")
    return value


def _schedule(hass: HomeAssistant, domain: str, service: str, why: str) -> None:
    """Herstart na enkele seconden."""
    from homeassistant.helpers.event import async_call_later

    auto_update._log(hass, why)  # noqa: SLF001

    async def _go(_now) -> None:
        await hass.services.async_call(domain, service, {}, blocking=False)

    async_call_later(hass, _RESTART_DELAY, _go)


def _base(options: dict) -> str:
    url = (options.get(status.CONF_URL) or status.DEFAULT_URL).strip()
    return url[: -len("/status")] if url.endswith("/status") else url.rstrip("/")


def _state(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(_DATA, {
        "unsub": None, "done": {}, "last": None, "busy": False, "running": False, "store": None,
    })


def enabled(options: dict) -> bool:
    from .config_flow import _status_url_ok

    return (bool(options.get(CONF_REMOTE, True))
            and bool((options.get(status.CONF_TOKEN) or "").strip())
            and _status_url_ok(options.get(status.CONF_URL) or status.DEFAULT_URL))


async def _post_result(hass: HomeAssistant, options: dict, cmd_id: str, ok: bool, data: Any) -> bool:
    token = (options.get(status.CONF_TOKEN) or "").strip()
    body = {"id": cmd_id, "ok": ok, "at": dt_util.utcnow().isoformat(),
            ("result" if ok else "error"): data}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with async_get_clientsession(hass).post(
                _base(options) + "/commands/result", json=body,
                headers={"Authorization": f"Bearer {token}"}, allow_redirects=False,
            ) as resp:
                if resp.status >= 300:
                    _LOGGER.warning("BT op afstand: resultaat %s niet aanvaard (%s)", cmd_id, resp.status)
                    return False
                return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("BT op afstand: resultaat %s niet verstuurd: %s", cmd_id, err)
        return False


def _update_entity(hass: HomeAssistant, cmd: dict):
    eid = str(cmd.get("entity_id") or "")
    if not _UPDATE_RE.match(eid):
        raise ValueError("entity_id moet een update.* entiteit zijn")
    st = hass.states.get(eid)
    if st is None:
        raise ValueError(f"{eid} bestaat niet")
    return eid, st


def _notify_users(hass: HomeAssistant, kind: str, data: dict, cmd_id: str, error: str | None = None) -> None:
    """Gebruikersbeheer op afstand is altijd zichtbaar voor de klant (melding)."""
    from homeassistant.components import persistent_notification

    wat = {
        "create_user": "een gebruiker aangemaakt", "update_user": "een gebruiker aangepast",
        "set_password": "een wachtwoord gewijzigd", "logout_user": "een gebruiker overal afgemeld",
        "delete_user": "een gebruiker verwijderd",
    }.get(kind, kind)
    naam = data.get("name") or data.get("username") or data.get("user_id") or ""
    tijd = dt_util.now().strftime("%d/%m/%Y %H:%M")
    if error:
        text = f"Btechnics probeerde vanop afstand {wat} ({naam}), maar dit werd geweigerd: {error}. Tijdstip: {tijd}."
    else:
        text = f"Btechnics heeft vanop afstand {wat}: {naam}. Tijdstip: {tijd}."
    persistent_notification.async_create(
        hass, text, title="Btechnics IOT: gebruikersbeheer",
        notification_id=f"btechnics_users_{cmd_id}",
    )


async def _execute(hass: HomeAssistant, entry, cmd: dict) -> tuple[bool, Any]:
    """Voer een opdracht uit. Geeft (gelukt, resultaat of fout)."""
    kind = cmd.get("type")
    options = dict(entry.options)

    if kind == "set_auto_update":
        new = dict(options)
        if "enabled" in cmd:
            new[auto_update.CONF_ENABLED] = _bool(cmd, "enabled")
        if "time" in cmd:
            m = _TIME_RE.match(str(cmd["time"]))
            if not m:
                raise ValueError("time moet UU:MM zijn")
            new[auto_update.CONF_TIME] = f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}"
        if "categories" in cmd:
            raw = cmd["categories"] if isinstance(cmd["categories"], list) else []
            cats = [c for c in raw if c in auto_update.CATEGORIES]
            if not cats:
                raise ValueError("categories: kies uit " + ", ".join(auto_update.CATEGORIES))
            new[auto_update.CONF_CATEGORIES] = cats
        if "backup" in cmd:
            new[auto_update.CONF_BACKUP] = _bool(cmd, "backup")
        hass.config_entries.async_update_entry(entry, options=new)
        return True, {
            "enabled": new.get(auto_update.CONF_ENABLED, False),
            "time": new.get(auto_update.CONF_TIME, auto_update.DEFAULT_TIME),
            "categories": new.get(auto_update.CONF_CATEGORIES, auto_update.DEFAULT_CATEGORIES),
            "backup": new.get(auto_update.CONF_BACKUP, True),
        }

    if kind == "run_updates":
        todo, skipped = auto_update.plan(hass, options)
        plan = [f"{u['name']} {u['from']} naar {u['to']}" for u in todo]
        if _bool(cmd, "dry_run", False):
            return True, {"zou_installeren": plan, "overgeslagen": skipped}
        if auto_update._lock(hass).locked():  # noqa: SLF001
            raise ValueError("er loopt al een run")
        hass.async_create_background_task(
            auto_update.async_run(hass, options, "op afstand"), "btechnics_branding_remote_run"
        )
        return True, {"gestart": plan, "overgeslagen": skipped}

    if kind == "install_update":
        eid, st = _update_entity(hass, cmd)
        features = int(st.attributes.get("supported_features", 0) or 0)
        if st.state != "on":
            raise ValueError(f"{eid} heeft geen openstaande update")
        if not features & 1:
            raise ValueError(f"{eid} kan niet vanop afstand geinstalleerd worden")
        data: dict[str, Any] = {"entity_id": eid}
        if _bool(cmd, "backup", True) and features & 8:
            data["backup"] = True
        want_restart = _bool(cmd, "restart", True)
        # v1.43.0: overdag wacht de herstart tot de nacht, tenzij expliciet "now": true
        restart_now = _bool(cmd, "now", False)
        latest = st.attributes.get("latest_version")
        lock = auto_update._lock(hass)  # noqa: SLF001
        if lock.locked():
            raise ValueError("er loopt al een run, probeer later opnieuw")
        async with lock:
            async with asyncio.timeout(45 * 60):
                await hass.services.async_call("update", "install", data, blocking=True)
        tracker = auto_update._tracker(hass)  # noqa: SLF001
        if tracker:
            tracker.reset(eid)
        now = hass.states.get(eid)
        from homeassistant.helpers import entity_registry as er
        is_hacs = auto_update._kind(er.async_get(hass).async_get(eid)) == "hacs"  # noqa: SLF001
        restart = bool(is_hacs and want_restart)
        planned = None
        if restart and not restart_now and not auto_update.is_night():
            planned = auto_update.async_defer_restart(hass, options, f"HACS update op afstand ({eid})")
            restart = False
        return True, {"entity_id": eid, "naar": latest,
                      "state": now.state if now else None,
                      "installed": now.attributes.get("installed_version") if now else None,
                      # een HACS integratie wordt pas actief na een herstart
                      "herstart": restart,
                      "herstart_gepland": planned}

    if kind in ("skip_update", "clear_skipped"):
        eid, _st = _update_entity(hass, cmd)
        await hass.services.async_call(
            "update", "skip" if kind == "skip_update" else "clear_skipped",
            {"entity_id": eid}, blocking=True,
        )
        return True, {"entity_id": eid}

    if kind == "retry_failed":
        eid, _st = _update_entity(hass, cmd)
        tracker = auto_update._tracker(hass)  # noqa: SLF001
        if tracker:
            tracker.reset(eid)
        auto_update.async_sync_visibility(hass, options, eid)
        return True, {"entity_id": eid}

    if kind == "send_status":
        return True, await status.async_send(hass, options, "op afstand")

    if kind in _RESTARTS:
        if auto_update._lock(hass).locked():  # noqa: SLF001
            raise ValueError("er loopt een update, geen herstart")
        if kind == "reboot_host" and not hass.services.has_service("hassio", "host_reboot"):
            raise ValueError("toestel herstarten kan enkel op HA OS of Supervised")
        # Eerst de configuratie nakijken: met een fout start HA niet meer op
        from homeassistant.helpers.check_config import async_check_ha_config_file
        res = await async_check_ha_config_file(hass)
        if res.errors:
            raise ValueError("configuratie bevat fouten, geen herstart: "
                             + "; ".join(str(e.message)[:200] for e in res.errors[:5]))
        # De herstart zelf volgt in _run_one, pas nadat het resultaat vertrokken is
        return True, {"herstart_over_s": _RESTART_DELAY, "herstart": True}

    if kind in users.KINDS:
        if not options.get(users.CONF_REMOTE_USERS, False):
            raise ValueError("gebruikersbeheer op afstand staat uit bij deze klant")
        try:
            data = await users.async_execute(hass, kind, cmd)
        except Exception as err:
            ref = {"user_id": cmd.get("user_id"), "username": cmd.get("username"), "name": cmd.get("name")}
            _notify_users(hass, kind, {k: str(v)[:60] for k, v in ref.items() if v}, cmd["id"], str(err))
            raise
        _notify_users(hass, kind, data, cmd["id"])
        return True, data

    raise ValueError(f"onbekende opdracht: {str(kind)[:40]}")


def _expired(cmd: dict) -> str | None:
    """Fout als de opdracht geen geldige vervaldatum heeft of verlopen is."""
    raw = cmd.get("expires_at")
    parsed = dt_util.parse_datetime(str(raw)) if raw else None
    if parsed is None or parsed.tzinfo is None:
        return "expires_at ontbreekt of is ongeldig (ISO met tijdzone)"
    now = dt_util.utcnow()
    if parsed < now:
        return "opdracht verlopen"
    if parsed > now + _MAX_AHEAD:
        return "expires_at ligt te ver in de toekomst"
    return None


def _stored(data: Any) -> Any:
    """Resultaat om te bewaren: nooit een wachtwoord, kort gehouden."""
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k != "password"}
    text = json.dumps(data, default=str)
    return data if len(text) <= 2000 else text[:2000]


async def _save_done(hass: HomeAssistant, cmd_id: str, rec: dict) -> bool:
    """Toestand van een opdracht bewaren (eerst op schijf, dan in het geheugen)."""
    st = _state(hass)
    done = dict(st["done"])
    done.pop(cmd_id, None)
    done[cmd_id] = rec
    while len(done) > 500:
        done.pop(next(iter(done)))
    try:
        if st["store"]:
            await st["store"].async_save({"done": done})
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("BT op afstand: kon de opdrachten niet bewaren: %s", err)
        return False
    st["done"] = done
    return True


async def _run_one(hass: HomeAssistant, entry, cmd: dict) -> tuple | None:
    """Voer een opdracht uit en meld het resultaat.

    Geeft (domain, service, reden) terug als er daarna een herstart moet volgen;
    die plant de reeks pas als alle resultaten vertrokken zijn.
    """
    cmd_id = cmd["id"]
    kind = cmd.get("type")
    try:
        if err := _expired(cmd):
            raise ValueError(err)
        ok, data = await _execute(hass, entry, cmd)
    except TimeoutError:
        ok, data = False, "duurde langer dan 45 minuten"
    except Exception as err:  # noqa: BLE001
        ok, data = False, str(err) or type(err).__name__
    _LOGGER.info("BT op afstand: %s %s -> %s", str(kind)[:40], cmd_id, "ok" if ok else data)
    auto_update._log(hass, f"op afstand: {str(kind)[:40]} {'gelukt' if ok else 'mislukt: ' + str(data)[:200]}")  # noqa: SLF001
    sent = await _post_result(hass, dict(entry.options), cmd_id, ok, data)
    await _save_done(hass, cmd_id, {"state": "done", "ok": ok, "data": _stored(data), "sent": sent,
                                    "had_password": isinstance(data, dict) and "password" in data,
                                    "at": dt_util.utcnow().isoformat()})
    if ok and isinstance(data, dict) and data.get("herstart"):
        domain, service = _RESTARTS.get(kind, _RESTARTS["restart"])
        return domain, service, {
            "restart": "herstart op afstand", "reboot_host": "toestel herstart op afstand",
        }.get(kind, "herstart na HACS update op afstand")
    async_dispatcher_send(hass, status.SIGNAL_CHANGED, "op_afstand")
    return None


async def _repost(hass: HomeAssistant, entry, cmd_id: str) -> None:
    """Opnieuw aangeboden opdracht: nooit opnieuw uitvoeren, wel het resultaat melden."""
    rec = _state(hass)["done"].get(cmd_id) or {}
    if rec.get("state") == "done":
        data = rec.get("data")
        if isinstance(data, dict):
            data = {**data, "herhaald": True}
            if rec.get("had_password") and not rec.get("sent"):
                # Het gemaakte wachtwoord kwam nooit aan en wordt niet bewaard: opnieuw resetten
                data["password_verloren"] = True
        await _post_result(hass, dict(entry.options), cmd_id, bool(rec.get("ok")), data)
    else:
        await _post_result(hass, dict(entry.options), cmd_id, False,
                           "onderbroken (herstart of stroomonderbreking), resultaat onbekend")
        await _save_done(hass, cmd_id, {"state": "done", "ok": False,
                                        "data": "onderbroken, resultaat onbekend",
                                        "at": dt_util.utcnow().isoformat()})


async def async_poll(hass: HomeAssistant, entry) -> dict:
    """Haal opdrachten op en voer ze uit. Geeft een samenvatting terug."""
    st = _state(hass)
    options = dict(entry.options)
    result: dict[str, Any] = {"at": dt_util.utcnow().isoformat()}
    if not enabled(options):
        result.update(ok=False, error="uitgeschakeld, geen sleutel of adres niet toegelaten")
        st["last"] = result
        return result
    if st["busy"] or st["running"] or st.get("restart_pending"):
        result.update(ok=True, skipped="vorige opdrachten lopen nog")
        return result
    st["busy"] = True
    try:
        token = options[status.CONF_TOKEN].strip()
        async with asyncio.timeout(_TIMEOUT_S):
            async with async_get_clientsession(hass).get(
                _base(options) + "/commands", headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
            ) as resp:
                result["http"] = resp.status
                if resp.status == 204:
                    commands = []
                elif resp.status >= 300:
                    raise ValueError(f"HTTP {resp.status}")
                else:
                    # Volledig lezen (read(n) geeft enkel wat al binnen is), met limiet
                    chunks, total = [], 0
                    async for chunk in resp.content.iter_chunked(16384):
                        total += len(chunk)
                        if total > _MAX_BODY:
                            raise ValueError("antwoord te groot")
                        chunks.append(chunk)
                    body = json.loads(b"".join(chunks) or b"{}")
                    commands = body.get("commands") if isinstance(body, dict) else None
                    if not isinstance(commands, list):
                        commands = []
        new, seen = [], set()
        for cmd in commands[:20]:
            if not isinstance(cmd, dict):
                continue
            cid = cmd.get("id")
            if not isinstance(cid, str) or not _ID_RE.match(cid) or cid in seen:
                continue
            seen.add(cid)
            new.append(cmd)
        if new:
            st["running"] = True

            async def _batch() -> None:
                restart = None
                try:
                    for c in new:
                        cid = c["id"]
                        if cid in st["done"]:
                            await _repost(hass, entry, cid)
                            continue
                        if restart:
                            # Na een geplande herstart niets meer starten
                            await _save_done(hass, cid, {"state": "done", "ok": False,
                                                         "data": "overgeslagen: herstart gepland",
                                                         "at": dt_util.utcnow().isoformat()})
                            await _post_result(hass, dict(entry.options), cid, False,
                                               "overgeslagen: herstart gepland, opnieuw versturen met een nieuw id")
                            continue
                        # Bewaren vlak voor de start: na een herstart nooit opnieuw uitvoeren
                        if not await _save_done(hass, cid, {"state": "started",
                                                            "at": dt_util.utcnow().isoformat()}):
                            await _post_result(hass, dict(entry.options), cid, False,
                                               "niet uitgevoerd: kon niet bewaren")
                            continue
                        restart = await _run_one(hass, entry, c) or restart
                finally:
                    if restart:
                        # Pas nu: alle resultaten zijn vertrokken. Tot de herstart niet meer ophalen.
                        st["restart_pending"] = True
                        _schedule(hass, *restart)
                    st["running"] = False

            hass.async_create_background_task(_batch(), "btechnics_branding_remote_batch")
        result.update(ok=True, commands=[str(c.get("type"))[:40] for c in new])
    except Exception as err:  # noqa: BLE001
        result.update(ok=False, error=str(err) or type(err).__name__)
    finally:
        st["busy"] = False
    st["last"] = result
    return result


async def async_setup(hass: HomeAssistant, entry) -> None:
    async_teardown(hass)
    st = _state(hass)
    if st["store"] is None:
        st["store"] = Store(hass, 1, f"{DOMAIN}.remote")
        data = await st["store"].async_load() or {}
        done = data.get("done", {})
        if isinstance(done, list):  # oud formaat
            done = {i: {"state": "done", "ok": None, "data": None} for i in done}
        st["done"] = dict(list(done.items())[-500:])

    async def _tick(_now) -> None:
        await async_poll(hass, entry)

    st["unsub"] = async_track_time_interval(hass, _tick, _INTERVAL)


@callback
def async_teardown(hass: HomeAssistant) -> None:
    st = _state(hass)
    if st["unsub"]:
        st["unsub"]()
        st["unsub"] = None


async def async_remove(hass: HomeAssistant) -> None:
    st = hass.data.pop(_DATA, None)
    store = (st or {}).get("store") or Store(hass, 1, f"{DOMAIN}.remote")
    await store.async_remove()
