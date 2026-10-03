"""
Regression tests for:

BUG 1 - general chat ("hey", "hello", "hi") was being routed into the
        referral workflow (the LLM invented a patient such as "John Smith").
BUG 2 - a referral reason showed "Unknown" (the LLM supplied a placeholder
        reason that was accepted and stored verbatim).

Governance itself is not changed; these tests also prove its behaviour
for a genuine request is identical.
"""

from __future__ import annotations

import pytest
from agent_framework import Agent
from fastapi.testclient import TestClient

from backend import agent_tools
from backend.app import app, get_chat_service
from backend.chat import CAPABILITY_REPLY, ChatService, is_small_talk
from backend.clinical_workflow import ClinicalReviewWorkflow
from backend.database.connection import SessionLocal
from backend.database.models import ClinicalWorkflowRun, Referral
from governance.ledger import entries_for_decision, ledger
from tests.conftest import AISHA_ID, REFERRAL_ALLOW_SHAPE, assert_causal_chain, referral_count
from tests.test_agent import ScriptedChatClient, _agent, _referral_call
from tests.test_clinical_workflow import GROUNDED, FakeAnalyzer


def _ledger_size() -> int:
    return sum(1 for _ in ledger.store.all_entries())


def _new_decisions(ledger_before: int) -> list[dict]:
    """Governance decisions recorded after ledger position ``ledger_before``."""

    from governance.ledger import summarize_decision

    grouped: dict[str, list] = {}
    for entry in list(ledger.store.all_entries())[ledger_before:]:
        grouped.setdefault(entry.decision_id, []).append(entry)
    decisions = []
    for entries in grouped.values():
        summary = summarize_decision(entries)
        decisions.append({
            "action": entries[0].payload.get("action"),
            "tool": entries[0].payload.get("tool"),
            "decision": summary["decision"],
            "pre_node": summary["pre_node"],
        })
    return decisions


def _run_count() -> int:
    with SessionLocal() as session:
        return session.query(ClinicalWorkflowRun).count()


class ToolAgentSpy:
    """Tool-enabled agent factory that records whether it was ever used."""

    def __init__(self, script):
        self.script = script
        self.created = 0
        self.client = None

    def __call__(self):
        self.created += 1
        agent, self.client = _agent(self.script)
        return agent


def _conversation_agent(text="Hello! How can I help you today?"):
    client = ScriptedChatClient([text])
    return Agent(client=client, name="Conversation")  # no tools


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# BUG 1: greetings never reach tools, patient resolution or governance
# ------------------------------------------------------------------

@pytest.mark.parametrize("message", ["hey", "hello", "hi", "Hi!", "hey there", "hello, thanks"])
def test_greeting_never_calls_create_referral(client, message):
    # If the tool-enabled agent were used, this script would call
    # create_referral with an invented patient - exactly the bug.
    spy = ToolAgentSpy(
        [_referral_call(patient_name="John Smith", department="Cardiology", reason="Unknown"), "Done."]
    )
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        agent_factory=spy,
        conversation_agent_factory=_conversation_agent,
    )
    ledger_before, runs_before = _ledger_size(), _run_count()

    response = client.post("/chat", json={"message": message})

    assert response.status_code == 200
    body = response.json()
    assert spy.created == 0, "tool-enabled agent must not be used for a greeting"
    assert body["referral_attempted"] is False
    assert body["clinical_review_attempted"] is False
    assert body["workflow_results"] == []
    assert body["clinical_reviews"] == []
    assert body["reply"] == "Hello! How can I help you today?"
    assert referral_count() == 0
    assert _run_count() == runs_before
    assert _ledger_size() == ledger_before, "no VSL governance for small talk"


