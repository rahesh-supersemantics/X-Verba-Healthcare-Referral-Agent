"""
X-Verba VSL governance policy for the healthcare referral agent.

This module defines the governance constructs used by the
healthcare referral workflow.

Application/database actions do not belong in this module.
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

REFERRAL_ASSURANCE = AssuranceBasis(
    f1_pre_commitment=True,
    f2_modification=F2Modification.NONE,
)


# ============================================================
# PRE-NODE MONITOR
# ============================================================

async def referral_request_monitor(
    candidate_input: Any,
) -> GammaEstimate:
    """
    Calculate a Gamma estimate for a referral request.

    A complete referral request contains:
        - patient_id
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


# ============================================================
# PRE-NODE
# ============================================================

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
# INVARIANT
# ============================================================

async def patient_exists_rule(
    candidate_input: Any,
) -> bool:
    """
    Verify that the governance context confirms that the
    referenced patient exists.

    The actual database lookup is performed by the governance
    gate layer. This policy remains independent of application
    infrastructure.
    """

    if not isinstance(candidate_input, dict):
        return False

    return candidate_input.get("patient_exists") is True

    patient_id = candidate_input.get("patient_id")
    session = candidate_input.get("session")

    if not patient_id or session is None:
        return False

    from backend.database.models import Patient

    patient = session.get(Patient, patient_id)

    return patient is not None

REFERRAL_ACTION_SUSPENDED = TerminalState(
    name="referral-action-suspended",
    description=(
        "Automated referral creation has been halted because "
        "a mandatory healthcare invariant was violated."
    ),
    entry_conditions=(
        "patient does not exist",
    ),
)

PATIENT_MUST_EXIST = Invariant(
    name="PATIENT_MUST_EXIST",
    description=(
        "A referral may only be created for an existing patient."
    ),
    rule=patient_exists_rule,
    assurance_basis=REFERRAL_ASSURANCE,
    scope="CREATE_REFERRAL",
    cannot_be_bypassed=True,
    on_violation=REFERRAL_ACTION_SUSPENDED,
)

# ============================================================
# GOVERNANCE REGISTRY
# ============================================================

ALL_PRE_NODES = [
    REFERRAL_REQUEST_VALID,
]

ALL_INVARIANTS = [
    PATIENT_MUST_EXIST,
]