"""
vsl-maf integration: X-Verba governance at the Microsoft Agent Framework
tool-call boundary (pre-tool governance).

Every agent tool is wrapped by a GovernedToolMiddleware, a subclass of
vsl-maf's VSLFunctionMiddleware. When the model proposes a tool call:

    LLM proposes tool(args)
        -> facts are computed (conversation context + database)
        -> governance.gates.governed_tool_call()       (ledgered decision,
           PreNodes compiled by the vsl-maf MAFAdapter)  MONITOR/PRE_NODE/
        -> ALLOW -> tool body executes                   VERIFICATION)
        -> DENY  -> tool body NEVER executes; the model receives a
                    structured denial explaining what is missing

Pre-tool PreNodes (governance/policy.py):

    search_patient                       PATIENT_SEARCH_REQUEST_VALID
    get_patient_information,
    get_patient_conditions/medications/
    allergies/observations/encounters,
    review_patient_for_referral          CLINICAL_DATA_ACCESS_VALID
    create_referral                      REFERRAL_INTENT_COMPLETE + ACTION_INPUT_GROUNDED
                                         + REFERRAL_CONFIRMED_BY_STAFF
    update_referral, cancel_referral,
    request_clinical_review              ACTION_INPUT_GROUNDED

These gate the MODEL'S PROPOSAL. The governed side effects behind the
action tools are then governed again, on the resolved candidate, by the
action-level decisions in governance.gates (REFERRAL_REQUEST_VALID,
REFERRAL_TARGET_VALID, REFERRAL_NOT_DUPLICATE, PATIENT_MUST_EXIST, ...).
The two layers evaluate different inputs, so no check is duplicated.

When no conversation is active (an agent run outside ChatService, e.g. a
script), grounding facts cannot be evaluated and are treated as satisfied;
structural checks (patient resolves, inputs complete) still apply.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

from vsl_core.exceptions import AutomationDeniedException
from vsl_maf import VSLFunctionMiddleware

from governance.gates import Check, governed_tool_call
from governance.policy import (
    ACTION_INPUT_GROUNDED,
    CLINICAL_DATA_ACCESS_VALID,
    PATIENT_SEARCH_REQUEST_VALID,
    REFERRAL_CONFIRMED_BY_STAFF,
    REFERRAL_INTENT_COMPLETE,
)


REFERRAL_TOOL_NAME = "create_referral"

CLINICAL_DATA_TOOLS = (
    "get_patient_information",
    "get_patient_conditions",
    "get_patient_medications",
    "get_patient_allergies",
    "get_patient_observations",
    "get_patient_encounters",
    "review_patient_for_referral",
)

# ============================================================
# Fact computation per tool
# ============================================================

def _conversation():
    from backend.conversation import current_conversation

    return current_conversation()


def _patient_facts(patient_name: Any, date_of_birth: Any = None) -> dict[str, Any]:
    """
    Resolve the patient deterministically, exactly as the tool will.

    The structured reference (name, date of birth, established patient) is
    built by the application (backend.conversation); this gate only takes
    the resolution result as a fact. No conversational logic lives here.
    """

    from backend.database.connection import SessionLocal
    from backend.patient_resolution import ResolutionStatus, resolve_patient_by_name

    conversation = _conversation()
    dob = date_of_birth if isinstance(date_of_birth, str) and date_of_birth.strip() else None
    named = conversation.patient_named_by_staff(patient_name) if conversation else True

    if conversation is not None:
        reference, resolution = conversation.resolve_patient(patient_name, dob)
        query = {"patient_name": reference.patient_name, "date_of_birth": reference.date_of_birth}
    else:
        with SessionLocal() as session:
            resolution = resolve_patient_by_name(session, patient_name, dob)
        query = {"patient_name": patient_name, "date_of_birth": dob}

    resolved = resolution.status is ResolutionStatus.RESOLVED and resolution.patient is not None
    return {
        "named": named,
        "resolved": resolved,
        "patient_id": resolution.patient.patient_id if resolved else None,
        "status": resolution.status.value,
        "message": resolution.message,
        "query": query,
        "candidates": [
            {"name": c.name, "date_of_birth": c.date_of_birth} for c in resolution.candidates
        ],
    }


def _text_ok(text: Any, *, exclude: str = "") -> bool:
    conversation = _conversation()
    if conversation is None:
        from backend.conversation import is_placeholder

        return not is_placeholder(text if isinstance(text, str) else "")
    return conversation.text_stated_by_staff(text if isinstance(text, str) else "", exclude=exclude)


def _reference_ok(referral_number: Any) -> bool:
    conversation = _conversation()
    if conversation is None:
        return True
    return conversation.reference_stated_by_staff(referral_number)


def _department_ok(department: Any) -> bool:
    if department in (None, ""):
        return True
    conversation = _conversation()
    if conversation is None:
        return True
    from backend.conversation import words

    return set(words(str(department))) <= conversation.staff_words | {
        w for w in words(conversation.context.department or "")
    }


def _confirmation_facts(args: dict, resolved_name: Any) -> dict[str, bool]:
    """Was this referral confirmed by the staff member, as proposed?"""

    conversation = _conversation()
    if conversation is None:
        return {"referral_confirmed": True, "matches_confirmed_details": True}

    from backend.proposals import normalize_department

    patient = _patient_facts(resolved_name, args.get("date_of_birth"))
    if not patient["resolved"]:
        # Nothing can be written for an unresolved patient: the referral
        # workflow reports PATIENT_NOT_FOUND / MULTIPLE_PATIENT_MATCHES
        # deterministically, which is the clinician-useful answer here.
        return {"referral_confirmed": True, "matches_confirmed_details": True}

    ctx = conversation.context
    confirmed = ctx.intent == "REFERRAL" and ctx.stage == "CONFIRMED" and ctx.patient is not None
    matches = False
    if confirmed:
        department = normalize_department(args.get("department")) or str(args.get("department") or "")
        matches = (
            patient["patient_id"] == ctx.patient.patient_id
            and department.casefold() == (ctx.department or "").casefold()
        )
    return {"referral_confirmed": confirmed, "matches_confirmed_details": matches}


def _search_policy(args: dict) -> tuple[list[Check], dict, dict]:
    name = args.get("name")
    conversation = _conversation()
    from_staff = conversation.patient_named_by_staff(name) if conversation else True
    valid = isinstance(name, str) and len(name.strip()) >= 2
    facts = {"search_term_from_staff": from_staff, "search_term_valid": valid}
    return (
        [Check(PATIENT_SEARCH_REQUEST_VALID, facts, facts)],
        {},
        {"failed": [k for k, v in facts.items() if not v]},
    )


def _data_policy(args: dict) -> tuple[list[Check], dict, dict]:
    patient = _patient_facts(args.get("patient_name"), args.get("date_of_birth"))
    facts = {"patient_named_by_staff": patient["named"], "patient_resolved": patient["resolved"]}
    return (
        [Check(CLINICAL_DATA_ACCESS_VALID, facts, {**facts, "resolution": patient["status"]})],
        {"patient_id": patient["patient_id"]},
        {"failed": [k for k, v in facts.items() if not v], "patient": patient},
    )


def _action_policy(
    args: dict,
    *,
    text_field: str,
    text_required: bool,
    reference_field: str | None,
    reference_required: bool,
    intent_complete: bool = False,
) -> tuple[list[Check], dict, dict]:
    conversation = _conversation()
    raw_name = args.get("patient_name")
    patient_named = conversation.patient_named_by_staff(raw_name) if conversation else True
    resolved_name = conversation.resolve_patient_reference(raw_name) if conversation else raw_name

    text = args.get(text_field)
    if text in (None, ""):
        text_ok = not text_required
    else:
        text_ok = _text_ok(text, exclude=f"{resolved_name or ''} {args.get('department') or ''}")
    text_ok = text_ok and _department_ok(args.get("department"))

    reference = args.get(reference_field) if reference_field else None
    if reference_field and (reference_required or reference not in (None, "")):
        reference_ok = _reference_ok(reference)
    else:
        reference_ok = True

    facts = {
        "patient_named_by_staff": bool(patient_named),
        "text_stated_by_staff": bool(text_ok),
        "reference_stated_by_staff": bool(reference_ok),
    }
    checks = []
    if intent_complete:
        checks.append(Check(REFERRAL_INTENT_COMPLETE, {**args, "patient_name": resolved_name}))
    checks.append(Check(ACTION_INPUT_GROUNDED, facts, facts))
    failed = [k for k, v in facts.items() if not v]
    if intent_complete:
        confirmation = _confirmation_facts(args, resolved_name)
        checks.append(Check(REFERRAL_CONFIRMED_BY_STAFF, confirmation, confirmation))
        if all(facts.values()):  # report confirmation only once inputs are grounded
            failed += [k for k, v in confirmation.items() if not v]
    return checks, {}, {"failed": failed}


TOOL_POLICIES: dict[str, Callable[[dict], tuple[list[Check], dict, dict]]] = {
    "search_patient": _search_policy,
    **{name: _data_policy for name in CLINICAL_DATA_TOOLS},
    REFERRAL_TOOL_NAME: lambda a: _action_policy(
        a, text_field="reason", text_required=True,
        reference_field=None, reference_required=False, intent_complete=True,
    ),
    "update_referral": lambda a: _action_policy(
        a, text_field="reason", text_required=False,
        reference_field="referral_number", reference_required=True,
    ),
    "cancel_referral": lambda a: _action_policy(
        a, text_field="cancellation_reason", text_required=True,
        reference_field="referral_number", reference_required=True,
    ),
    "request_clinical_review": lambda a: _action_policy(
        a, text_field="reason", text_required=True,
        reference_field="referral_number", reference_required=False,
    ),
}


# ============================================================
# Denial shown to the model (the tool body did not run)
# ============================================================

_GUIDANCE = {
    "search_term_from_staff": "The staff member has not named this patient. Ask who they mean; never guess a name.",
    "search_term_valid": "The search term is too short. Ask for the patient's name.",
    "patient_named_by_staff": "The staff member has not named this patient in this conversation. Ask which patient they mean; never invent one.",
    "patient_resolved": "The patient could not be uniquely identified. Ask the staff member to clarify (full name or date of birth).",
    "text_stated_by_staff": "The reason (or department) was not stated by the staff member. Ask for it in their own words; never use a placeholder such as 'Unknown'.",
    "reference_stated_by_staff": "The staff member has not given this referral number. Ask which referral (number) they mean.",
    "referral_confirmed": "The staff member has not confirmed this referral. Summarise patient, department and reason and ask them to confirm; do not call create_referral until they do.",
    "matches_confirmed_details": "These details differ from what the staff member confirmed. Use exactly the confirmed patient and department, or ask them to confirm the new details.",
}

# Clinician-facing wording for the same facts (no rule names, no IDs).
CLINICIAN_GUIDANCE = {
    "search_term_from_staff": "Please tell me which patient you mean.",
    "search_term_valid": "Please tell me the patient's name.",
    "patient_named_by_staff": "Please tell me which patient you mean.",
    "patient_resolved": "The patient could not be uniquely identified. Please give the full name.",
    "text_stated_by_staff": "Please state the reason in your own words.",
    "reference_stated_by_staff": "Please tell me the referral number.",
    "referral_confirmed": "Please confirm the patient, department and reason before I submit the referral.",
    "matches_confirmed_details": "The details differ from what you confirmed. Please confirm the patient, department and reason again.",
}


# ============================================================
# Per-turn record of governed tool attempts (read by backend.chat)
# ============================================================

_attempts: ContextVar[list | None] = ContextVar("xverba_tool_attempts", default=None)


@contextmanager
def capture_tool_attempts() -> Iterator[list]:
    """Collect {tool, decision, executed, failed, error, patient} for each governed tool call."""

    sink: list = []
    token = _attempts.set(sink)
    try:
        yield sink
    finally:
        _attempts.reset(token)


def _record_attempt(**attempt: Any) -> dict:
    sink = _attempts.get()
    if sink is not None:
        sink.append(attempt)
    return attempt


def _denial_view(tool: str, decision: dict, info: dict) -> str:
    failed = info.get("failed") or []
    patient = info.get("patient") or {}
    view = {
        "success": False,
        "status": "GOVERNANCE_DENIED",
        "governance": decision.get("decision", "DENY"),
        "tool_executed": False,
        "message": " ".join(_GUIDANCE[f] for f in failed if f in _GUIDANCE)
        or f"X-Verba governance did not permit {tool} with these inputs.",
    }
    if patient.get("status") in ("NOT_FOUND", "MULTIPLE_MATCHES"):
        view["patient_status"] = patient["status"]
        view["patient_message"] = patient.get("message")
        view["candidates"] = patient.get("candidates", [])
    return json.dumps(view)


# ============================================================
# Middleware
# ============================================================

class GovernedToolMiddleware(VSLFunctionMiddleware):
    """
    vsl-maf VSLFunctionMiddleware with ledgered, fact-based pre-tool
    governance. The compiled VSL gates run inside governance.gates; on
    DENY the tool body is never executed (call_next is not called) and the
    model receives a structured denial instead of a generic error.
    """

    def __init__(self, tool_name: str, policy: Callable[[dict], tuple[list[Check], dict, dict]]) -> None:
        self._tool_name = tool_name
        self._policy = policy
        super().__init__(
            self._governance_gate,
            candidate_input_fn=self._prepare,
            function_name=tool_name,
        )

    def _prepare(self, context: Any) -> dict:
        args = dict(getattr(context, "arguments", None) or {})
        checks, payload, info = self._policy(args)
        return {"checks": checks, "payload": payload, "info": info, "context": context}

    async def _governance_gate(self, prepared: dict) -> None:
        decision = await governed_tool_call(
            tool=self._tool_name,
            pre_nodes=prepared["checks"],
            monitor_payload=prepared["payload"],
        )
        prepared["decision"] = decision
        if decision.get("decision") != "ALLOW":
            raise AutomationDeniedException(
                reason=f"Pre-tool governance denied {self._tool_name} ({decision.get('pre_node')})",
                identity_key="vsl-maf",
            )

    async def process(self, context: Any, call_next) -> None:
        name = getattr(getattr(context, "function", None), "name", None)
        if name != self._tool_name:
            await call_next()
            return

        prepared = self._prepare(context)
        try:
            await self._governance_gate(prepared)
        except AutomationDeniedException:
            # F1 pre-commitment: the tool body is never reached on denial.
            decision = prepared.get("decision") or {}
            _record_attempt(tool=self._tool_name, decision=decision.get("decision", "DENY"),
                            executed=False, failed=list(prepared["info"].get("failed") or []), error=False,
                            patient=prepared["info"].get("patient"))
            context.result = _denial_view(self._tool_name, decision, prepared["info"])
            return

        attempt = _record_attempt(tool=self._tool_name, decision="ALLOW", executed=True, failed=[], error=False,
                                  patient=prepared["info"].get("patient"))
        try:
            await call_next()
        except Exception:
            attempt["error"] = True
            raise


GOVERNED_TOOL_MIDDLEWARE = [
    GovernedToolMiddleware(tool_name, policy) for tool_name, policy in TOOL_POLICIES.items()
]

# Phase 1/2 name: the create_referral gate.
referral_vsl_middleware = next(m for m in GOVERNED_TOOL_MIDDLEWARE if m._tool_name == REFERRAL_TOOL_NAME)
