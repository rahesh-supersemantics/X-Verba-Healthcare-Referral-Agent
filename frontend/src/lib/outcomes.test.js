// Run with: npm test   (Node's built-in test runner, no extra dependencies)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MalformedResponseError,
  classifyFailure,
  interpretChatResponse,
  presentActionResult,
  presentClinicalReview,
  presentConversationContext,
  presentWorkflowResult,
} from "./outcomes.js";

const AISHA_ID = "8f998bfd-bcee-9bc0-e435-7c50e571a851";
const DECISION_ID = "e4266183-f6ea-4fb0-8e34-4685e1d01b6f";

const created = {
  success: true,
  status: "REFERRAL_CREATED",
  error: null,
  message: "Referral 5 to Cardiology was created after X-Verba governance returned ALLOW.",
  patient_id: AISHA_ID,
  patient: { patient_id: AISHA_ID, name: "Aisha756 Melina208 Wiegand701", date_of_birth: "1991-10-19", gender: "female" },
  referral: {
    referral_id: 5,
    patient_id: AISHA_ID,
    department: "Cardiology",
    reason: "Needs cardiology assessment.",
    status: "PENDING",
    created_at: "2026-09-27T22:59:58.632497",
    governance_decision_id: DECISION_ID,
  },
  governance: { decision: "ALLOW", decision_id: DECISION_ID, reason: "All referral governance checks passed." },
  decision_id: DECISION_ID,
  candidates: [],
};

function chat(results, extra = {}) {
  return { success: true, reply: "x", agent_reply: "x", referral_attempted: results.length > 0, workflow_results: results, ...extra };
}

test("successful referral is presented as success with business details only", () => {
  const view = interpretChatResponse(chat([created]));
  assert.equal(view.kind, "referral");
  const [outcome] = view.outcomes;
  assert.equal(outcome.success, true);
  assert.equal(outcome.message, "Referral created successfully.");
  assert.equal(outcome.referral.reference, 5);
  assert.deepEqual(outcome.stages.map((s) => s.state), ["done", "done", "done", "done"]);

  const serialized = JSON.stringify(outcome);
  assert.ok(!serialized.includes(AISHA_ID), "patient UUID must not reach the clinician view");
  assert.ok(!serialized.includes(DECISION_ID), "decision ID must not reach the clinician view");
  assert.ok(!/VSL|PreNode|Invariant|ALLOW/.test(serialized), "no governance internals");
});

test("generic chat is never presented as a referral workflow", () => {
  const view = interpretChatResponse(chat([], { reply: "Hello. How can I help?" }));
  // Phase 3 adds the (empty) conversation fields; still no workflow outcome.
  assert.deepEqual(view, { kind: "message", text: "Hello. How can I help?", conversationId: null, context: null });
});

test("HTTP-level success with a failed workflow is presented as failure", () => {
  const notFound = { success: false, status: "PATIENT_NOT_FOUND", error: "PATIENT_NOT_FOUND", message: "No patient matches 'Zeb'.", candidates: [] };
  const [outcome] = interpretChatResponse(chat([notFound])).outcomes;
  assert.equal(outcome.success, false);
  assert.equal(outcome.title, "Patient not found");
  assert.deepEqual(outcome.stages.map((s) => s.state), ["done", "failed", "skipped", "skipped"]);
});

test("multiple matches list names and dates of birth, not UUIDs", () => {
  const multiple = {
    success: false,
    status: "MULTIPLE_PATIENT_MATCHES",
    candidates: [
      { patient_id: "11111111-2222-3333-4444-555555555555", name: "Jordan101 Smith202", date_of_birth: "1980-01-01" },
      { patient_id: "66666666-7777-8888-9999-000000000000", name: "Jordan303 Smithers404", date_of_birth: "1975-05-05" },
    ],
  };
  const outcome = presentWorkflowResult(multiple);
  assert.match(outcome.message, /could not be uniquely identified/);
  assert.deepEqual(outcome.candidates, [
    { name: "Jordan101 Smith202", dateOfBirth: "1980-01-01" },
    { name: "Jordan303 Smithers404", dateOfBirth: "1975-05-05" },
  ]);
  assert.ok(!JSON.stringify(outcome).includes("11111111-2222"));
});

