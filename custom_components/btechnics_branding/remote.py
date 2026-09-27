"""Bediening op afstand vanuit de Work-app (v1.34.0).

Elke minuut vraagt de installatie aan de Work-app of er opdrachten klaarstaan
(GET <basis>/commands, met de sleutel van de klant). De installatie haalt zelf
op: er hoeft geen poort open en de Work-app kan niets rechtstreeks aanroepen.

Enkel deze opdrachten bestaan; al de rest wordt geweigerd:
- set_auto_update   automatische updates aan/uit, uur, categorieen, back-up
- run_updates       de nachtelijke run nu starten (of dry_run: enkel tonen)
- install_update    een update installeren (enkel update.* entiteiten)
- skip_update       een update overslaan
- clear_skipped     overgeslagen update terug tonen
- retry_failed      telling van mislukte pogingen wissen (volgende nacht opnieuw)
- send_status       meteen de status versturen

Het resultaat gaat terug naar POST <basis>/commands/result. Uitschakelen kan in
de instellingen ("Bediening op afstand door Btechnics").
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import auto_update, status

_LOGGER = logging.getLogger(__name__)

DOMAIN = "btechnics_branding"
CONF_REMOTE = "remote_control"
_INTERVAL = timedelta(seconds=60)
_TIMEOUT_S = 20
_DATA = "btechnics_branding_remote"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
_UPDATE_RE = re.compile(r"^update\.[a-z0-9_]+$")


def _base(options: dict) -> str:
    url = (options.get(status.CONF_URL) or status.DEFAULT_URL).strip()
    return url[: -len("/status")] if url.endswith("/status") else url.rstrip("/")


def _state(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(_DATA, {"unsub": None, "done": [], "last": None, "busy": False})


def enabled(options: dict) -> bool:
    return bool(options.get(CONF_REMOTE, True)) and bool((options.get(status.CONF_TOKEN) or "").strip())


async def _post_result(hass: HomeAssistant, options: dict, cmd_id: str, ok: bool, data: Any) -> None:
    token = (options.get(status.CONF_TOKEN) or "").strip()
    body = {"id": cmd_id, "ok": ok, "at": dt_util.utcnow().isoformat(),
            ("result" if ok else "error"): data}
    try:
        async with asyncio.timeout(_TIMEOUT_S):
            async with async_get_clientsession(hass).post(
                _base(options) + "/commands/result", json=body,
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status >= 300:
                    _LOGGER.warning("BT op afstand: resultaat %s niet aanvaard (%s)", cmd_id, resp.status)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("BT op afstand: resultaat %s niet verstuurd: %s", cmd_id, err)


def _update_entity(hass: HomeAssistant, cmd: dict):
    eid = str(cmd.get("entity_id") or "")
    if not _UPDATE_RE.match(eid):
        raise ValueError("entity_id moet een update.* entiteit zijn")
    st = hass.states.get(eid)
    if st is None:
        raise ValueError(f"{eid} bestaat niet")
    return eid, st


async def _execute(hass: HomeAssistant, entry, cmd: dict) -> tuple[bool, Any]:
    """Voer een opdracht uit. Geeft (gelukt, resultaat of fout)."""
    kind = cmd.get("type")
    options = dict(entry.options)

    if kind == "set_auto_update":
        new = dict(options)
        if "enabled" in cmd:
            new[auto_update.CONF_ENABLED] = bool(cmd["enabled"])
        if "time" in cmd:
            m = _TIME_RE.match(str(cmd["time"]))
            if not m:
                raise ValueError("time moet UU:MM zijn")
            new[auto_update.CONF_TIME] = f"{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or '00'}"
        if "categories" in cmd:
            cats = [c for c in (cmd["categories"] or []) if c in auto_update.CATEGORIES]
            if not cats:
                raise ValueError("categories: kies uit " + ", ".join(auto_update.CATEGORIES))
            new[auto_update.CONF_CATEGORIES] = cats
        if "backup" in cmd:
            new[auto_update.CONF_BACKUP] = bool(cmd["backup"])
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
        if cmd.get("dry_run"):
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
        if cmd.get("backup", True) and features & 8:
            data["backup"] = True
        latest = st.attributes.get("latest_version")
        async with asyncio.timeout(45 * 60):
            await hass.services.async_call("update", "install", data, blocking=True)
        tracker = auto_update._tracker(hass)  # noqa: SLF001
        if tracker:
            tracker.reset(eid)
        now = hass.states.get(eid)
        return True, {"entity_id": eid, "naar": latest,
                      "state": now.state if now else None,
                      "installed": now.attributes.get("installed_version") if now else None}

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

    raise ValueError(f"onbekende opdracht: {kind}")


async def _run_one(hass: HomeAssistant, entry, cmd: dict) -> None:
    cmd_id = str(cmd.get("id") or "")
    try:
        ok, data = await _execute(hass, entry, cmd)
    except TimeoutError:
        ok, data = False, "duurde langer dan 45 minuten"
    except Exception as err:  # noqa: BLE001
        ok, data = False, str(err) or type(err).__name__
    _LOGGER.warning("BT op afstand: %s %s -> %s", cmd.get("type"), cmd_id, "ok" if ok else data)
    auto_update._log(hass, f"op afstand: {cmd.get('type')} {'gelukt' if ok else 'mislukt: ' + str(data)}")  # noqa: SLF001
    await _post_result(hass, dict(entry.options), cmd_id, ok, data)
    async_dispatcher_send(hass, status.SIGNAL_CHANGED, "op_afstand")


async def async_poll(hass: HomeAssistant, entry) -> dict:
    """Haal opdrachten op en voer ze uit. Geeft een samenvatting terug."""
    st = _state(hass)
    options = dict(entry.options)
    result: dict[str, Any] = {"at": dt_util.utcnow().isoformat()}
    if not enabled(options):
        result.update(ok=False, error="uitgeschakeld of geen sleutel")
        st["last"] = result
        return result
    if st["busy"]:
        result.update(ok=True, skipped="vorige ophaling loopt nog")
        return result
    st["busy"] = True
    try:
        token = options[status.CONF_TOKEN].strip()
        async with asyncio.timeout(_TIMEOUT_S):
            async with async_get_clientsession(hass).get(
                _base(options) + "/commands", headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                result["http"] = resp.status
                if resp.status == 204:
                    commands = []
                elif resp.status >= 300:
                    raise ValueError(f"HTTP {resp.status}")
                else:
                    commands = (await resp.json(content_type=None) or {}).get("commands") or []
        new = []
        for cmd in commands[:20]:
            if not isinstance(cmd, dict) or not cmd.get("id") or cmd["id"] in st["done"]:
                continue
            st["done"] = (st["done"] + [cmd["id"]])[-200:]
            new.append(cmd)
        if new:
            # Op de achtergrond (installeren kan lang duren), in de volgorde van de Work-app
            async def _batch() -> None:
                for c in new:
                    await _run_one(hass, entry, c)
            hass.async_create_background_task(_batch(), "btechnics_branding_remote_batch")
        result.update(ok=True, commands=[c.get("type") for c in new])
    except Exception as err:  # noqa: BLE001
        result.update(ok=False, error=str(err) or type(err).__name__)
    finally:
        st["busy"] = False
    st["last"] = result
    return result


async def async_setup(hass: HomeAssistant, entry) -> None:
    async_teardown(hass)

    async def _tick(_now) -> None:
        await async_poll(hass, entry)

    _state(hass)["unsub"] = async_track_time_interval(hass, _tick, _INTERVAL)


@callback
def async_teardown(hass: HomeAssistant) -> None:
    st = _state(hass)
    if st["unsub"]:
        st["unsub"]()
        st["unsub"] = None
