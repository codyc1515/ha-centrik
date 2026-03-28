"""Data models for Centrik."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class MedicationSchedule:
    """A single active medication + derived repeat schedule."""

    medication_id: str
    name: str
    status: str
    repeats_remaining: int
    next_due_date: date
    schedule_days: int
    validity_end_date: date | None
    prescriber_name: str | None
    facility_name: str | None
    dosage_instruction: str | None
    quantity_value: int | None
    quantity_unit: str | None
    dispensed_dates: list[date]
