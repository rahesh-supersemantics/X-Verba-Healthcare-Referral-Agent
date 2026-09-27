import asyncio

from backend.agent_tools import create_referral


async def main() -> None:
    print("=" * 70)
    print("X-VERBA DENIED REFERRAL TEST")
    print("=" * 70)

    fake_patient_id = "patient-does-not-exist"

    print("\nAttempting referral for:")
    print(f"Patient ID: {fake_patient_id}")

    result = await create_referral(
        patient_id=fake_patient_id,
        department="Cardiology",
        reason="Test invalid patient governance.",
    )

    print("\nRESULT:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())