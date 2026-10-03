"""
Controlled side effects.

This module is the single place where governed side effects are written:

    create_referral_record       new referral        (ReferralWorkflow)
    change_referral_record       update / cancel     (GovernedActionWorkflow)
    create_review_request_record clinical review     (GovernedActionWorkflow)

Each is called only after X-Verba VSL governance returned ALLOW.

Structural guarantees:
    - Every writer accepts a ``GovernanceDecision``, not raw fields, and
      refuses anything other than an ALLOW decision for its own candidate
      type.
    - The record written is exactly the candidate the decision was made
      for. New referrals and review requests store the governing
      ``decision_id``; for updates and cancellations the ledger MONITOR
      entry records the referral number and the change.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.database.models import ClinicalReviewRequestRecord, Referral
from backend.domain import (
    GovernanceDecision,
    ReferralCandidate,
    ReferralChangeCandidate,
    ReferralRecord,
    ReviewRequestCandidate,
    ReviewRequestRecord,
)


class GovernanceNotAllowedError(RuntimeError):
    """Raised if a side effect is attempted without an ALLOW decision."""


class StaleReferralError(RuntimeError):
    """The referral changed between the governance decision and the write."""


def _allowed_candidate(decision: object, candidate_type: type) -> object:
    """Fail closed unless this is an ALLOW decision for the right candidate type."""

    if not isinstance(decision, GovernanceDecision) or not decision.allows_side_effect:
        raise GovernanceNotAllowedError(
            "Write refused: X-Verba governance did not return ALLOW."
        )
    if not isinstance(decision.candidate, candidate_type):
        raise GovernanceNotAllowedError(
            "Write refused: the governance decision was made for a different action."
        )
    return decision.candidate


def _record(referral: Referral) -> ReferralRecord:
    return ReferralRecord(
        referral_id=referral.referral_id,
        patient_id=referral.patient_id,
        department=referral.department,
        reason=referral.reason,
        status=referral.status,
        created_at=referral.created_at,
        governance_decision_id=referral.governance_decision_id,
    )


def create_referral_record(
    session: Session,
    decision: GovernanceDecision,
) -> ReferralRecord:
    """Persist the governed referral candidate. Requires ALLOW."""

    candidate = _allowed_candidate(decision, ReferralCandidate)

    referral = Referral(
        patient_id=candidate.patient_id,
        department=candidate.department,
        reason=candidate.reason,
        status="PENDING",
        governance_decision_id=decision.decision_id,
    )

    try:
        session.add(referral)
        session.commit()
        session.refresh(referral)
    except Exception:
        session.rollback()
        raise

    return ReferralRecord(
        referral_id=referral.referral_id,
        patient_id=referral.patient_id,
        department=referral.department,
        reason=referral.reason,
        status=referral.status,
        created_at=referral.created_at,
        governance_decision_id=referral.governance_decision_id,
    )


def change_referral_record(
    session: Session,
    decision: GovernanceDecision,
) -> ReferralRecord:
    """Apply a governed UPDATE or CANCEL to one referral. Requires ALLOW."""

    candidate = _allowed_candidate(decision, ReferralChangeCandidate)

    try:
        referral = session.get(Referral, candidate.referral_id)
        # Defensive re-check: governance evaluated an active referral of
        # this patient; refuse if that is no longer true (race).
        if (
            referral is None
            or referral.patient_id != candidate.patient_id
            or referral.status != "PENDING"
        ):
            raise StaleReferralError("Referral changed after the governance decision.")

        if candidate.action == "CANCEL":
            referral.status = "CANCELLED"
        elif candidate.action == "UPDATE":
            if candidate.department is not None:
                referral.department = candidate.department
            if candidate.reason is not None:
                referral.reason = candidate.reason
        else:
            raise GovernanceNotAllowedError(f"Unknown referral change {candidate.action!r}.")

        session.commit()
        session.refresh(referral)
    except Exception:
        session.rollback()
        raise

    return _record(referral)


def create_review_request_record(
    session: Session,
    decision: GovernanceDecision,
) -> ReviewRequestRecord:
    """Persist a governed clinical review request. Requires ALLOW."""

    candidate = _allowed_candidate(decision, ReviewRequestCandidate)

    row = ClinicalReviewRequestRecord(
        patient_id=candidate.patient_id,
        referral_id=candidate.referral_id,
        department=candidate.department,
        reason=candidate.reason,
        status="OPEN",
        governance_decision_id=decision.decision_id,
    )
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        raise

    return ReviewRequestRecord(
        review_request_id=row.review_request_id,
        patient_id=row.patient_id,
        referral_id=row.referral_id,
        department=row.department,
        reason=row.reason,
        status=row.status,
        created_at=row.created_at,
        governance_decision_id=row.governance_decision_id,
    )
