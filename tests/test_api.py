"""FastAPI layer: /referrals, /patients, /chat, /health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app, get_chat_service, get_workflow
from backend.chat import ChatResult, LLMUnavailableError
from backend.domain import ReferralOutcome, WorkflowStatus
from backend.workflow import ReferralWorkflow
from tests.conftest import AISHA_ID, AISHA_NAME, NONEXISTENT_ID, referral_count


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ------------------------------------------------------------
# /referrals
# ------------------------------------------------------------

def test_post_referral_success(client):
    response = client.post(
        "/referrals",
        json={"patient_name": "Aisha Wiegand", "department": "Cardiology", "reason": "Chest pain."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "REFERRAL_CREATED"
    assert body["error"] is None
    assert body["patient_id"] == AISHA_ID
    assert body["referral"]["department"] == "Cardiology"
    assert body["governance"]["decision"] == "ALLOW"
    assert body["decision_id"] == body["governance"]["decision_id"]
    assert body["referral"]["governance_decision_id"] == body["decision_id"]
    assert referral_count() == 1


@pytest.mark.parametrize(
    "payload, status_code, error",
    [
        ({"patient_name": "Nonexistent Person", "department": "Cardiology", "reason": "x"}, 404, "PATIENT_NOT_FOUND"),
        ({"patient_name": "Jordan", "department": "Cardiology", "reason": "x"}, 409, "MULTIPLE_PATIENT_MATCHES"),
        ({"patient_id": "not-a-uuid", "department": "Cardiology", "reason": "x"}, 422, "INVALID_PATIENT_ID"),
        ({"patient_name": "Aisha Wiegand", "department": "Cardiology", "reason": "   "}, 403, "GOVERNANCE_DENIED"),
        ({"patient_id": NONEXISTENT_ID, "department": "Cardiology", "reason": "x"}, 403, "GOVERNANCE_TERMINAL"),
        ({"department": "Cardiology", "reason": "x"}, 422, "INVALID_REQUEST"),
    ],
)
def test_post_referral_failures_never_write(client, payload, status_code, error):
    response = client.post("/referrals", json=payload)

    assert response.status_code == status_code
    body = response.json()
    assert body["success"] is False
    assert body["error"] == error
    assert referral_count() == 0


def test_blocked_referral_exposes_governance_decision(client):
    response = client.post(
        "/referrals",
        json={"patient_id": NONEXISTENT_ID, "department": "Cardiology", "reason": "x"},
    )

    body = response.json()
    assert body["governance"]["decision"] == "TERMINAL"
    assert body["governance"]["terminal_state"] == "referral-action-suspended"
    assert body["decision_id"]


def test_multiple_matches_lists_candidates(client):
    body = client.post(
        "/referrals",
        json={"patient_name": "Jordan", "department": "Cardiology", "reason": "x"},
    ).json()

    assert len(body["candidates"]) == 2


def test_referral_request_rejects_unknown_fields(client):
    response = client.post(
        "/referrals",
        json={
            "patient_name": "Aisha Wiegand",
            "department": "Cardiology",
            "reason": "x",
            "status": "APPROVED",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_REQUEST"
    assert referral_count() == 0


def test_internal_error_does_not_leak_details(client):
    async def exploding_governance(_):
        raise RuntimeError("secret connection string sqlite:///C:/secret")

    app.dependency_overrides[get_workflow] = lambda: ReferralWorkflow(governance=exploding_governance)

    response = client.post(
        "/referrals",
        json={"patient_name": "Aisha Wiegand", "department": "Cardiology", "reason": "x"},
    )

    assert response.status_code == 500
    assert response.json()["error"] == "INTERNAL_ERROR"
    assert "secret" not in response.text
    assert referral_count() == 0


# ------------------------------------------------------------
# /patients
# ------------------------------------------------------------

def test_search_patients(client):
    response = client.get("/patients", params={"name": "Aisha Wiegand"})

    assert response.status_code == 200
    body = response.json()
    assert body["match_count"] == 1
    assert body["patients"][0] == {
        "patient_id": AISHA_ID,
        "name": AISHA_NAME,
        "date_of_birth": "1991-10-19",
        "gender": "female",
    }


def test_search_patients_requires_query(client):
    assert client.get("/patients").status_code == 422


def test_get_patient(client):
    response = client.get(f"/patients/{AISHA_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["patient"]["name"] == AISHA_NAME
    assert body["conditions"][0]["condition"] == "Essential hypertension"


def test_get_patient_not_found_and_invalid(client):
    missing = client.get(f"/patients/{NONEXISTENT_ID}")
    invalid = client.get("/patients/not-a-uuid")

    assert missing.status_code == 404
    assert missing.json()["error"] == "PATIENT_NOT_FOUND"
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "INVALID_PATIENT_ID"


# ------------------------------------------------------------
# /chat
# ------------------------------------------------------------

class _StubChat:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises

    async def chat(self, message, conversation_id=None):
        if self._raises:
            raise self._raises
        return self._result


def test_chat_endpoint_returns_workflow_results(client):
    outcome = ReferralOutcome(
        status=WorkflowStatus.PATIENT_NOT_FOUND,
        message="No patient matches 'X'. The referral was not created.",
    )
    app.dependency_overrides[get_chat_service] = lambda: _StubChat(
        ChatResult(reply=outcome.message, agent_reply="...", workflow_results=[outcome])
    )

    response = client.post("/chat", json={"message": "Refer X to cardiology"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["workflow_results"][0]["error"] == "PATIENT_NOT_FOUND"
    assert body["reply"] == outcome.message


def test_chat_endpoint_llm_unavailable(client):
    app.dependency_overrides[get_chat_service] = lambda: _StubChat(raises=LLMUnavailableError("down"))

    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["error"] == "LLM_UNAVAILABLE"


def test_chat_endpoint_rejects_empty_message(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_chat_endpoint_end_to_end_through_agent_framework(client):
    from backend.chat import ChatService
    from tests.test_agent import _agent, _referral_call

    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        agent_factory=lambda: _agent(
            [
                _referral_call(patient_name="Aisha Wiegand", department="Cardiology", reason="Chest pain."),
                "Referral created.",
            ]
        )[0]
    )

    response = client.post("/chat", json={"message": "Refer Aisha Wiegand to cardiology for chest pain."})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["workflow_results"][0]["status"] == "REFERRAL_CREATED"
    assert body["workflow_results"][0]["governance"]["decision"] == "ALLOW"
    assert body["referral_attempted"] is True
    assert referral_count() == 1


def test_generic_chat_does_not_report_a_referral_workflow(client):
    """A greeting must never look like a completed referral workflow."""

    from backend.chat import ChatService
    from tests.test_agent import _agent

    def tool_agent_must_not_be_used():
        raise AssertionError("a greeting must not reach the tool-enabled agent")

    # Greetings are answered by the tool-less conversation agent.
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        agent_factory=tool_agent_must_not_be_used,
        conversation_agent_factory=lambda: _agent(["Hello. How can I help with a referral today?"])[0],
    )

    response = client.post("/chat", json={"message": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["referral_attempted"] is False
    assert body["workflow_results"] == []
    assert body["reply"] == "Hello. How can I help with a referral today?"
    assert referral_count() == 0


# ------------------------------------------------------------
# System
# ------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_openapi_documents_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]

    for path in ["/chat", "/referrals", "/patients", "/patients/{patient_id}", "/governance/{decision_id}"]:
        assert path in paths


def test_no_route_writes_referrals_outside_the_workflow():
    """
    Only workflow-backed routes can mutate state.

    Phase 2 legitimately adds POST /clinical-workflows. It creates referrals
    only through the same ReferralWorkflow -> governed_referral -> actions
    path (see tests/test_clinical_workflow.py, which spies on the writer).
    """

    mutating = {
        route.path
        for route in app.routes
        if getattr(route, "methods", None) and route.methods & {"POST", "PUT", "PATCH", "DELETE"}
    }

    assert mutating == {"/chat", "/referrals", "/clinical-workflows"}
