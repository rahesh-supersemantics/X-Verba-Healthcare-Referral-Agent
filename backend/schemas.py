"""Pydantic request / response models for the X-Verba Healthcare API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain import ReferralOutcome, WorkflowStatus


# ============================================================
# Shared
# ============================================================


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: str = Field(..., examples=["PATIENT_NOT_FOUND"])
    message: str


class PatientSummary(BaseModel):
    patient_id: str
    name: str
    date_of_birth: str | None = None
    gender: str | None = None


# ============================================================
# Referrals
# ============================================================


class ReferralCreateRequest(BaseModel):
    """
    Governed referral request. Supply exactly one of ``patient_name`` or
    ``patient_id``; the server resolves the patient deterministically.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "patient_name": "Aisha Wiegand",
                    "department": "Cardiology",
                    "reason": "Persistent chest pain on exertion.",
                }
            ]
        },
    )

    patient_name: str | None = Field(default=None, max_length=200)
    patient_id: str | None = Field(default=None, max_length=64)
    date_of_birth: str | None = Field(
        default=None, max_length=40,
        description="Optional, with patient_name: narrows resolution (DD/MM/YYYY or YYYY-MM-DD).",
    )
    department: str = Field(..., max_length=100)
    reason: str = Field(..., max_length=2000)


class GovernanceSummary(BaseModel):
    decision: Literal["ALLOW", "DENY", "TERMINAL"]
    decision_id: str
    reason: str
    invariant: str | None = None
    terminal_state: str | None = None
    pre_node: str | None = None


class ReferralInfo(BaseModel):
    referral_id: int
    patient_id: str
    department: str
    reason: str
    status: str
    created_at: datetime
    governance_decision_id: str | None = None


class ReferralResponse(BaseModel):
    success: bool
    status: WorkflowStatus
    error: WorkflowStatus | None = Field(
        default=None,
        description="Set to the failure code when success is false.",
    )
    message: str
    patient_id: str | None = None
    patient: PatientSummary | None = None
    referral: ReferralInfo | None = None
    governance: GovernanceSummary | None = None
    decision_id: str | None = None
    candidates: list[PatientSummary] = Field(default_factory=list)

    @classmethod
    def from_outcome(cls, outcome: ReferralOutcome) -> "ReferralResponse":
        data: dict[str, Any] = outcome.to_dict()
        data["error"] = None if outcome.success else outcome.status
        data["decision_id"] = (
            outcome.governance.decision_id if outcome.governance else None
        )
        return cls.model_validate(data)


# ============================================================
# Patients
# ============================================================


class PatientSearchResponse(BaseModel):
    success: bool
    query: str
    match_count: int
    more_matches: bool
    patients: list[PatientSummary]


class PatientDetailResponse(BaseModel):
    success: Literal[True] = True
    patient: PatientSummary
    conditions: list[dict[str, Any]]
    medications: list[dict[str, Any]]
    allergies: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    recent_encounters: list[dict[str, Any]]


# ============================================================
# Clinical workflows (Phase 2)
# ============================================================


