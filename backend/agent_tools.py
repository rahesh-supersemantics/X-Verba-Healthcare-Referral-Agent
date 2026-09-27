from __future__ import annotations

import uuid
from typing import Annotated

from agent_framework import tool

from backend.database.connection import SessionLocal
from backend.database.models import Patient, Referral
from backend.tools.patient_tools import get_patient
from governance.gates import governed_referral


@tool(approval_mode="never_require")
def search_patient(
    name: Annotated[
        str,
        (
            "FULL HUMAN-READABLE PATIENT NAME. "
            "Example: Aisha756 Melina208 Wiegand701. "
            "Do NOT provide a patient UUID."
        ),
    ]
) -> dict:
    """
    SEARCH TOOL.

    Use this tool FIRST when the user provides a patient name.

    This tool converts a human-readable patient name into the
    patient's INTERNAL UUID.

    IMPORTANT:
    The returned patient_id is the ONLY patient_id that may be
    passed to get_patient_information or create_referral.
    """

    session = SessionLocal()

    try:
        patients = (
            session.query(Patient)
            .filter(Patient.name.ilike(f"%{name}%"))
            .limit(10)
            .all()
        )

        if not patients:
            return {
                "success": False,
                "match_count": 0,
                "patient_id": None,
                "patient_name": None,
                "message": "No patient found. Do not create a referral.",
            }

        if len(patients) > 1:
            return {
                "success": False,
                "match_count": len(patients),
                "patient_id": None,
                "patient_name": None,
                "message": (
                    "Multiple patients found. Ask the healthcare "
                    "staff member to clarify which patient."
                ),
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

        patient = patients[0]

        return {
            "success": True,
            "match_count": 1,

            # CRITICAL FIELD FOR THE NEXT TOOL CALL
            "patient_id": patient.patient_id,

            "patient_name": patient.name,

            "date_of_birth": patient.date_of_birth,
            "gender": patient.gender,

            "message": (
                "ONE patient found. "
                "COPY THIS EXACT patient_id into the next tool call. "
                "DO NOT modify it."
            ),
        }

    finally:
        session.close()


@tool(approval_mode="never_require")
def get_patient_information(
    patient_id: Annotated[
        str,
        (
            "INTERNAL PATIENT UUID. "
            "This value MUST come directly from the patient_id "
            "field returned by search_patient."
        ),
    ]
) -> dict:
    """
    Retrieve patient information using an INTERNAL patient UUID.

    Never use a patient's name here.
    """

    session = SessionLocal()

    try:
        return get_patient(session, patient_id)

    finally:
        session.close()


@tool(approval_mode="never_require")
async def create_referral(
    patient_id: Annotated[
        str,
        (
            "INTERNAL PATIENT UUID ONLY. "
            "MUST be copied EXACTLY from search_patient.patient_id. "
            "NEVER use the patient's name. "
            "NEVER invent a UUID."
        ),
    ],
    department: Annotated[
        str,
        (
            "Medical department receiving the referral. "
            "Example: Cardiology."
        ),
    ],
    reason: Annotated[
        str,
        (
            "Clinical reason provided by the healthcare staff member "
            "for creating the referral."
        ),
    ],
) -> dict:
    """
    CREATE REFERRAL TOOL.

    IMPORTANT:
    search_patient MUST be called first when the user gives a name.

    patient_id MUST be copied exactly from search_patient.

    This tool performs the consequential database operation and
    is protected by X-Verba VSL governance.
    """

    # ---------------------------------------------------------
    # Application-level validation
    # ---------------------------------------------------------

    try:
        uuid.UUID(patient_id)
    except (ValueError, AttributeError, TypeError):
        return {
            "success": False,
            "error": "INVALID_PATIENT_ID",
            "message": (
                "Invalid patient_id. "
                "You must call search_patient first and use "
                "the exact patient_id returned by that tool. "
                "Do not use the patient's name."
            ),
        }

    candidate = {
        "patient_id": patient_id,
        "department": department,
        "reason": reason,
    }

    # ---------------------------------------------------------
    # X-Verba governance
    # ---------------------------------------------------------

    governance_result = await governed_referral(candidate)

    if governance_result["decision"] != "ALLOW":
        return {
            "success": False,
            "governance": governance_result,
            "message": (
                "Referral was NOT created because "
                "X-Verba governance did not allow the action."
            ),
        }

    # ---------------------------------------------------------
    # Database side effect
    # ---------------------------------------------------------

    session = SessionLocal()

    try:
        referral = Referral(
            patient_id=patient_id,
            department=department,
            reason=reason,
            status="PENDING",
        )

        session.add(referral)
        session.commit()
        session.refresh(referral)

        return {
            "success": True,
            "referral": {
                "referral_id": referral.referral_id,
                "patient_id": referral.patient_id,
                "department": referral.department,
                "reason": referral.reason,
                "status": referral.status,
                "created_at": referral.created_at,
            },
            "governance": governance_result,
        }

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()