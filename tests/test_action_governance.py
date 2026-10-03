"""
Phase 3: action-level governance for every governed side effect.

    create referral        REFERRAL_REQUEST_VALID, REFERRAL_TARGET_VALID,
                           [AI_PROPOSAL_GROUNDED], REFERRAL_NOT_DUPLICATE;
                           PATIENT_MUST_EXIST, [GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT]
    update / cancel        REFERRAL_UPDATE_VALID / REFERRAL_CANCEL_VALID;
                           PATIENT_MUST_EXIST, REFERRAL_MUST_BELONG_TO_PATIENT
    clinical review request CLINICAL_REVIEW_REQUEST_VALID; PATIENT_MUST_EXIST
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import actions
from backend.app import app
from backend.clinical_runs import ClinicalRunStore
from backend.database.connection import SessionLocal
from backend.database.models import ClinicalReviewRequestRecord, Condition, Referral
from backend.domain import GovernanceDecision, GovernanceOutcome, ReferralCandidate, ReferralChangeCandidate
from backend.workflow import ClinicalReviewRequestInput, GovernedActionWorkflow, ReferralChangeRequest
from governance.gates import governed_referral
from governance.ledger import entries_for_decision, ledger
from tests.conftest import AISHA_ID, JORDAN_A_ID, NONEXISTENT_ID, assert_causal_chain, referral_count


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_review_requests():
    with SessionLocal() as session:
        session.query(ClinicalReviewRequestRecord).delete()
        session.commit()
    yield


def _referral(client, **payload):
    body = {"patient_name": "Aisha Wiegand", "department": "Cardiology", "reason": "Chest pain.", **payload}
    return client.post("/referrals", json=body)


def _referral_row(referral_id):
    with SessionLocal() as session:
        row = session.get(Referral, referral_id)
        return None if row is None else (row.department, row.reason, row.status)


# ------------------------------------------------------------------
# Create: valid, duplicate, unsupported department, terminal
# ------------------------------------------------------------------

def test_valid_referral_allows_exactly_one_write(client):
    response = _referral(client)

    assert response.status_code == 201
    assert referral_count() == 1


def test_duplicate_active_referral_is_denied_and_ledgered(client):
    first = _referral(client).json()
    second = _referral(client, reason="Still has chest pain").json()

    assert second["status"] == "GOVERNANCE_DENIED"
    assert second["governance"]["pre_node"] == "REFERRAL_NOT_DUPLICATE"
    assert "already active" in second["message"]
    assert referral_count() == 1

    entries = entries_for_decision(second["decision_id"])
    duplicate_check = [e for e in entries if e.payload.get("pre_node") == "REFERRAL_NOT_DUPLICATE"][0]
    assert duplicate_check.payload["denied"] is True
    assert duplicate_check.payload["active_duplicate_referral_ids"] == [first["referral"]["referral_id"]]
    assert_causal_chain(entries)


def test_cancelled_referral_is_not_a_duplicate(client):
    first = _referral(client).json()
    with SessionLocal() as session:
        session.get(Referral, first["referral"]["referral_id"]).status = "CANCELLED"
        session.commit()

    assert _referral(client).status_code == 201
    assert referral_count() == 2


def test_unsupported_department_is_denied(client):
    body = _referral(client, department="Astrology").json()

    assert body["status"] == "GOVERNANCE_DENIED"
    assert body["governance"]["pre_node"] == "REFERRAL_TARGET_VALID"
    assert referral_count() == 0


def test_nonexistent_patient_is_terminal(client):
    response = client.post(
        "/referrals", json={"patient_id": NONEXISTENT_ID, "department": "Cardiology", "reason": "x"}
    )

    assert response.json()["status"] == "GOVERNANCE_TERMINAL"
    assert referral_count() == 0


# ------------------------------------------------------------------
# AI proposals: evidence ownership and workflow context
# ------------------------------------------------------------------

def _seed_jordan_condition():
    with SessionLocal() as session:
        exists = session.query(Condition).filter_by(patient_id=JORDAN_A_ID, condition="Congestive heart failure").first()
        if not exists:
            session.add(Condition(patient_id=JORDAN_A_ID, condition="Congestive heart failure", status="active"))
            session.commit()


async def test_evidence_belonging_to_another_patient_is_denied():
    _seed_jordan_condition()
    from backend.clinical_workflow import ClinicalReviewRequest, ClinicalReviewWorkflow
    from tests.test_clinical_workflow import GROUNDED, FakeAnalyzer

    # "Congestive heart failure" exists - but in Jordan's record, not Aisha's.
    workflow = ClinicalReviewWorkflow(analyzer=FakeAnalyzer(dict(GROUNDED, evidence=["Congestive heart failure"])))
    result = await workflow.run(ClinicalReviewRequest("Aisha Wiegand"))

    assert result.status == "GOVERNANCE_DENIED"
    assert result.governance["pre_node"] == "AI_PROPOSAL_GROUNDED"
    grounding = [e for e in entries_for_decision(result.governance["decision_id"])
                 if e.payload.get("pre_node") == "AI_PROPOSAL_GROUNDED"][0]
    assert grounding.payload["evidence_unsupported"] == ["Congestive heart failure"]
    assert referral_count() == 0


async def test_ai_proposal_for_a_different_patient_than_its_workflow_is_terminal():
    # A workflow run that resolved Aisha ...
    store = ClinicalRunStore()
    snapshot = {"workflow_id": "0d0d0d0d-1111-4222-8333-444444444444", "state": "GOVERNANCE_CHECK",
                "request": {"patient_name": "Aisha Wiegand"}, "patient": {"patient_id": AISHA_ID}}
    store.create(snapshot, None)
    store.save(snapshot)

    # ... but an AI candidate that targets Jordan under that workflow.
    # Without evidence, grounding (a PreNode) denies it before invariants run.
    ungrounded = await governed_referral({
        "patient_id": JORDAN_A_ID, "department": "Cardiology", "reason": "Hypertension",
        "origin": "AI_PROPOSAL", "workflow_id": snapshot["workflow_id"], "evidence": [],
    })
    assert ungrounded["decision"] == "DENY"
    assert ungrounded["pre_node"] == "AI_PROPOSAL_GROUNDED"

    # With real Jordan evidence it passes grounding and hits the invariant.
    _seed_jordan_condition()
    decision = await governed_referral({
        "patient_id": JORDAN_A_ID, "department": "Cardiology", "reason": "Heart failure",
        "origin": "AI_PROPOSAL", "workflow_id": snapshot["workflow_id"],
        "evidence": ["Congestive heart failure"],
    })

    assert decision["decision"] == "TERMINAL"
    assert decision["invariant"] == "GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT"
    assert decision["terminal_state"] == "patient-context-integrity-violation"
    assert referral_count() == 0


# ------------------------------------------------------------------
# Update / cancel
# ------------------------------------------------------------------

async def _create(department="Cardiology"):
    from backend.domain import ReferralRequest
    from backend.workflow import ReferralWorkflow

    outcome = await ReferralWorkflow().run(
        ReferralRequest(patient_name="Aisha Wiegand", department=department, reason="Chest pain")
    )
    return outcome.referral.referral_id


async def test_update_existing_referral_is_allowed():
    referral_id = await _create()

    outcome = await GovernedActionWorkflow().change_referral(
        ReferralChangeRequest(action="UPDATE", referral_id=referral_id, patient_name="Aisha Wiegand",
                              reason="Chest pain on exertion, worsening")
    )

    assert outcome.status.value == "REFERRAL_UPDATED"
    assert outcome.governance.outcome is GovernanceOutcome.ALLOW
    assert _referral_row(referral_id) == ("Cardiology", "Chest pain on exertion, worsening", "PENDING")
    monitor = entries_for_decision(outcome.governance.decision_id)[0]
    assert monitor.payload["action"] == "UPDATE_REFERRAL"
    assert monitor.payload["changes"]["reason"]["from"] == "Chest pain"


@pytest.mark.parametrize("action", ["UPDATE", "CANCEL"])
async def test_update_or_cancel_nonexistent_referral_is_blocked(action):
    outcome = await GovernedActionWorkflow().change_referral(
        ReferralChangeRequest(action=action, referral_id=999999, patient_name="Aisha Wiegand",
                              reason="New reason", cancellation_reason="Not needed")
    )

    assert outcome.status.value == "GOVERNANCE_DENIED"
    pre_node = "REFERRAL_UPDATE_VALID" if action == "UPDATE" else "REFERRAL_CANCEL_VALID"
    assert outcome.governance.pre_node == pre_node
    assert referral_count() == 0


async def test_cancel_existing_referral_then_cancel_again_is_denied():
    referral_id = await _create()
    workflow = GovernedActionWorkflow()
    request = ReferralChangeRequest(action="CANCEL", referral_id=referral_id, patient_name="Aisha Wiegand",
                                    cancellation_reason="Symptoms resolved")

    first = await workflow.change_referral(request)
    second = await workflow.change_referral(request)

    assert first.status.value == "REFERRAL_CANCELLED"
    assert _referral_row(referral_id)[2] == "CANCELLED"
    assert second.status.value == "GOVERNANCE_DENIED"  # no longer active


async def test_changing_another_patients_referral_is_terminal():
    referral_id = await _create()

    outcome = await GovernedActionWorkflow().change_referral(
        ReferralChangeRequest(action="CANCEL", referral_id=referral_id, patient_name="Jordan101 Smith202",
                              cancellation_reason="Not needed")
    )

    assert outcome.status.value == "GOVERNANCE_TERMINAL"
    assert outcome.governance.invariant == "REFERRAL_MUST_BELONG_TO_PATIENT"
    assert _referral_row(referral_id)[2] == "PENDING"


async def test_update_with_no_change_or_bad_department_is_denied():
    referral_id = await _create()
    workflow = GovernedActionWorkflow()

    no_change = await workflow.change_referral(
        ReferralChangeRequest(action="UPDATE", referral_id=referral_id, patient_name="Aisha Wiegand")
    )
    bad = await workflow.change_referral(
        ReferralChangeRequest(action="UPDATE", referral_id=referral_id, patient_name="Aisha Wiegand",
                              department="Astrology")
    )

    assert no_change.status.value == bad.status.value == "GOVERNANCE_DENIED"
    assert _referral_row(referral_id) == ("Cardiology", "Chest pain", "PENDING")


# ------------------------------------------------------------------
# Clinical review requests
# ------------------------------------------------------------------

async def test_clinical_review_request_allowed_then_duplicate_denied():
    workflow = GovernedActionWorkflow()
    request = ClinicalReviewRequestInput(patient_name="Aisha Wiegand", reason="Blocked referral needs review",
                                         department="Neurology")

    first = await workflow.request_review(request)
    second = await workflow.request_review(request)

    assert first.status.value == "CLINICAL_REVIEW_REQUESTED"
    assert first.review_request.status == "OPEN"
    assert first.review_request.governance_decision_id == first.governance.decision_id
    assert second.status.value == "GOVERNANCE_DENIED"
    assert second.governance.pre_node == "CLINICAL_REVIEW_REQUEST_VALID"
    with SessionLocal() as session:
        assert session.query(ClinicalReviewRequestRecord).count() == 1


async def test_clinical_review_request_requires_a_reason():
    outcome = await GovernedActionWorkflow().request_review(
        ClinicalReviewRequestInput(patient_name="Aisha Wiegand", reason="  ")
    )

    assert outcome.status.value == "GOVERNANCE_DENIED"


def test_review_requests_are_listed(client):
    import asyncio

    asyncio.run(GovernedActionWorkflow().request_review(
        ClinicalReviewRequestInput(patient_name="Aisha Wiegand", reason="Please review cardiac risk")
    ))
    body = client.get("/clinical-review-requests").json()

    assert body["review_requests"][0]["reason"] == "Please review cardiac risk"


# ------------------------------------------------------------------
# Governance failure -> no side effect; writers fail closed
# ------------------------------------------------------------------

async def test_governance_failure_produces_no_side_effect():
    referral_id = await _create()

    async def broken(_candidate):
        raise RuntimeError("ledger unavailable")

    outcome = await GovernedActionWorkflow(cancel_governance=broken).change_referral(
        ReferralChangeRequest(action="CANCEL", referral_id=referral_id, patient_name="Aisha Wiegand",
                              cancellation_reason="Not needed")
    )

    assert outcome.status.value == "INTERNAL_ERROR"
    assert "ledger unavailable" not in outcome.message
    assert _referral_row(referral_id)[2] == "PENDING"


def test_writers_refuse_decisions_for_other_actions():
    create_candidate = ReferralCandidate(patient_id=AISHA_ID, department="Cardiology", reason="x")
    allow_for_create = GovernanceDecision(GovernanceOutcome.ALLOW, "d", "r", create_candidate)
    deny_change = GovernanceDecision(
        GovernanceOutcome.DENY, "d", "r", ReferralChangeCandidate("CANCEL", 1, AISHA_ID, cancellation_reason="x")
    )

    with SessionLocal() as session:
        with pytest.raises(actions.GovernanceNotAllowedError):
            actions.change_referral_record(session, allow_for_create)  # ALLOW, but for a different action
        with pytest.raises(actions.GovernanceNotAllowedError):
            actions.change_referral_record(session, deny_change)
        with pytest.raises(actions.GovernanceNotAllowedError):
            actions.create_review_request_record(session, allow_for_create)


def test_ledger_stays_audit_compatible_and_intact():
    assert "pre_node_has_verification" not in ledger.audit().checks_failed
    assert ledger.verify_integrity() is True
    # Evidence is plain JSON (hash chain covers it).
    assert all(json.dumps(e.payload) for e in ledger.store.all_entries())


# ------------------------------------------------------------------
# Client-readiness review regressions
# ------------------------------------------------------------------

def test_department_aliases_are_stored_canonically_and_cannot_bypass_duplicates(client):
    first = _referral(client, department="haematology")
    second = _referral(client, department="Hematology")

    assert first.json()["status"] == "REFERRAL_CREATED"
    assert first.json()["referral"]["department"] == "Hematology"
    assert second.json()["status"] == "GOVERNANCE_DENIED"
    assert second.json()["governance"]["pre_node"] == "REFERRAL_NOT_DUPLICATE"
    assert referral_count() == 1


async def test_update_cannot_create_the_duplicate_that_create_blocks():
    await _create("Cardiology")
    neurology = await _create("Neurology")

    outcome = await GovernedActionWorkflow().change_referral(
        ReferralChangeRequest(action="UPDATE", referral_id=neurology, patient_name="Aisha Wiegand",
                              department="Cardiology")
    )

    assert outcome.status.value == "GOVERNANCE_DENIED"
    assert outcome.governance.pre_node == "REFERRAL_NOT_DUPLICATE"
    assert _referral_row(neurology)[0] == "Neurology"


async def test_review_request_citing_a_missing_referral_is_denied_not_terminal():
    outcome = await GovernedActionWorkflow().request_review(
        ClinicalReviewRequestInput(patient_name="Aisha Wiegand", reason="Unclear diagnosis", referral_id=999999)
    )

    assert outcome.status.value == "GOVERNANCE_DENIED"
    assert outcome.governance.pre_node == "CLINICAL_REVIEW_REQUEST_VALID"


def test_terminal_verification_is_labelled_as_an_invariant_violation(client):
    response = client.post(
        "/referrals", json={"patient_id": NONEXISTENT_ID, "department": "Cardiology", "reason": "x"}
    )
    decision_id = response.json()["governance"]["decision_id"]
    entries = entries_for_decision(decision_id)

    verification, terminal = entries[-2], entries[-1]
    assert terminal.entry_type.value == "TERMINAL"
    assert terminal.caused_by == verification.entry_id
    assert verification.payload["outcome"] == "invariant_violated"
    assert verification.payload["invariant"] == "PATIENT_MUST_EXIST"
    assert_causal_chain(entries)
