"""Deterministic patient resolution (read-only)."""

from backend.database.connection import SessionLocal
from backend.patient_resolution import (
    ResolutionStatus,
    normalize_patient_id,
    resolve_patient_by_name,
    search_patients,
)
from tests.conftest import AISHA_ID, AISHA_NAME, JORDAN_A_ID, JORDAN_B_ID


def _resolve(name):
    with SessionLocal() as session:
        return resolve_patient_by_name(session, name)


def test_resolution_success_with_partial_name_tokens():
    result = _resolve("Aisha Wiegand")

    assert result.status is ResolutionStatus.RESOLVED
    assert result.patient is not None
    assert result.patient.patient_id == AISHA_ID
    assert result.patient.name == AISHA_NAME


def test_resolution_success_with_full_synthea_name_case_insensitive():
    result = _resolve("aisha756 melina208 wiegand701")

    assert result.status is ResolutionStatus.RESOLVED
    assert result.patient.patient_id == AISHA_ID


def test_patient_not_found():
    result = _resolve("Nonexistent Person")

    assert result.status is ResolutionStatus.NOT_FOUND
    assert result.patient is None


def test_multiple_patient_matches_never_guesses():
    result = _resolve("Jordan Smith")

    assert result.status is ResolutionStatus.MULTIPLE_MATCHES
    assert result.patient is None
    assert {c.patient_id for c in result.candidates} == {JORDAN_A_ID, JORDAN_B_ID}


def test_blank_name_is_invalid_input():
    assert _resolve("   ").status is ResolutionStatus.INVALID_INPUT
    assert _resolve(None).status is ResolutionStatus.INVALID_INPUT


def test_record_with_malformed_identifier_is_rejected():
    result = _resolve("Legacy999")

    assert result.status is ResolutionStatus.INVALID_PATIENT_ID
    assert result.patient is None


def test_like_wildcards_are_escaped():
    with SessionLocal() as session:
        matches, _ = search_patients(session, "%")
        underscore, _ = search_patients(session, "_")

    assert matches == []
    assert underscore == []


def test_normalize_patient_id():
    assert normalize_patient_id(AISHA_ID) == AISHA_ID
    assert normalize_patient_id(f"  {AISHA_ID.upper()} ") == AISHA_ID
    assert normalize_patient_id("Aisha756 Melina208 Wiegand701") is None
    assert normalize_patient_id("8f998bfdbcee9bc0e4357c50e571a851") is None
    assert normalize_patient_id("") is None
    assert normalize_patient_id(None) is None
    assert normalize_patient_id(12345) is None
