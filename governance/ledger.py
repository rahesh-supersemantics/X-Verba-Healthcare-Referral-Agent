"""
X-Verba VSL ledger configuration.

The ledger stores governance events in an append-only JSONL
store with filesystem synchronization enabled.
"""

from pathlib import Path

from vsl_core import JsonlLedgerStore, VerbaLedger


# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ledger location
LEDGER_PATH = PROJECT_ROOT / "data" / "ledger.jsonl"


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