import asyncio

from sqlalchemy.orm import Session

from backend.database.connection import engine
from governance.gates import governed_referral


PATIENT_ID = "8f998bfd-bcee-9bc0-e435-7c50e571a851"


async def main():

    print("\n======================================")
    print("GOVERNED REFERRAL TEST")
    print("======================================")

    with Session(engine) as session:

        # ====================================================
        # TEST 1 — VALID REQUEST
        # ====================================================

        valid_request = {
            "patient_id": PATIENT_ID,
            "department": "Cardiology",
            "reason": "Persistent cardiac symptoms.",
            "session": session,
        }

        result = await governed_referral(
            valid_request
        )

        print("\nTEST 1 — VALID REQUEST")
        print(f"Decision: {result['decision']}")
        print(f"Decision ID: {result['decision_id']}")
        print(f"Reason: {result['reason']}")

        # ====================================================
        # TEST 2 — INVALID REQUEST
        # ====================================================

        invalid_request = {
            "patient_id": "",
            "department": "",
            "reason": "",
            "session": session,
        }

        result = await governed_referral(
            invalid_request
        )

        print("\nTEST 2 — INVALID REQUEST")
        print(f"Decision: {result['decision']}")
        print(f"Decision ID: {result['decision_id']}")
        print(f"Reason: {result['reason']}")

        # ====================================================
        # TEST 3 — UNKNOWN PATIENT
        # ====================================================

        unknown_patient_request = {
            "patient_id": "PATIENT-DOES-NOT-EXIST",
            "department": "Cardiology",
            "reason": "Persistent cardiac symptoms.",
            "session": session,
        }

        result = await governed_referral(
            unknown_patient_request
        )

        print("\nTEST 3 — UNKNOWN PATIENT")
        print(f"Decision: {result['decision']}")
        print(f"Decision ID: {result['decision_id']}")
        print(f"Reason: {result['reason']}")

        if "terminal_state" in result:
            print(
                f"Terminal State: "
                f"{result['terminal_state']}"
            )


if __name__ == "__main__":
    asyncio.run(main())