import assert from "node:assert/strict";
import { test } from "node:test";

import { buildEvidence, formatTimestamp, isDecisionId } from "./ledger.js";

const terminal = {
  success: true,
  decision_id: "b660ee71-78ac-4bda-9551-0bb681a88790",
  decision: "TERMINAL",
  pre_node: "REFERRAL_REQUEST_VALID",
  invariant: "PATIENT_MUST_EXIST",
  terminal_state: "referral-action-suspended",
  ledger_integrity: true,
  entries: [
    { entry_id: "v", sequence: 3, entry_type: "VERIFICATION", timestamp: 3, caused_by: "p", payload: { result: "INSUFFICIENT" }, entry_hash: "h3", prev_hash: "h2" },
    { entry_id: "m", sequence: 1, entry_type: "MONITOR", timestamp: 1, caused_by: null, payload: { action: "CREATE_REFERRAL" }, entry_hash: "h1", prev_hash: "h0" },
    { entry_id: "t", sequence: 4, entry_type: "TERMINAL", timestamp: 4, caused_by: "v", payload: { terminal_state: "referral-action-suspended" }, entry_hash: "h4", prev_hash: "h3" },
    { entry_id: "p", sequence: 2, entry_type: "PRE_NODE", timestamp: 2, caused_by: "m", payload: { denied: false }, entry_hash: "h2", prev_hash: "h1" },
  ],
};

test("evidence is ordered and caused_by links resolve to returned entries only", () => {
  const evidence = buildEvidence(terminal);
  assert.deepEqual(evidence.entries.map((e) => e.entry_type), ["MONITOR", "PRE_NODE", "VERIFICATION", "TERMINAL"]);
  assert.equal(evidence.entries.length, 4, "no events are added");
  assert.deepEqual(evidence.entries[3].cause, { resolved: true, entryType: "VERIFICATION", sequence: 3 });
  assert.equal(evidence.entries[0].cause, null);
  assert.deepEqual(evidence.causalLinks, { total: 3, unresolved: 0 });
  assert.equal(evidence.action, "CREATE_REFERRAL");
  assert.equal(evidence.origin, null, "Phase 1 decisions have no AI origin");
  assert.equal(evidence.hasHumanAuthorisedTransition, false);
});

test("unresolved caused_by is reported, not invented", () => {
  const evidence = buildEvidence({ ...terminal, entries: terminal.entries.filter((e) => e.entry_id !== "p") });
  assert.equal(evidence.causalLinks.unresolved, 1);
  assert.deepEqual(evidence.entries.find((e) => e.entry_id === "v").cause, { resolved: false });
});

test("malformed evidence is rejected", () => {
  assert.throws(() => buildEvidence({ decision_id: "x" }));
  assert.throws(() => buildEvidence(null));
});

test("decision id validation and timestamp formatting", () => {
  assert.ok(isDecisionId(terminal.decision_id));
  assert.ok(!isDecisionId("not-a-uuid"));
  assert.equal(formatTimestamp(0), "1970-01-01 00:00:00.000 UTC");
  assert.equal(formatTimestamp(undefined), "—");
});

test("AI-originated decisions expose origin and workflow link from the MONITOR payload", () => {
  const entries = terminal.entries.map((e) =>
    e.entry_type === "MONITOR" ? { ...e, payload: { ...e.payload, origin: "AI_PROPOSAL", workflow_id: "wf-1" } } : e,
  );
  const evidence = buildEvidence({ ...terminal, entries });
  assert.equal(evidence.origin, "AI_PROPOSAL");
  assert.equal(evidence.workflowId, "wf-1");
});

test("Phase 3 pre-tool decisions expose the governed tool name", () => {
  const toolCall = {
    ...terminal,
    decision: "DENY",
    pre_node: "CLINICAL_DATA_ACCESS_VALID",
    invariant: null,
    terminal_state: null,
    entries: terminal.entries.map((e) =>
      e.entry_type === "MONITOR" ? { ...e, payload: { action: "TOOL_CALL", tool: "get_patient_medications" } } : e,
    ),
  };
  const evidence = buildEvidence(toolCall);
  assert.equal(evidence.action, "TOOL_CALL");
  assert.equal(evidence.tool, "get_patient_medications");
  assert.equal(buildEvidence(terminal).tool, null);
});
