"""X-Verba VSL governance gates: ALLOW / DENY / TERMINAL."""

from governance.gates import governed_referral
from governance.ledger import entries_for_decision
from tests.conftest import (
    AISHA_ID,
    NONEXISTENT_ID,
    REFERRAL_ALLOW_SHAPE,
    REFERRAL_PRE_NODES,
    assert_causal_chain,
    pre_node_names,
    referral_count,
)


def _types(decision_id):
    return [e.entry_type.value for e in entries_for_decision(decision_id)]


async def test_vsl_allow_for_complete_candidate_and_existing_patient():
    result = await governed_referral(
        {"patient_id": AISHA_ID, "department": "Cardiology", "reason": "Chest pain."}
    )

    assert result["decision"] == "ALLOW"
    # Phase 3: one PRE_NODE + VERIFICATION per PreNode (was 3 entries).
    entries = entries_for_decision(result["decision_id"])
    assert _types(result["decision_id"]) == REFERRAL_ALLOW_SHAPE
    assert pre_node_names(entries) == REFERRAL_PRE_NODES
    assert entries[-1].payload["outcome"] == "approved"
    assert_causal_chain(entries)


async def test_vsl_deny_for_incomplete_candidate():
    result = await governed_referral(
        {"patient_id": AISHA_ID, "department": "Cardiology", "reason": "   "}
    )

    assert result["decision"] == "DENY"
    assert "REFERRAL_REQUEST_VALID" in result["reason"]
    assert _types(result["decision_id"]) == ["MONITOR", "PRE_NODE", "VERIFICATION"]

    verification = entries_for_decision(result["decision_id"])[-1]
    # A PreNode correctly denying is governance WORKING -> SUFFICIENT.
    assert verification.payload["result"] == "SUFFICIENT"
    assert verification.payload["outcome"] == "denied"


async def test_vsl_terminal_for_nonexistent_patient():
    result = await governed_referral(
        {"patient_id": NONEXISTENT_ID, "department": "Cardiology", "reason": "Chest pain."}
    )

    assert result["decision"] == "TERMINAL"
    assert result["invariant"] == "PATIENT_MUST_EXIST"
    assert result["terminal_state"] == "referral-action-suspended"
    # Phase 3: all PreNodes pass first, then the invariant fails.
    assert _types(result["decision_id"]) == REFERRAL_ALLOW_SHAPE + ["TERMINAL"]

    entries = entries_for_decision(result["decision_id"])
    verification = entries[-2]
    assert verification.payload["result"] == "INSUFFICIENT"
    assert_causal_chain(entries)


async def test_governance_itself_never_writes_referrals():
    await governed_referral(
        {"patient_id": AISHA_ID, "department": "Cardiology", "reason": "Chest pain."}
    )

    assert referral_count() == 0
