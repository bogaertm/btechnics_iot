"""Config flow voor Btechnics IOT."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

DOMAIN = "btechnics_branding"
DEFAULT_LOGIN_TEXT = "Btechnics IOT"
DEFAULT_SIDEBAR_TEXT = "Btechnics IOT"
DEFAULT_LOGIN_SIZE = 24
DEFAULT_SIDEBAR_SIZE = 16


class BtechnicsBrandingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow voor Btechnics IOT."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Stap 1: installeren."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            return self.async_create_entry(title="Btechnics IOT", data={})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Opties flow aanmaken."""
        return BtechnicsBrandingOptionsFlow()


class BtechnicsBrandingOptionsFlow(config_entries.OptionsFlow):
    """Opties flow voor teksten en groottes instellen."""

    async def async_step_init(self, user_input=None):
        """Toon instellingen."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("login_text",
                    default=current.get("login_text", DEFAULT_LOGIN_TEXT)): str,
                vol.Optional("login_text_size",
                    default=current.get("login_text_size", DEFAULT_LOGIN_SIZE)): int,
                vol.Optional("sidebar_text",
                    default=current.get("sidebar_text", DEFAULT_SIDEBAR_TEXT)): str,
                vol.Optional("sidebar_text_size",
                    default=current.get("sidebar_text_size", DEFAULT_SIDEBAR_SIZE)): int,
            }),
        )
