"""
X-Verba VSL ledger configuration.

The ledger stores governance events in an append-only, hash-chained
JSONL store with filesystem synchronization enabled.

The ledger path can be overridden with the VSL_LEDGER_PATH environment
variable (used by the test suite to keep test evidence out of the
application ledger).
"""

import os
from pathlib import Path
from typing import Any

from vsl_core import JsonlLedgerStore, LedgerEntry, VerbaLedger


# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ledger location
LEDGER_PATH = Path(
    os.environ.get(
        "VSL_LEDGER_PATH",
        str(PROJECT_ROOT / "data" / "ledger.jsonl"),
    )
)


# Ensure the parent directory exists
LEDGER_PATH.parent.mkdir(
    parents=True,
    exist_ok=True,
)


# VSL append-only ledger
ledger_store = JsonlLedgerStore(
    LEDGER_PATH,
    fsync=True,
)

ledger = VerbaLedger(
    ledger_store,
)


def get_ledger() -> VerbaLedger:
    """
    Return the application's VSL ledger instance.
    """
    return ledger


# ============================================================
# Read-only evidence helpers
# ============================================================

def entries_for_decision(decision_id: str) -> list[LedgerEntry]:
    """All ledger entries recorded for one governance decision, in order."""

    return sorted(
        (
            entry
            for entry in ledger.store.all_entries()
            if entry.decision_id == decision_id
        ),
        key=lambda entry: entry.sequence,
    )


def summarize_decision(entries: list[LedgerEntry]) -> dict[str, Any]:
    """
    Derive the governance decision recorded by a set of entries.

    ALLOW    -> VERIFICATION with outcome "approved"
    DENY     -> VERIFICATION with outcome "denied"
    TERMINAL -> a TERMINAL entry exists
    """

    decision = "UNKNOWN"
    terminal_state = None
    invariant = None
    pre_node = None

    for entry in entries:
        entry_type = entry.entry_type.value
        payload = entry.payload or {}

        if entry_type == "PRE_NODE":
            pre_node = payload.get("pre_node")

        elif entry_type == "VERIFICATION":
            invariant = payload.get("invariant", invariant)
            outcome = payload.get("outcome")
            if outcome == "approved":
                decision = "ALLOW"
            elif outcome == "denied":
                decision = "DENY"

        elif entry_type == "TERMINAL":
            decision = "TERMINAL"
            terminal_state = payload.get("terminal_state")

    return {
        "decision": decision,
        "pre_node": pre_node,
        "invariant": invariant,
        "terminal_state": terminal_state,
    }


def recent_decisions(limit: int = 20) -> list[dict[str, Any]]:
    """
    Most recent governance decisions (newest first), derived from the
    existing ledger entries. Read-only; no separate storage.
    """

    grouped: dict[str, list[LedgerEntry]] = {}
    for entry in ledger.store.all_entries():
        if entry.decision_id:
            grouped.setdefault(entry.decision_id, []).append(entry)

    ordered = sorted(
        grouped.items(),
        key=lambda item: max(e.sequence for e in item[1]),
        reverse=True,
    )[:limit]

    decisions: list[dict[str, Any]] = []
    for decision_id, entries in ordered:
        entries.sort(key=lambda e: e.sequence)
        first = entries[0]
        payload = first.payload or {}
        decisions.append(
            {
                "decision_id": decision_id,
                "decision": summarize_decision(entries)["decision"],
                "action": payload.get("action"),
                "tool": payload.get("tool"),
                "department": payload.get("department"),
                "recorded_at": first.timestamp,
                "entry_count": len(entries),
            }
        )

    return decisions


def ledger_integrity_ok() -> bool:
    """True when the hash chain has not been tampered with."""

    return ledger.verify_integrity()
