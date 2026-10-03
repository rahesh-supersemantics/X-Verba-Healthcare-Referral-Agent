"""GET /governance/{decision_id}: ledger evidence for ALLOW / DENY / TERMINAL."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from tests.conftest import NONEXISTENT_ID, REFERRAL_ALLOW_SHAPE


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _referral(client, **payload):
    return client.post("/referrals", json={"department": "Cardiology", "reason": "Chest pain.", **payload}).json()


def test_governance_evidence_for_allow(client):
    decision_id = _referral(client, patient_name="Aisha Wiegand")["decision_id"]

    body = client.get(f"/governance/{decision_id}").json()

    assert body["decision"] == "ALLOW"
    assert body["pre_node"] == "REFERRAL_NOT_DUPLICATE"  # last PreNode evaluated
    assert body["ledger_integrity"] is True
    # Phase 3: one PRE_NODE + VERIFICATION per PreNode.
    assert [e["entry_type"] for e in body["entries"]] == REFERRAL_ALLOW_SHAPE
    assert body["entries"][1]["caused_by"] == body["entries"][0]["entry_id"]
    assert body["entries"][2]["caused_by"] == body["entries"][1]["entry_id"]
    assert body["entries"][-1]["caused_by"] == body["entries"][-2]["entry_id"]


def test_governance_evidence_for_deny(client):
    decision_id = _referral(client, patient_name="Aisha Wiegand", reason="  ")["decision_id"]

    body = client.get(f"/governance/{decision_id}").json()

    assert body["decision"] == "DENY"


def test_governance_evidence_for_terminal(client):
    decision_id = _referral(client, patient_id=NONEXISTENT_ID)["decision_id"]

    body = client.get(f"/governance/{decision_id}").json()

    assert body["decision"] == "TERMINAL"
    assert body["invariant"] == "PATIENT_MUST_EXIST"
    assert body["terminal_state"] == "referral-action-suspended"
    assert body["entries"][-1]["entry_type"] == "TERMINAL"


def test_unknown_and_invalid_decision_ids(client):
    unknown = client.get(f"/governance/{uuid.uuid4()}")
    invalid = client.get("/governance/not-a-uuid")

    assert unknown.status_code == 404
    assert unknown.json()["error"] == "DECISION_NOT_FOUND"
    assert invalid.status_code == 422


def test_recent_decisions_lists_real_ledger_decisions_newest_first(client):
    allowed = _referral(client, patient_name="Aisha Wiegand")["decision_id"]
    terminal = _referral(client, patient_id=NONEXISTENT_ID)["decision_id"]

    body = client.get("/governance", params={"limit": 5}).json()

    assert body["ledger_integrity"] is True
    ids = [d["decision_id"] for d in body["decisions"]]
    assert ids[:2] == [terminal, allowed]
    by_id = {d["decision_id"]: d for d in body["decisions"]}
    assert by_id[allowed]["decision"] == "ALLOW"
    assert by_id[allowed]["action"] == "CREATE_REFERRAL"
    assert by_id[allowed]["entry_count"] == len(REFERRAL_ALLOW_SHAPE)
    assert by_id[terminal]["decision"] == "TERMINAL"
    assert by_id[terminal]["entry_count"] == len(REFERRAL_ALLOW_SHAPE) + 1


def test_recent_decisions_limit_is_validated(client):
    assert client.get("/governance", params={"limit": 0}).status_code == 422
    assert client.get("/governance", params={"limit": 101}).status_code == 422
