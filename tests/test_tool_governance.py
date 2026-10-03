"""
Phase 3: pre-tool governance (vsl-maf GovernedToolMiddleware) and tool
selection. The model's tool proposals are governed BEFORE the tool body
runs; DENY means the body never executes and the decision is ledgered.
"""

from __future__ import annotations

import json

from backend import agent_tools
from backend.agent_tools import AGENT_TOOLS
from backend.chat import ChatService
from governance.ledger import entries_for_decision, ledger, recent_decisions
from governance.maf_gates import GOVERNED_TOOL_MIDDLEWARE, TOOL_POLICIES
from tests.conftest import AISHA_ID, referral_count
from tests.test_agent import _agent
from tests.test_chat_intent import _new_decisions, _ledger_size


def _call(tool, /, **arguments):
    return {"name": tool, "arguments": arguments}


def _tool_results(client):
    return [c.result for m in client.requests[-1] for c in m.contents if c.type == "function_result"]


async def _chat(script, message):
    holder = {}

    def factory():
        agent, holder["client"] = _agent(script)
        return agent

    before = _ledger_size()
    result = await ChatService(agent_factory=factory).chat(message)
    return result, holder["client"], _new_decisions(before)


# ------------------------------------------------------------------
# Every tool is governed
# ------------------------------------------------------------------

def test_every_agent_tool_has_a_pre_tool_gate():
    tool_names = {t.name for t in AGENT_TOOLS}
    assert tool_names == set(TOOL_POLICIES)
    assert {m._tool_name for m in GOVERNED_TOOL_MIDDLEWARE} == tool_names
    assert {
        "get_patient_conditions", "get_patient_medications", "get_patient_allergies",
        "get_patient_observations", "get_patient_encounters", "update_referral",
        "cancel_referral", "request_clinical_review",
    } <= tool_names


# ------------------------------------------------------------------
# 1. Valid tool call -> ALLOW -> tool executes
# ------------------------------------------------------------------

async def test_valid_tool_call_is_allowed_and_executes():
    result, client, decisions = await _chat(
        [_call("get_patient_medications", patient_name="Aisha Wiegand"), "She takes lisinopril."],
        "What medications is Aisha Wiegand taking?",
    )

    [output] = _tool_results(client)
    assert "lisinopril 10 MG Oral Tablet" in str(output)
    assert AISHA_ID not in str(output)
    assert decisions == [
        {"action": "TOOL_CALL", "tool": "get_patient_medications", "decision": "ALLOW",
         "pre_node": "CLINICAL_DATA_ACCESS_VALID"}
    ]
    # The pre-tool MONITOR records which patient's data was accessed.
    decision_id = recent_decisions(1)[0]["decision_id"]
    assert entries_for_decision(decision_id)[0].payload["patient_id"] == AISHA_ID


# ------------------------------------------------------------------
# 2. Invalid tool call -> DENY -> tool does not execute
# ------------------------------------------------------------------

async def test_denied_tool_call_never_executes_the_tool_body(monkeypatch):
    executed = []
    original = agent_tools.get_patient

    def spy(session, patient_id):
        executed.append(patient_id)
        return original(session, patient_id)

    monkeypatch.setattr(agent_tools, "get_patient", spy)

    _, client, decisions = await _chat(
        [_call("get_patient_medications", patient_name="John Smith"), "Who do you mean?"],
        "what medications are on the formulary?",
    )

    assert executed == []
    [output] = _tool_results(client)
    view = json.loads(output)
    assert view["tool_executed"] is False
    assert "check" not in view  # rule names stay in the ledger, not the model view
    assert decisions[0]["pre_node"] == "CLINICAL_DATA_ACCESS_VALID"
    assert decisions[0]["decision"] == "DENY"


async def test_ambiguous_patient_is_denied_with_candidates_for_clarification():
    _, client, decisions = await _chat(
        [_call("get_patient_conditions", patient_name="Jordan"), "Which Jordan?"],
        "What conditions does Jordan have?",
    )

    view = json.loads(_tool_results(client)[0])
    assert view["patient_status"] == "MULTIPLE_MATCHES"
    assert len(view["candidates"]) == 2
    assert "11111111" not in json.dumps(view)  # names and DOB only
    assert decisions[0]["decision"] == "DENY"


async def test_search_with_an_invented_name_is_denied():
    _, client, decisions = await _chat(
        [_call("search_patient", name="Smith"), "Who are you looking for?"],
        "find me a patient please",
    )

    assert json.loads(_tool_results(client)[0])["tool_executed"] is False
    assert decisions[0]["pre_node"] == "PATIENT_SEARCH_REQUEST_VALID"


async def test_referral_number_must_come_from_the_staff_member():
    _, client, decisions = await _chat(
        [_call("cancel_referral", referral_number=7, patient_name="Aisha Wiegand",
               cancellation_reason="no longer needed"), "Which referral?"],
        "Cancel Aisha Wiegand's referral, it is no longer needed",
    )

    view = json.loads(_tool_results(client)[0])
    assert decisions[0]["pre_node"] == "ACTION_INPUT_GROUNDED"
    assert "referral number" in view["message"]
    assert decisions[0]["decision"] == "DENY"


# ------------------------------------------------------------------
# Tool selection: only what the request needs, results grounded
# ------------------------------------------------------------------

async def test_review_tool_sequence_uses_only_requested_tools():
    import backend.agent_tools as tools
    from backend.clinical_workflow import ClinicalReviewWorkflow
    from tests.test_clinical_workflow import GROUNDED, FakeAnalyzer

    workflow = ClinicalReviewWorkflow(analyzer=FakeAnalyzer(GROUNDED))
    tools_before = tools.get_default_clinical_workflow
    tools.get_default_clinical_workflow = lambda: workflow
    try:
        result, client, decisions = await _chat(
            [
                _call("search_patient", name="Aisha"),
                _call("get_patient_conditions", patient_name="Aisha756 Melina208 Wiegand701"),
                _call("review_patient_for_referral", patient_name="she", department="Cardiology"),
                "Reviewed.",
            ],
            "Review Aisha and tell me whether a cardiology referral makes sense.",
        )
    finally:
        tools.get_default_clinical_workflow = tools_before

    assert [d["tool"] for d in decisions if d["action"] == "TOOL_CALL"] == [
        "search_patient", "get_patient_conditions", "review_patient_for_referral",
    ]
    assert all(d["decision"] == "ALLOW" for d in decisions if d["action"] == "TOOL_CALL")
    assert result.clinical_reviews[0].status == "REFERRAL_CREATED"
    # The AI-originated referral was governed again at action level.
    assert any(d["action"] == "CREATE_REFERRAL" and d["decision"] == "ALLOW" for d in decisions)
    assert referral_count() == 1


async def test_focused_tools_return_only_their_category():
    _, client, _ = await _chat(
        [_call("get_patient_allergies", patient_name="Aisha Wiegand"), "No allergies."],
        "Does Aisha Wiegand have any allergies?",
    )

    view = _tool_results(client)[0]
    assert "allergies" in str(view)
    assert "lisinopril" not in str(view)
    assert "Essential hypertension" not in str(view)


def test_ledger_audit_check_3_holds_for_pre_tool_decisions():
    assert "pre_node_has_verification" not in ledger.audit().checks_failed
    assert ledger.verify_integrity() is True
