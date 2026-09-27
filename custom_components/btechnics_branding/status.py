"""Status naar Btechnics (v1.33.0).

Elke installatie stuurt elk uur, en meteen bij een probleem, een korte status
naar de Work-app van Btechnics (work.btechnics.be). Daar komt het overzicht van
alle klanten en de mail bij een probleem:
- een automatische update die 2 keer mislukt is,
- de zelfcontrole die meldt dat de branding niet meer werkt,
- een klant waarvan al 24 uur niets meer binnenkwam (dat beslist de Work-app).

Er wordt enkel iets verstuurd als er een sleutel is ingevuld bij de instellingen.
Er gaan geen persoonsgegevens, wachtwoorden of toestelgegevens mee: enkel
versies, de naam van de installatie en de stand van de updates.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DOMAIN = "btechnics_branding"
SIGNAL_CHANGED = f"{DOMAIN}_status_changed"
CONF_URL = "status_url"
CONF_TOKEN = "status_token"
DEFAULT_URL = "https://work.btechnics.be/api/iot/status"
SCHEMA_VERSION = 1

_INTERVAL = timedelta(hours=1)
_DEBOUNCE_S = 10
_TIMEOUT_S = 20
_DATA = "btechnics_branding_status"


def _state(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(_DATA, {"unsubs": [], "pending": None, "last": None, "reasons": set()})


async def async_build(hass: HomeAssistant, options: dict, reason: str) -> dict[str, Any]:
    """Het bericht dat naar de Work-app gaat."""
    from homeassistant.helpers import instance_id
    from homeassistant.loader import async_get_integration

    from . import auto_update

    try:
        integration_version = str((await async_get_integration(hass, DOMAIN)).version)
    except Exception:  # noqa: BLE001
        integration_version = None
    try:
        from homeassistant.helpers.system_info import async_get_system_info
        info = await async_get_system_info(hass)
    except Exception:  # noqa: BLE001
        info = {}
    try:
        from homeassistant.helpers.network import NoURLAvailableError, get_url
        try:
            url = get_url(hass, allow_internal=False, allow_ip=False)
        except NoURLAvailableError:
            url = None
    except Exception:  # noqa: BLE001
        url = None

    health = hass.data.get("btechnics_branding_health") or {}
    problems = sorted(set(health.get("backend", set())) | set(health.get("frontend", set())))

    tracker = auto_update._tracker(hass)  # noqa: SLF001
    reg = er.async_get(hass)
    pending: list[dict] = []
    for st in hass.states.async_all("update"):
        if st.state != "on":
            continue
        entry = reg.async_get(st.entity_id)
        latest = st.attributes.get("latest_version")
        attempts = tracker.count(st.entity_id, latest) if tracker else 0
        pending.append({
            "entity_id": st.entity_id,
            "name": str(st.attributes.get("title") or st.attributes.get("friendly_name") or st.entity_id),
            "installed": st.attributes.get("installed_version"),
            "latest": latest,
            "kind": auto_update._kind(entry),  # noqa: SLF001
            "hidden": bool(entry and entry.hidden_by),
            "attempts": attempts,
            "failed": attempts >= auto_update.MAX_ATTEMPTS,
        })

    last = hass.data.get("btechnics_branding_update_last")
    return {
        "schema": SCHEMA_VERSION,
        "instance_id": await instance_id.async_get(hass),
        "name": hass.config.location_name,
        "url": url,
        "reason": reason,
        "sent_at": dt_util.utcnow().isoformat(),
        "versions": {
            "integration": integration_version,
            "home_assistant": HA_VERSION,
            "installation_type": info.get("installation_type"),
            "os": info.get("os_name"),
            "os_version": info.get("os_version"),
        },
        "branding": {"ok": not problems, "problems": problems},
        "auto_update": {
            "enabled": bool(options.get(auto_update.CONF_ENABLED, False)),
            "time": options.get(auto_update.CONF_TIME, auto_update.DEFAULT_TIME),
            "categories": list(options.get(auto_update.CONF_CATEGORIES, auto_update.DEFAULT_CATEGORIES)),
            "last_run": last,
        },
        "updates": {
            "pending": pending,
            "failed": [p for p in pending if p["failed"]],
        },
    }


async def async_send(hass: HomeAssistant, options: dict, reason: str) -> dict[str, Any]:
    """Verstuur de status. Geeft het resultaat terug (ook voor de service en diagnose)."""
    token = (options.get(CONF_TOKEN) or "").strip()
    url = (options.get(CONF_URL) or DEFAULT_URL).strip()
    result: dict[str, Any] = {"at": dt_util.utcnow().isoformat(), "reason": reason, "url": url}
    if not token:
        result.update(ok=False, error="geen sleutel ingevuld")
        _state(hass)["last"] = result
        return result
    payload = await async_build(hass, options, reason)
    try:
        session = async_get_clientsession(hass)
        async with asyncio.timeout(_TIMEOUT_S):
            resp = await session.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {token}", "User-Agent": f"btechnics-iot/{payload['versions']['integration']}"},
            )
            result["http"] = resp.status
            result["ok"] = 200 <= resp.status < 300
            if not result["ok"]:
                result["error"] = (await resp.text())[:200]
    except Exception as err:  # noqa: BLE001
        result.update(ok=False, error=str(err) or type(err).__name__)
    if not result.get("ok"):
        _LOGGER.warning("BT status naar Btechnics niet gelukt: %s", result.get("error") or result.get("http"))
    _state(hass)["last"] = result
    return result


@callback
def async_request_send(hass: HomeAssistant, get_options, reason: str) -> None:
    """Binnen enkele seconden versturen; meerdere aanvragen worden samengevoegd."""
    st = _state(hass)
    st["reasons"].add(reason)
    if st["pending"] is not None:
        return

    async def _go(_now) -> None:
        st["pending"] = None
        reasons = ",".join(sorted(st["reasons"])) or reason
        st["reasons"] = set()
        await async_send(hass, get_options(), reasons)

    st["pending"] = async_call_later(hass, _DEBOUNCE_S, _go)


async def async_setup(hass: HomeAssistant, get_options) -> None:
    """Elk uur versturen, en meteen als er iets verandert."""
    async_teardown(hass)
    st = _state(hass)

    async def _hourly(_now) -> None:
        await async_send(hass, get_options(), "uur")

    @callback
    def _changed(reason: str = "wijziging") -> None:
        async_request_send(hass, get_options, reason)

    st["unsubs"] = [
        async_track_time_interval(hass, _hourly, _INTERVAL),
        async_dispatcher_connect(hass, SIGNAL_CHANGED, _changed),
    ]
    async_request_send(hass, get_options, "start")


@callback
def async_teardown(hass: HomeAssistant) -> None:
    st = _state(hass)
    for unsub in st["unsubs"]:
        unsub()
    st["unsubs"] = []
    if st["pending"] is not None:
        st["pending"]()
        st["pending"] = None


def register_services(hass: HomeAssistant, get_options) -> None:
    """Service om de status meteen te versturen (en te bekijken wat er verstuurd wordt)."""
    if hass.services.has_service(DOMAIN, "send_status"):
        return
    from homeassistant.core import ServiceCall, SupportsResponse

    async def _send(call: ServiceCall) -> dict:
        options = get_options()
        result = await async_send(hass, options, "manueel")
        return {"resultaat": result, "bericht": await async_build(hass, options, "manueel")}

    hass.services.async_register(DOMAIN, "send_status", _send, supports_response=SupportsResponse.OPTIONAL)
