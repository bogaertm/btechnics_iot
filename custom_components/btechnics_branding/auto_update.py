"""Automatische updates voor Btechnics IOT.

Elke nacht op het ingestelde uur worden de beschikbare updates geinstalleerd:
Supervisor, apps (add-ons), HACS, eventueel firmware van toestellen, en tot slot
Core of OS. Een update die de gebruiker zelf heeft overgeslagen staat op "off"
en wordt dus nooit aangeraakt.

Regels (afgesproken met Btechnics):
- Core pas vanaf de eerste bugfix van een maand (2026.10.1, nooit 2026.10.0)
  en nooit een beta of release candidate.
- Back-up voor elke update die dat ondersteunt (Core, OS, apps).
- Geen updates zolang de zelfcontrole een probleem met de branding meldt.
- Core en OS herstarten het systeem; daarom hoogstens een van beide per nacht,
  als laatste stap. Wat daarna nog openstaat, volgt de volgende nacht.

Meldingen verbergen (v1.32.0):
- Een update die wij 's nachts zelf installeren, hoeft de klant niet te zien.
  Zolang ze openstaat, verbergen we de update entiteit in het entiteitenregister
  (hidden_by=integration). De frontend telt verborgen update entiteiten niet mee
  in het bolletje van Instellingen in de zijbalk en toont ze niet bovenaan
  Instellingen (frontend src/components/ha-sidebar.ts _calculateCounts en
  src/panels/config/dashboard/ha-config-dashboard.ts).
- Per entiteit en per versie tellen we de pogingen. Na 2 mislukte pogingen voor
  dezelfde versie proberen we niet meer, wordt de update weer zichtbaar en komt
  er een melding onder Reparaties. Een nieuwere versie begint opnieuw bij 0.
- Enkel wat wij zelf verborgen hebben, maken we weer zichtbaar. Wat de gebruiker
  verbergt (hidden_by=user), blijft van hem.
- Automatische updates uit, of de integratie weg: alles wordt weer zichtbaar.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time as _time
from datetime import datetime, time as dtime, timedelta
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DOMAIN = "btechnics_branding"
ISSUE_ID = "hooks_broken"

CONF_ENABLED = "auto_update"
CONF_TIME = "auto_update_time"
CONF_CATEGORIES = "auto_update_categories"
CONF_BACKUP = "auto_update_backup"

DEFAULT_TIME = "04:00:00"
CATEGORIES = ["system", "addons", "hacs", "firmware"]
DEFAULT_CATEGORIES = ["system", "addons", "hacs"]

_FEATURE_INSTALL = 1  # UpdateEntityFeature.INSTALL
_FEATURE_BACKUP = 8  # UpdateEntityFeature.BACKUP
_DATA_UNSUB = "btechnics_branding_update_unsub"
_DATA_LAST = "btechnics_branding_update_last"
_DATA_TRACKER = "btechnics_branding_update_tracker"
_DATA_VIS_UNSUB = "btechnics_branding_update_vis_unsub"
_DATA_LOCK = "btechnics_branding_update_lock"
_DATA_GETOPTS = "btechnics_branding_update_getopts"
_DATA_DEFER = "btechnics_branding_restart_deferred"
_DATA_INSTALLING = "btechnics_branding_update_installing"
MAX_ATTEMPTS = 2
FAILED_ISSUE_PREFIX = "update_failed_"
_INSTALL_TIMEOUT = 45 * 60  # een app of Core update mag lang duren

# Volgorde binnen een nacht. Core en OS staan achteraan: die herstarten.
_ORDER = ["supervisor", "addon", "hacs", "firmware", "core", "os"]


def _kind(entry: er.RegistryEntry | None) -> str:
    """Soort update op basis van het platform en de unique_id van de entiteit."""
    if entry is None:
        return "firmware"
    uid = entry.unique_id or ""
    if entry.platform == "hassio":
        if uid.startswith("home_assistant_core_"):
            return "core"
        if uid.startswith("home_assistant_os_"):
            return "os"
        if uid.startswith("home_assistant_supervisor_"):
            return "supervisor"
        return "addon"
    if entry.platform == "hacs":
        return "hacs"
    return "firmware"


def _category(kind: str) -> str:
    return {
        "core": "system", "os": "system", "supervisor": "system",
        "addon": "addons", "hacs": "hacs",
    }.get(kind, "firmware")


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def core_version_allowed(latest: str | None) -> tuple[bool, str]:
    """Core enkel vanaf x.1, en nooit beta, rc of dev."""
    if not latest:
        return False, "geen versie"
    m = _VERSION_RE.match(str(latest).strip())
    if not m:
        return False, f"{latest} is geen stabiele versie"
    if int(m.group(3)) == 0:
        return False, f"{latest} is een .0, wachten op de eerste bugfix"
    return True, ""


def _parse_time(value: Any) -> dtime:
    try:
        parts = [int(p) for p in str(value or DEFAULT_TIME).split(":")]
        return dtime(parts[0], parts[1] if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return dtime(4, 0)


# v1.43.0: een herstart na een HACS update op afstand viel midden op de dag
# (defrancq, 10/10 10:40). Elk open scherm verloor dan 1 a 2 minuten de verbinding.
# Overdag wacht de herstart nu tot het uur van de nachtelijke updates.
_NIGHT_FROM = 23
_NIGHT_UNTIL = 6


def is_night(now: datetime | None = None) -> bool:
    hour = (now or dt_util.now()).hour
    return hour >= _NIGHT_FROM or hour < _NIGHT_UNTIL


def _next_restart_time(options: dict) -> datetime:
    at = _parse_time(options.get(CONF_TIME, DEFAULT_TIME))
    now = dt_util.now()
    when = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    # Na de nachtelijke run: die herstart zelf als ze iets installeert
    return when + timedelta(minutes=15)


def deferred_restart(hass: HomeAssistant) -> str | None:
    info = hass.data.get(_DATA_DEFER)
    return info["at"] if info else None


@callback
def async_defer_restart(hass: HomeAssistant, options: dict, why: str) -> str:
    """Plan een herstart op het nachtelijke uur. Geeft het tijdstip (ISO) terug."""
    if (info := hass.data.get(_DATA_DEFER)) is not None:
        return info["at"]
    when = _next_restart_time(options)

    async def _go(_now: datetime) -> None:
        if _lock(hass).locked():
            # Nachtelijke run loopt nog: straks opnieuw proberen
            hass.data[_DATA_DEFER]["unsub"] = async_track_point_in_time(
                hass, _go, dt_util.now() + timedelta(minutes=5))
            return
        hass.data.pop(_DATA_DEFER, None)
        _log(hass, f"uitgestelde herstart nu: {why}")
        await hass.services.async_call("homeassistant", "restart", {}, blocking=False)

    hass.data[_DATA_DEFER] = {
        "at": when.isoformat(), "why": why,
        "unsub": async_track_point_in_time(hass, _go, when),
    }
    _log(hass, f"herstart uitgesteld tot {when:%d/%m %H:%M}: {why}")
    async_dispatcher_send(hass, f"{DOMAIN}_status_changed", "updates")
    return when.isoformat()


@callback
def async_cancel_deferred(hass: HomeAssistant) -> None:
    if (info := hass.data.pop(_DATA_DEFER, None)) is not None:
        info["unsub"]()


# v1.48.0: nieuwe versies van HA OS, Supervisor en apps pas installeren als ze
# minstens 7 dagen bekend zijn. De eerste dagen na een release zitten er vaak
# nog fouten in; dan komt meestal snel een bugfix. Core blijft wachten op .1.
HOLD_DAYS = 7
HOLD_KINDS = ("os", "supervisor", "addon")


def hold_until(first_seen: datetime, days: int = HOLD_DAYS) -> datetime:
    return first_seen + timedelta(days=days)


def on_hold(first_seen: datetime, now: datetime, days: int = HOLD_DAYS) -> bool:
    return now < hold_until(first_seen, days)


# v1.48.1: op 25/10 (iot.bogaert.me) mislukte de Core update met "Backup manager
# busy: create_backup". De automatische back-up van HA zelf liep op dat moment (geen
# vaste tijd ingesteld: 04:45 plus tot 60 min willekeurig, die nacht door de overgang
# naar wintertijd een uur vroeger). HA weigert dan een tweede back-up
# (homeassistant/components/backup/manager.py, async_initiate_backup).
# Daarom wachten we tot de back-upmanager vrij is, en telt "busy" niet als poging.
BACKUP_WAIT = 30 * 60
BACKUP_POLL = 15


def backup_state(hass: HomeAssistant) -> str | None:
    """Status van de HA back-upmanager (idle, create_backup, ...), None als er geen is."""
    manager = hass.data.get("backup")  # backup.const.DATA_MANAGER
    state = getattr(manager, "state", None)
    return None if state is None else str(state)


def backup_busy_error(err: BaseException) -> bool:
    return "backup manager busy" in str(err).lower()


# v1.48.2: op 26 en 27/10 mislukte Core 2026.10.4 op iot.bogaert.me telkens exact
# 30 s na de start met "Error creating backup: Backup failed: ... Preparing backup of
# Home Assistant Core failed. Failed to inform HA Core: Unsuccessful websocket ...".
# De Supervisor vraagt Core dan de database op slot te zetten (backup/start ->
# recorder.backup.async_pre_backup -> lock_database, DB_LOCK_TIMEOUT = 30 s). Om
# 04:00 is de recorder druk (statistieken van het uur). Zo'n back-upfout is tijdelijk:
# na een pauze opnieuw proberen, binnen dezelfde run.
BACKUP_RETRIES = 2
BACKUP_RETRY_WAIT = 5 * 60
_BACKUP_RETRY_RE = re.compile(
    r"backup manager busy|error creating backup|backup failed|preparing backup"
    r"|failed to inform ha core|could not lock database|pre-backup|pre_backup",
    re.IGNORECASE,
)


def backup_retryable(err: BaseException) -> bool:
    return bool(_BACKUP_RETRY_RE.search(str(err)))


# v1.48.2: Defrancq 26/10: "Error updating Home Assistant Core: Downloading Home
# Assistant version 2026.10.4 failed". De Supervisor haalt de image op bij ghcr.io;
# een haperend netwerk of register is meestal na enkele minuten voorbij.
_DOWNLOAD_RETRY_RE = re.compile(
    r"download\w* .*failed|failed to download|download failed|timeout while (pulling|downloading)",
    re.IGNORECASE,
)


def download_retryable(err: BaseException) -> bool:
    return bool(_DOWNLOAD_RETRY_RE.search(str(err)))


async def async_install_with_backup_retry(hass: HomeAssistant, data: dict, label: str) -> None:
    """update.install; bij een tijdelijke back-up- of downloadfout tot BACKUP_RETRIES keer opnieuw."""
    for n in range(BACKUP_RETRIES + 1):
        try:
            await hass.services.async_call("update", "install", data, blocking=True)
            return
        except Exception as err:  # noqa: BLE001
            backup = bool(data.get("backup")) and backup_retryable(err)
            if n >= BACKUP_RETRIES or not (backup or download_retryable(err)):
                raise
            soort = "back-up" if backup else "download"
            _log(hass, f"{soort} voor {label} mislukt, nieuwe poging over "
                       f"{BACKUP_RETRY_WAIT // 60} min: {err}")
            await asyncio.sleep(BACKUP_RETRY_WAIT)
            await async_wait_backup_idle(hass)


async def async_wait_backup_idle(
    hass: HomeAssistant, timeout: float | None = None, poll: float | None = None
) -> str | None:
    """Wacht tot de back-upmanager vrij is. None = vrij, anders de status na de wachttijd."""
    poll = BACKUP_POLL if poll is None else poll
    deadline = _time.monotonic() + (BACKUP_WAIT if timeout is None else timeout)
    while True:
        state = backup_state(hass)
        if state in (None, "idle"):
            return None
        if _time.monotonic() >= deadline:
            return state
        await asyncio.sleep(poll)


# v1.48.2: Defrancq 27/10: HA herstartte tijdens de Core-update (04:22) zonder dat er
# een resultaat gelogd werd. Na een herstart melden we of Core/OS echt nieuwer is.
_MODULE_START = dt_util.utcnow()
AFTER_RESTART_WINDOW = timedelta(hours=3)


def _after_restart_check(hass: HomeAssistant, tracker: "Tracker", state, kind: str, pending: bool) -> None:
    if kind not in ("core", "os"):
        return
    rec = tracker.attempts.get(state.entity_id)
    if not rec or rec.get("nagekeken"):
        return
    last = dt_util.parse_datetime(str(rec.get("last")))
    if last is None or last >= _MODULE_START or dt_util.utcnow() - last > AFTER_RESTART_WINDOW:
        return
    name = state.attributes.get("title") or state.attributes.get("friendly_name") or state.entity_id
    want = rec.get("version")
    have = state.attributes.get("installed_version")
    if not pending or have == want:
        _log(hass, f"{name} {want}: actief na de herstart")
    else:
        _log(hass, f"{name} {want}: na de herstart niet actief (nog altijd {have}); "
                   "update mislukt of teruggezet door de Supervisor")
    tracker.mark_done(state.entity_id)


class Tracker:
    """Pogingen per update en welke entiteiten wij verborgen hebben (blijft bewaard)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.auto_update")
        self.attempts: dict[str, dict] = {}
        self.hidden: set[str] = set()
        self.seen: dict[str, dict] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.attempts = data.get("attempts", {})
        self.hidden = set(data.get("hidden", []))
        self.seen = data.get("seen", {})

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {"attempts": self.attempts, "hidden": sorted(self.hidden), "seen": self.seen}, 2
        )

    def first_seen(self, entity_id: str, version: str | None) -> datetime:
        """Wanneer zagen we deze versie voor het eerst als beschikbaar (v1.48.0)."""
        rec = self.seen.get(entity_id)
        if rec and rec.get("version") == version:
            parsed = dt_util.parse_datetime(str(rec.get("since")))
            if parsed is not None:
                return parsed
        now = dt_util.utcnow()
        self.seen[entity_id] = {"version": version, "since": now.isoformat()}
        self._save()
        return now

    def forget_seen(self, entity_id: str) -> None:
        if self.seen.pop(entity_id, None) is not None:
            self._save()

    def count(self, entity_id: str, version: str | None) -> int:
        a = self.attempts.get(entity_id)
        return a["count"] if a and a.get("version") == version else 0

    def add_attempt(self, entity_id: str, version: str | None) -> int:
        n = self.count(entity_id, version) + 1
        self.attempts[entity_id] = {"version": version, "count": n,
                                    "last": dt_util.utcnow().isoformat()}
        self._save()
        return n

    def undo_attempt(self, entity_id: str, version: str | None) -> None:
        """v1.48.1: een poging die niet aan de update zelf lag, telt niet mee."""
        n = self.count(entity_id, version)
        if n <= 1:
            self.reset(entity_id)
        else:
            self.attempts[entity_id]["count"] = n - 1
            self._save()

    def mark_done(self, entity_id: str) -> None:
        """v1.48.2: resultaat van de poging is gekend (geen controle na herstart nodig)."""
        if (rec := self.attempts.get(entity_id)) is not None:
            rec["nagekeken"] = True
            self._save()

    def reset(self, entity_id: str) -> None:
        if self.attempts.pop(entity_id, None) is not None:
            self._save()

    def set_hidden(self, entity_id: str, hidden: bool) -> None:
        if hidden and entity_id not in self.hidden:
            self.hidden.add(entity_id)
            self._save()
        elif not hidden and entity_id in self.hidden:
            self.hidden.discard(entity_id)
            self._save()