def test_conversation_agent_in_production_has_no_tools():
    from backend.agent import create_agent, create_conversation_agent

    def tools_of(agent):
        return list((getattr(agent, "default_options", None) or {}).get("tools") or [])

    from backend.agent_tools import AGENT_TOOLS

    assert len(tools_of(create_agent())) == len(AGENT_TOOLS)  # proves the check can see tools
    assert tools_of(create_conversation_agent()) == []


async def test_llm_inventing_a_patient_does_not_run_any_workflow(monkeypatch):
    """Safety net for non-greeting chatter: an invented patient is refused."""

    workflow = ClinicalReviewWorkflow(analyzer=FakeAnalyzer(GROUNDED))
    monkeypatch.setattr(agent_tools, "get_default_clinical_workflow", lambda: workflow)
    script = [
        _referral_call(patient_name="John Smith", department="Cardiology", reason="chest pain"),
        {"name": "review_patient_for_referral", "arguments": {"patient_name": "John Smith", "department": "Cardiology"}},
        {"name": "get_patient_information", "arguments": {"patient_name": "John Smith"}},
        {"name": "search_patient", "arguments": {"name": "John Smith"}},
        "I can help with referrals.",
    ]
    service = ChatService(agent_factory=lambda: _agent(script)[0])
    ledger_before, runs_before = _ledger_size(), _run_count()

    result = await service.chat("what can you help me with today?")

    assert result.workflow_results == []
    assert result.clinical_reviews == []
    # The model's text is not passed through after it attempted governed
    # actions nobody asked for: a fixed reply states nothing was submitted.
    assert result.reply == CAPABILITY_REPLY
    assert referral_count() == 0
    assert _run_count() == runs_before
    # Phase 3: each invented call is a ledgered pre-tool DENY; the tool
    # bodies (and therefore every workflow) never ran.
    decisions = _new_decisions(ledger_before)
    assert [d["tool"] for d in decisions] == [
        "create_referral", "review_patient_for_referral", "get_patient_information", "search_patient",
    ]
    assert all(d["action"] == "TOOL_CALL" and d["decision"] == "DENY" for d in decisions)


def test_ambiguous_patient_mention_is_not_treated_as_small_talk():
    assert not is_small_talk("hi, refer Aisha Wiegand to cardiology for chest pain")
    assert not is_small_talk("what about Aisha?")
    assert is_small_talk("Good morning!")
    assert is_small_talk("thanks, bye")


# ------------------------------------------------------------------
# Genuine referral still uses the unchanged governed path
# ------------------------------------------------------------------

def test_genuine_referral_still_runs_workflow_and_governance(client):
    message = "Create a cardiology referral for Aisha Wiegand because she needs a cardiology assessment"
    spy = ToolAgentSpy(
        [
            _referral_call(
                patient_name="Aisha Wiegand",
                department="Cardiology",
                reason="She needs a cardiology assessment",
            ),
            "Done.",
        ]
    )
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        agent_factory=spy,
        conversation_agent_factory=lambda: (_ for _ in ()).throw(AssertionError("not small talk")),
    )

    body = client.post("/chat", json={"message": message}).json()

    assert spy.created == 1
    assert body["referral_attempted"] is True
    result = body["workflow_results"][0]
    assert result["status"] == "REFERRAL_CREATED"
    assert result["governance"]["decision"] == "ALLOW"
    assert referral_count() == 1

    # Action-level governance evidence (Phase 3: one PRE_NODE + VERIFICATION per PreNode).
    entries = entries_for_decision(result["decision_id"])
    assert [e.entry_type.value for e in entries] == REFERRAL_ALLOW_SHAPE
    assert_causal_chain(entries)

    # BUG 2 regression: the supplied reason survives end to end.
    assert result["referral"]["reason"] == "She needs a cardiology assessment"
    with SessionLocal() as session:
        row = session.get(Referral, result["referral"]["referral_id"])
        assert row.reason == "She needs a cardiology assessment"
        assert row.patient_id == AISHA_ID


