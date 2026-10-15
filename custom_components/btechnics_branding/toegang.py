"""Deurtoegang beheren vanuit Btechnics Work (v1.46.0).

De eigenlijke logica zit in de integratie btechnics_toegang (v0.6.0 of hoger),
die de dienst btechnics_toegang.werk aanbiedt. Wij geven de opdracht van de
Work-app door en sturen het antwoord terug.

- Standaard UIT, per klant aan te zetten ("Deurtoegang beheren vanuit Btechnics Work").
- Geheimen in het antwoord ("url" bij uitnodigen/portaal_link, "code" bij
  tijdelijke_code) gaan een keer naar de Work-app en worden nooit bewaard.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .users import CommandError

CONF_REMOTE_TOEGANG = "remote_toegang"
KIND = "toegang"
SERVICE_DOMAIN = "btechnics_toegang"
SERVICE = "werk"
SECRET_KEYS = ("url", "code")
_OFF = "deurtoegang op afstand staat uit bij deze klant"


def enabled(options: dict) -> bool:
    return bool(options.get(CONF_REMOTE_TOEGANG, False))


def available(hass: HomeAssistant) -> bool:
    return hass.services.has_service(SERVICE_DOMAIN, SERVICE)


async def _call(hass: HomeAssistant, actie: str, velden: dict, door: str | None) -> Any:
    data: dict[str, Any] = {"actie": actie, "velden": velden}
    if door:
        data["door"] = door
    return await hass.services.async_call(
        SERVICE_DOMAIN, SERVICE, data, blocking=True, return_response=True,
    )


async def async_execute(hass: HomeAssistant, options: dict, cmd: dict) -> Any:
    if not enabled(options):
        raise ValueError(_OFF)
    actie = cmd.get("actie")
    if not isinstance(actie, str) or not actie.strip() or len(actie) > 64:
        raise ValueError("actie ontbreekt of is ongeldig")
    velden = cmd.get("velden", {})
    if velden is None:
        velden = {}
    if not isinstance(velden, dict):
        raise ValueError("velden moet een object zijn")
    door = cmd.get("door")
    if door is not None and not isinstance(door, str):
        raise ValueError("door moet tekst zijn")
    if not available(hass):
        raise CommandError("Btechnics Toegang is niet geinstalleerd bij deze klant",
                           "toegang_ontbreekt")
    try:
        return await _call(hass, actie.strip(), velden, (door or "").strip()[:80] or None)
    except HomeAssistantError as err:
        msg = str(err) or type(err).__name__
        raise CommandError(msg, "toegang", msg) from err


def strip_secrets(data: Any) -> Any:
    """Kopie zonder url en code (op elk niveau)."""
    if isinstance(data, dict):
        return {k: strip_secrets(v) for k, v in data.items() if k not in SECRET_KEYS}
    if isinstance(data, list):
        return [strip_secrets(v) for v in data]
    return data


def has_secret(data: Any) -> bool:
    if isinstance(data, dict):
        return any(k in SECRET_KEYS for k in data) or any(has_secret(v) for v in data.values())
    if isinstance(data, list):
        return any(has_secret(v) for v in data)
    return False


async def async_status(hass: HomeAssistant, options: dict) -> dict | None:
    """Blok "toegang" voor de status: het overzicht, of {"fout": ...}."""
    if not enabled(options) or not available(hass):
        return None
    try:
        data = await _call(hass, "overzicht", {}, "status")
    except Exception as err:  # noqa: BLE001
        return {"fout": (str(err) or type(err).__name__)[:300]}
    return strip_secrets(data) if isinstance(data, (dict, list)) else data
