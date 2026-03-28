"""Data update coordinator for Centrik."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    VARIANT_PHARMACY,
)
from .models import MedicationSchedule

_LOGGER = logging.getLogger(__name__)


class CentrikDataUpdateCoordinator(DataUpdateCoordinator[list[MedicationSchedule]]):
    """Coordinator for Centrik medication data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        self._active_notification_ids: set[str] = set()

        self.api = CentrikApiClient(
            hass,
            email=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            app_bundle=entry.data.get(CONF_APP_BUNDLE, DEFAULT_APP_BUNDLE),
            app_version=entry.data.get(CONF_APP_VERSION, DEFAULT_APP_VERSION),
            variant=entry.data.get(CONF_VARIANT, VARIANT_PHARMACY),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> list[MedicationSchedule]:
        try:
            medications = await self.api.async_refresh_medications()
            await self._async_update_repeat_notifications(medications)
            return medications
        except CentrikAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except CentrikApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Unexpected Centrik update error: {err}") from err

    async def _async_update_repeat_notifications(
        self, medications: list[MedicationSchedule]
    ) -> None:
        """Create/dismiss repeat reminder notifications based on config."""
        repeat_enabled = self.config_entry.data.get(
            CONF_REPEAT_NOTIFICATION_ENABLED, DEFAULT_REPEAT_NOTIFICATION_ENABLED
        )
        prescription_enabled = self.config_entry.data.get(
            CONF_PRESCRIPTION_NOTIFICATION_ENABLED,
            DEFAULT_PRESCRIPTION_NOTIFICATION_ENABLED,
        )

        if not repeat_enabled and not prescription_enabled:
            for notification_id in self._active_notification_ids:
                persistent_notification.async_dismiss(self.hass, notification_id)
            self._active_notification_ids.clear()
            return

        repeat_days_before = int(
            self.config_entry.data.get(
                CONF_REPEAT_NOTIFICATION_DAYS_BEFORE,
                DEFAULT_REPEAT_NOTIFICATION_DAYS_BEFORE,
            )
        )
        prescription_days_before = int(
            self.config_entry.data.get(
                CONF_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
                DEFAULT_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE,
            )
        )
        today = dt_util.now().date()
        active_ids_now: set[str] = set()

        for medication in medications:
            repeat_order_date = medication.next_due_date - timedelta(days=repeat_days_before)
            if repeat_enabled and today >= repeat_order_date:
                notification_id = (
                    f"{DOMAIN}_{self.config_entry.entry_id}_{medication.medication_id}"
                    f"_repeat_{medication.next_due_date.isoformat()}"
                )
                active_ids_now.add(notification_id)

                message = (
                    f"Medication: **{medication.name}**\n\n"
                    f"Next repeat due: **{medication.next_due_date.isoformat()}**\n"
                    f"Reminder lead time: **{repeat_days_before} day(s)**\n"
                    f"Repeats remaining: **{medication.repeats_remaining}**"
                )
                persistent_notification.async_create(
                    self.hass,
                    message=message,
                    title="Centrik Repeat Reminder",
                    notification_id=notification_id,
                )

            if prescription_enabled:
                prescription_end_date = medication.next_due_date + timedelta(
                    days=medication.repeats_remaining * medication.schedule_days
                )
                prescription_order_date = prescription_end_date - timedelta(
                    days=prescription_days_before
                )
                if today >= prescription_order_date:
                    notification_id = (
                        f"{DOMAIN}_{self.config_entry.entry_id}_{medication.medication_id}"
                        f"_prescription_{prescription_end_date.isoformat()}"
                    )
                    active_ids_now.add(notification_id)

                    message = (
                        f"Medication: **{medication.name}**\n\n"
                        f"Prescription likely runs out: **{prescription_end_date.isoformat()}**\n"
                        f"Reminder lead time: **{prescription_days_before} day(s)**\n"
                        "Consider contacting your doctor for a new prescription."
                    )
                    persistent_notification.async_create(
                        self.hass,
                        message=message,
                        title="Centrik Prescription Reminder",
                        notification_id=notification_id,
                    )

        for stale_id in self._active_notification_ids - active_ids_now:
            persistent_notification.async_dismiss(self.hass, stale_id)

        self._active_notification_ids = active_ids_now