test("governance DENY and TERMINAL are presented as blocked", () => {
  for (const status of ["GOVERNANCE_DENIED", "GOVERNANCE_TERMINAL"]) {
    const outcome = presentWorkflowResult({
      success: false,
      status,
      governance: { decision: status === "GOVERNANCE_DENIED" ? "DENY" : "TERMINAL", decision_id: DECISION_ID, terminal_state: "referral-action-suspended" },
    });
    assert.equal(outcome.tone, "blocked");
    assert.match(outcome.message, /blocked by the governance workflow/);
    assert.equal(outcome.stages[2].state, "blocked");
    assert.ok(!JSON.stringify(outcome).includes("referral-action-suspended"));
  }
});

test("a created status without a referral record is not trusted as success", () => {
  const outcome = presentWorkflowResult({ ...created, referral: null });
  assert.equal(outcome.success, false);
  assert.equal(outcome.status, "UNKNOWN");
  assert.match(outcome.message, /Do not assume a referral was created/);
});

test("unknown status codes fail safe", () => {
  const outcome = presentWorkflowResult({ success: true, status: "SOMETHING_NEW" });
  assert.equal(outcome.success, false);
  assert.equal(outcome.status, "UNKNOWN");
});

test("internal error after ALLOW shows the record step as failed", () => {
  const outcome = presentWorkflowResult({ success: false, status: "INTERNAL_ERROR", governance: { decision: "ALLOW" } });
  assert.deepEqual(outcome.stages.map((s) => s.state), ["done", "done", "done", "failed"]);
});

test("malformed chat responses are rejected", () => {
  assert.throws(() => interpretChatResponse(null), MalformedResponseError);
  assert.throws(() => interpretChatResponse({ reply: "x" }), MalformedResponseError);
  assert.throws(() => interpretChatResponse({ workflow_results: [] }), MalformedResponseError);
  assert.throws(
    () => interpretChatResponse({ reply: "x", referral_attempted: true, workflow_results: [] }),
    MalformedResponseError,
  );
});

test("transport failures are classified", () => {
  assert.equal(classifyFailure({ network: true }), "API_UNAVAILABLE");
  assert.equal(classifyFailure({ timeout: true }), "TIMEOUT");
  assert.equal(classifyFailure({ status: 503, errorCode: "LLM_UNAVAILABLE" }), "LLM_UNAVAILABLE");
  assert.equal(classifyFailure({ status: 422 }), "INVALID_REQUEST");
  assert.equal(classifyFailure({ status: 500 }), "INTERNAL_ERROR");
  assert.equal(classifyFailure({ status: 418 }), "UNEXPECTED");
});

// ------------------------------------------------------------------
// Phase 2: clinical reviews
// ------------------------------------------------------------------

const t = (...states) => states.map((state) => ({ state, at: "2026-09-29T00:00:00Z", note: null }));

const review = {
  workflow_id: "0d6a1f2e-1111-4222-8333-444455556666",
  success: true,
  state: "COMPLETED",
  status: "REFERRAL_CREATED",
  message: "Referral 9 to Cardiology was created after governance approval.",
  transitions: t("REQUESTED", "PATIENT_RESOLVED", "DATA_RETRIEVED", "ANALYSIS_COMPLETED", "ACTION_PROPOSED", "GOVERNANCE_CHECK", "ACTION_EXECUTED", "COMPLETED"),
  patient: { patient_id: AISHA_ID, name: "Aisha756 Melina208 Wiegand701", date_of_birth: "1991-10-19" },
  proposal: { action: "CREATE_REFERRAL", department: "Cardiology", recommendation: "Cardiology review is reasonable.", reason: "Hypertension", evidence: ["Essential hypertension"] },
  ignored_ai_fields: ["patient_id"],
  raw_ai_output: `{"patient_id": "${AISHA_ID}"}`,
  governance: { decision: "ALLOW", decision_id: DECISION_ID, pre_node: "AI_PROPOSAL_GROUNDED" },
  referral: { referral_id: 9, patient_id: AISHA_ID, department: "Cardiology", reason: "Hypertension", status: "PENDING", created_at: "2026-09-29T00:00:00", governance_decision_id: DECISION_ID },
  candidates: [],
};

test("clinical review success shows recommendation and referral, no internals", () => {
  const view = presentClinicalReview(review);
  assert.equal(view.success, true);
  assert.equal(view.title, "Referral created");
  assert.equal(view.recommendation, "Cardiology review is reasonable.");
  assert.equal(view.referral.reference, 9);
  assert.deepEqual(view.stages.map((s) => s.state), ["done", "done", "done", "done", "done", "done"]);
  const serialized = JSON.stringify(view);
  for (const secret of [AISHA_ID, DECISION_ID, "AI_PROPOSAL_GROUNDED", "patient_id", "ALLOW"]) {
    assert.ok(!serialized.includes(secret), `clinician view leaked ${secret}`);
  }
});

