"""
Domain types for the governed healthcare referral workflow.

These types are deliberately framework-free (no FastAPI, no Agent
Framework, no SQLAlchemy) so they can be shared by the workflow,
the side-effect layer, the agent tools and the API without creating
import cycles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


# ============================================================
# Status codes
# ============================================================


class WorkflowStatus(str, Enum):
    """Machine-readable outcome of one referral workflow run."""

    REFERRAL_CREATED = "REFERRAL_CREATED"
    INVALID_REQUEST = "INVALID_REQUEST"
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"
    MULTIPLE_PATIENT_MATCHES = "MULTIPLE_PATIENT_MATCHES"
    INVALID_PATIENT_ID = "INVALID_PATIENT_ID"
    GOVERNANCE_DENIED = "GOVERNANCE_DENIED"
    GOVERNANCE_TERMINAL = "GOVERNANCE_TERMINAL"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class GovernanceOutcome(str, Enum):
    """The three decisions the X-Verba VSL gate sequence can return."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    TERMINAL = "TERMINAL"


# ============================================================
# Patients
# ============================================================


@dataclass(frozen=True)
class PatientRecord:
    patient_id: str
    name: str
    date_of_birth: str | None = None
    gender: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Referral request / candidate
# ============================================================


@dataclass(frozen=True)
class ReferralRequest:
    """
    What a caller (API client or agent tool) asks for.

    Exactly one of ``patient_name`` / ``patient_id`` must be supplied.
    The workflow - never the caller - turns this into an internal
    patient identifier.
    """

    department: str
    reason: str
    patient_name: str | None = None
    patient_id: str | None = None
    # Optional, separate from the name: narrows name resolution.
    date_of_birth: str | None = None
    # Phase 2 provenance for AI-originated proposals. Set only by the
    # clinical-review workflow (never from LLM-controlled input).
    origin: str | None = None
    evidence: tuple[str, ...] = ()
    workflow_id: str | None = None


@dataclass(frozen=True)
class ReferralCandidate:
    """
    The exact action proposed to X-Verba governance.

    Built deterministically by the workflow after patient resolution.
    The side-effect layer only ever writes the candidate carried by an
    ALLOW decision, so the governed input and the committed record
    cannot diverge.
    """

    patient_id: str
    department: str
    reason: str
    origin: str | None = None
    evidence: tuple[str, ...] = ()
    workflow_id: str | None = None

    def to_governance_input(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "patient_id": self.patient_id,
            "department": self.department,
            "reason": self.reason,
        }
        if self.origin:
            data["origin"] = self.origin
            data["evidence"] = list(self.evidence)
            data["workflow_id"] = self.workflow_id
        return data


# ============================================================
# Governance decision
# ============================================================


@dataclass(frozen=True)
class GovernanceDecision:
    outcome: GovernanceOutcome
    decision_id: str
    reason: str
    # The exact candidate governance evaluated (ReferralCandidate,
    # ReferralChangeCandidate or ReviewRequestCandidate). Writers only
    # ever persist this object.
    candidate: Any
    invariant: str | None = None
    terminal_state: str | None = None
    pre_node: str | None = None

    @property
    def allows_side_effect(self) -> bool:
        return self.outcome is GovernanceOutcome.ALLOW

    @classmethod
    def from_gate_result(
        cls,
        result: Mapping[str, Any],
        candidate: Any,
    ) -> "GovernanceDecision":
        """
        Parse the dict returned by ``governance.gates.governed_referral``.

        Fails closed: anything that is not a well-formed ALLOW / DENY /
        TERMINAL result raises ``ValueError`` and the workflow treats it
        as an internal error (no side effect).
        """

        if not isinstance(result, Mapping):
            raise ValueError("Governance result must be a mapping.")

        raw_decision = result.get("decision")
        try:
            outcome = GovernanceOutcome(raw_decision)
        except ValueError as exc:
            raise ValueError(
                f"Unrecognised governance decision: {raw_decision!r}"
            ) from exc

        decision_id = result.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("Governance result is missing decision_id.")

        return cls(
            outcome=outcome,
            decision_id=decision_id,
            reason=str(result.get("reason", "")),
            candidate=candidate,
            invariant=result.get("invariant"),
            terminal_state=result.get("terminal_state"),
            pre_node=result.get("pre_node"),
        )

    def summary(self) -> dict[str, Any]:
        return {
            "decision": self.outcome.value,
            "decision_id": self.decision_id,
            "reason": self.reason,
            "invariant": self.invariant,
            "terminal_state": self.terminal_state,
            "pre_node": self.pre_node,
        }


