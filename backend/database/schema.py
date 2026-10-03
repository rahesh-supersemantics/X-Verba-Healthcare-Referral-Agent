"""
Idempotent schema maintenance.

``ensure_schema`` creates any missing tables and applies the single
additive Phase 1 migration: a nullable ``referrals.governance_decision_id``
column linking each referral to the X-Verba decision that allowed it.
Existing rows and data are never modified.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from backend.database.connection import engine as default_engine
from backend.database.models import Base


def ensure_schema(bind: Engine = default_engine) -> None:
    Base.metadata.create_all(bind)

    columns = {
        column["name"]
        for column in inspect(bind).get_columns("referrals")
    }

    if "governance_decision_id" not in columns:
        with bind.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE referrals "
                    "ADD COLUMN governance_decision_id VARCHAR(36)"
                )
            )
