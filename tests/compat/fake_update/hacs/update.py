"""Test HACS update (v1.43.0): herstart na installatie op afstand.

Start zonder openstaande update, zodat de gewone runs in de test hem niet
installeren. De service hacs.test_nieuwe_versie zet een nieuwe versie klaar.

v1.47.0: nabootsing van HACS intern (hass.data["hacs"]) zodat Btechnics IOT
custom repositories kan laten verversen. Pas na hacs.test_bij_verversen geeft
verversen een nieuwe versie; hacs.test_teller geeft het aantal verversingen.
"""
from types import SimpleNamespace

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import SupportsResponse


class _Repo:
    def __init__(self, hass, ent, full_name, rid):
        self.hass, self.ent = hass, ent
        self.data = SimpleNamespace(id=rid, full_name=full_name)

    async def update_repository(self, ignore_issues=False, force=False):
        st = self.hass.data["bt_fake_hacs"]
        st["refreshes"] += 1
        if st["bump"] and self.ent is not None:
            self.ent._attr_latest_version = "v1.1.0"


class _Coord:
    def __init__(self, ent):
        self.ent = ent

    def async_update_listeners(self):
        self.ent.async_write_ha_state()


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    ent = FakeHacsUpdate()
    async_add_entities([ent])
    hass.data["bt_fake_hacs"] = {"refreshes": 0, "bump": False}
    custom = _Repo(hass, ent, "bogaertm/test_hacs_integratie", "111")
    default = _Repo(hass, None, "hacs/default_repo", "222")

    async def _write():
        return None

    hass.data["hacs"] = SimpleNamespace(
        repositories=SimpleNamespace(
            list_downloaded=[custom, default],
            is_default=lambda rid: rid == "222",
        ),
        data=SimpleNamespace(async_write=_write),
        coordinators={"integration": _Coord(ent)},
    )

    async def _nieuw(call):
        ent._attr_latest_version = "v1.1.0"
        ent.async_write_ha_state()

    async def _bij_verversen(call):
        hass.data["bt_fake_hacs"]["bump"] = True

    async def _teller(call):
        return {"refreshes": hass.data["bt_fake_hacs"]["refreshes"]}

    hass.services.async_register("hacs", "test_nieuwe_versie", _nieuw)
    hass.services.async_register("hacs", "test_bij_verversen", _bij_verversen)
    hass.services.async_register("hacs", "test_teller", _teller, supports_response=SupportsResponse.ONLY)


class FakeHacsUpdate(UpdateEntity):
    _attr_unique_id = "fake_hacs_integratie"
    _attr_name = "Test HACS integratie"
    _attr_title = "Test HACS integratie"
    _attr_installed_version = "v1.0.0"
    _attr_latest_version = "v1.0.0"
    _attr_supported_features = UpdateEntityFeature.INSTALL

    async def async_install(self, version, backup, **kwargs):
        self._attr_installed_version = self._attr_latest_version
        self.async_write_ha_state()
