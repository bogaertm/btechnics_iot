"""Config flow voor Btechnics IOT."""
import voluptuous as vol
from homeassistant import config_entries

DOMAIN = "btechnics_branding"


class BtechnicsBrandingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow voor Btechnics IOT."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Stap 1."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            return self.async_create_entry(title="Btechnics IOT", data={})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )
