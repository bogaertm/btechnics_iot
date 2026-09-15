"""Config flow voor Btechnics IOT."""
import logging
import pathlib
import shutil

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import callback
from homeassistant.helpers import selector

DOMAIN = "btechnics_branding"
DEFAULT_LOGIN_TEXT = "Btechnics IOT"
DEFAULT_SIDEBAR_TEXT = "Btechnics IOT"
DEFAULT_LOGIN_SIZE = 24
DEFAULT_SIDEBAR_SIZE = 16
DEFAULT_ZOOM_DESKTOP = 80
DEFAULT_ZOOM_MOBILE = 85
DEFAULT_ZOOM_BREAKPOINT = 870
DEFAULT_CUSTOMER_LOGO_SCALE = 100

# Map (onder de HA config map) waar het klantenlogo bewaard wordt
CUSTOMER_LOGO_DIR = "btechnics_branding"
CUSTOMER_LOGO_EXT = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")

_LOGGER = logging.getLogger(__name__)


def _customer_logo_dir(hass) -> pathlib.Path:
    return pathlib.Path(hass.config.path(CUSTOMER_LOGO_DIR))


def _save_uploaded_logo(hass, file_id: str) -> str | None:
    """Kopieer het geuploade bestand naar de config map. Draait in de executor."""
    target_dir = _customer_logo_dir(hass)
    target_dir.mkdir(parents=True, exist_ok=True)
    with process_uploaded_file(hass, file_id) as uploaded:
        ext = uploaded.suffix.lower()
        if ext not in CUSTOMER_LOGO_EXT:
            return None
        _remove_customer_logo(hass)
        target = target_dir / f"customer_logo{ext}"
        shutil.copyfile(uploaded, target)
        return target.name


def _remove_customer_logo(hass) -> None:
    """Verwijder een eerder klantenlogo. Draait in de executor."""
    target_dir = _customer_logo_dir(hass)
    if not target_dir.is_dir():
        return
    for path in target_dir.glob("customer_logo.*"):
        try:
            path.unlink()
        except OSError as err:
            _LOGGER.warning("BT: klantenlogo %s niet verwijderd: %s", path, err)


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
    """Opties flow voor teksten, groottes, zoom en klantenlogo."""

    async def async_step_init(self, user_input=None):
        """Toon instellingen."""
        errors = {}
        current = dict(self.config_entry.options)

        if user_input is not None:
            options = dict(current)
            file_id = user_input.pop("customer_logo", None)
            remove = user_input.pop("remove_customer_logo", False)
            options.update(user_input)

            if remove:
                await self.hass.async_add_executor_job(_remove_customer_logo, self.hass)
                options.pop("customer_logo_file", None)

            if file_id:
                try:
                    name = await self.hass.async_add_executor_job(
                        _save_uploaded_logo, self.hass, file_id
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("BT: klantenlogo upload mislukt: %s", err)
                    name = None
                if name:
                    options["customer_logo_file"] = name
                else:
                    errors["customer_logo"] = "invalid_logo"

            if not errors:
                return self.async_create_entry(title="", data=options)

        has_logo = bool(current.get("customer_logo_file"))
        schema = {
            vol.Optional("login_text",
                default=current.get("login_text", DEFAULT_LOGIN_TEXT)): str,
            vol.Optional("login_text_size",
                default=current.get("login_text_size", DEFAULT_LOGIN_SIZE)): int,
            vol.Optional("sidebar_text",
                default=current.get("sidebar_text", DEFAULT_SIDEBAR_TEXT)): str,
            vol.Optional("sidebar_text_size",
                default=current.get("sidebar_text_size", DEFAULT_SIDEBAR_SIZE)): int,
            vol.Optional("zoom_desktop",
                default=current.get("zoom_desktop", DEFAULT_ZOOM_DESKTOP)): vol.All(int, vol.Range(min=50, max=150)),
            vol.Optional("zoom_mobile",
                default=current.get("zoom_mobile", DEFAULT_ZOOM_MOBILE)): vol.All(int, vol.Range(min=50, max=150)),
            vol.Optional("zoom_breakpoint",
                default=current.get("zoom_breakpoint", DEFAULT_ZOOM_BREAKPOINT)): vol.All(int, vol.Range(min=300, max=2000)),
            vol.Optional("customer_logo"): selector.FileSelector(
                selector.FileSelectorConfig(accept="image/*")
            ),
            vol.Optional("customer_logo_scale",
                default=current.get("customer_logo_scale", DEFAULT_CUSTOMER_LOGO_SCALE)): vol.All(int, vol.Range(min=25, max=300)),
        }
        if has_logo:
            schema[vol.Optional("remove_customer_logo", default=False)] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "customer_logo_status": current.get("customer_logo_file") or "-",
            },
        )
