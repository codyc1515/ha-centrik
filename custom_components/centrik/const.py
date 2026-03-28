"""Constants for the Centrik integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "centrik"
PLATFORMS = ["calendar"]

DEFAULT_NAME = "Centrik"
DEFAULT_BASE_URL = "https://pharmacy.centrik.co.nz"
DEFAULT_APP_BUNDLE = "web.app.centrik.pharmacy"
DEFAULT_APP_VERSION = "1.78.2+897"
DEFAULT_SCAN_INTERVAL = timedelta(days=1)

CONF_BASE_URL = "base_url"
CONF_APP_BUNDLE = "app_bundle"
CONF_APP_VERSION = "app_version"
CONF_VARIANT = "variant"
CONF_REPEAT_NOTIFICATION_ENABLED = "repeat_notification_enabled"
CONF_REPEAT_NOTIFICATION_DAYS_BEFORE = "repeat_notification_days_before"
CONF_PRESCRIPTION_NOTIFICATION_ENABLED = "prescription_notification_enabled"
CONF_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE = "prescription_notification_days_before"

VARIANT_PHARMACY = "pharmacy"

DEFAULT_REPEAT_NOTIFICATION_ENABLED = True
DEFAULT_REPEAT_NOTIFICATION_DAYS_BEFORE = 3
DEFAULT_PRESCRIPTION_NOTIFICATION_ENABLED = True
DEFAULT_PRESCRIPTION_NOTIFICATION_DAYS_BEFORE = 7