def _tracker(hass: HomeAssistant) -> Tracker | None:
    return hass.data.get(_DATA_TRACKER)


def _managed(state, kind: str, options: dict) -> bool:
    """Valt deze update onder de automatische updates?"""
    if not options.get(CONF_ENABLED, False):
        return False
    features = int(state.attributes.get("supported_features", 0) or 0)
    if not features & _FEATURE_INSTALL:
        return False
    if kind == "core" and not _VERSION_RE.match(str(state.attributes.get("latest_version") or "").strip()):
        # v1.32.1: beta, rc of dev installeren we nooit, dus ook niet verbergen.
        # Een .0 blijft wel verborgen: die wordt de .1 en gaat dan automatisch.
        return False
    return _category(kind) in set(options.get(CONF_CATEGORIES, DEFAULT_CATEGORIES))


def plan(hass: HomeAssistant, options: dict) -> tuple[list[dict], list[str]]:
    """Welke updates staan klaar en in welke volgorde. Geeft (plan, overgeslagen)."""
    categories = set(options.get(CONF_CATEGORIES, DEFAULT_CATEGORIES))
    reg = er.async_get(hass)
    todo: list[dict] = []
    skipped: list[str] = []
    for state in hass.states.async_all("update"):
        if state.state != "on" or state.attributes.get("in_progress"):
            continue
        features = int(state.attributes.get("supported_features", 0) or 0)
        if not features & _FEATURE_INSTALL:
            continue  # enkel te melden, niet te installeren (bv. manuele firmware)
        kind = _kind(reg.async_get(state.entity_id))
        name = state.attributes.get("title") or state.attributes.get("friendly_name") or state.entity_id
        latest = state.attributes.get("latest_version")
        if _category(kind) not in categories:
            continue
        if kind == "core":
            allowed, why = core_version_allowed(latest)
            if not allowed:
                skipped.append(f"{name}: {why}")
                continue
        tracker = _tracker(hass)
        if tracker and kind in HOLD_KINDS:
            since = tracker.first_seen(state.entity_id, latest)
            if on_hold(since, dt_util.utcnow()):
                until = dt_util.as_local(hold_until(since))
                skipped.append(f"{name} {latest}: nieuwe versie, wacht tot {until:%d/%m} "
                               f"({HOLD_DAYS} dagen voor bugfixes)")
                continue
        if tracker and tracker.count(state.entity_id, latest) >= MAX_ATTEMPTS:
            skipped.append(f"{name} {latest}: {MAX_ATTEMPTS} keer mislukt, wacht op manuele actie")
            continue
        todo.append({
            "entity_id": state.entity_id,
            "kind": kind,
            "name": str(name),
            "from": state.attributes.get("installed_version"),
            "to": latest,
            "backup": bool(features & _FEATURE_BACKUP),
        })
    todo.sort(key=lambda u: (_ORDER.index(u["kind"]), u["name"].lower()))
    # Hoogstens een herstartende update per nacht: Core voor OS.
    restarting = [u for u in todo if u["kind"] in ("core", "os")]
    for u in restarting[1:]:
        todo.remove(u)
        skipped.append(f"{u['name']}: volgende nacht, na de herstart")
    return todo, skipped


