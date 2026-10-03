import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, RefreshCw, Search } from "lucide-react";

import { ApiError, getClinicalWorkflow, listClinicalWorkflows } from "../api.js";
import { describeApiError } from "../lib/apiErrors.js";
import { isDecisionId, shortId } from "../lib/ledger.js";
import { DecisionBadge } from "./shared.jsx";

const STATE_TONE = {
  COMPLETED: "allow",
  REVIEW_REQUIRED: "deny",
  TERMINAL: "terminal",
  FAILED: "terminal",
};

function StateBadge({ state }) {
  return <span className={`eng-badge eng-badge-${STATE_TONE[state] || "unknown"}`}>{state || "UNKNOWN"}</span>;
}

function formatIso(value) {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toISOString().replace("T", " ").replace("Z", " UTC");
}

async function fetchRuns() {
  try {
    const body = await listClinicalWorkflows(25);
    if (!body || !Array.isArray(body.workflows)) throw new Error("Malformed response");
    return { state: "ready", runs: body.workflows, error: null };
  } catch (error) {
    return { state: "error", runs: [], error: describeApiError(error) };
  }
}

async function fetchRun(id) {
  try {
    const { status, data } = await getClinicalWorkflow(id);
    if (status === 404) return { state: "error", message: "No clinical workflow run exists with this ID." };
    if (status !== 200) return { state: "error", message: `The backend rejected the request (HTTP ${status}).` };
    if (!data || typeof data.workflow_id !== "string" || !Array.isArray(data.transitions)) {
      return { state: "error", message: "The backend returned a malformed workflow run." };
    }
    return { state: "ready", run: data };
  } catch (error) {
    return {
      state: "error",
      message: error instanceof ApiError ? describeApiError(error) : "The backend returned a malformed workflow run.",
    };
  }
}

