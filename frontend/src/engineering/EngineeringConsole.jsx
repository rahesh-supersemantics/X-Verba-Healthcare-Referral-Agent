import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, Link2, Lock, RefreshCw, Search } from "lucide-react";

import { ApiError, getGovernanceDecision, listGovernanceDecisions } from "../api.js";
import { describeApiError } from "../lib/apiErrors.js";
import { buildEvidence, formatTimestamp, isDecisionId, shortId } from "../lib/ledger.js";
import { DecisionBadge, IntegrityBadge } from "./shared.jsx";
import WorkflowsView from "./WorkflowsView.jsx";
import "./engineering.css";

function readParam(name) {
  const value = new URLSearchParams(window.location.search).get(name);
  return value && isDecisionId(value) ? value.trim().toLowerCase() : "";
}

function setUrl(params) {
  const query = new URLSearchParams(params).toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

async function fetchRecent() {
  try {
    const body = await listGovernanceDecisions(25);
    if (!body || !Array.isArray(body.decisions)) throw new Error("Malformed response");
    return { state: "ready", decisions: body.decisions, integrity: body.ledger_integrity ?? null, error: null };
  } catch (error) {
    return { state: "error", decisions: [], integrity: null, error: describeApiError(error) };
  }
}

async function fetchEvidence(id) {
  try {
    const { status, data } = await getGovernanceDecision(id);
    if (status === 404) {
      return { state: "error", message: "No ledger evidence exists for this decision ID." };
    }
    if (status !== 200) {
      return { state: "error", message: `The backend rejected the request (HTTP ${status}).` };
    }
    return { state: "ready", evidence: buildEvidence(data) };
  } catch (error) {
    return {
      state: "error",
      message: error instanceof ApiError ? describeApiError(error) : "The backend returned malformed evidence.",
    };
  }
}

export default function EngineeringConsole() {
  const [tab, setTab] = useState(() =>
    new URLSearchParams(window.location.search).get("tab") === "workflows" || readParam("workflow")
      ? "workflows"
      : "decisions",
  );
  const [decisionFocus, setDecisionFocus] = useState(() => readParam("decision"));
  const [workflowFocus, setWorkflowFocus] = useState(() => readParam("workflow"));

  function openDecision(id) {
    setDecisionFocus(id);
    setTab("decisions");
    setUrl({ decision: id });
  }

  function openWorkflow(id) {
    setWorkflowFocus(id);
    setTab("workflows");
    setUrl({ tab: "workflows", workflow: id });
  }

  function switchTab(next) {
    setTab(next);
    setUrl(next === "workflows" ? { tab: "workflows" } : {});
  }

  return (
    <div className="eng-shell">
      <header className="eng-header">
        <div>
          <div className="eng-eyebrow">X-Verba · Engineering surface</div>
          <h1>Governance &amp; Review Console</h1>
          <p>Clinical workflow state and VSL ledger evidence for governed actions.</p>
        </div>
        <div className="eng-restricted">
          <Lock size={14} aria-hidden="true" />
          Restricted: for AI engineers and governance reviewers. Authentication is not implemented yet.
        </div>
      </header>

      <nav className="eng-tabs" role="tablist" aria-label="Console sections">
        <button type="button" role="tab" aria-selected={tab === "decisions"} onClick={() => switchTab("decisions")}>
          Governance decisions
        </button>
        <button type="button" role="tab" aria-selected={tab === "workflows"} onClick={() => switchTab("workflows")}>
          Clinical workflows
        </button>
      </nav>

      {tab === "decisions" ? (
        <DecisionsView key={decisionFocus || "none"} initialDecision={decisionFocus} onOpenWorkflow={openWorkflow} />
      ) : (
        <WorkflowsView
          key={workflowFocus || "none"}
          initialWorkflow={workflowFocus}
          onOpenDecision={openDecision}
          onSelect={(id) => setUrl({ tab: "workflows", workflow: id })}
        />
      )}
    </div>
  );
}

function DecisionsView({ initialDecision, onOpenWorkflow }) {
  const [recent, setRecent] = useState({ state: "loading", decisions: [], integrity: null, error: null });
  const [query, setQuery] = useState(initialDecision || "");
  const [detail, setDetail] = useState(() => (initialDecision ? { state: "loading" } : { state: "idle" }));

  const loadRecent = useCallback(async () => {
    setRecent((current) => ({ ...current, state: "loading", error: null }));
    setRecent(await fetchRecent());
  }, []);

  const inspect = useCallback(async (decisionId) => {
    const id = decisionId.trim().toLowerCase();
    if (!isDecisionId(id)) {
      setDetail({ state: "error", message: "Enter a valid decision ID (UUID format)." });
      return;
    }

    setQuery(id);
    setUrl({ decision: id });
    setDetail({ state: "loading" });
    setDetail(await fetchEvidence(id));
  }, []);

  // Initial load: recent decisions, plus a deep-linked decision if present.
  useEffect(() => {
    let cancelled = false;
    const initial = initialDecision;

    fetchRecent().then((next) => {
      if (!cancelled) setRecent(next);
    });
    if (initial) {
      fetchEvidence(initial).then((next) => {
        if (!cancelled) setDetail(next);
      });
    }

    return () => {
      cancelled = true;
    };
  }, [initialDecision]);

  return (
      <main className="eng-main">
        <section className="eng-panel eng-recent">
          <div className="eng-panel-head">
            <h2>Recent decisions</h2>
            <button type="button" className="eng-icon-button" onClick={loadRecent} aria-label="Refresh decisions">
              <RefreshCw size={15} className={recent.state === "loading" ? "eng-spin" : ""} />
            </button>
          </div>

          <div className="eng-recent-integrity">
            Ledger: <IntegrityBadge value={recent.integrity} />
          </div>

          {recent.state === "error" && <div className="eng-error">{recent.error}</div>}
          {recent.state === "ready" && recent.decisions.length === 0 && (
            <p className="eng-muted">No governance decisions have been recorded yet.</p>
          )}

          <ul className="eng-decision-list">
            {recent.decisions.map((item) => (
              <li key={item.decision_id}>
                <button
                  type="button"
                  className={`eng-decision-item ${query === item.decision_id ? "eng-selected" : ""}`}
                  onClick={() => inspect(item.decision_id)}
                >
                  <div className="eng-decision-row">
                    <DecisionBadge decision={item.decision} />
                    <span className="eng-mono">{shortId(item.decision_id)}</span>
                  </div>
                  <div className="eng-decision-meta">
                    {item.action || "—"}
                    {item.tool ? ` · ${item.tool}` : ""}
                    {item.department ? ` · ${item.department}` : ""}
                  </div>
                  <div className="eng-decision-meta">
                    {formatTimestamp(item.recorded_at)} · {item.entry_count} entries
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="eng-panel eng-detail">
          <form
            className="eng-lookup"
            onSubmit={(event) => {
              event.preventDefault();
              inspect(query);
            }}
          >
            <label htmlFor="eng-decision" className="visually-hidden">
              Decision ID
            </label>
            <input
              id="eng-decision"
              className="eng-mono"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Decision ID, e.g. e4266183-f6ea-4fb0-8e34-4685e1d01b6f"
              spellCheck={false}
            />
            <button type="submit">
              <Search size={15} aria-hidden="true" /> Inspect
            </button>
          </form>

          {detail.state === "idle" && (
            <div className="eng-empty">Select a decision or enter a decision ID to inspect its ledger evidence.</div>
          )}
          {detail.state === "loading" && <div className="eng-empty">Loading evidence…</div>}
          {detail.state === "error" && <div className="eng-error">{detail.message}</div>}
          {detail.state === "ready" && <DecisionEvidence evidence={detail.evidence} onOpenWorkflow={onOpenWorkflow} />}
        </section>
      </main>
  );
}

function DecisionEvidence({ evidence, onOpenWorkflow }) {
  const { causalLinks } = evidence;

  return (
    <div className="eng-evidence">
      <div className="eng-summary">
        <div className="eng-summary-head">
          <DecisionBadge decision={evidence.decision} />
          <span className="eng-mono eng-full-id">{evidence.decisionId}</span>
        </div>

        <dl className="eng-facts">
          <Fact label="Action" value={evidence.action} />
          {evidence.tool && <Fact label="Tool" value={evidence.tool} />}
          {evidence.action === "CREATE_REFERRAL" && (
            <Fact label="Origin" value={evidence.origin || "Clinician request"} />
          )}
          <Fact label="PreNode" value={evidence.preNode} />
          <Fact label="Invariant" value={evidence.invariant} />
          <Fact label="Terminal state" value={evidence.terminalState} />
          <div>
            <dt>Ledger integrity</dt>
            <dd>
              <IntegrityBadge value={evidence.ledgerIntegrity} />
            </dd>
          </div>
          <div>
            <dt>Causal links (caused_by)</dt>
            <dd>
              {causalLinks.total === 0
                ? "None"
                : `${causalLinks.total - causalLinks.unresolved}/${causalLinks.total} resolved within this decision`}
            </dd>
          </div>
        </dl>
      </div>

      {evidence.workflowId && (
        <button type="button" className="eng-crosslink" onClick={() => onOpenWorkflow(evidence.workflowId)}>
          <ArrowUpRight size={14} aria-hidden="true" /> Open clinical workflow {shortId(evidence.workflowId)}
        </button>
      )}

      <DecisionExplanation evidence={evidence} />

      <h3 className="eng-section-title">Ledger entries ({evidence.entries.length})</h3>
      <ol className="eng-timeline">
        {evidence.entries.map((entry) => (
          <li key={entry.entry_id} className={`eng-entry eng-entry-${String(entry.entry_type).toLowerCase()}`}>
            <div className="eng-entry-head">
              <span className="eng-seq">#{entry.sequence}</span>
              <strong>{entry.entry_type}</strong>
              <span className="eng-muted">{formatTimestamp(entry.timestamp)}</span>
            </div>

            <dl className="eng-entry-facts">
              <div>
                <dt>entry_id</dt>
                <dd className="eng-mono">{entry.entry_id}</dd>
              </div>
              <div>
                <dt>caused_by</dt>
                <dd className="eng-mono">
                  {entry.cause === null ? (
                    <span className="eng-muted">— (root entry)</span>
                  ) : entry.cause.resolved ? (
                    <span className="eng-link">
                      <Link2 size={13} aria-hidden="true" />#{entry.cause.sequence} {entry.cause.entryType} ·{" "}
                      {shortId(entry.caused_by)}
                    </span>
                  ) : (
                    <span className="eng-warn">{entry.caused_by} (not in this decision)</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>entry_hash</dt>
                <dd className="eng-mono" title={entry.entry_hash}>
                  {shortId(entry.entry_hash, 16)}
                </dd>
              </div>
              <div>
                <dt>prev_hash</dt>
                <dd className="eng-mono" title={entry.prev_hash}>
                  {shortId(entry.prev_hash, 16)}
                </dd>
              </div>
            </dl>

            <pre className="eng-payload">{JSON.stringify(entry.payload ?? {}, null, 2)}</pre>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={value ? "eng-mono" : "eng-muted"}>{value || "—"}</dd>
    </div>
  );
}

const ALLOW_EFFECT = {
  TOOL_CALL:
    "Pre-tool governance (vsl-maf): only after this decision did the tool body run. If the tool performs a side effect, that side effect is governed again by its own action-level decision.",
  CREATE_REFERRAL:
    "Only after this decision did the workflow write the referral; the referral row stores this ID in governance_decision_id.",
  UPDATE_REFERRAL:
    "Only after this decision was the referral updated. The MONITOR entry records the referral number and the before/after values.",
  CANCEL_REFERRAL:
    "Only after this decision was the referral cancelled. The MONITOR entry records the referral number and the cancellation reason.",
  REQUEST_CLINICAL_REVIEW:
    "Only after this decision was the review request stored; it stores this ID in governance_decision_id.",
  DEFAULT: "Only after this decision was the governed action performed.",
};

function DecisionExplanation({ evidence }) {
  if (evidence.decision === "ALLOW") {
    return (
      <div className="eng-note eng-note-allow">
        <strong>ALLOW: {evidence.action === "TOOL_CALL" ? "tool call permitted" : "side effect permitted"}.</strong>{" "}
        Every PreNode passed{evidence.action === "TOOL_CALL" ? "" : " and every invariant held"}; VERIFICATION was
        recorded with outcome <code>approved</code>. {ALLOW_EFFECT[evidence.action] || ALLOW_EFFECT.DEFAULT}
      </div>
    );
  }

  if (evidence.decision === "DENY") {
    return (
      <div className="eng-note eng-note-deny">
        <strong>DENY: PreNode denial.</strong> {evidence.preNode || "The PreNode"} did not reach the Gamma
        threshold{evidence.preNode === "AI_PROPOSAL_GROUNDED" ? " (evidence cited by the AI was not found in the patient record)" : ""}. VERIFICATION is recorded as governance functioning as designed (outcome{" "}
        <code>denied</code>). No side effect was executed.
      </div>
    );
  }

  if (evidence.decision === "TERMINAL") {
    return (
      <div className="eng-note eng-note-terminal">
        <strong>TERMINAL: invariant violation.</strong> {evidence.invariant || "An invariant"} was violated and the
        ledger records terminal state <code>{evidence.terminalState || "—"}</code>. No side effect was executed.
        <div className="eng-review">
          <div className="eng-review-title">Human review status</div>
          <ul>
            <li>
              HUMAN_AUTHORISED_TRANSITION:{" "}
              <strong>{evidence.hasHumanAuthorisedTransition ? "recorded" : "not recorded"}</strong>
            </li>
            <li>
              SPECIFICATION_UPDATE: <strong>{evidence.hasSpecificationUpdate ? "recorded" : "not recorded"}</strong>
            </li>
          </ul>
          <p>
            Current limitation: the backend records the TERMINAL entry but does not persist a suspension state
            or provide a human-authorised transition / re-enablement workflow. Later referrals are still evaluated
            independently, and ledger audit checks 4 and 5 cannot pass for this decision until that workflow exists.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="eng-note">
      The ledger entries for this decision do not contain a recognised ALLOW / DENY / TERMINAL outcome.
    </div>
  );
}
