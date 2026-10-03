"""
Clinical information retrieval and context assembly (Phase 2).

Uses only data that exists in the Synthea-derived SQLite database:
conditions, medications, allergies, observations and encounters.

The assembled context is what the AI analysis step sees. It contains
no internal patient identifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.domain import PatientRecord
from backend.tools.patient_tools import get_patient


MAX_CONDITIONS = 25
MAX_MEDICATIONS = 15


class PatientRecordUnavailableError(RuntimeError):
    """The resolved patient's record could not be retrieved."""


@dataclass(frozen=True)
class ClinicalContext:
    patient: PatientRecord
    conditions: list[dict[str, Any]] = field(default_factory=list)
    medications: list[dict[str, Any]] = field(default_factory=list)
    allergies: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    encounters: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "conditions": len(self.conditions),
            "medications": len(self.medications),
            "allergies": len(self.allergies),
            "observations": len(self.observations),
            "encounters": len(self.encounters),
        }

    def for_model(self) -> dict[str, Any]:
        """Context handed to the AI analysis step. No internal identifiers."""

        return {
            "patient": {
                "name": self.patient.name,
                "date_of_birth": self.patient.date_of_birth,
                "gender": self.patient.gender,
            },
            "conditions": self.conditions,
            "medications": self.medications,
            "allergies": self.allergies,
            "recent_observations": self.observations,
            "recent_encounters": self.encounters,
        }


def _dedupe(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        value = item.get(key)
        if value and value not in seen:
            seen.add(value)
            unique.append(item)
    return unique


def retrieve_clinical_context(session: Session, patient: PatientRecord) -> ClinicalContext:
    """Read-only retrieval for an already deterministically resolved patient."""

    record = get_patient(session, patient.patient_id)

    if not record.get("success"):
        raise PatientRecordUnavailableError("Patient record not found.")

    conditions = _dedupe(record.get("conditions", []), "condition")
    # Active problems first, then the rest, bounded.
    conditions.sort(key=lambda c: 0 if (c.get("status") or "").lower() == "active" else 1)

    medications = _dedupe(record.get("medications", []), "medication")
    medications.sort(key=lambda m: 0 if (m.get("status") or "").lower() == "active" else 1)

    return ClinicalContext(
        patient=patient,
        conditions=conditions[:MAX_CONDITIONS],
        medications=medications[:MAX_MEDICATIONS],
        allergies=record.get("allergies", []),
        observations=record.get("observations", []),
        encounters=record.get("recent_encounters", []),
    )