def _branding_broken(hass: HomeAssistant) -> bool:
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)
    return issue is not None and issue.active and not issue.dismissed_version


_DATA_EVENTS = "btechnics_branding_events"


def _log(hass: HomeAssistant, message: str) -> None:
    """Zichtbaar in Activiteit (logboek), in het HA log en (v1.35.0) in de Work-app."""
    # info i.p.v. warning: anders vullen onze eigen berichten de foutenlijst in de Work-app
    _LOGGER.info("BT auto-update: %s", message)
    events = hass.data.setdefault(_DATA_EVENTS, [])
    events.append({"at": dt_util.utcnow().isoformat(), "message": message})
    del events[:-100]
    if not hass.services.has_service("logbook", "log"):
        return
    try:
        hass.async_create_task(hass.services.async_call(
            "logbook", "log",
            {"name": "Btechnics IOT updates", "message": message, "domain": DOMAIN},
        ))
    except Exception:  # noqa: BLE001
        pass


# v1.47.0: HACS kijkt eigen (custom) repositories, zoals btechnics_iot,
# btechnics_toegang en btechnics_vto, maar elke 48 uur na: een interval dat
# bij elke herstart opnieuw begint (hacs/base.py, async_update_downloaded_custom_repositories,
# timedelta(hours=48)). Een installatie die vaker herstart, zag nieuwe versies
# nooit (iot.bogaert.me bleef op 1.40.0 staan). Daarom vragen we HACS zelf om
# die repositories te verversen, net zoals de knop "Opnieuw laden" in HACS
# (websocket hacs/repository/refresh).
_HACS_REFRESH_TIMEOUT = 60


