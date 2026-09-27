"""
X-Verba VSL governance gates for the healthcare referral agent.

The gates compile once at import time.

The side-effecting referral tool must only execute after
this governance function returns ALLOW.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.database.connection import SessionLocal
from backend.database.models import Patient

from governance.ledger import ledger
from governance.policy import (
    PATIENT_MUST_EXIST,
    REFERRAL_ACTION_SUSPENDED,
    REFERRAL_REQUEST_VALID,
)

from vsl_core.conformance.reference_adapter import (
    PlainPythonReferenceAdapter,
)
from vsl_core.exceptions import (
    AutomationDeniedException,
    InvariantViolation,
)
from vsl_core.identity import IdentityKey, Instance
from vsl_core.ledger import (
    LedgerEntryType,
    VerificationResult,
)


# ============================================================
# Compile gates once
# ============================================================

_adapter = PlainPythonReferenceAdapter()

referral_request_gate = _adapter.compile_pre_node(
    REFERRAL_REQUEST_VALID
)

patient_exists_gate = _adapter.compile_invariant(
    PATIENT_MUST_EXIST
)


# ============================================================
# Agent identity
# ============================================================

INSTANCE = Instance.new(
    IdentityKey(
        value="x-verba-healthcare-referral-agent"
    )
)


# ============================================================
# Governed referral action
# ============================================================

async def governed_referral(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute the complete VSL governance sequence.

    Returns one of:

        ALLOW
        DENY
        TERMINAL

    This function does NOT create the referral.

    The caller may invoke create_referral() only when
    decision == "ALLOW".
    """

    decision_id = str(uuid.uuid4())
    identity = INSTANCE.identity_key.value

    # ========================================================
    # 1. MONITOR
    # ========================================================

    monitor_entry = ledger.write_monitor(
        identity_key=identity,
        instance_id=INSTANCE.instance_id,
        decision_id=decision_id,
        drift_detected=False,
        extra_payload={
            "action": "CREATE_REFERRAL",
            "patient_id": candidate.get("patient_id"),
            "department": candidate.get("department"),
        },
    )

    # ========================================================
    # 2. PRE-NODE
    # ========================================================

    denied = None

    try:
        await referral_request_gate(candidate)

    except AutomationDeniedException as exc:
        denied = exc

    pre_node_entry = ledger.write(
        LedgerEntryType.PRE_NODE,
        identity_key=identity,
        instance_id=INSTANCE.instance_id,
        decision_id=decision_id,
        caused_by=monitor_entry.entry_id,
        payload={
            "pre_node": REFERRAL_REQUEST_VALID.name,
            "denied": denied is not None,
            "assurance_level": (
                REFERRAL_REQUEST_VALID.assurance_level.value
            ),
        },
    )

    # ========================================================
    # PRE-NODE DENIAL
    # ========================================================

    if denied is not None:
        # PreNode denial means the governance control
        # successfully detected and blocked the request.
        #
        # Therefore, the verification result is SUFFICIENT.

        ledger.write_verification(
            identity_key=identity,
            instance_id=INSTANCE.instance_id,
            decision_id=decision_id,
            caused_by=pre_node_entry.entry_id,
            result=VerificationResult.SUFFICIENT,
            extra_payload={
                "outcome": "denied",
                "reason": str(denied),
            },
        )

        return {
            "decision": "DENY",
            "decision_id": decision_id,
            "reason": str(denied),
        }

    # ========================================================
    # 3. INVARIANT
    # ========================================================

    session = SessionLocal()

    try:
        patient_exists = (
            session.get(
                Patient,
                candidate.get("patient_id"),
            )
            is not None
        )

        governance_candidate = {
            **candidate,
            "patient_exists": patient_exists,
        }

        await patient_exists_gate(
            governance_candidate
        )

    except InvariantViolation as exc:

        # ----------------------------------------------------
        # Invariant failed
        # ----------------------------------------------------

        verification_entry = ledger.write_verification(
            identity_key=identity,
            instance_id=INSTANCE.instance_id,
            decision_id=decision_id,
            caused_by=pre_node_entry.entry_id,
            result=VerificationResult.INSUFFICIENT,
            extra_payload={
                "invariant": exc.invariant_name,
            },
        )

        terminal_entry = ledger.write(
            LedgerEntryType.TERMINAL,
            identity_key=identity,
            instance_id=INSTANCE.instance_id,
            decision_id=decision_id,
            caused_by=verification_entry.entry_id,
            payload={
                "terminal_state": (
                    exc.terminal_state_name
                    or REFERRAL_ACTION_SUSPENDED.name
                ),
            },
        )

        return {
            "decision": "TERMINAL",
            "decision_id": decision_id,
            "reason": str(exc),
            "invariant": exc.invariant_name,
            "terminal_state": (
                exc.terminal_state_name
                or REFERRAL_ACTION_SUSPENDED.name
            ),
            "terminal_entry_id": terminal_entry.entry_id,
        }

    finally:
        session.close()

    # ========================================================
    # 4. ALL GOVERNANCE CHECKS PASSED
    # ========================================================

    verification_entry = ledger.write_verification(
        identity_key=identity,
        instance_id=INSTANCE.instance_id,
        decision_id=decision_id,
        caused_by=pre_node_entry.entry_id,
        result=VerificationResult.SUFFICIENT,
        extra_payload={
            "outcome": "approved",
        },
    )

    # ========================================================
    # 5. ALLOW
    # ========================================================

    return {
        "decision": "ALLOW",
        "decision_id": decision_id,
        "verification_entry_id": verification_entry.entry_id,
        "reason": "All referral governance checks passed.",
    }