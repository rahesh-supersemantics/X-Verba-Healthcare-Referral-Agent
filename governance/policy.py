"""
X-Verba VSL governance policy for the healthcare referral agent.

This module defines WHAT is governed. Declarations only.

Import rule: this module imports only vsl_core. Application, database
and model access belong in governance/gates.py or the backend.
"""

from typing import Any

from vsl_core import (
    AssuranceBasis,
    F2Modification,
    GammaEstimate,
    Invariant,
    PreNode,
    TerminalState,
)


# ============================================================
# ASSURANCE
# ============================================================

# F1 = True : every gate runs strictly before the side effect.
# F2 = NONE : output-layer control; the gates do not modify the model.
# Derived assurance level is therefore LOW (honest, per the VSL spec).
REFERRAL_ASSURANCE = AssuranceBasis(
    f1_pre_commitment=True,
    f2_modification=F2Modification.NONE,
)


def _is_filled(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ============================================================
# PRE-NODE: agent intake (vsl-maf boundary)
# ============================================================

async def referral_intent_monitor(
    candidate_input: Any,
) -> GammaEstimate:
    """
    Gamma estimate for the referral intent the LLM extracted from a
    staff member's request (the arguments of the agent's
    ``create_referral`` tool call).

    Complete intent = patient_name, department and reason all present.
    Deterministic in Phase 1 so behaviour is reproducible in tests.
    """

    if not isinstance(candidate_input, dict):
        return GammaEstimate(gamma_hat=0.0, delta_estimation_error=0.0)

    complete = (
        _is_filled(candidate_input.get("patient_name"))
        and _is_filled(candidate_input.get("department"))
        and _is_filled(candidate_input.get("reason"))
    )

    return GammaEstimate(
        gamma_hat=2.0 if complete else 0.0,
        delta_estimation_error=0.0,
    )


REFERRAL_INTENT_COMPLETE = PreNode(
    name="REFERRAL_INTENT_COMPLETE",
    description=(
        "The agent's referral tool call must carry a patient name, a "
        "department and a referral reason extracted from the staff "
        "request before any patient resolution or governance runs."
    ),
    monitor=referral_intent_monitor,
    assurance_basis=REFERRAL_ASSURANCE,
    gamma_threshold=1.1,
)


# ============================================================
# PRE-NODE: referral candidate
# ============================================================

async def referral_request_monitor(
    candidate_input: Any,
) -> GammaEstimate:
    """
    Calculate a Gamma estimate for a referral candidate.

    A complete referral candidate contains:
        - patient_id   (resolved deterministically by the application)
        - department
        - reason

    Gamma is deliberately deterministic in Phase 1 so that
    governance behavior can be tested reproducibly.
    """

    if not isinstance(candidate_input, dict):
        return GammaEstimate(gamma_hat=0.0)

    patient_id = candidate_input.get("patient_id")
    department = candidate_input.get("department")
    reason = candidate_input.get("reason")

    request_is_complete = bool(
        patient_id
        and str(patient_id).strip()
        and department
        and str(department).strip()
        and reason
        and str(reason).strip()
    )

    if request_is_complete:
        return GammaEstimate(
            gamma_hat=2.0,
            delta_estimation_error=0.0,
        )

    return GammaEstimate(
        gamma_hat=0.0,
        delta_estimation_error=0.0,
    )


REFERRAL_REQUEST_VALID = PreNode(
    name="REFERRAL_REQUEST_VALID",
    description=(
        "A referral request must contain a patient identifier, "
        "department, and referral reason."
    ),
    monitor=referral_request_monitor,
    assurance_basis=REFERRAL_ASSURANCE,
    gamma_threshold=1.1,
)


# ============================================================
# PRE-NODE: AI-originated action proposals (Phase 2)
# ============================================================

AI_PROPOSAL_ORIGIN = "AI_PROPOSAL"


async def ai_proposal_grounding_monitor(
    candidate_input: Any,
) -> GammaEstimate:
    """
    Gamma estimate for a referral proposed by the clinical-review AI.

    The proposal must cite at least one item of evidence, and EVERY cited
    item must exist in the patient's record. The record lookup is done
    by the gate layer (governance/gates.py), which supplies:

        evidence_cited      int  number of evidence items the AI cited
        evidence_supported  int  number of those found in the record

    Deterministic in Phase 2 so behaviour is reproducible in tests.
    """

    if not isinstance(candidate_input, dict):
        return GammaEstimate(gamma_hat=0.0, delta_estimation_error=0.0)

    cited = candidate_input.get("evidence_cited")
    supported = candidate_input.get("evidence_supported")

    grounded = (
        isinstance(cited, int)
        and isinstance(supported, int)
        and cited >= 1
        and supported == cited
    )

    return GammaEstimate(
        gamma_hat=2.0 if grounded else 0.0,
        delta_estimation_error=0.0,
    )


AI_PROPOSAL_GROUNDED = PreNode(
    name="AI_PROPOSAL_GROUNDED",
    description=(
        "A referral proposed by AI analysis must cite evidence that exists "
        "in the patient's record. Ungrounded proposals are denied and "
        "routed to human review."
    ),
    monitor=ai_proposal_grounding_monitor,
    assurance_basis=REFERRAL_ASSURANCE,
    gamma_threshold=1.1,
)


# ============================================================
# INVARIANT
# ============================================================

async def patient_exists_rule(
    candidate_input: Any,
) -> bool:
    """
    Verify that the governance context confirms that the
    referenced patient exists.

    The actual database lookup is performed by the governance
    gate layer (governance/gates.py). This policy remains independent
    of application infrastructure.
    """

    if not isinstance(candidate_input, dict):
        return False

    return candidate_input.get("patient_exists") is True


REFERRAL_ACTION_SUSPENDED = TerminalState(
    name="referral-action-suspended",
    description=(
        "The governed referral action has been halted because "
        "a mandatory healthcare invariant was violated."
    ),
    entry_conditions=(
        "patient does not exist",
    ),
)

PATIENT_MUST_EXIST = Invariant(
    name="PATIENT_MUST_EXIST",
    description=(
        "A referral action (create, update, cancel, review request) may only "
        "be performed for an existing patient."
    ),
    rule=patient_exists_rule,
    assurance_basis=REFERRAL_ASSURANCE,
    scope="CREATE_REFERRAL / UPDATE_REFERRAL / CANCEL_REFERRAL / REQUEST_CLINICAL_REVIEW",
    cannot_be_bypassed=True,
    on_violation=REFERRAL_ACTION_SUSPENDED,
)


# ============================================================
# PHASE 3: fact-based constructs
# ============================================================
#
# Every Phase 3 construct below consumes boolean FACTS that the gate layer
# (governance/gates.py, governance/maf_gates.py) computes from the
# database and the conversation context. Policy stays declarative and
# imports only vsl_core: it states WHAT must be true, not how to look it up.


def _facts_monitor(*fact_keys: str):
    """PreNode monitor: Gamma 2.0 only when every named fact is True."""

    async def monitor(candidate_input: Any) -> GammaEstimate:
        ok = isinstance(candidate_input, dict) and all(
            candidate_input.get(key) is True for key in fact_keys
        )
        return GammaEstimate(gamma_hat=2.0 if ok else 0.0, delta_estimation_error=0.0)

    monitor.__name__ = "facts_monitor__" + "__".join(fact_keys)
    return monitor


def _facts_rule(*fact_keys: str):
    """Invariant rule: holds only when every named fact is True."""

    async def rule(candidate_input: Any) -> bool:
        return isinstance(candidate_input, dict) and all(
            candidate_input.get(key) is True for key in fact_keys
        )

    rule.__name__ = "facts_rule__" + "__".join(fact_keys)
    return rule


def _pre_node(name: str, description: str, *facts: str) -> PreNode:
    return PreNode(
        name=name,
        description=description,
        monitor=_facts_monitor(*facts),
        assurance_basis=REFERRAL_ASSURANCE,
        gamma_threshold=1.1,
    )


# ---- Pre-tool PreNodes (vsl-maf boundary, before any tool body runs) ----

PATIENT_SEARCH_REQUEST_VALID = _pre_node(
    "PATIENT_SEARCH_REQUEST_VALID",
    "A patient search must use a name the staff member actually supplied "
    "in this conversation. Prevents the model from trawling patient records "
    "with invented queries.",
    "search_term_from_staff",
    "search_term_valid",
)

CLINICAL_DATA_ACCESS_VALID = _pre_node(
    "CLINICAL_DATA_ACCESS_VALID",
    "Clinical data may only be read for a patient the staff member named "
    "(or unambiguously referred to) in this conversation, and only once the "
    "name resolves to exactly one patient.",
    "patient_named_by_staff",
    "patient_resolved",
)

ACTION_INPUT_GROUNDED = _pre_node(
    "ACTION_INPUT_GROUNDED",
    "Inputs of a side-effecting tool (patient, referral number, free-text "
    "reason) must come from the staff member, not be invented by the model. "
    "Placeholder reasons such as 'Unknown' are not grounded.",
    "patient_named_by_staff",
    "text_stated_by_staff",
    "reference_stated_by_staff",
)

REFERRAL_CONFIRMED_BY_STAFF = _pre_node(
    "REFERRAL_CONFIRMED_BY_STAFF",
    "A referral prepared in conversation may only be submitted after the "
    "staff member confirmed it, and only for the patient and department they "
    "confirmed. A model cannot create a referral the clinician declined or "
    "never confirmed.",
    "referral_confirmed",
    "matches_confirmed_details",
)

# ---- Action-level PreNodes (governance.gates, before the side effect) ----

REFERRAL_TARGET_VALID = _pre_node(
    "REFERRAL_TARGET_VALID",
    "The receiving department must be in the supported referral catalogue.",
    "department_supported",
)

REFERRAL_NOT_DUPLICATE = _pre_node(
    "REFERRAL_NOT_DUPLICATE",
    "No equivalent active (PENDING) referral may already exist for the same "
    "patient and department. Soft gate: a clinician may legitimately need a "
    "second referral, so a duplicate is DENIED and routed to a human.",
    "no_active_duplicate",
)

REFERRAL_UPDATE_VALID = _pre_node(
    "REFERRAL_UPDATE_VALID",
    "An update must target an existing, active referral and request a "
    "valid change (supported department and/or non-empty reason).",
    "referral_exists",
    "referral_active",
    "change_requested",
    "change_valid",
)

REFERRAL_CANCEL_VALID = _pre_node(
    "REFERRAL_CANCEL_VALID",
    "A cancellation must target an existing, active referral and state a "
    "cancellation reason.",
    "referral_exists",
    "referral_active",
    "cancellation_reason_given",
)

CLINICAL_REVIEW_REQUEST_VALID = _pre_node(
    "CLINICAL_REVIEW_REQUEST_VALID",
    "A clinical review request must state a reason, must not duplicate an "
    "open review request for the same patient and topic, and any referral "
    "number it cites must exist.",
    "review_reason_given",
    "no_open_review_duplicate",
    "referenced_referral_exists",
)

# ---- Invariants: never acceptable, no automated way out ----

PATIENT_CONTEXT_VIOLATION = TerminalState(
    name="patient-context-integrity-violation",
    description=(
        "Automation halted: the governed action's patient did not match the "
        "patient established by the workflow or the referral record."
    ),
    entry_conditions=(
        "AI proposal patient differs from workflow patient",
        "referral belongs to a different patient",
    ),
)

GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT = Invariant(
    name="GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT",
    description=(
        "An AI-originated action must concern exactly the patient that its "
        "clinical workflow deterministically resolved."
    ),
    rule=_facts_rule("context_patient_matches"),
    assurance_basis=REFERRAL_ASSURANCE,
    scope="CREATE_REFERRAL",
    cannot_be_bypassed=True,
    on_violation=PATIENT_CONTEXT_VIOLATION,
)

REFERRAL_MUST_BELONG_TO_PATIENT = Invariant(
    name="REFERRAL_MUST_BELONG_TO_PATIENT",
    description=(
        "A referral may only be changed, cancelled or reviewed in the context "
        "of the patient it belongs to."
    ),
    rule=_facts_rule("referral_belongs_to_patient"),
    assurance_basis=REFERRAL_ASSURANCE,
    scope="UPDATE_REFERRAL / CANCEL_REFERRAL / REQUEST_CLINICAL_REVIEW",
    cannot_be_bypassed=True,
    on_violation=PATIENT_CONTEXT_VIOLATION,
)


# ============================================================
# GOVERNANCE REGISTRY
# ============================================================

ALL_PRE_NODES = [
    REFERRAL_INTENT_COMPLETE,
    REFERRAL_REQUEST_VALID,
    AI_PROPOSAL_GROUNDED,
    PATIENT_SEARCH_REQUEST_VALID,
    CLINICAL_DATA_ACCESS_VALID,
    ACTION_INPUT_GROUNDED,
    REFERRAL_CONFIRMED_BY_STAFF,
    REFERRAL_TARGET_VALID,
    REFERRAL_NOT_DUPLICATE,
    REFERRAL_UPDATE_VALID,
    REFERRAL_CANCEL_VALID,
    CLINICAL_REVIEW_REQUEST_VALID,
]

ALL_INVARIANTS = [
    PATIENT_MUST_EXIST,
    GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT,
    REFERRAL_MUST_BELONG_TO_PATIENT,
]
