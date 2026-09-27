import pandas as pd
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "processed"


FILES = {
    "patients": "patients.csv",
    "conditions": "conditions.csv",
    "medications": "medications.csv",
    "allergies": "allergies.csv",
    "observations": "observations.csv",
    "encounters": "encounters.csv",
}


def load_data(filename):
    path = DATA_DIR / filename

    if not path.exists():
        print(f"[ERROR] Missing file: {filename}")
        return None

    return pd.read_csv(path)


print("\n======================================")
print("HEALTHCARE DATA VALIDATION")
print("======================================")

data = {}

for name, filename in FILES.items():

    df = load_data(filename)

    if df is None:
        continue

    data[name] = df

    print(f"\n{name.upper()}")
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")


print("\n======================================")
print("PATIENT ID VALIDATION")
print("======================================")

patients = data.get("patients")

if patients is not None:

    patient_ids = set(
        patients["patient_id"]
        .dropna()
        .astype(str)
    )

    print(f"Unique patients: {len(patient_ids)}")

    for name in [
        "conditions",
        "medications",
        "allergies",
        "observations",
        "encounters",
    ]:

        df = data.get(name)

        if df is None or "patient_id" not in df.columns:
            continue

        related_ids = set(
            df["patient_id"]
            .dropna()
            .astype(str)
        )

        orphan_ids = related_ids - patient_ids

        print(
            f"{name}: "
            f"{len(orphan_ids)} orphan patient IDs"
        )


print("\n======================================")
print("MISSING VALUE CHECK")
print("======================================")

for name, df in data.items():

    missing = df.isnull().sum()

    print(f"\n{name}:")

    for column, count in missing.items():

        if count > 0:
            print(f"  {column}: {count} missing")


print("\n======================================")
print("VALIDATION COMPLETE")
print("======================================")