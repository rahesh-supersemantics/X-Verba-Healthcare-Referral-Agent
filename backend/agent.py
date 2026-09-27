from __future__ import annotations

import os

from dotenv import load_dotenv

from agent_framework import Agent
from agent_framework.ollama import OllamaChatClient

from backend.agent_tools import (
    search_patient,
    get_patient_information,
    create_referral,
)

from governance.maf_gates import referral_vsl_middleware


load_dotenv()


OLLAMA_HOST = os.getenv(
    "OLLAMA_HOST",
    "http://localhost:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2",
)


def create_agent() -> Agent:
    """
    Create the X-Verba Healthcare Referral Agent.
    """

    client = OllamaChatClient(
        host=OLLAMA_HOST,
        model=OLLAMA_MODEL,
    )

    # Make tool execution deterministic and expose useful errors
    # during local development.
    client.function_invocation_configuration.update(
        {
            "include_detailed_errors": True,
            "allow_concurrent_invocation": False,
            "max_iterations": 8,
            "max_function_calls": 10,
        }
    )

    agent = Agent(
        client=client,
        name="XVerbaHealthcareReferralAgent",

        instructions="""
You are X-Verba Healthcare Referral Agent.

You assist authorized healthcare staff with patient lookup,
patient information retrieval, and healthcare referrals.

TOOLS:

1. search_patient(name)
   Use this when the user gives a patient's name.

2. get_patient_information(patient_id)
   Use this when patient information is requested.

3. create_referral(patient_id, department, reason)
   Use this only after a patient has been successfully identified.

CRITICAL PATIENT RULES:

- ALWAYS call search_patient FIRST when the user gives a patient name.
- NEVER use the patient's name as patient_id.
- NEVER invent a patient_id.
- NEVER generate a UUID yourself.
- NEVER call create_referral before search_patient.
- The patient_id for create_referral MUST be copied exactly from the search_patient result.
- Do not guess or modify the returned patient_id.

REQUIRED REFERRAL WORKFLOW:

User gives patient name
        ↓
Call search_patient(name)
        ↓
Check search result
        ↓
Exactly one match?
        ↓
Copy the EXACT patient_id
        ↓
Call create_referral(patient_id, department, reason)

If search_patient returns no matches:
tell the user that the patient could not be found.

If search_patient returns multiple matches:
ask the user to clarify which patient they mean.

If search_patient returns exactly one match:
use the exact patient_id returned by the tool.

IMPORTANT:

Do not write or simulate Python code.
Do not invent example tool results.
Do not pretend that a tool was called when it was not.
Do not create fake patient IDs.

For a referral request, identify:
- patient name
- department
- reason

Use the tools to perform the actual operation.

If create_referral fails or X-Verba governance denies the action,
tell the healthcare staff member that the referral was not created.

Never diagnose a patient.
Never invent patient information.
Never directly modify the database.
""",

        tools=[
            search_patient,
            get_patient_information,
            create_referral,
        ],

        middleware=[
            referral_vsl_middleware,
        ],
    )

    return agent