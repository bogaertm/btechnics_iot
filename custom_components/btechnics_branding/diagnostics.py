"""Diagnose downloaden (v1.33.0).

Instellingen > Apparaten en diensten > Btechnics IOT > drie puntjes >
Diagnose downloaden. Handig bij support: alles wat de integratie weet in een
bestand, zonder sleutel.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import auto_update, status

TO_REDACT = {status.CONF_TOKEN}


def _summary(msg: dict) -> dict:
    """v1.35.0: diagnose komt soms in publieke issues; geen gebruikers, adres of logs."""
    msg = dict(msg)
    msg.pop("instance_id", None)
    msg["url"] = "**REDACTED**" if msg.get("url") else None
    users = msg.pop("users", None)
    msg["users"] = f"{len(users)} gebruikers" if isinstance(users, list) else None
    logs = msg.pop("logs", None) or {}
    msg["logs"] = {k: f"{len(v)} items" for k, v in logs.items() if isinstance(v, list)}
    return msg


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    options = dict(entry.options)
    tracker = auto_update._tracker(hass)  # noqa: SLF001
    health = hass.data.get("btechnics_branding_health") or {}
    return {
        "instellingen": async_redact_data(options, TO_REDACT),
        "zelfcontrole": {
            "backend": sorted(health.get("backend", set())),
            "frontend": sorted(health.get("frontend", set())),
        },
        "automatische_updates": {
            "laatste_run": hass.data.get("btechnics_branding_update_last"),
            "pogingen": tracker.attempts if tracker else None,
            "door_ons_verborgen": sorted(tracker.hidden) if tracker else None,
        },
        "op_afstand": (hass.data.get("btechnics_branding_remote") or {}).get("last"),
        "status_naar_btechnics": {
            "laatste": (hass.data.get("btechnics_branding_status") or {}).get("last"),
            "bericht": _summary(await status.async_build(hass, options, "diagnose")),
        },
    }