async def async_refresh_hacs_custom(hass: HomeAssistant) -> dict:
    """Ververs de gedownloade custom repositories in HACS. Faalt nooit."""
    out: dict[str, Any] = {"ververst": [], "fouten": []}
    hacs = hass.data.get("hacs")
    repos_obj = getattr(hacs, "repositories", None) if hacs is not None else None
    if repos_obj is None:
        return out
    try:
        repos = [r for r in repos_obj.list_downloaded
                 if not repos_obj.is_default(str(r.data.id))]
    except Exception as err:  # noqa: BLE001
        out["fouten"].append(f"lijst: {err}")
        return out
    for repo in repos:
        name = getattr(getattr(repo, "data", None), "full_name", "?")
        try:
            async with asyncio.timeout(_HACS_REFRESH_TIMEOUT):
                await repo.update_repository(ignore_issues=True, force=True)
            out["ververst"].append(name)
        except Exception as err:  # noqa: BLE001
            out["fouten"].append(f"{name}: {err or type(err).__name__}")
    try:
        await hacs.data.async_write()
    except Exception:  # noqa: BLE001
        pass
    for coordinator in (getattr(hacs, "coordinators", None) or {}).values():
        try:
            coordinator.async_update_listeners()
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(1)  # update-entiteiten hun nieuwe toestand laten schrijven
    if out["ververst"] or out["fouten"]:
        _LOGGER.info("BT auto-update: HACS custom repositories ververst: %s", out)
    return out


