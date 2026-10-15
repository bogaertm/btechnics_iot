"""Enkel voor tests (v1.46.0): nabootsing van btechnics_toegang.werk."""
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError

DOMAIN = "btechnics_toegang"


async def async_setup(hass, config):
    async def werk(call):
        actie = call.data.get("actie")
        velden = call.data.get("velden") or {}
        if actie == "overzicht":
            return {"schema": 1, "deuren": [{"id": "voordeur", "naam": "Voordeur"}],
                    "personen": [{"id": "p1", "naam": "Jelle"}]}
        if actie == "uitnodigen":
            return {"ok": True, "persoon": velden.get("persoon"), "url": "https://toegang.test/geheim-uitnodiging"}
        if actie == "tijdelijke_code":
            return {"ok": True, "deur": velden.get("deur"), "code": "918273"}
        raise HomeAssistantError(f"onbekende deur of actie: {actie}")

    hass.services.async_register(DOMAIN, "werk", werk, supports_response=SupportsResponse.ONLY)
    return True
