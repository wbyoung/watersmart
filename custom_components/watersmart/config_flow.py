"""Config flow for WaterSmart integration."""

from asyncio import timeout
import logging
from typing import Any

from aiohttp import ClientError
from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .client import AuthenticationError, WaterSmartClient
from .const import DOMAIN
from .helpers import parse_hostname

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.

    Returns:
        The details for creating a new config entry.

    Raises:
        CannotConnect: For connection errors.
        InvalidAuth: For authentication errors.
    """

    session = async_get_clientsession(hass)
    hostname, domain = parse_hostname(data[CONF_HOST])

    client = WaterSmartClient(
        hostname,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        domain=domain,
        session=session,
    )

    try:
        async with timeout(30):
            account_number = await client.async_get_account_number()
    except (ClientConnectorError, TimeoutError, ClientError) as error:
        raise CannotConnect from error
    except AuthenticationError as error:
        raise InvalidAuth from error

    if not account_number:
        raise InvalidAuth

    return {"title": f"{data[CONF_HOST]} ({data[CONF_USERNAME]})"}


class WaterSmartConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for WaterSmart."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Returns:
            The config flow result.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