def test_search_then_full_name_lookup_is_allowed():
    """A full name returned by search_patient in this turn counts as named."""

    import asyncio

    script = [
        {"name": "search_patient", "arguments": {"name": "Aisha"}},
        {"name": "get_patient_information", "arguments": {"patient_name": "Aisha756 Melina208 Wiegand701"}},
        "Here is the summary.",
    ]
    holder = {}

    def factory():
        agent, holder["client"] = _agent(script)
        return agent

    asyncio.run(ChatService(agent_factory=factory).chat("Find Aisha and show me her details"))

    results = [
        c.result
        for m in holder["client"].requests[-1]
        for c in m.contents
        if c.type == "function_result"
    ]
    assert "NO_PATIENT_NAMED" not in str(results)
    assert "Essential hypertension" in str(results)


# ------------------------------------------------------------------
# BUG 2: placeholder / unstated reasons never become a referral
# ------------------------------------------------------------------

async def test_missing_reason_is_asked_for_instead_of_invented():
    """Phase 3: the conversation layer asks only for the missing reason."""

    spy = ToolAgentSpy([_referral_call(patient_name="Aisha Wiegand", department="Cardiology", reason="Unknown")])
    ledger_before = _ledger_size()

    result = await ChatService(agent_factory=spy).chat("Create a cardiology referral for Aisha Wiegand")

    assert result.reply == "What is the reason for the referral?"
    assert spy.created == 0  # the model never got the chance to invent a reason
    assert result.context["patient"]["name"] == "Aisha756 Melina208 Wiegand701"
    assert result.context["department"] == "Cardiology"
    assert result.context["missing"] == ["reason"]
    assert referral_count() == 0
    assert _ledger_size() == ledger_before


@pytest.mark.parametrize("reason", ["Unknown", "unknown", "None", "N/A", "not specified", "x", "Cardiology referral"])
async def test_placeholder_or_unstated_reason_is_denied_before_the_tool_runs(reason):
    """If the model still invents a reason, pre-tool governance DENIES it (ledgered)."""

    service = ChatService(
        agent_factory=lambda: _agent(
            [_referral_call(patient_name="Aisha Wiegand", department="Cardiology", reason=reason), "What is the reason?"]
        )[0]
    )
    ledger_before = _ledger_size()

    # A question goes to the model (not the deterministic slot filler).
    result = await service.chat("Can you create a cardiology referral for Aisha Wiegand?")

    assert result.workflow_results == []
    # Deterministic reply: never the model's own account of what happened.
    assert result.reply == "No referral or change was made. Please state the reason in your own words."
    assert referral_count() == 0
    [decision] = _new_decisions(ledger_before)
    assert decision == {
        "action": "TOOL_CALL", "tool": "create_referral", "decision": "DENY", "pre_node": "ACTION_INPUT_GROUNDED",
    }


async def test_reason_denial_message_is_given_to_the_model():
    holder = {}

    def factory():
        agent, holder["client"] = _agent(
            [_referral_call(patient_name="Aisha Wiegand", department="Cardiology", reason="Unknown"), "Ok."]
        )
        return agent

    await ChatService(agent_factory=factory).chat("Can you create a cardiology referral for Aisha Wiegand?")

    results = str([
        c.result
        for m in holder["client"].requests[-1]
        for c in m.contents
        if c.type == "function_result"
    ])
    # The model gets actionable guidance, but no internal rule names it
    # could repeat to the clinician.
    assert "never use a placeholder" in results
    assert "ACTION_INPUT_GROUNDED" not in results


def test_direct_referral_api_is_unaffected_by_chat_guards(client):
    """POST /referrals is not LLM-mediated; its behaviour is unchanged."""

    response = client.post(
        "/referrals",
        json={"patient_name": "Aisha Wiegand", "department": "Cardiology", "reason": "Chest pain on exertion"},
    )

    assert response.status_code == 201
    assert response.json()["referral"]["reason"] == "Chest pain on exertion"
