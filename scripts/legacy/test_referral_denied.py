"""
Governance-failure scenario: a well-formed but nonexistent patient ID.

    referral candidate -> VSL -> PATIENT_MUST_EXIST violated
    -> TERMINAL -> no database write
"""

import asyncio

from backend.database.schema import ensure_schema
from backend.domain import ReferralRequest
from backend.workflow import get_default_workflow


async def main() -> None:
    ensure_schema()

    print("=" * 70)
    print("X-VERBA DENIED REFERRAL TEST")
    print("=" * 70)

    outcome = await get_default_workflow().run(
        ReferralRequest(
            patient_id="00000000-0000-0000-0000-000000000000",
            department="Cardiology",
            reason="Test invalid patient governance.",
        )
    )

    print("\nRESULT:")
    print(outcome.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
