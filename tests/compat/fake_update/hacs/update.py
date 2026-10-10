"""Test HACS update (v1.43.0): herstart na installatie op afstand.

Start zonder openstaande update, zodat de gewone runs in de test hem niet
installeren. De service hacs.test_nieuwe_versie zet een nieuwe versie klaar.
"""
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    ent = FakeHacsUpdate()
    async_add_entities([ent])

    async def _nieuw(call):
        ent._attr_latest_version = "v1.1.0"
        ent.async_write_ha_state()

    hass.services.async_register("hacs", "test_nieuwe_versie", _nieuw)


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
