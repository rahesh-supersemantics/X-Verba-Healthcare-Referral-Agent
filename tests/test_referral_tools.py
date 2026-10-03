"""
Deterministic referral workflow.

The critical property under test:

    INVALID / UNAUTHORIZED / GOVERNANCE FAILURE
        -> VSL -> DENY or TERMINAL
        -> NO REFERRAL DATABASE WRITE
"""

import pytest

from backend import actions
from backend.domain import (
    GovernanceDecision,
    GovernanceOutcome,
    ReferralCandidate,
    ReferralRequest,
    WorkflowStatus,
)
from backend.workflow import ReferralWorkflow
from governance.gates import governed_referral
from tests.conftest import AISHA_ID, NONEXISTENT_ID, referral_count


# ------------------------------------------------------------
# Spies
# ------------------------------------------------------------

class GovernanceSpy:
    """Wraps real (or stubbed) governance and records every candidate."""

    def __init__(self, result=None, raises=None):
        self.calls = []
        self._result = result
        self._raises = raises

    async def __call__(self, candidate):
        self.calls.append(dict(candidate))
        if self._raises is not None:
            raise self._raises
        if self._result is not None:
            return dict(self._result, decision_id="3f1b6a2e-0000-4000-8000-000000000001")
        return await governed_referral(candidate)


class WriterSpy:
    def __init__(self, raises=None):
        self.calls = []
        self._raises = raises

    def __call__(self, session, decision):
        self.calls.append(decision)
        if self._raises is not None:
            raise self._raises
        return actions.create_referral_record(session, decision)


def _workflow(governance=None, writer=None):
    return ReferralWorkflow(
        governance=governance or GovernanceSpy(),
        writer=writer or WriterSpy(),
    )


def _by_name(name="Aisha Wiegand", department="Cardiology", reason="Chest pain on exertion."):
    return ReferralRequest(patient_name=name, department=department, reason=reason)


# ------------------------------------------------------------
# Success
# ------------------------------------------------------------

async def test_valid_referral_request_creates_referral_after_allow():
    governance, writer = GovernanceSpy(), WriterSpy()

    outcome = await _workflow(governance, writer).run(_by_name())

    assert outcome.status is WorkflowStatus.REFERRAL_CREATED
    assert outcome.success is True
    assert outcome.governance.outcome is GovernanceOutcome.ALLOW
    assert outcome.referral.patient_id == AISHA_ID
    assert outcome.referral.governance_decision_id == outcome.governance.decision_id
    assert referral_count() == 1

    # Governance evaluated the deterministically resolved UUID,
    # exactly once, before the single write.
    assert governance.calls == [
        {"patient_id": AISHA_ID, "department": "Cardiology", "reason": "Chest pain on exertion."}
    ]
    assert len(writer.calls) == 1


async def test_referral_by_explicit_patient_id():
    outcome = await _workflow().run(
        ReferralRequest(patient_id=AISHA_ID.upper(), department="Neurology", reason="Migraine.")
    )

    assert outcome.status is WorkflowStatus.REFERRAL_CREATED
    assert outcome.referral.patient_id == AISHA_ID
    assert referral_count() == 1


# ------------------------------------------------------------
# Patient resolution failures - governance and write never reached
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "request_, expected",
    [
        (_by_name(name="Nonexistent Person"), WorkflowStatus.PATIENT_NOT_FOUND),
        (_by_name(name="Jordan Smith"), WorkflowStatus.MULTIPLE_PATIENT_MATCHES),
        (_by_name(name="Legacy999"), WorkflowStatus.INVALID_PATIENT_ID),
        (
            ReferralRequest(patient_id="Aisha756 Melina208 Wiegand701", department="Cardiology", reason="x"),
            WorkflowStatus.INVALID_PATIENT_ID,
        ),
        (
            ReferralRequest(patient_id="not-a-uuid", department="Cardiology", reason="x"),
            WorkflowStatus.INVALID_PATIENT_ID,
        ),
        (
            ReferralRequest(patient_name="Aisha", patient_id=AISHA_ID, department="Cardiology", reason="x"),
            WorkflowStatus.INVALID_REQUEST,
        ),
        (
            ReferralRequest(department="Cardiology", reason="x"),
            WorkflowStatus.INVALID_REQUEST,
        ),
    ],
)
async def test_resolution_failures_stop_before_governance(request_, expected):
    governance, writer = GovernanceSpy(), WriterSpy()

    outcome = await _workflow(governance, writer).run(request_)

    assert outcome.status is expected
    assert outcome.success is False
    assert governance.calls == []
    assert writer.calls == []
    assert referral_count() == 0


