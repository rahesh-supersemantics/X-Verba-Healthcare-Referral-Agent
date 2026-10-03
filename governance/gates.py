"""
X-Verba VSL governance gates for the healthcare referral agent.

This module defines HOW governance is enforced. It is the single
authoritative call site for every governed decision:

    pre-tool decisions     governed_tool_call()          (via governance.maf_gates)
    create referral        governed_referral()
    update referral        governed_referral_update()
    cancel referral        governed_referral_cancel()
    request clinical review governed_review_request()

Every decision follows the same VSL evidence sequence (decision_engine):

    MONITOR
      -> PRE_NODE #1 -> VERIFICATION (passed)          one VERIFICATION per
      -> PRE_NODE #2 -> VERIFICATION (passed)          PRE_NODE (audit check 3)
      -> ...
      -> PRE_NODE #n -> [invariants] -> VERIFICATION (approved | denied | INSUFFICIENT)
                                         -> TERMINAL on invariant violation

All gates compile once at import time with the vsl-maf adapter. Database
facts are looked up HERE and handed to the policy constructs, so
governance/policy.py stays declarative (vsl_core imports only).

A side effect may only execute after the corresponding function returns
decision == "ALLOW".
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from backend.database.connection import SessionLocal
from backend.database.models import (
    Allergy,
    ClinicalReviewRequestRecord,
    ClinicalWorkflowRun,
    Condition,
    Encounter,
    Medication,
    Observation,
    Patient,
    Referral,
)

from governance.ledger import ledger
from governance.policy import (
    AI_PROPOSAL_GROUNDED,
    AI_PROPOSAL_ORIGIN,
    CLINICAL_REVIEW_REQUEST_VALID,
    GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT,
    PATIENT_MUST_EXIST,
    REFERRAL_ACTION_SUSPENDED,
    REFERRAL_CANCEL_VALID,
    REFERRAL_MUST_BELONG_TO_PATIENT,
    REFERRAL_NOT_DUPLICATE,
    REFERRAL_REQUEST_VALID,
    REFERRAL_TARGET_VALID,
    REFERRAL_UPDATE_VALID,
)

from vsl_core.constructs import Invariant, PreNode
from vsl_core.exceptions import (
    AutomationDeniedException,
    InvariantViolation,
)
from vsl_core.identity import IdentityKey, Instance
from vsl_core.ledger import (
    LedgerEntryType,
    VerificationResult,
)
from vsl_maf import MAFAdapter


ACTIVE_REFERRAL_STATUS = "PENDING"
OPEN_REVIEW_STATUS = "OPEN"


# ============================================================
# Compile gates once
# ============================================================

_adapter = MAFAdapter()

_COMPILED: dict[str, Any] = {}


def compiled_gate(construct: PreNode | Invariant) -> Any:
    """The vsl-maf compiled gate for a policy construct (compiled once)."""

    gate = _COMPILED.get(construct.name)
    if gate is None:
        gate = (
            _adapter.compile_pre_node(construct)
            if isinstance(construct, PreNode)
            else _adapter.compile_invariant(construct)
        )
        _COMPILED[construct.name] = gate
    return gate



# ============================================================
# Agent identity
# ============================================================

INSTANCE = Instance.new(
    IdentityKey(
        value="x-verba-healthcare-referral-agent"
    )
)


# ============================================================
# Decision engine (one evidence shape for every governed decision)
# ============================================================

@dataclass
class Check:
    """One policy construct evaluated against one candidate."""

    construct: PreNode | Invariant
    candidate: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))


async def decision_engine(
    *,
    action: str,
    monitor_payload: dict[str, Any],
    pre_nodes: list[Check],
    invariants: list[Check],
) -> dict[str, Any]:
    """
    Evaluate PreNodes in order, then Invariants, writing the VSL evidence.

    Returns {"decision": ALLOW | DENY | TERMINAL, "decision_id", ...}.
    Never performs a side effect.
    """

    if not pre_nodes:
        raise ValueError("A governed decision needs at least one PreNode.")

    decision_id = str(uuid.uuid4())
    identity = INSTANCE.identity_key.value
    instance_id = INSTANCE.instance_id

    monitor_entry = ledger.write_monitor(
        identity_key=identity,
        instance_id=instance_id,
        decision_id=decision_id,
        drift_detected=False,
        extra_payload=_json_safe({"action": action, **monitor_payload}),
    )

    last_pre_node_entry = None

    for index, check in enumerate(pre_nodes):
        pre_node = check.construct
        denied: AutomationDeniedException | None = None
        try:
            await compiled_gate(pre_node)(check.candidate)
        except AutomationDeniedException as exc:
            denied = exc

        last_pre_node_entry = ledger.write(
            LedgerEntryType.PRE_NODE,
            identity_key=identity,
            instance_id=instance_id,
            decision_id=decision_id,
            caused_by=monitor_entry.entry_id,
            payload=_json_safe(
                {
                    "pre_node": pre_node.name,
                    "denied": denied is not None,
                    "assurance_level": pre_node.assurance_level.value,
                    **check.evidence,
                }
            ),
        )

        if denied is not None:
            # A PreNode correctly denying is governance WORKING -> SUFFICIENT.
            ledger.write_verification(
                identity_key=identity,
                instance_id=instance_id,
                decision_id=decision_id,
                caused_by=last_pre_node_entry.entry_id,
                result=VerificationResult.SUFFICIENT,
                extra_payload={"outcome": "denied", "reason": str(denied)},
            )
            return {
                "decision": "DENY",
                "decision_id": decision_id,
                "reason": str(denied),
                "pre_node": pre_node.name,
            }

        if index < len(pre_nodes) - 1:
            # Every PRE_NODE gets its own VERIFICATION (ledger audit check 3).
            ledger.write_verification(
                identity_key=identity,
                instance_id=instance_id,
                decision_id=decision_id,
                caused_by=last_pre_node_entry.entry_id,
                result=VerificationResult.SUFFICIENT,
                extra_payload={"outcome": "passed", "pre_node": pre_node.name},
            )

    for check in invariants:
        try:
            await compiled_gate(check.construct)(check.candidate)
        except InvariantViolation as exc:
            terminal_state = exc.terminal_state_name or REFERRAL_ACTION_SUSPENDED.name
            verification_entry = ledger.write_verification(
                identity_key=identity,
                instance_id=instance_id,
                decision_id=decision_id,
                caused_by=last_pre_node_entry.entry_id,
                result=VerificationResult.INSUFFICIENT,
                extra_payload={"outcome": "invariant_violated", "invariant": exc.invariant_name},
            )
            terminal_entry = ledger.write(
                LedgerEntryType.TERMINAL,
                identity_key=identity,
                instance_id=instance_id,
                decision_id=decision_id,
                caused_by=verification_entry.entry_id,
                payload={"terminal_state": terminal_state},
            )
            return {
                "decision": "TERMINAL",
                "decision_id": decision_id,
                "reason": str(exc),
                "invariant": exc.invariant_name,
                "terminal_state": terminal_state,
                "terminal_entry_id": terminal_entry.entry_id,
            }

    verification_entry = ledger.write_verification(
        identity_key=identity,
        instance_id=instance_id,
        decision_id=decision_id,
        caused_by=last_pre_node_entry.entry_id,
        result=VerificationResult.SUFFICIENT,
        extra_payload={"outcome": "approved"},
    )

    return {
        "decision": "ALLOW",
        "decision_id": decision_id,
        "verification_entry_id": verification_entry.entry_id,
        "reason": "All governance checks passed.",
    }


# ============================================================
# Database facts (read-only)
# ============================================================

def _patient_exists(patient_id: Any) -> bool:
    """Database fact supplied to the PATIENT_MUST_EXIST invariant."""

    if not isinstance(patient_id, str) or not patient_id.strip():
        return False

    session = SessionLocal()
    try:
        return session.get(Patient, patient_id) is not None
    finally:
        session.close()


def _normalize(text: Any) -> str:
    return " ".join(str(text).split()).casefold()


def _evidence_support(
    patient_id: Any,
    evidence: Any,
) -> tuple[int, int, list[str]]:
    """
    Database facts supplied to the AI_PROPOSAL_GROUNDED PreNode.

    Returns (cited, supported, unsupported_items). A cited item is
    supported only when it matches a condition, medication, allergy,
    observation type or encounter type recorded for THIS patient (exact
    match, or one text containing the other). Evidence that exists only
    in another patient's record is therefore unsupported.
    """

    items = [e for e in (evidence or ()) if isinstance(e, str) and e.strip()]
    if not items or not isinstance(patient_id, str):
        return len(items), 0, items

    session = SessionLocal()
    try:
        record: set[str] = set()
        for column, model in (
            (Condition.condition, Condition),
            (Medication.medication, Medication),
            (Allergy.allergy, Allergy),
            (Observation.type, Observation),
            (Encounter.type, Encounter),
        ):
            rows = session.scalars(
                select(column).where(model.patient_id == patient_id).distinct()
            ).all()
            record.update(_normalize(r) for r in rows if r)
    finally:
        session.close()

    def supported(item: str) -> bool:
        cited = _normalize(item)
        if cited in record:
            return True
        return any(
            (len(cited) >= 4 and cited in fact) or (len(fact) >= 6 and fact in cited)
            for fact in record
        )

    unsupported = [item for item in items if not supported(item)]
    return len(items), len(items) - len(unsupported), unsupported


def _department_supported(department: Any) -> tuple[bool, str | None]:
    from backend.proposals import normalize_department

    normalized = normalize_department(department)
    return normalized is not None, normalized


def _active_duplicates(patient_id: Any, department: str | None) -> list[int]:
    """IDs of PENDING referrals for the same patient and department."""

    if not isinstance(patient_id, str) or not department:
        return []
    session = SessionLocal()
    try:
        return list(
            session.scalars(
                select(Referral.referral_id).where(
                    Referral.patient_id == patient_id,
                    func.lower(Referral.department) == department.casefold(),
                    Referral.status == ACTIVE_REFERRAL_STATUS,
                )
            ).all()
        )
    finally:
        session.close()


def _workflow_patient(workflow_id: Any) -> str | None:
    """The patient the clinical workflow deterministically resolved."""

    if not isinstance(workflow_id, str):
        return None
    session = SessionLocal()
    try:
        run = session.get(ClinicalWorkflowRun, workflow_id)
        if run is None:
            return None
        snapshot = json.loads(run.result_json)
        return (snapshot.get("patient") or {}).get("patient_id")
    except (ValueError, TypeError):
        return None
    finally:
        session.close()


def _referral_facts(referral_id: Any, patient_id: Any) -> dict[str, Any]:
    session = SessionLocal()
    try:
        referral = session.get(Referral, referral_id) if isinstance(referral_id, int) else None
        if referral is None:
            return {"referral_exists": False, "referral_active": False, "referral_belongs_to_patient": False,
                    "current": None}
        return {
            "referral_exists": True,
            "referral_active": referral.status == ACTIVE_REFERRAL_STATUS,
            "referral_belongs_to_patient": referral.patient_id == patient_id,
            "current": {
                "department": referral.department,
                "reason": referral.reason,
                "status": referral.status,
            },
        }
    finally:
        session.close()


def _is_filled(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ============================================================
# Governed referral creation
# ============================================================

async def governed_referral(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Governance for CREATE_REFERRAL.

    PreNodes:   REFERRAL_REQUEST_VALID -> REFERRAL_TARGET_VALID
                -> [AI_PROPOSAL_GROUNDED, AI proposals only]
                -> REFERRAL_NOT_DUPLICATE
    Invariants: PATIENT_MUST_EXIST
                -> [GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT, AI proposals only]

    Returns ALLOW / DENY / TERMINAL. Does NOT create the referral.
    """

    patient_id = candidate.get("patient_id")
    is_ai = candidate.get("origin") == AI_PROPOSAL_ORIGIN

    supported, normalized_department = _department_supported(candidate.get("department"))
    duplicates = _active_duplicates(patient_id, normalized_department)

    pre_nodes = [
        Check(REFERRAL_REQUEST_VALID, candidate),
        Check(
            REFERRAL_TARGET_VALID,
            {"department_supported": supported},
            {"department": candidate.get("department")},
        ),
    ]

    if is_ai:
        cited, supported_count, unsupported = _evidence_support(patient_id, candidate.get("evidence"))
        pre_nodes.append(
            Check(
                AI_PROPOSAL_GROUNDED,
                {**candidate, "evidence_cited": cited, "evidence_supported": supported_count},
                {
                    "evidence_cited": cited,
                    "evidence_supported": supported_count,
                    "evidence_unsupported": unsupported[:10],
                },
            )
        )

    pre_nodes.append(
        Check(
            REFERRAL_NOT_DUPLICATE,
            {"no_active_duplicate": not duplicates},
            {"active_duplicate_referral_ids": duplicates[:10]},
        )
    )

    invariants = [Check(PATIENT_MUST_EXIST, {**candidate, "patient_exists": _patient_exists(patient_id)})]

    if is_ai:
        workflow_patient = _workflow_patient(candidate.get("workflow_id"))
        invariants.append(
            Check(
                GOVERNANCE_CONTEXT_MUST_MATCH_PATIENT,
                {"context_patient_matches": workflow_patient is not None and workflow_patient == patient_id},
            )
        )

    monitor_payload: dict[str, Any] = {
        "patient_id": patient_id,
        "department": candidate.get("department"),
    }
    if candidate.get("origin"):
        # Phase 2: provenance of AI-originated proposals.
        monitor_payload["origin"] = candidate.get("origin")
        monitor_payload["workflow_id"] = candidate.get("workflow_id")

    return await decision_engine(
        action="CREATE_REFERRAL",
        monitor_payload=monitor_payload,
        pre_nodes=pre_nodes,
        invariants=invariants,
    )


