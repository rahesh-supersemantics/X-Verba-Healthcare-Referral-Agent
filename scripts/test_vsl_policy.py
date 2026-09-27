import asyncio

from governance.policy import (
    REFERRAL_REQUEST_VALID,
    patient_exists_rule,
)


async def main():
    print("\n======================================")
    print("VSL POLICY TEST")
    print("======================================")

    valid_request = {
        "patient_id": "8f998bfd-bcee-9bc0-e435-7c50e571a851",
        "department": "Cardiology",
        "reason": "Persistent cardiac symptoms.",
    }

    invalid_request = {
        "patient_id": "",
        "department": "Cardiology",
        "reason": "",
    }

    # -----------------------------------------
    # Valid request
    # -----------------------------------------

    estimate = await REFERRAL_REQUEST_VALID.monitor(
        valid_request
    )

    print("\nVALID REQUEST")
    print(f"Gamma: {estimate.gamma_hat}")
    print(f"Robust Gamma: {estimate.robust_gamma()}")
    print(
        f"Sufficient: "
        f"{estimate.sufficient(REFERRAL_REQUEST_VALID.gamma_threshold)}"
    )

    # -----------------------------------------
    # Invalid request
    # -----------------------------------------

    estimate = await REFERRAL_REQUEST_VALID.monitor(
        invalid_request
    )

    print("\nINVALID REQUEST")
    print(f"Gamma: {estimate.gamma_hat}")
    print(f"Robust Gamma: {estimate.robust_gamma()}")
    print(
        f"Sufficient: "
        f"{estimate.sufficient(REFERRAL_REQUEST_VALID.gamma_threshold)}"
    )


if __name__ == "__main__":
    asyncio.run(main())