import {
  Ban,
  CheckCircle2,
  Circle,
  CircleHelp,
  History,
  Info,
  ListChecks,
  Loader2,
  MessagesSquare,
  Minus,
  TriangleAlert,
  WifiOff,
  XCircle,
} from "lucide-react";

import { REVIEW_STAGES, SERVICE_ERRORS, STAGES } from "../lib/outcomes.js";

const TONE_ICON = {
  success: CheckCircle2,
  warning: TriangleAlert,
  blocked: Ban,
  error: XCircle,
  info: Info,
};

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function truncate(value, length) {
  if (!value) return "Referral request";
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function titleCase(value) {
  if (!value) return "—";
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

export function ServiceStatusPill({ health }) {
  const label =
    health === "online" ? "Service connected" : health === "offline" ? "Service unavailable" : "Checking service…";
  return (
    <div className={`clin-pill clin-pill-${health}`} role="status">
      <span className="clin-pill-dot" aria-hidden="true" />
      {label}
    </div>
  );
}

export function OutcomeCard({ outcome, compact = false }) {
  const Icon = TONE_ICON[outcome.tone] || CircleHelp;

  return (
    <div className={`clin-outcome clin-tone-${outcome.tone} ${compact ? "clin-outcome-compact" : ""}`}>
      <div className="clin-outcome-head">
        <Icon size={18} aria-hidden="true" />
        <strong>{outcome.title}</strong>
      </div>
      <p>{outcome.message}</p>

      {outcome.kind === "review" && outcome.recommendation && (
        <div className="clin-recommendation">
          <div className="clin-recommendation-label">
            AI recommendation <span>· decision support only, not a diagnosis</span>
          </div>
          <p>{outcome.recommendation}</p>
          {outcome.proposedDepartment && !outcome.referral && (
            <p className="clin-muted">Proposed: referral to {outcome.proposedDepartment}</p>
          )}
        </div>
      )}

      {outcome.referral && (
        <dl className="clin-details">
          <div className="clin-details-patient">
            <dt>Patient</dt>
            <dd>{outcome.patient?.name ?? "—"}</dd>
          </div>
          {!compact && (
            <div>
              <dt>Date of birth</dt>
              <dd>{outcome.patient?.dateOfBirth ?? "—"}</dd>
            </div>
          )}
          <div>
            <dt>Department</dt>
            <dd>{outcome.referral.department}</dd>
          </div>
          {!compact && (
            <div className="clin-details-wide">
              <dt>Reason</dt>
              <dd>{outcome.referral.reason}</dd>
            </div>
          )}
          <div>
            <dt>Referral no.</dt>
            <dd>{outcome.referral.reference}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{titleCase(outcome.referral.status)}</dd>
          </div>
          {!compact && (
            <div>
              <dt>Created</dt>
              <dd>{formatDate(outcome.referral.createdAt)}</dd>
            </div>
          )}
        </dl>
      )}

      {outcome.reviewRequest && (
        <dl className="clin-details">
          <div className="clin-details-patient">
            <dt>Patient</dt>
            <dd>{outcome.patient?.name ?? "—"}</dd>
          </div>
          {outcome.reviewRequest.department && (
            <div>
              <dt>Department</dt>
              <dd>{outcome.reviewRequest.department}</dd>
            </div>
          )}
          <div>
            <dt>Review request no.</dt>
            <dd>{outcome.reviewRequest.reference}</dd>
          </div>
          {!compact && (
            <div className="clin-details-wide">
              <dt>Reason</dt>
              <dd>{outcome.reviewRequest.reason}</dd>
            </div>
          )}
        </dl>
      )}

      {outcome.candidates.length > 0 && (
        <div className="clin-candidates">
          <span>Matching patients:</span>
          <ul>
            {outcome.candidates.map((candidate) => (
              <li key={`${candidate.name}-${candidate.dateOfBirth}`}>
                {candidate.name}
                {candidate.dateOfBirth && <span className="clin-muted"> · DOB {candidate.dateOfBirth}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ServiceErrorCard({ kind, compact = false }) {
  const detail = SERVICE_ERRORS[kind] || SERVICE_ERRORS.UNEXPECTED;
  const Icon = kind === "API_UNAVAILABLE" ? WifiOff : XCircle;
  return (
    <div className={`clin-outcome clin-tone-error ${compact ? "clin-outcome-compact" : ""}`} role="alert">
      <div className="clin-outcome-head">
        <Icon size={18} aria-hidden="true" />
        <strong>{detail.title}</strong>
      </div>
      <p>{detail.message}</p>
    </div>
  );
}

const STAGE_ICON = {
  done: CheckCircle2,
  failed: XCircle,
  blocked: Ban,
  skipped: Minus,
  unknown: CircleHelp,
  notneeded: Minus,
  active: Loader2,
  idle: Circle,
};

const STAGE_TEXT = {
  done: "Completed",
  failed: "Not completed",
  blocked: "Blocked",
  skipped: "Not reached",
  unknown: "Not confirmed",
  notneeded: "Not needed",
  active: "In progress",
  idle: "Waiting",
};

export function RequestStatus({ latest, pending, pendingKind }) {
  let stages = null;
  let note = null;

  if (pending) {
    const base = pendingKind === "review" ? REVIEW_STAGES : STAGES;
    stages = base.map((stage, index) => ({ key: stage.key, label: stage.label, state: index === 0 ? "active" : "idle" }));
    note = "Your request is being processed.";
  } else if (latest?.type === "referral") {
    const items = [...(latest.reviews || []), ...(latest.outcomes || [])];
    stages = items[items.length - 1]?.stages || null;
    if (!stages) note = "The latest result is shown below.";
  } else if (latest?.type === "error") {
    note = "The last request could not be completed.";
  } else if (latest?.type === "message") {
    note = "Nothing has been submitted from the last message.";
  } else {
    note = "Submit a referral request to see its progress.";
  }

  return (
    <section className="clin-card">
      <h2 className="clin-card-title">
        <ListChecks size={17} aria-hidden="true" />
        Request status
      </h2>

      {stages && (
        <ol className="clin-stages">
          {stages.map((stage) => {
            const Icon = STAGE_ICON[stage.state] || Circle;
            return (
              <li key={stage.key} className={`clin-stage clin-stage-${stage.state}`}>
                <Icon size={16} aria-hidden="true" className={stage.state === "active" ? "clin-spin" : ""} />
                <span className="clin-stage-label">{stage.label}</span>
                <span className="clin-stage-state">{STAGE_TEXT[stage.state]}</span>
              </li>
            );
          })}
        </ol>
      )}

      {note && <p className="clin-muted">{note}</p>}
    </section>
  );
}

export function SessionReferrals({ items }) {
  return (
    <section className="clin-card">
      <h2 className="clin-card-title">
        <History size={17} aria-hidden="true" />
        This session
      </h2>
      {items.length === 0 ? (
        <p className="clin-muted">No referral requests or changes yet.</p>
      ) : (
        <ul className="clin-session">
          {items.map(({ id, request, outcome }) => (
            <li key={id}>
              <span className={`clin-chip clin-tone-${outcome.tone}`}>{outcome.title}</span>
              <span className="clin-session-text">
                {outcome.referral
                  ? `${outcome.patient?.name ?? "Patient"} → ${outcome.referral.department}`
                  : outcome.kind === "review" && outcome.patient
                    ? `Review: ${outcome.patient.name}${outcome.proposedDepartment ? ` → ${outcome.proposedDepartment}` : ""}`
                    : truncate(request, 70)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Phase 3: what the conversation has established so far (no identifiers). */
export function ConversationContextCard({ context }) {
  if (!context) return null;
  const rows = [
    ["Patient", context.patient?.name],
    ["Department", context.department],
    ["Reason", context.reason],
  ];
  return (
    <section className="clin-card clin-context" aria-label="Conversation details">
      <h2 className="clin-card-title">
        <MessagesSquare size={17} aria-hidden="true" />
        Current conversation
      </h2>
      {context.stage && <p className="clin-context-stage">{context.stage}</p>}
      <dl className="clin-details">
        {rows
          .filter(([label, value]) => value || context.active || label === "Patient")
          .map(([label, value]) => (
            <div key={label} className={label === "Reason" ? "clin-details-wide" : undefined}>
              <dt>{label}</dt>
              <dd>{value || <span className="clin-muted">Not yet provided</span>}</dd>
            </div>
          ))}
      </dl>
      {context.missing.length > 0 && (
        <p className="clin-muted">Still needed: {context.missing.join(", ")}</p>
      )}
    </section>
  );
}
