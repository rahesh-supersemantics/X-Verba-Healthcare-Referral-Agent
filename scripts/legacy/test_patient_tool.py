from sqlalchemy.orm import Session

from backend.database.connection import engine
from backend.tools.patient_tools import get_patient


PATIENT_ID = "8f998bfd-bcee-9bc0-e435-7c50e571a851"


def main():

    with Session(engine) as session:

        result = get_patient(
            session,
            PATIENT_ID,
        )

        print("\n======================================")
        print("GET PATIENT TEST")
        print("======================================")

        print(f"Success: {result['success']}")

        if result["success"]:

            patient = result["patient"]

            print(f"Patient ID: {patient['patient_id']}")
            print(f"Name: {patient['name']}")
            print(f"DOB: {patient['date_of_birth']}")
            print(f"Gender: {patient['gender']}")

            print(
                f"\nConditions: "
                f"{len(result['conditions'])}"
            )

            print(
                f"Medications: "
                f"{len(result['medications'])}"
            )

            print(
                f"Allergies: "
                f"{len(result['allergies'])}"
            )

            print(
                f"Observations: "
                f"{len(result['observations'])}"
            )

            print(
                f"Recent encounters: "
                f"{len(result['recent_encounters'])}"
            )

        else:

            print(
                f"Error: {result['error']}"
            )


if __name__ == "__main__":
    main()