export default function WorkflowsView({ initialWorkflow, onOpenDecision, onSelect }) {
  const [list, setList] = useState({ state: "loading", runs: [], error: null });
  const [query, setQuery] = useState(initialWorkflow || "");
  const [detail, setDetail] = useState(() => (initialWorkflow ? { state: "loading" } : { state: "idle" }));

  const reload = useCallback(async () => {
    setList((current) => ({ ...current, state: "loading" }));
    setList(await fetchRuns());
  }, []);

  const inspect = useCallback(
    async (workflowId) => {
      const id = workflowId.trim().toLowerCase();
      if (!isDecisionId(id)) {
        setDetail({ state: "error", message: "Enter a valid workflow ID (UUID format)." });
        return;
      }
      setQuery(id);
      onSelect(id);
      setDetail({ state: "loading" });
      setDetail(await fetchRun(id));
    },
    [onSelect],
  );

  useEffect(() => {
    let cancelled = false;
    fetchRuns().then((next) => {
      if (!cancelled) setList(next);
    });
    if (initialWorkflow) {
      fetchRun(initialWorkflow).then((next) => {
        if (!cancelled) setDetail(next);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [initialWorkflow]);

  return (
    <main className="eng-main">
      <section className="eng-panel eng-recent">
        <div className="eng-panel-head">
          <h2>Recent clinical workflows</h2>
          <button type="button" className="eng-icon-button" onClick={reload} aria-label="Refresh workflows">
            <RefreshCw size={15} className={list.state === "loading" ? "eng-spin" : ""} />
          </button>
        </div>

        {list.state === "error" && <div className="eng-error">{list.error}</div>}
        {list.state === "ready" && list.runs.length === 0 && (
          <p className="eng-muted">No clinical workflows have been run yet.</p>
        )}

        <ul className="eng-decision-list eng-workflow-list">
          {list.runs.map((run) => (
            <li key={run.workflow_id}>
              <button
                type="button"
                className={`eng-decision-item ${query === run.workflow_id ? "eng-selected" : ""}`}
                onClick={() => inspect(run.workflow_id)}
              >
                <div className="eng-decision-row">
                  <StateBadge state={run.state} />
                  <span className="eng-mono">{shortId(run.workflow_id)}</span>
                </div>
                <div className="eng-decision-meta">
                  {run.status || "—"} · {run.patient_name}
                  {run.department ? ` · ${run.department}` : ""}
                </div>
                <div className="eng-decision-meta">{formatIso(run.created_at)}</div>
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
          <label htmlFor="eng-workflow" className="visually-hidden">
            Workflow ID
          </label>
          <input
            id="eng-workflow"
            className="eng-mono"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Workflow ID"
            spellCheck={false}
          />
          <button type="submit">
            <Search size={15} aria-hidden="true" /> Inspect
          </button>
        </form>

        {detail.state === "idle" && (
          <div className="eng-empty">Select a clinical workflow run to inspect its state and action proposal.</div>
        )}
        {detail.state === "loading" && <div className="eng-empty">Loading workflow…</div>}
        {detail.state === "error" && <div className="eng-error">{detail.message}</div>}
        {detail.state === "ready" && <WorkflowDetail run={detail.run} onOpenDecision={onOpenDecision} />}
      </section>
    </main>
  );
}

function WorkflowDetail({ run, onOpenDecision }) {
  const governance = run.governance;

  return (
    <div className="eng-evidence">
      <div className="eng-summary">
        <div className="eng-summary-head">
          <StateBadge state={run.state} />
          <span className="eng-mono eng-full-id">{run.workflow_id}</span>
        </div>
        <dl className="eng-facts">
          <div>
            <dt>Workflow status</dt>
            <dd className="eng-mono">{run.status || "—"}</dd>
          </div>
          <div>
            <dt>Requested patient</dt>
            <dd>{run.request?.patient_name || "—"}</dd>
          </div>
          <div>
            <dt>Requested department</dt>
            <dd>{run.request?.department || "—"}</dd>
          </div>
          <div>
            <dt>Resolved patient</dt>
            <dd>
              {run.patient ? (
                <>
                  {run.patient.name}
                  <div className="eng-mono eng-muted">{run.patient.patient_id}</div>
                </>
              ) : (
                <span className="eng-muted">Not resolved</span>
              )}
            </dd>
          </div>
          <div>
            <dt>Governance decision</dt>
            <dd>
              {governance ? <DecisionBadge decision={governance.decision} /> : <span className="eng-muted">Not reached</span>}
            </dd>
          </div>
          <div>
            <dt>Referral</dt>
            <dd>{run.referral ? `#${run.referral.referral_id} · ${run.referral.department}` : <span className="eng-muted">None created</span>}</dd>
          </div>
        </dl>
        <p className="eng-run-message">{run.message}</p>
        {governance?.decision_id && (
          <button type="button" className="eng-crosslink" onClick={() => onOpenDecision(governance.decision_id)}>
            <ArrowUpRight size={14} aria-hidden="true" /> Open governance evidence {shortId(governance.decision_id)}
          </button>
        )}
        {run.replayed && <p className="eng-muted">This response was an idempotent replay of an earlier run.</p>}
      </div>

      <h3 className="eng-section-title">Workflow state transitions (business process)</h3>
      <ol className="eng-states">
        {run.transitions.map((transition, index) => (
          <li key={`${transition.state}-${index}`}>
            <span className="eng-mono eng-state-name">{transition.state}</span>
            <span className="eng-muted">{formatIso(transition.at)}</span>
            {transition.note && <span className="eng-state-note">{transition.note}</span>}
          </li>
        ))}
      </ol>

      <h3 className="eng-section-title">Action proposal (validated in backend)</h3>
      {run.proposal ? (
        <pre className="eng-payload">{JSON.stringify(run.proposal, null, 2)}</pre>
      ) : (
        <p className="eng-muted">No valid action proposal was produced.</p>
      )}

      {run.proposal_errors?.length > 0 && (
        <div className="eng-note eng-note-terminal">
          <strong>Proposal rejected before governance.</strong>
          <ul>
            {run.proposal_errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </div>
      )}

      {run.ignored_ai_fields?.length > 0 && (
        <div className="eng-note eng-note-deny">
          <strong>AI output fields ignored:</strong> <code>{run.ignored_ai_fields.join(", ")}</code>. Identifiers
          and unknown fields from the model are never used; the patient ID comes from deterministic resolution.
        </div>
      )}

      {run.context_summary && (
        <>
          <h3 className="eng-section-title">Clinical context given to the model</h3>
          <p className="eng-muted">
            {Object.entries(run.context_summary)
              .map(([key, count]) => `${count} ${key}`)
              .join(" · ")}{" "}
            (no internal identifiers)
          </p>
        </>
      )}

      {run.raw_ai_output && (
        <>
          <h3 className="eng-section-title">Raw AI output (untrusted)</h3>
          <pre className="eng-payload">{run.raw_ai_output}</pre>
        </>
      )}
    </div>
  );
}
