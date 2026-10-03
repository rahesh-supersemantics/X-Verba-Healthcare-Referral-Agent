/**
 * Clinician-facing interpretation of backend responses.
 *
 * Every message shown to a clinician is derived from the workflow
 * STATUS CODE returned by the backend (the authoritative outcome),
 * never from the HTTP status alone and never from LLM text when a
 * referral was attempted. Nothing here re-implements business rules.
 */

export const TONES = {
  SUCCESS: "success",
  WARNING: "warning",
  BLOCKED: "blocked",
  ERROR: "error",
  INFO: "info",
};

const PRESENTATION = {
  REFERRAL_CREATED: {
    tone: TONES.SUCCESS,
    title: "Referral created",
    message: "Referral created successfully.",
  },
  PATIENT_NOT_FOUND: {
    tone: TONES.WARNING,
    title: "Patient not found",
    message:
      "The referral could not be created because no matching patient record was found. Check the patient's name and try again.",
  },
  MULTIPLE_PATIENT_MATCHES: {
    tone: TONES.WARNING,
    title: "Patient not uniquely identified",
    message:
      "The referral could not be created because the patient could not be uniquely identified. Please restate the request using the patient's full name.",
  },
  INVALID_PATIENT_ID: {
    tone: TONES.ERROR,
    title: "Patient record could not be verified",
    message:
      "The referral could not be created because the patient record could not be verified. Please contact the clinical systems team.",
  },
  INVALID_REQUEST: {
    tone: TONES.WARNING,
    title: "Request incomplete",
    message:
      "The referral could not be created because the request was incomplete. Include the patient, the receiving department and the reason for referral.",
  },
  GOVERNANCE_DENIED: {
    tone: TONES.BLOCKED,
    title: "Referral blocked",
    message:
      "The referral was blocked by the governance workflow. No referral was created. Review the request details and try again.",
  },
  GOVERNANCE_TERMINAL: {
    tone: TONES.BLOCKED,
    title: "Referral blocked",
    message:
      "The referral was blocked by the governance workflow because a mandatory safety check was not met. No referral was created. If you believe this is an error, contact the clinical systems team.",
  },
  INTERNAL_ERROR: {
    tone: TONES.ERROR,
    title: "Referral not created",
    message:
      "The referral could not be completed because of a system error. No referral was created. Please try again or contact support.",
  },
};

// Phase 3: clearer wording for specific governance denials. Keyed on the
// rule that denied, which itself is never displayed to clinicians.
const DENIAL_PRESENTATION = {
  REFERRAL_NOT_DUPLICATE: {
    tone: TONES.BLOCKED,
    title: "Duplicate referral blocked",
    message:
      "An equivalent referral to this department is already active for this patient, so no new referral was created.",
  },
  REFERRAL_TARGET_VALID: {
    tone: TONES.BLOCKED,
    title: "Department not supported",
    message:
      "The requested department is not one that referrals can be sent to. No referral was created. Choose a supported department.",
  },
};

const UNKNOWN_OUTCOME = {
  tone: TONES.ERROR,
  title: "Outcome could not be confirmed",
  message:
    "The outcome of this request could not be confirmed. Do not assume a referral was created.",
};

/** Request-progress stages shown to clinicians (business language only). */
export const STAGES = [
  { key: "request", label: "Request received" },
  { key: "patient", label: "Patient identified" },
  { key: "checks", label: "Safety & governance checks" },
  { key: "record", label: "Referral recorded" },
];

// done | failed | blocked | skipped | unknown
const STAGE_STATES = {
  REFERRAL_CREATED: ["done", "done", "done", "done"],
  INVALID_REQUEST: ["failed", "skipped", "skipped", "skipped"],
  PATIENT_NOT_FOUND: ["done", "failed", "skipped", "skipped"],
  MULTIPLE_PATIENT_MATCHES: ["done", "failed", "skipped", "skipped"],
  INVALID_PATIENT_ID: ["done", "failed", "skipped", "skipped"],
  GOVERNANCE_DENIED: ["done", "done", "blocked", "skipped"],
  GOVERNANCE_TERMINAL: ["done", "done", "blocked", "skipped"],
};