def _lock(hass: HomeAssistant) -> asyncio.Lock:
    """v1.33.1: een run tegelijk (nachtelijk en manueel), anders dubbele installaties."""
    return hass.data.setdefault(_DATA_LOCK, asyncio.Lock())


async def async_run(hass: HomeAssistant, options: dict, trigger: str = "schema") -> dict:
    """Voer de updates uit. Geeft een samenvatting terug (ook voor tests)."""
    lock = _lock(hass)
    if lock.locked():
        _LOGGER.warning("BT auto-update: er loopt al een run, %s overgeslagen", trigger)
        return {"trigger": trigger, "stopped": "er loopt al een run"}
    async with lock:
        return await _async_run_locked(hass, options, trigger)


async def _async_run_locked(hass: HomeAssistant, options: dict, trigger: str) -> dict:
    result: dict[str, Any] = {
        "started": dt_util.now().isoformat(), "trigger": trigger,
        "installed": [], "failed": [], "skipped": [], "stopped": None,
    }
    hass.data[_DATA_LAST] = result

    if _branding_broken(hass):
        result["stopped"] = "zelfcontrole meldt een probleem, geen updates"
        _log(hass, result["stopped"])
        return result

    refresh = await async_refresh_hacs_custom(hass)
    if refresh["fouten"]:
        _log(hass, "HACS verversen deels mislukt: " + "; ".join(refresh["fouten"])[:300])
    todo, skipped = plan(hass, options)
    result["skipped"] = skipped
    if not todo:
        if skipped:
            _log(hass, "niets geinstalleerd; overgeslagen: " + "; ".join(skipped))
        return result

    use_backup = options.get(CONF_BACKUP, True)
    hacs_done = False
    # v1.48.2: herstart door Core/OS zelf; enkel als die installatie echt lukte.
    # Vroeger keken we naar de planning: mislukte Core, dan bleef een HACS-update
    # (zoals v1.48.1 op 26/10) inactief tot een toevallige herstart.
    system_restarts = False
    for index, upd in enumerate(todo):
        data: dict[str, Any] = {"entity_id": upd["entity_id"]}
        if use_backup and upd["backup"]:
            data["backup"] = True
        label = f"{upd['name']} {upd['from']} naar {upd['to']}"
        if data.get("backup") and backup_state(hass) not in (None, "idle"):
            _log(hass, f"back-up van HA bezig ({backup_state(hass)}), wachten voor {label}")
            busy = await async_wait_backup_idle(hass)
            if busy is not None:
                skipped.append(f"{label}: back-up van HA nog bezig ({busy}), volgende nacht")
                continue
        if upd["kind"] in ("core", "os"):
            # Vanaf hier herstart het systeem; eerst loggen wat al gebeurd is.
            _log(hass, "gestart: " + label + (" (met back-up)" if data.get("backup") else ""))
        tracker = _tracker(hass)
        if tracker:
            tracker.add_attempt(upd["entity_id"], upd["to"])
        installing = hass.data.setdefault(_DATA_INSTALLING, set())
        installing.add(upd["entity_id"])
        try:
            async with asyncio.timeout(_INSTALL_TIMEOUT):
                await async_install_with_backup_retry(hass, data, label)
            st = hass.states.get(upd["entity_id"])
            if upd["kind"] in ("core", "os"):
                system_restarts = True
            if st is None or st.state == "off" or st.attributes.get("installed_version") == upd["to"]:
                result["installed"].append(label)
                if tracker:
                    tracker.reset(upd["entity_id"])
            elif upd["kind"] in ("core", "os", "supervisor"):
                # Herstart volgt; of het gelukt is, zien we na de herstart.
                result["installed"].append(label + " (bevestiging na herstart)")
            else:
                result["failed"].append(f"{label}: na installatie nog altijd {st.attributes.get('installed_version')}")
                if tracker:
                    tracker.mark_done(upd["entity_id"])
            if upd["kind"] == "hacs":
                hacs_done = True
        except TimeoutError:
            installing.discard(upd["entity_id"])
            result["failed"].append(f"{label}: duurde langer dan {_INSTALL_TIMEOUT // 60} minuten")
            if tracker:
                tracker.mark_done(upd["entity_id"])
            _LOGGER.info("BT auto-update: %s duurde te lang", label)
        except Exception as err:  # noqa: BLE001
            installing.discard(upd["entity_id"])
            if backup_busy_error(err):
                # v1.48.1: net tegelijk met een back-up gestart; geen fout van de update
                if tracker:
                    tracker.undo_attempt(upd["entity_id"], upd["to"])
                skipped.append(f"{label}: back-up van HA bezig, volgende nacht")
                _LOGGER.info("BT auto-update: %s uitgesteld: %s", label, err)
                continue
            result["failed"].append(f"{label}: {err or type(err).__name__}")
            if tracker:
                tracker.mark_done(upd["entity_id"])
            _LOGGER.info("BT auto-update: %s mislukt: %s", label, err)
        else:
            installing.discard(upd["entity_id"])
            if upd["kind"] == "supervisor" and index + 1 < len(todo):
                # v1.33.1: de Supervisor herstart zichzelf na een update. Wat nu volgt,
                # zou falen en als mislukte poging tellen. De rest volgt de volgende nacht.
                for rest in todo[index + 1:]:
                    skipped.append(f"{rest['name']}: volgende nacht, Supervisor herstart")
                break

    # v1.33.1: met de opties van nu (ze kunnen tijdens de run gewijzigd zijn)
    getter = hass.data.get(_DATA_GETOPTS)
    async_sync_visibility(hass, getter() if getter else options)
    summary = []
    if result["installed"]:
        summary.append("geinstalleerd: " + "; ".join(result["installed"]))
    if result["failed"]:
        summary.append("mislukt: " + "; ".join(result["failed"]))
    if skipped:
        summary.append("overgeslagen: " + "; ".join(skipped))
    _log(hass, " | ".join(summary))

    async_dispatcher_send(hass, f"{DOMAIN}_status_changed", "updates")

    # HACS integraties worden pas actief na een herstart. Core/OS herstart al zelf.
    if hacs_done and not system_restarts:
        if trigger == "op afstand" and not is_night():
            result["herstart_gepland"] = async_defer_restart(hass, options, "HACS updates op afstand")
        else:
            async_cancel_deferred(hass)
            _log(hass, "herstart na HACS updates")
            await hass.services.async_call("homeassistant", "restart", {}, blocking=False)
    return result


