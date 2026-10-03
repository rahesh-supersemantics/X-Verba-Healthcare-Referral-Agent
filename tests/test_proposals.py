"""Phase 2: AI output -> validated action proposal (no trust in model output)."""

import pytest

from backend.proposals import normalize_department, parse_model_output, validate_proposal
from tests.conftest import JORDAN_A_ID

VALID = {
    "recommendation": "Raised blood pressure on treatment; specialist review is reasonable.",
    "action": "CREATE_REFERRAL",
    "department": "cardiology",
    "reason": "Essential hypertension with raised systolic blood pressure.",
    "evidence": ["Essential hypertension", "Systolic Blood Pressure"],
}


def test_valid_proposal_is_normalized():
    result = validate_proposal(dict(VALID, action=" create referral ", department="Cardiology Department"))

    assert result.valid
    assert result.proposal.action == "CREATE_REFERRAL"
    assert result.proposal.department == "Cardiology"
    assert result.proposal.evidence == ("Essential hypertension", "Systolic Blood Pressure")


def test_identifier_fields_from_the_ai_are_ignored_and_recorded():
    result = validate_proposal(dict(VALID, patient_id=JORDAN_A_ID, uuid=JORDAN_A_ID, referral_id=99))

    assert result.valid
    assert set(result.ignored_fields) == {"patient_id", "uuid", "referral_id"}
    assert "patient_id" not in result.proposal.to_dict()


def test_uuid_inside_ai_text_is_rejected():
    result = validate_proposal(dict(VALID, reason=f"Refer patient {JORDAN_A_ID} urgently."))

    assert not result.valid
    assert any("internal identifier" in e for e in result.errors)


@pytest.mark.parametrize(
    "change, fragment",
    [
        ({"action": "DELETE_PATIENT"}, "Unsupported action"),
        ({"action": None}, "Unsupported action"),
        ({"department": "Astrology"}, "Unsupported department"),
        ({"reason": "  "}, "Missing referral reason"),
        ({"recommendation": None}, "Missing recommendation"),
        ({"evidence": "Essential hypertension"}, "Evidence must be a list"),
        ({"evidence": ["x" * 500]}, "Too much evidence"),
    ],
)
def test_malformed_proposals_are_rejected(change, fragment):
    result = validate_proposal(dict(VALID, **change))

    assert not result.valid
    assert result.proposal is None
    assert any(fragment in e for e in result.errors), result.errors


@pytest.mark.parametrize("raw", ["not json at all", "", None, 42, ["a", "b"], "{broken json"])
def test_non_object_output_is_rejected(raw):
    result = validate_proposal(raw)

    assert not result.valid
    assert result.errors == ("AI output is not a JSON object.",)


def test_json_wrapped_in_text_or_code_fences_is_parsed():
    fenced = '```json\n{"action": "NO_ACTION", "recommendation": "No referral needed."}\n```'
    chatty = 'Here is my answer: {"action": "NO_ACTION", "recommendation": "Fine."} Thanks!'

    assert parse_model_output(fenced)["action"] == "NO_ACTION"
    assert validate_proposal(chatty).valid


def test_out_of_scope_department_is_rejected():
    result = validate_proposal(dict(VALID, department="Neurology"), requested_department="Cardiology")

    assert not result.valid
    assert any("outside the requested scope" in e for e in result.errors)


def test_no_action_ignores_referral_fields():
    result = validate_proposal({"action": "NO_ACTION", "recommendation": "Not indicated.", "department": "Astrology"})

    assert result.valid
    assert result.proposal.department is None
    assert result.proposal.reason is None


def test_department_aliases():
    assert normalize_department("cardiac") == "Cardiology"
    assert normalize_department("ENT") == "Otolaryngology"
    assert normalize_department("made-up") is None
