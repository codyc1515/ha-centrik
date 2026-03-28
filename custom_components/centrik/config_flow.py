"""Config flow for Centrik."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .api import CentrikApiClient, CentrikApiError, CentrikAuthenticationError
from .const import (
    CONF_APP_BUNDLE,
    CONF_APP_VERSION,
    CONF_BASE_URL,
    CONF_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
    CONF_PRESCRIPTION_NOTIFICATION_ENABLED,
    CONF_REPEAT_NOTIFICATION_DAYS_BEFORE,
    CONF_REPEAT_NOTIFICATION_ENABLED,
    CONF_VARIANT,
    DEFAULT_APP_BUNDLE,
    DEFAULT_APP_VERSION,
    DEFAULT_BASE_URL,
    DEFAULT_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
    DEFAULT_PRESCRIPTION_NOTIFICATION_ENABLED,
    DEFAULT_REPEAT_NOTIFICATION_DAYS_BEFORE,
    DEFAULT_REPEAT_NOTIFICATION_ENABLED,
    DOMAIN,
    VARIANT_PHARMACY,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CentrikConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Centrik."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_VARIANT]}::{user_input[CONF_USERNAME]}")
            self._abort_if_unique_id_configured()

            try:
                await self._async_validate_input(user_input)
            except InvalidAuth as err:
                _LOGGER.warning("Centrik config flow invalid auth: %s", err)
                errors["base"] = "invalid_auth"
            except CannotConnect as err:
                _LOGGER.warning("Centrik config flow cannot connect: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Centrik config flow unknown login error for variant=%s base_url=%s",
                    user_input.get(CONF_VARIANT),
                    DEFAULT_BASE_URL,
                )
                errors["base"] = "unknown"
            else:
                entry_data = {
                    **user_input,
                    CONF_BASE_URL: DEFAULT_BASE_URL,
                    CONF_APP_BUNDLE: DEFAULT_APP_BUNDLE,
                    CONF_APP_VERSION: DEFAULT_APP_VERSION,
                }
                return self.async_create_entry(
                    title=f"Centrik ({user_input[CONF_USERNAME]})",
                    data=entry_data,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_VARIANT, default=VARIANT_PHARMACY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=VARIANT_PHARMACY,
                                label="Unichem & Life Pharmacy",
                            )
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_REPEAT_NOTIFICATION_ENABLED,
                    default=DEFAULT_REPEAT_NOTIFICATION_ENABLED,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_REPEAT_NOTIFICATION_DAYS_BEFORE,
                    default=DEFAULT_REPEAT_NOTIFICATION_DAYS_BEFORE,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=14,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PRESCRIPTION_NOTIFICATION_ENABLED,
                    default=DEFAULT_PRESCRIPTION_NOTIFICATION_ENABLED,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
                    default=DEFAULT_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=14,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_validate_input(self, data: dict[str, Any]) -> None:
        """Validate credentials by executing the live auth/data flow."""
        api = CentrikApiClient(
            self.hass,
            email=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            base_url=DEFAULT_BASE_URL,
            app_bundle=DEFAULT_APP_BUNDLE,
            app_version=DEFAULT_APP_VERSION,
            variant=data[CONF_VARIANT],
        )

        try:
            await api.async_refresh_medications()
        except CentrikAuthenticationError as err:
            raise InvalidAuth(str(err)) from err
        except CentrikApiError as err:
            raise CannotConnect(str(err)) from err
