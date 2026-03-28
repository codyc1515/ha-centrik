"""Calendar platform for Centrik active medication repeats."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import CentrikDataUpdateCoordinator
from .models import MedicationSchedule


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Centrik calendar entities from config entry."""
    coordinator: CentrikDataUpdateCoordinator = entry.runtime_data
    manager = CentrikCalendarEntityManager(coordinator, entry, async_add_entities)
    await manager.async_sync_entities()

    @callback
    def _handle_coordinator_update() -> None:
        hass.async_create_task(manager.async_sync_entities())

    remove_listener = coordinator.async_add_listener(_handle_coordinator_update)
    entry.async_on_unload(remove_listener)


class CentrikCalendarEntityManager:
    """Track dynamic calendar entities for active medications."""

    def __init__(
        self,
        coordinator: CentrikDataUpdateCoordinator,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._async_add_entities = async_add_entities
        self._entities_by_medication_id: dict[str, CentrikMedicationCalendarEntity] = {}

    async def async_sync_entities(self) -> None:
        """Add/remove entities to match the latest active medication set."""
        active_ids = {med.medication_id for med in self._coordinator.data}

        new_entities: list[CentrikMedicationCalendarEntity] = []
        for medication in self._coordinator.data:
            if medication.medication_id in self._entities_by_medication_id:
                continue
            entity = CentrikMedicationCalendarEntity(
                self._coordinator, self._entry, medication
            )
            self._entities_by_medication_id[medication.medication_id] = entity
            new_entities.append(entity)

        if new_entities:
            self._async_add_entities(new_entities)

        removed_ids = [
            medication_id
            for medication_id in self._entities_by_medication_id
            if medication_id not in active_ids
        ]
        for medication_id in removed_ids:
            entity = self._entities_by_medication_id.pop(medication_id)
            await entity.async_remove()


class CentrikMedicationCalendarEntity(
    CoordinatorEntity[CentrikDataUpdateCoordinator], CalendarEntity
):
    """Calendar entity for one active medication."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CentrikDataUpdateCoordinator,
        entry: ConfigEntry,
        medication: MedicationSchedule,
    ) -> None:
        super().__init__(coordinator)
        self._medication_id = medication.medication_id
        self._attr_unique_id = f"{entry.entry_id}_{medication.medication_id}"
        medication_suffix = medication.medication_id.split("_")[-1]
        self._attr_entity_id = (
            f"calendar.{DOMAIN}_{slugify(medication.name)}_{slugify(medication_suffix)}"
        )

    @property
    def medication(self) -> MedicationSchedule | None:
        """Return the matching medication model from latest coordinator data."""
        for med in self.coordinator.data:
            if med.medication_id == self._medication_id:
                return med
        return None

    @property
    def name(self) -> str:
        """Entity name."""
        med = self.medication
        if med is None:
            return "Medication"
        return med.name

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming repeat event."""
        med = self.medication
        if med is None:
            return None

        now = dt_util.now()
        for evt in _build_events(med, now.date(), now.date() + timedelta(days=365 * 2)):
            event_start = datetime.combine(evt.start, datetime.min.time(), tzinfo=dt_util.UTC)
            if event_start >= now:
                return evt

        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return all events in date range."""
        med = self.medication
        if med is None:
            return []
        return _build_events(med, start_date.date(), end_date.date())

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Expose medication details."""
        med = self.medication
        if med is None:
            return {}

        return {
            "medication_id": med.medication_id,
            "status": med.status,
            "repeats_remaining": med.repeats_remaining,
            "next_due_date": med.next_due_date.isoformat(),
            "prescription_end_date": (
                med.next_due_date
                + timedelta(days=med.repeats_remaining * med.schedule_days)
            ).isoformat(),
            "schedule_days": med.schedule_days,
            "validity_end_date": med.validity_end_date.isoformat()
            if med.validity_end_date
            else None,
            "prescriber_name": med.prescriber_name,
            "facility_name": med.facility_name,
            "dosage_instruction": med.dosage_instruction,
            "quantity_value": med.quantity_value,
            "quantity_unit": med.quantity_unit,
        }


def _build_events(
    medication: MedicationSchedule,
    start_date,
    end_date,
) -> list[CalendarEvent]:
    """Build repeat due events for the current active medication."""
    events: list[CalendarEvent] = []

    for index in range(medication.repeats_remaining):
        due_date = medication.next_due_date + timedelta(days=index * medication.schedule_days)

        if medication.validity_end_date and due_date > medication.validity_end_date:
            break

        if due_date < start_date or due_date > end_date:
            continue

        description_parts = [f"Repeat {index + 1} of {medication.repeats_remaining}"]
        if medication.prescriber_name:
            description_parts.append(f"Prescriber: {medication.prescriber_name}")
        if medication.facility_name:
            description_parts.append(f"Facility: {medication.facility_name}")
        if medication.dosage_instruction:
            description_parts.append(f"Dosage: {medication.dosage_instruction}")

        events.append(
            CalendarEvent(
                summary=f"{medication.name} repeat due",
                start=due_date,
                end=due_date + timedelta(days=1),
                description="\n".join(description_parts),
            )
        )

    prescription_end_date = medication.next_due_date + timedelta(
        days=medication.repeats_remaining * medication.schedule_days
    )
    if (
        prescription_end_date >= start_date
        and prescription_end_date <= end_date
    ):
        events.append(
            CalendarEvent(
                summary=f"{medication.name} prescription renewal planning",
                start=prescription_end_date,
                end=prescription_end_date + timedelta(days=1),
                description=(
                    "Expected end of current prescription supply.\n"
                    "Contact your doctor in advance for a new prescription."
                ),
            )
        )

    return events
