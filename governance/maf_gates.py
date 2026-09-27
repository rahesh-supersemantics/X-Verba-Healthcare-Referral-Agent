from __future__ import annotations

from typing import Any

from vsl_maf import MAFAdapter, VSLFunctionMiddleware

from governance.policy import REFERRAL_REQUEST_VALID


adapter = MAFAdapter()

referral_pre_node_gate = adapter.compile_pre_node(
    REFERRAL_REQUEST_VALID
)


def referral_candidate_from_context(context: Any) -> dict:
    """
    Convert the MAF tool invocation arguments into
    the candidate format expected by the VSL PreNode.
    """

    return dict(context.arguments)


referral_vsl_middleware = VSLFunctionMiddleware(
    referral_pre_node_gate,
    candidate_input_fn=referral_candidate_from_context,
    function_name="create_referral",
)