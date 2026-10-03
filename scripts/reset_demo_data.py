"""
Reset the demo state before a client demonstration.

    python -m scripts.reset_demo_data --yes

What it does:
  - archives the governance ledger (data/ledger.jsonl is RENAMED to
    data/ledger-archive-<timestamp>.jsonl; nothing is deleted, so earlier
    evidence remains available for inspection);
  - removes referrals, clinical review requests and clinical workflow runs
    from the SQLite database, so referral numbers and workflow links start
    fresh and match the new ledger.

Synthetic patient data (patients, conditions, medications, observations,
allergies, encounters) is NOT touched.

Stop the FastAPI server before running this (the server keeps the ledger
file open).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = Path(os.environ.get("VSL_LEDGER_PATH", str(PROJECT_ROOT / "data" / "ledger.jsonl")))


def archive_ledger() -> Path | None:
    if not LEDGER_PATH.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = LEDGER_PATH.with_name(f"{LEDGER_PATH.stem}-archive-{stamp}{LEDGER_PATH.suffix}")
    LEDGER_PATH.rename(target)
    lock = LEDGER_PATH.with_name(LEDGER_PATH.name + ".lock")
    if lock.exists():
        lock.unlink()
    return target


def clear_governed_records() -> dict[str, int]:
    from backend.database.connection import SessionLocal
    from backend.database.models import ClinicalReviewRequestRecord, ClinicalWorkflowRun, Referral
    from backend.database.schema import ensure_schema

    ensure_schema()
    with SessionLocal() as session:
        counts = {
            # Review requests reference referrals, so they go first.
            "clinical_review_requests": session.query(ClinicalReviewRequestRecord).delete(),
            "clinical_workflow_runs": session.query(ClinicalWorkflowRun).delete(),
            "referrals": session.query(Referral).delete(),
        }
        session.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm the reset")
    args = parser.parse_args()

    if not args.yes:
        print("This archives the governance ledger and removes all referrals, review requests and")
        print("workflow runs. Patient data is kept. Re-run with --yes to proceed.")
        return 1

    archived = archive_ledger()
    counts = clear_governed_records()

    print(f"Ledger archived to: {archived}" if archived else "No ledger file found (nothing to archive).")
    for table, count in counts.items():
        print(f"Removed {count} row(s) from {table}")
    print("Demo state reset. A new, empty ledger is created on the next governed decision.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
