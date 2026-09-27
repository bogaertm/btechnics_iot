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
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time as dtime
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change
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
        try:
            async with asyncio.timeout(_INSTALL_TIMEOUT):
                await hass.services.async_call("update", "install", data, blocking=True)
            result["installed"].append(label)
            if upd["kind"] == "hacs":
                hacs_done = True
        except Exception as err:  # noqa: BLE001
            result["failed"].append(f"{label}: {err}")
            _LOGGER.warning("BT auto-update: %s mislukt: %s", label, err)

    summary = []
    if result["installed"]:
        summary.append("geinstalleerd: " + "; ".join(result["installed"]))
    if result["failed"]:
        summary.append("mislukt: " + "; ".join(result["failed"]))
    if skipped:
        summary.append("overgeslagen: " + "; ".join(skipped))
    _log(hass, " | ".join(summary))

    # HACS integraties worden pas actief na een herstart. Core/OS herstart al zelf.
    if hacs_done and not any(u["kind"] in ("core", "os") for u in todo):
        _log(hass, "herstart na HACS updates")
        await hass.services.async_call("homeassistant", "restart", {}, blocking=False)
    return result


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
