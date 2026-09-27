from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import Patient


def search_patient(
    session: Session,
    name: str,
) -> dict:
    """
    Search for patients using name tokens.

    Example:
        "Aisha Wiegand"

    can match:
        "Aisha756 Melina208 Wiegand701"

    This operation is read-only.
    """

    search_term = name.strip()

    if not search_term:
        return {
            "success": False,
            "error": "Patient name is required",
            "matches": [],
        }

    # Split the search into individual words.
    # Example:
    # "Aisha Wiegand" -> ["Aisha", "Wiegand"]
    search_tokens = search_term.split()

    statement = select(Patient)

    # Every supplied token must appear somewhere in the patient name.
    for token in search_tokens:
        statement = statement.where(
            Patient.name.ilike(f"%{token}%")
        )

    statement = statement.order_by(Patient.name)

    patients = session.scalars(statement).all()

    if not patients:
        return {
            "success": False,
            "error": "No matching patients found",
            "matches": [],
        }

    return {
        "success": True,
        "match_count": len(patients),
        "matches": [
            {
                "patient_id": patient.patient_id,
                "name": patient.name,
                "date_of_birth": patient.date_of_birth,
                "gender": patient.gender,
            }
            for patient in patients
        ],
    }