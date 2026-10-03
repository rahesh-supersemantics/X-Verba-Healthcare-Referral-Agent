from sqlalchemy.orm import Session

from backend.database.connection import engine
from scripts.legacy.patient_search import search_patient


def main():
    with Session(engine) as session:

        result = search_patient(
            session=session,
            name="Aisha Wiegand",
        )

        print("\n======================================")
        print("PATIENT SEARCH TEST")
        print("======================================")

        print(f"Success: {result['success']}")

        if result["success"]:
            print(f"Matches: {result['match_count']}")

            for patient in result["matches"]:
                print("\nPatient:")
                print(f"  ID: {patient['patient_id']}")
                print(f"  Name: {patient['name']}")
                print(f"  DOB: {patient['date_of_birth']}")
                print(f"  Gender: {patient['gender']}")

        else:
            print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()