@callback
def async_sync_visibility(hass: HomeAssistant, options: dict, only: str | None = None) -> None:
    """Verberg openstaande updates die wij afhandelen; toon ze na 2 mislukte pogingen."""
    tracker = _tracker(hass)
    if tracker is None:
        return
    reg = er.async_get(hass)
    issues = ir.async_get(hass)
    states = [hass.states.get(only)] if only else hass.states.async_all("update")
    for state in states:
        if state is None:
            continue
        eid = state.entity_id
        entry = reg.async_get(eid)
        if entry is None:
            continue
        if state.state not in ("on", "off"):
            # v1.32.1: bij het opstarten en tijdens een herstart zijn update
            # entiteiten even unavailable of unknown. Dan niets aanraken: anders
            # telden de mislukte pogingen terug vanaf 0 en kwam alles even tevoorschijn.
            continue
        kind = _kind(entry)
        latest = state.attributes.get("latest_version")
        pending = state.state == "on"
        _after_restart_check(hass, tracker, state, kind, pending)
        if not pending:
            tracker.reset(eid)
            tracker.forget_seen(eid)
        elif kind in HOLD_KINDS:
            # v1.48.0: de wachttijd start zodra de update verschijnt, niet pas 's nachts
            tracker.first_seen(eid, latest)
        # v1.48.2: de teller gaat al omhoog voor de installatie (Core herstart HA).
        # Tijdens die installatie is ze nog niet mislukt: anders vertrokken melding en
        # mail "2 keer mislukt" bij de start van poging 2 (27/10, 449 en 149).
        busy = eid in hass.data.get(_DATA_INSTALLING, ())
        failed = pending and not busy and tracker.count(eid, latest) >= MAX_ATTEMPTS
        hide = pending and not failed and _managed(state, kind, options)

        if hide and entry.hidden_by is None:
            reg.async_update_entity(eid, hidden_by=er.RegistryEntryHider.INTEGRATION)
            tracker.set_hidden(eid, True)
        elif not hide and eid in tracker.hidden:
            if entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
                reg.async_update_entity(eid, hidden_by=None)
            tracker.set_hidden(eid, False)

        issue_id = FAILED_ISSUE_PREFIX + eid
        if failed and _managed(state, kind, options):
            if issues.async_get_issue(DOMAIN, issue_id) is None:
                name = str(state.attributes.get("title") or state.attributes.get("friendly_name") or eid)
                _log(hass, f"{name} {latest}: {MAX_ATTEMPTS} keer mislukt, weer zichtbaar in de zijbalk")
                async_dispatcher_send(hass, f"{DOMAIN}_status_changed", "update_mislukt")
            ir.async_create_issue(
                hass, DOMAIN, issue_id,
                is_fixable=False, is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="update_failed",
                translation_placeholders={
                    "name": str(state.attributes.get("title") or state.attributes.get("friendly_name") or eid),
                    "version": str(latest),
                    "attempts": str(MAX_ATTEMPTS),
                },
            )
        elif issues.async_get_issue(DOMAIN, issue_id) is not None:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def _async_unhide_all(hass: HomeAssistant) -> None:
    tracker = _tracker(hass)
    if tracker is None:
        return
    reg = er.async_get(hass)
    for eid in list(tracker.hidden):
        entry = reg.async_get(eid)
        if entry and entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
            reg.async_update_entity(eid, hidden_by=None)
        tracker.set_hidden(eid, False)
    for issue_id in list(ir.async_get(hass).issues):
        if issue_id[0] == DOMAIN and issue_id[1].startswith(FAILED_ISSUE_PREFIX):
            ir.async_delete_issue(hass, DOMAIN, issue_id[1])