# ============================================================
# Referral record (after the controlled side effect)
# ============================================================


@dataclass(frozen=True)
class ReferralRecord:
    referral_id: int
    patient_id: str
    department: str
    reason: str
    status: str
    created_at: datetime
    governance_decision_id: str | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


# ============================================================
# Workflow outcome
# ============================================================


@dataclass(frozen=True)
class ReferralOutcome:
    status: WorkflowStatus
    message: str
    patient: PatientRecord | None = None
    patient_id: str | None = None
    referral: ReferralRecord | None = None
    governance: GovernanceDecision | None = None
    candidates: tuple[PatientRecord, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        return self.status is WorkflowStatus.REFERRAL_CREATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "message": self.message,
            "patient_id": self.patient_id,
            "patient": self.patient.to_dict() if self.patient else None,
            "referral": self.referral.to_dict() if self.referral else None,
            "governance": self.governance.summary() if self.governance else None,
            "candidates": [c.to_dict() for c in self.candidates],
        }



# ============================================================
# Phase 3: further governed actions
# ============================================================


class ActionStatus(str, Enum):
    """Outcome codes for update / cancel / review-request actions."""

    REFERRAL_UPDATED = "REFERRAL_UPDATED"
    REFERRAL_CANCELLED = "REFERRAL_CANCELLED"
    CLINICAL_REVIEW_REQUESTED = "CLINICAL_REVIEW_REQUESTED"
    INVALID_REQUEST = "INVALID_REQUEST"
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"
    MULTIPLE_PATIENT_MATCHES = "MULTIPLE_PATIENT_MATCHES"
    INVALID_PATIENT_ID = "INVALID_PATIENT_ID"
    GOVERNANCE_DENIED = "GOVERNANCE_DENIED"
    GOVERNANCE_TERMINAL = "GOVERNANCE_TERMINAL"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ACTION_SUCCESS = {
    ActionStatus.REFERRAL_UPDATED,
    ActionStatus.REFERRAL_CANCELLED,
    ActionStatus.CLINICAL_REVIEW_REQUESTED,
}


@dataclass(frozen=True)
class ReferralChangeCandidate:
    """A proposed UPDATE or CANCEL of one existing referral."""

    action: str  # "UPDATE" | "CANCEL"
    referral_id: int
    patient_id: str
    department: str | None = None
    reason: str | None = None
    cancellation_reason: str | None = None

    def to_governance_input(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewRequestCandidate:
    """A proposed request for human clinical review."""

    patient_id: str
    reason: str
    department: str | None = None
    referral_id: int | None = None

    def to_governance_input(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewRequestRecord:
    review_request_id: int
    patient_id: str
    referral_id: int | None
    department: str | None
    reason: str
    status: str
    created_at: datetime
    governance_decision_id: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass(frozen=True)
class ActionOutcome:
    action: str  # UPDATE_REFERRAL | CANCEL_REFERRAL | REQUEST_CLINICAL_REVIEW
    status: ActionStatus
    message: str
    patient: PatientRecord | None = None
    patient_id: str | None = None
    referral: ReferralRecord | None = None
    review_request: ReviewRequestRecord | None = None
    governance: GovernanceDecision | None = None
    candidates: tuple[PatientRecord, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        return self.status in ACTION_SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "success": self.success,
            "status": self.status.value,
            "message": self.message,
            "patient_id": self.patient_id,
            "patient": self.patient.to_dict() if self.patient else None,
            "referral": self.referral.to_dict() if self.referral else None,
            "review_request": self.review_request.to_dict() if self.review_request else None,
            "governance": self.governance.summary() if self.governance else None,
            "candidates": [c.to_dict() for c in self.candidates],
        }