# ============================================================
# Governed referral update / cancellation
# ============================================================

async def governed_referral_update(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Governance for UPDATE_REFERRAL.

    PreNodes:   REFERRAL_UPDATE_VALID (exists, active, a valid change)
                [REFERRAL_NOT_DUPLICATE when the department changes]
    Invariants: PATIENT_MUST_EXIST, REFERRAL_MUST_BELONG_TO_PATIENT
    """

    patient_id = candidate.get("patient_id")
    facts = _referral_facts(candidate.get("referral_id"), patient_id)
    current = facts.pop("current") or {}

    new_department = candidate.get("department")
    new_reason = candidate.get("reason")
    department_ok = True
    if new_department is not None:
        department_ok, normalized = _department_supported(new_department)
        new_department = normalized or new_department
    reason_ok = new_reason is None or _is_filled(new_reason)

    changes = {}
    current_department = str(current.get("department") or "")
    if new_department is not None and str(new_department).casefold() != current_department.casefold():
        changes["department"] = {"from": current.get("department"), "to": new_department}
    if new_reason is not None and new_reason != current.get("reason"):
        changes["reason"] = {"from": current.get("reason"), "to": new_reason}

    pre_nodes = [
        Check(
            REFERRAL_UPDATE_VALID,
            {**facts, "change_requested": bool(changes), "change_valid": department_ok and reason_ok},
            {k: facts[k] for k in ("referral_exists", "referral_active")},
        )
    ]
    if "department" in changes:
        # Moving a referral to a department that already has an active
        # referral would create the duplicate that CREATE blocks.
        duplicates = [
            rid for rid in _active_duplicates(patient_id, new_department)
            if rid != candidate.get("referral_id")
        ]
        pre_nodes.append(
            Check(
                REFERRAL_NOT_DUPLICATE,
                {"no_active_duplicate": not duplicates},
                {"department": new_department, "active_duplicate_referral_ids": duplicates[:10]},
            )
        )

    return await decision_engine(
        action="UPDATE_REFERRAL",
        monitor_payload={"patient_id": patient_id, "referral_id": candidate.get("referral_id"), "changes": changes},
        pre_nodes=pre_nodes,
        invariants=[
            Check(PATIENT_MUST_EXIST, {"patient_exists": _patient_exists(patient_id)}),
            Check(REFERRAL_MUST_BELONG_TO_PATIENT, facts),
        ],
    )


async def governed_referral_cancel(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Governance for CANCEL_REFERRAL.

    PreNodes:   REFERRAL_CANCEL_VALID (exists, active, reason stated)
    Invariants: PATIENT_MUST_EXIST, REFERRAL_MUST_BELONG_TO_PATIENT
    """

    patient_id = candidate.get("patient_id")
    facts = _referral_facts(candidate.get("referral_id"), patient_id)
    facts.pop("current")

    return await decision_engine(
        action="CANCEL_REFERRAL",
        monitor_payload={
            "patient_id": patient_id,
            "referral_id": candidate.get("referral_id"),
            "cancellation_reason": candidate.get("cancellation_reason"),
        },
        pre_nodes=[
            Check(
                REFERRAL_CANCEL_VALID,
                {**facts, "cancellation_reason_given": _is_filled(candidate.get("cancellation_reason"))},
                {k: facts[k] for k in ("referral_exists", "referral_active")},
            )
        ],
        invariants=[
            Check(PATIENT_MUST_EXIST, {"patient_exists": _patient_exists(patient_id)}),
            Check(REFERRAL_MUST_BELONG_TO_PATIENT, facts),
        ],
    )


# ============================================================
# Governed clinical review request (human review queue)
# ============================================================

def _open_review_duplicates(patient_id: Any, department: Any, referral_id: Any) -> list[int]:
    if not isinstance(patient_id, str):
        return []
    session = SessionLocal()
    try:
        statement = select(ClinicalReviewRequestRecord.review_request_id).where(
            ClinicalReviewRequestRecord.patient_id == patient_id,
            ClinicalReviewRequestRecord.status == OPEN_REVIEW_STATUS,
        )
        if referral_id is not None:
            statement = statement.where(ClinicalReviewRequestRecord.referral_id == referral_id)
        elif department:
            statement = statement.where(func.lower(ClinicalReviewRequestRecord.department) == str(department).casefold())
        else:
            statement = statement.where(
                ClinicalReviewRequestRecord.referral_id.is_(None),
                ClinicalReviewRequestRecord.department.is_(None),
            )
        return list(session.scalars(statement).all())
    finally:
        session.close()


async def governed_review_request(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Governance for REQUEST_CLINICAL_REVIEW.

    PreNodes:   CLINICAL_REVIEW_REQUEST_VALID (reason stated, no open duplicate,
                referenced referral exists)
    Invariants: PATIENT_MUST_EXIST
                [REFERRAL_MUST_BELONG_TO_PATIENT when a referral is referenced]
    """

    patient_id = candidate.get("patient_id")
    referral_id = candidate.get("referral_id")
    duplicates = _open_review_duplicates(patient_id, candidate.get("department"), referral_id)

    invariants = [Check(PATIENT_MUST_EXIST, {"patient_exists": _patient_exists(patient_id)})]
    referral_exists = True
    if referral_id is not None:
        facts = _referral_facts(referral_id, patient_id)
        referral_exists = facts["referral_exists"]
        invariants.append(Check(REFERRAL_MUST_BELONG_TO_PATIENT, facts))

    return await decision_engine(
        action="REQUEST_CLINICAL_REVIEW",
        monitor_payload={
            "patient_id": patient_id,
            "referral_id": referral_id,
            "department": candidate.get("department"),
        },
        pre_nodes=[
            Check(
                CLINICAL_REVIEW_REQUEST_VALID,
                {
                    "review_reason_given": _is_filled(candidate.get("reason")),
                    "no_open_review_duplicate": not duplicates,
                    "referenced_referral_exists": referral_exists,
                },
                {"open_review_request_ids": duplicates[:10], "referenced_referral_exists": referral_exists},
            )
        ],
        invariants=invariants,
    )


# ============================================================
# Pre-tool governance (called by governance.maf_gates)
# ============================================================

async def governed_tool_call(
    *,
    tool: str,
    pre_nodes: list[Check],
    monitor_payload: dict[str, Any],
) -> dict[str, Any]:
    """Ledgered pre-tool decision. Tool body runs only on ALLOW."""

    return await decision_engine(
        action="TOOL_CALL",
        monitor_payload={"tool": tool, **monitor_payload},
        pre_nodes=pre_nodes,
        invariants=[],
    )