async def async_setup_visibility(hass: HomeAssistant, get_options) -> None:
    """Tracker laden en luisteren naar update entiteiten."""
    if _DATA_TRACKER not in hass.data:
        tracker = Tracker(hass)
        await tracker.async_load()
        hass.data[_DATA_TRACKER] = tracker
    if unsub := hass.data.pop(_DATA_VIS_UNSUB, None):
        unsub()
    hass.data[_DATA_GETOPTS] = get_options

    @callback
    def _filter(event_data) -> bool:
        return str(event_data.get("entity_id", "")).startswith("update.")

    @callback
    def _changed(event: Event) -> None:
        async_sync_visibility(hass, get_options(), event.data.get("entity_id"))

    hass.data[_DATA_VIS_UNSUB] = hass.bus.async_listen(
        EVENT_STATE_CHANGED, _changed, event_filter=_filter
    )
    apply_options(hass, get_options())


@callback
def apply_options(hass: HomeAssistant, options: dict) -> None:
    """Na het wijzigen van de opties: verbergen of alles weer tonen."""
    if options.get(CONF_ENABLED, False):
        async_sync_visibility(hass, options)
    else:
        _async_unhide_all(hass)


@callback
def async_teardown_visibility(hass: HomeAssistant) -> None:
    if unsub := hass.data.pop(_DATA_VIS_UNSUB, None):
        unsub()
    _async_unhide_all(hass)


