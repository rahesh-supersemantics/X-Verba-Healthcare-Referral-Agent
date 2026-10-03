"""Phase 2: /clinical-workflows API and the agent review tool."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import agent_tools
from backend.app import app, get_chat_service, get_clinical_workflow
from backend.chat import ChatService
from backend.clinical_workflow import ClinicalReviewWorkflow
from tests.conftest import AISHA_ID, JORDAN_A_ID, referral_count
from tests.test_agent import _agent, _referral_call
from tests.test_clinical_workflow import GROUNDED, FakeAnalyzer


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _use(output=None, raises=None):
    analyzer = FakeAnalyzer(output, raises)
    workflow = ClinicalReviewWorkflow(analyzer=analyzer)
    app.dependency_overrides[get_clinical_workflow] = lambda: workflow
    return workflow, analyzer


def _post(client, **body):
    return client.post("/clinical-workflows", json={"patient_name": "Aisha Wiegand", **body})


# ------------------------------------------------------------------
# POST /clinical-workflows
# ------------------------------------------------------------------

def test_valid_workflow_returns_actual_success(client):
    _use(GROUNDED)

    response = _post(client, department="Cardiology")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["state"] == "COMPLETED"
    assert body["status"] == "REFERRAL_CREATED"
    assert body["governance"]["decision"] == "ALLOW"
    assert body["decision_id"] == body["referral"]["governance_decision_id"]
    assert [t["state"] for t in body["transitions"]][-2:] == ["ACTION_EXECUTED", "COMPLETED"]
    assert referral_count() == 1

    # Retrievable, and the decision's ledger evidence links back to the run.
    run = client.get(f"/clinical-workflows/{body['workflow_id']}").json()
    assert run["status"] == "REFERRAL_CREATED"
    evidence = client.get(f"/governance/{body['decision_id']}").json()
    assert evidence["decision"] == "ALLOW"
    assert evidence["entries"][0]["payload"]["workflow_id"] == body["workflow_id"]
    listed = client.get("/clinical-workflows").json()["workflows"]
    assert listed[0]["workflow_id"] == body["workflow_id"]


@pytest.mark.parametrize(
    "name, output, raises, code, status, state",
    [
        ("Nonexistent Person", GROUNDED, None, 404, "PATIENT_NOT_FOUND", "FAILED"),
        ("Jordan", GROUNDED, None, 409, "MULTIPLE_PATIENT_MATCHES", "FAILED"),
        ("Aisha Wiegand", dict(GROUNDED, evidence=["Congestive heart failure"]), None, 403, "GOVERNANCE_DENIED", "REVIEW_REQUIRED"),
        ("Aisha Wiegand", "not json", None, 502, "INVALID_PROPOSAL", "FAILED"),
        ("Aisha Wiegand", {"action": "NO_ACTION", "recommendation": "Not indicated."}, None, 200, "NO_ACTION_RECOMMENDED", "COMPLETED"),
    ],
)
def test_workflow_outcomes_and_no_write_on_failure(client, name, output, raises, code, status, state):
    _use(output, raises)

    response = client.post("/clinical-workflows", json={"patient_name": name})

    assert response.status_code == code
    body = response.json()
    assert body["status"] == status
    assert body["state"] == state
    assert body["referral"] is None
    assert referral_count() == 0


def test_analysis_unavailable_returns_503(client):
    from backend.analysis import AnalysisUnavailableError

    _use(raises=AnalysisUnavailableError("down"))

    response = _post(client)

    assert response.status_code == 503
    assert response.json()["status"] == "ANALYSIS_UNAVAILABLE"


def test_client_cannot_supply_a_patient_uuid(client):
    _use(GROUNDED)

    response = _post(client, patient_id=JORDAN_A_ID)

    assert response.status_code == 422
    assert referral_count() == 0


def test_idempotent_retry_does_not_execute_twice(client):
    _, analyzer = _use(GROUNDED)

    first = _post(client, idempotency_key="retry-key-0001").json()
    second = _post(client, idempotency_key="retry-key-0001").json()

    assert second["replayed"] is True
    assert second["workflow_id"] == first["workflow_id"]
    assert len(analyzer.calls) == 1
    assert referral_count() == 1


def test_get_workflow_validation(client):
    _use(GROUNDED)

    assert client.get("/clinical-workflows/not-a-uuid").status_code == 422
    assert client.get("/clinical-workflows/11111111-1111-4111-8111-111111111111").status_code == 404


# ------------------------------------------------------------------
# Agent: same workflow service via the review tool
# ------------------------------------------------------------------

def _chat_with(client, monkeypatch, script, output=GROUNDED):
    workflow = ClinicalReviewWorkflow(analyzer=FakeAnalyzer(output))
    monkeypatch.setattr(agent_tools, "get_default_clinical_workflow", lambda: workflow)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(agent_factory=lambda: _agent(script)[0])
    return client.post("/chat", json={"message": "Review Aisha Wiegand for a cardiology referral."})


def _review_call(**arguments):
    return {"name": "review_patient_for_referral", "arguments": arguments}


def test_agent_review_uses_workflow_result_not_llm_claim(client, monkeypatch):
    response = _chat_with(
        client,
        monkeypatch,
        [
            _review_call(patient_name="Aisha Wiegand", department="Cardiology"),
            "I reviewed the patient and did NOT create any referral.",  # model misreport
        ],
    )

    body = response.json()
    assert body["clinical_review_attempted"] is True
    assert body["clinical_reviews"][0]["status"] == "REFERRAL_CREATED"
    assert "was created after governance approval" in body["reply"]
    assert body["agent_reply"] == "I reviewed the patient and did NOT create any referral."
    assert referral_count() == 1


def test_agent_review_then_create_referral_does_not_duplicate(client, monkeypatch):
    response = _chat_with(
        client,
        monkeypatch,
        [
            _review_call(patient_name="Aisha Wiegand", department="Cardiology"),
            _referral_call(patient_name="Aisha Wiegand", department="Cardiology", reason="Hypertension."),
            _review_call(patient_name="Aisha Wiegand", department="Cardiology"),
            "Done.",
        ],
    )

    assert response.status_code == 200
    assert referral_count() == 1
    assert len(response.json()["clinical_reviews"]) == 1


def test_agent_cannot_inject_patient_uuid_into_review(client, monkeypatch):
    _chat_with(
        client,
        monkeypatch,
        [
            _review_call(patient_name="Aisha Wiegand", department="Cardiology", patient_id=JORDAN_A_ID),
            "Done.",
        ],
    )

    from backend.database.connection import SessionLocal
    from backend.database.models import Referral

    with SessionLocal() as session:
        patients = {r.patient_id for r in session.query(Referral).all()}
    # The injected argument is dropped: the review ran for the
    # deterministically resolved patient only.
    assert patients == {AISHA_ID}
    assert JORDAN_A_ID not in patients


def test_review_tool_result_given_to_model_has_no_uuid(monkeypatch):
    import asyncio

    workflow = ClinicalReviewWorkflow(analyzer=FakeAnalyzer(GROUNDED))
    monkeypatch.setattr(agent_tools, "get_default_clinical_workflow", lambda: workflow)

    view = asyncio.run(agent_tools.review_patient_for_referral(patient_name="Aisha Wiegand", department="Cardiology"))

    assert view["status"] == "REFERRAL_CREATED"
    assert AISHA_ID not in json.dumps(view)
