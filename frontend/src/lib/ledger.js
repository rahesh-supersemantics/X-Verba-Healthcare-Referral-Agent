/**
 * Engineering-console helpers for VSL ledger evidence.
 *
 * These helpers only reshape what GET /governance/{decision_id} returns.
 * They never add ledger events that the backend did not return.
 */

export const DECISIONS = ["ALLOW", "DENY", "TERMINAL"];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isDecisionId(value) {
  return typeof value === "string" && UUID_PATTERN.test(value.trim());
}

export function formatTimestamp(epochSeconds) {
  if (typeof epochSeconds !== "number" || !Number.isFinite(epochSeconds)) {
    return "—";
  }
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").replace("Z", " UTC");
}

export function shortId(value, length = 8) {
  if (typeof value !== "string" || !value) return "—";
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

/**
 * Validate the evidence payload and annotate caused_by links using only
 * the returned entries. Throws on malformed input.
 */
export function buildEvidence(body) {
  if (
    body === null ||
    typeof body !== "object" ||
    typeof body.decision_id !== "string" ||
    typeof body.decision !== "string" ||
    !Array.isArray(body.entries)
  ) {
    throw new Error("Malformed governance evidence response");
  }

  const entries = [...body.entries]
    .filter((e) => e && typeof e === "object" && typeof e.entry_id === "string")
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));

  const byId = new Map(entries.map((e) => [e.entry_id, e]));

  const annotated = entries.map((entry) => {
    const cause = entry.caused_by ? byId.get(entry.caused_by) : null;
    return {
      ...entry,
      cause: entry.caused_by
        ? cause
          ? { resolved: true, entryType: cause.entry_type, sequence: cause.sequence }
          : { resolved: false }
        : null,
    };
  });

  const linkable = annotated.filter((e) => e.caused_by);
  const unresolved = linkable.filter((e) => !e.cause.resolved).length;
  const monitor = annotated.find((e) => e.entry_type === "MONITOR");
  const types = new Set(annotated.map((e) => e.entry_type));

  return {
    decisionId: body.decision_id,
    decision: body.decision,
    action: monitor?.payload?.action ?? null,
    tool: monitor?.payload?.tool ?? null,
    origin: monitor?.payload?.origin ?? null,
    workflowId: monitor?.payload?.workflow_id ?? null,
    preNode: body.pre_node ?? null,
    invariant: body.invariant ?? null,
    terminalState: body.terminal_state ?? null,
    ledgerIntegrity: typeof body.ledger_integrity === "boolean" ? body.ledger_integrity : null,
    entries: annotated,
    causalLinks: { total: linkable.length, unresolved },
    hasHumanAuthorisedTransition: types.has("HUMAN_AUTHORISED_TRANSITION"),
    hasSpecificationUpdate: types.has("SPECIFICATION_UPDATE"),
  };
}
