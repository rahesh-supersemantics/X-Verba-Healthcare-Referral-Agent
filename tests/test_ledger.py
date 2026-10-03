"""Ledger evidence for the successful governed referral."""

from backend.database.connection import SessionLocal
from backend.database.models import Referral
from backend.domain import ReferralRequest, WorkflowStatus
from backend.workflow import ReferralWorkflow
from governance.ledger import entries_for_decision, ledger, summarize_decision
from tests.conftest import AISHA_ID, REFERRAL_ALLOW_SHAPE, assert_causal_chain


async def test_allow_produces_causally_linked_ledger_evidence_and_traceable_referral():
    outcome = await ReferralWorkflow().run(
        ReferralRequest(
            patient_name="Aisha Wiegand",
            department="Cardiology",
            reason="Persistent chest pain on exertion.",
        )
    )

    assert outcome.status is WorkflowStatus.REFERRAL_CREATED
    decision_id = outcome.governance.decision_id

    entries = entries_for_decision(decision_id)
    monitor, verification = entries[0], entries[-1]

    # Causal chain: MONITOR -> PRE_NODE -> VERIFICATION, for every PreNode.
    assert [e.entry_type.value for e in entries] == REFERRAL_ALLOW_SHAPE
    assert_causal_chain(entries)
    assert verification.payload["outcome"] == "approved"
    assert monitor.payload["patient_id"] == AISHA_ID

    assert summarize_decision(entries)["decision"] == "ALLOW"
    assert ledger.verify_integrity() is True

    # The committed row points back at its governance decision.
    with SessionLocal() as session:
        row = session.get(Referral, outcome.referral.referral_id)
        assert row.governance_decision_id == decision_id
        assert row.patient_id == AISHA_ID
