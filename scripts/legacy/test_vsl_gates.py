import asyncio

from sqlalchemy.orm import Session

from backend.database.connection import engine
from governance.gates import check_referral_governance


PATIENT_ID = "8f998bfd-bcee-9bc0-e435-7c50e571a851"


async def main():

    print("\n======================================")
    print("VSL GOVERNANCE GATE TEST")
    print("======================================")

    with Session(engine) as session:

        # =====================================================
        # TEST 1 — VALID REQUEST + EXISTING PATIENT
        # =====================================================

        valid_request = {
            "patient_id": PATIENT_ID,
            "department": "Cardiology",
            "reason": "Persistent cardiac symptoms.",
            "session": session,
        }

        result = await check_referral_governance(
            valid_request
        )

        print("\nTEST 1 — VALID REQUEST")
        print(f"Decision: {result['decision']}")
        print(f"Reason: {result['reason']}")

        # =====================================================
        # TEST 2 — INVALID REQUEST
        # =====================================================

        invalid_request = {
            "patient_id": "",
            "department": "Cardiology",
            "reason": "",
            "session": session,
        }

        result = await check_referral_governance(
            invalid_request
        )

        print("\nTEST 2 — INVALID REQUEST")
        print(f"Decision: {result['decision']}")
        print(f"Reason: {result['reason']}")

        # =====================================================
        # TEST 3 — NON-EXISTENT PATIENT
        # =====================================================

        unknown_patient_request = {
            "patient_id": "PATIENT-DOES-NOT-EXIST",
            "department": "Cardiology",
            "reason": "Persistent cardiac symptoms.",
            "session": session,
        }

        result = await check_referral_governance(
            unknown_patient_request
        )

        print("\nTEST 3 — UNKNOWN PATIENT")
        print(f"Decision: {result['decision']}")
        print(f"Reason: {result['reason']}")

        if "invariant" in result:
            print(f"Invariant: {result['invariant']}")


if __name__ == "__main__":
    asyncio.run(main())