@callback
def async_schedule(hass: HomeAssistant, options: dict) -> None:
    """(Her)plan de nachtelijke run volgens de opties."""
    if unsub := hass.data.pop(_DATA_UNSUB, None):
        unsub()
    if not options.get(CONF_ENABLED, False):
        _LOGGER.info("BT auto-update: uitgeschakeld")
        return
    at = _parse_time(options.get(CONF_TIME, DEFAULT_TIME))

    async def _fire(now: datetime) -> None:
        await async_run(hass, options, "schema")

    hass.data[_DATA_UNSUB] = async_track_time_change(
        hass, _fire, hour=at.hour, minute=at.minute, second=0
    )
    _LOGGER.info("BT auto-update: elke dag om %02d:%02d", at.hour, at.minute)


@callback
def async_unschedule(hass: HomeAssistant) -> None:
    if unsub := hass.data.pop(_DATA_UNSUB, None):
        unsub()
    async_cancel_deferred(hass)


def register_services(hass: HomeAssistant, get_options) -> None:
    """Service om de run meteen te starten, of enkel te tonen wat er zou gebeuren."""
    if hass.services.has_service(DOMAIN, "run_updates"):
        return

    async def _run(call: ServiceCall) -> dict:
        options = get_options()
        if call.data.get("dry_run", False):
            await async_refresh_hacs_custom(hass)
            todo, skipped = plan(hass, options)
            return {
                "zou_installeren": [f"{u['name']} {u['from']} naar {u['to']}" for u in todo],
                "overgeslagen": skipped,
                "branding_probleem": _branding_broken(hass),
            }
        if _lock(hass).locked():
            return {"gestart": [], "overgeslagen": [], "al_bezig": True,
                    "branding_probleem": _branding_broken(hass)}
        # Een run kan lang duren (apps, Core). Op de achtergrond starten en
        # meteen antwoorden; het resultaat komt in Activiteit en het log.
        todo, skipped = plan(hass, options)
        hass.async_create_background_task(
            async_run(hass, options, "manueel"), "btechnics_branding_run_updates"
        )
        return {
            "gestart": [f"{u['name']} {u['from']} naar {u['to']}" for u in todo],
            "overgeslagen": skipped,
            "branding_probleem": _branding_broken(hass),
        }

    from homeassistant.core import SupportsResponse
    from homeassistant.helpers.service import async_register_admin_service
    import voluptuous as vol
    # v1.33.1: enkel beheerders (installeert updates en herstart het systeem)
    async_register_admin_service(
        hass, DOMAIN, "run_updates", _run,
        schema=vol.Schema({vol.Optional("dry_run", default=False): bool}),
        supports_response=SupportsResponse.OPTIONAL,
    )