class ClinicalWorkflowRequest(BaseModel):
    """
    Review a patient and, if the AI analysis proposes it, submit a referral
    to X-Verba governance. Supply ``idempotency_key`` to make retries safe:
    a repeated key returns the recorded outcome without re-executing.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "patient_name": "Aisha Wiegand",
                    "department": "Endocrinology",
                    "question": "Is an endocrinology referral appropriate?",
                    "idempotency_key": "review-2026-09-29-001",
                }
            ]
        },
    )

    patient_name: str = Field(..., min_length=1, max_length=200)
    date_of_birth: str | None = Field(
        default=None, max_length=40,
        description="Optional: narrows patient resolution (DD/MM/YYYY or YYYY-MM-DD).",
    )
    department: str | None = Field(default=None, max_length=100)
    question: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class WorkflowTransition(BaseModel):
    state: str
    at: str
    note: str | None = None


class ClinicalWorkflowResponse(BaseModel):
    workflow_id: str
    success: bool
    state: str = Field(..., description="Business-process state (not a governance decision).")
    status: str | None
    error: str | None = None
    message: str
    request: dict[str, Any]
    transitions: list[WorkflowTransition]
    patient: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    context_summary: dict[str, int] | None = None
    raw_ai_output: str | None = Field(default=None, description="Untrusted model output, for engineering review.")
    proposal: dict[str, Any] | None = None
    proposal_errors: list[str] = Field(default_factory=list)
    ignored_ai_fields: list[str] = Field(default_factory=list)
    governance: GovernanceSummary | None = None
    decision_id: str | None = None
    referral: ReferralInfo | None = None
    replayed: bool = False

    @classmethod
    def from_result(cls, result: Any) -> "ClinicalWorkflowResponse":
        data = result.to_dict()
        data["error"] = None if result.success else result.status
        data["decision_id"] = (result.governance or {}).get("decision_id")
        return cls.model_validate(data)


class ClinicalWorkflowListItem(BaseModel):
    workflow_id: str
    created_at: datetime
    state: str
    status: str | None = None
    patient_name: str
    department: str | None = None
    governance_decision_id: str | None = None
    referral_id: int | None = None


class ClinicalWorkflowListResponse(BaseModel):
    success: Literal[True] = True
    workflows: list[ClinicalWorkflowListItem]


# ============================================================
# Chat
# ============================================================


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": (
                        "Refer Aisha Wiegand to Cardiology because of "
                        "persistent chest pain on exertion."
                    )
                }
            ]
        },
    )

    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        max_length=64,
        description="Continue an existing conversation. Omit to start a new one.",
    )


class ActionResponse(BaseModel):
    """Outcome of a governed update / cancel / clinical-review-request action."""

    action: str
    success: bool
    status: str
    error: str | None = None
    message: str
    patient_id: str | None = None
    patient: PatientSummary | None = None
    referral: ReferralInfo | None = None
    review_request: dict[str, Any] | None = None
    governance: GovernanceSummary | None = None
    decision_id: str | None = None
    candidates: list[PatientSummary] = Field(default_factory=list)

    @classmethod
    def from_outcome(cls, outcome: Any) -> "ActionResponse":
        data = outcome.to_dict()
        data["error"] = None if outcome.success else outcome.status.value
        data["decision_id"] = outcome.governance.decision_id if outcome.governance else None
        return cls.model_validate(data)


class ConversationContextView(BaseModel):
    """Clinician-safe view of what the conversation has established."""

    intent: str | None = None
    stage: str
    patient: dict[str, Any] | None = None
    # A patient being identified (name / date of birth as given; no ID).
    patient_query: dict[str, Any] | None = None
    department: str | None = None
    reason: str | None = None
    missing: list[str] = Field(default_factory=list)
    awaiting: str | None = None
    last_referral_id: int | None = None


class ChatResponse(BaseModel):
    success: bool
    reply: str = Field(
        ...,
        description=(
            "Reply for the user. When a referral was attempted this is "
            "derived from the governed workflow outcome, not the LLM text."
        ),
    )
    agent_reply: str | None = Field(
        default=None, description="Raw LLM reply, for transparency."
    )
    referral_attempted: bool = Field(
        default=False,
        description=(
            "True only when the governed referral workflow actually ran for "
            "this message. False for greetings, questions and lookups."
        ),
    )
    workflow_results: list[ReferralResponse] = Field(default_factory=list)
    clinical_review_attempted: bool = Field(
        default=False,
        description="True only when the Phase 2 clinical-review workflow ran for this message.",
    )
    clinical_reviews: list[ClinicalWorkflowResponse] = Field(default_factory=list)
    action_attempted: bool = Field(
        default=False,
        description="True when a governed update / cancel / review-request action ran.",
    )
    action_results: list[ActionResponse] = Field(default_factory=list)
    conversation_id: str | None = None
    context: ConversationContextView | None = None


# ============================================================
# Governance evidence
# ============================================================


class LedgerEntryView(BaseModel):
    entry_id: str
    sequence: int
    entry_type: str
    timestamp: float
    caused_by: str | None = None
    payload: dict[str, Any]
    entry_hash: str
    prev_hash: str


class GovernanceDecisionResponse(BaseModel):
    success: Literal[True] = True
    decision_id: str
    decision: Literal["ALLOW", "DENY", "TERMINAL", "UNKNOWN"]
    pre_node: str | None = None
    invariant: str | None = None
    terminal_state: str | None = None
    ledger_integrity: bool
    entries: list[LedgerEntryView]


class DecisionListItem(BaseModel):
    decision_id: str
    decision: Literal["ALLOW", "DENY", "TERMINAL", "UNKNOWN"]
    action: str | None = None
    tool: str | None = None
    department: str | None = None
    recorded_at: float
    entry_count: int


class DecisionListResponse(BaseModel):
    success: Literal[True] = True
    ledger_integrity: bool
    decisions: list[DecisionListItem]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
