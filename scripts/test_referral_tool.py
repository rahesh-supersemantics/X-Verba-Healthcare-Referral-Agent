import asyncio

from backend.agent_tools import create_referral


PATIENT_ID = "8f998bfd-bcee-9bc0-e435-7c50e571a851"


async def main() -> None:
    print("=" * 70)
    print("X-VERBA GOVERNED REFERRAL TOOL TEST")
    print("=" * 70)

    print("\nCreating referral...")

    result = await create_referral(
        patient_id=PATIENT_ID,
        department="Cardiology",
        reason="Patient requires cardiology assessment.",
    )

    print("\nRESULT:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())