function stagesFor(result) {
  let states = STAGE_STATES[result.status];

  if (!states && result.status === "UNKNOWN") {
    states = ["done", "unknown", "unknown", "unknown"];
  } else if (!states) {
    // INTERNAL_ERROR or unknown: only mark what the backend proves happened.
    const allowed = result.governance && result.governance.decision === "ALLOW";
    states = allowed
      ? ["done", "done", "done", "failed"]
      : ["done", "failed", "skipped", "skipped"];
  }

  return STAGES.map((stage, index) => ({ ...stage, state: states[index] }));
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * Convert one workflow result into a clinician-safe view model.
 * Patient UUIDs, decision IDs and governance internals are dropped.
 */
export function presentWorkflowResult(result) {
  if (!isObject(result) || typeof result.status !== "string") {
    return {
      ...UNKNOWN_OUTCOME,
      status: "UNKNOWN",
      success: false,
      stages: stagesFor({ status: "UNKNOWN" }),
      referral: null,
      patient: null,
      candidates: [],
    };
  }

  const known = PRESENTATION[result.status];
  const presentation =
    (result.status === "GOVERNANCE_DENIED" && DENIAL_PRESENTATION[result.governance?.pre_node]) ||
    known ||
    UNKNOWN_OUTCOME;

  // Success requires BOTH the success flag and the created status and a
  // referral record. Anything less is not presented as success.
  const success =
    result.success === true &&
    result.status === "REFERRAL_CREATED" &&
    isObject(result.referral);

  // A "created" status without a referral record is contradictory:
  // treat it as unconfirmed rather than as success.
  const trusted = Boolean(known) && (success || result.status !== "REFERRAL_CREATED");
  const view = trusted ? presentation : UNKNOWN_OUTCOME;
  const effectiveStatus = trusted ? result.status : "UNKNOWN";

  const patient = isObject(result.patient)
    ? {
        name: result.patient.name,
        dateOfBirth: result.patient.date_of_birth || null,
      }
    : null;

  const referral = success
    ? {
        reference: result.referral.referral_id,
        department: result.referral.department,
        reason: result.referral.reason,
        status: result.referral.status,
        createdAt: result.referral.created_at,
      }
    : null;

  const candidates = Array.isArray(result.candidates)
    ? result.candidates
        .filter(isObject)
        .map((c) => ({ name: c.name, dateOfBirth: c.date_of_birth || null }))
    : [];

  return {
    ...view,
    status: effectiveStatus,
    success,
    stages: stagesFor({ ...result, status: effectiveStatus }),
    patient,
    referral,
    candidates,
  };
}

/**
 * Interpret a POST /chat response body.
 *
 * Returns { kind: "referral", outcomes: [...] } when the governed
 * workflow actually ran, { kind: "message", text } for conversational
 * replies (greetings, questions, lookups), or throws MalformedResponse.
 */
export class MalformedResponseError extends Error {
  constructor(message = "Malformed response") {
    super(message);
    this.name = "MalformedResponseError";
  }
}

export function interpretChatResponse(body) {
  if (!isObject(body) || typeof body.reply !== "string") {
    throw new MalformedResponseError("Missing reply");
  }

  const results = body.workflow_results;

  if (!Array.isArray(results)) {
    throw new MalformedResponseError("Missing workflow_results");
  }

  const attempted =
    typeof body.referral_attempted === "boolean"
      ? body.referral_attempted
      : results.length > 0;

  if (attempted !== results.length > 0) {
    throw new MalformedResponseError("Inconsistent workflow result");
  }

  // Phase 2: clinical reviews (optional field for older backends).
  const reviews = body.clinical_reviews ?? [];
  if (!Array.isArray(reviews)) {
    throw new MalformedResponseError("Malformed clinical_reviews");
  }
  const reviewed =
    typeof body.clinical_review_attempted === "boolean" ? body.clinical_review_attempted : reviews.length > 0;
  if (reviewed !== reviews.length > 0) {
    throw new MalformedResponseError("Inconsistent clinical review result");
  }

  // Phase 3: governed update / cancel / review-request actions.
  const actions = body.action_results ?? [];
  if (!Array.isArray(actions)) {
    throw new MalformedResponseError("Malformed action_results");
  }
  const acted = typeof body.action_attempted === "boolean" ? body.action_attempted : actions.length > 0;
  if (acted !== actions.length > 0) {
    throw new MalformedResponseError("Inconsistent action result");
  }

  const conversation = {
    conversationId: typeof body.conversation_id === "string" ? body.conversation_id : null,
    context: presentConversationContext(body.context),
  };

  if (attempted || reviewed || acted) {
    return {
      kind: "referral",
      reviews: reviews.map(presentClinicalReview),
      outcomes: [...results.map(presentWorkflowResult), ...actions.map(presentActionResult)],
      ...conversation,
    };
  }

  return {
    kind: "message",
    text: body.reply.trim() || "No response was returned.",
    ...conversation,
  };
}

const ACTION_PRESENTATION = {
  REFERRAL_UPDATED: { tone: TONES.SUCCESS, title: "Referral updated", message: "The referral was updated." },
  REFERRAL_CANCELLED: { tone: TONES.SUCCESS, title: "Referral cancelled", message: "The referral was cancelled." },
  CLINICAL_REVIEW_REQUESTED: {
    tone: TONES.SUCCESS,
    title: "Clinical review requested",
    message: "A clinical review was requested for this patient.",
  },
  INVALID_REQUEST: {
    tone: TONES.WARNING,
    title: "Request incomplete",
    message: "The request was incomplete, so no change was made.",
  },
  PATIENT_NOT_FOUND: PRESENTATION.PATIENT_NOT_FOUND,
  MULTIPLE_PATIENT_MATCHES: PRESENTATION.MULTIPLE_PATIENT_MATCHES,
  INVALID_PATIENT_ID: PRESENTATION.INVALID_PATIENT_ID,
  GOVERNANCE_DENIED: {
    tone: TONES.BLOCKED,
    title: "Change blocked",
    message: "The governance workflow did not permit this change. Nothing was changed.",
  },
  GOVERNANCE_TERMINAL: {
    tone: TONES.BLOCKED,
    title: "Change blocked",
    message:
      "The change was blocked because a mandatory safety check was not met. Nothing was changed. If you believe this is an error, contact the clinical systems team.",
  },
  INTERNAL_ERROR: {
    tone: TONES.ERROR,
    title: "Change not completed",
    message: "The change could not be completed because of a system error. Nothing was changed.",
  },
};

const ACTION_SUCCESS = new Set(["REFERRAL_UPDATED", "REFERRAL_CANCELLED", "CLINICAL_REVIEW_REQUESTED"]);

/** Progress stages for update / cancel / review-request actions. */
export const ACTION_STAGES = [
  { key: "request", label: "Request received" },
  { key: "patient", label: "Patient identified" },
  { key: "checks", label: "Safety & governance checks" },
  { key: "record", label: "Change recorded" },
];

const ACTION_STAGE_STATES = {
  REFERRAL_UPDATED: ["done", "done", "done", "done"],
  REFERRAL_CANCELLED: ["done", "done", "done", "done"],
  CLINICAL_REVIEW_REQUESTED: ["done", "done", "done", "done"],
  INVALID_REQUEST: ["failed", "skipped", "skipped", "skipped"],
  PATIENT_NOT_FOUND: ["done", "failed", "skipped", "skipped"],
  MULTIPLE_PATIENT_MATCHES: ["done", "failed", "skipped", "skipped"],
  INVALID_PATIENT_ID: ["done", "failed", "skipped", "skipped"],
  GOVERNANCE_DENIED: ["done", "done", "blocked", "skipped"],
  GOVERNANCE_TERMINAL: ["done", "done", "blocked", "skipped"],
  INTERNAL_ERROR: ["done", "unknown", "unknown", "failed"],
  UNKNOWN: ["done", "unknown", "unknown", "unknown"],
};

function actionStages(status) {
  const states = ACTION_STAGE_STATES[status] || ACTION_STAGE_STATES.UNKNOWN;
  return ACTION_STAGES.map((stage, index) => ({ ...stage, state: states[index] }));
}

/**
 * Phase 3: present a governed update / cancel / review-request outcome.
 * Success needs the success flag, a success status and the record the
 * action produced; anything less is not shown as success.
 */
export function presentActionResult(result) {
  if (!isObject(result) || typeof result.status !== "string") {
    return { ...UNKNOWN_OUTCOME, kind: "action", status: "UNKNOWN", success: false, stages: actionStages("UNKNOWN"), referral: null, patient: null, candidates: [] };
  }

  const known = ACTION_PRESENTATION[result.status];
  const hasRecord =
    result.status === "CLINICAL_REVIEW_REQUESTED" ? isObject(result.review_request) : isObject(result.referral);
  const success = result.success === true && ACTION_SUCCESS.has(result.status) && hasRecord;
  const trusted = Boolean(known) && (success || !ACTION_SUCCESS.has(result.status));
  const view = trusted ? known : UNKNOWN_OUTCOME;

  const referral =
    success && isObject(result.referral)
      ? {
          reference: result.referral.referral_id,
          department: result.referral.department,
          reason: result.referral.reason,
          status: result.referral.status,
          createdAt: result.referral.created_at,
        }
      : null;

  return {
    ...view,
    kind: "action",
    action: typeof result.action === "string" ? result.action : null,
    status: trusted ? result.status : "UNKNOWN",
    success,
    stages: actionStages(trusted ? result.status : "UNKNOWN"),
    patient: isObject(result.patient)
      ? { name: result.patient.name, dateOfBirth: result.patient.date_of_birth || null }
      : null,
    referral,
    reviewRequest:
      success && isObject(result.review_request)
        ? {
            reference: result.review_request.review_request_id,
            department: result.review_request.department || null,
            reason: result.review_request.reason,
          }
        : null,
    candidates: Array.isArray(result.candidates)
      ? result.candidates.filter(isObject).map((c) => ({ name: c.name, dateOfBirth: c.date_of_birth || null }))
      : [],
  };
}

const MISSING_LABELS = { patient: "Patient", department: "Department", reason: "Reason for referral" };
const STAGE_LABELS = {
  COLLECTING: "Collecting details",
  READY: "Awaiting your confirmation",
  CONFIRMED: "Confirmed",
  SUBMITTED: "Submitted",
};

/**
 * Phase 3: clinician-safe view of what the conversation has established
 * (patient name, department, reason, what is still missing). Returns null
 * when no referral is being discussed.
 */
export function presentConversationContext(context) {
  if (!isObject(context)) return null;
  const patient = isObject(context.patient) && typeof context.patient.name === "string"
    ? { name: context.patient.name, dateOfBirth: context.patient.date_of_birth || null }
    : null;
  const missing = Array.isArray(context.missing)
    ? context.missing.filter((m) => typeof m === "string").map((m) => MISSING_LABELS[m] || m)
    : [];
  const active = context.intent === "REFERRAL" || context.intent === "REVIEW";
  if (!active && !patient) return null;
  return {
    active,
    stage: active ? STAGE_LABELS[context.stage] || null : null,
    patient,
    department: active && typeof context.department === "string" ? context.department : null,
    reason: active && typeof context.reason === "string" ? context.reason : null,
    missing: active ? missing : [],
  };
}

/** Clinician-safe text for transport / service failures. */
export const SERVICE_ERRORS = {
  API_UNAVAILABLE: {
    title: "Referral service unavailable",
    message:
      "The referral service could not be reached. No referral was created. Please try again shortly.",
  },
  LLM_UNAVAILABLE: {
    title: "Assistant temporarily unavailable",
    message:
      "The referral assistant is temporarily unavailable. No referral was created. Please try again shortly.",
  },
  TIMEOUT: {
    title: "Request timed out",
    message:
      "The request took too long to complete. Its outcome could not be confirmed, so do not assume a referral was created.",
  },
  INVALID_REQUEST: {
    title: "Request not accepted",
    message:
      "The request could not be accepted. Please check the message and try again.",
  },
  INTERNAL_ERROR: {
    title: "System error",
    message:
      "The request could not be completed because of a system error. No referral was created.",
  },
  MALFORMED_RESPONSE: {
    title: "Outcome could not be confirmed",
    message:
      "The service returned an unexpected response. Do not assume a referral was created.",
  },
  UNEXPECTED: {
    title: "Request failed",
    message: "The request could not be completed. Please try again.",
  },
};

/**
 * Classify a transport-level failure into one of SERVICE_ERRORS keys.
 * Input is a plain description so it can be unit tested without axios.
 */
export function classifyFailure({ network = false, timeout = false, status, errorCode } = {}) {
  if (timeout) return "TIMEOUT";
  if (network || status === undefined || status === null) return "API_UNAVAILABLE";
  if (status === 503 && errorCode === "LLM_UNAVAILABLE") return "LLM_UNAVAILABLE";
  if (status === 503) return "API_UNAVAILABLE";
  if (status === 422 || status === 400) return "INVALID_REQUEST";
  if (status >= 500) return "INTERNAL_ERROR";
  return "UNEXPECTED";
}

// ------------------------------------------------------------------
// Phase 2: clinical review workflow (POST /clinical-workflows, agent tool)
// ------------------------------------------------------------------

const REVIEW_PRESENTATION = {
  REFERRAL_CREATED: {
    tone: TONES.SUCCESS,
    title: "Referral created",
    message: "The review recommended a referral and it was created successfully.",
  },
  NO_ACTION_RECOMMENDED: {
    tone: TONES.INFO,
    title: "No referral recommended",
    message: "The review did not recommend a referral. No action was taken.",
  },
  GOVERNANCE_DENIED: {
    tone: TONES.BLOCKED,
    title: "Referral needs human review",
    message:
      "The proposed referral was blocked by the governance workflow and needs review by a clinician. No referral was created.",
  },
  GOVERNANCE_TERMINAL: PRESENTATION.GOVERNANCE_TERMINAL,
  INVALID_PROPOSAL: {
    tone: TONES.ERROR,
    title: "Review could not be completed",
    message:
      "The automated review did not produce a usable recommendation. No action was taken and no referral was created.",
  },
  ANALYSIS_UNAVAILABLE: {
    tone: TONES.ERROR,
    title: "Review service unavailable",
    message: "The automated review service is temporarily unavailable. No referral was created. Please try again shortly.",
  },
  PATIENT_NOT_FOUND: PRESENTATION.PATIENT_NOT_FOUND,
  MULTIPLE_PATIENT_MATCHES: PRESENTATION.MULTIPLE_PATIENT_MATCHES,
  INVALID_PATIENT_ID: PRESENTATION.INVALID_PATIENT_ID,
  INVALID_REQUEST: {
    tone: TONES.WARNING,
    title: "Request not accepted",
    message:
      "The review request could not be accepted. Check the patient name and the department, then try again.",
  },
  INTERNAL_ERROR: PRESENTATION.INTERNAL_ERROR,
};

export const REVIEW_STAGES = [
  { key: "patient", label: "Patient identified", state: "PATIENT_RESOLVED" },
  { key: "record", label: "Record retrieved", state: "DATA_RETRIEVED" },
  { key: "analysis", label: "AI review", state: "ANALYSIS_COMPLETED" },
  { key: "proposal", label: "Action proposed", state: "ACTION_PROPOSED" },
  { key: "checks", label: "Safety & governance checks", state: "GOVERNANCE_CHECK" },
  { key: "record_referral", label: "Referral recorded", state: "ACTION_EXECUTED" },
];

/**
 * Stages derived from the backend's ACTUAL state transitions; nothing is
 * marked done unless the backend recorded it.
 */
function reviewStages(result, trustedStatus) {
  const reached = new Set(
    (Array.isArray(result.transitions) ? result.transitions : []).map((t) => t && t.state),
  );
  const governanceAllowed = isObject(result.governance) && result.governance.decision === "ALLOW";
  const noAction = trustedStatus === "NO_ACTION_RECOMMENDED";

  const isDone = (stage) =>
    stage.key === "checks" ? reached.has("ACTION_EXECUTED") || governanceAllowed : reached.has(stage.state);

  function firstMissingState(stage) {
    if (noAction) return "notneeded";
    if (trustedStatus === "UNKNOWN") return "unknown";
    if (result.state === "REVIEW_REQUIRED" || result.state === "TERMINAL") return "blocked";
    if (result.state === "FAILED") return "failed";
    return stage.key === "checks" ? "blocked" : "unknown";
  }

  let stopped = false;
  return REVIEW_STAGES.map((stage) => {
    let state;
    if (!stopped && isDone(stage)) {
      state = "done";
    } else if (!stopped) {
      state = firstMissingState(stage);
      stopped = true;
    } else {
      state = noAction ? "notneeded" : "skipped";
    }
    return { key: stage.key, label: stage.label, state };
  });
}

/** Clinician-safe view of a clinical workflow result (no UUIDs, no governance internals). */
export function presentClinicalReview(result) {
  if (!isObject(result) || typeof result.status !== "string") {
    return {
      ...UNKNOWN_OUTCOME,
      kind: "review",
      status: "UNKNOWN",
      success: false,
      stages: REVIEW_STAGES.map((s) => ({ key: s.key, label: s.label, state: "unknown" })),
      recommendation: null,
      proposedDepartment: null,
      patient: null,
      referral: null,
      candidates: [],
    };
  }

  const known = REVIEW_PRESENTATION[result.status];
  const created = result.status === "REFERRAL_CREATED";
  const success =
    result.success === true &&
    (created ? isObject(result.referral) : result.status === "NO_ACTION_RECOMMENDED");
  const trusted = Boolean(known) && (success || !(created || result.status === "NO_ACTION_RECOMMENDED"));
  const view = trusted ? known : UNKNOWN_OUTCOME;
  const status = trusted ? result.status : "UNKNOWN";

  const proposal = isObject(result.proposal) ? result.proposal : null;

  return {
    ...view,
    kind: "review",
    status,
    success,
    stages: reviewStages(result, status),
    recommendation: proposal && typeof proposal.recommendation === "string" ? proposal.recommendation : null,
    proposedDepartment: proposal && proposal.action === "CREATE_REFERRAL" ? proposal.department ?? null : null,
    patient: isObject(result.patient)
      ? { name: result.patient.name, dateOfBirth: result.patient.date_of_birth || null }
      : null,
    referral:
      success && created
        ? {
            reference: result.referral.referral_id,
            department: result.referral.department,
            reason: result.referral.reason,
            status: result.referral.status,
            createdAt: result.referral.created_at,
          }
        : null,
    candidates: Array.isArray(result.candidates)
      ? result.candidates.filter(isObject).map((c) => ({ name: c.name, dateOfBirth: c.date_of_birth || null }))
      : [],
  };
}