test("clinical review no-action is not presented as a created referral", () => {
  const view = presentClinicalReview({
    ...review,
    status: "NO_ACTION_RECOMMENDED",
    proposal: { action: "NO_ACTION", recommendation: "I have created the referral." },
    governance: null,
    referral: null,
    transitions: t("REQUESTED", "PATIENT_RESOLVED", "DATA_RETRIEVED", "ANALYSIS_COMPLETED", "ACTION_PROPOSED", "COMPLETED"),
  });
  assert.equal(view.title, "No referral recommended");
  assert.equal(view.referral, null);
  assert.deepEqual(view.stages.map((s) => s.state), ["done", "done", "done", "done", "notneeded", "notneeded"]);
});

test("clinical review governance denial needs human review", () => {
  const view = presentClinicalReview({
    ...review,
    success: false,
    state: "REVIEW_REQUIRED",
    status: "GOVERNANCE_DENIED",
    governance: { decision: "DENY", decision_id: DECISION_ID },
    referral: null,
    transitions: t("REQUESTED", "PATIENT_RESOLVED", "DATA_RETRIEVED", "ANALYSIS_COMPLETED", "ACTION_PROPOSED", "GOVERNANCE_CHECK", "REVIEW_REQUIRED"),
  });
  assert.equal(view.tone, "blocked");
  assert.match(view.message, /blocked by the governance workflow/);
  assert.deepEqual(view.stages.map((s) => s.state), ["done", "done", "done", "done", "blocked", "skipped"]);
});

test("invalid AI proposal fails at the proposal stage", () => {
  const view = presentClinicalReview({
    ...review,
    success: false,
    state: "FAILED",
    status: "INVALID_PROPOSAL",
    proposal: null,
    governance: null,
    referral: null,
    transitions: t("REQUESTED", "PATIENT_RESOLVED", "DATA_RETRIEVED", "ANALYSIS_COMPLETED", "FAILED"),
  });
  assert.equal(view.success, false);
  assert.match(view.message, /no referral was created/);
  assert.deepEqual(view.stages.map((s) => s.state), ["done", "done", "done", "failed", "skipped", "skipped"]);
});

test("created review status without a referral record is not trusted", () => {
  const view = presentClinicalReview({ ...review, referral: null });
  assert.equal(view.success, false);
  assert.equal(view.status, "UNKNOWN");
});

test("chat response carrying clinical reviews", () => {
  const body = { success: true, reply: "x", referral_attempted: false, workflow_results: [], clinical_review_attempted: true, clinical_reviews: [review] };
  const view = interpretChatResponse(body);
  assert.equal(view.kind, "referral");
  assert.equal(view.reviews.length, 1);
  assert.equal(view.outcomes.length, 0);
  assert.throws(() => interpretChatResponse({ ...body, clinical_reviews: [] }), MalformedResponseError);
});

test("BUG 2 regression: the supplied referral reason reaches the result card unchanged", () => {
  const reason = "She needs a cardiology assessment";
  const [outcome] = interpretChatResponse(
    chat([{ ...created, referral: { ...created.referral, reason } }]),
  ).outcomes;
  assert.equal(outcome.referral.reason, reason);

  const review = presentClinicalReview({
    workflow_id: "w",
    success: true,
    state: "COMPLETED",
    status: "REFERRAL_CREATED",
    transitions: [],
    proposal: { action: "CREATE_REFERRAL", recommendation: "r", department: "Cardiology", reason },
    referral: { ...created.referral, reason },
  });
  assert.equal(review.referral.reason, reason);
});

// ------------------------------------------------------------------
// Phase 3
// ------------------------------------------------------------------

const denied = (pre_node) => ({
  ...created,
  success: false,
  status: "GOVERNANCE_DENIED",
  error: "GOVERNANCE_DENIED",
  referral: null,
  governance: { decision: "DENY", decision_id: DECISION_ID, reason: "x", pre_node },
});

