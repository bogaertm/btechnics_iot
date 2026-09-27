"""Test update entiteiten voor de compatibiliteitstest van Btechnics IOT."""
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.exceptions import HomeAssistantError


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([
        FakeUpdate("fake_ok", "Test OK", fail=False),
        FakeUpdate("fake_fail", "Test Faalt", fail=True),
        FakeUpdate("fake_manual", "Test Enkel Melding", fail=False, installable=False),
    ])


class FakeUpdate(UpdateEntity):
    def __init__(self, uid, title, fail, installable=True):
        self._attr_unique_id = uid
        self._attr_name = title
        self._attr_title = title
        self._attr_installed_version = "1.0.0"
        self._attr_latest_version = "2.0.0"
        self._attr_supported_features = UpdateEntityFeature.INSTALL if installable else UpdateEntityFeature(0)
        self._fail = fail

    @property
    def entity_picture(self):
        # Zoals HACS (custom_components/hacs/update.py): icoon van de brands CDN,
        # waar Btechnics niet op staat -> "icon not available"
        return "https://brands.home-assistant.io/_/btechnics_branding/icon.png"

    async def async_install(self, version, backup, **kwargs):
        if self._fail:
            raise HomeAssistantError("testfout: installatie mislukt")
        self._attr_installed_version = self._attr_latest_version
        self.async_write_ha_state()
