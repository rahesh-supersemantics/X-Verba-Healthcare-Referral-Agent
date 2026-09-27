import json
from pathlib import Path
import csv


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FHIR_DIR = PROJECT_ROOT / "synthea" / "output" / "fhir"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


# ---------------------------------------------------------
# Create directories
# ---------------------------------------------------------

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# Storage
# ---------------------------------------------------------

patients = []
conditions = []
medications = []
allergies = []
observations = []
encounters = []


# ---------------------------------------------------------
# Helper
# ---------------------------------------------------------

def get_patient_name(resource):
    names = resource.get("name", [])

    if not names:
        return ""

    name = names[0]

    given = " ".join(name.get("given", []))
    family = name.get("family", "")

    return f"{given} {family}".strip()


def get_code_display(resource):
    code = resource.get("code", {})

    if "text" in code:
        return code["text"]

    coding = code.get("coding", [])

    if coding:
        return coding[0].get("display", "")

    return ""


# ---------------------------------------------------------
# Process FHIR bundles
# ---------------------------------------------------------

json_files = [
    file
    for file in FHIR_DIR.glob("*.json")
    if not file.name.startswith("hospitalInformation")
    and not file.name.startswith("practitionerInformation")
]


for file_path in json_files:

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            bundle = json.load(file)

    except Exception as error:
        print(f"Skipping {file_path.name}: {error}")
        continue


    patient_id = None


    # -----------------------------------------------------
    # First pass: find Patient
    # -----------------------------------------------------

    for entry in bundle.get("entry", []):

        resource = entry.get("resource", {})

        if resource.get("resourceType") == "Patient":

            patient_id = resource.get("id")

            patients.append({
                "patient_id": patient_id,
                "name": get_patient_name(resource),
                "date_of_birth": resource.get("birthDate"),
                "gender": resource.get("gender")
            })

            break


    if not patient_id:
        continue


    # -----------------------------------------------------
    # Second pass: process resources
    # -----------------------------------------------------

    for entry in bundle.get("entry", []):

        resource = entry.get("resource", {})

        resource_type = resource.get("resourceType")


        # -------------------------------------------------
        # Conditions
        # -------------------------------------------------

        if resource_type == "Condition":

            conditions.append({
                "patient_id": patient_id,
                "condition": get_code_display(resource),
                "status": (
                    resource
                    .get("clinicalStatus", {})
                    .get("coding", [{}])[0]
                    .get("code", "")
                ),
                "onset": resource.get("onsetDateTime", "")
            })


        # -------------------------------------------------
        # Medications
        # -------------------------------------------------

        elif resource_type == "MedicationRequest":

            medication = resource.get("medicationCodeableConcept", {})

            medication_name = ""

            if medication.get("text"):
                medication_name = medication["text"]

            elif medication.get("coding"):
                medication_name = medication["coding"][0].get(
                    "display", ""
                )

            medications.append({
                "patient_id": patient_id,
                "medication": medication_name,
                "status": resource.get("status", "")
            })


        # -------------------------------------------------
        # Allergies
        # -------------------------------------------------

        elif resource_type == "AllergyIntolerance":

            allergy = resource.get("code", {})

            allergy_name = allergy.get("text", "")

            if not allergy_name and allergy.get("coding"):
                allergy_name = allergy["coding"][0].get(
                    "display", ""
                )

            allergies.append({
                "patient_id": patient_id,
                "allergy": allergy_name,
                "status": resource.get("clinicalStatus", {})
                .get("coding", [{}])[0]
                .get("code", "")
            })


        # -------------------------------------------------
        # Observations
        # -------------------------------------------------

        elif resource_type == "Observation":

            value = ""

            if "valueQuantity" in resource:

                quantity = resource["valueQuantity"]

                value = (
                    f"{quantity.get('value', '')} "
                    f"{quantity.get('unit', '')}"
                ).strip()

            elif "valueString" in resource:

                value = resource["valueString"]

            elif "valueCodeableConcept" in resource:

                value = resource[
                    "valueCodeableConcept"
                ].get("text", "")

            observations.append({
                "patient_id": patient_id,
                "type": get_code_display(resource),
                "value": value,
                "date": resource.get("effectiveDateTime", "")
            })


        # -------------------------------------------------
        # Encounters
        # -------------------------------------------------

        elif resource_type == "Encounter":

            encounter_type = ""

            types = resource.get("type", [])

            if types:

                encounter_type = (
                    types[0]
                    .get("coding", [{}])[0]
                    .get("display", "")
                )

            encounters.append({
                "patient_id": patient_id,
                "type": encounter_type,
                "status": resource.get("status", ""),
                "start": (
                    resource
                    .get("period", {})
                    .get("start", "")
                )
            })


# ---------------------------------------------------------
# CSV writer
# ---------------------------------------------------------

def write_csv(filename, rows):

    if not rows:
        return

    output_file = PROCESSED_DIR / filename

    with open(
        output_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=rows[0].keys()
        )

        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------
# Save processed datasets
# ---------------------------------------------------------

write_csv("patients.csv", patients)
write_csv("conditions.csv", conditions)
write_csv("medications.csv", medications)
write_csv("allergies.csv", allergies)
write_csv("observations.csv", observations)
write_csv("encounters.csv", encounters)


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------

print("\n======================================")
print("SYNTHETHEA DATA EXTRACTION COMPLETE")
print("======================================")

print(f"Patients:      {len(patients)}")
print(f"Conditions:    {len(conditions)}")
print(f"Medications:   {len(medications)}")
print(f"Allergies:     {len(allergies)}")
print(f"Observations:  {len(observations)}")
print(f"Encounters:    {len(encounters)}")

print("\nProcessed files:")
print(PROCESSED_DIR)