test("duplicate referral denial has duplicate-specific wording without rule names", () => {
  const view = presentWorkflowResult(denied("REFERRAL_NOT_DUPLICATE"));
  assert.equal(view.title, "Duplicate referral blocked");
  assert.equal(view.success, false);
  assert.equal(view.referral, null);
  assert.ok(!JSON.stringify(view).includes("REFERRAL_NOT_DUPLICATE"));
  assert.ok(!JSON.stringify(view).includes(DECISION_ID));
});

test("unsupported department denial is explained; other denials keep the generic text", () => {
  assert.equal(presentWorkflowResult(denied("REFERRAL_TARGET_VALID")).title, "Department not supported");
  assert.equal(presentWorkflowResult(denied("REFERRAL_REQUEST_VALID")).title, "Referral blocked");
});

const cancelled = {
  action: "CANCEL_REFERRAL",
  success: true,
  status: "REFERRAL_CANCELLED",
  error: null,
  message: "Referral 5 was cancelled.",
  patient_id: AISHA_ID,
  patient: created.patient,
  referral: { ...created.referral, status: "CANCELLED" },
  review_request: null,
  governance: created.governance,
  decision_id: DECISION_ID,
  candidates: [],
};

test("governed action results are presented without identifiers", () => {
  const view = presentActionResult(cancelled);
  assert.equal(view.title, "Referral cancelled");
  assert.equal(view.success, true);
  assert.equal(view.referral.status, "CANCELLED");
  assert.ok(!JSON.stringify(view).includes(AISHA_ID));
  assert.ok(!JSON.stringify(view).includes(DECISION_ID));
});

test("an action success status without its record is not trusted", () => {
  const view = presentActionResult({ ...cancelled, referral: null });
  assert.equal(view.success, false);
  assert.equal(view.status, "UNKNOWN");

  const review = presentActionResult({
    ...cancelled,
    action: "REQUEST_CLINICAL_REVIEW",
    status: "CLINICAL_REVIEW_REQUESTED",
    referral: null,
    review_request: { review_request_id: 3, patient_id: AISHA_ID, department: null, reason: "Uncertain", status: "OPEN" },
  });
  assert.equal(review.success, true);
  assert.equal(review.reviewRequest.reference, 3);
  assert.ok(!JSON.stringify(review).includes(AISHA_ID));
});

test("blocked actions are presented as blocked, never as success", () => {
  const view = presentActionResult({ ...cancelled, success: false, status: "GOVERNANCE_DENIED", referral: null });
  assert.equal(view.tone, "blocked");
  assert.equal(view.success, false);
});

test("chat responses carry action results and the conversation id", () => {
  const body = chat([], { action_attempted: true, action_results: [cancelled], conversation_id: "c-1" });
  const view = interpretChatResponse(body);
  assert.equal(view.kind, "referral");
  assert.equal(view.outcomes[0].title, "Referral cancelled");
  assert.equal(view.conversationId, "c-1");
  assert.throws(() => interpretChatResponse({ ...body, action_results: [] }), MalformedResponseError);
});

test("conversation context shows what is known and what is missing, no identifiers", () => {
  const context = presentConversationContext({
    intent: "REFERRAL",
    stage: "COLLECTING",
    patient: { name: "Aisha756 Melina208 Wiegand701", date_of_birth: "1991-10-19" },
    department: "Cardiology",
    reason: null,
    missing: ["reason"],
    awaiting: "reason",
    last_referral_id: null,
  });
  assert.equal(context.patient.name, "Aisha756 Melina208 Wiegand701");
  assert.equal(context.department, "Cardiology");
  assert.deepEqual(context.missing, ["Reason for referral"]);
  assert.equal(context.stage, "Collecting details");

  assert.equal(presentConversationContext({ intent: null, stage: "IDLE", patient: null, missing: [] }), null);
  assert.equal(presentConversationContext(undefined), null);

  const view = interpretChatResponse(chat([], { conversation_id: "c-2", context: { intent: null, stage: "IDLE", patient: null, missing: [] } }));
  assert.equal(view.kind, "message");
  assert.equal(view.conversationId, "c-2");
  assert.equal(view.context, null);
});

test("action results carry their own progress stages", () => {
  const done = presentActionResult(cancelled);
  assert.deepEqual(done.stages.map((s) => s.state), ["done", "done", "done", "done"]);
  assert.equal(done.stages[3].label, "Change recorded");

  const blocked = presentActionResult({ ...cancelled, success: false, status: "GOVERNANCE_DENIED", referral: null });
  assert.deepEqual(blocked.stages.map((s) => s.state), ["done", "done", "blocked", "skipped"]);
});
