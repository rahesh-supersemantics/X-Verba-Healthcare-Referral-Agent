from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import (
    Patient,
    Condition,
    Medication,
    Allergy,
    Observation,
    Encounter,
)


def get_patient(session: Session, patient_id: str) -> dict:
    """
    Retrieve a patient's healthcare information using the internal
    patient ID.
    """

    patient = session.get(Patient, patient_id)

    if patient is None:
        return {
            "success": False,
            "error": "Patient not found",
            "patient_id": patient_id,
        }

    conditions = session.scalars(
        select(Condition)
        .where(Condition.patient_id == patient_id)
    ).all()

    medications = session.scalars(
        select(Medication)
        .where(Medication.patient_id == patient_id)
    ).all()

    allergies = session.scalars(
        select(Allergy)
        .where(Allergy.patient_id == patient_id)
    ).all()

    observations = session.scalars(
        select(Observation)
        .where(Observation.patient_id == patient_id)
        .order_by(Observation.date.desc())
        .limit(20)
    ).all()

    encounters = session.scalars(
        select(Encounter)
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.start.desc())
        .limit(10)
    ).all()

    return {
        "success": True,

        "patient": {
            "patient_id": patient.patient_id,
            "name": patient.name,
            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,
        },

        "conditions": [
            {
                "condition": item.condition,
                "status": item.status,
                "onset": item.onset,
            }
            for item in conditions
        ],

        "medications": [
            {
                "medication": item.medication,
                "status": item.status,
            }
            for item in medications
            if item.medication
        ],

        "allergies": [
            {
                "allergy": item.allergy,
                "status": item.status,
            }
            for item in allergies
        ],

        "observations": [
            {
                "type": item.type,
                "value": item.value,
                "date": item.date,
            }
            for item in observations
        ],

        "recent_encounters": [
            {
                "type": item.type,
                "status": item.status,
                "start": item.start,
            }
            for item in encounters
        ],
    }