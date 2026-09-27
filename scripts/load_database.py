import pandas as pd
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import engine
from backend.database.models import (
    Patient,
    Condition,
    Medication,
    Allergy,
    Observation,
    Encounter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"


def load_csv(filename):
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    return pd.read_csv(path)


def load_patients(session):
    df = load_csv("patients.csv")

    count = 0

    for _, row in df.iterrows():

        existing = session.get(
            Patient,
            str(row["patient_id"])
        )

        if existing:
            continue

        patient = Patient(
            patient_id=str(row["patient_id"]),
            name=str(row["name"]),
            date_of_birth=(
                None
                if pd.isna(row["date_of_birth"])
                else str(row["date_of_birth"])
            ),
            gender=(
                None
                if pd.isna(row["gender"])
                else str(row["gender"])
            ),
        )

        session.add(patient)
        count += 1

    session.commit()

    print(f"Patients inserted: {count}")


def load_conditions(session):
    df = load_csv("conditions.csv")

    count = 0

    for _, row in df.iterrows():

        if pd.isna(row["condition"]):
            continue

        record = Condition(
            patient_id=str(row["patient_id"]),
            condition=str(row["condition"]),
            status=(
                None
                if pd.isna(row["status"])
                else str(row["status"])
            ),
            onset=(
                None
                if pd.isna(row["onset"])
                else str(row["onset"])
            ),
        )

        session.add(record)
        count += 1

    session.commit()

    print(f"Conditions inserted: {count}")


def load_medications(session):
    df = load_csv("medications.csv")

    count = 0

    for _, row in df.iterrows():

        medication = (
            None
            if pd.isna(row["medication"])
            else str(row["medication"])
        )

        record = Medication(
            patient_id=str(row["patient_id"]),
            medication=medication,
            status=(
                None
                if pd.isna(row["status"])
                else str(row["status"])
            ),
        )

        session.add(record)
        count += 1

    session.commit()

    print(f"Medications inserted: {count}")


def load_allergies(session):
    df = load_csv("allergies.csv")

    count = 0

    for _, row in df.iterrows():

        if pd.isna(row["allergy"]):
            continue

        record = Allergy(
            patient_id=str(row["patient_id"]),
            allergy=str(row["allergy"]),
            status=(
                None
                if pd.isna(row["status"])
                else str(row["status"])
            ),
        )

        session.add(record)
        count += 1

    session.commit()

    print(f"Allergies inserted: {count}")


def load_observations(session):
    df = load_csv("observations.csv")

    count = 0

    for _, row in df.iterrows():

        if pd.isna(row["type"]):
            continue

        record = Observation(
            patient_id=str(row["patient_id"]),
            type=str(row["type"]),
            value=(
                None
                if pd.isna(row["value"])
                else str(row["value"])
            ),
            date=(
                None
                if pd.isna(row["date"])
                else str(row["date"])
            ),
        )

        session.add(record)
        count += 1

    session.commit()

    print(f"Observations inserted: {count}")


def load_encounters(session):
    df = load_csv("encounters.csv")

    count = 0

    for _, row in df.iterrows():

        record = Encounter(
            patient_id=str(row["patient_id"]),
            type=(
                None
                if pd.isna(row["type"])
                else str(row["type"])
            ),
            status=(
                None
                if pd.isna(row["status"])
                else str(row["status"])
            ),
            start=(
                None
                if pd.isna(row["start"])
                else str(row["start"])
            ),
        )

        session.add(record)

    session.commit()

    print(f"Encounters inserted: {len(df)}")


def main():

    print("\n======================================")
    print("LOADING HEALTHCARE DATABASE")
    print("======================================\n")

    with Session(engine) as session:

        load_patients(session)
        load_conditions(session)
        load_medications(session)
        load_allergies(session)
        load_observations(session)
        load_encounters(session)

    print("\n======================================")
    print("DATABASE LOADING COMPLETE")
    print("======================================")


if __name__ == "__main__":
    main()