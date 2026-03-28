"""API client for Centrik pharmacy portal."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

import async_timeout
from pycognito import Cognito

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_APP_BUNDLE, DEFAULT_APP_VERSION, VARIANT_PHARMACY
from .models import MedicationSchedule

_LOGGER = logging.getLogger(__name__)


class CentrikApiError(Exception):
    """Base API error for Centrik."""


class CentrikAuthenticationError(CentrikApiError):
    """Authentication failed."""


class CentrikApiClient:
    """Client for Centrik pharmacy API variant."""

    def __init__(
        self,
        hass,
        *,
        email: str,
        password: str,
        base_url: str,
        app_bundle: str = DEFAULT_APP_BUNDLE,
        app_version: str = DEFAULT_APP_VERSION,
        variant: str = VARIANT_PHARMACY,
    ) -> None:
        self._hass = hass
        self._session = async_get_clientsession(hass)
        self._email = email
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._app_bundle = app_bundle
        self._app_version = app_version
        self._variant = variant

        self._pool_id: str | None = None
        self._pool_client_id: str | None = None
        self._cognito: Cognito | None = None

        self._access_token: str | None = None
        self._id_token: str | None = None
        self._refresh_token: str | None = None

        self._team_id: int | None = None
        self._link_id: str | None = None

    async def async_refresh_medications(self) -> list[MedicationSchedule]:
        """Authenticate and fetch active medication schedules."""
        _LOGGER.debug(
            "Starting Centrik refresh for %s (variant=%s, base_url=%s)",
            _redact_email(self._email),
            self._variant,
            self._base_url,
        )
        await self._async_ensure_authenticated()
        medication_payload = await self._async_get(
            "/api/patient/dispensed-medication",
            include_context_headers=True,
            include_auth=True,
        )
        _LOGGER.debug("Fetched dispensed medication payload successfully")
        return self._parse_active_medications(medication_payload)

    async def _async_ensure_authenticated(self) -> None:
        """Ensure we have valid auth and patient context."""
        if self._cognito and self._access_token:
            try:
                await self._hass.async_add_executor_job(self._cognito.check_token, True)
                self._access_token = self._cognito.access_token
                self._id_token = self._cognito.id_token
                self._refresh_token = self._cognito.refresh_token
                if self._team_id is not None and self._link_id is not None:
                    return
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Existing Cognito token invalid, re-authenticating")

        await self._async_login()

    async def _async_login(self) -> None:
        """Perform login and resolve patient/team context."""
        _LOGGER.debug("Login step 1/4: loading public app auth config")
        try:
            await self._async_get_public_auth_config()
        except Exception as err:  # noqa: BLE001
            raise CentrikApiError(
                f"Login step failed while loading public app config: {err}"
            ) from err

        if not self._pool_id or not self._pool_client_id:
            raise CentrikAuthenticationError("Missing Cognito auth configuration")

        # This endpoint is required by the web app before auth; it returns challenge hints.
        _LOGGER.debug("Login step 2/4: calling /api/patient/initiate-auth")
        try:
            await self._async_post(
                "/api/patient/initiate-auth",
                json_body={"email": self._email},
                include_auth=False,
            )
        except Exception as err:  # noqa: BLE001
            raise CentrikApiError(
                f"Login step failed during /api/patient/initiate-auth: {err}"
            ) from err

        region = self._pool_id.split("_", maxsplit=1)[0]
        try:
            cognito = await self._hass.async_add_executor_job(
                self._build_cognito_client,
                region,
            )
        except Exception as err:  # noqa: BLE001
            raise CentrikAuthenticationError(
                f"Login step failed while creating Cognito client: {err.__class__.__name__}: {err}"
            ) from err

        _LOGGER.debug("Login step 3/4: authenticating against Cognito region=%s", region)
        try:
            await self._hass.async_add_executor_job(cognito.authenticate, self._password)
        except Exception as err:  # noqa: BLE001
            raise CentrikAuthenticationError(
                f"Login step failed during Cognito authentication: {err.__class__.__name__}: {err}"
            ) from err

        self._cognito = cognito
        self._access_token = cognito.access_token
        self._id_token = cognito.id_token
        self._refresh_token = cognito.refresh_token

        _LOGGER.debug("Login step 4/4: loading patient context")
        try:
            await self._async_load_patient_context()
        except Exception as err:  # noqa: BLE001
            raise CentrikApiError(
                f"Login step failed while loading patient context: {err}"
            ) from err

    async def _async_get_public_auth_config(self) -> None:
        """Fetch public app config to resolve Cognito pool/client IDs."""
        payload = await self._async_get("/api/public-app-config")
        auth = payload.get("authentication", {})
        self._pool_id = auth.get("pool_id")
        self._pool_client_id = auth.get("pool_client_id")
        _LOGGER.debug(
            "Resolved public app auth config: pool_id=%s client_id_present=%s",
            self._pool_id,
            bool(self._pool_client_id),
        )

    async def _async_load_patient_context(self) -> None:
        """Load team and link IDs required for medication endpoints."""
        payload = await self._async_get(
            "/api/patient/me",
            params={"withLastAccessed": "false"},
            include_auth=True,
        )
        data = payload.get("data", {})

        teams = data.get("teams", [])
        if teams:
            self._team_id = teams[0].get("id")

        current_link = data.get("current_patient_link") or {}
        self._link_id = current_link.get("uuid")

        if self._team_id is None or not self._link_id:
            raise CentrikApiError("Unable to resolve patient team/link context")
        _LOGGER.debug(
            "Resolved patient context: team_id=%s link_id=%s",
            self._team_id,
            _redact_identifier(self._link_id),
        )

    async def _async_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        include_auth: bool = False,
        include_context_headers: bool = False,
    ) -> dict[str, Any]:
        return await self._async_request(
            "GET",
            path,
            params=params,
            include_auth=include_auth,
            include_context_headers=include_context_headers,
        )

    async def _async_post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        include_auth: bool,
    ) -> dict[str, Any]:
        return await self._async_request(
            "POST",
            path,
            json_body=json_body,
            include_auth=include_auth,
        )

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        include_auth: bool = False,
        include_context_headers: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "accept": "application/json",
            "x-app-bundle": self._app_bundle,
            "x-app-version": self._app_version,
            "x-requested-with": "XMLHttpRequest",
        }

        if include_auth:
            if not self._access_token:
                raise CentrikAuthenticationError("No access token available")
            headers["authorization"] = f"Bearer {self._access_token}"

        if include_context_headers:
            if self._team_id is None or not self._link_id:
                raise CentrikApiError("Missing patient context headers")
            headers["x-current-team-id"] = str(self._team_id)
            headers["x-current-link-id"] = self._link_id

        async with async_timeout.timeout(30):
            response = await self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            )
        _LOGGER.debug(
            "Centrik API %s %s -> %s",
            method,
            path,
            response.status,
        )

        if response.status in (401, 403):
            raise CentrikAuthenticationError(
                f"Unauthorized response from Centrik ({response.status})"
            )

        if response.status >= 400:
            text = await response.text()
            raise CentrikApiError(
                f"Centrik API request failed ({response.status}) for {path}: {text[:400]}"
            )

        data = await response.json(content_type=None)
        if isinstance(data, dict):
            return data
        raise CentrikApiError(f"Unexpected response format for {path}")

    def _build_cognito_client(self, region: str) -> Cognito:
        """Build Cognito client with boto3 configured away from IMDS lookups."""
        boto3_client_kwargs: dict[str, Any] = {}

        try:
            # Use unsigned Cognito-IDP requests for this public app client flow.
            # This avoids botocore credential chain IMDS probing (169.254.169.254).
            from botocore import UNSIGNED
            from botocore.config import Config

            boto3_client_kwargs = {
                "region_name": region,
                "config": Config(signature_version=UNSIGNED),
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "botocore unsigned config unavailable, using default Cognito client config: %s",
                err,
            )

        return Cognito(
            user_pool_id=self._pool_id,
            client_id=self._pool_client_id,
            user_pool_region=region,
            username=self._email,
            boto3_client_kwargs=boto3_client_kwargs,
        )

    def _parse_active_medications(self, payload: dict[str, Any]) -> list[MedicationSchedule]:
        """Convert API payload into active medication schedules."""
        today = datetime.now(UTC).date()
        result: list[MedicationSchedule] = []

        for raw in payload.get("data", []):
            if raw.get("status") != "active":
                continue

            repeats = raw.get("repeats") or {}
            repeats_count = int(repeats.get("count") or 0)
            if repeats_count <= 0:
                continue

            dispensed_dates_raw = raw.get("dispensed_dates") or []
            dispensed_dates = [
                _parse_iso_date(item)
                for item in dispensed_dates_raw
                if isinstance(item, str) and _parse_iso_date(item)
            ]
            dispensed_dates = [d for d in dispensed_dates if d is not None]
            if not dispensed_dates:
                continue

            latest_dispensed = max(dispensed_dates)

            medication = raw.get("medication") or {}
            quantity = medication.get("quantity") or {}
            quantity_value = _safe_int(quantity.get("value"))

            dosage_instruction = None
            if isinstance(medication.get("dosage_instruction"), list):
                for item in medication["dosage_instruction"]:
                    if isinstance(item, dict) and item.get("text"):
                        dosage_instruction = item["text"]
                        break

            schedule_days = quantity_value if quantity_value and quantity_value > 0 else 30
            next_due_date = latest_dispensed + timedelta(days=schedule_days)

            validity_end_date = _parse_iso_date((repeats.get("validity_period") or {}).get("end"))
            if validity_end_date and next_due_date > validity_end_date:
                next_due_date = validity_end_date

            if next_due_date < today:
                next_due_date = today

            prescriber = raw.get("prescriber") or {}

            result.append(
                MedicationSchedule(
                    medication_id=str(raw.get("id")),
                    name=raw.get("name") or "Medication",
                    status=raw.get("status") or "active",
                    repeats_remaining=repeats_count,
                    next_due_date=next_due_date,
                    schedule_days=schedule_days,
                    validity_end_date=validity_end_date,
                    prescriber_name=prescriber.get("name"),
                    facility_name=prescriber.get("facility_name"),
                    dosage_instruction=dosage_instruction,
                    quantity_value=quantity_value,
                    quantity_unit=quantity.get("unit"),
                    dispensed_dates=sorted(dispensed_dates),
                )
            )

        return result


def _safe_int(value: Any) -> int | None:
    """Parse integer values safely."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD style strings."""
    if not value or not isinstance(value, str):
        return None

    cleaned = value.split("T", maxsplit=1)[0]
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def _redact_email(email: str) -> str:
    """Return a minimally identifying redacted email string."""
    if "@" not in email:
        return "***"
    name, domain = email.split("@", maxsplit=1)
    if len(name) <= 2:
        redacted_name = "*" * len(name)
    else:
        redacted_name = f"{name[0]}***{name[-1]}"
    return f"{redacted_name}@{domain}"


def _redact_identifier(value: str) -> str:
    """Return a redacted identifier for logs."""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"
