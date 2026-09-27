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
from datetime import datetime, time as dtime
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
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


class Tracker:
    """Pogingen per update en welke entiteiten wij verborgen hebben (blijft bewaard)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict] = Store(hass, 1, f"{DOMAIN}.auto_update")
        self.attempts: dict[str, dict] = {}
        self.hidden: set[str] = set()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.attempts = data.get("attempts", {})
        self.hidden = set(data.get("hidden", []))

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {"attempts": self.attempts, "hidden": sorted(self.hidden)}, 2
        )

    def count(self, entity_id: str, version: str | None) -> int:
        a = self.attempts.get(entity_id)
        return a["count"] if a and a.get("version") == version else 0

    def add_attempt(self, entity_id: str, version: str | None) -> int:
        n = self.count(entity_id, version) + 1
        self.attempts[entity_id] = {"version": version, "count": n,
                                    "last": dt_util.utcnow().isoformat()}
        self._save()
        return n

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


def _log(hass: HomeAssistant, message: str) -> None:
    """Zichtbaar in Activiteit (logboek) en in het HA log."""
    _LOGGER.warning("BT auto-update: %s", message)
    if not hass.services.has_service("logbook", "log"):
        return
    try:
        hass.async_create_task(hass.services.async_call(
            "logbook", "log",
            {"name": "Btechnics IOT updates", "message": message, "domain": DOMAIN},
        ))
    except Exception:  # noqa: BLE001
        pass


async def async_run(hass: HomeAssistant, options: dict, trigger: str = "schema") -> dict:
    """Voer de updates uit. Geeft een samenvatting terug (ook voor tests)."""
    result: dict[str, Any] = {
        "started": dt_util.now().isoformat(), "trigger": trigger,
        "installed": [], "failed": [], "skipped": [], "stopped": None,
    }
    hass.data[_DATA_LAST] = result

    if _branding_broken(hass):
        result["stopped"] = "zelfcontrole meldt een probleem, geen updates"
        _log(hass, result["stopped"])
        return result

    todo, skipped = plan(hass, options)
    result["skipped"] = skipped
    if not todo:
        if skipped:
            _log(hass, "niets geinstalleerd; overgeslagen: " + "; ".join(skipped))
        return result

    use_backup = options.get(CONF_BACKUP, True)
    hacs_done = False
    for upd in todo:
        data: dict[str, Any] = {"entity_id": upd["entity_id"]}
        if use_backup and upd["backup"]:
            data["backup"] = True
        label = f"{upd['name']} {upd['from']} naar {upd['to']}"
        if upd["kind"] in ("core", "os"):
            # Vanaf hier herstart het systeem; eerst loggen wat al gebeurd is.
            _log(hass, "gestart: " + label + (" (met back-up)" if data.get("backup") else ""))
        tracker = _tracker(hass)
        if tracker:
            tracker.add_attempt(upd["entity_id"], upd["to"])
        try:
            async with asyncio.timeout(_INSTALL_TIMEOUT):
                await hass.services.async_call("update", "install", data, blocking=True)
            st = hass.states.get(upd["entity_id"])
            if st is None or st.state == "off" or st.attributes.get("installed_version") == upd["to"]:
                result["installed"].append(label)
                if tracker:
                    tracker.reset(upd["entity_id"])
            elif upd["kind"] in ("core", "os", "supervisor"):
                # Herstart volgt; of het gelukt is, zien we na de herstart.
                result["installed"].append(label + " (bevestiging na herstart)")
            else:
                result["failed"].append(f"{label}: na installatie nog altijd {st.attributes.get('installed_version')}")
            if upd["kind"] == "hacs":
                hacs_done = True
        except Exception as err:  # noqa: BLE001
            result["failed"].append(f"{label}: {err}")
            _LOGGER.warning("BT auto-update: %s mislukt: %s", label, err)

    async_sync_visibility(hass, options)
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
    if hacs_done and not any(u["kind"] in ("core", "os") for u in todo):
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
        if not pending:
            tracker.reset(eid)
        failed = pending and tracker.count(eid, latest) >= MAX_ATTEMPTS
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
    running = {"busy": False}

    async def _fire(now: datetime) -> None:
        if running["busy"]:
            return
        running["busy"] = True
        try:
            await async_run(hass, options, "schema")
        finally:
            running["busy"] = False

    hass.data[_DATA_UNSUB] = async_track_time_change(
        hass, _fire, hour=at.hour, minute=at.minute, second=0
    )
    _LOGGER.info("BT auto-update: elke dag om %02d:%02d", at.hour, at.minute)


@callback
def async_unschedule(hass: HomeAssistant) -> None:
    if unsub := hass.data.pop(_DATA_UNSUB, None):
        unsub()


def register_services(hass: HomeAssistant, get_options) -> None:
    """Service om de run meteen te starten, of enkel te tonen wat er zou gebeuren."""
    if hass.services.has_service(DOMAIN, "run_updates"):
        return

    async def _run(call: ServiceCall) -> dict:
        options = get_options()
        if call.data.get("dry_run", False):
            todo, skipped = plan(hass, options)
            return {
                "zou_installeren": [f"{u['name']} {u['from']} naar {u['to']}" for u in todo],
                "overgeslagen": skipped,
                "branding_probleem": _branding_broken(hass),
            }
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
    import voluptuous as vol
    hass.services.async_register(
        DOMAIN, "run_updates", _run,
        schema=vol.Schema({vol.Optional("dry_run", default=False): bool}),
        supports_response=SupportsResponse.OPTIONAL,
    )
