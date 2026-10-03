import { Ban, CheckCircle2, CircleHelp, OctagonX, ShieldAlert, ShieldCheck } from "lucide-react";

const DECISION_ICON = { ALLOW: CheckCircle2, DENY: Ban, TERMINAL: OctagonX };

export function DecisionBadge({ decision }) {
  const Icon = DECISION_ICON[decision] || CircleHelp;
  return (
    <span className={`eng-badge eng-badge-${(decision || "UNKNOWN").toLowerCase()}`}>
      <Icon size={14} aria-hidden="true" />
      {decision || "UNKNOWN"}
    </span>
  );
}

export function IntegrityBadge({ value }) {
  if (value === null || value === undefined) return <span className="eng-muted">Not reported</span>;
  return value ? (
    <span className="eng-integrity eng-integrity-ok">
      <ShieldCheck size={14} aria-hidden="true" /> Hash chain intact
    </span>
  ) : (
    <span className="eng-integrity eng-integrity-bad">
      <ShieldAlert size={14} aria-hidden="true" /> Integrity check FAILED
    </span>
  );
}