async def test_multiple_matches_returns_candidates_for_clarification():
    outcome = await _workflow().run(_by_name(name="Jordan"))

    assert outcome.status is WorkflowStatus.MULTIPLE_PATIENT_MATCHES
    assert len(outcome.candidates) == 2


# ------------------------------------------------------------
# Governance DENY / TERMINAL - no database write
# ------------------------------------------------------------

async def test_real_vsl_deny_blocks_write():
    writer = WriterSpy()

    outcome = await _workflow(writer=writer).run(_by_name(reason="   "))

    assert outcome.status is WorkflowStatus.GOVERNANCE_DENIED
    assert outcome.governance.outcome is GovernanceOutcome.DENY
    assert outcome.governance.decision_id
    assert writer.calls == []
    assert referral_count() == 0


async def test_real_vsl_terminal_blocks_write_for_nonexistent_patient():
    writer = WriterSpy()

    outcome = await _workflow(writer=writer).run(
        ReferralRequest(patient_id=NONEXISTENT_ID, department="Cardiology", reason="Chest pain.")
    )

    assert outcome.status is WorkflowStatus.GOVERNANCE_TERMINAL
    assert outcome.governance.outcome is GovernanceOutcome.TERMINAL
    assert outcome.governance.invariant == "PATIENT_MUST_EXIST"
    assert writer.calls == []
    assert referral_count() == 0


@pytest.mark.parametrize(
    "stub, expected",
    [
        ({"decision": "DENY", "reason": "policy"}, WorkflowStatus.GOVERNANCE_DENIED),
        (
            {"decision": "TERMINAL", "reason": "halted", "terminal_state": "referral-action-suspended"},
            WorkflowStatus.GOVERNANCE_TERMINAL,
        ),
    ],
)
async def test_governance_refusal_for_valid_patient_blocks_write(stub, expected):
    """Even a perfectly valid, resolved patient is not written without ALLOW."""

    writer = WriterSpy()

    outcome = await _workflow(GovernanceSpy(result=stub), writer).run(_by_name())

    assert outcome.status is expected
    assert writer.calls == []
    assert referral_count() == 0


# ------------------------------------------------------------
# Fail-safe behaviour
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "governance",
    [
        GovernanceSpy(raises=RuntimeError("ledger unavailable")),
        GovernanceSpy(result={"decision": "MAYBE"}),
    ],
)
async def test_governance_error_or_malformed_result_fails_closed(governance):
    writer = WriterSpy()

    outcome = await _workflow(governance, writer).run(_by_name())

    assert outcome.status is WorkflowStatus.INTERNAL_ERROR
    assert "ledger unavailable" not in outcome.message
    assert writer.calls == []
    assert referral_count() == 0


async def test_database_error_after_allow_is_rolled_back():
    outcome = await _workflow(writer=WriterSpy(raises=RuntimeError("disk full"))).run(_by_name())

    assert outcome.status is WorkflowStatus.INTERNAL_ERROR
    assert "disk full" not in outcome.message
    assert referral_count() == 0


def test_side_effect_layer_refuses_non_allow_decisions():
    from backend.database.connection import SessionLocal

    candidate = ReferralCandidate(patient_id=AISHA_ID, department="Cardiology", reason="x")

    for outcome in (GovernanceOutcome.DENY, GovernanceOutcome.TERMINAL):
        decision = GovernanceDecision(
            outcome=outcome, decision_id="d", reason="r", candidate=candidate
        )
        with SessionLocal() as session, pytest.raises(actions.GovernanceNotAllowedError):
            actions.create_referral_record(session, decision)

    with SessionLocal() as session, pytest.raises(actions.GovernanceNotAllowedError):
        actions.create_referral_record(session, {"decision": "ALLOW"})  # type: ignore[arg-type]

    assert referral_count() == 0
